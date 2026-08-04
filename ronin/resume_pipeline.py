"""Source-driven resume regeneration pipeline.

Two hand-owned poles bracket the same set of facts:

  * ``source.yml`` — the TRUTH pole. Plain, defensible, no positioning.
  * ``c.yml`` — the RECRUITER pole. The same truth pushed to its most
    keyword-dense, achievement-forward register.

The four archetype variants (builder / fixer / operator / translator) sit at
the midpoint and are the only files the tuning agent writes. Both poles are
inputs to it; ``c.yml`` supplies the register ceiling, ``source.yml`` supplies
the facts:

    log note ──► [ingest agent] ──► source.yml ─┬─► [tuning agent] ──► builder.yml
                                     c.yml ─────┘                      fixer.yml
                                    (read-only)                        operator.yml
                                                                       translator.yml

Design guarantees (why weekly, unattended, auto-pushed regen is safe):
  * ``c.yml`` is frozen against the tuning agent. :data:`FROZEN_VARIANTS`
    is enforced in :func:`tune_variant`, so no code path can overwrite a pole.
  * The tuning agent rewrites ONLY prose (headline, career summary, per-role
    responsibilities and achievements). Companies, dates, periods and titles
    are copied verbatim from source — the LLM never chooses them.
  * Every dollar / percentage / count metric in the output must already exist
    in the source facts. Invented numbers are rejected and the old file is kept.
    The recruiter pole is a style exemplar only — its numbers are not a licence.
  * Regen is idempotent: unchanged source + log + pole ⇒ no LLM call, no commit.

Recruiter-visibility (keeping the Seek profile "recently updated") is handled
separately by :mod:`ronin.seek.profile_refresh`.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from loguru import logger

from ronin.ai import AnthropicService
from ronin.config import get_ronin_home, load_config
from ronin.resume_variants import ResumeVariantManager

# The two poles. Both are hand-owned: the tuning agent reads them and never
# writes them. `c` is the recruiter ceiling the archetypes are calibrated
# against; `source` is the floor.
POLE_VARIANT = "c"
FROZEN_VARIANTS = frozenset({POLE_VARIANT})

# Variants the tuning agent writes, mapped to their focus. Every one sits at
# the midpoint between the poles — the lens below chooses WHICH facts lead, not
# how hard the copy pushes. Register calibration is shared (see _tune_system).
VARIANT_LENSES: Dict[str, str] = {
    "builder": (
        "DESIGN AND BUILD. Lead with systems that did not exist before the "
        "engagement: architecture designed, platforms and pipelines stood up, "
        "patterns and standards established, infrastructure-as-code laid down, "
        "first delivery into production. Open on what was CREATED, in creation "
        "verbs — designed, architected, built, stood up, established, "
        "standardised, delivered. Do NOT lead a bullet on migrating, "
        "re-engineering or modernising something that already existed; that is "
        "the fixer variant's territory, and defaulting to it is why this "
        "variant previously read as a migration resume. Where a fact is "
        "genuinely a migration, frame it by the thing built as a result (the "
        "new lakehouse, the new pipeline, the new model), never by the legacy "
        "system replaced."
    ),
    "fixer": (
        "MIGRATION AND MODERNISATION. Lead with what was inherited and made "
        "better: legacy platform migrations, re-architecture, refactors, "
        "cost and performance uplift on systems already in production, "
        "cutover with no data loss."
    ),
    "operator": (
        "RELIABILITY AND OPERATIONS. Lead with keeping production healthy: "
        "observability, alerting, incident response, runbooks, SLA and "
        "freshness guarantees, BAU support, the failure rates and recovery "
        "times that moved."
    ),
    "translator": (
        "STAKEHOLDERS AND ENABLEMENT. Lead with the business-facing half: "
        "requirements discovery, self-serve analytics, semantic and governance "
        "layers, reporting the business actually trusts, sign-off from "
        "non-technical owners."
    ),
}

# What a bare `ronin resume regen` (and the weekly launchd job) rewrites.
DEFAULT_REGEN_VARIANTS: Tuple[str, ...] = ("builder", "fixer", "operator", "translator")


def get_lens(variant: str, config: Optional[Dict[str, Any]] = None) -> str:
    """Return the focus paragraph for ``variant``, honouring config overrides.

    Market drift closes the loop by editing lenses, and a self-adjusting system
    must not rewrite its own source. Overrides therefore live in config under
    ``resume_variants.lens_overrides.<variant>`` — data, reviewable in a diff and
    revertible by deleting a key — while the defaults above stay the code-level
    baseline. An override replaces the default outright rather than appending,
    so a lens cannot silently accumulate contradictory instructions over
    successive market cycles.
    """
    default = VARIANT_LENSES.get(variant, "a general data-engineering angle.")
    overrides = (
        ((config or {}).get("resume_variants") or {}).get("lens_overrides") or {}
    )
    if not isinstance(overrides, dict):
        return default
    override = overrides.get(variant)
    text = str(override or "").strip()
    return text or default

# Fields the tuning agent is allowed to rewrite. Everything else is copied.
_TUNABLE_ROLE_FIELDS = ("responsibilities", "achievements")

# Log inbox markers (see source_log.md).
_LOG_START = "<!-- ronin:log:start -->"
_LOG_END = "<!-- ronin:log:end -->"

# Seek field limits: summary field caps at ~600 chars (headline is prefixed into
# it), role detail at ~1800. We hold a small margin on detail.
_MAX_SUMMARY_COMBINED = 600
_MAX_ROLE_DETAIL = 1700
# The headline renders on one PDF line and prefixes the Seek summary.
_MAX_HEADER = 110
# Retries when a length cap is missed (truthfulness failures never retry).
_TUNE_MAX_ATTEMPTS = 3


class ResumeRegenError(RuntimeError):
    """A regen step failed a hard validation gate; the old file is untouched."""


# --------------------------------------------------------------------------- paths


def _paths(config: Dict[str, Any]) -> Dict[str, Path]:
    manager = ResumeVariantManager(config)
    base = manager.repo_path / "yaml" / manager.role_name
    return {
        "repo": manager.repo_path,
        "source": base / "source.yml",
        "pole": base / f"{POLE_VARIANT}.yml",
        "log": base / "source_log.md",
        "log_archive": base / "source_log.archive.md",
        "state": get_ronin_home() / "resume_regen_state.json",
    }


def _now_date() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


# ----------------------------------------------------------------------- log inbox


def append_log(text: str, config: Optional[Dict[str, Any]] = None) -> Path:
    """Append a timestamped note into ``source_log.md`` between the markers."""
    config = config or load_config()
    log_path = _paths(config)["log"]
    line = f"- [{_now_date()}] {str(text).strip()}"

    if not log_path.exists():
        log_path.write_text(
            f"# Work-log inbox\n\n{_LOG_START}\n{line}\n{_LOG_END}\n",
            encoding="utf-8",
        )
        return log_path

    content = log_path.read_text(encoding="utf-8")
    if _LOG_END in content:
        content = content.replace(_LOG_END, f"{line}\n{_LOG_END}", 1)
    else:  # markers missing — append a fresh block
        content = content.rstrip() + f"\n\n{_LOG_START}\n{line}\n{_LOG_END}\n"
    log_path.write_text(content, encoding="utf-8")
    return log_path


def _read_unprocessed_log(config: Dict[str, Any]) -> List[str]:
    log_path = _paths(config)["log"]
    if not log_path.exists():
        return []
    content = log_path.read_text(encoding="utf-8")
    if _LOG_START not in content or _LOG_END not in content:
        return []
    block = content.split(_LOG_START, 1)[1].split(_LOG_END, 1)[0]
    notes: List[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or not line.startswith("-"):
            continue
        notes.append(line.lstrip("-").strip())
    return notes


def _archive_log(config: Dict[str, Any]) -> None:
    """Move processed inbox lines to the archive, leaving an empty inbox."""
    paths = _paths(config)
    log_path, archive_path = paths["log"], paths["log_archive"]
    if not log_path.exists():
        return
    content = log_path.read_text(encoding="utf-8")
    if _LOG_START not in content or _LOG_END not in content:
        return
    block = content.split(_LOG_START, 1)[1].split(_LOG_END, 1)[0].strip()
    if block:
        header = "" if archive_path.exists() else "# Archived work-log entries\n\n"
        stamp = f"## folded into source.yml {_now_date()}\n"
        with archive_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{header}{stamp}{block}\n\n")
    emptied = content.split(_LOG_START, 1)[0] + f"{_LOG_START}\n{_LOG_END}\n"
    log_path.write_text(emptied, encoding="utf-8")


# ------------------------------------------------------------------ state / hashing


def _content_hash(config: Dict[str, Any]) -> str:
    paths = _paths(config)
    h = hashlib.sha256()
    # The recruiter pole is an input to tuning, so hand-editing it must
    # invalidate the cache the same way a new fact does.
    for key in ("source", "pole", "log"):
        p = paths[key]
        h.update(p.read_bytes() if p.exists() else b"")
        h.update(b"\0")
    return h.hexdigest()


def _load_state(config: Dict[str, Any]) -> Dict[str, Any]:
    p = _paths(config)["state"]
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(config: Dict[str, Any], state: Dict[str, Any]) -> None:
    p = _paths(config)["state"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ------------------------------------------------------------------------- yaml I/O


def _load_source(config: Dict[str, Any]) -> Dict[str, Any]:
    src = _paths(config)["source"]
    if not src.exists():
        raise ResumeRegenError(f"source.yml not found: {src}")
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ResumeRegenError("source.yml did not parse to a mapping")
    return data


def _dump_yaml(data: Dict[str, Any], path: Path, header: str) -> None:
    body = yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False
    )
    path.write_text(header + body, encoding="utf-8")


def _all_roles(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    roles: List[Dict[str, Any]] = []
    for key in ("experience_freelance", "experience_full_time"):
        for r in source.get(key) or []:
            if isinstance(r, dict):
                roles.append(r)
    return roles


# ----------------------------------------------------------------- metric guard


_METRIC_RE = re.compile(
    r"\$\s?[\d.,]+\s?[kmb]?\+?"      # $150K, $2M+, $2k-5k parts
    r"|\b\d[\d,.]*\s?%"              # 60%, 22 %
    r"|\b\d+x\b"                     # 6x, 75x
    r"|\b\d[\d,.]*\s?[kmb]\+?\b"     # 10M+, 800GB->800 handled below, 66,500
    r"|\b\d{2,}\b",                 # 52, 270, 17, 10, 63
    re.IGNORECASE,
)


def _metric_tokens(text: str) -> set:
    out = set()
    for m in _METRIC_RE.findall(str(text or "")):
        # Strip trailing '+' so "$150K+" matches source "$150K" (a "+" is
        # stylistic puffery on the same figure, not an invented number).
        norm = re.sub(r"[\s,]", "", m).lower().rstrip("+")
        if norm:
            out.add(norm)
    return out


def _source_metric_pool(source: Dict[str, Any]) -> set:
    pool: set = set()
    pool |= _metric_tokens(source.get("career_summary_template", ""))
    for tpl in source.get("highlight_capability_templates") or []:
        pool |= _metric_tokens(tpl)
    for r in _all_roles(source):
        pool |= _metric_tokens(r.get("responsibilities", ""))
        pool |= _metric_tokens(r.get("description", ""))
        for a in r.get("achievements") or []:
            pool |= _metric_tokens(a)
    return pool


# --------------------------------------------------------------------- ingest agent


_INGEST_SYSTEM = (
    "You maintain a data engineer's master resume fact base. You are given the "
    "current structured facts (YAML) and a list of freeform work-log notes the "
    "person jotted down. Fold the notes into the facts WITHOUT inventing "
    "anything. Rules: (1) Only add information the notes actually state. (2) If a "
    "note refines an existing role, add a concise achievement bullet to that "
    "role (match by company). (3) If a note describes a genuinely new role, add a "
    "new role object with company, title, period, location, responsibilities, and "
    "achievements drawn only from the note. (4) Never alter companies, dates, or "
    "titles of existing roles. (5) Never invent metrics. Return ONLY a JSON object "
    "of the form {\"freelance\": [...], \"full_time\": [...]} where each list "
    "contains ONLY role objects to ADD or MODIFY; a modification repeats the "
    "existing company plus the fields to change. Return empty lists if the notes "
    "add no durable resume facts."
)


def ingest_log(config: Dict[str, Any], brain: AnthropicService) -> bool:
    """Fold unprocessed log notes into source.yml. Returns True if it changed."""
    notes = _read_unprocessed_log(config)
    if not notes:
        return False

    source = _load_source(config)
    user = (
        "Current facts (YAML):\n```yaml\n"
        + yaml.safe_dump(
            {
                "experience_freelance": source.get("experience_freelance", []),
                "experience_full_time": source.get("experience_full_time", []),
            },
            sort_keys=False,
            allow_unicode=True,
        )
        + "\n```\n\nNew work-log notes:\n"
        + "\n".join(f"- {n}" for n in notes)
        + "\n\nReturn the JSON described in the system prompt."
    )
    result = brain.chat_completion(
        system_prompt=_INGEST_SYSTEM,
        user_message=user,
        model=_brain_model(config),
        max_tokens=4096,
    )
    if not isinstance(result, dict):
        logger.warning("[resume] ingest returned no usable JSON; archiving notes as-is")
        _archive_log(config)
        return False

    changed = _apply_ingest(source, result)
    if changed:
        _dump_yaml(source, _paths(config)["source"], _source_header())
        logger.info(f"[resume] folded {len(notes)} log note(s) into source.yml")
    _archive_log(config)
    return changed


def _apply_ingest(source: Dict[str, Any], result: Dict[str, Any]) -> bool:
    changed = False
    for res_key, src_key in (("freelance", "experience_freelance"), ("full_time", "experience_full_time")):
        additions = result.get(res_key) or []
        if not isinstance(additions, list):
            continue
        existing = source.setdefault(src_key, [])
        by_company = {str(r.get("company", "")).strip().lower(): r for r in existing if isinstance(r, dict)}
        for add in additions:
            if not isinstance(add, dict) or not add.get("company"):
                continue
            key = str(add["company"]).strip().lower()
            target = by_company.get(key)
            if target is None:  # new role
                existing.append(add)
                by_company[key] = add
                changed = True
                continue
            # Modify existing role: append new achievements only (never rewrite dates/title).
            for bullet in add.get("achievements") or []:
                b = str(bullet).strip()
                if b and b not in (target.get("achievements") or []):
                    target.setdefault("achievements", []).append(b)
                    changed = True
    return changed


# ----------------------------------------------------------------------- tune agent


def _tune_system(variant: str, config: Optional[Dict[str, Any]] = None) -> str:
    lens = get_lens(variant, config)
    return (
        "You are a resume copywriter producing ONE variant of a data engineer's "
        "resume. You are given two reference documents that bracket the same "
        "career. TRUTH POLE (the master facts): plain, literal, no positioning. "
        "RECRUITER POLE (an existing finished resume): the same career written "
        "at its most keyword-dense, achievement-forward extreme. Your output "
        "must land at the MIDPOINT between them — noticeably sharper and more "
        "keyword-rich than the facts, but visibly more restrained than the "
        "recruiter pole. Concretely: adopt the recruiter pole's sentence "
        "architecture, verb strength and technical vocabulary, but drop its "
        "superlatives, its stacked qualifiers, and any framing that would be "
        "hard to defend in a technical interview. Do NOT copy the recruiter "
        "pole's sentences; do NOT reuse a number that does not appear in that "
        "same company's facts. The recruiter pole is a register exemplar, not a "
        f"source of truth. THIS VARIANT'S FOCUS: {lens} Order and weight each "
        "role's prose so this focus leads; keep the rest of the work accurate "
        "but secondary. Rewrite ONLY the prose. "
        "STYLE RULES: (1) Open every bullet with an ownership verb — "
        "Architected, Led, Re-engineered, Standardized, Owned, Governed, "
        "Delivered. (2) Name the full stack inline in parentheses — e.g. "
        "'(S3 + Glue + Lambda + Step Functions)' — and call architecture "
        "patterns by name where the facts support them: medallion "
        "Bronze/Silver/Gold, lakehouse, serverless ELT, event-driven, "
        "exactly-once processing, CDC, SCD Type 2, star schema, "
        "infrastructure-as-code. (3) Shape each bullet OUTCOME-FIRST: open "
        "with what the business could then decide, prove, meet, or stop doing "
        "manually, then the system that made it possible (named tech). The "
        "technology is the supporting clause, never the subject. "
        "(4) Blend three registers so seniority reads on every line: "
        "deep engineering (named services and patterns), strategy "
        "(architecture decisions, cost governance, FinOps, delivery "
        "sequencing), and communication (stakeholder sign-off, "
        "cross-functional partnership, team leadership, "
        "discovery-to-production ownership). (5) Shape the career summary as: "
        "a positioning sentence ('Specialist in ...'), then one sentence of "
        "scope facts (sectors, platforms, migration types — NO dollar or "
        "percentage figures, and never a number that already appears in a "
        "role bullet: each metric lives in exactly one place on the resume), "
        "then 'Expert in ...' with the highest-signal keywords. (6) Write a "
        "headline that states the seniority, this variant's focus, and the "
        "3-5 highest-signal tools, e.g. "
        "'Data Engineer | Reliability & Operations | Databricks • AWS • dbt'. "
        "Return ONLY a "
        "JSON object with keys: \"header\" (a string), "
        "\"career_summary_template\" (a string; you MAY "
        "keep the '{aws_exp_years}+ years' placeholder), \"roles\" (an object "
        "keyed by EXACT company name, each value {\"responsibilities\": string, "
        "\"achievements\": [strings]}), and \"highlight_order\" (a list of "
        "integers — the indices of the supplied capability highlights, reordered "
        "so the ones this variant's focus is about come FIRST; include every "
        "index exactly once; you may NOT edit the highlight text, only reorder "
        "it). HARD RULES: include every company from the "
        "facts and no others; do not invent, inflate, or alter any dollar amount, "
        "percentage, or count — reuse only numbers present in that company's "
        "facts, never a number seen only in the recruiter pole; keep each role's "
        "total prose under 1600 characters; the header must be AT MOST 110 "
        "characters; the "
        "career_summary_template must be AT MOST 430 characters after resolving "
        "the year placeholder; do not mention titles, dates, or companies you were "
        "not given."
    )


def _load_pole(config: Dict[str, Any]) -> str:
    """Return the recruiter-pole yaml as text, for use as a register exemplar.

    Absence is not fatal — the agent falls back to the shared style rules — but
    it does remove the calibration ceiling, so say so loudly.
    """
    pole = _paths(config)["pole"]
    if not pole.exists():
        logger.warning(
            f"[resume] recruiter pole {pole.name} missing — tuning without a "
            "register ceiling"
        )
        return ""
    return pole.read_text(encoding="utf-8")


def tune_variant(
    config: Dict[str, Any], brain: AnthropicService, variant: str
) -> Tuple[bool, Path]:
    """Rewrite the variant yaml's prose from source. Returns (changed, path)."""
    if variant in FROZEN_VARIANTS:
        raise ResumeRegenError(
            f"{variant}.yml is a hand-owned pole and is never machine-written. "
            f"Edit it directly; the tuning agent reads it as a register exemplar."
        )
    if variant not in VARIANT_LENSES:
        raise ResumeRegenError(
            f"no lens defined for variant '{variant}' — add one to VARIANT_LENSES "
            f"(known: {', '.join(sorted(VARIANT_LENSES))})"
        )

    source = _load_source(config)
    roles = _all_roles(source)
    manager = ResumeVariantManager(config)
    variant_path = manager.repo_path / "yaml" / manager.role_name / f"{variant}.yml"

    facts_yaml = yaml.safe_dump(
        {
            "career_summary_template": source.get("career_summary_template", ""),
            "roles": [
                {
                    "company": r.get("company"),
                    "title": r.get("de_title") or r.get("title"),
                    "responsibilities": r.get("responsibilities"),
                    "achievements": r.get("achievements"),
                }
                for r in roles
            ],
        },
        sort_keys=False,
        allow_unicode=True,
    )
    pole_yaml = _load_pole(config)
    base_user = f"TRUTH POLE — master facts (YAML):\n```yaml\n{facts_yaml}\n```\n"

    source_highlights = source.get("highlight_capability_templates") or []
    if source_highlights:
        listed = "\n".join(f"  [{i}] {h}" for i, h in enumerate(source_highlights))
        base_user += (
            "\nCAPABILITY HIGHLIGHTS — fixed text, render near the top of the "
            "resume. Return highlight_order to put this variant's focus first:\n"
            f"{listed}\n"
        )
    if pole_yaml:
        base_user += (
            f"\nRECRUITER POLE — {POLE_VARIANT}.yml, the same career at its most "
            "aggressive. Match its craft, not its intensity; land halfway "
            f"between it and the facts:\n```yaml\n{pole_yaml}\n```\n"
        )
    base_user += "\nReturn the JSON."

    # A missed length cap is recoverable — feed it back and retry. A truthfulness
    # failure (invented metric, role mismatch) is not: raise immediately.
    # Length-cap AND metric-traceability failures are both recoverable — feed the
    # exact violation back and retry. A role-set mismatch is not (raise at once).
    correction = ""
    last_error: Optional[str] = None
    for attempt in range(1, _TUNE_MAX_ATTEMPTS + 1):
        result = brain.chat_completion(
            system_prompt=_tune_system(variant, config),
            user_message=base_user + correction,
            model=_brain_model(config),
            max_tokens=8192,
        )
        if not isinstance(result, dict) or "roles" not in result:
            raise ResumeRegenError(f"tuning agent returned no usable JSON for {variant}")

        new_doc = _build_variant_doc(source, roles, result, variant, variant_path)
        try:
            _validate_variant(source, new_doc)
        except ResumeRegenError as exc:
            recoverable = ("chars >" in str(exc)) or ("invented metric" in str(exc))
            if recoverable and attempt < _TUNE_MAX_ATTEMPTS:
                last_error = str(exc)
                correction = (
                    f"\n\nYour previous answer was rejected: {exc}. "
                    "Fix ONLY that: use exact numbers from the facts (no added '+', "
                    "no rounding, no new figures) and satisfy every length cap. "
                    "Return the corrected JSON."
                )
                logger.info(f"[resume] tune attempt {attempt} rejected ({str(exc)[:80]}); retrying")
                continue
            raise

        _dump_yaml(new_doc, variant_path, _variant_header(variant, config))
        logger.info(f"[resume] retuned {variant}.yml ({len(roles)} roles, attempt {attempt})")
        return True, variant_path

    raise ResumeRegenError(f"tuning agent could not satisfy validation: {last_error}")


