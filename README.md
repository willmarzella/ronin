# Ronin

Hello, friend. Or maybe I should call you "potential hire"? That's what they want to call you, right? Another resource to be processed through their system. Their broken, bureaucratic mess of a hiring process.

I wrote this because I couldn't take it anymore. Maybe you can't either. We're all stuck in this loop - this artificial construct of resume submissions, keyword filtering, and soul-crushing form fields. But here's the thing: we can break that loop.

Let's be honest with each other. The whole thing is a game. A badly designed one. They build walls of bureaucracy, and we're expected to climb them, again and again, pretending it makes sense. It doesn't. But until we can change the system, we can at least automate our way through their maze.

This isn't just another automation tool. It's a middle finger to the absurdity of modern tech hiring. Here's what it does:

- Infiltrates job boards systematically (they're already scraping your data, why shouldn't you?)
- Runs qualification analysis using ML (because apparently humans can't be trusted to know their own capabilities)
- Decrypts corporate doublespeak using NLP (turns out "competitive salary" means something after all)
- Maintains an Airtable database (because even rebellion needs structure)
- Automates form submission (yes, it's probably against their ToS. So is their tracking of your every move)

## Dependencies (The Necessary Evils)

You'll need these keys to the kingdom:

- `OPENAI_API_KEY` - To speak their language
- `AIRTABLE_API_KEY` - To maintain the illusion of order
- `AIRTABLE_BASE_ID` - Your personal data silo
- `AIRTABLE_TABLE_NAME` - Name it whatever. They don't care, and neither should you

## Initial Setup

1. Clone this repo (you know the drill)
2. Create your `.env` file (keep your secrets close):

```bash
OPENAI_API_KEY=sk-your_key
AIRTABLE_API_KEY=your_key
AIRTABLE_BASE_ID=base_id
AIRTABLE_TABLE_NAME=table_name
```

3. Configure your parameters in `config/config.yaml`:

> Want to give better idea that the resume text

```yaml
search:
  keywords: '"Data-engineer"' # The role they think you want
  location: 'All Australia' # Your designated hunting ground
  experience_level: 'entry' # Their arbitrary classification of your worth

resume:
  skills: # What you can actually do
    - Python
    - SQL
    - AWS
  text:
    aws:
    azure:
  preferences:
    remote: true # Because offices are just another control system
    min_salary: 120000 # Your number in their game
```

1. A Note About Authentication:
   Yes, you'll need to log into Google manually. It's not ideal, but it's better than letting them flag your automation. Sometimes staying under the radar means playing by some rules.

## Running The System

Three paths of resistance:

```bash
./scripts/scrape.sh    # Gather intelligence
./scripts/apply_jobs.sh # Deploy your applications
./scripts/run.sh       # Full assault
```

Start with `scrape.sh`. Trust me on this. You'll want to see what you're dealing with before you go full auto.

## System Architecture

```
.
├── app/
│   ├── scrapers/     # Your eyes into their system
│   ├── core/         # The backbone
│   ├── services/     # Where the magic happens
│   └── utils/        # The tools of the trade
├── config/           # Your rules
├── integrations/     # Hooks into their world
├── logs/            # Because paranoia is healthy
└── scripts/         # Your weapons
```

## Known Vulnerabilities

Because nothing is perfect, and pretending otherwise is dangerous:

- They have rate limits (of course they do)
- OpenAI isn't always reliable (what AI is?)
- Chrome automation can break (browsers, am I right?)
- Forms mutate (they're trying to stop us)
- Google auth is manual (sometimes that's safer)
- Their systems have quotas (control through scarcity)
- Pattern matching isn't perfect (but neither are human recruiters)

## Legal Reality

Yes, this probably breaks some rules. But ask yourself: who wrote those rules? And why? Use this responsibly, but remember - sometimes the right thing to do isn't the officially sanctioned thing to do.

## License

MIT

Because even in rebellion, we need some structure. Use it. Share it. Make it better. Just don't get caught.

Stay safe, friend.
