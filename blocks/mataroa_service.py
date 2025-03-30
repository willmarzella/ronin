"""Mataroa blog API service."""

import os
import requests
from typing import Dict, Optional
from datetime import datetime


class MataroaService:
    """Service for interacting with Mataroa blog API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Mataroa service with API key."""
        self.api_key = api_key or os.getenv("MATAROA_API_KEY")
        if not self.api_key:
            raise ValueError("MATAROA_API_KEY environment variable is required")

        self.api_url = "https://mataroa.blog/api/posts/"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def create_post(
        self, title: str, body: str, published_at: Optional[str] = None
    ) -> Dict:
        """
        Create a new blog post.

        Args:
            title: Post title
            body: Post content in markdown format
            published_at: Optional publication date (ISO format)

        Returns:
            Dict containing post details including slug and URL
        """
        data = {
            "title": title,
            "body": body,
        }

        if published_at:
            data["published_at"] = published_at

        response = requests.post(self.api_url, headers=self.headers, json=data)

        if response.status_code not in [200, 201]:  # Accept both 200 and 201 as success
            raise Exception(
                f"Failed to create post: {response.status_code} - {response.text}"
            )

        return response.json()

    def update_post(
        self, slug: str, title: str, body: str, published_at: Optional[str] = None
    ) -> Dict:
        """
        Update an existing blog post.

        Args:
            slug: Post slug
            title: Updated title
            body: Updated content
            published_at: Optional updated publication date

        Returns:
            Dict containing updated post details
        """
        data = {
            "title": title,
            "body": body,
        }

        if published_at:
            data["published_at"] = published_at

        url = f"{self.api_url}{slug}/"
        response = requests.patch(url, headers=self.headers, json=data)

        if response.status_code != 200:
            raise Exception(
                f"Failed to update post: {response.status_code} - {response.text}"
            )

        return response.json()

    def get_post(self, slug: str) -> Optional[Dict]:
        """
        Fetch a post by its slug.

        Args:
            slug: Post slug

        Returns:
            Dict containing post details or None if not found
        """
        url = f"{self.api_url}{slug}/"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            raise Exception(
                f"Failed to fetch post: {response.status_code} - {response.text}"
            )

    def delete_post(self, slug: str) -> Dict:
        """
        Delete a blog post by its slug.

        Args:
            slug: Post slug to delete

        Returns:
            Dict containing deletion confirmation

        Raises:
            Exception: If deletion fails
        """
        url = f"{self.api_url}{slug}/"
        response = requests.delete(url, headers=self.headers)

        if response.status_code != 200:
            raise Exception(
                f"Failed to delete post: {response.status_code} - {response.text}"
            )

        return {"ok": True}
