# Ronin - AI-Powered Job Application Automation

Ronin automatically searches job boards, scores every listing using AI, picks
the right resume for each role, writes a tailored cover letter, and submits
applications -- all while you do something better with your time.

Set it up once. Run one command. Wake up to a full pipeline of applications.

---

## How It Works

```
  Keywords           Seek.com.au           AI Analysis          Your Resumes
     |                   |                     |                     |
     v                   v                     v                     v
 +---------+      +------------+      +-----------------+    +--------------+
 | Config  | ---> |   Scrape   | ---> |  Score & Rank   | -> | Pick Resume  |
 | (YAML)  |      |  Listings  |      |  (0-100 score)  |    | + Cover Ltr  |
 +---------+      +------------+      +-----------------+    +--------------+
                                              |                     |
                                              v                     v
                                      +-----------------+    +--------------+
                                      |  Store in DB    | -> | Auto-Apply   |
                                      |  (SQLite)       |    | via Chrome   |
                                      +-----------------+    +--------------+
```

1. **Search** -- Ronin scrapes Seek.com.au and LinkedIn (guest job search)
   for jobs matching your keywords. LinkedIn also powers people-search
   outreach.
2. **Score** -- Each job description is sent to an AI model (Claude or GPT)
   which scores it 0-100 based on your skills, preferences, and red flags.
3. **Select** -- The AI picks the best resume profile for each job and
   classifies it (contract vs. long-term), with archetype-aware matching.
4. **Apply** -- Seek Quick Apply jobs go through the deterministic Chrome
   applier (`make apply`). Everything else — LinkedIn Easy Apply and
   external ATSes (Workday, PageUp, Greenhouse, ...) — goes through the
   agent applier (`make apply-external`), which fills forms, uploads the
   matching resume PDF, and navigates to submit.
5. **Learn** -- Ronin can parse Gmail outcomes (rejection, callback,
   interview, offer) and feed conversion signals back into future scoring.

---

## Quick Start

```
git clone https://github.com/automationchad/ronin.git
cd ronin
pip install .
ronin setup
ronin search
```

When you are ready to start applying:

```
ronin apply
```

The rest of this document walks through every step in detail.

---

## Prerequisites

Before you begin, you need four things:

### 1. Python 3.11 or newer

Ronin requires Python version 3.11 or above.

**macOS:** Open Terminal (press Cmd+Space, type "Terminal", press Enter) and run:

```
python3 --version
```

If it says `Python 3.11` or higher, you are good. If not, download the latest
version from https://www.python.org/downloads/macos/ -- click the big yellow
button, open the downloaded file, and follow the installer prompts.

**Windows:** Open Command Prompt (press the Windows key, type "cmd", press
Enter) and run:

```
python --version
```

If it says `Python 3.11` or higher, you are good. If not, download the latest
version from https://www.python.org/downloads/windows/ -- click the big yellow
button, run the installer, and **check the box that says "Add Python to PATH"**
before clicking Install.

### 2. Google Chrome

Ronin uses Chrome to submit applications. Download it from
https://www.google.com/chrome/ if you do not already have it.

### 3. A Seek.com.au account

You need an active Seek account with at least one resume uploaded. Ronin logs
in to Seek through Google SSO (Sign in with Google), so your Seek account must
be linked to a Google account.

To upload resumes on Seek: log in at https://www.seek.com.au, go to
Profile > Resumes, and upload your resume files there.

### 4. At least one AI API key

Ronin uses AI to score jobs, write cover letters, and answer screening
questions. You need an API key from at least one of these providers:

**Anthropic (Claude) -- recommended:**
- Go to https://console.anthropic.com/
- Create an account and add a payment method
- Go to API Keys and create a new key
- Copy the key (it starts with `sk-ant-`)

**OpenAI (GPT):**
- Go to https://platform.openai.com/
- Create an account and add a payment method
- Go to API Keys and create a new key
- Copy the key (it starts with `sk-`)

**What these cost:** Typical usage runs about $5-20 per month depending on how
many jobs you search and apply to. Each job analysis costs a fraction of a cent.
Cover letters cost slightly more. You only pay for what you use.

---

## Installation

### macOS

Open Terminal (press Cmd+Space, type "Terminal", press Enter) and run each
line one at a time:

