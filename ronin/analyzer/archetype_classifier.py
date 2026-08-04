"""Rule-first archetype classifier and metadata extraction for job descriptions."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List, Optional

from loguru import logger


ARCHETYPE_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "builder": {
        "verb_patterns": [
            "build {tech}",
            "building {tech}",
            "design {tech}",
            "designing {tech}",
            "design and implement {tech}",
            "designing and implementing {tech}",
            "architect {tech}",
            "architecting {tech}",
            "implement {tech} from scratch",
            "implementing {tech} from scratch",
            "establish {tech}",
            "establishing {tech}",
            "create {tech}",
            "creating {tech}",
            "set up {tech}",
            "setting up {tech}",
            "develop new {tech}",
            "developing new {tech}",
            "stand up {tech}",
            "standing up {tech}",
            "greenfield",
            "from the ground up",
            "define standards",
            "new platform",
            "cloud-native",
            "founding",
            "build out",
            "building out",
            "develop and deploy",
            "developing and deploying",
            "create a new",
            "design the architecture",
            "lead the development of",
            "stand up new {tech}",
            "stand up a new {tech}",
            "build the {tech} platform",
            "implement new {tech}",
            "implementing new {tech}",
            "establish new {tech}",
            "deploy new {tech}",
            "deploying new {tech}",
            "rollout {tech}",
            "roll out {tech}",
        ],
        "sentence_indicators": [
            "no existing",
            "first hire",
            "new team",
            "newly created",
            "start-up phase",
            "zero to one",
            "ground floor",
            "vision for",
            "shape the direction",
            "greenfield",
            "der integration",
            "ami rollout",
            "ami deployment",
            "new metering platform",
            "first-of-kind",
            "new asset management platform",
            "establishing a new capability",
        ],
    },
    "fixer": {
        "verb_patterns": [
            "migrate {tech}",
            "migrating {tech}",
            "migrate from {tech} to {tech}",
            "consolidate {tech}",
            "refactor {tech}",
            "refactoring {tech}",
            "modernise {tech}",
            "modernising {tech}",
            "modernize {tech}",
            "modernizing {tech}",
            "replace {tech}",
            "uplift {tech}",
            "uplifting {tech}",
            "remediate {tech}",
            "transition from {tech}",
            "transition to {tech}",
            "sunset {tech}",
            "decommission {tech}",
            "decommissioning {tech}",
            "optimise {tech}",
            "re-platform",
            "improve existing",
            "reduce complexity",
            "streamline",
            "transform legacy",
            "clean up",
            "rationalise",
            "data migration",
            "target state",
            "target-state",
            "transformation program",
            "uplift program",
            "platform uplift",
            "system decommissioning",
            "uplift asset data",
            "uplift {tech}",
            "uplifting {tech}",
            "data quality uplift",
            "asset data uplift",
            "metering data uplift",
            "regulatory data uplift",
            "scada migration",
            "pi historian migration",
            "osisoft migration",
            "gis migration",
            "smallworld migration",
            "ellipse migration",
            "maximo migration",
        ],
        "sentence_indicators": [
            "legacy",
            "tech debt",
            "technical debt",
            "end of life",
            "current state",
            "pain points",
            "inefficiencies",
            "aging infrastructure",
            "manual processes",
            "existing systems need",
            "outdated",
            "migration",
            "migrating",
            "modernisation",
            "modernization",
            "uplift",
            "target state",
            "target-state",
            "transformation",
            "decommission",
            "decommissioning",
            "asset data uplift",
            "regulatory uplift",
            "metering uplift",
            "legacy gis",
            "legacy scada",
            "legacy ellipse",
            "legacy maximo",
            "pi historian uplift",
            "ring-fencing",
            "ring fencing",
            "aer determination",
            "rin submission",
        ],
    },
    "operator": {
        "verb_patterns": [
            "maintain {tech}",
            "maintaining {tech}",
            "support {tech}",
            "supporting {tech}",
            "monitor {tech}",
            "monitoring {tech}",
            "ensure reliability of {tech}",
            "manage {tech}",
            "administer {tech}",
            "troubleshoot {tech}",
            "troubleshooting {tech}",
            "on-call",
            "incident response",
            "production support",
            "bau",
            "run book",
            "sla",
            "ensure uptime",
            "day-to-day management",
            "operational readiness",
            "observability",
            "platform reliability",
            "operational resilience",
            "runbook",
            "slo",
            "sli",
            "operate {tech}",
            "operating {tech}",
            "manage outages",
            "managing outages",
            "monitor network",
            "monitoring network",
            "respond to faults",
            "responding to faults",
            "support control room",
            "supporting control room",
            "asset condition monitoring",
            "condition-based monitoring",
            "real-time operations",
            "scada support",
            "pi historian support",
            "field operations",
            "outage management",
            "network operations",
            "dispatch operations",
            "fault response",
        ],
        "sentence_indicators": [
            "steady state",
            "ongoing",
            "business as usual",
            "existing environment",
            "mature platform",
            "well-established",
            "ensure continuity",
            "support the team",
            "keep the lights on",
            "incident",
            "runbook",
            "observability",
            "control room",
            "dispatch",
            "outage management",
            "fault response",
            "network operations",
            "real-time operations",
            "field operations",
            "asset condition monitoring",
            "scada support",
            "ner compliance",
            "ams operations",
            "shift work",
            "shift roster",
            "rotating roster",
        ],
    },
    "translator": {
        "verb_patterns": [
            "enable {tech}",
            "train on {tech}",
            "translate requirements",
            "bridge technical and business",
            "self-serve",
            "data literacy",
            "empower stakeholders",
            "gather requirements",
            "communicate insights",
            "present findings",
            "democratise data",
            "engage with regulator",
            "engaging with regulator",
            "prepare regulatory submission",
            "preparing regulatory submission",
            "translate regulatory requirements",
            "translating regulatory requirements",
            "respond to regulator",
            "responding to regulator",
            "liaise with regulator",
            "liaising with regulator",
            "prepare aer submission",
            "prepare rin submission",
        ],
        "sentence_indicators": [
            "stakeholder",
            "non-technical",
            "business users",
            "executive reporting",
            "data-driven culture",
            "enable teams",
            "business intelligence",
            "analytics enablement",
            "self-serve",
            "semantic model",
            "aer submission",
            "aemo submission",
            "rin submission",
            "rin process",
            "regulatory submission",
            "regulator engagement",
            "ring-fencing",
            "community engagement",
            "outage communications",
            "customer-facing reporting",
        ],
    },
}

# Title markers for roles no longer being targeted. A listing whose title
# contains one of these is kept in the database for market intelligence but is
# never queued for application — see ``is_excluded_title``.
#
# These are customer-facing technical-selling roles (sales / solutions /
# forward-deployed engineering). They are not data-engineering JD shapes, so the
# four archetypes score them as noise; previously they were bucketed into
# "translator" so the mis-tag was at least consistent. Now that the role is not
# being pursued, that bucketing would make them *more* applyable, not less.
EXCLUDED_TITLE_MARKERS = (
    "sales engineer", "solutions engineer", "sales engineering",
    "solutions engineering", "pre-sales", "presales", "forward deployed",
    "forward-deployed", "solutions architect", "solutions consultant",
    "customer engineer", "field engineer", "technical account manager",
    "customer success engineer", "technical sales", "implementation consultant",
    "implementation engineer", "deployment engineer", "professional services",
    "customer solutions",
)


def is_excluded_title(job_title: str) -> bool:
    """True when a listing title names a role that is no longer targeted."""
    title_lower = (job_title or "").strip().lower()
    if not title_lower:
        return False
    return any(marker in title_lower for marker in EXCLUDED_TITLE_MARKERS)


# Companies never auto-applied to, whatever the listing scores. These are the
# bespoke-channel targets from §Career (energy distributors + AEMO + Toyota —
# applied to by hand with tailored material, never a generic quick-apply) plus
# the current employer (D2i). Listings from these companies stay in the
# database for market intelligence — the career-target radar reads them — but
# an auto-application here would burn the hand-sent channel it exists to feed.
PROTECTED_COMPANY_MARKERS = (
    "d2i",
    "essential energy",
    "ausgrid",
    "endeavour energy",
    "powercor",
    "citipower",
    "jemena",
    "united energy",
    "ausnet",
    "aemo",
    "australian energy market operator",
    "origin energy",
    "toyota",
)


def is_protected_company(company_name: str) -> bool:
    """True when a listing's company is reserved for bespoke, hand-sent applications."""
    name_lower = (company_name or "").strip().lower()
    if not name_lower:
        return False
    return any(marker in name_lower for marker in PROTECTED_COMPANY_MARKERS)


