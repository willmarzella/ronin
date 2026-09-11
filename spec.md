# Self-Improving Job Applier — Technical Implementation Spec

**Audience:** LLM or developer implementing this system.
**Owner:** Will (data engineering contractor, Melbourne, AU)
**Runtime:** Split architecture — Local Agent (residential IP) + Remote Worker (hosted VPS)

---

## System Overview

An automated job application pipeline that:
1. Scrapes job descriptions from Seek across multiple keyword searches
2. Classifies each JD into one of four work-shape archetypes using verb-context pattern analysis
3. Selects the appropriate resume variant per archetype
4. Queues and batches applications by archetype to coordinate with Seek profile state
5. Captures application outcomes from Gmail (and manual phone call logging) to close the feedback loop
6. Tracks market drift via rolling embedding centroids and triggers resume rewrites when both market shift and resume staleness co-occur
7. Versions all resume variants in Git with commit hashes tied to application records for performance attribution

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              REMOTE WORKER (VPS)            │
│                                             │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │ Gmail Poller │  │ Archetype Classifier │  │
│  │ (15 min)     │  │ (on JD insert)       │  │
│  └──────┬──────┘  └──────────┬───────────┘  │
│         │                    │               │
│  ┌──────▼──────┐  ┌─────────▼────────────┐  │
│  │ Email Parser│  │ Embedding Pipeline   │  │
│  │ + Matcher   │  │ (sentence-transformers)│ │
│  └──────┬──────┘  └─────────┬────────────┘  │
│         │                    │               │
│  ┌──────▼────────────────────▼────────────┐  │
│  │         PostgreSQL / SQLite            │  │
│  │         (source of truth)              │  │
│  └──────────────────┬─────────────────────┘  │
│         ┌───────────┤                        │
│  ┌──────▼──────┐  ┌─▼───────────────────┐   │
│  │ Drift       │  │ Funnel Metrics      │   │
│  │ Detection   │  │ + Performance       │   │
│  │ (weekly)    │  │   Reporting         │   │
│  └─────────────┘  └─────────────────────┘   │
│                                             │
└──────────────────────┬──────────────────────┘
                       │ SSH tunnel / HTTPS API
┌──────────────────────▼──────────────────────┐
│            LOCAL AGENT (Will's machine)      │
│                                             │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │ Seek Scraper│  │ Seek Profile Updater │  │
│  │ (residential│  │ (Playwright/Selenium)│  │
│  │  IP only)   │  │                      │  │
│  └──────┬──────┘  └──────────┬───────────┘  │
│         │                    │               │
│  ┌──────▼──────┐  ┌─────────▼────────────┐  │
│  │ Application │  │ CLI Interface        │  │
│  │ Submitter   │  │                      │  │
│  └─────────────┘  └─────────────────────┘  │
│                                             │
│  ┌─────────────────────────────────────────┐ │
│  │ Local Sync Queue (SQLite)              │ │
│  │ (buffers when remote unavailable)       │ │
│  └─────────────────────────────────────────┘ │
│                                             │
│  ┌─────────────────────────────────────────┐ │
│  │ Git Repo: ~/job-applier/resumes/       │ │
│  │ builder.md | fixer.md | operator.md |  │ │
│  │ translator.md + alignment JSONs        │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## Database Schema

Engine: SQLite (sufficient at hundreds of records, single user). Upgrade to PostgreSQL on remote worker if concurrent access becomes an issue.

### Table: `applications`
```sql
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seek_job_id TEXT,                           -- Seek's internal job identifier
    job_title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    job_description_text TEXT NOT NULL,          -- full JD body
    date_scraped DATE NOT NULL,
    date_applied DATE,                          -- null if queued but not yet applied
    job_type TEXT,                               -- 'contract' | 'permanent' | 'unknown'
    day_rate_or_salary TEXT,                     -- raw text if present
    seniority_level TEXT,                        -- 'junior' | 'mid' | 'senior' | 'lead' | 'unknown'
    tech_stack_tags TEXT,                        -- JSON array of extracted technology names
    search_keyword_origin TEXT,                  -- which search term surfaced this JD

    -- Archetype classification
    archetype_scores TEXT,                       -- JSON: {"builder": 0.45, "fixer": 0.35, "operator": 0.05, "translator": 0.15}
    archetype_primary TEXT,                      -- highest scoring archetype
    embedding_vector BLOB,                       -- sentence-transformers embedding of full JD

    -- Application metadata
    resume_variant_sent TEXT,                    -- 'builder' | 'fixer' | 'operator' | 'translator'
    resume_commit_hash TEXT,                     -- git commit hash of resume variant at time of application
    profile_state_at_application TEXT,           -- which archetype the Seek profile was set to
    application_batch_id INTEGER,                -- links to batch record

    -- Outcome tracking
    outcome_stage TEXT DEFAULT 'applied',        -- 'applied' | 'acknowledged' | 'viewed' | 'rejected' | 'interview_request' | 'offer' | 'ghost'
    outcome_date DATE,
    outcome_email_id TEXT,                       -- reference to email_parsed.id

    -- Market intelligence flag
    market_intelligence_only BOOLEAN DEFAULT 0,  -- 1 = not applied, used for drift detection only

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `email_parsed`
```sql
CREATE TABLE email_parsed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT UNIQUE NOT NULL,
    date_received TIMESTAMP NOT NULL,
    sender_address TEXT NOT NULL,
    sender_domain TEXT NOT NULL,
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    source_type TEXT NOT NULL,                   -- 'seek' | 'direct' | 'agency' | 'unknown'
    outcome_classification TEXT,                 -- 'acknowledged' | 'viewed' | 'rejected' | 'interview_request' | 'offer' | 'other'
    classification_confidence REAL,              -- 0.0-1.0 based on keyword match density
    matched_application_id INTEGER REFERENCES applications(id),
    match_method TEXT,                           -- 'seek_job_id' | 'domain_title_date' | 'fuzzy' | 'manual' | 'unmatched'
    requires_manual_review BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `known_senders`
```sql
CREATE TABLE known_senders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_address TEXT NOT NULL,
    domain TEXT NOT NULL,
    company_name TEXT,
    sender_type TEXT DEFAULT 'unknown',          -- 'recruiter_agency' | 'hiring_manager' | 'hr_internal' | 'unknown'
    first_seen_date DATE NOT NULL,
    UNIQUE(email_address)
);
```

### Table: `resume_variants`
```sql
CREATE TABLE resume_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype TEXT UNIQUE NOT NULL,              -- 'builder' | 'fixer' | 'operator' | 'translator'
    file_path TEXT NOT NULL,                     -- path in git repo
    current_commit_hash TEXT NOT NULL,
    embedding_vector BLOB,
    alignment_score REAL,                        -- cosine similarity to archetype centroid
    last_rewritten DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `market_centroids`
```sql
CREATE TABLE market_centroids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype TEXT NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    centroid_vector BLOB NOT NULL,
    jd_count INTEGER NOT NULL,                   -- number of JDs in this window for this archetype
    shift_from_previous REAL,                    -- cosine distance from prior window's centroid
    top_gained_terms TEXT,                        -- JSON array: terms closer to new centroid than old
    top_lost_terms TEXT,                          -- JSON array: terms farther from new centroid than old
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(archetype, window_start)
);
```

### Table: `drift_alerts`
```sql
CREATE TABLE drift_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype TEXT NOT NULL,
    alert_type TEXT NOT NULL,                    -- 'market_shift' | 'resume_stale' | 'rewrite_triggered'
    metric_value REAL NOT NULL,
    threshold_value REAL NOT NULL,
    details TEXT,                                 -- JSON: contextual info about what changed
    acknowledged BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `application_batches`
