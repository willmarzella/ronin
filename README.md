# Revoltx

Because writing "I am passionate about leveraging my synergistic skill set in a dynamic environment" for the 100th time is slowly killing your soul. Let the machines handle the boring parts.

## What it does

- Scrapes job postings so you don't have to keep refreshing job boards like a maniac
- Figures out if you're actually qualified (or close enough)
- Uses AI to decode what "competitive salary" and "rockstar developer" actually mean
- Keeps track of everything in Airtable because your spreadsheet is a mess

## Tech Stack

```python
stack = {
    "core": "Python",  # Because life's too short for Java
    "scraping": "BeautifulSoup4",  # Parsing HTML like it's 2023
    "ai": "OpenAI API",  # The expensive part
    "tracking": "Airtable",  # Excel but fancy
    "scheduling": "Schedule",  # Cron jobs but less painful
    "logging": "Loguru",  # Because print() is for amateurs
}
```

## Prerequisites

You'll need these API keys (yes, some cost money, welcome to automation):

- `OPENAI_API_KEY` - For the AI magic
- `AIRTABLE_API_KEY` - For pretending to be organized
- `AIRTABLE_BASE_ID` - That long string you'll definitely copy-paste
- `AIRTABLE_TABLE_NAME` - Name it whatever, just be consistent

## Setup

1. Clone this bad boy
2. Make a `.env` file and fill it with your secrets:

```bash
OPENAI_API_KEY=sk-your_wallet_draining_key
AIRTABLE_API_KEY=your_other_key
AIRTABLE_BASE_ID=that_long_string
AIRTABLE_TABLE_NAME=job_hunt_or_whatever
```

3. Configure your job search preferences in `config/config.yaml`:

```yaml
# Quick start: Edit these sections first
search:
  keywords: '"Data-engineer"' # Your target role
  location: 'All Australia' # Where you want to work
  experience_level: 'entry' # entry, mid, senior

resume:
  skills: # Your actual skills
    - Python
    - SQL
    - AWS
  preferences:
    remote: true # WFH or office?
    min_salary: 120000 # Know your worth
```

See `config/config.yaml` for full configuration options.

### Option 1: Docker (The Easy Way)

```bash
# Let Docker handle the mess
./scripts/run.sh
```

### Option 2: Local Setup (The Masochist's Way)

```bash
# The classic virtual environment dance
python -m venv venv
source venv/bin/activate  # Windows users: you know what to do

# Get the goods
pip install -r requirements.txt

# Launch this beast
python main.py
```

## Project Structure

```
.
├── app/
│   ├── scrapers/     # Job board stalking tools
│   ├── services/     # The actually useful stuff
│   └── utils/        # Code we all copy from StackOverflow
├── config/           # Magic numbers live here
├── integrations/     # Plays nice with others
├── logs/            # When things go wrong
└── scripts/         # Automation for your automation
```

## Known Issues

- Some job boards really hate bots (rude)
- API rate limits because we're too cheap for enterprise
- Sometimes thinks "10 years Rust experience" is reasonable
- May occasionally apply to jobs in Antarctica

## Todo

- [ ] Add more job boards (once they unban us)
- [ ] Make the matching smarter than a coin flip
- [ ] Actually read your resume
- [ ] Track which automated rejections hurt the most

## Legal Disclaimer

This probably violates some Terms of Service somewhere. Use at your own risk. If you get caught, we've never met and this repo will self-destruct.

## License

MIT (but seriously, if you get banned from LinkedIn or Seek, that's on you)