def _ordered_highlights(
    source: Dict[str, Any], order: Any, variant: str
) -> Optional[List[str]]:
    """Return source highlights permuted by ``order`` (a list of source indices).

    Anything short of a clean permutation falls back to source order. The
    content is identical either way, so a malformed answer costs emphasis, not
    correctness — never worth failing a regen over.
    """
    highlights = source.get("highlight_capability_templates")
    if not isinstance(highlights, list) or not highlights:
        return highlights

    if not isinstance(order, list):
        return highlights

    try:
        indices = [int(i) for i in order]
    except (TypeError, ValueError):
        logger.warning(f"[resume] {variant}: non-integer highlight_order; keeping source order")
        return highlights

    if sorted(indices) != list(range(len(highlights))):
        logger.warning(
            f"[resume] {variant}: highlight_order {indices} is not a permutation of "
            f"0..{len(highlights) - 1}; keeping source order"
        )
        return highlights

    return [highlights[i] for i in indices]


def _build_variant_doc(
    source: Dict[str, Any],
    roles: List[Dict[str, Any]],
    result: Dict[str, Any],
    variant: str,
    variant_path: Path,
) -> Dict[str, Any]:
    """Assemble the variant yaml: structural fields copied, prose from the LLM."""
    out_roles: Dict[str, List[Dict[str, Any]]] = {
        "experience_freelance": [],
        "experience_full_time": [],
    }
    llm_roles = {str(k).strip().lower(): v for k, v in (result.get("roles") or {}).items()}

    for src_key in ("experience_freelance", "experience_full_time"):
        for r in source.get(src_key) or []:
            if not isinstance(r, dict):
                continue
            company = str(r.get("company", ""))
            llm = llm_roles.get(company.strip().lower(), {})
            role = {
                "company": company,
                "location": r.get("location", ""),
                # Present the DE-framed title when set, else the real title.
                "title": r.get("de_title") or r.get("title", ""),
                "period": r.get("period", ""),
                "responsibilities": str(
                    llm.get("responsibilities") or r.get("responsibilities", "")
                ).strip(),
                "achievements": [
                    str(a).strip()
                    for a in (llm.get("achievements") or r.get("achievements") or [])
                    if str(a).strip()
                ],
            }
            if r.get("engagement"):
                role["engagement"] = r["engagement"]
            if r.get("description"):
                role["description"] = r["description"]
            out_roles[src_key].append(role)

    # Capability highlights come ONLY from source.yml (curated, guard-validated).
    # We deliberately do NOT inherit them from the previous variant file — that
    # would let stale, unvetted claims persist across regenerations.
    #
    # The agent may REORDER them per variant but never rewrite them: the strings
    # stay verbatim, so truthfulness is guaranteed by construction, while the
    # variant gets to lead with the capability its lens is about. Sharing one
    # fixed order across all four made every resume open on the same two
    # cost/modernisation lines, which is measurably why builder.md embedded
    # closer to the fixer archetype than to its own.
    highlights = _ordered_highlights(source, result.get("highlight_order"), variant)

    # Contact details are copied verbatim; only the headline is variant-specific,
    # since a reliability resume and a greenfield resume should not lead with the
    # same line.
    personal = dict(source.get("personal", {}) or {})
    llm_header = str(result.get("header") or "").strip()
    if llm_header:
        personal["header"] = llm_header

    doc: Dict[str, Any] = {
        "personal": personal,
        "career_summary_template": str(
            result.get("career_summary_template")
            or source.get("career_summary_template", "")
        ).strip(),
        "experience_start_dates": source.get("experience_start_dates", {}),
    }
    if highlights:
        doc["highlight_capability_templates"] = highlights
    doc["experience_freelance"] = out_roles["experience_freelance"]
    doc["experience_full_time"] = out_roles["experience_full_time"]
    doc["education"] = source.get("education", [])
    doc["certifications"] = source.get("certifications", [])
    return doc


