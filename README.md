# 🐒 Ronin - AI-Powered Job Automation Platform

> **Monkey-Friendly Structure** - Even a monkey can understand this codebase!

## 📁 Repository Structure

```
ronin/
├── src/ronin/                    # 🎯 Main source code
│   ├── core/                     # ⚙️ Core functionality
│   │   ├── config.py            # Configuration management
│   │   ├── logging.py           # Logging setup
│   │   └── config.yaml          # Configuration file
│   │
│   ├── apps/                     # 🚀 Application modules
│   │   ├── job_automation/      # 💼 Job automation suite
│   │   │   ├── search/          # 🔍 Job search & scraping
│   │   │   ├── application/     # 📝 Job application automation
│   │   │   └── outreach/        # 🤝 Networking & outreach
│   │   │
│   │   ├── blog_generation/     # ✍️ Blog content automation
│   │   └── book_scraping/       # 📚 Book content extraction
│   │
│   ├── services/                 # 🔌 External service integrations
│   │   ├── ai_service.py        # 🤖 AI/LLM services
│   │   ├── airtable_service.py  # 📊 Airtable integration
│   │   ├── github_service.py    # 🐙 GitHub integration
│   │   └── ...                  # Other services
│   │
│   ├── models/                   # 📋 Data models & schemas
│   │   ├── job.py               # Job data model
│   │   ├── blog_post.py         # Blog post model
│   │   └── ...
│   │
│   └── utils/                    # 🛠️ Utility functions
│       ├── formatters.py         # Data formatting
│       └── validators.py         # Data validation
│
├── dags/                         # 🌪️ Airflow DAGs
├── scripts/                      # 📜 Automation scripts
├── assets/                       # 📁 Static assets (CVs, templates)
├── data/                         # 💾 Data storage
├── logs/                         # 📝 Log files
└── tests/                        # 🧪 Test files
```

## 🎯 **What Each Section Does**

### 🏗️ **Core** (`src/ronin/core/`)

- **Purpose**: Foundation of the entire system
- **Contains**: Configuration, logging, base functionality
- **Monkey Translation**: "The brain and nervous system"

### 🚀 **Apps** (`src/ronin/apps/`)

- **Purpose**: Main business logic and features
- **Contains**: Job automation, blog generation, book scraping
- **Monkey Translation**: "The different things the monkey can do"

#### 💼 **Job Automation** (`apps/job_automation/`)

- **Search**: Find jobs on various platforms
- **Application**: Automatically apply to jobs
- **Outreach**: Network and reach out to people

#### ✍️ **Blog Generation** (`apps/blog_generation/`)

- **Purpose**: Create blog content automatically
- **Monkey Translation**: "The monkey writes articles"

#### 📚 **Book Scraping** (`apps/book_scraping/`)

- **Purpose**: Extract content from books
- **Monkey Translation**: "The monkey reads books and takes notes"

### 🔌 **Services** (`src/ronin/services/`)

- **Purpose**: Connect to external APIs and services
- **Contains**: AI services, databases, social platforms
- **Monkey Translation**: "The monkey's tools and connections"

### 📋 **Models** (`src/ronin/models/`)

- **Purpose**: Define data structures
- **Contains**: Job, blog post, book models
- **Monkey Translation**: "The monkey's filing system"

### 🛠️ **Utils** (`src/ronin/utils/`)

- **Purpose**: Helper functions used everywhere
- **Contains**: Formatters, validators, common functions
- **Monkey Translation**: "The monkey's toolbox"

## 🚀 **How to Use**

### 1. **Job Automation**

```python
from ronin.apps.job_automation.search import JobSearcher
from ronin.apps.job_automation.application import JobApplier
from ronin.apps.job_automation.outreach import Networker

# Search for jobs
searcher = JobSearcher()
jobs = searcher.find_jobs("Python Developer")

# Apply to jobs
applier = JobApplier()
applier.apply_to_jobs(jobs)

# Network with people
networker = Networker()
networker.connect_with_recruiters()
```

### 2. **Blog Generation**

```python
from ronin.apps.blog_generation import BlogGenerator

generator = BlogGenerator()
post = generator.create_post("AI in Job Search")
generator.publish_post(post)
```

### 3. **Book Scraping**

```python
from ronin.apps.book_scraping import BookScraper

scraper = BookScraper()
content = scraper.extract_from_url("https://example.com/book")
```

## 🎨 **Design Principles**

1. **🐒 Monkey-Friendly**: Clear, obvious structure
2. **🔧 Single Responsibility**: Each module does one thing well
3. **📦 Modular**: Easy to add/remove features
4. **🔗 Loose Coupling**: Modules don't depend heavily on each other
5. **📖 Self-Documenting**: Code structure tells the story

## 🛠️ **Development**

```bash
# Install dependencies
pip install -r requirements.txt

# Run formatting
black src/
isort src/

# Run tests
pytest tests/

# Run specific app
python -m ronin.apps.job_automation.search
```

## 📈 **Benefits of This Structure**

- ✅ **Easy to Navigate**: Find what you need quickly
- ✅ **Easy to Extend**: Add new apps without breaking existing code
- ✅ **Easy to Test**: Each module can be tested independently
- ✅ **Easy to Deploy**: Deploy specific apps separately
- ✅ **Easy to Understand**: Even new developers (or monkeys) can contribute

---

**Remember**: If a monkey can understand it, so can you! 🐒✨
