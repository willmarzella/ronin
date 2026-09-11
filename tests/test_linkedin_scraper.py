"""Tests for LinkedIn scraper URL filter construction."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from ronin.scraper.linkedin import LinkedInScraper


def _base_config():
    return {
        "search": {
            "keywords": ['"Data engineer"-or-"platform engineer"'],
            "location": "Victoria-VIC",
            "date_range": 7,
        },
        "scraping": {
            "delay_seconds": 0,
            "timeout_seconds": 5,
            "quick_apply_only": True,
        },
        "boards": {
            "linkedin": {
                "enabled": True,
                "page_size": 25,
                "max_pages": 40,
                "filters": {
                    "easy_apply_only": True,
                    "job_types": ["full_time", "contract"],
                    "experience_levels": ["associate", "mid_senior"],
                    "workplace_types": ["remote", "hybrid"],
                    "distance_km": 25,
                    "sort_by": "DD",
                },
            }
        },
    }


def test_build_search_url_includes_structured_filters() -> None:
    scraper = LinkedInScraper(_base_config())
    url = scraper.build_search_url(start=50)
    query = parse_qs(urlparse(url).query)

    assert query.get("start", [""])[0] == "50"
    assert query.get("count", [""])[0] == "25"
    assert query.get("f_AL", [""])[0] == "true"
    assert query.get("f_JT", [""])[0] == "F,C"
    assert query.get("f_E", [""])[0] == "3,4"
    assert query.get("f_WT", [""])[0] == "2,3"
    assert query.get("distance", [""])[0] == "25"
    assert query.get("sortBy", [""])[0] == "DD"
    assert query.get("f_TPR", [""])[0].startswith("r")


def test_build_search_url_ignores_invalid_filter_values() -> None:
    cfg = _base_config()
    cfg["boards"]["linkedin"]["filters"] = {
        "job_types": ["bad_code"],
        "experience_levels": ["unknown"],
        "workplace_types": ["wtf"],
        "sort_by": "oops",
    }
    scraper = LinkedInScraper(cfg)
    url = scraper.build_search_url(start=0)
    query = parse_qs(urlparse(url).query)

    assert "f_JT" not in query
    assert "f_E" not in query
    assert "f_WT" not in query
    assert query.get("sortBy", [""])[0] == "DD"


def test_easy_apply_filter_omitted_when_disabled() -> None:
    cfg = _base_config()
    cfg["boards"]["linkedin"]["filters"]["easy_apply_only"] = False
    scraper = LinkedInScraper(cfg)
    query = parse_qs(urlparse(scraper.build_search_url(start=0)).query)

    assert "f_AL" not in query


def test_keyword_translation_to_linkedin_boolean() -> None:
    assert (
        LinkedInScraper._to_linkedin_keywords('"data engineer"-or-"ml engineer"')
        == '"data engineer" OR "ml engineer"'
    )
    # Unquoted input passes through untouched.
    assert LinkedInScraper._to_linkedin_keywords("plain words") == "plain words"


def test_location_translation() -> None:
    assert LinkedInScraper._to_linkedin_location("All-Australia") == "Australia"
    assert (
        LinkedInScraper._to_linkedin_location("Victoria-VIC") == "Victoria, Australia"
    )
    assert (
        LinkedInScraper._to_linkedin_location("Melbourne-VIC") == "Melbourne, Australia"
    )
    assert LinkedInScraper._to_linkedin_location("Sydney") == "Sydney"


def test_job_id_prefix_roundtrip() -> None:
    assert LinkedInScraper._extract_job_id("4012345678") == "li-4012345678"
    assert LinkedInScraper._extract_job_id("li-4012345678") == "li-4012345678"
    assert LinkedInScraper._strip_job_id_prefix("li-4012345678") == "4012345678"
    assert LinkedInScraper._strip_job_id_prefix("4012345678") == "4012345678"


_CARD = """
<div class="base-card" data-entity-urn="urn:li:jobPosting:4012345678">
  <a class="base-card__full-link" href="https://au.linkedin.com/jobs/view/data-engineer-at-acme-4012345678"></a>
  <h3 class="base-search-card__title">Senior Data Engineer</h3>
  <h4 class="base-search-card__subtitle">Acme</h4>
  <span class="job-search-card__location">Melbourne, VIC</span>
  <time class="job-search-card__listdate" datetime="2026-07-29">2 days ago</time>
</div>
"""

_CARD_NO_DATE = _CARD.replace(
    '<time class="job-search-card__listdate" datetime="2026-07-29">2 days ago</time>',
    "",
)


def _card(html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser").find("div", class_="base-card")


def test_preview_card_captures_the_posting_date() -> None:
    scraper = LinkedInScraper(_base_config())
    info = scraper.extract_job_info(_card(_CARD))
    assert info is not None
    # The card is the only source of a real posting date — the guest detail
    # endpoint has no <time>, so losing this makes every job look brand new and
    # exempt from expire_after_days.
    assert info["posted_at"] == "2026-07-29"
    assert info["job_id"] == "li-4012345678"


def test_preview_card_without_a_date_reports_empty_not_now() -> None:
    scraper = LinkedInScraper(_base_config())
    info = scraper.extract_job_info(_card(_CARD_NO_DATE))
    assert info is not None
    # Empty, never a fabricated timestamp: the DB layer owns the fallback so a
    # missing date stays distinguishable from a real one.
    assert info["posted_at"] == ""


def test_scrape_loop_prefers_the_card_date_over_detail_output() -> None:
    scraper = LinkedInScraper(_base_config())
    scraper.quick_apply_only = False
    preview = {"job_id": "li-1", "title": "Data Engineer", "posted_at": "2026-07-29"}
    scraper.get_job_previews = lambda: [preview]
    scraper.get_job_details = lambda _job_id: {
        "description": "x",
        "quick_apply": False,
        "apply_type": "external",
        "created_at": "",
    }
    jobs = scraper.scrape_jobs()
    assert jobs and jobs[0]["created_at"] == "2026-07-29"


if __name__ == "__main__":
    test_preview_card_captures_the_posting_date()
    test_preview_card_without_a_date_reports_empty_not_now()
    test_scrape_loop_prefers_the_card_date_over_detail_output()
    test_build_search_url_includes_structured_filters()
    test_build_search_url_ignores_invalid_filter_values()
    test_easy_apply_filter_omitted_when_disabled()
    test_keyword_translation_to_linkedin_boolean()
    test_location_translation()
    test_job_id_prefix_roundtrip()
    print("test_linkedin_scraper: all assertions passed")
