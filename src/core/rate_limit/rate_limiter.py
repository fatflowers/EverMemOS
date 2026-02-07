"""
Async rate limiting decorator module based on aiolimiter

Provides rate limiting functionality for async functions with flexible configuration.
"""

from collections import OrderedDict
from functools import wraps
import time
from typing import Callable, Any, Optional
from aiolimiter import AsyncLimiter


class RateLimitManager:
    """Rate limit manager that manages multiple limiter instances"""

    def __init__(self, max_size: int = 1024, ttl_seconds: Optional[float] = None):
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        self._limiters: "OrderedDict[str, tuple[AsyncLimiter, float]]" = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

    def _purge_expired(self, now: float) -> None:
        if self._ttl_seconds is None:
            return
        expired_keys = [
            key
            for key, (_, last_used) in self._limiters.items()
            if now - last_used >= self._ttl_seconds
        ]
        for key in expired_keys:
            self._limiters.pop(key, None)

    def _evict_overflow(self) -> None:
        while len(self._limiters) > self._max_size:
            self._limiters.popitem(last=False)

    def get_limiter(self, key: str, max_rate: int, time_period: int) -> AsyncLimiter:
        """
        Get or create a limiter instance

        Args:
            key: Unique identifier for the limiter
            max_rate: Maximum number of allowed requests within the time window
            time_period: Time window size (seconds)

        Returns:
            AsyncLimiter: Limiter instance
        """
        limiter_key = f"{key}_{max_rate}_{time_period}"
        now = time.monotonic()

        self._purge_expired(now)

        if limiter_key in self._limiters:
            limiter, _ = self._limiters[limiter_key]
            self._limiters[limiter_key] = (limiter, now)
            self._limiters.move_to_end(limiter_key)
            return limiter

        limiter = AsyncLimiter(max_rate, time_period)
        self._limiters[limiter_key] = (limiter, now)
        self._limiters.move_to_end(limiter_key)
        self._evict_overflow()
        return limiter


# Global rate limit manager instance
_rate_limit_manager = RateLimitManager()


def rate_limit(
    max_rate: int = 3,
    time_period: int = 10,
    key_func: Optional[Callable[..., str]] = None,
):
    """
    Async function rate limiting decorator

    Args:
        max_rate: Maximum number of allowed requests within the time window, default is 3
        time_period: Time window size (seconds), default is 10 seconds
        key_func: Optional key function to generate different rate limit keys for different parameters
                 If not provided, all calls share the same limiter

    Raises:
        ValueError: Raised when max_rate <= 0 or time_period <= 0

    Usage:
        @rate_limit(max_rate=3, time_period=10)
        async def my_api_call():
            pass

        @rate_limit(max_rate=5, time_period=60, key_func=lambda user_id: f"user_{user_id}")
        async def user_specific_call(user_id: str):
            pass
    """
    if max_rate <= 0:
        raise ValueError(f"max_rate must be positive, got {max_rate}")
    if time_period <= 0:
        raise ValueError(f"time_period must be positive, got {time_period}")

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Generate key for the limiter
            if key_func:
                # Use custom key function
                try:
                    limiter_key = key_func(*args, **kwargs)
                except (TypeError, ValueError, KeyError):
                    # If key function fails, use function name as default key
                    limiter_key = func.__name__
            else:
                # Use function name as default key
                limiter_key = func.__name__

            # Get the limiter
            limiter = _rate_limit_manager.get_limiter(
                limiter_key, max_rate, time_period
            )

            # Wait for the limiter to allow execution
            async with limiter:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


# Predefined common rate limiting decorators
def rate_limit_3_per_10s(func: Callable) -> Callable:
    """Rate limiting decorator allowing maximum 3 requests per 10 seconds"""
    return rate_limit(max_rate=3, time_period=10)(func)


def rate_limit_5_per_minute(func: Callable) -> Callable:
    """Rate limiting decorator allowing maximum 5 requests per minute"""
    return rate_limit(max_rate=5, time_period=60)(func)


def rate_limit_10_per_hour(func: Callable) -> Callable:
    """Rate limiting decorator allowing maximum 10 requests per hour"""
    return rate_limit(max_rate=10, time_period=3600)(func)
