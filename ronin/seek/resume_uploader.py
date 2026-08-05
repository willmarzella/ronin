"""Seek resume upload automation (Playwright).

This module automates uploading/replacing the resume documents stored in your
Seek profile. It is separate from:
- Selecting which already-uploaded resume to attach in an application form
  (handled by SeekApplier via seek_resume_id)
- Switching your Seek profile copy (headline/summary/skills)

The UI can change; selectors are best-effort and can be overridden via
`seek_profile.automation.selectors` in config.yaml.
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

from loguru import logger

from ronin.config import get_ronin_home


class SeekResumeUploadError(RuntimeError):
    pass


class SeekLoginRequired(SeekResumeUploadError):
    pass


UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _expand_path(raw: str, *, base: Optional[Path] = None) -> Path:
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    if base is None:
        base = get_ronin_home()
    return (base / p).resolve()


class SeekResumeUploader:
    """Automate uploading/replacing resume documents in Seek."""

    # As of 2026-02, resume management UI lives under /profile/me/resume.
    # The older /profile/resumes route may exist but does not reliably expose
    # upload controls.
    DEFAULT_RESUMES_URL = "https://au.seek.com/profile/me/resume?mode=edit"
    DEFAULT_RESUME_DETAIL_BASE = "https://au.seek.com/profile/resumes"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        cfg = self.config.get("seek_profile", {}) or {}
        auto = cfg.get("automation", {}) or {}

        self.headless = _truthy(auto.get("headless"), False)
        self.slow_mo_ms = _int(auto.get("slow_mo_ms"), 0)
        self.timeout_ms = _int(auto.get("timeout_ms"), 45_000)
        self.login_timeout_sec = _int(auto.get("login_timeout_sec"), 300)
        self.channel = str(auto.get("channel") or "chrome").strip() or None

        raw_dir = str(auto.get("user_data_dir") or "").strip()
        if raw_dir:
            self.user_data_dir = _expand_path(raw_dir)
        else:
            self.user_data_dir = (get_ronin_home() / "chrome_profile").resolve()

        self.resumes_url = (
            str(auto.get("resumes_url") or "").strip() or self.DEFAULT_RESUMES_URL
        )

        self.selectors: Dict[str, str] = {}
        raw_selectors = auto.get("selectors")
        if isinstance(raw_selectors, dict):
            self.selectors = {str(k): str(v) for k, v in raw_selectors.items() if v}

        self.jitter = _truthy(auto.get("jitter"), True)
        self.min_delay_sec = float(auto.get("min_delay_sec") or 0.1)
        self.max_delay_sec = float(auto.get("max_delay_sec") or 0.5)

    def debug_pause(self, url: str = "") -> None:
        """Open Playwright Inspector on the resumes page."""
        url = str(url or "").strip() or self.resumes_url
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ModuleNotFoundError as exc:
            raise SeekResumeUploadError(
                "Playwright is required for Seek resume automation. "
                "Install: pip install playwright && playwright install chromium"
            ) from exc

        user_data_dir = self._resolve_user_data_dir_with_lock()
        lock = user_data_dir["lock"]
        profile_dir = user_data_dir["path"]
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel=self.channel,
                    headless=False,
                    slow_mo=150,
                    viewport={"width": 1280, "height": 900},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-extensions",
                        "--disable-gpu",
                    ],
                )
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)
                page.goto(url, wait_until="domcontentloaded")
                logger.info("Playwright Inspector opened. Close/resume to exit.")
                page.pause()
                context.close()
        finally:
            try:
                lock.release()
            except Exception:
                pass

    def upload_or_replace(
        self,
        *,
        pdf_path: Path,
        resume_id: str = "",
        allow_manual_login: bool = True,
    ) -> str:
        """Upload a new resume or replace an existing one.

        Args:
            pdf_path: Path to PDF to upload.
            resume_id: Existing Seek resume UUID. If provided, attempt replace.
            allow_manual_login: If Seek login is required, allow interactive login.

        Returns:
            The Seek resume UUID to use in applications.
        """

        pdf_path = Path(pdf_path).expanduser().resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"Resume PDF not found: {pdf_path}")

        if resume_id:
            try:
                parsed = uuid.UUID(str(resume_id).strip())
                resume_id = str(parsed)
            except Exception:
                raise ValueError(f"Invalid resume_id (expected UUID): {resume_id}")

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ModuleNotFoundError as exc:
            raise SeekResumeUploadError(
                "Playwright is required for Seek resume automation. "
                "Install: pip install playwright && playwright install chromium"
            ) from exc

        user_data_dir = self._resolve_user_data_dir_with_lock()
        lock = user_data_dir["lock"]
        profile_dir = user_data_dir["path"]
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel=self.channel,
                    headless=self.headless,
                    slow_mo=self.slow_mo_ms or None,
                    viewport={"width": 1280, "height": 900},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-extensions",
                        "--disable-gpu",
                    ],
                )
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)

                if resume_id:
                    result = self._replace_resume(
                        page,
                        resume_id=resume_id,
                        pdf_path=pdf_path,
                        allow_manual_login=allow_manual_login,
                    )
                else:
                    result = self._upload_new_resume(
                        page,
                        pdf_path=pdf_path,
                        allow_manual_login=allow_manual_login,
                    )

                self._sleep_jitter()
                context.close()
                return result
        finally:
            try:
                lock.release()
            except Exception:
                pass

    def delete_all_resumes(
        self,
        *,
        allow_manual_login: bool = True,
        keep_ids: Optional[Set[str]] = None,
        max_deletes: int = 25,
    ) -> int:
        """Delete resumes from the Seek resume management page.

        Args:
            allow_manual_login: If Seek login is required, allow interactive login.
            keep_ids: Optional set of Seek resume UUIDs to keep.
            max_deletes: Safety cap to avoid infinite loops.

        Returns:
            Number of resumes deleted.
        """

        keep_ids = {
            str(x).strip().lower() for x in (keep_ids or set()) if str(x).strip()
        }
        max_deletes = max(0, int(max_deletes))

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ModuleNotFoundError as exc:
            raise SeekResumeUploadError(
                "Playwright is required for Seek resume automation. "
                "Install: pip install playwright && playwright install chromium"
            ) from exc

        user_data_dir = self._resolve_user_data_dir_with_lock()
        lock = user_data_dir["lock"]
        profile_dir = user_data_dir["path"]
        deleted = 0

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel=self.channel,
                    headless=self.headless,
                    slow_mo=self.slow_mo_ms or None,
                    viewport={"width": 1280, "height": 900},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-extensions",
                        "--disable-gpu",
                    ],
                )
                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)

                self._goto_resumes_page(page, allow_manual_login=allow_manual_login)
                stale_passes = 0
                while deleted < max_deletes:
                    items = self._list_resume_items(page)
                    # Seek can render duplicate rows transiently; dedupe by resume_id.
                    targets_by_id: Dict[str, Dict[str, Any]] = {}
                    for item in items:
                        resume_id = str(item.get("resume_id") or "").strip().lower()
                        if not resume_id or resume_id in keep_ids:
                            continue
                        targets_by_id[resume_id] = item

                    # Fallback: extract IDs directly from page content.
                    if not targets_by_id:
                        for resume_id in sorted(self._extract_resume_ids(page)):
                            if resume_id in keep_ids:
                                continue
                            targets_by_id[resume_id] = {
                                "resume_id": resume_id,
                                "filename": "",
                            }

                    if not targets_by_id:
                        if stale_passes >= 1:
                            break
                        stale_passes += 1
                        try:
                            page.wait_for_timeout(900)
                        except Exception:
                            pass
                        try:
                            page.reload(wait_until="domcontentloaded")
                            page.wait_for_load_state("networkidle", timeout=5_000)
                        except Exception:
                            pass
                        continue

                    pass_deleted = 0
                    # Process the current list from top to bottom without per-item
                    # reloads; Seek can lag before reflecting each delete.
                    for target in list(targets_by_id.values()):
                        if deleted >= max_deletes:
                            break
                        try:
                            did_delete = self._delete_resume_item(
                                page,
                                resume_id=target["resume_id"],
                                filename=target.get("filename") or "",
                            )
                        except SeekResumeUploadError as exc:
                            # Never abort the whole purge on one stubborn row.
                            # Seek refuses to delete the default resume, and a
                            # slow delete can outlive the detach wait; either
                            # way the remaining rows must still be processed.
                            logger.warning(
                                f"Skipping resume {target['resume_id']} during "
                                f"purge: {str(exc)[:160]}"
                            )
                            keep_ids.add(str(target["resume_id"]).lower())
                            did_delete = False
                        if did_delete:
                            deleted += 1
                            pass_deleted += 1

                        try:
                            page.wait_for_timeout(900)
                        except Exception:
                            pass

                        # Some flows navigate away from management list.
                        if "mode=edit" not in str(getattr(page, "url", "") or ""):
                            self._goto_resumes_page(
                                page, allow_manual_login=allow_manual_login
                            )

                    # Single refresh after each pass through the current list.
                    try:
                        page.reload(wait_until="domcontentloaded")
                        page.wait_for_load_state("networkidle", timeout=5_000)
                    except Exception:
                        pass

                    if pass_deleted == 0:
                        stale_passes += 1
                        if stale_passes >= 2:
                            break
                    else:
                        stale_passes = 0

                context.close()
                return deleted
        finally:
            try:
                lock.release()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _goto_resumes_page(self, page: Any, *, allow_manual_login: bool) -> None:
        page.goto(self.resumes_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass

        if self._looks_like_login(page):
            if not allow_manual_login:
                raise SeekLoginRequired("Seek login required")
            if self.headless:
                raise SeekLoginRequired(
                    "Seek login required but headless mode is enabled. "
                    "Set seek_profile.automation.headless: false and retry."
                )
            logger.warning(
                "Seek login required. Complete login in the opened browser window (timeout: %ss)...",
                self.login_timeout_sec,
            )
            if not self._wait_for_login(page, timeout_sec=self.login_timeout_sec):
                raise SeekLoginRequired("Seek login not detected before timeout")
            page.goto(self.resumes_url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass

        # Ensure the management section is present.
        try:
            page.wait_for_selector("[data-automation='manage-resumes']", timeout=10_000)
        except Exception:
            pass

    def _list_resume_items(self, page: Any) -> List[Dict[str, Any]]:
        """Return a list of resume items visible on the management page."""
        items: List[Dict[str, Any]] = []
        loc = page.locator("[data-automation^='resume-item-']")
        try:
            count = int(loc.count())
        except Exception:
            count = 0

        for i in range(count):
            row = loc.nth(i)
            data_auto = ""
            try:
                data_auto = str(row.get_attribute("data-automation") or "")
            except Exception:
                data_auto = ""

            match = UUID_RE.search(data_auto)
            if not match:
                continue
            resume_id = match.group(0).lower()

            filename = ""
            try:
                btn = row.locator("button[aria-label^='Options for ']")
                if btn.count() > 0:
                    label = str(btn.first.get_attribute("aria-label") or "")
                    filename = label.replace("Options for", "", 1).strip()
            except Exception:
                filename = ""

            is_default = False
            try:
                if (
                    row.locator(
                        f"[data-automation='resume-is-default-{resume_id}']"
                    ).count()
                    > 0
                ):
                    is_default = True
            except Exception:
                is_default = False

            items.append(
                {
                    "resume_id": resume_id,
                    "filename": filename,
                    "is_default": is_default,
                }
            )

        return items

    def _delete_resume_item(self, page: Any, *, resume_id: str, filename: str) -> bool:
        resume_id = str(resume_id or "").strip().lower()
        if not resume_id:
            raise SeekResumeUploadError("Missing resume_id for delete")

        row_sel = f"[data-automation='resume-item-{resume_id}']"
        row = page.locator(row_sel)
        if row.count() == 0:
            return False

        # Open options menu.
        options_btn = row.locator("button[aria-label^='Options for ']")
        if options_btn.count() == 0:
            raise SeekResumeUploadError(
                f"Could not find options menu for resume {resume_id} ({filename or 'unknown file'})"
            )
        options_btn.first.click(timeout=5_000)
        self._sleep_jitter(base=0.3)

        # Click delete/remove.
        clicked = False
        action_re = re.compile(r"delete|remove", re.IGNORECASE)
        for role in ["menuitem", "button"]:
            try:
                act = page.get_by_role(role, name=action_re)
                if act.count() > 0:
                    act.first.click(timeout=5_000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            try:
                act = page.get_by_text(action_re)
                if act.count() > 0:
                    act.first.click(timeout=5_000)
                    clicked = True
            except Exception:
                clicked = False

        if not clicked:
            raise SeekResumeUploadError(
                f"Could not find delete action for resume {resume_id} ({filename or 'unknown file'})"
            )

        self._sleep_jitter(base=0.3)

        # Confirm in dialog if present.
        try:
            dialog = page.get_by_role("dialog")
            btn = dialog.get_by_role("button", name=action_re)
            if btn.count() > 0:
                btn.first.click(timeout=5_000)
        except Exception:
            # Fallback: any visible confirm button.
            try:
                btn = page.get_by_role("button", name=action_re)
                if btn.count() > 0:
                    btn.first.click(timeout=5_000)
            except Exception:
                pass

        # Wait for removal. Seek can lag well past the detach wait (deletes
        # land server-side while the row lingers), so verify with a reload
        # before declaring failure.
        try:
            page.locator(row_sel).wait_for(state="detached", timeout=20_000)
        except Exception:
            try:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass
            if page.locator(row_sel).count() > 0:
                raise SeekResumeUploadError(
                    f"Delete did not complete for resume {resume_id} ({filename or 'unknown file'})"
                )
        return True

    def _make_default_resume(self, page: Any, *, resume_id: str) -> bool:
        """Best-effort: mark the given resume as default via its options menu."""
        resume_id = str(resume_id or "").strip().lower()
        if not resume_id:
            return False
        row = page.locator(f"[data-automation='resume-item-{resume_id}']")
        if row.count() == 0:
            return False
        options_btn = row.locator("button[aria-label^='Options for ']")
        if options_btn.count() == 0:
            return False
        try:
            options_btn.first.click(timeout=5_000)
            self._sleep_jitter(base=0.3)
            act = page.get_by_role(
                "menuitem", name=re.compile(r"default", re.IGNORECASE)
            )
            if act.count() == 0:
                act = page.get_by_text(re.compile(r"make default", re.IGNORECASE))
            if act.count() == 0:
                return False
            act.first.click(timeout=5_000)
            self._sleep_jitter(base=0.3)
            return True
        except Exception:
            return False

    def _resume_detail_url(self, resume_id: str) -> str:
        # The detail route is still useful when available (e.g. for replace flows).
        base = str(self.DEFAULT_RESUME_DETAIL_BASE).rstrip("/")
        return f"{base}/{resume_id}"

    def _upload_new_resume(
        self,
        page: Any,
        *,
        pdf_path: Path,
        allow_manual_login: bool,
    ) -> str:
        console_errors: list[str] = []
        request_failures: list[str] = []

        def redact_url(url: str) -> str:
            try:
                parts = urlsplit(str(url or ""))
                # Drop query+fragment to avoid leaking signed URLs.
                return f"{parts.scheme}://{parts.netloc}{parts.path}"
            except Exception:
                return str(url or "")

        def is_upload_related_url(url: str) -> bool:
            u = str(url or "").lower()
            if "doc-uploads" in u:
                return True
            if "s3." in u and "uploads" in u:
                return True
            if "resume" in u and "upload" in u:
                return True
            return False

        # Capture browser-side signals so we can produce actionable errors.
        try:
            page.on(
                "console",
                lambda msg: (
                    console_errors.append(f"[{msg.type}] {msg.text}")
                    if (
                        getattr(msg, "type", "") in {"error"}
                        or "resume error" in str(getattr(msg, "text", "")).lower()
                    )
                    else None
                ),
            )
        except Exception:
            pass

        try:

            def _on_request_failed(req: Any) -> None:
                try:
                    url = str(getattr(req, "url", "") or "")
                    failure = None
                    try:
                        failure = req.failure
                        failure = failure() if callable(failure) else failure
                    except Exception:
                        failure = None
                    err_text = ""
                    if failure and isinstance(failure, dict):
                        err_text = str(failure.get("errorText") or "")
                    elif failure is not None:
                        err_text = str(
                            getattr(failure, "error_text", "")
                            or getattr(failure, "errorText", "")
                            or ""
                        )

                    if is_upload_related_url(url):
                        request_failures.append(
                            f"{redact_url(url)} :: {err_text or 'request failed'}"
                        )
                except Exception:
                    return

            page.on("requestfailed", _on_request_failed)
        except Exception:
            pass

        page.goto(self.resumes_url, wait_until="domcontentloaded")
        # Best-effort: allow client-side UI to render.
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        if self._looks_like_login(page):
            if not allow_manual_login:
                raise SeekLoginRequired("Seek login required")
            if self.headless:
                raise SeekLoginRequired(
                    "Seek login required but headless mode is enabled. "
                    "Set seek_profile.automation.headless: false and retry."
                )
            logger.warning(
                "Seek login required. Complete login in the opened browser window (timeout: %ss)...",
                self.login_timeout_sec,
            )
            if not self._wait_for_login(page, timeout_sec=self.login_timeout_sec):
                raise SeekLoginRequired("Seek login not detected before timeout")
            page.goto(self.resumes_url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass

        before = self._extract_resume_ids(page)
        try:
            self._trigger_upload(page, pdf_path=pdf_path)
        except SeekResumeUploadError as exc:
            # A very common failure mode is being logged out but not redirected
            # to an explicit /login URL.
            if self._looks_like_login(page):
                raise SeekLoginRequired(
                    "Seek login required. Open `ronin resume debug` to log in and capture selectors."
                ) from exc
            raise

        target_filename = pdf_path.name

        # Poll for a new resume ID to appear.
        deadline = time.time() + 90
        last_reload_at: float | None = None
        while time.time() < deadline:
            self._sleep_jitter(base=0.5)

            if request_failures:
                raise SeekResumeUploadError(
                    "Seek document upload request failed (network/browser). "
                    f"Example: {request_failures[-1]}"
                )

            # Some failures only surface as console errors.
            if console_errors:
                last = console_errors[-1]
                if "failed to fetch" in last.lower() or "resume error" in last.lower():
                    raise SeekResumeUploadError(
                        "Seek resume upload failed in the browser (JS error). "
                        f"Example: {last}"
                    )

            # If user is at the 10 resume limit, Seek shows a specific alert and
            # the upload won't succeed.
            try:
                alert = page.locator("[data-automation='max-resume-alert']")
                if alert.count() > 0 and alert.first.is_visible():
                    raise SeekResumeUploadError(
                        "Seek resume limit reached (10). Delete a resume in Seek or "
                        "replace an existing one by providing resume_id."
                    )
            except SeekResumeUploadError:
                raise
            except Exception:
                pass

            # New-id detection: any id we return must not have existed before
            # the upload. Filename mapping alone is unsafe — a prior upload of
            # the same variant shares the filename, and returning its row's id
            # silently registers a stale document while the fresh upload sits
            # unregistered (the pre-2026-08 replace bug).
            current = self._extract_resume_ids(page)
            added = sorted(current - before)
            if added:
                if len(added) > 1:
                    try:
                        mapped = self._extract_resume_id_for_filename(
                            page, target_filename
                        )
                    except Exception:
                        mapped = ""
                    if mapped and mapped in added:
                        return mapped
                return added[0]

            try:
                mapped = self._extract_resume_id_for_filename(page, target_filename)
            except Exception:
                mapped = ""
            if mapped and mapped not in before:
                return mapped

            # Some flows navigate directly to the resume detail page.
            m = UUID_RE.search(str(getattr(page, "url", "") or ""))
            if m and m.group(0) and m.group(0).lower() not in before:
                return m.group(0).lower()

            # Some Seek flows don't update the list until after a soft refresh.
            # Reload once after we see an "Uploaded" indicator.
            try:
                uploaded = page.get_by_text(
                    re.compile(r"^\s*Uploaded\s*$", re.IGNORECASE)
                )
                if (
                    uploaded.count() > 0
                    and uploaded.first.is_visible()
                    and (last_reload_at is None)
                ):
                    page.reload(wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=5_000)
                    except Exception:
                        pass
                    last_reload_at = time.time()
                    continue
            except Exception:
                pass

        try:
            final_count = len(self._extract_resume_ids(page))
        except Exception:
            final_count = -1
        limit_hint = (
            "The account holds 10 resumes (Seek's cap), so the upload was "
            "silently rejected — delete a document and retry. "
            if final_count >= 10
            else ""
        )
        raise SeekResumeUploadError(
            "Resume upload did not produce a NEW resume ID. "
            + limit_hint
            + "Run `ronin resume debug` to verify the resumes_url and capture selectors. "
            + (f"Last console error: {console_errors[-1]} " if console_errors else "")
            + (
                f"Last request failure: {request_failures[-1]}"
                if request_failures
                else ""
            )
        )

    def _extract_resume_id_for_filename(self, page: Any, filename: str) -> str:
        """Return resume UUID whose "Options for <file>" matches filename."""
        filename = str(filename or "").strip()
        if not filename:
            return ""

        try:
            rows = page.eval_on_selector_all(
                "button[aria-label^='Options for ']",
                """
                els => els.map(e => ({
                    label: e.getAttribute('aria-label') || '',
                    item: (e.closest("[data-automation^='resume-item-']") || null)?.getAttribute('data-automation') || ''
                }))
                """,
            )
        except Exception:
            rows = None

        if not isinstance(rows, list):
            return ""

        want = filename.lower()
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("label") or "")
            item = str(row.get("item") or "")
            # label: "Options for <file>"
            file_in_label = label.replace("Options for", "", 1).strip().lower()
            if not file_in_label:
                continue

            # Seek sometimes normalises whitespace; use contains match.
            if want in file_in_label or file_in_label in want:
                m = UUID_RE.search(item)
                if m:
                    return m.group(0).lower()

        return ""

    def _replace_resume(
        self,
        page: Any,
        *,
        resume_id: str,
        pdf_path: Path,
        allow_manual_login: bool,
    ) -> str:
        # Seek's resume UI moved to /profile/me/resume and no longer exposes a
        # stable per-resume detail page — the old /profile/resumes/{id} route
        # 404s. "Replace" is therefore performed by uploading a fresh version on
        # the list page (the same click-through as a new upload) and then
        # removing the prior resume so the list doesn't accumulate duplicates.
        new_id = self._upload_new_resume(
            page, pdf_path=pdf_path, allow_manual_login=allow_manual_login
        )

        old_id = str(resume_id or "").strip().lower()
        if new_id and old_id and new_id.lower() != old_id:
            try:
                page.goto(self.resumes_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=5_000)
                except Exception:
                    pass
                # Seek refuses to delete the default resume. If the outgoing
                # document is the default, promote the fresh upload first.
                try:
                    old_row = page.locator(
                        f"[data-automation='resume-item-{old_id}']"
                    )
                    if old_row.count() > 0 and re.search(
                        r"\bdefault\b",
                        old_row.first.inner_text() or "",
                        re.IGNORECASE,
                    ):
                        self._make_default_resume(page, resume_id=new_id)
                        self._sleep_jitter(base=0.5)
                except Exception:
                    pass
                if self._delete_resume_item(page, resume_id=old_id, filename=""):
                    logger.info(
                        "Removed prior Seek resume %s after replace", old_id
                    )
            except Exception as exc:
                logger.warning(
                    "Uploaded new resume %s but could not remove prior %s: %s",
                    new_id,
                    old_id,
                    str(exc)[:160],
                )

        return new_id

    def _extract_resume_ids(self, page: Any) -> Set[str]:
        ids: Set[str] = set()

        # Primary: the /profile/me/resume management page renders items with
        # `data-automation="resume-item-<uuid>"`.
        try:
            autos = page.eval_on_selector_all(
                "[data-automation^='resume-item-']",
                "els => els.map(e => e.getAttribute('data-automation') || '')",
            )
            if isinstance(autos, list):
                for raw in autos:
                    match = UUID_RE.search(str(raw or ""))
                    if match:
                        ids.add(match.group(0).lower())
        except Exception:
            pass

        try:
            hrefs = page.eval_on_selector_all(
                "a[href*='/profile/resumes/']",
                "els => els.map(e => e.getAttribute('href') || '')",
            )
            if isinstance(hrefs, list):
                for href in hrefs:
                    match = UUID_RE.search(str(href or ""))
                    if match:
                        ids.add(match.group(0).lower())
        except Exception:
            pass

        # Fallback: parse IDs from HTML using resume-specific patterns.
        try:
            html = page.content()
            ids |= self._extract_resume_ids_from_html(str(html or ""))
        except Exception:
            pass

        # Also scan iframe contents; some Seek sections are embedded.
        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    try:
                        if getattr(frame, "url", "") == "about:blank":
                            continue
                        html = frame.content()
                        ids |= self._extract_resume_ids_from_html(str(html or ""))
                    except Exception:
                        continue
        except Exception:
            pass

        try:
            url = str(getattr(page, "url", "") or "")
            match = UUID_RE.search(url)
            if match:
                ids.add(match.group(0).lower())
        except Exception:
            pass

        return ids

    def _extract_resume_ids_from_html(self, html: str) -> Set[str]:
        """Extract resume UUIDs from HTML using Seek-specific markers."""
        found: Set[str] = set()
        if not html:
            return found

        # /profile/me/resume list items
        try:
            pattern = re.compile(r"resume-item-(%s)" % UUID_RE.pattern, re.IGNORECASE)
            for m in pattern.finditer(html):
                found.add(m.group(1).lower())
        except Exception:
            pass

        # Older detail links
        try:
            pattern = re.compile(
                r"/profile/resumes/(%s)" % UUID_RE.pattern, re.IGNORECASE
            )
            for m in pattern.finditer(html):
                found.add(m.group(1).lower())
        except Exception:
            pass

        return found

    def _trigger_upload(self, page: Any, *, pdf_path: Path) -> None:
        # Known stable Seek attributes (2026-02).
        seek_file_input = "input[type='file'][data-automation='resume-upload']"
        seek_browse_button = "button[data-automation='resume-browse']"

        def try_set_any_file_input(scope: Any) -> bool:
            try:
                # Prefer Seek's specific input when present.
                file_input = scope.locator(seek_file_input)
                if file_input.count() == 0:
                    file_input = scope.locator("input[type='file']")
                if file_input.count() > 0:
                    file_input.first.set_input_files(str(pdf_path))
                    return True
            except Exception:
                return False
            return False

        def click_and_set(locator: Any) -> bool:
            # First try the "file chooser" event path.
            try:
                with page.expect_file_chooser(timeout=5_000) as fc:
                    locator.first.click(timeout=5_000)
                fc.value.set_files(str(pdf_path))
                return True
            except Exception:
                pass

            # Some Seek flows open a modal containing an <input type=file>.
            try:
                locator.first.click(timeout=5_000)
                self._sleep_jitter(base=0.5)
                return try_set_any_file_input(page)
            except Exception:
                return False

        # 1) Direct file input override.
        input_sel = self.selectors.get("resume_file_input")
        if input_sel:
            page.set_input_files(input_sel, str(pdf_path))
            return

        # 2) Seek's known input.
        try:
            if page.locator(seek_file_input).count() > 0:
                page.set_input_files(seek_file_input, str(pdf_path))
                return
        except Exception:
            pass

        # 3) Generic file input on the page.
        try:
            page.wait_for_selector("input[type='file']", timeout=3_000)
        except Exception:
            pass
        if try_set_any_file_input(page):
            return

        # Try within iframes (Seek sometimes embeds profile sections).
        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    try:
                        if try_set_any_file_input(frame):
                            return
                    except Exception:
                        continue
        except Exception:
            pass

        # 4) Click upload button and handle chooser.
        upload_sel = self.selectors.get("upload_resume_button")
        if upload_sel:
            if click_and_set(page.locator(upload_sel)):
                return

        # 5) Seek's known browse button.
        try:
            btn = page.locator(seek_browse_button)
            if btn.count() > 0 and click_and_set(btn):
                return
        except Exception:
            pass

        name_re = re.compile(
            r"(upload\s+(a\s+)?resume|add\s+(a\s+)?resume|upload\s+(a\s+)?cv|add\s+document|upload\s+document|upload)",
            re.IGNORECASE,
        )

        for role in ["button", "link"]:
            try:
                el = page.get_by_role(role, name=name_re)
                if click_and_set(el):
                    return
            except Exception:
                pass

        # Role search within iframes.
        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    for role in ["button", "link"]:
                        try:
                            el = frame.get_by_role(role, name=name_re)
                            if click_and_set(el):
                                return
                        except Exception:
                            continue
        except Exception:
            pass

        # Text fallback (best-effort; can be brittle across locales).
        try:
            el = page.get_by_text(name_re)
            if click_and_set(el):
                return
        except Exception:
            pass

        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    try:
                        el = frame.get_by_text(name_re)
                        if click_and_set(el):
                            return
                    except Exception:
                        continue
        except Exception:
            pass

        raise SeekResumeUploadError(
            "Could not find a resume upload control. "
            "Configure seek_profile.automation.selectors.resume_file_input or upload_resume_button. "
            "For the /profile/me/resume page, common working values are: "
            "resume_file_input='input[data-automation=resume-upload]' and "
            "upload_resume_button='button[data-automation=resume-browse]'."
        )

    def _trigger_replace(self, page: Any, *, pdf_path: Path) -> None:
        def try_set_any_file_input(scope: Any) -> bool:
            try:
                file_input = scope.locator("input[type='file']")
                if file_input.count() > 0:
                    file_input.first.set_input_files(str(pdf_path))
                    return True
            except Exception:
                return False
            return False

        def click_and_set(locator: Any) -> bool:
            try:
                with page.expect_file_chooser(timeout=5_000) as fc:
                    locator.first.click(timeout=5_000)
                fc.value.set_files(str(pdf_path))
                return True
            except Exception:
                pass

            try:
                locator.first.click(timeout=5_000)
                self._sleep_jitter(base=0.5)
                return try_set_any_file_input(page)
            except Exception:
                return False

        # 1) Direct selector override.
        replace_sel = self.selectors.get("replace_resume_button")
        if replace_sel:
            if click_and_set(page.locator(replace_sel)):
                return

        # 2) Heuristic buttons.
        name_re = re.compile(
            r"(replace\s+(your\s+)?resume|update\s+(your\s+)?resume|replace\s+document|update\s+document|upload\s+new\s+version|upload\s+new|replace|update)",
            re.IGNORECASE,
        )

        for role in ["button", "link"]:
            try:
                el = page.get_by_role(role, name=name_re)
                if click_and_set(el):
                    return
            except Exception:
                pass

        # Role search within iframes.
        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    for role in ["button", "link"]:
                        try:
                            el = frame.get_by_role(role, name=name_re)
                            if click_and_set(el):
                                return
                        except Exception:
                            continue
        except Exception:
            pass

        try:
            el = page.get_by_text(name_re)
            if click_and_set(el):
                return
        except Exception:
            pass

        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    try:
                        el = frame.get_by_text(name_re)
                        if click_and_set(el):
                            return
                    except Exception:
                        continue
        except Exception:
            pass

        # 3) Generic file input fallback.
        try:
            file_input = page.locator("input[type='file']")
            if file_input.count() > 0:
                file_input.first.set_input_files(str(pdf_path))
                return
        except Exception:
            pass

        try:
            frames = getattr(page, "frames", None)
            if frames:
                for frame in frames:
                    try:
                        file_input = frame.locator("input[type='file']")
                        if file_input.count() > 0:
                            file_input.first.set_input_files(str(pdf_path))
                            return
                    except Exception:
                        continue
        except Exception:
            pass

        raise SeekResumeUploadError(
            "Could not find a resume replace control. "
            "Configure seek_profile.automation.selectors.replace_resume_button."
        )

    def _resolve_user_data_dir_with_lock(self) -> Dict[str, Any]:
        """Return {path, lock} with best-effort lock acquisition."""
        try:
            from filelock import FileLock
        except Exception:
            FileLock = None

        base_dir = self.user_data_dir
        base_dir.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(base_dir) + ".lock")

        if FileLock is None:
            return {"path": base_dir, "lock": _NoopLock()}

        try:
            lock = FileLock(str(lock_path), timeout=0)
            lock.acquire()
            return {"path": base_dir, "lock": lock}
        except Exception:
            session_id = str(uuid.uuid4())[:8]
            alt_dir = base_dir.parent / f"{base_dir.name}_{session_id}"
            alt_dir.mkdir(parents=True, exist_ok=True)
            logger.warning(
                "Chrome profile lock busy; using session profile %s (login may be required)",
                alt_dir,
            )
            return {"path": alt_dir, "lock": _NoopLock()}

    def _looks_like_login(self, page: Any) -> bool:
        url = str(getattr(page, "url", "") or "").lower()
        if any(
            token in url for token in ["login", "signin", "sign-in", "oauth", "auth"]
        ):
            return True

        # If the profile page is visible but Seek hasn't redirected to /login,
        # we may see a "profile could not be found" style error.
        try:
            body = page.locator("body")
            text = (body.inner_text(timeout=1_000) or "").lower()
            for phrase in [
                "profile could not be found",
                "couldn't find your profile",
                "we couldn't find your profile",
                "we could not find your profile",
                "sign in to",
                "log in to",
                "please sign in",
                "please log in",
                "session expired",
            ]:
                if phrase in text:
                    return True
        except Exception:
            pass

        try:
            login_btn = page.get_by_role(
                "button", name=re.compile(r"sign\s*in|log\s*in", re.IGNORECASE)
            )
            if login_btn.count() > 0 and login_btn.first.is_visible():
                return True
        except Exception:
            pass

        try:
            login_link = page.get_by_role(
                "link", name=re.compile(r"sign\s*in|log\s*in", re.IGNORECASE)
            )
            if login_link.count() > 0 and login_link.first.is_visible():
                return True
        except Exception:
            pass

        try:
            a = page.locator("a[href*='login'], a[href*='signin'], a[href*='sign-in']")
            if a.count() > 0:
                return True
        except Exception:
            pass
        return False

    def _wait_for_login(self, page: Any, *, timeout_sec: int) -> bool:
        deadline = time.time() + max(10, int(timeout_sec))
        while time.time() < deadline:
            try:
                if not self._looks_like_login(page):
                    return True
            except Exception:
                pass
            self._sleep_jitter(base=1.0)
        return False

    def _sleep_jitter(self, *, base: float = 0.0) -> None:
        if base <= 0:
            base = self.min_delay_sec
        if not self.jitter:
            time.sleep(base)
            return
        try:
            import random

            extra = random.uniform(self.min_delay_sec, self.max_delay_sec)
        except Exception:
            extra = self.min_delay_sec
        time.sleep(base + extra)


class _NoopLock:
    def release(self) -> None:
        return
