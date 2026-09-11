"""Tests for outcome-weighted apply gating and ordering (ronin/ranking.py)."""

from __future__ import annotations

from ronin.ranking import DEFAULT_ARCHETYPE_WEIGHTS, DEFAULT_MIN_SCORE, RankingPolicy


def _job(score, archetype="operator", seniority="mid"):
    return {
        "score": score,
        "archetype_primary": archetype,
        "seniority_level": seniority,
    }


def test_gate_uses_score_not_resume_alignment() -> None:
    p = RankingPolicy({})
    assert p.is_below_bar(_job(39))
    assert not p.is_below_bar(_job(40))
    assert not p.is_below_bar(_job(80))
    # A missing or unparseable score must not sneak through the floor.
    assert p.is_below_bar({"score": None})
    assert p.is_below_bar({"score": "not a number"})
    assert p.is_below_bar({})


def test_outcome_weights_can_outrank_a_higher_raw_score() -> None:
    p = RankingPolicy({})
    # The whole point: raw score is not monotone against callbacks. A senior
    # fixer at 62 beat a mid builder at 80 in the application history.
    assert p.priority(_job(62, "fixer", "senior")) > p.priority(
        _job(80, "builder", "mid")
    )
    # Within one archetype and seniority, score still orders.
    assert p.priority(_job(80)) > p.priority(_job(60))


def test_unknown_labels_are_treated_as_average_not_dropped() -> None:
    p = RankingPolicy({})
    # A new archetype must score like an average one, or it can never earn
    # evidence to justify a weight.
    assert p.priority(_job(50, "brand_new_archetype", "unheard_of")) == 50.0


def test_no_weight_is_zero() -> None:
    # A zero weight permanently starves an archetype: it would never be applied
    # to, so it could never generate the outcomes needed to recover.
    assert all(w > 0 for w in DEFAULT_ARCHETYPE_WEIGHTS.values())
    assert DEFAULT_ARCHETYPE_WEIGHTS["translator"] > 0  # raw rate was 0.0%


def test_disabled_policy_restores_raw_score_ordering_and_opens_the_gate() -> None:
    p = RankingPolicy({"application": {"ranking": {"enabled": False}}})
    assert p.priority(_job(80, "builder", "mid")) == 80.0
    assert p.priority(_job(62, "fixer", "senior")) == 62.0
    # Gating reverts to the caller's legacy queue_threshold path.
    assert not p.is_below_bar(_job(10))


def test_config_overrides_merge_over_defaults() -> None:
    p = RankingPolicy(
        {
            "application": {
                "min_score": 55,
                "ranking": {"archetype_weights": {"builder": 4.0}},
            }
        }
    )
    assert p.min_score == 55
    assert p.is_below_bar(_job(54))
    assert p.archetype_weights["builder"] == 4.0
    # Untouched keys keep their defaults rather than being wiped by the merge.
    assert p.archetype_weights["fixer"] == DEFAULT_ARCHETYPE_WEIGHTS["fixer"]
    assert p.seniority_weights["senior"] == 1.93


def test_bad_config_values_are_ignored_not_fatal() -> None:
    p = RankingPolicy(
        {"application": {"ranking": {"archetype_weights": {"fixer": "heaps"}}}}
    )
    assert p.archetype_weights["fixer"] == DEFAULT_ARCHETYPE_WEIGHTS["fixer"]
    assert p.min_score == DEFAULT_MIN_SCORE


if __name__ == "__main__":
    test_gate_uses_score_not_resume_alignment()
    test_outcome_weights_can_outrank_a_higher_raw_score()
    test_unknown_labels_are_treated_as_average_not_dropped()
    test_no_weight_is_zero()
    test_disabled_policy_restores_raw_score_ordering_and_opens_the_gate()
    test_config_overrides_merge_over_defaults()
    test_bad_config_values_are_ignored_not_fatal()
    print("test_ranking: all assertions passed")
