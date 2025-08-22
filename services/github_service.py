from typing import Dict, List, Optional, Union
from github import Github, Repository, ContentFile
import os
import base64
from datetime import datetime
from core.logging import setup_logger

logger = setup_logger()


class GitHubService:
    def __init__(self, token: str, repo_name: str):
        """
        Initialize GitHub service with authentication token and repository name.

        Args:
            token (str): GitHub personal access token
            repo_name (str): Repository name in format "username/repo"
        """
        self.github = Github(token)
        self.repo_name = repo_name
        self._repo: Optional[Repository.Repository] = None
        self._initialize_repo()

    def _initialize_repo(self):
        """Initialize repository connection"""
        try:
            self._repo = self.github.get_repo(self.repo_name)
        except Exception as e:
            raise ValueError(
                f"Failed to initialize repository {self.repo_name}: {str(e)}"
            )

    def get_file_content(self, path: str) -> Optional[str]:
        """
        Get the content of a file from the repository.

        Args:
            path (str): Path to the file in the repository

        Returns:
            Optional[str]: File content if found, None otherwise
        """
        try:
            content_file = self._repo.get_contents(path)
            if isinstance(content_file, list):
                return None
            return base64.b64decode(content_file.content).decode("utf-8")
        except Exception as e:
            return None

    def get_directory_contents(self, path: str = "/") -> List[Dict[str, str]]:
        """
        Get contents of a directory in the repository.

        Args:
            path (str): Path to the directory

        Returns:
            List[Dict[str, str]]: List of file information dictionaries
        """
        try:
            contents = self._repo.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]

            logger.info(f"Found {len(contents)} files in {path}")

            return [
                {
                    "name": item.name,
                    "path": item.path,
                    "type": "file" if item.type == "file" else "dir",
                    "sha": item.sha,
                }
                for item in contents
            ]
        except Exception as e:
            return []

    def get_files_by_extension(
        self, directory: str, extension: str, max_files: int = 20
    ) -> List[Dict[str, Union[str, datetime]]]:
        """
        Get all files with a specific extension from a directory and its subdirectories.

        Args:
            directory (str): Directory to search in
            extension (str): File extension to filter by (e.g., ".md")
            max_files (int): Maximum number of files to process (default: 20)

        Returns:
            List[Dict[str, Union[str, datetime]]]: List of file information
        """

        def _get_files_iterative(files_found: List[Dict]) -> None:
            """Process files iteratively to avoid recursion."""
            assert isinstance(files_found, list), "files_found must be a list"
            assert (
                isinstance(max_files, int) and max_files > 0
            ), "max_files must be positive integer"

            # Use a queue for iterative directory traversal with bounded depth
            max_depth = 10  # Fixed maximum directory depth
            dirs_to_process = [(directory, 0)]  # (path, depth) tuples

            while dirs_to_process and len(files_found) < max_files:
                current_path, current_depth = dirs_to_process.pop(0)

                # Enforce depth limit to prevent infinite traversal
                if current_depth >= max_depth:
                    continue

                try:
                    contents = self._repo.get_contents(current_path)
                    if not isinstance(contents, list):
                        contents = [contents]

                    for item in contents:
                        # If we've reached the limit, stop processing
                        if len(files_found) >= max_files:
                            return

                        try:
                            if item.type == "dir":
                                # Add directory to processing queue with incremented depth
                                dirs_to_process.append((item.path, current_depth + 1))
                            elif item.type == "file" and item.name.endswith(extension):
                                try:
                                    # Get file content first
                                    content = base64.b64decode(item.content).decode(
                                        "utf-8"
                                    )

                                    # Then get commit info - use list slicing to get first commit
                                    commits = list(
                                        self._repo.get_commits(path=item.path)
                                    )[:1]
                                    if commits:
                                        commit = commits[0]
                                        files_found.append(
                                            {
                                                "name": item.name,
                                                "path": item.path,
                                                "sha": item.sha,
                                                "content": content,
                                                "last_modified": commit.commit.author.date,
                                                "last_commit_message": commit.commit.message,
                                            }
                                        )
                                        logger.info(
                                            f"Successfully processed file: {item.path} ({len(files_found)}/{max_files})"
                                        )
                                    else:
                                        logger.warning(
                                            f"No commit history found for file: {item.path}"
                                        )
                                        # Use timezone-aware datetime for fallback
                                        current_time = datetime.now(
                                            datetime.now().astimezone().tzinfo
                                        )
                                        files_found.append(
                                            {
                                                "name": item.name,
                                                "path": item.path,
                                                "sha": item.sha,
                                                "content": content,
                                                "last_modified": current_time,  # timezone-aware fallback
                                                "last_commit_message": "No commit history available",
                                            }
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"Error processing file {item.path}: {str(e)}"
                                    )
                                    # If we hit rate limit, raise to outer exception handler
                                    if "rate limit" in str(e).lower():
                                        raise
                                    continue
                        except Exception as e:
                            logger.error(
                                f"Error processing item {item.path if hasattr(item, 'path') else 'unknown'}: {str(e)}"
                            )
                            if "rate limit" in str(e).lower():
                                raise
                            continue

                except Exception as e:
                    error_msg = str(e).lower()
                    if "rate limit" in error_msg:
                        logger.error(
                            "GitHub API rate limit exceeded. Please wait before trying again."
                        )
                        raise
                    logger.error(f"Error accessing directory {current_path}: {str(e)}")

        try:
            logger.info(
                f"Starting file search in directory: {directory} (limit: {max_files} files)"
            )
            files = []
            _get_files_iterative(files)
            if len(files) >= max_files:
                logger.info(f"Reached file limit of {max_files} files")
            return files
        except Exception as e:
            if "rate limit" in str(e).lower():
                # Re-raise rate limit errors
                raise
            logger.error(f"Failed to search for files: {str(e)}")
            return []

    def create_or_update_file(
        self, path: str, content: str, commit_message: str, branch: str = "main"
    ) -> Dict[str, str]:
        """
        Create or update a file in the repository.

        Args:
            path (str): Path where to create/update the file
            content (str): Content to write to the file
            commit_message (str): Commit message
            branch (str): Branch to commit to

        Returns:
            Dict[str, str]: Result of the operation
        """
        try:
            # Check if file exists
            try:
                file = self._repo.get_contents(path, ref=branch)
                # Update existing file
                self._repo.update_file(
                    path=path,
                    message=commit_message,
                    content=content,
                    sha=file.sha,
                    branch=branch,
                )
                return {"status": "updated", "path": path}
            except:
                # Create new file
                self._repo.create_file(
                    path=path, message=commit_message, content=content, branch=branch
                )
                return {"status": "created", "path": path}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_file_history(
        self, path: str, max_commits: int = 10
    ) -> List[Dict[str, Union[str, datetime]]]:
        """
        Get the commit history for a specific file.

        Args:
            path (str): Path to the file
            max_commits (int): Maximum number of commits to retrieve

        Returns:
            List[Dict[str, Union[str, datetime]]]: List of commit information
        """
        try:
            commits = self._repo.get_commits(path=path)
            history = []

            for commit in commits[:max_commits]:
                history.append(
                    {
                        "sha": commit.sha,
                        "message": commit.commit.message,
                        "author": commit.commit.author.name,
                        "date": commit.commit.author.date,
                        "url": commit.html_url,
                    }
                )

            return history
        except Exception as e:
            return []

    def search_files(
        self, query: str, extension: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Search for files in the repository.

        Args:
            query (str): Search query
            extension (Optional[str]): Filter by file extension

        Returns:
            List[Dict[str, str]]: List of matching files
        """
        try:
            # Build the search query
            search_query = f"repo:{self.repo_name} {query}"
            if extension:
                search_query += f" extension:{extension.lstrip('.')}"

            # Search code in the repository
            results = self.github.search_code(search_query)

            return [
                {
                    "name": item.name,
                    "path": item.path,
                    "url": item.html_url,
                    "repository": item.repository.full_name,
                }
                for item in results
            ]
        except Exception as e:
            return []

    def close(self):
        """Close the GitHub connection"""
        if self.github:
            self.github.close()
