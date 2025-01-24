from functools import wraps

def synchronized(lock):
    """A decorator that synchronizes using a lock stored as an instance attribute."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            lock = getattr(self, lock)  # Get the lock from the object
            async with lock:
                return await func(self, *args, **kwargs)
        return wrapper
    return decorator