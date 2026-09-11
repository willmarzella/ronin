"""Seek profile state automation (Playwright).

This module is intentionally best-effort and configurable:
- Seek's UI changes frequently.
- Prefer stable locators (ARIA labels / roles / data-testid) when possible.
- Allow user overrides via config.yaml (seek_profile.automation.selectors).

The primary goal is archetype batching support:
before `ronin apply batch <archetype>`, switch your Seek profile copy to match
the archetype so recruiter profile views see the right framing.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger

from ronin.config import get_ronin_home


class SeekProfileAutomationError(RuntimeError):
    pass


class SeekLoginRequired(SeekProfileAutomationError):
    pass


class SeekTemplateMissing(SeekProfileAutomationError):
    pass


@dataclass
class SeekCareerEntry:
    title: str = ""
    company: str = ""
    period: str = ""
    responsibilities: str = ""
    achievements: List[str] = field(default_factory=list)


@dataclass
class SeekProfileTemplate:
    archetype: str
    headline: str = ""
    summary: str = ""
    skills: List[str] = field(default_factory=list)
    experience: List[SeekCareerEntry] = field(default_factory=list)


def _safe_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    if isinstance(value, str):
        parts = re.split(r"[\n,]+", value)
        return [p.strip() for p in parts if p.strip()]
    return []


def load_template_from_config(
    config: Dict[str, Any], archetype: str
) -> SeekProfileTemplate:
    archetype = str(archetype or "").strip().lower()
    cfg = (config or {}).get("seek_profile", {}) or {}
    templates = cfg.get("templates", {}) or {}
    tpl_raw = templates.get(archetype)
    if not isinstance(tpl_raw, dict):
        tpl_raw = {}

    headline = str(tpl_raw.get("headline") or "").strip()
    summary = str(tpl_raw.get("summary") or "").strip()
    skills = _safe_list(tpl_raw.get("skills"))

    headline_file = str(tpl_raw.get("headline_file") or "").strip()
    summary_file = str(tpl_raw.get("summary_file") or "").strip()
    skills_file = str(tpl_raw.get("skills_file") or "").strip()

    ronin_home = get_ronin_home()

    if headline_file:
        path = Path(headline_file).expanduser()
        if not path.is_absolute():
            path = (ronin_home / path).resolve()
        try:
            headline = path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            raise SeekTemplateMissing(f"Failed to read headline_file: {path}") from exc

    if summary_file:
        path = Path(summary_file).expanduser()
        if not path.is_absolute():
            path = (ronin_home / path).resolve()
        try:
            summary = path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            raise SeekTemplateMissing(f"Failed to read summary_file: {path}") from exc

    if skills_file:
        path = Path(skills_file).expanduser()
        if not path.is_absolute():
            path = (ronin_home / path).resolve()
        try:
            skills = _safe_list(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SeekTemplateMissing(f"Failed to read skills_file: {path}") from exc

    return SeekProfileTemplate(
        archetype=archetype,
        headline=headline,
        summary=summary,
        skills=skills,
    )


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
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


class SeekProfileUpdater:
    """Automate switching Seek profile content for batching.

    Requires Playwright at runtime.
    """

    DEFAULT_PROFILE_URL = "https://www.seek.com.au/profile"
    DEFAULT_HOME_URL = "https://www.seek.com.au/"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        cfg = self.config.get("seek_profile", {}) or {}
        auto = cfg.get("automation", {}) or {}

        self.enabled = _truthy(auto.get("enabled"), False)
        self.headless = _truthy(auto.get("headless"), False)
        self.slow_mo_ms = _int(auto.get("slow_mo_ms"), 0)
        self.timeout_ms = _int(auto.get("timeout_ms"), 45_000)
        self.login_timeout_sec = _int(auto.get("login_timeout_sec"), 300)
        self.channel = str(auto.get("channel") or "chrome").strip() or None

        raw_dir = str(auto.get("user_data_dir") or "").strip()
        if raw_dir:
            self.user_data_dir = _expand_path(raw_dir)
        else:
            # Default to Selenium's shared Chrome profile to reuse Seek login.
            self.user_data_dir = (get_ronin_home() / "chrome_profile").resolve()

        self.profile_url = (
            str(auto.get("profile_url") or "").strip() or self.DEFAULT_PROFILE_URL
        )
        self.home_url = str(auto.get("home_url") or "").strip() or self.DEFAULT_HOME_URL
        self.selectors: Dict[str, str] = {}
        raw_selectors = auto.get("selectors")
        if isinstance(raw_selectors, dict):
            self.selectors = {str(k): str(v) for k, v in raw_selectors.items() if v}

        self.jitter = _truthy(auto.get("jitter"), True)
        self.min_delay_sec = float(auto.get("min_delay_sec") or 0.1)
        self.max_delay_sec = float(auto.get("max_delay_sec") or 0.5)

    def _match_entries_to_rows(
        self,
        entries: List[SeekCareerEntry],
        rows: List[Dict[str, Any]],
    ) -> List[tuple]:
        """Pair career entries with confirmed Seek career-history rows.

        A row matches an entry when either normalised company string contains
        the other, compared line by line — Seek may show a truncated company
        name, and the entry may carry the longer legal name. Rows flagged
        ``pending`` (resume-extracted suggestions awaiting confirmation) are
        never matched, and each row is claimed at most once.
        """

        def norm(s: Any) -> str:
            return re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower()).strip()

        matched: List[tuple] = []
        claimed: set = set()
        for entry in entries:
            company = norm(getattr(entry, "company", ""))
            if not company:
                continue
            for row in rows:
                if not isinstance(row, dict) or row.get("pending"):
                    continue
                row_key = str(row.get("auto_id") or id(row))
                if row_key in claimed:
                    continue
                lines = [
                    norm(line)
                    for line in str(row.get("text") or "").splitlines()
                    if norm(line)
                ]
                if any(company in line or line in company for line in lines):
                    matched.append((entry, row))
                    claimed.add(row_key)
                    break
        return matched

    def apply_archetype(
        self,
        archetype: str,
        template: Optional[SeekProfileTemplate] = None,
        *,
        dry_run: bool = False,
        allow_manual_login: bool = True,
    ) -> None:
        """Apply a profile template for an archetype."""
        archetype = str(archetype or "").strip().lower()
        template = template or load_template_from_config(self.config, archetype)
        if not (template.headline or template.summary or template.skills):
            raise SeekTemplateMissing(
                "No Seek profile template content found for archetype "
                f"{archetype!r}. Configure seek_profile.templates.<archetype> in config.yaml."
            )

        sync_playwright = None
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ModuleNotFoundError as exc:
            raise SeekProfileAutomationError(
                "Playwright is required for Seek profile automation. "
                "Install: pip install playwright && playwright install chromium"
            ) from exc

        # Best-effort locking strategy to avoid Chrome profile corruption.
        lock = None
        user_data_dir = self._resolve_user_data_dir_with_lock()
        try:
            lock = user_data_dir["lock"]
            profile_dir = user_data_dir["path"]

            with sync_playwright() as p:
                chromium = p.chromium
                context = None
                try:
                    context = chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        channel=self.channel,
                        headless=self.headless,
                        slow_mo=self.slow_mo_ms or None,
                        viewport={"width": 1280, "height": 900},
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                except Exception as exc:
                    if self.channel:
                        logger.warning(
                            "Playwright launch with channel=%r failed (%s); falling back to bundled chromium",
                            self.channel,
                            str(exc)[:200],
                        )
                        context = chromium.launch_persistent_context(
                            user_data_dir=str(profile_dir),
                            headless=self.headless,
                            slow_mo=self.slow_mo_ms or None,
                            viewport={"width": 1280, "height": 900},
                            args=["--disable-blink-features=AutomationControlled"],
                        )
                    else:
                        raise

                page = context.new_page()
                page.set_default_timeout(self.timeout_ms)

                # Navigate and ensure we are logged in.
                page.goto(self.profile_url, wait_until="domcontentloaded")
                if self._looks_like_login(page):
                    if not allow_manual_login:
                        raise SeekLoginRequired(
                            "Seek login required. Run in headful mode and log in once, "
                            "then retry."
                        )
                    if self.headless:
                        raise SeekLoginRequired(
                            "Seek login required but headless mode is enabled. "
                            "Set seek_profile.automation.headless: false and retry."
                        )
                    logger.warning(
                        "Seek login required. Complete login in the opened browser window (timeout: %ss)...",
                        self.login_timeout_sec,
                    )
                    if not self._wait_for_login(
                        page, timeout_sec=self.login_timeout_sec
                    ):
                        raise SeekLoginRequired(
                            "Seek login not detected before timeout. "
                            "Please log in within the opened browser window and retry."
                        )
                    page.goto(self.profile_url, wait_until="domcontentloaded")

                # Some profiles use a view page + edit CTA. Skip the heuristic
                # when field-level edit selectors are configured — on the
                # current profile page it matches unrelated "Edit ..." buttons
                # (visibility, personal details) and opens the wrong drawer.
                if not any(k.endswith("_edit_button") for k in self.selectors):
                    self._best_effort_enter_edit_mode(page)

                # Apply template.
                self._apply_template(page, template, dry_run=dry_run)

                # Ensure any navigation completes before closing.
                self._sleep_jitter()
                context.close()
        finally:
            if lock is not None:
                try:
                    lock.release()
                except Exception:
                    pass

    def debug_pause(self, url: str = "") -> None:
        """Open a headful browser and pause in Playwright Inspector.

        Use this to discover stable locators/selectors to place under:
        seek_profile.automation.selectors
        """
        url = str(url or "").strip() or self.profile_url

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ModuleNotFoundError as exc:
            raise SeekProfileAutomationError(
                "Playwright is required for Seek profile automation. "
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
                    args=["--disable-blink-features=AutomationControlled"],
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

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------

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
            # No locking available; proceed.
            return {"path": base_dir, "lock": _NoopLock()}

        try:
            lock = FileLock(str(lock_path), timeout=0)
            lock.acquire()
            return {"path": base_dir, "lock": lock}
        except Exception:
            # Fall back to a session-specific profile to avoid corruption.
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
        try:
            # Common buttons on Seek auth pages.
            login_btn = page.get_by_role(
                "button", name=re.compile(r"sign\s*in|log\s*in", re.IGNORECASE)
            )
            if login_btn.count() > 0 and login_btn.first.is_visible():
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

    def _best_effort_enter_edit_mode(self, page: Any) -> None:
        edit_sel = self.selectors.get("edit_profile_button")
        if edit_sel:
            try:
                page.locator(edit_sel).first.click(timeout=2500)
                self._sleep_jitter()
                return
            except Exception:
                pass

        # Heuristic: try a few common names.
        for label in ["Edit profile", "Edit", "Update profile"]:
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
                if btn.count() > 0:
                    btn.first.click(timeout=2000)
                    self._sleep_jitter()
                    return
            except Exception:
                continue

    def _apply_template(
        self, page: Any, template: SeekProfileTemplate, *, dry_run: bool
    ) -> None:
        failures: List[str] = []

        # Seek has no separate headline field — the headline is presented as
        # the first line of the personal summary. Combined text must stay
        # under Seek's 600-character limit for that field.
        summary_value = "\n\n".join(
            part
            for part in (template.headline.strip(), template.summary.strip())
            if part
        )
        if summary_value:
            if len(summary_value) > 600:
                logger.warning(
                    "Combined headline + summary is %d chars (Seek limit 600); "
                    "the save may be rejected",
                    len(summary_value),
                )
            ok = self._update_text_field(
                page,
                field_key="summary",
                value=summary_value,
                label_candidates=["Profile summary", "Summary", "About"],
                multiline=True,
                dry_run=dry_run,
            )
            if not ok:
                failures.append("summary")

        if template.skills:
            ok = self._update_skills(
                page,
                skills=template.skills,
                dry_run=dry_run,
            )
            if not ok:
                failures.append("skills")

        if failures:
            raise SeekProfileAutomationError(
                "Seek profile update failed for: "
                + ", ".join(failures)
                + ". Run `ronin profile debug` to capture selectors, then configure "
                "seek_profile.automation.selectors in config.yaml."
            )

    def _update_text_field(
        self,
        page: Any,
        *,
        field_key: str,
        value: str,
        label_candidates: Iterable[str],
        dry_run: bool,
        multiline: bool = False,
    ) -> bool:
        value = str(value or "").strip()
        if not value:
            return True

        edit_sel = self.selectors.get(f"{field_key}_edit_button")
        input_sel = self.selectors.get(f"{field_key}_input")
        save_sel = self.selectors.get(f"{field_key}_save_button")

        # 1) Enter edit for field.
        if edit_sel:
            try:
                page.locator(edit_sel).first.click(timeout=2500)
                self._sleep_jitter()
            except Exception:
                logger.debug("Failed clicking %s edit selector", field_key)

        # 2) Locate input.
        locator = None
        if input_sel:
            try:
                locator = page.locator(input_sel).first
            except Exception:
                locator = None

        if locator is None:
            locator = self._find_textbox_by_label(
                page, label_candidates, multiline=multiline
            )

        if locator is None:
            return False

        try:
            locator.wait_for(state="visible", timeout=5000)
        except Exception:
            return False

        if dry_run:
            logger.info("[dry-run] Would set %s", field_key)
            self._close_editor(page, field_key)
            return True

        try:
            locator.fill(value)
            self._sleep_jitter()
        except Exception as exc:
            logger.warning("Failed filling %s: %s", field_key, str(exc)[:200])
            return False

        # 3) Save.
        if save_sel:
            try:
                page.locator(save_sel).first.click(timeout=2500)
                self._sleep_jitter()
                return True
            except Exception:
                logger.debug("Failed clicking %s save selector", field_key)

        # Heuristic save button.
        for name in ["Save", "Done", "Update", "Confirm"]:
            try:
                btn = page.get_by_role("button", name=re.compile(name, re.IGNORECASE))
                if btn.count() > 0:
                    btn.first.click(timeout=2500)
                    self._sleep_jitter()
                    return True
            except Exception:
                continue

        return True  # Field may auto-save.

    def _find_textbox_by_label(
        self, page: Any, label_candidates: Iterable[str], *, multiline: bool
    ) -> Optional[Any]:
        # Prefer explicit labels when Seek uses them.
        for label in label_candidates:
            try:
                loc = page.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue

        # Fallback: role-based lookup.
        for label in label_candidates:
            try:
                loc = page.get_by_role(
                    "textbox", name=re.compile(re.escape(label), re.IGNORECASE)
                )
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue

        # Last resort: grab any textarea/input on the current form/dialog.
        try:
            dialog = page.locator("[role='dialog']").last
            if dialog.count() > 0:
                if multiline:
                    area = dialog.locator("textarea").first
                    if area.count() > 0:
                        return area
                else:
                    inp = dialog.locator("input").first
                    if inp.count() > 0:
                        return inp
        except Exception:
            pass
        return None

    def _update_skills(self, page: Any, *, skills: List[str], dry_run: bool) -> bool:
        skills = [s.strip() for s in (skills or []) if str(s).strip()]
        if not skills:
            return True

        edit_sel = self.selectors.get("skills_edit_button")
        input_sel = self.selectors.get("skills_input")
        save_sel = self.selectors.get("skills_save_button")
        clear_sel = self.selectors.get("skills_clear_button")
        remove_sel = self.selectors.get("skills_remove_buttons")
        add_sel = self.selectors.get("skills_add_button")

        if edit_sel:
            try:
                page.locator(edit_sel).first.click(timeout=2500)
                self._sleep_jitter()
            except Exception:
                pass
        else:
            # Heuristic: click an Edit button near a Skills heading.
            try:
                heading = page.get_by_role("heading", name=re.compile("skills", re.I))
                if heading.count() > 0:
                    container = heading.first.locator(
                        "xpath=ancestor-or-self::*[self::section or self::div][1]"
                    )
                    btn = container.get_by_role("button", name=re.compile("edit", re.I))
                    if btn.count() > 0:
                        btn.first.click(timeout=2500)
                        self._sleep_jitter()
            except Exception:
                pass

        # Locate input.
        skill_input = None
        if input_sel:
            try:
                skill_input = page.locator(input_sel).first
            except Exception:
                skill_input = None

        if skill_input is None:
            # Try label/placeholder based matching.
            for label in ["Skills", "Add a skill", "Add skills", "Key skills"]:
                try:
                    loc = page.get_by_label(re.compile(label, re.I))
                    if loc.count() > 0:
                        skill_input = loc.first
                        break
                except Exception:
                    continue
            if skill_input is None:
                try:
                    loc = page.get_by_placeholder(re.compile("skill", re.I))
                    if loc.count() > 0:
                        skill_input = loc.first
                except Exception:
                    pass

        if skill_input is None:
            return False

        try:
            skill_input.wait_for(state="visible", timeout=5000)
        except Exception:
            return False

        if dry_run:
            logger.info("[dry-run] Would set skills (%d entries)", len(skills))
            self._close_editor(page, "skills")
            return True

        # Best-effort clear.
        if clear_sel:
            try:
                page.locator(clear_sel).first.click(timeout=2000)
                self._sleep_jitter()
            except Exception:
                pass
        if remove_sel:
            try:
                buttons = page.locator(remove_sel)
                for _ in range(min(50, buttons.count())):
                    try:
                        buttons.first.click(timeout=1000)
                        self._sleep_jitter(base=0.05)
                    except Exception:
                        break
            except Exception:
                pass
        else:
            # Heuristic: remove buttons inside a dialog.
            try:
                dialog = page.locator("[role='dialog']").last
                if dialog.count() > 0:
                    rm = dialog.get_by_role(
                        "button", name=re.compile("remove|delete|clear", re.I)
                    )
                    for _ in range(min(50, rm.count())):
                        try:
                            rm.nth(0).click(timeout=800)
                            self._sleep_jitter(base=0.05)
                        except Exception:
                            break
            except Exception:
                pass

        # Add skills. Seek's tag input is a combobox with an explicit Add
        # button; Enter is the fallback when no add selector is configured.
        for skill in skills:
            try:
                skill_input.click(timeout=1000)
                skill_input.fill("")
                skill_input.type(skill, delay=40)
                self._sleep_jitter(base=0.1)
                if add_sel:
                    try:
                        page.locator(add_sel).first.click(timeout=1500)
                    except Exception:
                        page.keyboard.press("Enter")
                else:
                    page.keyboard.press("Enter")
                self._sleep_jitter(base=0.15)
            except Exception as exc:
                logger.warning("Failed adding skill %r: %s", skill, str(exc)[:200])

        # Save.
        if save_sel:
            try:
                page.locator(save_sel).first.click(timeout=2500)
                self._sleep_jitter()
                return True
            except Exception:
                pass

        for name in ["Save", "Done", "Update", "Confirm"]:
            try:
                btn = page.get_by_role("button", name=re.compile(name, re.I))
                if btn.count() > 0:
                    btn.first.click(timeout=2500)
                    self._sleep_jitter()
                    return True
            except Exception:
                continue

        return True

    def _close_editor(self, page: Any, field_key: str) -> None:
        """Close an open edit drawer without saving (used by dry runs).

        A drawer left open overlays the page and blocks the next field's edit
        control, so every dry-run field visit must close what it opened.
        """
        cancel_sel = self.selectors.get(f"{field_key}_cancel_button")
        if cancel_sel:
            try:
                page.locator(cancel_sel).first.click(timeout=2000)
                self._sleep_jitter()
                return
            except Exception:
                pass
        try:
            page.keyboard.press("Escape")
            self._sleep_jitter()
        except Exception:
            pass

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