```sql
CREATE TABLE application_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype TEXT NOT NULL,
    profile_state TEXT NOT NULL,                  -- archetype the Seek profile was set to
    batch_start_date TIMESTAMP NOT NULL,
    batch_end_date TIMESTAMP,
    application_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `phone_call_log`
```sql
CREATE TABLE phone_call_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number TEXT,
    company_name TEXT,
    job_title TEXT,
    outcome TEXT,                                 -- 'screening_call' | 'interview' | 'rejection' | 'other'
    notes TEXT,
    call_date DATE NOT NULL,
    matched_application_id INTEGER REFERENCES applications(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Epic 1: Gmail Integration for Outcome Tracking

### Task 1.1: Gmail API Setup

**Implementation:**

```python
# Dependencies
# pip install google-auth google-auth-oauthlib google-api-python-client

# OAuth2 setup
# 1. Create project at console.cloud.google.com
# 2. Enable Gmail API
# 3. Create OAuth2 credentials (Desktop application type)
# 4. Download credentials.json to project root
# Scopes needed: 'https://www.googleapis.com/auth/gmail.readonly'
```

- Authenticate using OAuth2 with offline access (refresh token stored locally for unattended polling on remote worker)
- Poll interval: every 15 minutes via APScheduler
- Query filter: `newer_than:1d` on each poll to limit fetch volume. Track last-processed message ID to avoid reprocessing.
- Intake filter: process ALL inbound emails. Exclude known personal/spam senders using a configurable ignore list stored in a `sender_ignore_list` table (domains and addresses, manually seeded, expanded over time).

### Task 1.2: Email Parser

**For Seek emails (`noreply@seek.com.au` and variants):**
- Parse HTML body to extract: job title, company name, Seek job reference ID (found in URL query parameters within email body, pattern: `jobId=\d+` or `/job/\d+`), outcome type
- Seek emails are templated — build a regex map from 10+ manually inspected Seek emails to identify extraction patterns

**For non-Seek emails:**
- Extract: sender address, sender domain (split on `@`, take right side), subject line, plain text body (strip HTML), all URLs, date received
- Store sender domain for cascade matching in Task 1.4

**Output:** One `email_parsed` record per processed email.

### Task 1.3: Outcome Classifier

**Rule-based classifier. No ML needed at this scale.**

```python
OUTCOME_RULES = {
    'rejected': {
        'keywords': ['unfortunately', 'other candidates', 'not progressing',
                     'position has been filled', 'we will not be', 'unsuccessful',
                     'decided not to proceed', 'not shortlisted', 'gone with another'],
        'min_matches': 1
    },
    'interview_request': {
        'keywords': ['availability', 'phone screen', 'would like to discuss',
                     'schedule', 'interview', 'meet with', 'arrange a time',
                     'chat about the role', 'initial conversation', 'when are you free'],
        'min_matches': 1
    },
    'viewed': {
        'keywords': ['your application was viewed', 'has viewed your application',
                     'viewed your profile'],
        'min_matches': 1
    },
    'acknowledged': {
        'keywords': ['application received', 'thank you for applying',
                     'we have received', 'application submitted'],
        'min_matches': 1
    }
}
```

- Match against lowercased body text
- Priority order: interview_request > rejected > viewed > acknowledged > other (if multiple categories match, take highest priority)
- Confidence score = matched_keywords / total_keywords_in_category
- If no category matches with min_matches, classify as 'other'

### Task 1.4: Application Matching

**Seek emails (structured):**
- Extract Seek job ID from email. Direct lookup against `applications.seek_job_id`. This is a deterministic match.

**Non-Seek emails (cascade):**

```python
def match_email_to_application(email: ParsedEmail, applications: List[Application]) -> MatchResult:
    candidates = applications  # start with all

    # Step 1: Domain match
    known = lookup_known_sender(email.sender_address)
    if known:
        candidates = [a for a in candidates if fuzzy_match(a.company_name, known.company_name) > 0.7]
    else:
        sender_domain_root = extract_root_domain(email.sender_domain)  # e.g., 'woolworths' from 'woolworths.com.au'
        candidates = [a for a in candidates if fuzzy_match(a.company_name, sender_domain_root) > 0.5]

    if not candidates:
        return MatchResult(status='unmatched', candidates=[])

    # Step 2: Title match
    scored = []
    for app in candidates:
        title_sim = token_jaccard(email.subject + ' ' + email.body_text, app.job_title)
        scored.append((app, title_sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    candidates = [(app, score) for app, score in scored if score > 0.2]

    # Step 3: Tech keyword overlap
    for i, (app, score) in enumerate(candidates):
        tech_tags = json.loads(app.tech_stack_tags or '[]')
        body_overlap = sum(1 for tag in tech_tags if tag.lower() in email.body_text.lower())
        candidates[i] = (app, score + body_overlap * 0.1)

    # Step 4: Date proximity
    for i, (app, score) in enumerate(candidates):
        days_diff = (email.date_received - app.date_applied).days
        if 0 <= days_diff <= 30:
            candidates[i] = (app, score + 0.2)
        elif 30 < days_diff <= 60:
            candidates[i] = (app, score + 0.1)

    candidates.sort(key=lambda x: x[1], reverse=True)

    if len(candidates) == 1 and candidates[0][1] > 0.5:
        return MatchResult(status='auto_matched', application=candidates[0][0])
    elif len(candidates) > 0:
        return MatchResult(status='manual_review', candidates=candidates[:3])
    else:
        return MatchResult(status='unmatched', candidates=[])
```

- On confirmed match (auto or manual): upsert `known_senders` with sender address, domain, company name, sender type
- Write outcome to `applications.outcome_stage`, `applications.outcome_date`, `applications.outcome_email_id`

### Task 1.5: Phone Call Intake

**Lightweight local web form. Flask, single endpoint.**

```python
@app.route('/log-call', methods=['GET', 'POST'])
def log_call():
    if request.method == 'POST':
        record = PhoneCallLog(
            phone_number=request.form.get('phone'),
            company_name=request.form['company'],
            job_title=request.form['title'],
            outcome=request.form['outcome'],
            notes=request.form.get('notes'),
            call_date=request.form['date']
        )
        # Fuzzy match to application using same cascade as email matching
        match = match_call_to_application(record)
        if match.status == 'auto_matched':
            record.matched_application_id = match.application.id
            update_application_outcome(match.application, record.outcome, record.call_date)
        db.session.add(record)
        db.session.commit()
        return redirect('/log-call?success=1')
    return render_template('call_form.html')
```

- Accessible at `localhost:5001/log-call` on local machine
- Fields: phone number (optional), company name, job title, outcome (dropdown: screening_call, interview, rejection, other), date, notes
- On submit, run same fuzzy matching as Task 1.4 against applications table

### Task 1.6: Funnel Dashboard

**SQL queries for funnel metrics:**

```sql
-- Overall funnel
SELECT
    COUNT(*) as total_applied,
    SUM(CASE WHEN outcome_stage != 'applied' THEN 1 ELSE 0 END) as any_response,
    SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) as viewed,
    SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) as interviews,
    SUM(CASE WHEN outcome_stage = 'rejected' THEN 1 ELSE 0 END) as rejected,
    SUM(CASE WHEN outcome_stage = 'applied'
         AND date_applied < date('now', '-30 days') THEN 1 ELSE 0 END) as ghost
FROM applications
WHERE market_intelligence_only = 0;

-- Monthly breakdown
SELECT
    strftime('%Y-%m', date_applied) as month,
    COUNT(*) as applied,
    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) / COUNT(*), 1) as view_rate,
    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) as interview_rate
FROM applications
WHERE market_intelligence_only = 0
GROUP BY month
ORDER BY month DESC;

-- By archetype
SELECT
    archetype_primary,
    COUNT(*) as applied,
    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) as interview_rate
FROM applications
WHERE market_intelligence_only = 0
GROUP BY archetype_primary;
```

- Output as formatted terminal table (use `tabulate` library) or simple local HTML page
- Include: total applications, view rate, response rate, interview rate, rejection rate, ghost rate (no signal after 30 days)
- Break down by: month, archetype, resume version (commit hash)

---

## Epic 2: Job Description Archetype Classifier

### Task 2.1: Prerequisite — Corpus Analysis

**Run before any manual labelling:**

```sql
-- Normalise and count job titles
SELECT
    LOWER(REPLACE(REPLACE(REPLACE(REPLACE(job_title,
        'Senior ', ''), 'Lead ', ''), 'Junior ', ''), 'Principal ', '')) as normalised_title,
    COUNT(*) as count
FROM applications
GROUP BY normalised_title
ORDER BY count DESC
LIMIT 30;
```

- If data engineering variants > 80% of corpus, confirm single-domain scope. Drop platform engineering from system scope.
- Use this analysis to understand the actual distribution of roles you've been applying to.

### Task 2.1: Seed Dictionary Construction

**Verb-pattern templates, NOT keyword lists. The technology noun is irrelevant to classification. The verb context is the signal.**

```python
ARCHETYPE_PATTERNS = {
    'builder': {
        'verb_patterns': [
            'build {tech}', 'design {tech}', 'design and implement {tech}',
            'architect {tech}', 'implement {tech} from scratch',
            'establish {tech}', 'create {tech}', 'set up {tech}',
            'develop new {tech}', 'stand up {tech}', 'greenfield',
            'from the ground up', 'define standards', 'new platform',
            'cloud-native', 'founding', 'build out', 'develop and deploy',
            'create a new', 'design the architecture', 'lead the development of'
        ],
        'sentence_indicators': [
            'no existing', 'first hire', 'new team', 'newly created',
            'start-up phase', 'zero to one', 'ground floor',
            'vision for', 'shape the direction'
        ]
    },
    'fixer': {
        'verb_patterns': [
            'migrate {tech}', 'migrate from {tech} to {tech}',
            'consolidate {tech}', 'refactor {tech}', 'modernise {tech}',
            'replace {tech}', 'uplift {tech}', 'remediate {tech}',
            'transition from {tech}', 'sunset {tech}', 'decommission {tech}',
            'optimise {tech}', 're-platform', 'improve existing',
            'reduce complexity', 'streamline', 'transform legacy',
            'clean up', 'rationalise'
        ],
        'sentence_indicators': [
            'legacy', 'tech debt', 'technical debt', 'end of life',
            'current state', 'pain points', 'inefficiencies',
            'aging infrastructure', 'manual processes',
            'existing systems need', 'outdated'
        ]
    },
    'operator': {
        'verb_patterns': [
            'maintain {tech}', 'support {tech}', 'monitor {tech}',
            'ensure reliability of {tech}', 'manage {tech}',
            'administer {tech}', 'troubleshoot {tech}',
            'on-call', 'incident response', 'production support',
            'BAU', 'run book', 'SLA', 'ensure uptime',
            'day-to-day management'
        ],
        'sentence_indicators': [
            'steady state', 'ongoing', 'business as usual',
            'existing environment', 'mature platform',
            'well-established', 'ensure continuity',
            'support the team', 'keep the lights on'
        ]
    },
    'translator': {
        'verb_patterns': [
            'enable {tech}', 'train on {tech}',
            'translate requirements', 'bridge technical and business',
            'self-serve', 'data literacy', 'empower stakeholders',
            'gather requirements', 'communicate insights',
            'present findings', 'democratise data'
        ],
        'sentence_indicators': [
            'stakeholder', 'cross-functional', 'non-technical',
            'business users', 'executive reporting',
            'data-driven culture', 'enable teams',
            'business intelligence', 'analytics enablement',
            'partner with', 'collaborate closely with business'
        ]
    }
}
```

**Manual labelling process:**
1. Sample 50 JDs from corpus
2. For each JD, read the description and assign primary archetype + secondary (if applicable)
3. Record which specific sentences drove the decision
4. Add any new verb patterns discovered to the seed dictionary
5. Target: 20-30 verb patterns and 10-15 sentence indicators per archetype minimum

### Task 2.2: Embedding-Based Dictionary Expansion

**Model:** `sentence-transformers/all-MiniLM-L6-v2` (fast, 384-dimensional, sufficient for this use case)

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer('all-MiniLM-L6-v2')

# Compute archetype centroids from seed patterns
archetype_centroids = {}
for archetype, patterns in ARCHETYPE_PATTERNS.items():
    all_phrases = patterns['verb_patterns'] + patterns['sentence_indicators']
    embeddings = model.encode(all_phrases)
    archetype_centroids[archetype] = np.mean(embeddings, axis=0)

# Scan corpus for expansion candidates
for jd in all_job_descriptions:
    sentences = split_into_sentences(jd.text)  # use nltk.sent_tokenize
    for sentence in sentences:
        emb = model.encode(sentence)
        for archetype, centroid in archetype_centroids.items():
            similarity = cosine_similarity(emb, centroid)
            if similarity > 0.65:
                # Check if sentence contains terms not in existing dictionary
                # Flag as expansion candidate for manual review
                log_expansion_candidate(archetype, sentence, similarity)
```

- One-time batch process against full corpus
- Manually review expansion candidates, add confirmed good patterns to seed dictionary
- Recompute centroids after expansion
- Re-run only if classification quality degrades (monitored in Task 2.5)

### Task 2.3: JD Scoring Pipeline

**Core principle: keywords don't classify. Verb-in-context classifies.**

```python
import nltk
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer('all-MiniLM-L6-v2')

def score_jd(jd_text: str, archetype_centroids: dict, archetype_patterns: dict) -> dict:
    sentences = nltk.sent_tokenize(jd_text)
    archetype_scores = {a: 0.0 for a in archetype_centroids}

    for sentence in sentences:
        sentence_lower = sentence.lower()

        # Keyword pattern matching (verb-context patterns)
        for archetype, patterns in archetype_patterns.items():
            for pattern in patterns['verb_patterns']:
                # Replace {tech} with wildcard for matching
                regex_pattern = pattern.replace('{tech}', r'\w[\w\s]*')
                if re.search(regex_pattern, sentence_lower):
                    archetype_scores[archetype] += 1.0

            for indicator in patterns['sentence_indicators']:
                if indicator.lower() in sentence_lower:
                    archetype_scores[archetype] += 0.5

        # Embedding similarity (supplements keyword matching)
        emb = model.encode(sentence)
        for archetype, centroid in archetype_centroids.items():
            sim = cosine_similarity(emb, centroid)
            if sim > 0.5:  # only count meaningfully similar sentences
                archetype_scores[archetype] += sim * 0.3  # weighted lower than keyword matches

    # Normalise to sum to 1.0
    total = sum(archetype_scores.values())
    if total > 0:
        archetype_scores = {a: round(s / total, 3) for a, s in archetype_scores.items()}
    else:
        archetype_scores = {a: 0.25 for a in archetype_scores}  # uniform if no signal

    return archetype_scores
```

- Run on every new JD inserted into the database
- Store scores as JSON in `applications.archetype_scores`
- Set `applications.archetype_primary` to the highest-scoring archetype
- Also compute and store the full JD embedding in `applications.embedding_vector`

### Task 2.4: Supplementary Signal Extraction

**Extract structured metadata from each JD:**

```python
def extract_metadata(jd_text: str, job_title: str) -> dict:
    text_lower = jd_text.lower()

    # Job type
    job_type = 'unknown'
    if any(t in text_lower for t in ['contract', 'fixed term', 'fixed-term', '6 month', '12 month']):
        job_type = 'contract'
    elif any(t in text_lower for t in ['permanent', 'full-time', 'full time', 'ongoing']):
        job_type = 'permanent'

    # Tech stack extraction
    KNOWN_TECH = ['snowflake', 'dbt', 'airflow', 'spark', 'kafka', 'terraform',
                  'aws', 'azure', 'gcp', 'python', 'sql', 'kubernetes', 'docker',
                  'fivetran', 'looker', 'tableau', 'power bi', 'databricks',
                  'redshift', 'bigquery', 'matillion', 'informatica', 'talend',
                  'ssis', 'ssas', 'ssrs', 'kimball', 'data vault', 'medallion']
    tech_tags = [t for t in KNOWN_TECH if t in text_lower]

    # Seniority
    title_lower = job_title.lower()
    seniority = 'mid'
    if any(s in title_lower for s in ['junior', 'graduate', 'entry']):
        seniority = 'junior'
    elif any(s in title_lower for s in ['senior', 'sr.', 'sr ']):
        seniority = 'senior'
    elif any(s in title_lower for s in ['lead', 'principal', 'staff', 'head of']):
        seniority = 'lead'

    # Archetype prior based on job type
    # Contract roles skew Builder/Fixer (project-based, immediate start)
    # Permanent roles skew Operator/Translator (ongoing, embedded in team)
    archetype_prior = {}
    if job_type == 'contract':
        archetype_prior = {'builder': 0.1, 'fixer': 0.1, 'operator': -0.05, 'translator': -0.05}
    elif job_type == 'permanent':
        archetype_prior = {'builder': -0.05, 'fixer': -0.05, 'operator': 0.05, 'translator': 0.05}

    return {
        'job_type': job_type,
        'tech_stack_tags': tech_tags,
        'seniority_level': seniority,
        'archetype_prior': archetype_prior
    }
```

- Apply `archetype_prior` as an additive adjustment to the raw archetype scores BEFORE normalisation in Task 2.3
- Store all extracted fields on the application record

### Task 2.5: Validation

```python
def validate_classifier(labelled_jds: List[Tuple[str, str]], archetype_centroids, archetype_patterns):
    correct = 0
    total = len(labelled_jds)
    disagreements = []

    for jd_text, manual_label in labelled_jds:
        scores = score_jd(jd_text, archetype_centroids, archetype_patterns)
        predicted = max(scores, key=scores.get)

        if predicted == manual_label:
            correct += 1
        else:
            disagreements.append({
                'predicted': predicted,
                'predicted_score': scores[predicted],
                'manual': manual_label,
                'manual_score': scores[manual_label],
                'jd_snippet': jd_text[:200]
            })

    accuracy = correct / total
    print(f"Agreement: {accuracy:.1%} ({correct}/{total})")

    if accuracy < 0.70:
        print("WARNING: Below 70% threshold. Seed dictionaries need expansion.")
        print("Review disagreements:")
        for d in disagreements:
            print(f"  Predicted {d['predicted']} ({d['predicted_score']:.2f}) "
                  f"vs Manual {d['manual']} ({d['manual_score']:.2f})")
            print(f"  Snippet: {d['jd_snippet']}")

    return accuracy, disagreements
```

- Run against 50 manually labelled JDs
- Target: >75% agreement on primary archetype
- If below 70%, inspect disagreements, expand seed dictionaries, re-run

---

## Epic 3: Resume Variant System

### Task 3.1: Write Four Base Variants

**File structure in Git repo:**

```
~/job-applier/resumes/
├── builder.md
├── builder.alignment.json
├── fixer.md
├── fixer.alignment.json
├── operator.md
├── operator.alignment.json
├── translator.md
├── translator.alignment.json
└── shared/
    └── base_experience.json    # structured facts used by all variants
```

**Resume structure (each variant is a Markdown file with YAML frontmatter):**

```markdown
---
archetype: builder
version: 1
last_updated: 2026-02-17
---

# Will [Last Name]
Data Engineer | Melbourne, AU

## Summary
[2-3 sentences. Builder variant: emphasise architecture, greenfield, technology selection]

## Experience

### [Company] — [Title] (Date - Date)
- [Bullet framed for builder archetype: "Designed and implemented...", "Architected...", "Selected and deployed..."]
- [Bullet framed for builder archetype]
- [Domain-flex block — always included, framing varies]

### [Company] — [Title] (Date - Date)
...

## Technical Skills
[Ordered by relevance to builder archetype]

## Education
...
```

- All four variants share the same facts. They differ in: summary, bullet point ordering, verb choice, which projects are emphasised, skills ordering.
- Each variant is a standalone resume — not a template with merge fields.
- Commit initial versions with message: `"baseline: initial four archetype variants"`

### Task 3.2: Resume-to-Archetype Alignment Scoring

```python
def compute_alignment(resume_path: str, archetype: str, archetype_centroids: dict) -> float:
    with open(resume_path) as f:
        resume_text = f.read()
    resume_embedding = model.encode(resume_text)
    centroid = archetype_centroids[archetype]
    alignment = cosine_similarity(resume_embedding, centroid)

    # Write alignment metadata
    alignment_data = {
        'archetype': archetype,
        'alignment_score': round(float(alignment), 4),
        'computed_date': datetime.now().isoformat(),
        'commit_hash': get_current_commit_hash()
    }
    alignment_path = resume_path.replace('.md', '.alignment.json')
    with open(alignment_path, 'w') as f:
        json.dump(alignment_data, f, indent=2)

    return alignment
```

- Run after every resume commit
- Commit alignment JSON alongside resume: `"score: builder alignment 0.72 at commit abc1234"`

### Task 3.3: Variant Selection Logic

```python
def select_variant(jd_archetype_scores: dict, resume_variants: dict) -> Tuple[str, bool]:
    """
    Returns: (selected_archetype, needs_manual_review)
    """
    sorted_archetypes = sorted(jd_archetype_scores.items(), key=lambda x: x[1], reverse=True)
    top = sorted_archetypes[0]
    second = sorted_archetypes[1]

    if top[1] - second[1] < 0.10:
        # Close call — flag for manual review
        return top[0], True
    else:
        return top[0], False
```

- On application: record `resume_variant_sent`, `resume_commit_hash` (from `git rev-parse HEAD` of the variant file), `profile_state_at_application`
- Log selection rationale (scores, whether manual review was flagged) for later analysis

### Task 3.4: Resume Performance by Version

```sql
-- Performance by resume version per archetype
SELECT
    resume_variant_sent as archetype,
    resume_commit_hash as version,
    COUNT(*) as applications,
    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'viewed' THEN 1 ELSE 0 END) / COUNT(*), 1) as view_rate,
    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'interview_request' THEN 1 ELSE 0 END) / COUNT(*), 1) as interview_rate,
    ROUND(100.0 * SUM(CASE WHEN outcome_stage = 'rejected' THEN 1 ELSE 0 END) / COUNT(*), 1) as rejection_rate
