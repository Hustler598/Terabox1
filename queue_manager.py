import asyncio
from typing import Dict, Set
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class QueueItem:
    url: str
    data: dict
    added_time: datetime
    chat_id: int = None
    message_id: int = None
    processing: bool = False

class QueueManager:
    def __init__(self):
        self._queue: Dict[str, QueueItem] = {}
        self._processing: Set[str] = set()
        self._lock = asyncio.Lock()
        
    async def add_to_queue(self, url: str, data: dict) -> bool:
        """Add URL and its data to queue"""
        async with self._lock:
            if url not in self._queue:
                self._queue[url] = QueueItem(
                    url=url,
                    data=data,
                    added_time=datetime.now()
                )
                logger.info(f"Added {url} to queue")
                return True
            return False
            
    async def remove_from_queue(self, url: str) -> bool:
        """Remove URL from queue after successful processing"""
        async with self._lock:
            if url in self._queue:
                del self._queue[url]
                if url in self._processing:
                    self._processing.remove(url)
                logger.info(f"Removed {url} from queue")
                return True
            return False
            
    async def get_next_unprocessed(self) -> QueueItem | None:
        """Get next unprocessed item from queue"""
        async with self._lock:
            for url, item in self._queue.items():
                if not item.processing and url not in self._processing:
                    item.processing = True
                    self._processing.add(url)
                    return item
            return None
            
    async def mark_as_failed(self, url: str):
        """Mark URL as failed processing"""
        async with self._lock:
            if url in self._processing:
                self._processing.remove(url)
            if url in self._queue:
                self._queue[url].processing = False
                
    def is_processing(self, url: str) -> bool:
        """Check if URL is currently being processed"""
        return url in self._processing

# Global queue manager instance
queue_manager = QueueManager()
