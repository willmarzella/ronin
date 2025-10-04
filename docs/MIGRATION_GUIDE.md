# 🔄 Migration Guide: Old Structure → New Structure

## 📋 **Import Changes**

### **Before (Old Structure)**

```python
# Core imports
from core.config import load_config
from core.logging import setup_logging

# Service imports
from services.ai_service import AIService
from services.airtable_service import AirtableManager

# Task imports
from tasks.job_application.question_answer import QuestionAnswerHandler
from tasks.job_scraping.scrapers import JobScraper
from tasks.blog_posts.generation import BlogGenerator

# Model imports
from models.job import Job
from models.blog_post import BlogPost

# Utils imports
from utils.formatters import format_job_data
```

### **After (New Structure)**

```python
# Core imports
from ronin.core.config import load_config
from ronin.core.logging import setup_logging

# Service imports
from ronin.services.ai_service import AIService
from ronin.services.airtable_service import AirtableManager

# App imports
from ronin.apps.job_automation.application.question_answer import QuestionAnswerHandler
from ronin.apps.job_automation.search.scrapers import JobScraper
from ronin.apps.blog_generation.generation import BlogGenerator

# Model imports
from ronin.models.job import Job
from ronin.models.blog_post import BlogPost

# Utils imports
from ronin.utils.formatters import format_job_data
```

## 🔄 **File Movement Map**

| **Old Location**                 | **New Location**                             |
| -------------------------------- | -------------------------------------------- |
| `core/`                          | `src/ronin/core/`                            |
| `services/`                      | `src/ronin/services/`                        |
| `models/`                        | `src/ronin/models/`                          |
| `utils/`                         | `src/ronin/utils/`                           |
| `tasks/job_scraping/`            | `src/ronin/apps/job_automation/search/`      |
| `tasks/job_application/`         | `src/ronin/apps/job_automation/application/` |
| `tasks/job_outreach/`            | `src/ronin/apps/job_automation/outreach/`    |
| `tasks/blog_posts/`              | `src/ronin/apps/blog_generation/`            |
| `services/actualized_scraper.py` | `src/ronin/apps/book_scraping/`              |
| `models/book.py`                 | `src/ronin/apps/book_scraping/`              |

## 🛠️ **Migration Steps**

### 1. **Update DAG Files**

```python
# In dags/job_application_dag.py
# OLD:
from tasks.job_application.appliers import SeekApplier

# NEW:
from ronin.apps.job_automation.application.appliers import SeekApplier
```

### 2. **Update Script Files**

```python
# In scripts/run_job_application.sh
# Update Python path and imports
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
```

### 3. **Update Test Files**

```python
# In test_*.py files
# OLD:
from services.actualized_scraper import ActualizedScraper

# NEW:
from ronin.apps.book_scraping.actualized_scraper import ActualizedScraper
```

## 🎯 **Benefits After Migration**

1. **🔍 Clearer Purpose**: Each directory has a clear, single responsibility
2. **📦 Better Organization**: Related functionality is grouped together
3. **🚀 Easier Development**: Find and modify features quickly
4. **🧪 Better Testing**: Test individual modules independently
5. **📈 Scalability**: Add new apps without cluttering the root

## 🐒 **Monkey Translation**

**Before**: "Where's the banana? It could be anywhere!"
**After**: "Bananas are in the fruit bowl, tools are in the toolbox, and toys are in the toy box!"

## ⚠️ **Important Notes**

1. **Update PYTHONPATH**: Add `src/` to your Python path
2. **Update Imports**: All import statements need to be updated
3. **Test Everything**: Run tests after migration to ensure nothing broke
4. **Update Documentation**: Update any docs that reference old paths

## 🚀 **Quick Migration Script**

```bash
#!/bin/bash
# Quick migration helper

# Add src to Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

# Update all Python files
find . -name "*.py" -not -path "./src/*" -not -path "./venv/*" | while read file; do
    # Update imports (this is a simplified example)
    sed -i 's/from core\./from ronin.core./g' "$file"
    sed -i 's/from services\./from ronin.services./g' "$file"
    sed -i 's/from tasks\./from ronin.apps./g' "$file"
    sed -i 's/from models\./from ronin.models./g' "$file"
    sed -i 's/from utils\./from ronin.utils./g' "$file"
done

echo "Migration complete! 🐒"
```