FROM applications
WHERE market_intelligence_only = 0
  AND date_applied IS NOT NULL
GROUP BY resume_variant_sent, resume_commit_hash
HAVING applications >= 15  -- minimum sample size before drawing conclusions
ORDER BY archetype, version;
```

- Minimum 15-20 applications per version before comparing metrics
- Compare across versions to determine if rewrites improved or degraded performance
- Alert if a new version performs worse than previous across 20+ applications

---

## Epic 4: Seek Profile Batch Strategy

### Task 4.1: Application Queue

```python
def queue_jd(application_id: int):
    """Add a scored JD to the application queue. Only queue if alignment is sufficient."""
    app = get_application(application_id)
    scores = json.loads(app.archetype_scores)
    primary = max(scores, key=scores.get)
    primary_score = scores[primary]

    # Get current alignment score for this archetype's resume variant
    variant = get_resume_variant(primary)
    alignment = variant.alignment_score

    # Minimum threshold: JD archetype score * resume alignment
    # Both need to be reasonable for the application to be worth sending
    combined_score = primary_score * alignment

    if combined_score >= 0.15:  # calibrate this threshold from data
        app.archetype_primary = primary
        app.market_intelligence_only = False
        # Enters the application queue
    else:
        app.market_intelligence_only = True
        # Stored for drift detection only, not applied to
