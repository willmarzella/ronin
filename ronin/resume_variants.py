"""Resume variant integration with the existing YAML-driven resume repository."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

from ronin.analyzer.archetype_classifier import ArchetypeClassifier

ARCHETYPES = ["builder", "fixer", "operator", "translator"]
DEFAULT_FALLBACK_CODES = {
    "builder": "b",
    "fixer": "b",
    "operator": "c",
    "translator": "c",
}


@dataclass
class ResumeVariantSpec:
    """Filesystem mapping for one archetype variant."""

    archetype: str
    yaml_path: Path
    markdown_path: Path
    alignment_path: Path


class ResumeVariantManager:
    """Bridge Ronin archetypes to the existing `resume/` YAML workflow."""

    def __init__(self, config: Dict):
        self.config = config or {}
        rv_cfg = self.config.get("resume_variants", {})
        repo_raw = rv_cfg.get("repo_path", "resume")
        self.repo_path = Path(repo_raw).expanduser()
        if not self.repo_path.is_absolute():
            # Resolve against cwd first (how launchd runs it), then against the
            # package root. Without the fallback any caller with a different
            # working directory — compile.sh runs from resume/ — silently
            # resolves to a path that does not exist.
            from_cwd = (Path.cwd() / self.repo_path).resolve()
            from_pkg = (Path(__file__).resolve().parents[1] / self.repo_path).resolve()
            self.repo_path = (
                from_cwd if from_cwd.exists() or not from_pkg.exists() else from_pkg
            )

        self.role_name = str(rv_cfg.get("role_name", "data_engineer"))
        self.mapping_cfg = rv_cfg.get("archetype_mapping", {}) or {}
        self.seek_profile_mapping = rv_cfg.get("seek_profile_mapping", {}) or {}

    def get_variant_spec(self, archetype: str) -> ResumeVariantSpec:
        """Return YAML/Markdown paths for one archetype."""
        archetype = archetype.strip().lower()
        if archetype not in ARCHETYPES:
            raise ValueError(f"Unknown archetype: {archetype}")

        entry = self.mapping_cfg.get(archetype, {})
        explicit_yaml = entry.get("yaml") if isinstance(entry, dict) else None
        explicit_markdown = entry.get("markdown") if isinstance(entry, dict) else None

        if explicit_yaml:
            yaml_rel = Path(explicit_yaml)
        else:
            direct_yaml = Path("yaml") / self.role_name / f"{archetype}.yml"
            if (self.repo_path / direct_yaml).exists():
                yaml_rel = direct_yaml
            else:
                fallback_code = DEFAULT_FALLBACK_CODES.get(archetype, "b")
                yaml_rel = Path("yaml") / self.role_name / f"{fallback_code}.yml"

        yaml_base = yaml_rel.stem

        if explicit_markdown:
            markdown_rel = Path(explicit_markdown)
        else:
            # The markdown output path is derived from the YAML filename.
            # This keeps `ensure_markdown()` consistent with scripts/simple.py output.
            markdown_rel = Path("markdown") / f"{self.role_name}_{yaml_base}.md"

        alignment_rel = markdown_rel.with_suffix(".alignment.json")
        return ResumeVariantSpec(
            archetype=archetype,
            yaml_path=self.repo_path / yaml_rel,
            markdown_path=self.repo_path / markdown_rel,
            alignment_path=self.repo_path / alignment_rel,
        )

    def ensure_markdown(self, archetype: str) -> Path:
        """Generate or refresh markdown output from variant YAML."""
        spec = self.get_variant_spec(archetype)
        if not spec.yaml_path.exists():
            raise FileNotFoundError(
                f"Resume YAML for archetype '{archetype}' not found: {spec.yaml_path}"
            )

        should_build = not spec.markdown_path.exists()
        if spec.markdown_path.exists() and spec.yaml_path.exists():
            should_build = (
                spec.yaml_path.stat().st_mtime > spec.markdown_path.stat().st_mtime
            )

        if should_build:
            self._run_simple_converter(spec.yaml_path, output_format="markdown")
            logger.info(f"Generated markdown resume for archetype {archetype}")

        if not spec.markdown_path.exists():
            raise FileNotFoundError(
                f"Markdown output missing after build: {spec.markdown_path}"
            )
        return spec.markdown_path

    def build_pdf(self, archetype: str) -> Optional[Path]:
        """Generate PDF for one archetype variant using existing scripts/simple.py logic."""
        spec = self.get_variant_spec(archetype)
        if not spec.yaml_path.exists():
            return None

        self._run_simple_converter(spec.yaml_path, output_format="latex")
        tex_path = spec.markdown_path.with_suffix(".tex")
        tex_path = self.repo_path / "latex" / tex_path.name
        if not tex_path.exists():
            logger.warning(f"Cannot build PDF; LaTeX not found at {tex_path}")
            return None

        pdf_dir = self.repo_path / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                f"-output-directory={pdf_dir}",
                str(tex_path),
            ],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(f"PDF build failed for {archetype}: {result.stderr[:300]}")
            return None
        out_pdf = pdf_dir / f"{tex_path.stem}.pdf"
        return out_pdf if out_pdf.exists() else None

    def compute_and_store_alignment(
        self,
        archetype: str,
        classifier: ArchetypeClassifier,
    ) -> Dict:
        """Compute resume embedding alignment and write alignment JSON metadata."""
        spec = self.get_variant_spec(archetype)
        markdown_path = self.ensure_markdown(archetype)
        resume_text = markdown_path.read_text(encoding="utf-8")
        resume_embedding = classifier.embed_text(resume_text)
        centroid = classifier.get_centroid(archetype)
        alignment = classifier.cosine_similarity(resume_embedding, centroid)

        commit_hash = self.get_file_commit_hash(markdown_path)
        computed = {
            "archetype": archetype,
            "alignment_score": round(float(alignment), 4),
            "computed_date": datetime.now().isoformat(),
            "commit_hash": commit_hash,
            "yaml_path": str(spec.yaml_path),
            "markdown_path": str(markdown_path),
        }
        spec.alignment_path.parent.mkdir(parents=True, exist_ok=True)
        spec.alignment_path.write_text(
            json.dumps(computed, indent=2) + "\n",
            encoding="utf-8",
        )

        return {
            "archetype": archetype,
            "file_path": str(markdown_path),
            "current_commit_hash": commit_hash,
            "embedding_vector": resume_embedding,
            "alignment_score": float(alignment),
            "last_rewritten": self.get_file_commit_date(markdown_path),
            "alignment_path": str(spec.alignment_path),
        }

    def refresh_variants(self, classifier: ArchetypeClassifier) -> Dict[str, Dict]:
        """Refresh and score all archetype variants currently mapped in resume/ repo."""
        results: Dict[str, Dict] = {}
        for archetype in ARCHETYPES:
            try:
                results[archetype] = self.compute_and_store_alignment(
                    archetype=archetype,
                    classifier=classifier,
                )
            except Exception as exc:
                logger.warning(f"Resume variant refresh failed for {archetype}: {exc}")
        return results

    def seek_resume_profile_for_archetype(
        self,
        archetype: str,
        fallback: str = "default",
    ) -> str:
        """Return configured Seek profile name to use for an archetype batch."""
        return str(self.seek_profile_mapping.get(archetype) or fallback)

    def _run_simple_converter(self, yaml_path: Path, output_format: str) -> None:
        role_name = self.role_name
        python_bin = self._resolve_python_binary()
        yaml_arg = str(yaml_path.relative_to(self.repo_path))
        command = [python_bin, "scripts/simple.py", yaml_arg, role_name, output_format]

        result = subprocess.run(
            command,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Resume conversion failed for {yaml_path.name}: {result.stderr or result.stdout}"
            )

    def _resolve_python_binary(self) -> str:
        candidate = self.repo_path / "venv" / "bin" / "python3"
        if candidate.exists():
            return str(candidate)
        return sys.executable

    def get_file_commit_hash(self, file_path: Path) -> str:
        """Get latest git commit hash touching a file in resume repo."""
        rel = file_path.relative_to(self.repo_path)
        cmd = [
            "git",
            "-C",
            str(self.repo_path),
            "log",
            "-n",
            "1",
            "--format=%H",
            "--",
            str(rel),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        head = subprocess.run(
            ["git", "-C", str(self.repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head.returncode == 0 and head.stdout.strip():
            return head.stdout.strip()
        return "unknown"

    def get_file_commit_date(self, file_path: Path) -> Optional[str]:
        """Get latest commit date for a file in ISO date format."""
        rel = file_path.relative_to(self.repo_path)
        cmd = [
            "git",
            "-C",
            str(self.repo_path),
            "log",
            "-n",
            "1",
            "--format=%cI",
            "--",
            str(rel),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            return datetime.fromisoformat(result.stdout.strip()).date().isoformat()
        except Exception:
            return None
