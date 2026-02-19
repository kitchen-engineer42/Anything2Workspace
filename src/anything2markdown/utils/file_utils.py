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
    Convert nested path to a grouped or flat output name.

    - Direct children of root_dir stay flat: ``file.pdf`` → ``file``
    - Files inside a subdirectory are grouped under the first sub-dir:
      ``sub/a/b/file.pdf`` → ``sub/a_b_file``

    Args:
        file_path: Full path to the file
        root_dir: Root directory to make path relative to

    Returns:
        Output name without extension (may contain one ``/`` for grouped files)
    """
    try:
        relative = file_path.relative_to(root_dir)
        parts = relative.parts
        if len(parts) <= 1:
            # Direct child → flat
            return relative.stem
        else:
            # Grouped: first subdirectory becomes folder, rest flattened
            group = parts[0]
            rest = "_".join(parts[1:])
            return str(Path(group) / Path(rest).stem)
    except ValueError:
        return file_path.stem