KNOWN_TECH = [
    "snowflake",
    "dbt",
    "airflow",
    "spark",
    "kafka",
    "terraform",
    "aws",
    "azure",
    "gcp",
    "python",
    "sql",
    "kubernetes",
    "docker",
    "fivetran",
    "looker",
    "tableau",
    "power bi",
    "databricks",
    "redshift",
    "bigquery",
    "matillion",
    "informatica",
    "talend",
    "ssis",
    "ssas",
    "ssrs",
    "kimball",
    "data vault",
    "medallion",
    "scada",
    "pi historian",
    "osisoft",
    "gis",
    "smallworld",
    "ellipse",
    "maximo",
    "sap pm",
    "ami",
    "der",
    "historian",
]

# Matching is word-boundary, not substring. Several entries are short enough to
# appear inside ordinary English -- "der" in "under"/"considered", "ami" in
# "family"/"dynamic", "gis" in "logistics"/"registry" -- which tagged a sentence
# containing no technology at all as ['der', 'ami', 'gis'] and put "der" in 96%
# of the corpus. Anything built on these tags (market drift, centroids) learns
# noise unless the boundary holds.
#
# Boundaries are non-word characters rather than \b alone, so "power bi" matches
# inside a comma list and a trailing "." or ")" does not defeat it, while
# "bigquery" never satisfies "gis".
_TECH_PATTERNS = [
    (tech, re.compile(rf"(?<![0-9a-z]){re.escape(tech)}(?![0-9a-z])", re.IGNORECASE))
    for tech in KNOWN_TECH
]


