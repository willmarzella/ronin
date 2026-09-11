"""LinkedIn guest job scraper.

This scraper uses public LinkedIn jobs-guest endpoints for discovery and
market-intelligence ingestion. Applications are not automated for LinkedIn.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup
from loguru import logger

from ronin.scraper.base import BaseScraper


class LinkedInScraper(BaseScraper):
    """Scraper for LinkedIn job postings via jobs-guest endpoints."""

    JOB_TYPE_CODES = {
        "full_time": "F",
        "part_time": "P",
        "contract": "C",
        "temporary": "T",
        "internship": "I",
        "volunteer": "V",
        "other": "O",
    }
    EXPERIENCE_CODES = {
        "internship": "1",
        "entry": "2",
        "associate": "3",
        "mid_senior": "4",
        "director": "5",
        "executive": "6",
    }
    WORKPLACE_CODES = {
        "on_site": "1",
        "remote": "2",
        "hybrid": "3",
    }

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = "https://www.linkedin.com"
        self.search_config = config.get("search", {})
        self.board_cfg = (config.get("boards", {}) or {}).get("linkedin", {}) or {}
        self.filters_cfg = self.board_cfg.get("filters", {}) or {}
        self.page_size = int(self.board_cfg.get("page_size", 25) or 25)
        self.max_pages = int(self.board_cfg.get("max_pages", 40) or 40)
        self._parse_search_keywords()
        self.current_keyword_group_index = 0

    @staticmethod
    def _coerce_str_list(value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            pieces = [p.strip() for p in value.split(",")]
            return [p for p in pieces if p]
        if isinstance(value, list):
            out = []
            for item in value:
                token = str(item or "").strip()
                if token:
                    out.append(token)
            return out
        token = str(value).strip()
        return [token] if token else []

    @classmethod
    def _normalize_codes(cls, raw: object, mapping: Dict[str, str]) -> List[str]:
        raw_list = cls._coerce_str_list(raw)
        normalized: List[str] = []
        allowed = set(mapping.values())
        for item in raw_list:
            key = item.strip().lower()
            code = mapping.get(key, item.strip().upper())
            if code in allowed and code not in normalized:
                normalized.append(code)
        return normalized

    def _parse_search_keywords(self) -> None:
        keywords_list = self.search_config.get("keywords", [])
        if isinstance(keywords_list, str):
            keywords_list = [keywords_list]

        self.keyword_groups = keywords_list
        self.target_keywords: List[str] = []

        for keyword_group in keywords_list:
            matches = re.findall(r'"([^"]*)"', keyword_group)
            parsed_keywords = [keyword.lower() for keyword in matches if keyword]
            if not parsed_keywords:
                parsed_keywords = [
                    k.strip().lower() for k in keyword_group.split("OR") if k.strip()
                ]
            self.target_keywords.extend(parsed_keywords)

        logger.debug(
            f"LinkedIn scraper parsed {len(self.target_keywords)} target keywords"
        )

    def _get_matching_keyword(self, title: str) -> Optional[str]:
        if not self.target_keywords:
            return "No keywords defined"

        title_lower = (title or "").lower()
        for keyword in self.target_keywords:
            if " " in keyword:
                if keyword in title_lower:
                    return keyword
            else:
                word_pattern = r"\b{}\b".format(re.escape(keyword))
                if re.search(word_pattern, title_lower):
                    return keyword
        return None

    _AU_STATE_CODES = {"vic", "nsw", "qld", "sa", "wa", "tas", "nt", "act"}

    @classmethod
    def _to_linkedin_keywords(cls, keyword_group: str) -> str:
        """Translate a Seek-style keyword group into LinkedIn boolean syntax.

        Seek groups look like ``'"a"-or-"b"'``; LinkedIn expects
        ``'"a" OR "b"'``. Passing the Seek form verbatim matches nothing.
        """
        phrases = [p.strip() for p in re.findall(r'"([^"]*)"', keyword_group)]
        phrases = [p for p in phrases if p]
        if phrases:
            return " OR ".join(f'"{p}"' for p in phrases)
        return keyword_group

    @classmethod
    def _to_linkedin_location(cls, location: str) -> str:
        """Translate a Seek-style location into a LinkedIn geo string.

        ``All-Australia`` means the whole country; ``<Place>-<STATE>`` needs a
        country suffix so LinkedIn does not resolve the bare place name to
        another region (e.g. Victoria, Canada).
        """
        loc = str(location or "Australia").strip()
        if loc.lower() in ("all-australia", "all australia", "australia"):
            return "Australia"
        parts = loc.split("-")
        if len(parts) == 2 and parts[1].strip().lower() in cls._AU_STATE_CODES:
            return f"{parts[0].strip()}, Australia"
        return loc.replace("-", " ")

    def build_search_url(self, start: int, keyword_index: Optional[int] = None) -> str:
        """Build LinkedIn jobs-guest search URL."""
        idx = (
            keyword_index
            if keyword_index is not None
            else self.current_keyword_group_index
        )
        if idx < 0 or idx >= len(self.keyword_groups):
            raise ValueError(f"Invalid keyword group index: {idx}")

        keyword_group = self.keyword_groups[idx]
        location = self.search_config.get("location", "Australia")
        date_range_days = int(self.search_config.get("date_range", 30) or 30)
        # LinkedIn expects seconds for f_TPR; this keeps recency roughly aligned.
        recent_seconds = max(1, date_range_days) * 24 * 60 * 60

        job_type_codes = self._normalize_codes(
            self.filters_cfg.get("job_types"), self.JOB_TYPE_CODES
        )
        exp_codes = self._normalize_codes(
            self.filters_cfg.get("experience_levels"), self.EXPERIENCE_CODES
        )
        workplace_codes = self._normalize_codes(
            self.filters_cfg.get("workplace_types"), self.WORKPLACE_CODES
        )

        sort_by = str(self.filters_cfg.get("sort_by") or "DD").strip().upper()
        if sort_by not in {"DD", "R"}:
            sort_by = "DD"

        distance = int(self.filters_cfg.get("distance_km", 0) or 0)
        easy_apply_only = bool(self.filters_cfg.get("easy_apply_only", False))

        params = {
            "keywords": self._to_linkedin_keywords(keyword_group),
            "location": self._to_linkedin_location(location),
            "start": int(start),
            "count": int(self.page_size),
            "f_TPR": f"r{recent_seconds}",
            "sortBy": sort_by,
        }
        if distance > 0:
            params["distance"] = distance
        if easy_apply_only:
            params["f_AL"] = "true"
        if job_type_codes:
            params["f_JT"] = ",".join(job_type_codes)
        if exp_codes:
            params["f_E"] = ",".join(exp_codes)
        if workplace_codes:
            params["f_WT"] = ",".join(workplace_codes)
        return (
            f"{self.base_url}/jobs-guest/jobs/api/seeMoreJobPostings/search?"
            f"{urlencode(params)}"
        )

    @staticmethod
    def _extract_job_id(raw: str) -> str:
        token = str(raw or "").strip()
        if token.startswith("li-"):
            return token
        return f"li-{token}"

    @staticmethod
    def _strip_job_id_prefix(job_id: str) -> str:
        value = str(job_id or "").strip()
        return value[3:] if value.startswith("li-") else value

    def extract_job_info(self, card: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract one LinkedIn preview card."""
        try:
            urn = card.get("data-entity-urn") or ""
            match = re.search(r"jobPosting:(\d+)", urn)
            raw_job_id = match.group(1) if match else ""

            link_el = card.find("a", class_=lambda c: c and "full-link" in c)
            url = (link_el.get("href") or "").strip() if link_el else ""
            url = self._normalize_result_url(url)
            if not raw_job_id and url:
                url_match = re.search(r"/view/(\d+)", url)
                raw_job_id = url_match.group(1) if url_match else ""

            if not raw_job_id:
                return None

            title_el = card.find("h3", class_=lambda c: c and "title" in c)
            title = " ".join((title_el.get_text() or "").split()) if title_el else ""
            if not title:
                return None

            matching_keyword = self._get_matching_keyword(title)
            if not matching_keyword:
                return None

            company = ""
            company_el = card.find(
                "h4", class_=lambda c: c and "subtitle" in c
            ) or card.find("a", class_=lambda c: c and "hidden-nested-link" in c)
            if company_el:
                company = " ".join((company_el.get_text() or "").split())

            location_el = card.find("span", class_=lambda c: c and "location" in c)
            location = (
                " ".join((location_el.get_text() or "").split()) if location_el else ""
            )

            # The card is the ONLY place LinkedIn exposes a real posting date --
            # the guest jobPosting detail endpoint carries no <time> element, so
            # anything derived there silently degrades to "now". Capture it here
            # and thread it through, or every LinkedIn row looks freshly posted
            # and never ages out under expire_after_days.
            posted_at = ""
            date_el = card.find(
                "time", class_=lambda c: c and "listdate" in c
            ) or card.find("time")
            if date_el and date_el.get("datetime"):
                posted_at = str(date_el.get("datetime")).strip()

            return {
                "job_id": self._extract_job_id(raw_job_id),
                "title": title,
                "company": company or "Unknown",
                "url": url or f"{self.base_url}/jobs/view/{raw_job_id}",
                "source": "linkedin",
                "location": location,
                "matching_keyword": matching_keyword,
                "quick_apply": False,
                "posted_at": posted_at,
            }
        except Exception as exc:
            logger.debug(f"LinkedIn preview parse failed: {exc}")
            return None

    @staticmethod
    def _normalize_result_url(href: str) -> str:
        """Drop noisy tracking params from LinkedIn result URLs."""
        value = str(href or "").strip()
        if not value:
            return value
        try:
            parsed = urlparse(value)
            query = parse_qs(parsed.query)
            keep = {}
            if "currentJobId" in query:
                keep["currentJobId"] = query["currentJobId"][0]
            if "trk" in query:
                keep["trk"] = query["trk"][0]
            clean_query = urlencode(keep) if keep else ""
            normalized = parsed._replace(query=clean_query, fragment="")
            return normalized.geturl()
        except Exception:
            return value

    def get_job_previews(self) -> List[Dict[str, Any]]:
        """Get LinkedIn previews across configured keyword groups."""
        all_jobs: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for keyword_index in range(len(self.keyword_groups)):
            self.current_keyword_group_index = keyword_index

            for page in range(self.max_pages):
                start = page * self.page_size
                if self.max_jobs and len(all_jobs) >= int(self.max_jobs):
                    break

                url = self.build_search_url(start=start)
                soup = self.make_request(url)
                if not soup:
                    break

                cards = soup.find_all(
                    "div", class_=lambda c: c and "base-search-card" in c
                )
                if not cards:
                    break

                page_added = 0
                for card in cards:
                    parsed = self.extract_job_info(card)
                    if not parsed:
                        continue
                    job_id = str(parsed.get("job_id") or "").strip()
                    if not job_id or job_id in seen:
                        continue
                    seen.add(job_id)
                    all_jobs.append(parsed)
                    page_added += 1
                    if self.max_jobs and len(all_jobs) >= int(self.max_jobs):
                        break

                if page_added == 0:
                    # End-of-results protection when endpoint repeats stale cards.
                    break

        logger.debug(f"LinkedIn scraper found {len(all_jobs)} preview matches")
        return all_jobs

    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get LinkedIn job details by job posting id."""
        raw_job_id = self._strip_job_id_prefix(job_id)
        if not raw_job_id:
            return None

        url = f"{self.base_url}/jobs-guest/jobs/api/jobPosting/{raw_job_id}"
        soup = self.make_request(url)
        if not soup:
            return None

        try:
            description_el = soup.find(
                "div", class_=lambda c: c and "show-more-less-html__markup" in c
            ) or soup.find("section", class_=lambda c: c and "description" in c)
            if not description_el:
                logger.debug(f"LinkedIn details missing description for {job_id}")
                return None

            description = description_el.get_text(separator="\n").strip()
            description = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", description)

            location = ""
            location_el = soup.find(
                "span", class_=lambda c: c and "topcard__flavor--bullet" in c
            ) or soup.find("span", class_=lambda c: c and "location" in c)
            if location_el:
                location = " ".join((location_el.get_text() or "").split())

            work_type = "Unknown"
            body_text = soup.get_text(separator="\n")
            lowered = body_text.lower()
            if "contract" in lowered:
                work_type = "Contract"
            elif "full-time" in lowered or "full time" in lowered:
                work_type = "Full Time"

            # The guest jobPosting endpoint carries no <time>; the posting date
            # comes from the preview card (see extract_job_info) and is applied
            # by the scrape loop. Falling back to now() here would overwrite it
            # with the scrape time, so leave it empty when genuinely absent.
            posted_time = ""
            time_el = soup.find("time")
            if time_el and time_el.get("datetime"):
                posted_time = str(time_el.get("datetime"))

            pay_rate = "Not specified"
            salary_match = re.search(
                r"(\$[\d,\.\s]+(?:k|K)?(?:\s*-\s*\$[\d,\.\s]+(?:k|K)?)?)",
                body_text,
            )
            if salary_match:
                pay_rate = salary_match.group(1).strip()

            # Optional hints for recruiter-intel enrichment.
            recruiter_hints: List[Dict[str, str]] = []
            for a in soup.find_all("a", href=True):
                href = str(a.get("href") or "").strip()
                text = " ".join((a.get_text() or "").split())
                if href.startswith("mailto:"):
                    recruiter_hints.append(
                        {
                            "email": href.replace("mailto:", "", 1).strip(),
                            "name": text,
                        }
                    )
                elif "linkedin.com/in/" in href:
                    recruiter_hints.append(
                        {
                            "linkedin_url": href,
                            "name": text,
                        }
                    )

            posted_by = re.search(
                r"posted by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
                body_text,
                flags=re.IGNORECASE,
            )
            if posted_by:
                recruiter_hints.append({"name": posted_by.group(1).strip()})

            return {
                "description": description,
                "quick_apply": False,
                # LinkedIn is never Seek Quick Apply; route it through the agent
                # applier path (its ATS detection handles the linkedin.com host).
                "apply_type": "external",
                "created_at": posted_time,
                "location": location or "Unknown",
                "work_type": work_type,
                "pay_rate": pay_rate,
                "recruiter_hints": recruiter_hints,
            }
        except Exception as exc:
            logger.exception(f"LinkedIn details extraction failed for {job_id}: {exc}")
            return None