```

- CLI command `apply queue` shows:
```
Application Queue:
  Builder:    12 roles (avg archetype score: 0.52)
  Fixer:       7 roles (avg archetype score: 0.48)
  Operator:    3 roles (avg archetype score: 0.41)
  Translator:  2 roles (avg archetype score: 0.39)
  Market Intel: 8 roles (below threshold, drift data only)
```

### Task 4.2: Batch Application Workflow

1. Select archetype batch via CLI: `apply batch builder`
2. System verifies: Seek profile is set to Builder archetype (prompt to update if not)
3. System lists all queued Builder applications with titles and companies
4. User confirms
5. For each application in batch:
   - Attach builder resume variant
   - Record: `resume_variant_sent = 'builder'`, `resume_commit_hash = <current>`, `profile_state_at_application = 'builder'`, `date_applied = now()`
   - Create/assign `application_batch_id`
6. After batch completes, log batch record with count and dates
7. Display: "Applied to 12 Builder roles. Wait 3-5 days before switching profile to next archetype."

### Task 4.3: Seek Profile Automation (Deferred)

**Implementation notes for when this is built:**
- Use Playwright (preferred over Selenium — async, faster, better anti-detection)
- Script must: login to Seek, navigate to profile editor, update headline/summary/skills sections
- Store four profile content templates in `profile_variants` table
- Add random delays (2-8 seconds) between actions
- Rotate user-agent strings
- Risk: Seek may detect automation. Start with manual profile switches. Only automate if batch volume exceeds 3-4 archetype switches per week.

---

## Epic 5: Drift Detection

### Task 5.1: JD Embedding Pipeline

- Triggered on every new JD insert (both applied and market-intelligence-only)
- Use same `sentence-transformers/all-MiniLM-L6-v2` model as archetype classifier
- Embed the full JD text
- Store embedding vector in `applications.embedding_vector`
- Tag with `archetype_primary` and `date_scraped`

### Task 5.2: Market Centroid Tracking

```python
def compute_centroids(window_days: int = 30):
    """Compute per-archetype centroids for rolling window."""
    today = date.today()
    window_start = today - timedelta(days=window_days)

    for archetype in ['builder', 'fixer', 'operator', 'translator']:
        embeddings = get_embeddings_for_archetype_in_window(
            archetype, window_start, today
        )

        if len(embeddings) < 5:
            continue  # not enough data for meaningful centroid

        centroid = np.mean(embeddings, axis=0)

        # Get previous window's centroid
        prev = get_most_recent_centroid(archetype)
        shift = 0.0
        if prev is not None:
            shift = 1 - cosine_similarity(centroid, prev.centroid_vector)

        store_centroid(
            archetype=archetype,
            window_start=window_start,
            window_end=today,
            centroid_vector=centroid,
            jd_count=len(embeddings),
            shift_from_previous=shift
        )
