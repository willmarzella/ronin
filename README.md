# Revoltx

Because writing "I am passionate about leveraging my synergistic skill set in a dynamic environment" for the 100th time is slowly killing your soul. Let the machines handle the boring parts.

## What it does

- Scrapes job postings so you don't have to keep refreshing job boards like a maniac
- Figures out if you're actually qualified (or close enough)
- Uses AI to decode what "competitive salary" and "rockstar developer" actually mean
- Keeps track of everything in Airtable because your spreadsheet is a mess
- Applies to jobs you're actually qualified for by handling form fields using Selenium and AI

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

4. Login to Google (yes, manually, we're not trying to get arrested):
   - Open your browser
   - Log into your Google account
   - Come back here and press Enter when prompted
   - We know it's not elegant, but it beats typing "Detail-oriented team player" 50 times

See `config/config.yaml` for full configuration options.

### Running the script (Choose Your Adventure)

Pick your poison - we've got three flavors of automation:

```bash
./scripts/scrape.sh    # Just stalk the job boards
./scripts/apply_jobs.sh # Mass distribute your hopes and dreams
./scripts/run.sh       # The full monty - scrape AND apply
```

Pro tip: Run `scrape.sh` first if you're paranoid (smart) and want to see what jobs it finds before letting it loose on the apply button. Or just YOLO with `run.sh` - we won't judge.

## Project Structure

```
.
├── app/
│   ├── scrapers/     # Job board stalking tools
│   ├── core/        # The brains of the operation
│   ├── services/    # The actually useful stuff
│   └── utils/       # Code we all copy from StackOverflow
├── config/          # Magic numbers live here
├── integrations/    # Plays nice with others
├── logs/            # When things go wrong
└── scripts/         # Automation for your automation
```

## Known Issues

- Some job boards really hate bots (especially if you apply too fast)
- OpenAI API might occasionally timeout or return invalid responses
- Chrome automation can be finicky (close ALL Chrome windows before running)
- AI might get confused by weird form fields (looking at you, custom dropdowns)
- Form elements sometimes change their IDs (thanks Seek)
- Manual Google login required (because we're not trying to get arrested)
- Airtable rate limits if you're too enthusiastic
- Sometimes thinks you're qualified for jobs that want "10 years Rust experience"

## Legal Disclaimer

This probably violates some Terms of Service somewhere. Use at your own risk. If you get caught, we've never met and this repo will self-destruct.

## License

MIT (but seriously, if you get banned from LinkedIn or Seek, that's on you)