def extract_tech_tags(text: str) -> List[str]:
    """Return the KNOWN_TECH entries genuinely present in ``text``."""
    if not text:
        return []
    return [tech for tech, pattern in _TECH_PATTERNS if pattern.search(text)]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class ArchetypeClassifier:
    """Hybrid classifier: verb-context rules with optional embedding support."""

    ARCHE_TYPES = ["builder", "fixer", "operator", "translator"]

    def __init__(
        self,
        patterns: Optional[Dict[str, Dict[str, List[str]]]] = None,
        enable_embeddings: bool = True,
        embedding_model_name: str = "all-MiniLM-L6-v2",
    ) -> None:
        self.patterns = patterns or ARCHETYPE_PATTERNS
        self.enable_embeddings = enable_embeddings
        self._embedding_model = None
        self._nltk_tokenize = None
        self._embedding_dim = 384

        self._compiled_patterns = self._compile_patterns(self.patterns)
        self._load_sentence_tokenizer()
        self._load_embedding_model(embedding_model_name)
        self._centroids = self._build_centroids()

    def _compile_patterns(self, patterns: Dict[str, Dict[str, List[str]]]) -> Dict:
        compiled = {}
        for archetype, entries in patterns.items():
            regex_patterns = []
            for pattern in entries.get("verb_patterns", []):
                escaped = re.escape(pattern.lower())
                has_placeholder = "{tech}" in pattern
                if has_placeholder:
                    # Allow common JD punctuation between tokens (e.g. "designing, building and...")
                    escaped = escaped.replace(r"\ ", r"[\s,;:/&\-]+")
                else:
                    escaped = escaped.replace(r"\ ", r"\s+")

                wildcard = escaped.replace(
                    re.escape("{tech}"),
                    r"[a-z0-9][a-z0-9\-\s\/&,\.]{0,80}",
                )
                regex_patterns.append(re.compile(wildcard, re.IGNORECASE))
            compiled[archetype] = {
                "verb_patterns": regex_patterns,
                "sentence_indicators": [
                    indicator.lower()
                    for indicator in entries.get("sentence_indicators", [])
                ],
            }
        return compiled

    def _load_sentence_tokenizer(self) -> None:
        try:
            import nltk

            self._nltk_tokenize = nltk.sent_tokenize
        except Exception:
            self._nltk_tokenize = None

    def _load_embedding_model(self, model_name: str) -> None:
        if not self.enable_embeddings:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._embedding_model = SentenceTransformer(model_name)
            self._embedding_dim = int(
                self._embedding_model.get_sentence_embedding_dimension()
            )
        except Exception as exc:
            logger.debug(f"sentence-transformers unavailable; using fallback: {exc}")
            self._embedding_model = None

    def _split_sentences(self, text: str) -> List[str]:
        if not text:
            return []
        if self._nltk_tokenize:
            try:
                return [s.strip() for s in self._nltk_tokenize(text) if s.strip()]
            except Exception:
                pass
        chunks = re.split(r"(?<=[\.!?])\s+", text)
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def embed_text(self, text: str) -> List[float]:
        """Generate deterministic embedding vector for text."""
        if not text:
            return [0.0] * self._embedding_dim

        if self._embedding_model is not None:
            vector = self._embedding_model.encode(text)
            return [float(v) for v in vector]

        dim = int(self._embedding_dim or 384)
        vector = [0.0] * dim
        tokens = re.findall(r"[a-z0-9_\-]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % dim
            vector[idx] += 1.0

        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def _build_centroids(self) -> Dict[str, List[float]]:
        centroids: Dict[str, List[float]] = {}
        for archetype, entries in self.patterns.items():
            phrases = entries.get("verb_patterns", []) + entries.get(
                "sentence_indicators", []
            )
            if not phrases:
                continue
            vectors = [self.embed_text(phrase) for phrase in phrases]
            if not vectors:
                continue
            length = len(vectors[0])
            centroid = [0.0] * length
            for vec in vectors:
                for idx, value in enumerate(vec):
                    centroid[idx] += value
            count = float(len(vectors))
            centroids[archetype] = [value / count for value in centroid]
        return centroids

    def _keyword_boosts(self, text_lower: str, title_lower: str) -> Dict[str, float]:
        """Apply small boosts for strong archetype cues.

        These boosts reduce brittle tie-breaking (e.g., builder winning on equal
        scores) and help handle common JD phrasing like noun-form "migration".
        """

        boosts = {archetype: 0.0 for archetype in self.ARCHE_TYPES}

        strong_fixer_tokens = [
            "legacy",
            "tech debt",
            "technical debt",
            "decommission",
            "decommissioning",
            "end of life",
            "uplift program",
            "platform uplift",
            "target state",
            "target-state",
            "transformation program",
            "erp transformation",
            "modernisation",
            "modernization",
            "redesign",
            "re-platform",
            "replatform",
            "asset data uplift",
            "regulatory uplift",
            "metering uplift",
            "scada migration",
            "pi historian migration",
            "osisoft migration",
            "gis migration",
            "ellipse migration",
            "maximo migration",
            "ring-fencing",
            "ring fencing",
        ]
        medium_fixer_tokens = [
            "migration",
            "migrate",
            "migrating",
            "transition",
            "transform",
            "refactor",
            "uplift",
            "modernis",
            "moderniz",
            "legacy gis",
            "legacy scada",
            "legacy ellipse",
        ]

        hard_operator_tokens = [
            "on-call",
            "on call",
            "incident response",
            "production support",
            "runbook",
            "run book",
            "sla",
            "slo",
            "sli",
            "control room",
            "outage management",
            "dispatch operations",
            "fault response",
            "network operations centre",
            "noc operations",
            "shift roster",
            "rotating roster",
        ]
        soft_operator_tokens = [
            "observability",
            "operational readiness",
            "operational resilience",
            "platform reliability",
            "asset condition monitoring",
            "condition-based monitoring",
            "scada support",
            "pi historian support",
            "real-time operations",
            "field operations",
            "ner compliance",
        ]
        translator_tokens = [
            "self-serve",
            "self serve",
            "semantic model",
            "executive reporting",
            "business intelligence",
            "data literacy",
            "analytics enablement",
            "aer submission",
            "aemo submission",
            "rin submission",
            "rin process",
            "regulatory submission",
            "regulator engagement",
            "community engagement",
            "outage communications",
        ]
        builder_tokens = [
            "greenfield",
            "from the ground up",
            "from scratch",
            "0->1",
            "zero to one",
            "new platform",
            "first hire",
        ]

        if any(token in text_lower for token in strong_fixer_tokens):
            boosts["fixer"] += 1.2
        else:
            medium_hits = sum(1 for token in medium_fixer_tokens if token in text_lower)
            if medium_hits >= 2:
                boosts["fixer"] += 1.0

        if any(token in text_lower for token in hard_operator_tokens):
            boosts["operator"] += 1.2
        else:
            soft_hits = sum(1 for token in soft_operator_tokens if token in text_lower)
            if soft_hits >= 2:
                boosts["operator"] += 0.8

        # Translator is intentionally conservative; avoid dominating DE roles
        # that simply mention "stakeholders".
        translator_hits = sum(1 for token in translator_tokens if token in text_lower)
        if translator_hits >= 2:
            boosts["translator"] += 0.8
        elif translator_hits == 1 and "self-serve" in text_lower:
            boosts["translator"] += 0.5

        if any(token in text_lower for token in builder_tokens):
            boosts["builder"] += 0.6

        if "data architect" in title_lower and boosts["fixer"] > 0:
            boosts["fixer"] += 0.2
        if "platform engineer" in title_lower and boosts["operator"] > 0:
            boosts["operator"] += 0.2
        if "asset" in title_lower and "engineer" in title_lower and boosts["fixer"] > 0:
            boosts["fixer"] += 0.2
        if "regulatory" in title_lower and boosts["translator"] > 0:
            boosts["translator"] += 0.2
        if "rin analyst" in title_lower:
            boosts["translator"] += 0.4
        if "network operations" in title_lower and boosts["operator"] > 0:
            boosts["operator"] += 0.2
        if "control room" in title_lower:
            boosts["operator"] += 0.4
        if "ot " in title_lower or "ot/it" in title_lower or "ot integration" in title_lower:
            boosts["operator"] += 0.2

        return boosts

    def extract_metadata(self, jd_text: str, job_title: str) -> Dict:
        """Extract structured metadata and priors from JD content."""
        text_lower = (jd_text or "").lower()
        title_lower = (job_title or "").lower()

        job_type = "unknown"
        if any(
            token in text_lower
            for token in ["contract", "fixed term", "fixed-term", "6 month", "12 month"]
        ):
            job_type = "contract"
        elif any(
            token in text_lower
            for token in ["permanent", "full-time", "full time", "ongoing"]
        ):
            job_type = "permanent"

        tech_tags = extract_tech_tags(text_lower)

        seniority = "mid"
        if any(token in title_lower for token in ["junior", "graduate", "entry"]):
            seniority = "junior"
        elif any(token in title_lower for token in ["senior", "sr.", "sr "]):
            seniority = "senior"
        elif any(
            token in title_lower for token in ["lead", "principal", "staff", "head of"]
        ):
            seniority = "lead"

        prior: Dict[str, float] = {}
        if job_type == "contract":
            prior = {
                "builder": 0.1,
                "fixer": 0.1,
                "operator": -0.05,
                "translator": -0.05,
            }
        elif job_type == "permanent":
            prior = {
                "builder": -0.05,
                "fixer": -0.05,
                "operator": 0.05,
                "translator": 0.05,
            }

        return {
            "job_type": job_type,
            "tech_stack_tags": tech_tags,
            "seniority_level": seniority,
            "archetype_prior": prior,
        }

    def score_jd(self, jd_text: str, job_title: str = "") -> Dict[str, float]:
        """Return normalized archetype weights for a full job description."""
        sentences = self._split_sentences(jd_text)
        metadata = self.extract_metadata(jd_text, job_title)
        prior = metadata.get("archetype_prior", {})

        text_lower = (jd_text or "").lower()
        title_lower = (job_title or "").lower()

        raw_scores = {archetype: 0.0 for archetype in self.ARCHE_TYPES}

        for sentence in sentences:
            sentence_lower = sentence.lower()

            for archetype, compiled in self._compiled_patterns.items():
                for pattern in compiled["verb_patterns"]:
                    if pattern.search(sentence_lower):
                        raw_scores[archetype] += 1.0
                for indicator in compiled["sentence_indicators"]:
                    if indicator in sentence_lower:
                        raw_scores[archetype] += 0.5

            if self.enable_embeddings and self._centroids:
                sentence_embedding = self.embed_text(sentence)
                for archetype, centroid in self._centroids.items():
                    similarity = _cosine_similarity(sentence_embedding, centroid)
                    if similarity > 0.5:
                        raw_scores[archetype] += similarity * 0.3

        for archetype, shift in prior.items():
            raw_scores[archetype] = raw_scores.get(archetype, 0.0) + float(shift)

        boosts = self._keyword_boosts(text_lower=text_lower, title_lower=title_lower)
        for archetype, boost in boosts.items():
            raw_scores[archetype] = raw_scores.get(archetype, 0.0) + float(boost)

        bounded_scores = {key: max(0.0, value) for key, value in raw_scores.items()}
        total = sum(bounded_scores.values())
        if total > 0:
            return {
                archetype: round(score / total, 3)
                for archetype, score in bounded_scores.items()
            }
        return {archetype: 0.25 for archetype in self.ARCHE_TYPES}

    def classify(self, jd_text: str, job_title: str = "") -> Dict:
        """Classify JD and return scores, primary archetype, metadata, and embedding."""
        scores = self.score_jd(jd_text=jd_text, job_title=job_title)
        primary = max(scores, key=scores.get)
        metadata = self.extract_metadata(jd_text, job_title)
        embedding = self.embed_text(jd_text)

        return {
            "archetype_scores": scores,
            "archetype_primary": primary,
            "embedding_vector": embedding,
            "job_type": metadata["job_type"],
            "tech_stack_tags": metadata["tech_stack_tags"],
            "seniority_level": metadata["seniority_level"],
            "archetype_prior": metadata["archetype_prior"],
            # Scores stay as-is so the row remains readable for analytics; the
            # queue is what refuses to act on it.
            "role_excluded": is_excluded_title(job_title),
        }

    def get_centroid(self, archetype: str) -> List[float]:
        """Return centroid vector for one archetype."""
        return self._centroids.get(archetype, [])

    @staticmethod
    def cosine_similarity(left: List[float], right: List[float]) -> float:
        """Public cosine helper for downstream components."""
        return _cosine_similarity(left, right)