```

- Run weekly via scheduler on Remote Worker
- Minimum 5 JDs per archetype per window to compute centroid (below this, skip — insufficient data)

### Task 5.3: Market Shift Alert

```python
SHIFT_THRESHOLD = 0.05  # starting value, calibrate from data

def check_market_shift():
    for archetype in ['builder', 'fixer', 'operator', 'translator']:
        latest = get_most_recent_centroid(archetype)
        if latest is None or latest.shift_from_previous is None:
            continue

        if latest.shift_from_previous > SHIFT_THRESHOLD:
            # Compute what changed
            prev = get_previous_centroid(archetype)
            gained, lost = compute_term_drift(prev.centroid_vector, latest.centroid_vector)

            create_drift_alert(
                archetype=archetype,
                alert_type='market_shift',
                metric_value=latest.shift_from_previous,
                threshold_value=SHIFT_THRESHOLD,
                details=json.dumps({
                    'gained_terms': gained[:10],
                    'lost_terms': lost[:10],
                    'jd_count': latest.jd_count,
                    'window': f"{latest.window_start} to {latest.window_end}"
                })
            )

def compute_term_drift(old_centroid, new_centroid):
    """Find terms that moved closer to or farther from the centroid."""
    # Use a reference vocabulary of common JD terms
    REFERENCE_TERMS = [...]  # populated from corpus analysis
    term_embeddings = model.encode(REFERENCE_TERMS)

    old_sims = [cosine_similarity(t, old_centroid) for t in term_embeddings]
    new_sims = [cosine_similarity(t, new_centroid) for t in term_embeddings]

    deltas = [(term, new - old) for term, old, new in zip(REFERENCE_TERMS, old_sims, new_sims)]
    deltas.sort(key=lambda x: x[1], reverse=True)

    gained = [term for term, delta in deltas if delta > 0.02]
    lost = [term for term, delta in deltas if delta < -0.02]

    return gained, lost