```
# 1. Download the code
git clone https://github.com/automationchad/ronin.git
cd ronin

# 2. Create a virtual environment (keeps Ronin's packages separate)
python3 -m venv venv

# 3. Activate the virtual environment
source venv/bin/activate

# 4. Install Ronin
pip install .
```

You will know it worked when you can run `ronin --version` and see `ronin 2.0.0`.

Every time you open a new Terminal window to use Ronin, you need to activate
the virtual environment again:

```
cd ronin
source venv/bin/activate
```

### Windows

Open Command Prompt (press Windows key, type "cmd", press Enter) and run
each line one at a time:

```
# 1. Download the code
git clone https://github.com/automationchad/ronin.git
cd ronin

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
venv\Scripts\activate

# 4. Install Ronin
pip install .
```

You will know it worked when you can run `ronin --version` and see `ronin 2.0.0`.

Every time you open a new Command Prompt window to use Ronin, you need to
activate the virtual environment again:

```
cd ronin
venv\Scripts\activate
```

---

## Setup

Run the setup wizard:

```
ronin setup
```

This creates your configuration directory at `~/.ronin/` and walks you through
several screens. You can re-run a specific section at any time:

```
ronin setup --step personal
```

The wizard configures the following:

### Personal information

Your name, email, phone number, and location. Used in cover letters and
application forms.

### Work rights

Citizenship, visa status, driver's licence, willingness to relocate/travel,
police check status, and notice period. The AI uses these to answer screening
questions accurately on your behalf.

### Professional profile

Your job title, years of experience, salary expectations, and skills broken
down by category (languages, cloud platforms, frameworks, etc.). This is the
core data the AI uses to score jobs and match you to roles.

### Preferences

High-value signals (things that make a job more attractive to you) and red
flags (things that make a job less attractive). The AI boosts or penalises
scores based on these. You also set your preferred work types (full-time,
contract) and arrangements (remote, hybrid, onsite).

### Resume profiles

Ronin supports multiple resumes for different types of roles. Each resume
profile has:

- **name** -- a short identifier like "default" or "contract_senior"
- **file** -- a plain-text version of your resume, stored in `~/.ronin/resumes/`
- **seek_resume_id** -- the UUID of the matching resume on Seek.com.au
- **archetype** -- one of `expansion`, `consolidation`, `adaptation`, `aspiration`
- **use_when** -- rules for when this resume should be selected (e.g. use for
  contract roles, use for full-time roles)

When the AI analyses a job, it combines archetype hints, `use_when` rules,
and listing context to pick the best resume automatically. If AI returns an
invalid resume name, Ronin falls back to deterministic matching.

**How to find your Seek resume ID:** When you are on the Seek resume page, the
URL contains the resume UUID. The setup wizard will guide you through this.

### Cover letter settings

