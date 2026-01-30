"""
Simple rate limiting utilities using Django's cache framework.
"""
from django.core.cache import cache
from django.utils import timezone


def check_rate_limit(key, max_attempts, window_seconds):
    """
    Check if rate limit is exceeded.

    Args:
        key: Unique identifier (e.g., 'password_reset:email@example.com')
        max_attempts: Maximum number of attempts allowed
        window_seconds: Time window in seconds

    Returns:
        tuple: (is_allowed, attempts_remaining, seconds_until_reset)
    """
    cache_key = f'rate_limit:{key}'

    # Get current attempts data
    data = cache.get(cache_key)
    now = timezone.now().timestamp()

    if data is None:
        # First attempt
        data = {
            'attempts': 1,
            'first_attempt': now,
        }
        cache.set(cache_key, data, window_seconds)
        return True, max_attempts - 1, window_seconds

    # Check if window has expired
    elapsed = now - data['first_attempt']
    if elapsed >= window_seconds:
        # Reset window
        data = {
            'attempts': 1,
            'first_attempt': now,
        }
        cache.set(cache_key, data, window_seconds)
        return True, max_attempts - 1, window_seconds

    # Check if limit exceeded
    if data['attempts'] >= max_attempts:
        seconds_remaining = int(window_seconds - elapsed)
        return False, 0, seconds_remaining

    # Increment attempts
    data['attempts'] += 1
    remaining_time = int(window_seconds - elapsed)
    cache.set(cache_key, data, remaining_time)

    return True, max_attempts - data['attempts'], remaining_time


def get_remaining_attempts(key, max_attempts, window_seconds):
    """
    Get remaining attempts without incrementing.
    """
    cache_key = f'rate_limit:{key}'
    data = cache.get(cache_key)

    if data is None:
        return max_attempts

    now = timezone.now().timestamp()
    elapsed = now - data['first_attempt']

    if elapsed >= window_seconds:
        return max_attempts

    return max(0, max_attempts - data['attempts'])


# Rate limit constants
PASSWORD_RESET_MAX_ATTEMPTS = 3  # Max 3 attempts per email per hour
PASSWORD_RESET_WINDOW = 3600  # 1 hour in seconds

PASSWORD_RESET_IP_MAX_ATTEMPTS = 10  # Max 10 attempts per IP per hour
PASSWORD_RESET_IP_WINDOW = 3600  # 1 hour in seconds
