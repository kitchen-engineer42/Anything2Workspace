"""Retry logic with decorator pattern."""

import functools
import time
from typing import Callable, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """Error that should trigger a retry."""

    pass


class NonRetryableError(Exception):
    """Error that should NOT trigger a retry (skip immediately)."""

    pass


def with_retry(
    max_retries: int = 1,
    delay_seconds: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
):
    """
    Decorator for retry logic: retry specified times then raise.

    Behavior: Retry once then skip, log failures.

    Args:
        max_retries: Maximum number of retry attempts (default: 1)
        delay_seconds: Delay between retries in seconds (default: 2.0)
        retryable_exceptions: Tuple of exception types to retry on

    Usage:
        @with_retry(max_retries=1, delay_seconds=2.0)
        def process_file(file_path):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except NonRetryableError:
                    # Don't retry, re-raise immediately
                    raise
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        logger.warning(
                            "Attempt failed, retrying",
                            function=func.__name__,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            error=str(e),
                            delay_seconds=delay_seconds,
                        )
                        time.sleep(delay_seconds)
                    else:
                        logger.error(
                            "All attempts failed, skipping",
                            function=func.__name__,
                            total_attempts=max_retries + 1,
                            error=str(e),
                        )

            # Re-raise the last exception
            if last_exception:
                raise last_exception

        return wrapper

    return decorator
