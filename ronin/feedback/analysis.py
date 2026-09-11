"""Outcome analytics for closed-loop job application feedback."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List

from loguru import logger

from ronin.db import get_db_manager

POSITIVE_STAGES = {"viewed", "interview_request", "offer"}
RESOLVED_STAGES = {
    "acknowledged",
    "viewed",
    "rejected",
    "interview_request",
    "offer",
    "ghost",
    "other",
}

TITLE_STOPWORDS = {
    "junior",
    "jr",
    "mid",
    "senior",
    "lead",
    "staff",
    "principal",
    "engineer",
    "developer",
    "software",
    "full",
    "stack",
    "ii",
    "iii",
    "iv",
    "the",
    "and",
}


def _rate(successes: int, total: int) -> float:
    return (successes / total) if total else 0.0


def _normalize_title_family(title: str) -> str:
    tokens = re.findall(r"[a-zA-Z]+", (title or "").lower())
    filtered = [
        token for token in tokens if token not in TITLE_STOPWORDS and len(token) > 2
    ]
    if not filtered:
        return "unknown"
    return " ".join(filtered[:2])


def _resolve_stage(row: Dict) -> str:
    stage = str(row.get("outcome_stage") or "").strip().lower()
    if stage:
        return stage

    legacy = str(row.get("outcome") or "").strip().upper()
    mapping = {
        "PENDING": "applied",
        "CALLBACK": "interview_request",
        "INTERVIEW": "interview_request",
        "REJECTION": "rejected",
        "OFFER": "offer",
    }
    return mapping.get(legacy, "applied")


class OutcomeAnalytics:
    """Build aggregate feedback signals from tracked outcomes."""

    def __init__(self, db_manager: object | None = None):
        self.db_manager = db_manager or get_db_manager()
        self._owns_db = db_manager is None

    def close(self) -> None:
        if self._owns_db:
            self.db_manager.close()

    def build_feedback_report(self, min_samples: int = 2) -> Dict:
        """Compute conversion analytics by resume, keyword, and title mapping."""
        try:
            all_rows = self.db_manager.get_applications(limit=0)
            resolved = [
                row for row in all_rows if _resolve_stage(row) in RESOLVED_STAGES
            ]
            outcome_stats = self.db_manager.get_application_outcome_stats()

            report: Dict = {
                "outcome_stats": outcome_stats,
                "resume_performance": [],
                "keyword_performance": [],
                "role_title_mappings": [],
            }

            if not resolved:
                return report

            resume_buckets: Dict[tuple[str, str], Dict[str, int]] = defaultdict(
                lambda: {"total": 0, "positive": 0, "offers": 0}
            )
            keyword_buckets: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"total": 0, "positive": 0, "offers": 0}
            )
            family_totals: Dict[str, int] = defaultdict(int)
            family_positive: Dict[str, int] = defaultdict(int)
            family_profile_totals: Dict[str, Dict[str, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            family_profile_positive: Dict[str, Dict[str, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            profile_archetype: Dict[str, Counter] = defaultdict(Counter)

            for row in resolved:
                stage = _resolve_stage(row)
                is_positive = stage in POSITIVE_STAGES
                is_offer = stage == "offer"

                resume_profile = row.get("resume_profile") or "default"
                resume_archetype = row.get("resume_archetype") or "adaptation"
                key = (resume_profile, resume_archetype)

                resume_buckets[key]["total"] += 1
                resume_buckets[key]["positive"] += 1 if is_positive else 0
                resume_buckets[key]["offers"] += 1 if is_offer else 0
                profile_archetype[resume_profile][resume_archetype] += 1

                keyword = (row.get("matching_keyword") or "").strip().lower()
                if keyword:
                    keyword_buckets[keyword]["total"] += 1
                    keyword_buckets[keyword]["positive"] += 1 if is_positive else 0
                    keyword_buckets[keyword]["offers"] += 1 if is_offer else 0

                family = _normalize_title_family(
                    row.get("job_title") or row.get("title") or ""
                )
                if family != "unknown":
                    family_totals[family] += 1
                    family_positive[family] += 1 if is_positive else 0
                    family_profile_totals[family][resume_profile] += 1
                    family_profile_positive[family][resume_profile] += (
                        1 if is_positive else 0
                    )

            resume_perf: List[Dict] = []
            for (profile, archetype), stats in resume_buckets.items():
                total = stats["total"]
                if total < min_samples:
                    continue
                positive = stats["positive"]
                resume_perf.append(
                    {
                        "resume_profile": profile,
                        "resume_archetype": archetype,
                        "total": total,
                        "positive": positive,
                        "offers": stats["offers"],
                        "positive_rate": _rate(positive, total),
                    }
                )

            resume_perf.sort(
                key=lambda item: (item["positive_rate"], item["total"]),
                reverse=True,
            )

            keyword_perf: List[Dict] = []
            for keyword, stats in keyword_buckets.items():
                total = stats["total"]
                if total < min_samples:
                    continue
                positive = stats["positive"]
                keyword_perf.append(
                    {
                        "keyword": keyword,
                        "total": total,
                        "positive": positive,
                        "offers": stats["offers"],
                        "positive_rate": _rate(positive, total),
                    }
                )

            keyword_perf.sort(
                key=lambda item: (item["positive_rate"], item["total"]),
                reverse=True,
            )

            role_mappings: List[Dict] = []
            for family, total in family_totals.items():
                if total < min_samples:
                    continue

                best_profile = ""
                best_total = 0
                best_positive = 0
                best_rate = 0.0

                for profile, profile_total in family_profile_totals[family].items():
                    profile_positive = family_profile_positive[family].get(profile, 0)
                    profile_rate = _rate(profile_positive, profile_total)
                    if (
                        profile_rate > best_rate
                        or (profile_rate == best_rate and profile_total > best_total)
                        or not best_profile
                    ):
                        best_profile = profile
                        best_total = profile_total
                        best_positive = profile_positive
                        best_rate = profile_rate

                archetype_counts = profile_archetype.get(best_profile, Counter())
                best_archetype = "adaptation"
                if archetype_counts:
                    best_archetype = archetype_counts.most_common(1)[0][0]

                role_mappings.append(
                    {
                        "title_family": family,
                        "family_total": total,
                        "family_positive": family_positive[family],
                        "family_positive_rate": _rate(family_positive[family], total),
                        "best_resume_profile": best_profile,
                        "best_resume_archetype": best_archetype,
                        "best_profile_total": best_total,
                        "best_profile_positive": best_positive,
                        "best_profile_rate": best_rate,
                    }
                )

            role_mappings.sort(
                key=lambda item: (item["best_profile_rate"], item["family_total"]),
                reverse=True,
            )

            report["resume_performance"] = resume_perf
            report["keyword_performance"] = keyword_perf
            report["role_title_mappings"] = role_mappings
            return report

        except Exception as e:
            logger.error(f"Failed to build outcome analytics report: {e}")
            return {
                "outcome_stats": self.db_manager.get_application_outcome_stats(),
                "resume_performance": [],
                "keyword_performance": [],
                "role_title_mappings": [],
            }

    def build_prompt_context(self, max_lines: int = 8, min_samples: int = 2) -> str:
        """Format concise market feedback to inject into job-analysis prompts."""
        report = self.build_feedback_report(min_samples=min_samples)
        outcome_stats = report.get("outcome_stats", {})

        resolved = int(outcome_stats.get("resolved", 0))
        if resolved < min_samples:
            return ""

        lines: list[str] = [
            f"Feedback dataset: {resolved} resolved applications with outcomes.",
        ]

        top_resumes = report.get("resume_performance", [])[:2]
        for row in top_resumes:
            lines.append(
                "Resume signal: "
                f"{row['resume_profile']} ({row['resume_archetype']}) "
                f"{row['positive_rate']:.0%} positive "
                f"({row['positive']}/{row['total']})."
            )

        top_keywords = report.get("keyword_performance", [])[:2]
        for row in top_keywords:
            lines.append(
                "Keyword signal: "
                f"'{row['keyword']}' {row['positive_rate']:.0%} positive "
                f"({row['positive']}/{row['total']})."
            )

        top_roles = report.get("role_title_mappings", [])[:2]
        for row in top_roles:
            lines.append(
                "Role mapping signal: "
                f"'{row['title_family']}' -> {row['best_resume_profile']} "
                f"({row['best_resume_archetype']}) at "
                f"{row['best_profile_rate']:.0%} positive "
                f"({row['best_profile_positive']}/{row['best_profile_total']})."
            )

        lines.append("Treat these as soft priors, not hard constraints.")
        return "\n".join(lines[:max_lines])