Tone (casual professional, formal, conversational), maximum word count,
spelling preference (Australian, American, British English), and anti-slop
rules (phrases the AI must never use, like "passionate about" or "leverage my
skills").

You can also provide an example cover letter and a highlights file in
`~/.ronin/assets/` for the AI to reference.

### AI provider configuration

Which AI provider and model to use for each task:
- Job analysis and scoring (default: Claude)
- Cover letter generation (default: Claude)
- Screening question answers (default: GPT-4o)

### API keys

Your Anthropic and/or OpenAI API keys are stored in `~/.ronin/.env`. The
wizard will prompt you to enter them.

---

## Usage

### Searching for Jobs

```
ronin search
```

This command:

1. Scrapes enabled job boards (Seek by default) for jobs matching your configured keywords
2. Fetches full details for each listing
3. Filters out jobs you have already seen (tracked in a local database)
4. Sends each new job description to the AI for scoring
5. Saves everything to a local SQLite/Postgres database
6. Optionally extracts recruiter contacts (email/LinkedIn/name) for outreach

You will see a progress bar as it works through each phase. At the end, it
reports how many new jobs were found, scored, and saved.

LinkedIn job scraping is controlled by `boards.linkedin.jobs_search_enabled`
and uses LinkedIn's guest search endpoints (no login). Tune
`boards.linkedin.filters` (easy apply, job type, experience level, workplace
type, distance, sort order) rather than relying only on keyword text. All
LinkedIn jobs are stored as `apply_type: external` and applied via
`ronin apply external`, which needs a LinkedIn login in the persisted Chrome
profile (sign in once when prompted; the session is reused after that).

**How often to run it:** Every few hours, or set up automatic scheduling (see
below). New listings appear on Seek throughout the day.

### Recruiter Outreach Queue

```
ronin apply contacts --refresh --limit 50
```

This command runs a two-stage contact strategy:

1. If the role appears to be from a staffing agency, prioritize known agency
   recruiters and direct email.
2. Otherwise, use JD-extracted email first, then LinkedIn + inferred email
   suggestions when no explicit email exists.

If `contact_intel.use_llm` is enabled, Ronin adds an LLM extraction pass for
recruiter details that regex misses.

To send outreach emails directly (explicit opt-in):

```
ronin apply contacts --refresh --send-email --yes
```

To auto-generate LinkedIn DM drafts for non-agency roles and open top search tabs:

```
ronin apply contacts --refresh --open-linkedin --open-linkedin-limit 5
```

To manually seed a known recruiter (so agency matches can reuse them):

```
ronin apply contacts --seed-recruiter-email jonny.church@pra.com.au --seed-recruiter-name "Jonny Church" --seed-recruiter-company "PRA"
```

Optional call CTA in message template:

- Set `contact_intel.outreach.cta_phone` in `~/.ronin/config.yaml`, or
- Pass `--cta-phone "0413414869"` at runtime

### Applying to Jobs

```
ronin apply
```

This command:

1. Pulls all pending jobs from the database (scored but not yet applied to),
   ordered by score (highest first)
2. Opens a Chrome browser window
3. Logs into Seek via Google SSO
4. For each job: navigates to the listing, selects the right resume, writes
   and pastes a cover letter, answers screening questions, and clicks submit

**First time:** Chrome will open and you will need to manually complete the
Google sign-in (enter your password, handle 2FA). After the first login, the
session is preserved so subsequent runs log in automatically.

**Batch limit:** By default, Ronin applies to up to 100 jobs per run. You can
change this in `config.yaml` under `application.batch_limit`.

**What "stale" means:** If a job has been taken down since you last searched,
Ronin marks it as STALE and moves on.

### Applying to External / LinkedIn Jobs

```
ronin apply external --report    # see what's captured, by company
ronin apply external             # dry-run: fill + traverse, never submit
ronin apply external --live      # actually submit (asks for confirmation)
```

Jobs without Seek Quick Apply — LinkedIn listings and link-outs to employer
ATSes (Workday, PageUp, Greenhouse, Lever, ...) — are stored as
`apply_type: external` when `scraping.capture_external` is on. The agent
applier drives them with an observe-decide-act loop: it detects the ATS,
fills each form page, uploads the archetype-matched resume PDF from
`agent_apply.resume_pdf_dir`, and walks continue/review steps to the final
submit.

Safety defaults: `agent_apply.dry_run: true` means it stops right before the
submit button and reports what it would have sent; captchas and login walls
stop the run rather than fight it. LinkedIn requires a signed-in session in
the persisted Chrome profile — the first run pauses and waits while you log
in, then reuses that session.

### Keeping Your Resume + Seek Profile Fresh (Automated)

One master fact base drives the tuned resume variants and your Seek profile.

**Capture wins as they happen:**

```
ronin log "cut Snowflake spend 30% at <client> via warehouse right-sizing"
```

(or the `rlog` shell alias). Notes land in `resume/yaml/data_engineer/source_log.md`.

**Two hand-owned poles** bracket the same career, both in
`resume/yaml/data_engineer/`:

- `source.yml` — the **truth pole**. Real companies, dates, and titles stated
  plainly. Each role may set an optional `de_title` (the data-engineering-framed
  title to present when the real title, e.g. "Solutions Engineer", undersells the
  data work).
- `c.yml` — the **recruiter pole**. The same truth at its most keyword-dense and
  achievement-forward. Edit it by hand; `ronin resume regen` refuses to write it.

**Weekly regeneration** (`ronin resume regen`, scheduled Monday) runs two AI
agents: an *ingest* agent folds your log notes into `source.yml`, then a *tuning*
agent rewrites `builder.yml`, `fixer.yml`, `operator.yml`, and `translator.yml`.
Each lands at the midpoint between the poles — it reads `c.yml` as its register
ceiling and differs from its siblings by which facts lead (greenfield /
migration / reliability / stakeholders). Guardrails make unattended regen safe:

- Companies, dates, and titles are copied verbatim — the AI only rewrites prose
  (headline, career summary, responsibilities, achievements).
- Every dollar/percentage/count in the output must trace to the source facts;
  invented numbers are rejected and that variant's old file is kept. The
  recruiter pole is a style exemplar, so its numbers are not a licence either.
- Unchanged source + pole + log ⇒ no AI call, no commit (idempotent). Editing
  `c.yml` moves the ceiling for all four archetypes and so triggers a rerun.
- One variant failing validation does not block the rest of the run.

Regenerated variants commit to the resume repo and push to the remote named in
`resume_variants.regen_push_remote` (leave empty to commit locally only).

**Weekly Seek refresh** (`ronin profile refresh`, scheduled Mon + Thu) publishes
`c.yml` to your Seek profile. A fresh *last-updated* timestamp is the strongest
"I'm on the market" signal to recruiters, so when nothing changed it re-saves
the summary with an invisible character toggle — the timestamp still bumps.

```
ronin resume regen            # regenerate all four archetypes now
ronin resume regen --variant operator   # just one (repeatable; poles refused)
ronin profile refresh --dry-run   # preview the Seek update plan
ronin profile refresh         # publish / recency-touch now
```

Schedule (macOS launchd): `com.ronin.resume` (Mon 06:30) and `com.ronin.seek`
(Mon + Thu 07:30).

### Checking Status

```
ronin status
```

Shows a dashboard of your current pipeline: how many jobs have been discovered,
how many are pending application, how many have been applied to, and error
counts.

### Closed-Loop Feedback (Gmail Outcomes)

```
ronin feedback sync
ronin feedback report
ronin feedback review
```

`feedback sync` scans Gmail for outcome signals and records events such as:

- `REJECTION`
- `CALLBACK`
- `INTERVIEW`
- `OFFER`

Ronin matches those outcomes against your submitted applications and stores the
resume profile + role context. `feedback report` then shows which resume
archetypes, keyword patterns, and role-title families are converting.

If an email can't be confidently matched to an application, it is marked for
manual review. Use `feedback review` to confirm matches and apply the outcome to
the correct application record.

To enable this:

- Create OAuth Desktop credentials for the Gmail API and download `credentials.json`
- Place it in the project root, or set `tracking.gmail.credentials_path` in `~/.ronin/config.yaml`
- Run `ronin feedback sync` once interactively to complete OAuth; a refresh token is stored at
  `~/.ronin/gmail_token.json` (or `tracking.gmail.token_path`)

Headless worker note:

- If you're running the worker on a server without a browser, set `tracking.gmail.auth_mode: console`
  (or `RONIN_GMAIL_AUTH_MODE=console`) and run `ronin feedback sync` once in a terminal to complete
  the one-time auth.

### Automated Search (Set and Forget)

Instead of manually running `search` every few hours, you can install a
scheduled task:

```
ronin schedule install --interval 2
```

This tells your operating system to run `ronin search` every 2 hours in the
background.

**macOS:** Creates a launchd job that runs automatically, even after restarts.
Logs go to `~/.ronin/logs/launchd_search.log`.

**Windows:** Creates a Windows Task Scheduler entry. Logs go to the console
output of the scheduled task.

**Linux:** Adds a crontab entry. Logs go to `~/.ronin/logs/cron_search.log`.

To check if the schedule is active:

```
ronin schedule status
```

To remove the schedule:

```
ronin schedule uninstall
```

### Split Local/Remote (Postgres)

If you want a split setup (local machine does Seek; a VPS runs the worker loop),
point both machines at the same Postgres database:

1) Create a Postgres database and user (managed Postgres or on your VPS)
2) On both machines:
   - Set `database.backend: postgres` in `~/.ronin/config.yaml` (or set `RONIN_DB_BACKEND=postgres`)
   - Set `RONIN_DATABASE_DSN=postgresql://...` in `~/.ronin/.env`