```

### Task 5.4: Resume Staleness Metric

```python
STALENESS_THRESHOLD = 0.08  # starting value, calibrate from data

def check_resume_staleness():
    for archetype in ['builder', 'fixer', 'operator', 'translator']:
        variant = get_resume_variant(archetype)
        latest_centroid = get_most_recent_centroid(archetype)

        if variant is None or latest_centroid is None:
            continue

        distance = 1 - cosine_similarity(variant.embedding_vector, latest_centroid.centroid_vector)

        if distance > STALENESS_THRESHOLD:
            create_drift_alert(
                archetype=archetype,
                alert_type='resume_stale',
                metric_value=distance,
                threshold_value=STALENESS_THRESHOLD,
                details=json.dumps({
                    'current_alignment': variant.alignment_score,
                    'last_rewritten': str(variant.last_rewritten),
                    'commit_hash': variant.current_commit_hash
                })
            )
```

### Task 5.5: Rewrite Trigger Logic

```python
MIN_REWRITE_INTERVAL_DAYS = 21

def check_rewrite_triggers():
    for archetype in ['builder', 'fixer', 'operator', 'translator']:
        variant = get_resume_variant(archetype)

        # Condition (c): minimum interval since last rewrite
        if variant.last_rewritten and \
           (date.today() - variant.last_rewritten).days < MIN_REWRITE_INTERVAL_DAYS:
            continue

        # Condition (a): market shift alert exists for this archetype (recent, unacknowledged)
        market_alert = get_recent_unacknowledged_alert(archetype, 'market_shift')
        if market_alert is None:
            continue

        # Condition (b): resume staleness alert exists
        stale_alert = get_recent_unacknowledged_alert(archetype, 'resume_stale')
        if stale_alert is None:
            continue

        # All three conditions met — generate rewrite report
        report = generate_rewrite_report(archetype, market_alert, stale_alert)
        create_drift_alert(
            archetype=archetype,
            alert_type='rewrite_triggered',
            metric_value=stale_alert.metric_value,
            threshold_value=stale_alert.threshold_value,
            details=json.dumps(report)
        )
        # Acknowledge the component alerts
        acknowledge_alert(market_alert.id)
        acknowledge_alert(stale_alert.id)

