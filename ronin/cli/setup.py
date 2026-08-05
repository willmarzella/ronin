#!/usr/bin/env python3
"""Textual TUI setup wizard for Ronin.

Guides the user through complete configuration, writing profile.yaml,
config.yaml, .env, and resume files to ~/.ronin/ (or RONIN_HOME).

Usage:
    ronin setup              # Full wizard
    ronin setup --step personal  # Jump to a specific step
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Optional

import yaml
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
    TextArea,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RONIN_HOME = Path(os.environ.get("RONIN_HOME", Path.home() / ".ronin"))

STEP_ORDER = [
    "welcome",
    "personal",
    "work_rights",
    "professional",
    "preferences",
    "resumes",
    "cover_letter",
    "search",
    "boards",
    "api_keys",
    "browser",
    "schedule",
    "review",
]

STEP_SCREEN_MAP: dict[str, type[Screen]] = {}  # populated by _register decorator


def _register(name: str):
    """Class decorator that registers a screen in STEP_SCREEN_MAP."""

    def decorator(cls):
        STEP_SCREEN_MAP[name] = cls
        cls.step_name = name
        return cls

    return decorator


# ---------------------------------------------------------------------------
# Shared navigation footer
# ---------------------------------------------------------------------------


class NavFooter(Horizontal):
    """Back / Next buttons shown at the bottom of every wizard screen."""

    DEFAULT_CSS = """
    NavFooter {
        dock: bottom;
        height: 3;
        padding: 0 1;
        align: center middle;
    }
    NavFooter Button {
        margin: 0 1;
    }
    """

    def __init__(self, show_back: bool = True, next_label: str = "Next"):
        super().__init__()
        self._show_back = show_back
        self._next_label = next_label

    def compose(self) -> ComposeResult:
        if self._show_back:
            yield Button("Back", id="nav_back", variant="default")
        yield Button(self._next_label, id="nav_next", variant="primary")


# ---------------------------------------------------------------------------
# Screen implementations
# ---------------------------------------------------------------------------


@_register("welcome")
class WelcomeScreen(Screen):
    """Welcome screen with ASCII art and prerequisites checklist."""

    BINDINGS = [Binding("enter", "next", "Next")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            Static(
                """\
 ____   ___  _   _ ___ _   _
|  _ \\ / _ \\| \\ | |_ _| \\ | |
| |_) | | | |  \\| || ||  \\| |
|  _ <| |_| | |\\  || || |\\  |
|_| \\_\\\\___/|_| \\_|___|_| \\_|