3) On the VPS: run `ronin worker start`
4) On your local machine: run `ronin search` and `ronin apply batch <archetype>`

Seek profile batching note:

- By default, `ronin apply batch <archetype>` assumes you manually switched your Seek profile copy to match the archetype.
- To automate the profile switch, configure `seek_profile` in `~/.ronin/config.yaml`, then run:
  - `ronin profile set builder` (one-off), or
  - `ronin profile sync` (detect dominant archetype drift and switch automatically), or
  - `ronin apply batch builder --auto-profile`
  - If Seek UI changes, use `ronin profile debug` to open Playwright Inspector and capture selectors.
- To auto-run drift sync in autopilot, enable `seek_profile.drift.enabled: true`; then `ronin run` will check tracked profile state and switch when dominant archetype changes.

Offline buffer:

- If Postgres is temporarily unreachable, the local agent falls back to a local
  SQLite spool DB (default: `~/.ronin/data/spool.db`, configurable via
  `database.spool_path`).
- When Postgres is reachable again, Ronin will best-effort flush the spool on
  the next `ronin search` / `ronin apply` / `ronin run`, and you can also force a
  flush with `ronin apply sync`.

Security note: don't expose Postgres publicly. Prefer a private network (e.g.
Tailscale) or strict firewall rules.