def generate_rewrite_report(archetype, market_alert, stale_alert) -> dict:
    market_details = json.loads(market_alert.details)
    stale_details = json.loads(stale_alert.details)

    return {
        'archetype': archetype,
        'recommendation': 'rewrite',
        'market_shift': market_alert.metric_value,
        'resume_distance': stale_alert.metric_value,
        'terms_gaining': market_details.get('gained_terms', []),
        'terms_declining': market_details.get('lost_terms', []),
        'current_resume_version': stale_details.get('commit_hash'),
        'last_rewritten': stale_details.get('last_rewritten'),
        'suggested_focus': f"Market for {archetype} roles is shifting towards: "
                          f"{', '.join(market_details.get('gained_terms', [])[:5])}. "
                          f"Consider de-emphasising: "
                          f"{', '.join(market_details.get('lost_terms', [])[:5])}."
    }
```

- After manual rewrite: commit new resume, update `resume_variants` table, recompute alignment score, tag commit:
  ```bash
  git add builder.md builder.alignment.json
  git commit -m "rewrite: builder v3 — market shifted toward [terms], distance was 0.12"
  git tag builder-v3-2026-03-15
  ```

---

## Epic 6: Orchestration and Local Runtime

### Task 6.1: Database Setup

- Database engine: SQLite for simplicity. File lives on Remote Worker.
- Schema: as defined above
- Migration: use Alembic or simple versioned SQL scripts
- Backup: daily SQLite file backup to a separate directory

### Task 6.2: Pipeline Orchestration

**Remote Worker scheduler (APScheduler):**

```python
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

