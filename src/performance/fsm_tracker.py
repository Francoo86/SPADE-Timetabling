from dataclasses import dataclass
from datetime import datetime
import asyncio
import aiofiles
from typing import Dict, Optional, List
import json
from enum import Enum

@dataclass
class NegotiationEvent:
    """Represents a single negotiation event/message"""
    timestamp: datetime
    professor_name: str
    subject_name: Optional[str]
    fsm_state: str
    performative: str
    room_code: Optional[str]
    message_type: str  # 'sent' or 'received'
    satisfaction_score: Optional[int]
    details: Optional[str]
    
class FSMMetricsTracker:
    """Tracks metrics for FSM negotiations with async file I/O"""
    
    def __init__(self, negotiations_log_file: str):
        self.negotiations_log_file = negotiations_log_file
        self.current_negotiations: Dict[str, Dict] = {}  # prof_name -> negotiation_data
        self._lock = asyncio.Lock()
        asyncio.create_task(self._init_log_file())
        
    async def _init_log_file(self):
        """Initialize the negotiations log CSV file with headers using aiofiles"""
        headers = [
            'timestamp', 'professor_name', 'subject_name', 'fsm_state',
            'performative', 'room_code', 'message_type', 'satisfaction_score',
            'rtt_ms', 'cycle_duration_ms', 'details'
        ]
        async with aiofiles.open(self.negotiations_log_file, 'w', encoding='utf-8') as f:
            await f.write(','.join(headers) + '\n')
            
    async def log_negotiation_event(self, event: NegotiationEvent):
        """Log a negotiation event and update metrics"""
        async with self._lock:
            prof_data = self.current_negotiations.setdefault(
                event.professor_name, 
                {
                    'cycle_start': datetime.now(),
                    'last_message': None,
                    'messages': []
                }
            )
            
            # Calculate RTT if this is a response
            rtt_ms = None
            if event.message_type == 'received' and prof_data['last_message']:
                rtt_ms = (event.timestamp - prof_data['last_message']).total_seconds() * 1000
                
            # Calculate cycle duration if state is changing
            cycle_duration_ms = None
            if prof_data.get('current_state') != event.fsm_state:
                cycle_duration_ms = (event.timestamp - prof_data['cycle_start']).total_seconds() * 1000
                prof_data['cycle_start'] = event.timestamp
                prof_data['current_state'] = event.fsm_state
                
            # Update last message timestamp
            if event.message_type == 'sent':
                prof_data['last_message'] = event.timestamp
                
            # Store message
            prof_data['messages'].append(event)
            
            # Prepare CSV row
            row = [
                event.timestamp.isoformat(),
                event.professor_name,
                event.subject_name or '',
                event.fsm_state,
                event.performative,
                event.room_code or '',
                event.message_type,
                str(event.satisfaction_score or ''),
                f"{rtt_ms:.2f}" if rtt_ms else '',
                f"{cycle_duration_ms:.2f}" if cycle_duration_ms else '',
                event.details or ''
            ]
            
            # Write to CSV using aiofiles
            async with aiofiles.open(self.negotiations_log_file, 'a', encoding='utf-8') as f:
                await f.write(','.join(row) + '\n')
                
    async def clear_professor_data(self, professor_name: str):
        """Clear stored data for a professor when they finish"""
        async with self._lock:
            if professor_name in self.current_negotiations:
                # Write summary before clearing
                prof_data = self.current_negotiations[professor_name]
                summary_row = [
                    datetime.now().isoformat(),
                    professor_name,
                    'SUMMARY',
                    'FINISHED',
                    '',
                    '',
                    '',
                    '',
                    '',
                    str((datetime.now() - prof_data['cycle_start']).total_seconds() * 1000),
                    f"Total messages: {len(prof_data['messages'])}"
                ]
                
                async with aiofiles.open(self.negotiations_log_file, 'a', encoding='utf-8') as f:
                    await f.write(','.join(summary_row) + '\n')
                    
                del self.current_negotiations[professor_name]

class EnhancedMetricsMonitor:
    """Enhanced metrics monitor that includes FSM and negotiation tracking"""
    
    def __init__(self, 
                 output_file: str,
                 request_log_file: str,
                 negotiations_log_file: str):
        self.output_file = output_file
        self.request_log_file = request_log_file
        self.fsm_tracker = FSMMetricsTracker(negotiations_log_file)
        self._lock = asyncio.Lock()

    async def log_negotiation(self,
                            professor_name: str,
                            subject_name: Optional[str],
                            fsm_state: str,
                            performative: str,
                            room_code: Optional[str],
                            message_type: str,
                            satisfaction_score: Optional[int] = None,
                            details: Optional[str] = None):
        """Log a negotiation event"""
        event = NegotiationEvent(
            timestamp=datetime.now(),
            professor_name=professor_name,
            subject_name=subject_name,
            fsm_state=fsm_state,
            performative=performative,
            room_code=room_code,
            message_type=message_type,
            satisfaction_score=satisfaction_score,
            details=details
        )
        await self.fsm_tracker.log_negotiation_event(event)
        
    async def clear_professor_tracking(self, professor_name: str):
        """Clear tracking data for a professor"""
        await self.fsm_tracker.clear_professor_data(professor_name)
        
    async def close(self):
        """Close all file handles and write final summaries"""
        if hasattr(self, 'fsm_tracker'):
            for prof_name in list(self.fsm_tracker.current_negotiations.keys()):
                await self.clear_professor_tracking(prof_name)