### Backups

Create a point-in-time backup (SQLite file copy or Postgres `pg_dump`):

```
ronin db backup
```

Restore (high level):

- SQLite: replace `~/.ronin/data/ronin.db` with a `ronin-sqlite-*.db` backup
- Postgres: restore into an empty database with `psql < ronin-postgres-*.sql`

---

## Configuration

Ronin uses two YAML files and one `.env` file, all stored in `~/.ronin/`.

### Profile (profile.yaml)

Your personal and professional information. Controls how the AI writes cover
letters, scores jobs, and answers screening questions. Key sections:

| Section | What it controls |
|---|---|
| `personal` | Name, email, phone, location |
| `work_rights` | Citizenship, visa, licence, clearances |
| `professional` | Title, experience, salary, skills, preferences |
| `resumes` | Resume profiles and selection rules |
| `cover_letter` | Tone, length, spelling, anti-slop rules |
| `ai` | Provider and model for each AI task |

See `profile.example.yaml` in the repo root for a fully commented example.

### Config (config.yaml)

Runtime settings that control how Ronin operates (not who you are):

| Section | What it controls |
|---|---|
| `search` | Keywords, location, date range, salary filter |
| `application` | Salary for forms, batch limit |
| `database` | SQLite vs Postgres backend |
| `scraping` | Rate limiting, timeouts, quick-apply filter |
| `analysis` | Minimum score threshold |
| `proxy` | HTTP/HTTPS proxy (optional) |
| `notifications` | Slack webhook for alerts (optional) |
| `boards` | Which job boards are enabled |
| `browser` | Chrome mode and path override |
| `schedule` | Scheduling interval |
| `tracking` | Gmail outcome tracking and sync limits |
| `timeouts` | HTTP, page load, element wait timeouts |
| `retry` | Max attempts, backoff, jitter |

See `config.yaml` in the repo root for a fully commented example.

### Environment Variables (.env)

API keys and credentials. Never committed to version control.

```
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
OPENAI_API_KEY=sk-your-key-here

# Optional: use a remote Postgres DB (for split local/remote worker)
# RONIN_DB_BACKEND=postgres
# RONIN_DATABASE_DSN=postgresql://user:password@host:5432/ronin
```

Seek login is handled via an interactive Chrome session; Ronin does not store your
Seek/Google credentials in `.env`.

See `.env.example` in the repo root for the full list.

### File Locations

Everything lives under `~/.ronin/` (your home directory):

```
~/.ronin/
  config.yaml          # Runtime configuration
  profile.yaml         # Your personal profile
  .env                 # API keys and credentials
  resumes/             # Plain-text resume files
    default.txt
    contract.txt
  assets/              # Cover letter examples, highlights
    cover_letter_example.txt
    highlights.txt
  data/
    ronin.db           # SQLite database (all jobs, scores, statuses)
  logs/                # Log files
    search.log
    apply.log
    ronin.log
```

---

## Troubleshooting

### "No config.yaml found"

You have not run setup yet. Run:

```
ronin setup
```

### "ANTHROPIC_API_KEY not set" or "OPENAI_API_KEY not set"

Your `.env` file is missing or does not contain the required key. Check that
`~/.ronin/.env` exists and has your API key. You can re-run setup to fix this:

```
ronin setup --step api
```

Or edit `~/.ronin/.env` directly in any text editor.

### Chrome will not open

- Make sure Google Chrome is installed and up to date.
- If Chrome is installed in a non-standard location, set `browser.chrome_path`
  in `config.yaml` to the full path of the Chrome executable.
- Try setting `browser.mode` to `"testing"` in `config.yaml` to use Chrome for
  Testing instead of your system Chrome.

### Schedule not running

Run:

