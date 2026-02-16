"""Levenshtein distance utilities for fuzzy string matching."""

import Levenshtein
import structlog

logger = structlog.get_logger(__name__)


def find_best_match(needle: str, haystack: str, search_window: int = 500) -> int | None:
    """
    Find the best matching position for a needle string in a haystack.

    Uses Levenshtein distance to find the closest match, which handles
    minor differences between LLM output and actual text.

    Args:
        needle: The string to find (typically K tokens from LLM output)
        haystack: The text to search in
        search_window: How far to search (in characters) to limit computation

    Returns:
        Character position of best match start, or None if no good match
    """
    if not needle or not haystack:
        return None

    needle_len = len(needle)
    best_pos = None
    best_distance = float("inf")

    # Limit search to reasonable window
    search_end = min(len(haystack), search_window)

    for i in range(search_end - needle_len + 1):
        candidate = haystack[i : i + needle_len]
        distance = Levenshtein.distance(needle, candidate)

        # Normalize by length to get similarity ratio
        similarity = 1 - (distance / max(len(needle), len(candidate)))

        if distance < best_distance and similarity > 0.7:  # At least 70% similar
            best_distance = distance
            best_pos = i

    if best_pos is not None:
        logger.debug(
            "Found match",
            position=best_pos,
            distance=best_distance,
            needle_preview=needle[:50],
        )

    return best_pos


def find_cut_position(
    tokens_before: str, tokens_after: str, text: str, search_start: int = 0
) -> int | None:
    """
    Find the exact cut position given tokens before and after the cut.

    The LLM provides K tokens before and K tokens after a suggested cut point.
    This function locates where that cut should happen in the actual text.

    Args:
        tokens_before: Text that should appear before the cut
        tokens_after: Text that should appear after the cut
        text: The full text to search in
        search_start: Starting position for search

    Returns:
        Character position for the cut, or None if not found
    """
    # Search for the "tokens_before" pattern first
    search_text = text[search_start:]

    before_pos = find_best_match(tokens_before, search_text, search_window=len(search_text))
    if before_pos is None:
        logger.warning("Could not find tokens_before in text")
        return None

    # The cut should be right after "tokens_before"
    cut_pos = search_start + before_pos + len(tokens_before)

    # Verify by checking if tokens_after is nearby
    after_search = text[cut_pos : cut_pos + len(tokens_after) + 100]
    after_pos = find_best_match(tokens_after, after_search, search_window=len(after_search))

    if after_pos is None or after_pos > 50:  # Allow small gap
        logger.warning(
            "tokens_after not found at expected position",
            expected_pos=cut_pos,
            after_pos=after_pos,
        )
        # Still return the position based on tokens_before
        return cut_pos

    # Adjust cut position if there's whitespace
    while cut_pos < len(text) and text[cut_pos] in " \t":
        cut_pos += 1

    return cut_pos
