"""Market drift detection and resume staleness checks."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from loguru import logger

from ronin.analyzer.archetype_classifier import ArchetypeClassifier
from ronin.db import get_db_manager

ARCHETYPES = ["builder", "fixer", "operator", "translator"]
SHIFT_THRESHOLD = 0.05
STALENESS_THRESHOLD = 0.08
MIN_REWRITE_INTERVAL_DAYS = 21


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _mean_vector(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    length = len(vectors[0])
    total = [0.0] * length
    for vector in vectors:
        if len(vector) != length:
            continue
        for idx, value in enumerate(vector):
            total[idx] += value
    return [value / len(vectors) for value in total]


class DriftEngine:
    """Compute market centroid movement and rewrite triggers."""

    def __init__(self, db_manager: Optional[object] = None) -> None:
        self.db = db_manager or get_db_manager()
        self._owns_db = db_manager is None
        self.classifier = ArchetypeClassifier(enable_embeddings=True)

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def compute_centroids(self, window_days: int = 30, min_jd_count: int = 5) -> Dict:
        """Compute and store rolling centroids by archetype."""
        today = date.today()
        window_start = today - timedelta(days=max(1, window_days))
        summary = {"computed": 0, "skipped": 0}

        for archetype in ARCHETYPES:
            embeddings = self.db.get_embeddings_for_archetype_window(
                archetype=archetype,
                window_start=window_start.isoformat(),
                window_end=today.isoformat(),
            )
            if len(embeddings) < min_jd_count:
                summary["skipped"] += 1
                continue

            centroid = _mean_vector(embeddings)
            previous = self.db.get_most_recent_centroid(archetype)
            shift = 0.0
            if previous and previous.get("centroid_vector"):
                shift = 1 - _cosine_similarity(centroid, previous["centroid_vector"])

            ok = self.db.store_market_centroid(
                archetype=archetype,
                window_start=window_start.isoformat(),
                window_end=today.isoformat(),
                centroid_vector=centroid,
                jd_count=len(embeddings),
                shift_from_previous=shift,
            )
            if ok:
                summary["computed"] += 1

        return summary

    def check_market_shift(self, threshold: float = SHIFT_THRESHOLD) -> List[Dict]:
        """Create market_shift alerts when centroid movement exceeds threshold."""
        created: List[Dict] = []
        for archetype in ARCHETYPES:
            latest = self.db.get_most_recent_centroid(archetype)
            prev = self.db.get_previous_centroid(archetype)
            if not latest or not prev:
                continue
            shift = float(latest.get("shift_from_previous") or 0.0)
            if shift <= threshold:
                continue

            gained, lost = self.compute_term_drift(
                prev.get("centroid_vector") or [],
                latest.get("centroid_vector") or [],
            )
            alert_id = self.db.create_drift_alert(
                archetype=archetype,
                alert_type="market_shift",
                metric_value=shift,
                threshold_value=threshold,
                details={
                    "gained_terms": gained[:10],
                    "lost_terms": lost[:10],
                    "jd_count": latest.get("jd_count", 0),
                    "window": (
                        f"{latest.get('window_start')} to {latest.get('window_end')}"
                    ),
                },
            )
            if alert_id:
                created.append(
                    {
                        "id": alert_id,
                        "archetype": archetype,
                        "shift": shift,
                        "gained_terms": gained[:10],
                        "lost_terms": lost[:10],
                    }
                )
        return created

    def check_resume_staleness(
        self, threshold: float = STALENESS_THRESHOLD
    ) -> List[Dict]:
        """Create resume_stale alerts when variant is far from market centroid."""
        created: List[Dict] = []
        for archetype in ARCHETYPES:
            variant = self.db.get_resume_variant(archetype)
            latest_centroid = self.db.get_most_recent_centroid(archetype)
            if not variant or not latest_centroid:
                continue

            variant_embedding = variant.get("embedding_vector")
            if not variant_embedding and variant.get("file_path"):
                try:
                    with open(variant["file_path"], "r", encoding="utf-8") as handle:
                        variant_embedding = self.classifier.embed_text(handle.read())
                except Exception as exc:
                    logger.debug(
                        f"Could not derive embedding for {archetype} resume variant: {exc}"
                    )

            centroid = latest_centroid.get("centroid_vector") or []
            distance = 1 - _cosine_similarity(variant_embedding or [], centroid)
            if distance <= threshold:
                continue

            alert_id = self.db.create_drift_alert(
                archetype=archetype,
                alert_type="resume_stale",
                metric_value=distance,
                threshold_value=threshold,
                details={
                    "current_alignment": variant.get("alignment_score"),
                    "last_rewritten": variant.get("last_rewritten"),
                    "commit_hash": variant.get("current_commit_hash"),
                },
            )
            if alert_id:
                created.append(
                    {
                        "id": alert_id,
                        "archetype": archetype,
                        "distance": round(distance, 4),
                    }
                )
        return created

    def check_rewrite_triggers(
        self, min_interval_days: int = MIN_REWRITE_INTERVAL_DAYS
    ) -> List[Dict]:
        """Generate rewrite_triggered alerts when market+stale conditions co-occur."""
        triggered: List[Dict] = []
        for archetype in ARCHETYPES:
            variant = self.db.get_resume_variant(archetype)
            if variant and variant.get("last_rewritten"):
                try:
                    last_date = datetime.fromisoformat(
                        str(variant["last_rewritten"])
                    ).date()
                    days_since = (date.today() - last_date).days
                    if days_since < min_interval_days:
                        continue
                except Exception:
                    pass

            market_alert = self.db.get_recent_unacknowledged_alert(
                archetype=archetype,
                alert_type="market_shift",
            )
            stale_alert = self.db.get_recent_unacknowledged_alert(
                archetype=archetype,
                alert_type="resume_stale",
            )
            if not market_alert or not stale_alert:
                continue

            report = self.generate_rewrite_report(
                archetype=archetype,
                market_alert=market_alert,
                stale_alert=stale_alert,
            )
            alert_id = self.db.create_drift_alert(
                archetype=archetype,
                alert_type="rewrite_triggered",
                metric_value=float(stale_alert.get("metric_value") or 0.0),
                threshold_value=float(stale_alert.get("threshold_value") or 0.0),
                details=report,
            )
            if alert_id:
                self.db.acknowledge_alert(int(market_alert["id"]))
                self.db.acknowledge_alert(int(stale_alert["id"]))
                triggered.append(
                    {
                        "id": alert_id,
                        "archetype": archetype,
                        "report": report,
                    }
                )
        return triggered

    def generate_rewrite_report(
        self,
        archetype: str,
        market_alert: Dict,
        stale_alert: Dict,
    ) -> Dict:
        """Build rewrite recommendation payload for alerts table."""
        market_details = market_alert.get("details", {})
        stale_details = stale_alert.get("details", {})
        gained = market_details.get("gained_terms", [])
        lost = market_details.get("lost_terms", [])
        return {
            "archetype": archetype,
            "recommendation": "rewrite",
            "market_shift": market_alert.get("metric_value"),
            "resume_distance": stale_alert.get("metric_value"),
            "terms_gaining": gained,
            "terms_declining": lost,
            "current_resume_version": stale_details.get("commit_hash"),
            "last_rewritten": stale_details.get("last_rewritten"),
            "suggested_focus": (
                f"Market for {archetype} roles is shifting towards: "
                f"{', '.join(gained[:5])}. "
                f"Consider de-emphasising: {', '.join(lost[:5])}."
            ),
        }

    def compute_term_drift(
        self,
        old_centroid: List[float],
        new_centroid: List[float],
    ) -> Tuple[List[str], List[str]]:
        """Estimate gained/lost terms by similarity delta to centroids."""
        reference_terms = self._build_reference_terms()
        if not reference_terms:
            return [], []

        deltas: List[Tuple[str, float]] = []
        for term in reference_terms:
            term_embedding = self.classifier.embed_text(term)
            old_sim = _cosine_similarity(term_embedding, old_centroid)
            new_sim = _cosine_similarity(term_embedding, new_centroid)
            deltas.append((term, new_sim - old_sim))

        deltas.sort(key=lambda item: item[1], reverse=True)
        gained = [term for term, delta in deltas if delta > 0.02]
        lost = [term for term, delta in deltas if delta < -0.02]
        return gained, lost

    def _build_reference_terms(self, limit: int = 200) -> List[str]:
        """Build reference JD vocabulary from persisted job descriptions."""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                SELECT description
                FROM jobs
                WHERE description IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 500
            """
            )
            counter: Counter = Counter()
            for row in cursor.fetchall():
                if isinstance(row, dict):
                    text = (row.get("description") or "").lower()
                else:
                    try:
                        text = (row[0] or "").lower()
                    except Exception:
                        text = str(row).lower()
                terms = re.findall(r"[a-z][a-z\-]{3,}", text)
                counter.update(terms)
            return [term for term, _ in counter.most_common(limit)]
        except Exception as exc:
            logger.debug(f"Unable to build reference terms for drift: {exc}")
            return []


def run_weekly_drift_jobs(db_manager: Optional[object] = None) -> Dict:
    """Convenience orchestrator for weekly centroid + alert pipeline."""
    engine = DriftEngine(db_manager=db_manager)
    try:
        centroid = engine.compute_centroids()
        market_shift = engine.check_market_shift()
        stale = engine.check_resume_staleness()
        rewrite = engine.check_rewrite_triggers()
        return {
            "centroids": centroid,
            "market_shift_alerts": market_shift,
            "resume_stale_alerts": stale,
            "rewrite_triggers": rewrite,
        }
    finally:
        engine.close()
