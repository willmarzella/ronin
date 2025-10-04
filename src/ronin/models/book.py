"""Book model for Actualized.org book list tracking."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Book:
    """Represents a book from Actualized.org book list."""

    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    url: Optional[str] = None
    isbn: Optional[str] = None
    rating: Optional[float] = None
    read_status: bool = False
    date_added: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert book to dictionary format for JSON storage."""
        return {
            "title": self.title,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "url": self.url,
            "isbn": self.isbn,
            "rating": self.rating,
            "read_status": self.read_status,
            "date_added": self.date_added.isoformat() if self.date_added else None,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Book":
        """Create Book instance from dictionary."""
        data = data.copy()
        if data.get("date_added"):
            data["date_added"] = datetime.fromisoformat(data["date_added"])
        return cls(**data)

    def __hash__(self) -> int:
        """Make Book hashable based on title and author."""
        return hash((self.title, self.author))

    def __eq__(self, other) -> bool:
        """Compare books based on title and author."""
        if not isinstance(other, Book):
            return False
        return self.title == other.title and self.author == other.author
