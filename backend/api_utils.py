"""API utilities: retry with exponential backoff, session management."""

import time
import random
import logging
from functools import wraps

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = (429, 500, 502, 503, 504)


def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=60.0,
                       backoff_factor=2.0, retryable_statuses=RETRYABLE_STATUSES):
    """Decorator: retry a function with exponential backoff + jitter on transient failures.

    Respects the Retry-After header on 429 responses.
    Works on functions that return a requests.Response or raise an exception.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    # Check if result is a requests.Response with a retryable status
                    if hasattr(result, 'status_code'):
                        status = result.status_code
                        if status in retryable_statuses and attempt < max_retries:
                            delay = _get_delay(result, attempt, base_delay, max_delay, backoff_factor)
                            logger.warning('[Retry %d/%d] %s returned %d, retrying in %.1fs...',
                                           attempt + 1, max_retries, func.__name__, status, delay)
                            time.sleep(delay)
                            continue
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = _compute_delay(attempt, base_delay, max_delay, backoff_factor)
                        logger.warning('[Retry %d/%d] %s failed: %s, retrying in %.1fs...',
                                       attempt + 1, max_retries, func.__name__, e, delay)
                        time.sleep(delay)
                    else:
                        logger.error('[Retry exhausted] %s failed after %d attempts: %s',
                                     func.__name__, max_retries + 1, e)

            if last_error:
                raise last_error
            return None
        return wrapper
    return decorator


def _get_delay(response, attempt, base_delay, max_delay, backoff_factor):
    """Extract delay from Retry-After header if present, else compute exponential."""
    retry_after = response.headers.get('Retry-After')
    if retry_after is not None:
        try:
            return min(float(retry_after), max_delay)
        except ValueError:
            pass
    return _compute_delay(attempt, base_delay, max_delay, backoff_factor)


def _compute_delay(attempt, base_delay, max_delay, backoff_factor):
    """Exponential backoff with full jitter."""
    delay = base_delay * (backoff_factor ** attempt)
    delay = min(delay, max_delay)
    delay = random.uniform(0, delay)
    return delay
