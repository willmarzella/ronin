import json
import os
import sys
from typing import Dict, List, Optional

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(project_root)

from services.mataroa_service import MataroaService


def delete_blog_post(slug: str, api_key: Optional[str] = None) -> Dict:
    """
    Delete a blog post from Mataroa.

    Args:
        slug (str): The slug of the post to delete
        api_key (Optional[str]): Mataroa API key. If not provided, will use
            environment variable

    Returns:
        Dict: Confirmation of deletion

    Raises:
        Exception: If deletion fails
    """
    mataroa_service = MataroaService(api_key=api_key)
    return mataroa_service.delete_post(slug)


def delete_all_posts(api_key: Optional[str] = None) -> List[Dict]:
    """
    Delete all posts listed in the publishing_stats.json file as fast as possible.

    Args:
        api_key (Optional[str]): Mataroa API key. If not provided, will use
            environment variable

    Returns:
        List[Dict]: List of results for each deletion attempt
    """
    # Load the stats file
    with open("./tests/publishing_stats.json", "r") as f:
        stats = json.load(f)

    results = []
    mataroa_service = MataroaService(api_key=api_key)
    total_posts = len(stats.get("published_urls", []))

    print(f"Starting deletion of {total_posts} posts...")

    for i, post in enumerate(stats.get("published_urls", []), 1):
        url = post["url"]
        slug = url.rstrip("/").split("/")[-1]

        try:
            result = mataroa_service.delete_post(slug)
            results.append(
                {
                    "title": post["title"],
                    "slug": slug,
                    "status": "success",
                    "result": result,
                }
            )
            print(f"[{i}/{total_posts}] Deleted: {post['title']}")
        except Exception as e:
            results.append(
                {
                    "title": post["title"],
                    "slug": slug,
                    "status": "error",
                    "error": str(e),
                }
            )
            print(f"[{i}/{total_posts}] Failed: {post['title']} - {str(e)}")

    successful = len([r for r in results if r["status"] == "success"])
    failed = len([r for r in results if r["status"] == "error"])
    print(f"\nComplete! Deleted {successful} posts, Failed {failed} posts")

    return results


if __name__ == "__main__":
    try:
        delete_all_posts()
    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)
