from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict


@dataclass
class BlogPost:
    title: str
    content: str
    category: str  # shitposting, sermonposting, or nerdposting
    themes: List[Dict[str, str]]  # List of theme objects with name and examples
    published_at: datetime
    slug: Optional[str] = None
    front_matter: Optional[Dict] = None
    metadata: Optional[Dict] = None

    @property
    def is_published(self) -> bool:
        """Check if the post is published based on the published_at date"""
        return self.published_at <= datetime.now()

    def to_dict(self) -> Dict:
        """Convert the blog post to a dictionary format for API submission"""
        return {
            "title": self.title,
            "content": self.content,
            "published_at": self.published_at.isoformat(),
            "slug": self.slug,
            "metadata": {
                "category": self.category,
                "themes": self.themes,
                **(self.metadata or {}),
            },
            **(self.front_matter or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BlogPost":
        """Create a BlogPost instance from a dictionary"""
        return cls(
            title=data["title"],
            content=data["content"],
            category=data.get("metadata", {}).get("category", "nerdposting"),
            themes=data.get("metadata", {}).get("themes", []),
            published_at=datetime.fromisoformat(data["published_at"]),
            slug=data.get("slug"),
            front_matter=data.get("front_matter"),
            metadata=data.get("metadata"),
        )
