from typing import Dict
from dataclasses import dataclass
from datetime import datetime
import asyncio

@dataclass
class QuickRejectCacheEntry:
    """Cache entry for room quick reject decisions"""
    subject_code: str
    room_id: str
    should_reject: bool
    timestamp: datetime = datetime.now()

class RoomQuickRejectFilter:
    """Optimization filter for quickly rejecting unsuitable rooms"""
    
    MEETING_ROOM_THRESHOLD = 10
    CACHE_TTL_SECONDS = 300  # 5 minute cache entries
    
    def __init__(self):
        self._cache: Dict[str, QuickRejectCacheEntry] = {}
        self._lock = asyncio.Lock()
        
    def _get_cache_key(self, subject_code: str, room_id: str) -> str:
        """Generate cache key from subject and room IDs"""
        return f"{subject_code}-{room_id}"
        
    async def can_quick_reject(self, 
                             subject_name: str,
                             subject_code: str, 
                             subject_campus: str,
                             subject_vacancies: int,
                             room_code: str,
                             room_campus: str,
                             room_capacity: int) -> bool:
        """
        Quickly determine if a room can be rejected without full evaluation
        
        Args:
            subject_name: Name of the subject
            subject_code: Subject's code
            subject_campus: Subject's campus
            subject_vacancies: Number of students
            room_code: Room's code
            room_campus: Room's campus  
            room_capacity: Room's capacity
            
        Returns:
            bool: True if room can be rejected, False if it needs full evaluation
        """
        cache_key = self._get_cache_key(subject_code, room_code)
        
        async with self._lock:
            # Check cache first
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                age = (datetime.now() - entry.timestamp).total_seconds()
                if age < self.CACHE_TTL_SECONDS:
                    return entry.should_reject
                
            # Quick reject conditions
            should_reject = False
            
            # Campus mismatch
            if room_campus != subject_campus:
                should_reject = True
                
            else:
                # Meeting room logic
                subject_needs_meeting_room = subject_vacancies < self.MEETING_ROOM_THRESHOLD
                is_meeting_room = room_capacity < self.MEETING_ROOM_THRESHOLD
                
                # Reject if meeting room requirements don't match
                if subject_needs_meeting_room != is_meeting_room:
                    should_reject = True
                    
                # For meeting rooms, be more lenient with capacity
                elif is_meeting_room:
                    should_reject = room_capacity < (subject_vacancies * 0.8)
                    
                # For regular rooms
                else:
                    should_reject = room_capacity < subject_vacancies
                    
            # Cache the result
            self._cache[cache_key] = QuickRejectCacheEntry(
                subject_code=subject_code,
                room_id=room_code,
                should_reject=should_reject
            )
            
            return should_reject
            
    async def cleanup_cache(self):
        """Remove expired cache entries"""
        async with self._lock:
            now = datetime.now()
            expired_keys = [
                key for key, entry in self._cache.items()
                if (now - entry.timestamp).total_seconds() > self.CACHE_TTL_SECONDS
            ]
            for key in expired_keys:
                del self._cache[key]