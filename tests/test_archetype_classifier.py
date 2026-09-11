#!/usr/bin/env python3
"""Lightweight regression checks for the archetype classifier.

These tests are intentionally dependency-light (no sentence-transformers required)
and run as a standalone script.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_primary_archetypes() -> None:
    from ronin.analyzer.archetype_classifier import ArchetypeClassifier

    classifier = ArchetypeClassifier(enable_embeddings=False)

    samples = {
        "builder": (
            "We will design and implement a new platform from the ground up. "
            "You will establish standards and build out cloud-native pipelines in AWS."
        ),
        "fixer": (
            "This role will migrate from Redshift to Snowflake and modernise legacy ETL. "
            "You will refactor existing workflows and reduce technical debt."
        ),
        "operator": (
            "Provide production support and incident response for our data platform. "
            "Maintain SLAs, monitor pipelines, and participate in on-call rotation."
        ),
        "translator": (
            "Partner with stakeholders to gather requirements and enable self-serve analytics. "
            "Improve data literacy and translate business needs into technical deliverables."
        ),
    }

    for expected, jd_text in samples.items():
        result = classifier.classify(jd_text=jd_text, job_title="Data Engineer")
        predicted = result.get("archetype_primary")
        _assert(
            predicted == expected,
            f"Expected {expected}, got {predicted} (scores={result.get('archetype_scores')})",
        )


def test_metadata_extraction() -> None:
    from ronin.analyzer.archetype_classifier import ArchetypeClassifier

    classifier = ArchetypeClassifier(enable_embeddings=False)
    meta = classifier.extract_metadata(
        jd_text="6 month contract role supporting production systems. Maintain SLAs.",
        job_title="Senior Data Engineer",
    )
    _assert(meta.get("job_type") == "contract", f"Unexpected job_type: {meta}")
    _assert(meta.get("seniority_level") == "senior", f"Unexpected seniority: {meta}")


def test_fixture_regressions() -> None:
    from ronin.analyzer.archetype_classifier import ArchetypeClassifier

    classifier = ArchetypeClassifier(enable_embeddings=False)
    fixture_path = Path(__file__).parent / "fixtures" / "archetype_jds.jsonl"
    rows = fixture_path.read_text(encoding="utf-8").splitlines()
    _assert(rows, "Fixture file is empty")

    for line in rows:
        payload = json.loads(line)
        expected = str(payload.get("expected") or "").strip().lower()
        title = str(payload.get("title") or "")
        jd_text = str(payload.get("jd_text") or "")
        name = payload.get("name")

        result = classifier.classify(jd_text=jd_text, job_title=title)
        predicted = result.get("archetype_primary")
        _assert(
            predicted == expected,
            f"Fixture {name}: expected {expected}, got {predicted} (scores={result.get('archetype_scores')})",
        )


def _load_classifier_module():
    """Import archetype_classifier without the package __init__ chain.

    ``ronin.analyzer.__init__`` pulls in the analyzer service, which needs bs4
    and selenium. These tests are meant to run dependency-light.
    """
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "ronin" / "analyzer" / "archetype_classifier.py"
    spec = importlib.util.spec_from_file_location("_ac_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_protected_companies(tmp_home: Path | None = None) -> None:
    """The engagement register keeps the pipeline off current clients.

    The register is published from outside ronin (see ENGAGEMENT_REGISTER). The
    contract under test: markers in it are honoured, the built-in
    bespoke-channel list still applies, and every failure mode leaves the
    built-ins intact rather than throwing.
    """
    import tempfile

    mod = _load_classifier_module()

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        os.environ["RONIN_HOME"] = str(home)
        try:
            # No register at all: built-ins only, never an exception.
            mod._engagement_cache = (0.0, ())
            _assert(mod.engagement_markers() == (), "absent register should yield no markers")
            _assert(mod.is_protected_company("d2i"), "built-in marker must still apply")
            _assert(
                not mod.is_protected_company("Northwind Talent Pty Ltd"),
                "unpublished company must not be protected",
            )

            # Published register: client, agency and OPAC all protected.
            (home / "engagements.yaml").write_text(
                "protected_companies:\n"
                "  - 'acme'\n"
                "  - 'northwind'\n"
                "  - 'contoso'\n"
            )
            mod._engagement_cache = (0.0, ())
            for name in (
                "ACME",
                "Acme Mining Ltd",
                "Northwind Talent Pty Ltd",
                "Northwind",
                "Contoso Payroll Pty Ltd",
            ):
                _assert(mod.is_protected_company(name), f"{name} should be protected")

            for name in ("Techforce Recruitment", "Virgin Australia", "Some Random Pty Ltd", ""):
                _assert(not mod.is_protected_company(name), f"{name} should not be protected")

            _assert(mod.is_protected_company("Toyota Australia"), "built-ins survive the merge")

            # Corrupt register: keep the last good value, do not throw and do
            # not fail open. An unreadable file must never unprotect a client.
            (home / "engagements.yaml").write_text("protected_companies: [oh: no: ]\n:::")
            os.utime(home / "engagements.yaml", (0, 0))
            _assert(
                mod.is_protected_company("ACME"),
                "corrupt register must not unprotect a live client",
            )
        finally:
            os.environ.pop("RONIN_HOME", None)


def main() -> int:
    try:
        test_primary_archetypes()
        test_metadata_extraction()
        test_fixture_regressions()
        test_protected_companies()
        print("PASS: archetype classifier")
        return 0
    except Exception as exc:
        print(f"FAIL: archetype classifier -- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