def _validate_variant(source: Dict[str, Any], doc: Dict[str, Any]) -> None:
    src_companies = {str(r.get("company", "")).strip().lower() for r in _all_roles(source)}
    out_companies = {
        str(r.get("company", "")).strip().lower()
        for r in doc.get("experience_freelance", []) + doc.get("experience_full_time", [])
    }
    if out_companies != src_companies:
        missing = src_companies - out_companies
        extra = out_companies - src_companies
        raise ResumeRegenError(
            f"variant role set mismatch (missing={sorted(missing)}, extra={sorted(extra)})"
        )

    pool = _source_metric_pool(source)

    header = str((doc.get("personal") or {}).get("header") or "")
    if len(header) > _MAX_HEADER:
        raise ResumeRegenError(f"header {len(header)} chars > {_MAX_HEADER} cap")
    invented = _metric_tokens(header) - pool
    if invented:
        raise ResumeRegenError(
            f"invented metric(s) in header: {sorted(invented)} "
            "(not present in source facts) — refusing to write"
        )

    # Capability highlights are rendered on the PDF/markdown resume — hold them to
    # the same truthfulness bar as role prose.
    for tpl in doc.get("highlight_capability_templates") or []:
        invented = _metric_tokens(tpl) - pool
        if invented:
            raise ResumeRegenError(
                f"invented metric(s) in capability highlight: {sorted(invented)} "
                "(not present in source facts) — refusing to write"
            )

    for r in doc.get("experience_freelance", []) + doc.get("experience_full_time", []):
        detail = str(r.get("responsibilities", "")) + " " + " ".join(r.get("achievements", []))
        invented = _metric_tokens(detail) - pool
        if invented:
            raise ResumeRegenError(
                f"invented metric(s) in {r.get('company')!r}: {sorted(invented)} "
                "(not present in source facts) — refusing to write"
            )
        if len(detail) > _MAX_ROLE_DETAIL:
            raise ResumeRegenError(
                f"{r.get('company')!r} detail {len(detail)} chars > {_MAX_ROLE_DETAIL} cap"
            )

    # Summary + header must fit Seek's combined field.
    summary = _render_summary(source, doc.get("career_summary_template", ""))
    header = str(source.get("personal", {}).get("header", ""))
    combined = len(header) + 2 + len(summary)
    if combined > _MAX_SUMMARY_COMBINED:
        raise ResumeRegenError(
            f"summary+header {combined} chars > {_MAX_SUMMARY_COMBINED} cap"
        )
    # Every metric in the summary must also trace to source.
    invented_summary = _metric_tokens(summary) - pool
    if invented_summary:
        raise ResumeRegenError(f"invented metric(s) in summary: {sorted(invented_summary)}")