# Every 15 minutes: poll Gmail, parse emails, classify, match
scheduler.add_job(poll_and_process_gmail, 'interval', minutes=15)

# On JD insert (event-driven, triggered by Local Agent pushing new JDs):
# - score_jd(), extract_metadata(), compute_embedding()
# These run as post-insert hooks in the database layer

# Weekly (Sunday midnight):
scheduler.add_job(compute_centroids, 'cron', day_of_week='sun', hour=0)
scheduler.add_job(check_market_shift, 'cron', day_of_week='sun', hour=0, minute=5)
scheduler.add_job(check_resume_staleness, 'cron', day_of_week='sun', hour=0, minute=10)
scheduler.add_job(check_rewrite_triggers, 'cron', day_of_week='sun', hour=0, minute=15)

scheduler.start()
```

**Local Agent:**
- Runs when you invoke CLI commands
- Pushes scraped JDs to Remote Worker's database
- Pulls archetype scores and drift alerts from Remote Worker
- All Seek interactions (scrape, apply, profile update) execute locally

**Communication:** SSH tunnel to Remote Worker's database, or a lightweight REST API (Flask/FastAPI) on the Remote Worker that the Local Agent calls.

### Task 6.3: CLI Interface

```
Usage: apply <command>

Commands:
  queue               Show queued applications grouped by archetype
  batch <archetype>   Apply to all queued jobs for an archetype
  status              Show funnel metrics and conversion rates
  drift               Show current drift metrics and active alerts
  classify <file>     Score a single JD file and return archetype weights
  log-call            Open phone call intake form in browser
  sync                Force sync local queue to remote database
  versions            Show resume version performance comparison
  alerts              Show all unacknowledged drift alerts
```

### Task 6.4: IP / Detection

- Local Agent: residential IP only. No cloud IPs touch Seek.
- Remote Worker: any IP. Gmail API, embeddings, database — all IP-agnostic.
- SSH tunnel: Local Agent → Remote Worker. Authenticated, encrypted.
- If Seek profile automation is implemented (Task 4.3): random delays 2-8s, human-like mouse movements, rotating user-agent.
- No data leaves to third-party services. Embeddings computed locally on Remote Worker using open-source model.

---

## Dependencies

### Python Packages
```
google-auth
google-auth-oauthlib
google-api-python-client
sentence-transformers
numpy
scipy
scikit-learn
flask
apscheduler
tabulate
python-Levenshtein
nltk
alembic (if using migrations)
playwright (if automating Seek profile)
```

### Infrastructure
- Remote Worker: any VPS with 2GB+ RAM (sentence-transformers model needs ~500MB). Fly.io, Railway, or a $5/mo DigitalOcean droplet.
- SQLite database on Remote Worker filesystem
- Git repo: local on Will's machine, optionally mirrored to private GitHub for backup

### External APIs
- Gmail API (readonly scope)
- No other external APIs. All ML inference is local.
