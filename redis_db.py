import logging
import os
import sys
import threading
import typing
from typing import Any
import time
from config import REDIS_PUBLIC_URL

from redis import Redis as r

log = logging.getLogger("telethon")

class RedisConnection:
    def __init__(self):
        # Get Redis URL from config
        self.redis_url = REDIS_PUBLIC_URL
        
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                log.info(f"Attempting Redis connection (attempt {retry_count + 1}/{max_retries})")
                self.redis = r.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_timeout=10,
                    socket_connect_timeout=10,
                    socket_keepalive=True,
                    health_check_interval=30,
                    retry_on_timeout=True
                )
                
                # Test connection
                if not self.redis.ping():
                    raise ConnectionError("Redis ping failed")
                    
                log.info("Redis connection successful!")
                self._cache = {}
                
                # Start cache initialization in background
                self._cache_initialized = threading.Event()
                threading.Thread(target=self._init_cache, daemon=True).start()
                
                # Wait for cache to initialize
                if not self._cache_initialized.wait(timeout=30):
                    log.warning("Cache initialization timed out, continuing anyway")
                
                return
                
            except Exception as e:
                retry_count += 1
                log.error(f"Redis connection attempt {retry_count} failed: {e}")
                if retry_count == max_retries:
                    log.error("All Redis connection attempts failed")
                    sys.exit(1)
                time.sleep(5)  # Wait before retrying

    def _init_cache(self):
        """Initialize cache in background thread"""
        try:
            keys = self.redis.keys()
            for key in keys:
                self._cache[key] = self.redis.get(key)
            log.info(f"Successfully cached {len(self._cache)} keys")
        except Exception as e:
            log.error(f"Error initializing cache: {e}")
        finally:
            self._cache_initialized.set()

    def get(self, key: str) -> Any:
        """Get a value from cache or Redis"""
        try:
            if key in self._cache:
                return self._cache[key]
            value = self.redis.get(key)
            self._cache[key] = value
            return value
        except Exception as e:
            log.error(f"Error getting key {key}: {e}")
            return None

    def set(self, key: str, value: Any, ex: int = None) -> bool:
        """Set a value in both cache and Redis"""
        try:
            self._cache[key] = value
            return self.redis.set(key, value, ex=ex)
        except Exception as e:
            log.error(f"Error setting key {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a value from both cache and Redis"""
        try:
            if key in self._cache:
                del self._cache[key]
            return bool(self.redis.delete(key))
        except Exception as e:
            log.error(f"Error deleting key {key}: {e}")
            return False

    def set_key(self, key: str, value: Any) -> bool:
        """Set a key-value pair in Redis (alias for set method)"""
        return self.set(key, value)

# Initialize the connection
db = RedisConnection()