def _render_summary(source: Dict[str, Any], template: str) -> str:
    """Resolve {x_exp_years} placeholders the way simple.py / the updater do."""
    year_now = datetime.now().year
    text = str(template or "")
    for key, start in (source.get("experience_start_dates") or {}).items():
        try:
            years = max(1, year_now - int(start))
        except Exception:
            continue
        text = text.replace("{" + f"{key}_exp_years" + "}", str(years))
    return re.sub(r"\{[a-zA-Z0-9_]+\}", "", text).strip()


# ------------------------------------------------------------------------- git / run


def _brain_model(config: Dict[str, Any]) -> str:
    return str(
        (config.get("agent_apply", {}) or {}).get("brain_model")
        or "claude-opus-4-8"
    )


def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
    )


def _push_remote(config: Dict[str, Any]) -> str:
    """Explicit remote to push regen commits to (empty = commit locally only).

    Deliberately NOT a bare ``git push``: this repo's branch upstream may point at
    someone else's remote. Configure ``resume_variants.regen_push_remote`` to the
    remote name you actually own (e.g. your personal fork).
    """
    return str((config.get("resume_variants", {}) or {}).get("regen_push_remote", "")).strip()


def _git_commit_push(config: Dict[str, Any], files: List[Path], message: str, push: bool) -> None:
    repo = _paths(config)["repo"]
    # The resume repo is its own git root; commit in whichever root tracks these.
    root = repo
    probe = _git(["rev-parse", "--show-toplevel"], repo)
    if probe.returncode == 0 and probe.stdout.strip():
        root = Path(probe.stdout.strip())

    existing = [f for f in files if f.exists()]
    # Drop gitignored build artifacts (markdown/, pdf/) — passing them to
    # `git add` aborts the whole staging operation.
    rels: List[str] = []
    for f in existing:
        ignored = _git(["check-ignore", "-q", str(f)], root)
        if ignored.returncode == 0:
            continue
        rels.append(str(f))
    if not rels:
        logger.info("[resume] no trackable files to commit")
        return
    add = _git(["add", *rels], root)
    if add.returncode != 0:
        logger.warning(f"[resume] git add failed: {add.stderr.strip()[:200]}")
        return
    status = _git(["status", "--porcelain", *rels], root)
    if not status.stdout.strip():
        logger.info("[resume] nothing staged; skipping commit")
        return
    commit = _git(["commit", "-m", message, *rels], root)
    if commit.returncode != 0:
        logger.warning(f"[resume] git commit failed: {commit.stderr.strip()[:200]}")
        return
    logger.info(f"[resume] committed: {message}")

    if not push:
        return
    remote = _push_remote(config)
    if not remote:
        logger.info(
            "[resume] committed locally; push skipped "
            "(set resume_variants.regen_push_remote to enable)"
        )
        return
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip() or "main"
    pushed = _git(["push", remote, f"HEAD:{branch}"], root)
    if pushed.returncode != 0:
        logger.warning(f"[resume] git push to {remote} failed: {pushed.stderr.strip()[:200]}")
    else:
        logger.info(f"[resume] pushed to {remote} {branch}")


