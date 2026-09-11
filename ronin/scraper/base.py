"""Base scraper class for job boards."""

import functools
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# curl_cffi.requests is a drop-in replacement for `requests` that uses libcurl
# under the hood and can impersonate Chrome's TLS/JA3 fingerprint + HTTP/2
# settings. Plain `requests` has a distinct fingerprint that Cloudflare flags
# instantly, regardless of how clean the HTTP headers look. This is the
# single biggest leverage for getting past Seek's CF gate.
from curl_cffi import requests as cf_requests
from loguru import logger


def rate_limited(func):
    """Decorator to implement rate limiting and error handling for requests."""

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            time.sleep(self.delay)
            return func(self, *args, **kwargs)
        except cf_requests.exceptions.RequestException as e:
            logger.error(f"Request error in {func.__name__}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            return None

    return wrapper


class BaseScraper(ABC):
    """Base class for all job board scrapers."""

    def __init__(
        self,
        config: Dict,
        session: Optional[cf_requests.Session] = None,
    ):
        self.config = config
        # impersonate="chrome" sets the latest Chrome TLS fingerprint, HTTP/2
        # SETTINGS frame, and a complete realistic header baseline. Our
        # explicit header overrides below merge on top.
        self.session = session or cf_requests.Session(impersonate="chrome")
        self.delay = config.get("scraping", {}).get("delay_seconds", 2)
        self.max_jobs = config.get("scraping", {}).get("max_jobs", None)
        self.timeout = config.get("scraping", {}).get("timeout_seconds", 10)
        self.quick_apply_only = config.get("scraping", {}).get("quick_apply_only", True)
        # When True, non-quick-apply (link-out / external) jobs are retained and
        # tagged apply_type='external' for the agent applier, instead of being
        # discarded. Overrides quick_apply_only's drop behaviour for externals.
        self.capture_external = config.get("scraping", {}).get(
            "capture_external", False
        )

        # Track last URL so subsequent same-host requests can send a
        # realistic Referer + Sec-Fetch-Site=same-origin (required by
        # Seek/Cloudflare to avoid 403 on /job/<id> detail pages).
        self._last_url: Optional[str] = None

        # Configure proxy if available
        proxy_config = self._get_proxy_config()
        if proxy_config:
            self.session.proxies.update(proxy_config)

        # Set up common headers. The previous UA was truncated
        # ("AppleWebKit/537.36" with no Chrome/Safari tail) which is an
        # obvious bot signature and triggered 403s on Seek. This is a full
        # Chrome-on-macOS header set including client hints (Sec-Ch-Ua),
        # fetch metadata (Sec-Fetch-*), and language/accept negotiation.
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/137.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.7"
                ),
                "Accept-Language": "en-AU,en-US;q=0.9,en;q=0.8",
                "Sec-Ch-Ua": (
                    '"Google Chrome";v="137", "Chromium";v="137", '
                    '"Not/A)Brand";v="24"'
                ),
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

    def _get_proxy_config(self) -> Optional[Dict[str, str]]:
        """Get proxy configuration from environment variables or config."""
        import os

        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")

        if http_proxy or https_proxy:
            proxy_config = {}
            if http_proxy:
                proxy_config["http"] = http_proxy
            if https_proxy:
                proxy_config["https"] = https_proxy
            return proxy_config

        proxy_config = self.config.get("proxy", {})
        if proxy_config.get("enabled", False):
            return {
                "http": proxy_config.get("http_url"),
                "https": proxy_config.get("https_url"),
            }

        return None

    @rate_limited
    def make_request(self, url: str) -> Optional[BeautifulSoup]:
        """Make an HTTP request and return BeautifulSoup object."""
        per_request_headers: Dict[str, str] = {}
        if self._last_url:
            try:
                same_host = urlparse(self._last_url).netloc == urlparse(url).netloc
            except Exception:
                same_host = False
            if same_host:
                per_request_headers["Referer"] = self._last_url
                per_request_headers["Sec-Fetch-Site"] = "same-origin"
                per_request_headers["Sec-Fetch-User"] = "?1"

        response = self.session.get(
            url, timeout=self.timeout, headers=per_request_headers or None
        )
        response.raise_for_status()
        self._last_url = response.url
        return BeautifulSoup(response.text, "html.parser")

    @abstractmethod
    def get_job_previews(self) -> List[Dict[str, Any]]:
        """Get job previews with minimal information."""
        pass

    @abstractmethod
    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed job information."""
        pass

    def scrape_jobs(self) -> List[Dict[str, Any]]:
        """Scrape all jobs with full details."""
        job_previews = self.get_job_previews()
        if not job_previews:
            return []

        jobs_data = []
        for preview in job_previews:
            job_details = self.get_job_details(preview["job_id"])
            if job_details:
                is_quick = job_details.get("quick_apply", False)
                # Drop non-quick jobs only when quick_apply_only is set AND we
                # are not deliberately capturing externals for the agent applier.
                if self.quick_apply_only and not is_quick and not self.capture_external:
                    logger.debug(
                        f"Skipping job without quick apply: {preview['title']} (ID: {preview['job_id']})"
                    )
                    continue

                # Ensure every retained job carries an explicit apply_type so
                # the DB and the applier dispatch never have to guess.
                if "apply_type" not in job_details:
                    job_details["apply_type"] = "quick" if is_quick else "external"

                full_job = {**preview, **job_details}

                # A real posting date from the preview card beats anything the
                # detail page inferred. Board detail pages routinely omit it and
                # fall back to "now", which makes a month-old ad look fresh and
                # exempts it from expire_after_days.
                posted_at = str(preview.get("posted_at") or "").strip()
                if posted_at:
                    full_job["created_at"] = posted_at

                jobs_data.append(full_job)
                logger.debug(
                    f"Scraped details for: {preview['title']} "
                    f"(ID: {preview['job_id']}, apply_type={job_details['apply_type']})"
                )

        external_count = sum(1 for j in jobs_data if j.get("apply_type") == "external")
        if self.capture_external and external_count:
            logger.info(
                f"Captured {external_count} external (link-out) jobs for the "
                f"agent applier"
            )
        return jobs_data