Automated Job Search & Application
""",
                classes="ascii-art",
            ),
            Static(
                "This wizard will configure Ronin to search job boards, "
                "analyse listings with AI, and apply on your behalf.\n\n"
                "It will create the following files in "
                f"[bold]{RONIN_HOME}[/bold]:\n"
                "  - profile.yaml  (your personal info, skills, preferences)\n"
                "  - config.yaml   (search parameters, runtime settings)\n"
                "  - .env          (API keys)\n"
                "  - resumes/      (plain-text resume files)\n"
                "  - assets/       (cover letter examples, highlights)\n",
            ),
            Static("[bold]Prerequisites[/bold]", classes="section-header"),
            Static(
                "  - Python 3.11+\n"
                "  - Google Chrome (or Chrome for Testing)\n"
                "  - An Anthropic or OpenAI API key\n"
                "  - A Seek.com.au account with uploaded resumes\n",
            ),
            Static(
                "[dim]Press Enter or click Next to begin.[/dim]",
            ),
            NavFooter(show_back=False),
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.action_next_step()

    def action_next(self) -> None:
        self.app.action_next_step()


@_register("personal")
class PersonalInfoScreen(Screen):
    """Collect name, email, phone, location."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("personal", {})
        yield Header()
        yield ScrollableContainer(
            Static("[bold]Personal Information[/bold]\n", classes="section-header"),
            Label("Full name"),
            Input(value=data.get("name", ""), placeholder="Jane Smith", id="name"),
            Label("Email"),
            Input(
                value=data.get("email", ""),
                placeholder="jane@example.com",
                id="email",
            ),
            Label("Phone"),
            Input(
                value=data.get("phone", ""),
                placeholder="+61 400 000 000",
                id="phone",
            ),
            Label("Location"),
            Input(
                value=data.get("location", ""),
                placeholder="Melbourne, Australia",
                id="location",
            ),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        return {
            "name": self.query_one("#name", Input).value.strip(),
            "email": self.query_one("#email", Input).value.strip(),
            "phone": self.query_one("#phone", Input).value.strip(),
            "location": self.query_one("#location", Input).value.strip(),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["personal"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["personal"] = self._collect()
            self.app.action_prev_step()


@_register("work_rights")
class WorkRightsScreen(Screen):
    """Citizenship, visa, clearances, etc."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("work_rights", {})
        yield Header()
        yield ScrollableContainer(
            Static("[bold]Work Rights & Legal[/bold]\n", classes="section-header"),
            Label("Citizenship"),
            Input(
                value=data.get("citizenship", ""),
                placeholder="Australian citizen",
                id="citizenship",
            ),
            Label("Visa status"),
            Input(
                value=data.get("visa_status", ""),
                placeholder="Full working rights",
                id="visa_status",
            ),
            Checkbox(
                "I have a current driver's licence",
                value=data.get("has_drivers_license", False),
                id="has_drivers_license",
            ),
            Label("Security clearances (comma-separated, leave blank if none)"),
            Input(
                value=", ".join(data.get("security_clearances", [])),
                placeholder="NV1, NV2",
                id="security_clearances",
            ),
            Checkbox(
                "Willing to obtain security clearance",
                value=data.get("willing_to_obtain_clearance", False),
                id="willing_to_obtain_clearance",
            ),
            Checkbox(
                "Willing to relocate",
                value=data.get("willing_to_relocate", False),
                id="willing_to_relocate",
            ),
            Checkbox(
                "Willing to travel",
                value=data.get("willing_to_travel", False),
                id="willing_to_travel",
            ),
            Label("Police check"),
            Select(
                [
                    ("Willing to undergo", "Willing to undergo"),
                    ("Current", "Current"),
                    ("Not willing", "Not willing"),
                ],
                value=data.get("police_check", "Willing to undergo"),
                id="police_check",
            ),
            Label("Notice period"),
            Input(
                value=data.get("notice_period", ""),
                placeholder="2 weeks",
                id="notice_period",
            ),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        raw_clearances = self.query_one("#security_clearances", Input).value.strip()
        clearances = [c.strip() for c in raw_clearances.split(",") if c.strip()]
        return {
            "citizenship": self.query_one("#citizenship", Input).value.strip(),
            "visa_status": self.query_one("#visa_status", Input).value.strip(),
            "has_drivers_license": self.query_one(
                "#has_drivers_license", Checkbox
            ).value,
            "security_clearances": clearances,
            "willing_to_obtain_clearance": self.query_one(
                "#willing_to_obtain_clearance", Checkbox
            ).value,
            "willing_to_relocate": self.query_one(
                "#willing_to_relocate", Checkbox
            ).value,
            "willing_to_travel": self.query_one("#willing_to_travel", Checkbox).value,
            "police_check": self.query_one("#police_check", Select).value,
            "notice_period": self.query_one("#notice_period", Input).value.strip(),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["work_rights"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["work_rights"] = self._collect()
            self.app.action_prev_step()


@_register("professional")
class ProfessionalScreen(Screen):
    """Job title, experience, salary, skills by category."""

    DEFAULT_CATEGORIES = [
        "core_skills",
        "tools_and_software",
        "certifications",
        "interpersonal",
    ]

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("professional", {})
        skills = data.get("skills", {})
        yield Header()
        yield ScrollableContainer(
            Static("[bold]Professional Profile[/bold]\n", classes="section-header"),
            Label("Job title"),
            Input(
                value=data.get("title", ""),
                placeholder="e.g. Marketing Manager, Nurse, Software Engineer",
                id="title",
            ),
            Label("Years of experience"),
            Input(
                value=str(data.get("years_experience", "")),
                placeholder="5",
                id="years_experience",
            ),
            Label("Minimum salary"),
            Input(
                value=str(data.get("salary_min", "")),
                placeholder="e.g. 60000",
                id="salary_min",
            ),
            Label("Maximum salary"),
            Input(
                value=str(data.get("salary_max", "")),
                placeholder="e.g. 90000",
                id="salary_max",
            ),
            Label("Salary currency"),
            Select(
                [
                    ("AUD", "AUD"),
                    ("USD", "USD"),
                    ("GBP", "GBP"),
                    ("EUR", "EUR"),
                ],
                value=data.get("salary_currency", "AUD"),
                id="salary_currency",
            ),
            Static(
                "\n[bold]Skills[/bold] [dim](comma-separated per category)[/dim]\n"
                "[dim]Define your own categories below. Add or rename "
                "categories to fit your profession.[/dim]\n",
            ),
            *self._skill_widgets(skills),
            Button(
                "+ Add skill category",
                id="add_skill_cat",
                variant="default",
            ),
            NavFooter(),
        )
        yield Footer()

    def _skill_widgets(self, skills: dict):
        widgets = []
        # Use existing categories from profile, or defaults for new users
        categories = list(skills.keys()) if skills else self.DEFAULT_CATEGORIES
        self._current_categories = categories
        for cat in categories:
            existing = ", ".join(skills.get(cat, []))
            display_name = cat.replace("_", " ").title()
            widgets.append(Label(display_name))
            widgets.append(
                TextArea(
                    text=existing,
                    id=f"skill_{cat}",
                )
            )
        return widgets

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add_skill_cat":
            # Add a new empty category with a generated name
            idx = len(self._current_categories) + 1
            new_cat = f"category_{idx}"
            self._current_categories.append(new_cat)
            container = self.query_one(ScrollableContainer)
            display_name = f"Category {idx} (rename in profile.yaml)"
            container.mount(Label(display_name), before="#add_skill_cat")
            container.mount(
                TextArea(text="", id=f"skill_{new_cat}"),
                before="#add_skill_cat",
            )
        elif event.button.id == "nav_next":
            self.app.wizard_data["professional"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["professional"] = self._collect()
            self.app.action_prev_step()

    def _collect(self) -> dict:
        skills: dict[str, list[str]] = {}
        for cat in self._current_categories:
            raw = self.query_one(f"#skill_{cat}", TextArea).text.strip()
            skills[cat] = [s.strip() for s in raw.split(",") if s.strip()]

        def _int_or(val: str, default: int = 0) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        return {
            "title": self.query_one("#title", Input).value.strip(),
            "years_experience": _int_or(
                self.query_one("#years_experience", Input).value
            ),
            "salary_min": _int_or(self.query_one("#salary_min", Input).value),
            "salary_max": _int_or(self.query_one("#salary_max", Input).value),
            "salary_currency": self.query_one("#salary_currency", Select).value,
            "skills": skills,
        }


@_register("preferences")
class PreferencesScreen(Screen):
    """High-value signals, red flags, work type and arrangement preferences."""

    WORK_TYPES = ["contract", "full-time", "consulting", "permanent", "part-time"]
    ARRANGEMENTS = ["remote", "hybrid", "onsite"]

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("preferences", {})
        yield Header()
        yield ScrollableContainer(
            Static("[bold]Preferences[/bold]\n", classes="section-header"),
            Label("High-value signals (one per line)"),
            TextArea(
                text="\n".join(data.get("high_value_signals", [])),
                id="high_value_signals",
            ),
            Label("Red flags (one per line)"),
            TextArea(
                text="\n".join(data.get("red_flags", [])),
                id="red_flags",
            ),
            Static("\n[bold]Preferred work types[/bold]"),
            *[
                Checkbox(
                    wt,
                    value=wt in data.get("preferred_work_types", []),
                    id=f"wt_{wt.replace('-', '_')}",
                )
                for wt in self.WORK_TYPES
            ],
            Static("\n[bold]Preferred arrangements[/bold]"),
            *[
                Checkbox(
                    arr,
                    value=arr in data.get("preferred_arrangements", []),
                    id=f"arr_{arr}",
                )
                for arr in self.ARRANGEMENTS
            ],
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        def _lines(widget_id: str) -> list[str]:
            raw = self.query_one(f"#{widget_id}", TextArea).text.strip()
            return [line.strip() for line in raw.splitlines() if line.strip()]

        work_types = [
            wt
            for wt in self.WORK_TYPES
            if self.query_one(f"#wt_{wt.replace('-', '_')}", Checkbox).value
        ]
        arrangements = [
            arr
            for arr in self.ARRANGEMENTS
            if self.query_one(f"#arr_{arr}", Checkbox).value
        ]
        return {
            "high_value_signals": _lines("high_value_signals"),
            "red_flags": _lines("red_flags"),
            "preferred_work_types": work_types,
            "preferred_arrangements": arrangements,
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["preferences"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["preferences"] = self._collect()
            self.app.action_prev_step()


@_register("resumes")
class ResumesScreen(Screen):
    """Create one or more resume profiles with text content."""

    JOB_TYPES = ["contract", "full-time", "consulting", "permanent", "part-time"]

    def __init__(self):
        super().__init__()
        self._resume_count = 0

    def compose(self) -> ComposeResult:
        existing = self.app.wizard_data.get("resumes", [])
        if not existing:
            existing = [{"name": "default", "job_types": [], "text": ""}]
        yield Header()
        container = ScrollableContainer(id="resumes_container")
        with container:
            yield Static("[bold]Resume Profiles[/bold]\n", classes="section-header")
            yield Static(
                "Define one or more resume profiles. Each is a plain-text resume "
                "that Ronin selects based on job type.\n"
                "[dim]Tip: if you use names expansion, consolidation, adaptation, "
                "aspiration, Ronin maps those to archetype-aware matching.[/dim]\n"
            )
            for i, res in enumerate(existing):
                yield from self._resume_widgets(i, res)
                self._resume_count = i + 1
            yield Button(
                "+ Add another resume",
                id="add_resume",
                variant="default",
            )
            yield NavFooter()
        yield container
        yield Footer()

    def _resume_widgets(self, index: int, data: dict):
        prefix = f"res{index}"
        yield Static(f"\n[bold]Resume #{index + 1}[/bold]")
        yield Label("Profile name")
        yield Input(
            value=data.get("name", ""),
            placeholder="default",
            id=f"{prefix}_name",
        )
        yield Label("Matches job types")
        for jt in self.JOB_TYPES:
            yield Checkbox(
                jt,
                value=jt in data.get("job_types", []),
                id=f"{prefix}_jt_{jt.replace('-', '_')}",
            )
        yield Label("Resume text (paste full plain-text resume)")
        yield TextArea(
            text=data.get("text", ""),
            id=f"{prefix}_text",
        )

    def _collect_one(self, index: int) -> dict:
        prefix = f"res{index}"
        job_types = [
            jt
            for jt in self.JOB_TYPES
            if self.query_one(f"#{prefix}_jt_{jt.replace('-', '_')}", Checkbox).value
        ]
        return {
            "name": self.query_one(f"#{prefix}_name", Input).value.strip()
            or f"resume_{index}",
            "job_types": job_types,
            "text": self.query_one(f"#{prefix}_text", TextArea).text,
        }

    def _collect_all(self) -> list[dict]:
        return [self._collect_one(i) for i in range(self._resume_count)]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add_resume":
            # Save current, add blank, re-mount
            self.app.wizard_data["resumes"] = self._collect_all()
            self.app.wizard_data["resumes"].append(
                {"name": "", "job_types": [], "text": ""}
            )
            self.app.push_screen(ResumesScreen())
        elif event.button.id == "nav_next":
            self.app.wizard_data["resumes"] = self._collect_all()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["resumes"] = self._collect_all()
            self.app.action_prev_step()


@_register("cover_letter")
class CoverLetterScreen(Screen):
    """Cover letter generation settings."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("cover_letter", {})
        yield Header()
        yield ScrollableContainer(
            Static(
                "[bold]Cover Letter Configuration[/bold]\n", classes="section-header"
            ),
            Label("Tone"),
            Select(
                [
                    ("Casual professional", "casual professional"),
                    ("Formal", "formal"),
                    ("Conversational", "conversational"),
                ],
                value=data.get("tone", "casual professional"),
                id="tone",
            ),
            Label("Max words"),
            Input(
                value=str(data.get("max_words", 150)),
                placeholder="150",
                id="max_words",
            ),
            Label("Spelling convention"),
            Select(
                [
                    ("Australian English", "Australian English"),
                    ("American English", "American English"),
                    ("British English", "British English"),
                ],
                value=data.get("spelling", "Australian English"),
                id="spelling",
            ),
            Label("Anti-slop rules (one per line)"),
            TextArea(
                text="\n".join(data.get("anti_slop_rules", [])),
                id="anti_slop_rules",
            ),
            Label("Contract framing (how to frame cover letters for contract roles)"),
            TextArea(
                text=data.get("contract_framing", ""),
                id="contract_framing",
            ),
            Label("Full-time framing (how to frame cover letters for permanent roles)"),
            TextArea(
                text=data.get("fulltime_framing", ""),
                id="fulltime_framing",
            ),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        def _int_or(val: str, default: int) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        raw_rules = self.query_one("#anti_slop_rules", TextArea).text.strip()
        rules = [r.strip() for r in raw_rules.splitlines() if r.strip()]
        return {
            "tone": self.query_one("#tone", Select).value,
            "max_words": _int_or(self.query_one("#max_words", Input).value, 150),
            "spelling": self.query_one("#spelling", Select).value,
            "anti_slop_rules": rules,
            "contract_framing": self.query_one(
                "#contract_framing", TextArea
            ).text.strip(),
            "fulltime_framing": self.query_one(
                "#fulltime_framing", TextArea
            ).text.strip(),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["cover_letter"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["cover_letter"] = self._collect()
            self.app.action_prev_step()


@_register("search")
class SearchConfigScreen(Screen):
    """Search keywords, location, date range, salary bounds."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("search", {})
        salary = data.get("salary", {})
        yield Header()
        yield ScrollableContainer(
            Static("[bold]Search Configuration[/bold]\n", classes="section-header"),
            Label(
                "Keywords (one per line, use Seek format: "
                '\'"job title"-or-"job titles"\')'
            ),
            TextArea(
                text="\n".join(data.get("keywords", [])),
                id="keywords",
            ),
            Label("Location"),
            Input(
                value=data.get("location", ""),
                placeholder="All-Australia",
                id="search_location",
            ),
            Label("Date range (days to look back)"),
            Input(
                value=str(data.get("date_range", 2)),
                placeholder="2",
                id="date_range",
            ),
            Label("Salary minimum"),
            Input(
                value=str(salary.get("min", 0)),
                placeholder="0",
                id="salary_min",
            ),
            Label("Salary maximum"),
            Input(
                value=str(salary.get("max", 400000)),
                placeholder="400000",
                id="salary_max",
            ),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        def _int_or(val: str, default: int) -> int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return default

        raw_kw = self.query_one("#keywords", TextArea).text.strip()
        keywords = [k.strip() for k in raw_kw.splitlines() if k.strip()]
        return {
            "keywords": keywords,
            "location": self.query_one("#search_location", Input).value.strip(),
            "date_range": _int_or(self.query_one("#date_range", Input).value, 2),
            "salary": {
                "min": _int_or(self.query_one("#salary_min", Input).value, 0),
                "max": _int_or(self.query_one("#salary_max", Input).value, 400000),
            },
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["search"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["search"] = self._collect()
            self.app.action_prev_step()


@_register("boards")
class BoardSetupScreen(Screen):
    """Link Seek resume IDs to each resume profile."""

    def compose(self) -> ComposeResult:
        resumes = self.app.wizard_data.get("resumes", [])
        board_data = self.app.wizard_data.get("boards", {})
        yield Header()
        container = ScrollableContainer()
        with container:
            yield Static("[bold]Job Board Setup[/bold]\n", classes="section-header")
            yield Static(
                "[bold]Seek.com.au[/bold]\n"
                "1. Go to seek.com.au and log in\n"
                "2. Upload your resumes under Profile > Resumes\n"
                "3. Copy the resume ID from the URL when viewing each resume\n"
                "   (e.g. https://www.seek.com.au/profile/resumes/[bold]THIS-UUID[/bold])\n"
                "4. Paste the ID below for each resume profile\n"
            )
            if not resumes:
                yield Static(
                    "[yellow]No resume profiles defined yet. "
                    "Go back to the Resumes step first.[/yellow]"
                )
            else:
                for i, res in enumerate(resumes):
                    name = res.get("name", f"resume_{i}")
                    existing_id = board_data.get(f"seek_{name}", "")
                    yield Label(f'Seek resume ID for "{name}"')
                    yield Input(
                        value=existing_id,
                        placeholder="paste-uuid-here",
                        id=f"seek_id_{i}",
                    )
            yield NavFooter()
        yield container
        yield Footer()

    def _collect(self) -> dict:
        resumes = self.app.wizard_data.get("resumes", [])
        board_data = {}
        for i, res in enumerate(resumes):
            name = res.get("name", f"resume_{i}")
            try:
                val = self.query_one(f"#seek_id_{i}", Input).value.strip()
            except Exception:
                val = ""
            board_data[f"seek_{name}"] = val
        return board_data

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["boards"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["boards"] = self._collect()
            self.app.action_prev_step()


@_register("api_keys")
class APIKeysScreen(Screen):
    """API key entry and optional connection test."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("api_keys", {})
        yield Header()
        yield ScrollableContainer(
            Static("[bold]API Keys[/bold]\n", classes="section-header"),
            Static(
                "These are stored in [bold]~/.ronin/.env[/bold] and never "
                "committed to version control.\n"
            ),
            Label("Anthropic API key"),
            Input(
                value=data.get("ANTHROPIC_API_KEY", ""),
                placeholder="sk-ant-...",
                password=True,
                id="anthropic_key",
            ),
            Label("OpenAI API key"),
            Input(
                value=data.get("OPENAI_API_KEY", ""),
                placeholder="sk-...",
                password=True,
                id="openai_key",
            ),
            Label("Slack webhook URL (optional)"),
            Input(
                value=data.get("SLACK_WEBHOOK_URL", ""),
                placeholder="https://hooks.slack.com/services/...",
                id="slack_webhook",
            ),
            Static(""),
            Button("Test Connection", id="test_connection", variant="warning"),
            Static("", id="test_result"),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        return {
            "ANTHROPIC_API_KEY": self.query_one("#anthropic_key", Input).value.strip(),
            "OPENAI_API_KEY": self.query_one("#openai_key", Input).value.strip(),
            "SLACK_WEBHOOK_URL": self.query_one("#slack_webhook", Input).value.strip(),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test_connection":
            self._test_keys()
        elif event.button.id == "nav_next":
            self.app.wizard_data["api_keys"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["api_keys"] = self._collect()
            self.app.action_prev_step()

    def _test_keys(self) -> None:
        result_widget = self.query_one("#test_result", Static)
        keys = self._collect()
        results: list[str] = []

        anthropic_key = keys.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            try:
                import anthropic

                client = anthropic.Anthropic(api_key=anthropic_key)
                client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}],
                )
                results.append("[green]Anthropic: OK[/green]")
            except Exception as exc:
                results.append(f"[red]Anthropic: {exc}[/red]")
        else:
            results.append("[yellow]Anthropic: skipped (no key)[/yellow]")

        openai_key = keys.get("OPENAI_API_KEY", "")
        if openai_key:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=openai_key)
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}],
                )
                results.append("[green]OpenAI: OK[/green]")
            except Exception as exc:
                results.append(f"[red]OpenAI: {exc}[/red]")
        else:
            results.append("[yellow]OpenAI: skipped (no key)[/yellow]")

        result_widget.update("\n".join(results))


@_register("browser")
class BrowserScreen(Screen):
    """Choose between system Chrome and Chrome for Testing."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("browser", {})
        current_mode = data.get("mode", "system")

        # Auto-detect Chrome path
        detected = _detect_chrome_path()

        yield Header()
        yield ScrollableContainer(
            Static("[bold]Browser Configuration[/bold]\n", classes="section-header"),
            Label("Chrome mode"),
            RadioSet(
                RadioButton(
                    "Use system Chrome (recommended)",
                    value=current_mode == "system",
                    id="mode_system",
                ),
                RadioButton(
                    "Download Chrome for Testing",
                    value=current_mode == "testing",
                    id="mode_testing",
                ),
                id="browser_mode",
            ),
            Static(
                f"\n[dim]Auto-detected Chrome path:[/dim] "
                f"{'[green]' + detected + '[/green]' if detected else '[yellow]not found[/yellow]'}"
            ),
            Label("Chrome path override (leave blank for auto-detection)"),
            Input(
                value=data.get("chrome_path", ""),
                placeholder="/Applications/Google Chrome.app/...",
                id="chrome_path",
            ),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        radio_set = self.query_one("#browser_mode", RadioSet)
        mode = "system"
        if radio_set.pressed_index == 1:
            mode = "testing"
        return {
            "mode": mode,
            "chrome_path": self.query_one("#chrome_path", Input).value.strip(),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["browser"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["browser"] = self._collect()
            self.app.action_prev_step()


@_register("schedule")
class ScheduleScreen(Screen):
    """Configure automated search schedule."""

    def compose(self) -> ComposeResult:
        data = self.app.wizard_data.get("schedule", {})
        plat = platform.system()
        scheduler_desc = {
            "Darwin": "launchd (macOS LaunchAgent)",
            "Windows": "Task Scheduler",
            "Linux": "crontab",
        }.get(plat, "cron")

        yield Header()
        yield ScrollableContainer(
            Static("[bold]Scheduled Search[/bold]\n", classes="section-header"),
            Static(
                f"Platform: [bold]{plat}[/bold] — "
                f"will use [bold]{scheduler_desc}[/bold]\n"
            ),
            Checkbox(
                "Enable scheduled search",
                value=data.get("enabled", False),
                id="schedule_enabled",
            ),
            Label("Interval (hours)"),
            Input(
                value=str(data.get("interval_hours", 2)),
                placeholder="2",
                id="interval_hours",
            ),
            Static(
                "\n[dim]When enabled, Ronin will automatically run "
                "'ronin search' at the configured interval.[/dim]"
            ),
            NavFooter(),
        )
        yield Footer()

    def _collect(self) -> dict:
        def _int_or(val: str, default: int) -> int:
            try:
                return max(1, int(val))
            except (ValueError, TypeError):
                return default

        return {
            "enabled": self.query_one("#schedule_enabled", Checkbox).value,
            "interval_hours": _int_or(
                self.query_one("#interval_hours", Input).value, 2
            ),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self.app.wizard_data["schedule"] = self._collect()
            self.app.action_next_step()
        elif event.button.id == "nav_back":
            self.app.wizard_data["schedule"] = self._collect()
            self.app.action_prev_step()


@_register("review")
class ReviewScreen(Screen):
    """Show a summary of all configuration, then save."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield ScrollableContainer(
            Static("[bold]Review & Save[/bold]\n", classes="section-header"),
            Static(f"Files will be written to [bold]{RONIN_HOME}[/bold]\n"),
            RichLog(id="review_log", wrap=True, markup=True),
            Static(""),
            NavFooter(next_label="Save & Finish"),
        )
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#review_log", RichLog)
        data = self.app.wizard_data

        # Personal
        personal = data.get("personal", {})
        log.write("[bold]Personal[/bold]")
        for k, v in personal.items():
            log.write(f"  {k}: {v}")

        # Work rights
        wr = data.get("work_rights", {})
        log.write("\n[bold]Work Rights[/bold]")
        for k, v in wr.items():
            log.write(f"  {k}: {v}")

        # Professional
        prof = data.get("professional", {})
        log.write("\n[bold]Professional[/bold]")
        for k, v in prof.items():
            if k == "skills":
                log.write("  skills:")
                for cat, items in v.items():
                    log.write(f"    {cat}: {', '.join(items) if items else '(none)'}")
            else:
                log.write(f"  {k}: {v}")

        # Preferences
        prefs = data.get("preferences", {})
        log.write("\n[bold]Preferences[/bold]")
        for k, v in prefs.items():
            if isinstance(v, list):
                log.write(f"  {k}: {', '.join(v) if v else '(none)'}")
            else:
                log.write(f"  {k}: {v}")

        # Resumes
        resumes = data.get("resumes", [])
        log.write(f"\n[bold]Resumes[/bold] ({len(resumes)} profile(s))")
        for r in resumes:
            name = r.get("name", "unnamed")
            jt = ", ".join(r.get("job_types", []))
            text_len = len(r.get("text", ""))
            log.write(f"  {name} — types: {jt or '(none)'}, text: {text_len} chars")

        # Cover letter
        cl = data.get("cover_letter", {})
        log.write("\n[bold]Cover Letter[/bold]")
        for k, v in cl.items():
            if isinstance(v, list):
                log.write(f"  {k}: {', '.join(v) if v else '(none)'}")
            else:
                display = str(v)[:80]
                log.write(f"  {k}: {display}")

        # Search
        search = data.get("search", {})
        log.write("\n[bold]Search[/bold]")
        for k, v in search.items():
            if isinstance(v, list):
                for item in v:
                    log.write(f"  keyword: {item}")
            elif isinstance(v, dict):
                for sk, sv in v.items():
                    log.write(f"  {k}.{sk}: {sv}")
            else:
                log.write(f"  {k}: {v}")

        # Boards
        boards = data.get("boards", {})
        log.write("\n[bold]Boards[/bold]")
        if boards:
            for k, v in boards.items():
                log.write(f"  {k}: {v or '(not set)'}")
        else:
            log.write("  (no board IDs configured)")

        # API Keys
        api = data.get("api_keys", {})
        log.write("\n[bold]API Keys[/bold]")
        for k, v in api.items():
            masked = v[:8] + "..." if v and len(v) > 8 else "(not set)"
            log.write(f"  {k}: {masked}")

        # Browser
        browser = data.get("browser", {})
        log.write("\n[bold]Browser[/bold]")
        log.write(f"  mode: {browser.get('mode', 'system')}")
        log.write(f"  chrome_path: {browser.get('chrome_path', '(auto-detect)')}")

        # Schedule
        sched = data.get("schedule", {})
        log.write("\n[bold]Schedule[/bold]")
        log.write(f"  enabled: {sched.get('enabled', False)}")
        log.write(f"  interval_hours: {sched.get('interval_hours', 2)}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav_next":
            self._save_all()
        elif event.button.id == "nav_back":
            self.app.action_prev_step()

    def _save_all(self) -> None:
        """Write profile.yaml, config.yaml, .env, and resume files."""
        data = self.app.wizard_data

        # Ensure directories exist
        for subdir in ["", "resumes", "assets", "data", "logs"]:
            (RONIN_HOME / subdir).mkdir(parents=True, exist_ok=True)

        # -- profile.yaml --
        boards = data.get("boards", {})
        resumes_list = []
        valid_archetypes = {
            "expansion",
            "consolidation",
            "adaptation",
            "aspiration",
        }
        for res in data.get("resumes", []):
            name = res.get("name", "default")
            filename = name.replace(" ", "_") + ".txt"
            seek_id = boards.get(f"seek_{name}", "")
            archetype = str(res.get("archetype", "")).strip().lower()
            if archetype not in valid_archetypes:
                inferred = name.strip().lower()
                archetype = inferred if inferred in valid_archetypes else "adaptation"
            resumes_list.append(
                {
                    "name": name,
                    "file": filename,
                    "seek_resume_id": seek_id,
                    "archetype": archetype,
                    "hiring_signal": str(res.get("hiring_signal", "")).strip(),
                    "role_title_patterns": list(res.get("role_title_patterns", [])),
                    "keyword_bias": list(res.get("keyword_bias", [])),
                    "use_when": {
                        "job_types": res.get("job_types", []),
                        "description": "",
                    },
                }
            )

        prefs = data.get("preferences", {})

        professional = dict(data.get("professional", {}))
        professional["preferences"] = {
            "high_value_signals": prefs.get("high_value_signals", []),
            "red_flags": prefs.get("red_flags", []),
            "preferred_work_types": prefs.get("preferred_work_types", []),
            "preferred_arrangements": prefs.get("preferred_arrangements", []),
        }

        profile = {
            "personal": data.get("personal", {}),
            "work_rights": data.get("work_rights", {}),
            "professional": professional,
            "resumes": resumes_list,
            "cover_letter": data.get("cover_letter", {}),
            "ai": {
                "analysis_provider": "anthropic",
                "analysis_model": "claude-sonnet-4-6",
                "cover_letter_provider": "anthropic",
                "cover_letter_model": "claude-opus-4-8",
                "form_filling_provider": "openai",
                "form_filling_model": "gpt-4o",
            },
        }

        profile_path = RONIN_HOME / "profile.yaml"
        with open(profile_path, "w", encoding="utf-8") as f:
            f.write(
                "# =============================================================\n"
                "# Ronin Profile Configuration\n"
                "# =============================================================\n"
                "# Generated by: ronin setup\n"
                f"# Location: {profile_path}\n"
                "# To reconfigure, run: ronin setup\n"
                "# To edit a specific section: ronin setup --step personal\n"
                "# =============================================================\n\n"
            )
            yaml.dump(profile, f, default_flow_style=False, sort_keys=False)

        # -- config.yaml --
        search = data.get("search", {})
        browser = data.get("browser", {})
        schedule = data.get("schedule", {})

        config = {
            "search": {
                "keywords": search.get("keywords", []),
                "location": search.get("location", "All-Australia"),
                "date_range": search.get("date_range", 2),
                "salary": search.get("salary", {"min": 0, "max": 400000}),
            },
            "application": {
                "salary_min": professional.get("salary_min", 0),
                "salary_max": professional.get("salary_max", 0),
                "batch_limit": 100,
                "queue_threshold": 0.15,
            },
            "database": {
                "backend": "sqlite",
                "spool_path": "data/spool.db",
                "postgres": {"dsn": "", "fallback_to_spool": True},
            },
            "scraping": {
                "max_jobs": 0,
                "delay_seconds": 1,
                "timeout_seconds": 10,
                "quick_apply_only": True,
            },
            "analysis": {
                "min_score": 0,
                "feedback_min_samples": 2,
                "enable_embeddings": True,
                "embedding_model": "all-MiniLM-L6-v2",
            },
            "proxy": {"enabled": False, "http_url": "", "https_url": ""},
            "notifications": {
                "slack": {
                    "webhook_url": data.get("api_keys", {}).get(
                        "SLACK_WEBHOOK_URL", ""
                    ),
                    "notify_on_error": True,
                    "notify_on_warning": True,
                    "notify_on_success": False,
                }
            },
            "boards": {"seek": {"enabled": True}},
            "browser": {
                "mode": browser.get("mode", "system"),
                "chrome_path": browser.get("chrome_path", ""),
            },
            "schedule": {
                "enabled": schedule.get("enabled", False),
                "interval_hours": schedule.get("interval_hours", 2),
            },
            "tracking": {
                "gmail": {
                    "enabled": False,
                    "mailbox": "INBOX",
                    "lookback_days": 45,
                    "query": "newer_than:1d",
                    "auth_mode": "auto",
                    "credentials_path": "credentials.json",
                    "token_path": "~/.ronin/gmail_token.json",
                    "max_messages_per_sync": 250,
                }
            },
            "resume_variants": {
                "repo_path": "resume",
                "role_name": "data_engineer",
                "seek_profile_mapping": {
                    "builder": "default",
                    "fixer": "default",
                    "operator": "default",
                    "translator": "default",
                },
                "archetype_mapping": {
                    "builder": {
                        "yaml": "yaml/data_engineer/b.yml",
                        "markdown": "markdown/data_engineer_b.md",
                    },
                    "fixer": {
                        "yaml": "yaml/data_engineer/b.yml",
                        "markdown": "markdown/data_engineer_b.md",
                    },
                    "operator": {
                        "yaml": "yaml/data_engineer/c.yml",
                        "markdown": "markdown/data_engineer_c.md",
                    },
                    "translator": {
                        "yaml": "yaml/data_engineer/c.yml",
                        "markdown": "markdown/data_engineer_c.md",
                    },
                },
            },
            "seek_profile": {
                "automation": {
                    "enabled": False,
                    "headless": False,
                    "channel": "chrome",
                    "user_data_dir": "~/.ronin/chrome_profile",
                    "profile_url": "https://www.seek.com.au/profile",
                    "timeout_ms": 45000,
                    "login_timeout_sec": 300,
                    "slow_mo_ms": 0,
                    "jitter": True,
                    "min_delay_sec": 0.1,
                    "max_delay_sec": 0.5,
                    "selectors": {},
                },
                "templates": {
                    "builder": {"headline": "", "summary": "", "skills": []},
                    "fixer": {"headline": "", "summary": "", "skills": []},
                    "operator": {"headline": "", "summary": "", "skills": []},
                    "translator": {"headline": "", "summary": "", "skills": []},
                },
            },
            "timeouts": {
                "http_request": 30,
                "page_load": 45,
                "element_wait": 10,
                "implicit_wait": 10,
            },
            "retry": {
                "max_attempts": 3,
                "backoff_multiplier": 2.0,
                "jitter": True,
            },
        }

        config_path = RONIN_HOME / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "# =============================================================\n"
                "# Ronin Runtime Configuration\n"
                "# =============================================================\n"
                "# Generated by: ronin setup\n"
                f"# Location: {config_path}\n"
                "# =============================================================\n\n"
            )
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        # -- .env --
        api_keys = data.get("api_keys", {})
        env_lines = []
        for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SLACK_WEBHOOK_URL"]:
            val = api_keys.get(key, "")
            env_lines.append(f"{key}={val}")

        env_path = RONIN_HOME / ".env"
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

        # -- Resume text files --
        resumes_dir = RONIN_HOME / "resumes"
        for res in data.get("resumes", []):
            name = res.get("name", "default")
            filename = name.replace(" ", "_") + ".txt"
            text = res.get("text", "")
            if text:
                (resumes_dir / filename).write_text(text, encoding="utf-8")

        # -- Install schedule if enabled --
        if schedule.get("enabled", False):
            try:
                from ronin.scheduler import install_schedule

                interval = schedule.get("interval_hours", 2)
                install_schedule(interval)
            except Exception:
                pass  # Non-fatal; user can run `ronin schedule install` later

        # Done
        self.app.exit(message=f"Configuration saved to {RONIN_HOME}")


# ---------------------------------------------------------------------------
# Chrome detection helper
# ---------------------------------------------------------------------------


def _detect_chrome_path() -> str:
    """Try to find system Chrome. Returns empty string on failure."""
    system = platform.system()
    candidates: list[str] = []
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            str(
                Path.home()
                / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
        ]
    elif system == "Windows":
        for env_var in ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"]:
            base = os.environ.get(env_var, "")
            if base:
                candidates.append(
                    str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
                )
    else:
        candidates = ["/usr/bin/google-chrome", "/usr/bin/chromium-browser"]

    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if chrome:
        return chrome

    for path in candidates:
        if Path(path).exists():
            return path
    return ""


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class SetupWizard(App):
    """Textual TUI setup wizard for Ronin."""

    TITLE = "Ronin Setup"
    CSS = """
    Screen {
        background: $surface;
    }
    .section-header {
        margin-bottom: 1;
    }
    .ascii-art {
        color: $accent;
        margin-bottom: 1;
    }
    ScrollableContainer {
        padding: 1 2;
    }
    Input, TextArea, Select {
        margin-bottom: 1;
    }
    Label {
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, start_step: Optional[str] = None):
        super().__init__()
        self.wizard_data: dict = {}
        self._step_index = 0
        if start_step and start_step in STEP_ORDER:
            self._step_index = STEP_ORDER.index(start_step)

    def on_mount(self) -> None:
        self._push_current_step()

    def _push_current_step(self) -> None:
        step_name = STEP_ORDER[self._step_index]
        screen_cls = STEP_SCREEN_MAP[step_name]
        self.push_screen(screen_cls())

    def action_next_step(self) -> None:
        if self._step_index >= len(STEP_ORDER) - 1:
            return
        self._step_index += 1
        self._push_current_step()

    def action_prev_step(self) -> None:
        if self._step_index <= 0:
            return
        self._step_index -= 1
        self.pop_screen()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_setup(step: Optional[str] = None) -> None:
    """Launch the setup wizard.

    Args:
        step: Optional step name to jump directly to (e.g. "personal").
            Must be one of the keys in STEP_ORDER.
    """
    app = SetupWizard(start_step=step)
    result = app.run()
    if result:
        print(result)


if __name__ == "__main__":
    import sys

    step_arg = None
    args = sys.argv[1:]
    if "--step" in args:
        idx = args.index("--step")
        if idx + 1 < len(args):
            step_arg = args[idx + 1]
            if step_arg not in STEP_ORDER:
                print(f"Unknown step: {step_arg}")
                print(f"Available steps: {', '.join(STEP_ORDER)}")
                sys.exit(1)
    run_setup(step=step_arg)