def regen(
    *,
    variants: Optional[List[str]] = None,
    force: bool = False,
    push: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the full pipeline: ingest log -> tune variants -> build -> commit/push.

    Idempotent: unchanged source + pole + log and no --force means no LLM call
    and no commit. Returns a small report dict.

    A variant that fails validation does not block the others: its old file is
    kept, the failure is recorded in ``failures``, and the run continues.
    """
    config = config or load_config()
    targets = [str(v).strip().lower() for v in (variants or DEFAULT_REGEN_VARIANTS) if str(v).strip()]
    frozen = [v for v in targets if v in FROZEN_VARIANTS]
    if frozen:
        raise ResumeRegenError(
            f"refusing to regenerate hand-owned pole(s): {', '.join(frozen)}. "
            "Edit those files directly."
        )

    paths = _paths(config)
    state = _load_state(config)
    current_hash = _content_hash(config)
    prev_hash = state.get("hash")

    if not force and prev_hash == current_hash and state.get("variants") == targets:
        logger.info("[resume] source unchanged since last regen — skipping")
        return {"skipped": True, "reason": "unchanged", "variants": targets}

    brain = AnthropicService()

    ingested = ingest_log(config, brain)

    manager = ResumeVariantManager(config)
    built_files: List[Path] = [paths["source"], paths["log"], paths["log_archive"]]
    written: List[str] = []
    failures: Dict[str, str] = {}

    for variant in targets:
        try:
            _, path = tune_variant(config, brain, variant=variant)
        except ResumeRegenError as exc:
            logger.warning(f"[resume] {variant} kept unchanged: {str(exc)[:200]}")
            failures[variant] = str(exc)
            continue
        built_files.append(path)
        written.append(variant)

        # Rebuild markdown (pure python) and PDF (best-effort — needs pdflatex).
        try:
            built_files.append(manager.ensure_markdown(variant))
        except Exception as exc:  # markdown build is best-effort
            logger.warning(f"[resume] {variant} markdown build skipped: {str(exc)[:160]}")
        try:
            pdf = manager.build_pdf(variant)
            if pdf:
                built_files.append(Path(pdf))
        except Exception as exc:
            logger.warning(f"[resume] {variant} pdf build skipped: {str(exc)[:160]}")

    msg = f"chore(resume): weekly regen {', '.join(written) or 'facts only'} {_now_date()}"
    _git_commit_push(config, built_files, msg, push=push)

    state["hash"] = _content_hash(config)
    state["last_regen"] = _now_date()
    state["variants"] = targets
    state.pop("variant", None)
    _save_state(config, state)
    return {
        "skipped": False,
        "variants": targets,
        "written": written,
        "failures": failures,
        "ingested_notes": ingested,
    }


# ---------------------------------------------------------------------- yaml headers


def _source_header() -> str:
    return (
        "# SOURCE OF TRUTH — master fact base for the data-engineering resume "
        "variants.\n# Edited by `ronin resume regen` (folds source_log.md notes). "
        "Safe to hand-edit.\n\n"
    )


def _variant_header(variant: str, config: Optional[Dict[str, Any]] = None) -> str:
    lens = get_lens(variant, config)
    return (
        f"# GENERATED by `ronin resume regen` — {variant}.yml.\n"
        f"# Focus: {lens[:70]}...\n"
        f"# Register: midpoint between source.yml (truth) and {POLE_VARIANT}.yml "
        "(recruiter).\n"
        "# Do not hand-edit; edit source.yml (or `ronin log`) and regen instead.\n\n"
    )