```
ronin schedule status
```

If it says "Not installed", install it again:

```
ronin schedule install --interval 2
```

On macOS, check the log at `~/.ronin/logs/launchd_search.log` for errors.

### Jobs not being found

- Check your keywords in `config.yaml`. Ronin uses Seek's search syntax.
  Keywords should be quoted: `'"Software engineer"-or-"software engineers"'`
- Increase `search.date_range` to look further back (default is 2 days).
- Set `search.location` to a broader area (e.g. `"All-Australia"`).
- Set `scraping.quick_apply_only` to `false` if you want to include jobs
  without Quick Apply (note: Ronin can only auto-apply to Quick Apply jobs).

### "Profile not found"

Your profile has not been created. Run:

```
ronin setup
```

### Applications failing

- Check `~/.ronin/logs/apply.log` for detailed error messages.
- Make sure your Seek resume IDs are correctly configured in `profile.yaml`.
- Expired or removed job listings will be marked STALE automatically.
- If you see `APP_ERROR` statuses, those jobs will be retried on the next run.

---

## Architecture (For Contributors)

### Codebase Structure

```
ronin/
  cli/
    main.py             # CLI entry point (argparse dispatcher)
    search.py           # Search command implementation
    apply.py            # Apply command implementation
    feedback.py         # Gmail sync + outcome analytics commands
    setup.py            # Interactive setup wizard
    status.py           # Status dashboard
  scraper/
    base.py             # BaseScraper abstract class
    seek.py             # Seek.com.au scraper implementation
  analyzer/
    analyzer.py         # AI job analysis service
  applier/
    base.py             # BaseApplier abstract class
    applier.py          # Seek application automation (Selenium)
    browser.py          # Chrome WebDriver management
    cover_letter.py     # Cover letter generation
    forms.py            # Screening question handler
    form_applier.py     # Form field automation
    validation.py       # Application validation
    ai_handler.py       # AI integration for forms
    html_formatter.py   # HTML formatting for cover letters
  prompts/
    generator.py        # Dynamic prompt generation from profile
    job_analysis.py     # Static job analysis prompt (fallback)
    cover_letter.py     # Cover letter prompt template
    form_fields.py      # Screening question prompt template
  feedback/
    gmail_tracker.py    # Parses Gmail and records outcomes
    analysis.py         # Conversion metrics for feedback loop
  config.py             # Configuration loading (~/.ronin/config.yaml)
  profile.py            # Profile loading and validation (Pydantic)
  db.py                 # SQLite database manager
  ai.py                 # AI service abstraction (Anthropic + OpenAI)
  scheduler.py          # Cross-platform scheduling (launchd/schtasks/cron)
```

### Adding a New Job Board

To support a new job board (e.g. LinkedIn, Indeed), implement two classes:

1. **Scraper** -- subclass `BaseScraper` (in `ronin/scraper/base.py`):
   - Implement `get_job_previews()` to return a list of job preview dicts
   - Implement `get_job_details(job_id)` to return full job details

2. **Applier** -- subclass `BaseApplier` (in `ronin/applier/base.py`):
   - Implement `apply_to_job()` to handle the application flow
   - Implement `login()` to authenticate with the job board
   - Implement `cleanup()` to close browser resources
   - Set `board_name` property to the board identifier

Register the new board in `ronin/applier/base.py:get_applier()` and add a
toggle in `config.yaml` under the `boards` section.

### How Prompts Work

Ronin generates AI prompts dynamically from your `profile.yaml`. The
`ronin/prompts/generator.py` module reads your skills, preferences, resume
profiles, and cover letter settings, then assembles them into system prompts
for each AI task:

- **Job analysis:** Scores 0-100, classifies as CASH_FLOW or LONG_TERM,
  identifies tech stack, selects resume profile, writes a recommendation.
- **Cover letters:** Uses your tone, anti-slop rules, engagement framing,
  example letter, and resume text to generate a human-sounding cover letter.
- **Screening questions:** Uses your work rights, skills, and salary
  expectations to answer form fields (radio buttons, checkboxes, text areas).

### Data Flow

```
Scraper  -->  Analyzer  -->  SQLiteManager  -->  Applier
(HTML)        (AI API)       (ronin.db)          (Selenium)
```

Jobs move through statuses: `DISCOVERED` -> `APPLIED` (or `STALE` / `APP_ERROR`).

---

## License

MIT
