import re
from typing import Dict, List, Tuple
from services.github_service import GitHubService
from datetime import datetime, timedelta
from core.logging import setup_logger

logger = setup_logger()


class NoteParser:
    def __init__(self, github_token: str, repo_name: str):
        """
        Initialize the note parser with GitHub credentials

        Args:
            github_token (str): GitHub personal access token
            repo_name (str): Repository name in format "username/repo"
        """
        self.github_service = GitHubService(github_token, repo_name)
        logger.info(f"Initialized NoteParser for {repo_name}")

    def get_repo_notes(
        self, directory_path: str = "/", days: int = 7, max_files: int = 3
    ) -> List[Dict]:
        """
        Fetches markdown notes from the specified GitHub repository directory
        that match the YYYY-MM-DD filename format for daily notes.
        Returns the most recent N notes based on the date in the filename.
        Also fetches the most recent conversation notes from the "conversations" subdirectory.

        Args:
            directory_path (str): Path to the notes directory in the repository (defaults to root)
            days (int): Number of most recent daily notes to retrieve (default: 7)
            max_files (int): Maximum number of files to process (default: 3)

        Returns:
            List[Dict]: List of processed notes with their metadata
        """
        try:
            # Get timezone for consistency
            today = datetime.now(datetime.now().astimezone().tzinfo)
            logger.info(
                f"Looking for the {days} most recent daily notes (limit: {max_files} files)"
            )

            # Get daily notes
            daily_notes = self._get_daily_notes(directory_path, days, max_files)

            # Get conversation notes (3 most recent)
            # Use the correct path for conversations directory
            # Instead of appending to the daily notes path, use the parent directory
            if directory_path.endswith("daily-notes"):
                # If we're in daily-notes, go up one level and then to conversations
                parent_dir = "/".join(directory_path.rstrip("/").split("/")[:-1])
                conversation_path = f"{parent_dir}/conversations"
            else:
                # If we're at the root or another directory, use the specified conversations path
                conversation_path = "02 - timeline/conversations"

            logger.info(f"Looking for conversation notes in: {conversation_path}")
            conversation_notes = self._get_conversation_notes(
                conversation_path, max_files=0
            )

            # Combine both types of notes
            all_notes = daily_notes + conversation_notes
            logger.info(
                f"Successfully processed {len(all_notes)} total notes ({len(daily_notes)} daily, {len(conversation_notes)} conversation)"
            )

            return all_notes

        except Exception as e:
            logger.error(f"Unexpected error in get_repo_notes: {str(e)}")
            return []

    def _get_daily_notes(
        self, directory_path: str, days: int, max_files: int
    ) -> List[Dict]:
        """
        Fetches daily notes with YYYY-MM-DD.md format from the specified directory.

        Args:
            directory_path (str): Path to the notes directory
            days (int): Number of most recent daily notes to retrieve
            max_files (int): Maximum number of files to process

        Returns:
            List[Dict]: List of processed daily notes
        """
        try:
            # Get timezone for consistency
            today = datetime.now(datetime.now().astimezone().tzinfo)

            # First, get all files in the directory to identify daily notes
            try:
                directory_contents = self.github_service.get_directory_contents(
                    directory_path
                )
                logger.info(
                    f"Found {len(directory_contents)} items in directory {directory_path}"
                )
            except Exception as e:
                logger.error(f"Failed to fetch directory contents: {str(e)}")
                return []

            # Filter for markdown files with YYYY-MM-DD format
            date_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
            daily_notes = []

            for file_info in directory_contents:
                # Skip directories
                if file_info.get("type") != "file":
                    continue

                file_name = file_info.get("name", "")

                # Check if filename matches YYYY-MM-DD.md pattern
                match = date_pattern.match(file_name)
                if not match:
                    logger.debug(f"Skipping non-daily note: {file_info.get('path')}")
                    continue

                # Extract date from filename
                date_str = match.group(1)
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    file_date = file_date.replace(
                        tzinfo=today.tzinfo
                    )  # Make timezone-aware

                    # Add file date for sorting
                    file_info["file_date"] = file_date
                    file_info["date_str"] = date_str
                    file_info["note_type"] = "daily"
                    daily_notes.append(file_info)
                    logger.debug(
                        f"Found daily note: {file_info.get('path')} ({date_str})"
                    )
                except ValueError:
                    logger.warning(
                        f"Invalid date format in filename: {file_info.get('path')}"
                    )
                    continue

            if not daily_notes:
                logger.warning("No daily notes with YYYY-MM-DD format found")
                return []

            # Sort by date (newest first) and limit to the number of days requested
            daily_notes.sort(key=lambda x: x["file_date"], reverse=True)

            # Limit to the requested number of days
            selected_notes = daily_notes[:days]

            logger.info(f"Selected {len(selected_notes)} most recent daily notes")

            # Now fetch full content for only the selected notes
            return self._process_note_files(selected_notes)

        except Exception as e:
            logger.error(f"Unexpected error in _get_daily_notes: {str(e)}")
            return []

    def _get_conversation_notes(
        self, conversation_path: str, max_files: int = 0
    ) -> List[Dict]:
        """
        Fetches the most recent conversation notes from the specified directory.
        Handles conversation notes with format "YYYY-MM-DD - Person Name.md"
        and variations like "YYYY-MM-DD- Person Name.md"

        Args:
            conversation_path (str): Path to the conversations directory
            max_files (int): Maximum number of conversation files to retrieve

        Returns:
            List[Dict]: List of processed conversation notes
        """
        try:
            logger.info(f"Looking for the {max_files} most recent conversation notes")

            # Get all files in the conversations directory
            try:
                directory_contents = self.github_service.get_directory_contents(
                    conversation_path
                )
                logger.info(
                    f"Found {len(directory_contents)} items in directory {conversation_path}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to fetch conversation directory contents: {str(e)}"
                )
                return []

            # Filter for markdown files with conversation format (YYYY-MM-DD - Person Name)
            conversation_files = []
            # Updated pattern to match variations:
            # - "YYYY-MM-DD - Person Name.md" (standard)
            # - "YYYY-MM-DD- Person Name.md" (no space before hyphen)
            # - "YYYY-MM-DD -Person Name.md" (no space after hyphen)
            # - "YYYY-MM-DD-Person Name.md" (no spaces around hyphen)
            convo_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*-\s*(.+)\.md$")
            today = datetime.now(datetime.now().astimezone().tzinfo)

            for file_info in directory_contents:
                # Skip directories
                if file_info.get("type") != "file":
                    continue

                file_name = file_info.get("name", "")

                # Only include markdown files
                if not file_name.endswith(".md"):
                    continue

                # Try to extract date from filename using the conversation format
                match = convo_pattern.match(file_name)
                if match:
                    # Extract date and person name
                    date_str = match.group(1)
                    person_name = match.group(2)

                    # Log the exact format found for debugging
                    logger.debug(
                        f"Matched conversation note format: '{file_name}' → Date: '{date_str}', Person: '{person_name}'"
                    )

                    try:
                        # Parse the date
                        file_date = datetime.strptime(date_str, "%Y-%m-%d")
                        file_date = file_date.replace(
                            tzinfo=today.tzinfo
                        )  # Make timezone-aware

                        # Add metadata
                        file_info["file_date"] = file_date
                        file_info["date_str"] = date_str
                        file_info["person_name"] = person_name
                        file_info["note_type"] = "conversation"
                        conversation_files.append(file_info)
                        logger.debug(
                            f"Found conversation note: {file_info.get('path')} ({date_str} - {person_name})"
                        )
                    except ValueError:
                        logger.warning(
                            f"Invalid date format in conversation filename: {file_info.get('path')}"
                        )
                        continue
                else:
                    # For files that don't match the pattern, fall back to commit date
                    file_path = file_info.get("path")
                    logger.debug(
                        f"Filename '{file_name}' didn't match conversation pattern, using commit date"
                    )
                    commit_info = self.github_service.get_file_history(
                        file_path, max_commits=1
                    )

                    if commit_info:
                        last_modified = commit_info[0].get("date")
                        file_info["last_modified"] = last_modified
                        file_info["note_type"] = "conversation"
                        conversation_files.append(file_info)
                        logger.debug(
                            f"Found conversation note (using commit date): {file_path}"
                        )

            if not conversation_files:
                logger.warning("No conversation notes found")
                return []

            # Sort by file date if available, otherwise by last modified date
            conversation_files.sort(
                key=lambda x: x.get("file_date", x.get("last_modified")), reverse=True
            )

            # Limit to the requested number of files
            selected_notes = conversation_files[:max_files]

            logger.info(
                f"Selected {len(selected_notes)} most recent conversation notes"
            )

            # Process the selected conversation notes
            return self._process_note_files(selected_notes)

        except Exception as e:
            logger.error(f"Unexpected error in _get_conversation_notes: {str(e)}")
            return []

    def _process_note_files(self, file_info_list: List[Dict]) -> List[Dict]:
        """
        Process a list of file information dictionaries to fetch and parse their content.

        Args:
            file_info_list (List[Dict]): List of file information dictionaries

        Returns:
            List[Dict]: List of processed notes with content and metadata
        """
        notes = []

        for i, file_info in enumerate(file_info_list):
            try:
                # Fetch content for the file
                file_path = file_info.get("path")
                file_content = self.github_service.get_file_content(file_path)

                if not file_content:
                    logger.warning(f"No content found for file {file_path}")
                    continue

                # Parse the markdown content
                try:
                    front_matter, body = self.parse_markdown(file_content)
                except Exception as e:
                    logger.error(f"Failed to parse markdown for {file_path}: {str(e)}")
                    continue

                # Get commit info for the file if not already present
                if "last_modified" not in file_info:
                    commit_info = self.github_service.get_file_history(
                        file_path, max_commits=1
                    )
                    last_modified = commit_info[0].get("date") if commit_info else None
                    last_commit = commit_info[0].get("message") if commit_info else None
                else:
                    last_modified = file_info.get("last_modified")
                    commit_info = self.github_service.get_file_history(
                        file_path, max_commits=1
                    )
                    last_commit = commit_info[0].get("message") if commit_info else None

                note_data = {
                    "path": file_path,
                    "front_matter": front_matter,
                    "content": body,
                    "sha": file_info.get("sha"),
                    "last_modified": last_modified,
                    "last_commit": last_commit,
                    "note_type": file_info.get("note_type", "unknown"),
                }

                # Add date for daily notes
                if "date_str" in file_info:
                    note_data["date"] = file_info["date_str"]

                notes.append(note_data)
                logger.info(
                    f"Successfully processed {file_info.get('note_type', 'unknown')} note: {file_path} ({i+1}/{len(file_info_list)})"
                )

            except Exception as e:
                logger.error(
                    f"Error processing file {file_info.get('path', 'unknown')}: {str(e)}"
                )
                continue

        return notes

    def parse_markdown(self, content: str) -> Tuple[Dict, str]:
        """
        Parses markdown content into front matter and body

        Args:
            content (str): Raw markdown content

        Returns:
            Tuple[Dict, str]: (front matter dictionary, markdown body)
        """
        front_matter = {}
        body = content

        if content.startswith("---"):
            parts = content[3:].split("---", 1)
            if len(parts) >= 2:
                front_matter_str, body = parts
                front_matter = self._parse_front_matter(front_matter_str)
                body = body.strip()
        return front_matter, body

    def _parse_front_matter(self, content: str) -> Dict:
        """
        Parses YAML front matter into a dictionary

        Args:
            content (str): Front matter content

        Returns:
            Dict: Parsed front matter
        """
        front_matter = {}
        lines = content.strip().split("\n")
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                front_matter[key.strip()] = value.strip()
        return front_matter

    def __del__(self):
        """Cleanup GitHub connection when object is destroyed"""
        try:
            self.github_service.close()
        except:
            pass
