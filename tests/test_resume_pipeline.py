"""Tests for the source-driven resume regeneration pipeline (pure functions)."""

from __future__ import annotations

from pathlib import Path

from ronin.resume_pipeline import (
    _MAX_HEADER,
    DEFAULT_REGEN_VARIANTS,
    POLE_VARIANT,
    VARIANT_LENSES,
    ResumeRegenError,
    _build_variant_doc,
    _metric_tokens,
    _render_summary,
    _source_metric_pool,
    _validate_variant,
    regen,
    tune_variant,
)
from ronin.seek.profile_updater import SeekCareerEntry, SeekProfileUpdater


def _source():
    return {
        "personal": {"header": "Senior Data Engineer | AWS"},
        "career_summary_template": "Data engineer with {aws_exp_years}+ years delivering $150K savings and 60% cost cuts.",
        "experience_start_dates": {"aws": 2019},
        "experience_freelance": [
            {
                "company": "Stygian Consulting",
                "location": "Melbourne",
                "title": "Founder",
                "period": "2022 -- Present",
                "responsibilities": "Consulting on AWS and Snowflake.",
                "achievements": ["Cut spend 25% via auto-suspend"],
            }
        ],
        "experience_full_time": [
            {
                "company": "SAI360",
                "location": "Melbourne",
                "title": "Solutions Engineer",
                "de_title": "Data Integration Engineer",
                "period": "2024",
                "responsibilities": "Integration design.",
                "achievements": ["Built demo environments"],
            }
        ],
    }


def _good_result():
    return {
        "career_summary_template": "Data engineer with {aws_exp_years}+ years cutting cost 60% and saving $150K.",
        "roles": {
            "Stygian Consulting": {
                "responsibilities": "Cost-focused AWS/Snowflake consulting.",
                "achievements": ["Reduced credit consumption 25% through governance"],
            },
            "SAI360": {
                "responsibilities": "Data integration for compliance workloads.",
                "achievements": ["Delivered reusable integration designs"],
            },
        },
    }


def test_metric_tokens_and_pool() -> None:
    pool = _source_metric_pool(_source())
    assert "$150k" in pool and "60%" in pool and "25%" in pool
    # Truthful line traces to pool; invented does not.
    assert not (_metric_tokens("saved $150K at 60% reduction") - pool)
    assert _metric_tokens("saved $900K at 95% reduction") - pool


def test_build_variant_doc_uses_de_title_and_copies_structure() -> None:
    src = _source()
    roles = src["experience_freelance"] + src["experience_full_time"]
    doc = _build_variant_doc(src, roles, _good_result(), "c", Path("/nonexistent.yml"))
    sai = next(r for r in doc["experience_full_time"] if r["company"] == "SAI360")
    # de_title presented, dates/company copied from source, prose from LLM.
    assert sai["title"] == "Data Integration Engineer"
    assert sai["period"] == "2024"
    assert "integration" in sai["responsibilities"].lower()


def test_validate_passes_on_truthful_output() -> None:
    src = _source()
    roles = src["experience_freelance"] + src["experience_full_time"]
    doc = _build_variant_doc(src, roles, _good_result(), "c", Path("/nonexistent.yml"))
    _validate_variant(src, doc)  # must not raise


def test_validate_rejects_invented_metric() -> None:
    src = _source()
    roles = src["experience_freelance"] + src["experience_full_time"]
    bad = _good_result()
    bad["roles"]["SAI360"]["achievements"] = ["Saved $2M in ARR (invented)"]
    doc = _build_variant_doc(src, roles, bad, "c", Path("/nonexistent.yml"))
    try:
        _validate_variant(src, doc)
        raise AssertionError("expected ResumeRegenError for invented metric")
    except ResumeRegenError as exc:
        assert "invented metric" in str(exc)


def test_validate_rejects_role_mismatch() -> None:
    src = _source()
    roles = src["experience_freelance"] + src["experience_full_time"]
    doc = _build_variant_doc(src, roles, _good_result(), "c", Path("/nonexistent.yml"))
    doc["experience_full_time"] = []  # drop a real role
    try:
        _validate_variant(src, doc)
        raise AssertionError("expected ResumeRegenError for role mismatch")
    except ResumeRegenError as exc:
        assert "role set mismatch" in str(exc)


