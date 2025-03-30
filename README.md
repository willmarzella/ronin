# Ronin: Automation Workflows with Prefect

A comprehensive collection of automation workflows for job searching, applications, outreach, and content generation, built with Prefect.

## Features

- **Job Search**: Automated scraping, analysis, and storage of job postings
- **Job Application**: Preparation and submission of customized job applications
- **Job Outreach**: Follow-up and networking communications with potential employers
- **Blog Generator**: End-to-end blog post content creation and publication

## Project Structure

```
ronin/
├── flows/                  # Prefect flows
│   ├── job_search_flow.py
│   ├── job_application_flow.py
│   ├── job_outreach_flow.py
│   └── blog_generator_flow.py
├── tasks/                  # Task modules for each workflow
│   ├── job_scraping/
│   ├── job_application/
│   ├── job_outreach/
│   └── blog_posts/
├── blocks/                 # Prefect blocks for external services
│   └── prefect_blocks.py
├── deployments/            # Deployment scripts
│   └── deploy.py
├── utils/                  # Utility functions
├── configs/                # Configuration files
├── tests/                  # Test suite
├── assets/                 # Static assets
├── logs/                   # Log files
├── models/                 # ML models (if applicable)
├── scripts/                # Utility scripts
├── notebooks/              # Jupyter notebooks
├── prefect.yaml            # Prefect project configuration
├── Dockerfile              # Docker configuration
├── docker-compose.yml      # Docker Compose configuration
├── requirements.txt        # Python dependencies
└── pyproject.toml          # Project configuration
```

## Getting Started

### Prerequisites

- Python 3.10+
- Docker (optional, for containerized execution)
- Prefect account (for deployments)

### Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/ronin.git
cd ronin
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file with necessary API keys and configuration:

```
OPENAI_API_KEY=your_openai_api_key
AIRTABLE_API_KEY=your_airtable_api_key
SLACK_WEBHOOK_URL=your_slack_webhook_url
# Add other required environment variables
```

### Local Development

1. Start a local Prefect server:

```bash
prefect server start
```

2. In a new terminal, register Prefect blocks:

```bash
python blocks/prefect_blocks.py
```

3. Run flows locally:

```bash
python flows/job_search_flow.py
```

### Deployment

#### Using Docker Compose

1. Start the Prefect server and worker:

```bash
docker-compose up -d
```

2. Deploy all flows:

```bash
docker-compose exec prefect-worker python deployments/deploy.py
```

#### Using Prefect Cloud

1. Log in to your Prefect Cloud account:

```bash
prefect cloud login
```

2. Deploy all flows:

```bash
python deployments/deploy.py --apply
```

3. Create a work pool if needed:

```bash
prefect work-pool create default-agent-pool --type process
```

4. Start a worker:

```bash
prefect worker start --pool default-agent-pool
```

## Configuration

The project configuration is stored in `configs/config.yaml`. This file contains settings for:

- Job search platforms and criteria
- Application preferences
- Outreach templates and strategies
- Blog content settings
- Service connections

## Usage

### Job Search Flow

The job search flow scrapes job postings from configured platforms, analyzes them for relevance, and stores them in Airtable.

```bash
python flows/job_search_flow.py
```

### Job Application Flow

The job application flow prepares customized resumes and cover letters for selected jobs and submits applications.

```bash
python flows/job_application_flow.py --application-limit 5
```

### Job Outreach Flow

The job outreach flow manages follow-up communications, networking, and relationship building with potential employers.

```bash
python flows/job_outreach_flow.py --outreach-limit 10
```

### Blog Generator Flow

The blog generator flow creates blog posts based on trending topics and content strategy.

```bash
python flows/blog_generator_flow.py --num-topics 3
```

## Monitoring and Observability

### Prefect UI

Access the Prefect UI at http://localhost:4200 to monitor flow runs, view logs, and manage deployments.

### Notifications

The system is configured to send notifications through:

- Slack
- Email
- Custom notification channels

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit changes: `git commit -am 'Add new feature'`
4. Push to the branch: `git push origin feature/my-feature`
5. Submit a pull request

## License

This project is licensed under the terms of the license provided in the LICENSE file.

## Acknowledgements

- [Prefect](https://prefect.io) - The workflow orchestration framework
- [OpenAI](https://openai.com) - For AI-powered content generation
- [Airtable](https://airtable.com) - Data storage and organization
