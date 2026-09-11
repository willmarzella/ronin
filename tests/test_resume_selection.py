"""Tests for custom-resume selection (Profile.select_custom_resume).

The four embedding archetypes only describe data-engineering JD shapes. Two
kinds of resume override them, and they are matched by different rules:
role cuts on title, register cuts on work type + keyword bias. These tests pin
the boundary between them, because collapsing the two lets the role cut match
on body text and swallow the queue.
"""

from __future__ import annotations

from ronin.analyzer.archetype_classifier import is_excluded_title
from ronin.profile import Profile, ResumeProfile, ResumeUseWhen


def _profile() -> Profile:
    """A profile exercising both matcher kinds.

    ``role_cut`` is a stand-in, not a live resume — the solutions_engineer role
    is retired. The role-cut mechanism itself is still load-bearing, so it stays
    under test with a synthetic fixture.
    """
    return Profile(
        resumes=[
            # Register cut: no title patterns, opts in via keyword_bias.
            ResumeProfile(
                name="contract_aggressive",
                file="c.txt",
                keyword_bias=["finops", "cost optimisation", "cloud spend"],
                use_when=ResumeUseWhen(job_types=["contract", "consulting"]),
            ),
            # Role cut: matched on title only.
            ResumeProfile(
                name="role_cut",
                file="role_cut.txt",
                role_title_patterns=["integration engineer", "platform specialist"],
                keyword_bias=["discovery", "demo", "stakeholder"],
                use_when=ResumeUseWhen(job_types=["permanent"]),
            ),
            # Neither signal — must never be auto-selected.
            ResumeProfile(
                name="growth_honest",
                file="b.txt",
                use_when=ResumeUseWhen(job_types=["permanent", "full-time"]),
            ),
            ResumeProfile(name="builder", file="builder.txt"),
        ]
    )


def test_role_cut_matches_on_title_only() -> None:
    p = _profile()
    assert (
        p.select_custom_resume(
            job_title="Senior Integration Engineer", work_type="permanent"
        )
        == "role_cut"
    )
    # The same words in the BODY of an ordinary data-engineering ad must not
    # pull the role cut in — this is what made it swallow ~45% of the queue.
    assert (
        p.select_custom_resume(
            job_title="Data Engineer",
            job_description=(
                "Run discovery with stakeholder groups, build a demo, and "
                "support the integration engineer team."
            ),
            work_type="permanent",
        )
        is None
    )


def test_register_cut_needs_work_type_and_a_keyword() -> None:
    p = _profile()
    # Work type (2.0) + one keyword (1.0) clears the 3.0 threshold.
    assert (
        p.select_custom_resume(
            job_title="Data Engineer",
            job_description="Drive FinOps and cloud spend reduction across the platform.",
            work_type="contract",
        )
        == "contract_aggressive"
    )
    # Work type alone (2.0) is not enough, or every contract ad would take it.
    assert (
        p.select_custom_resume(
            job_title="Data Engineer",
            job_description="Build pipelines in dbt and Snowflake.",
            work_type="contract",
        )
        is None
    )
    # Keywords alone, wrong work type: still short of the threshold.
    assert (
        p.select_custom_resume(
            job_title="Data Engineer",
            job_description="Some finops awareness helps.",
            work_type="permanent",
        )
        is None
    )


def test_resume_without_title_patterns_or_keywords_is_never_selected() -> None:
    p = _profile()
    # growth_honest matches job_types permanent + full-time and nothing else.
    for work_type in ("permanent", "full-time"):
        picked = p.select_custom_resume(
            job_title="Data Engineer",
            job_description="Greenfield platform launch, scale the team.",
            work_type=work_type,
        )
        assert picked != "growth_honest", f"{work_type} wrongly took growth_honest"


def test_archetype_resumes_are_never_returned_as_custom() -> None:
    p = _profile()
    picked = p.select_custom_resume(
        job_title="Data Engineer", job_description="Build things.", work_type="contract"
    )
    assert picked in (None, "contract_aggressive")


def test_title_match_wins_over_a_scoring_register_cut() -> None:
    p = _profile()
    # A contract role-cut ad full of FinOps words is still a role problem.
    picked = p.select_custom_resume(
        job_title="Platform Specialist",
        job_description="Own cloud spend and cost optimisation conversations.",
        work_type="contract",
    )
    assert picked == "role_cut"


def test_empty_profile_and_blank_title_are_safe() -> None:
    assert Profile(resumes=[]).select_custom_resume(job_title="Data Engineer") is None
    p = _profile()
    assert (
        p.select_custom_resume(job_title="", job_description="", work_type="") is None
    )


def test_retired_roles_are_excluded_by_title() -> None:
    for title in (
        "Senior Solutions Engineer",
        "Forward Deployed AI Engineer",
        "Data Solutions Architect - Microsoft stack",
        "Technical Sales Representative (Industrial Products)",
    ):
        assert is_excluded_title(title), f"{title!r} should be excluded"

    # Data-engineering titles must survive — the markers are substrings, so an
    # over-broad entry here would silently drain the queue.
    for title in (
        "Senior Data Engineer",
        "Data Platform Engineer",
        "Analytics Engineer",
        "Data Architect",
        "Lead Data Modeller",
    ):
        assert not is_excluded_title(title), f"{title!r} should not be excluded"

    assert not is_excluded_title("")


if __name__ == "__main__":
    test_role_cut_matches_on_title_only()
    test_register_cut_needs_work_type_and_a_keyword()
    test_resume_without_title_patterns_or_keywords_is_never_selected()
    test_archetype_resumes_are_never_returned_as_custom()
    test_title_match_wins_over_a_scoring_register_cut()
    test_empty_profile_and_blank_title_are_safe()
    test_retired_roles_are_excluded_by_title()
    print("test_resume_selection: all assertions passed")