def test_pole_variant_is_never_machine_written() -> None:
    # c.yml is hand-owned: both the single-variant and the batch entry points
    # must refuse it before any LLM call is made.
    try:
        tune_variant({}, None, variant=POLE_VARIANT)
        raise AssertionError("expected ResumeRegenError for frozen pole")
    except ResumeRegenError as exc:
        assert "hand-owned pole" in str(exc)

    try:
        regen(variants=["builder", POLE_VARIANT])
        raise AssertionError("expected ResumeRegenError for frozen pole in batch")
    except ResumeRegenError as exc:
        assert "hand-owned pole" in str(exc)

    assert POLE_VARIANT not in VARIANT_LENSES
    assert POLE_VARIANT not in DEFAULT_REGEN_VARIANTS


def test_tune_rejects_variant_without_a_lens() -> None:
    try:
        tune_variant({}, None, variant="industrial")
        raise AssertionError("expected ResumeRegenError for lens-less variant")
    except ResumeRegenError as exc:
        assert "no lens defined" in str(exc)


def test_header_is_variant_specific_and_capped() -> None:
    src = _source()
    roles = src["experience_freelance"] + src["experience_full_time"]

    result = _good_result()
    result["header"] = "Data Engineer | Reliability & Operations | AWS • dbt"
    doc = _build_variant_doc(src, roles, result, "operator", Path("/nonexistent.yml"))
    assert doc["personal"]["header"] == result["header"]
    # Contact details still come from source, and source is not mutated.
    assert src["personal"]["header"] == "Senior Data Engineer | AWS"
    _validate_variant(src, doc)

    # No header from the LLM leaves source's headline in place.
    fallback = _build_variant_doc(
        src, roles, _good_result(), "operator", Path("/x.yml")
    )
    assert fallback["personal"]["header"] == "Senior Data Engineer | AWS"

    result["header"] = "Data Engineer | " + "x" * _MAX_HEADER
    doc = _build_variant_doc(src, roles, result, "operator", Path("/nonexistent.yml"))
    try:
        _validate_variant(src, doc)
        raise AssertionError("expected ResumeRegenError for over-long header")
    except ResumeRegenError as exc:
        assert "chars >" in str(exc)  # recoverable marker: tune_variant retries


def test_render_summary_resolves_placeholder() -> None:
    out = _render_summary(
        {"experience_start_dates": {"aws": 2019}}, "{aws_exp_years}+ years"
    )
    assert "{aws" not in out and out[0].isdigit()


def test_seek_matcher_bidirectional_and_skips_pending() -> None:
    rows = [
        {
            "auto_id": "e0",
            "text": "Found in resumé\nContractor\nStygian",
            "pending": True,
        },
        {"auto_id": "e1", "text": "Data Engineer\nWesfarmers", "pending": False},
        {"auto_id": "e2", "text": "Founder\nStygian Consulting", "pending": False},
    ]
    entries = [
        SeekCareerEntry(title="X", company="Wesfarmers OneDigital"),  # longer than row
        SeekCareerEntry(title="Y", company="Stygian Consulting"),
    ]
    u = SeekProfileUpdater(config={})
    matched = u._match_entries_to_rows(entries, rows)
    got = {e.company: r["auto_id"] for e, r in matched}
    assert got.get("Wesfarmers OneDigital") == "e1"  # bidirectional first-word match
    assert got.get("Stygian Consulting") == "e2"  # confirmed row, not pending e0
    assert "e0" not in got.values()


if __name__ == "__main__":
    test_metric_tokens_and_pool()
    test_build_variant_doc_uses_de_title_and_copies_structure()
    test_validate_passes_on_truthful_output()
    test_validate_rejects_invented_metric()
    test_validate_rejects_role_mismatch()
    test_pole_variant_is_never_machine_written()
    test_tune_rejects_variant_without_a_lens()
    test_header_is_variant_specific_and_capped()
    test_render_summary_resolves_placeholder()
    test_seek_matcher_bidirectional_and_skips_pending()
    print("test_resume_pipeline: all assertions passed")
