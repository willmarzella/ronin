"""Outcome-weighted gating and ordering for the apply queue.

Replaces two rules that the application history contradicts.

**Gating.** The old gate was ``archetype_score * resume_alignment >= 0.15``.
Both terms are the wrong shape for the job: ``archetype_score`` is a normalised
*share* across the four archetypes (a JD that is unambiguously one archetype
scores high simply for being unambiguous), and ``alignment`` is a per-archetype
resume-quality constant. Multiplying them means throughput depends on how the
resumes happen to embed, not on whether a job is worth applying to — the same
gate passed 313 sub-40-score jobs historically and, after a resume regen moved
the alignment constants, passed nothing at all. The gate now keys on the
analyst score, which is the only term that actually judges the job.

**Ordering.** The queue sorted by raw score descending. Measured over 498
applications with 26 positive outcomes, score is not monotone — sub-40 converts
at 2.2% against roughly 10% for 40-89 — and archetype separates far harder than
score does: fixer 22.0%, operator 5.0%, builder 0.9%, translator 0.0%.

Weights are empirical but shrunk toward the base rate, since several cells are
small (fixer is 9 positives from 41). A raw 22% becomes 15.6%; a raw 0% becomes
2.0% rather than a weight of zero that would permanently starve an archetype and
prevent it ever earning evidence back. They are config-overridable and should be
re-derived as outcomes accumulate — see ``ronin feedback sync``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Minimum analyst score for a job to enter the apply queue. Sub-40 converted at
# 2.2% against ~10% above it, while consuming 63% of all applications.
DEFAULT_MIN_SCORE = 40.0

# Multipliers relative to the 5.2% base callback rate, shrunk toward it.
DEFAULT_ARCHETYPE_WEIGHTS: Dict[str, float] = {
    "fixer": 2.99,
    "adaptation": 1.18,
    "operator": 0.97,
    "translator": 0.38,
    "builder": 0.31,
}

DEFAULT_SENIORITY_WEIGHTS: Dict[str, float] = {
    "senior": 1.93,
    "unknown": 1.18,
    "junior": 0.83,
    "mid": 0.72,
    "lead": 0.67,
}

# Applied to any key absent from the tables above, so a newly introduced
# archetype or seniority label is treated as average rather than dropped.
NEUTRAL_WEIGHT = 1.0


class RankingPolicy:
    """Resolved gating and ordering policy for one apply run."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        app_cfg = (config or {}).get("application") or {}
        ranking_cfg = app_cfg.get("ranking") or {}

        self.enabled = bool(ranking_cfg.get("enabled", True))
        self.min_score = float(app_cfg.get("min_score", DEFAULT_MIN_SCORE))
        self.archetype_weights = self._merge(
            DEFAULT_ARCHETYPE_WEIGHTS, ranking_cfg.get("archetype_weights")
        )
        self.seniority_weights = self._merge(
            DEFAULT_SENIORITY_WEIGHTS, ranking_cfg.get("seniority_weights")
        )

    @staticmethod
    def _merge(defaults: Dict[str, float], override: Any) -> Dict[str, float]:
        merged = dict(defaults)
        if isinstance(override, dict):
            for key, value in override.items():
                try:
                    merged[str(key).strip().lower()] = float(value)
                except (TypeError, ValueError):
                    continue
        return merged

    def priority(self, job: Dict[str, Any]) -> float:
        """Expected-value ordering key. Higher applies first."""
        score = _as_float(job.get("score"))
        if not self.enabled:
            return score

        archetype = str(job.get("archetype_primary") or "").strip().lower()
        seniority = str(job.get("seniority_level") or "").strip().lower()
        return round(
            score
            * self.archetype_weights.get(archetype, NEUTRAL_WEIGHT)
            * self.seniority_weights.get(seniority, NEUTRAL_WEIGHT),
            3,
        )

    def is_below_bar(self, job: Dict[str, Any]) -> bool:
        """True when a job should stay market-intel rather than enter the queue."""
        if not self.enabled:
            return False
        return _as_float(job.get("score")) < self.min_score


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
