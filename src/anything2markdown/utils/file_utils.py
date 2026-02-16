"""File system utilities."""

import os
from pathlib import Path
from typing import Generator


# Files to exclude when walking directories
EXCLUDED_FILES = {"urls.txt", ".gitkeep", ".DS_Store", ".env", ".env.example"}


def walk_directory(directory: Path) -> Generator[Path, None, None]:
    """
    Walk through nested folders and yield all files.
    Excludes hidden files and special files like urls.txt.

    Args:
        directory: Root directory to walk

    Yields:
        Path objects for each file found
    """
    if not directory.exists():
        return

    for root, dirs, files in os.walk(directory):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for filename in files:
            # Skip hidden files
            if filename.startswith("."):
                continue
            # Skip excluded files
            if filename in EXCLUDED_FILES:
                continue

            yield Path(root) / filename


def read_url_list(url_file: Path) -> list[str]:
    """
    Read URLs from a text file, one URL per line.
    Ignores empty lines and comments (lines starting with #).

    Args:
        url_file: Path to the URL list file

    Returns:
        List of URL strings
    """
    urls = []

    if not url_file.exists():
        return urls

    with open(url_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            urls.append(line)

    return urls


def ensure_directory(path: Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure exists

    Returns:
        The same path for chaining
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_file_size_mb(file_path: Path) -> float:
    """
    Get file size in megabytes.

    Args:
        file_path: Path to the file

    Returns:
        File size in MB
    """
    return file_path.stat().st_size / (1024 * 1024)


def flatten_path(file_path: Path, root_dir: Path) -> str:
    """
    Convert nested path to flat filename.
    e.g., folder1/folder2/file.pdf -> folder1_folder2_file

    Args:
        file_path: Full path to the file
        root_dir: Root directory to make path relative to

    Returns:
        Flattened filename without extension
    """
    try:
        relative = file_path.relative_to(root_dir)
        flat_name = str(relative).replace("/", "_").replace("\\", "_")
        # Remove extension
        return Path(flat_name).stem
    except ValueError:
        return file_path.stem
