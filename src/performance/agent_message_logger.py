import asyncio
import aiofiles
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Set
from pathlib import Path
from collections import deque
import json
from spade.message import Message
from ..jade_migration.asyncio_singleton import AsyncioSingleton

@dataclass
class MessageLogEntry:
    """Single message log entry matching JADE format"""
    timestamp: datetime
    agent: str
    agent_action: str  # SEND or RECEIVE
    sender: str
    receivers: str
    performative: str
    conversation_id: str
    content: str
    sequence_id: int

    def to_csv_row(self) -> str:
        """Convert to CSV row format matching JADE logger"""
        timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # Truncate to milliseconds
        
        # Escape quotes in content
        escaped_content = self.content.replace('"', '""')
        
        return (f'{timestamp_str},{self.agent},{self.agent_action},{self.sender},'
                f'{self.receivers},{self.performative},{self.conversation_id},'
                f'"{escaped_content}",{self.sequence_id}')

class AgentMessageLogger(metaclass=AsyncioSingleton):
    """
    SPADE equivalent of JADE's AgentMessageLogger
    Provides singleton message logging with async file operations
    """
    
    def __init__(self):
        self._log_queue: deque = deque()
        self._is_running: bool = False
        self._sequence_counter: int = 0
        self._log_path: Optional[Path] = None
        self._writer_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
    
    async def start(self, scenario: str) -> None:
        """Start the message logger for given scenario"""
        if self._is_running:
            return
            
        try:
            # Create output directory
            output_path = Path("agent_output") / "message_logs" / scenario
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Create log file with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_path = output_path / f"agent_messages_{scenario}_{timestamp}.csv"
            
            # Write CSV headers
            headers = "timestamp,agent,agentAction,sender,receivers,performative,conversationId,content,sequenceId\n"
            async with aiofiles.open(self._log_path, 'w') as f:
                await f.write(headers)
            
            # Start background writer
            self._is_running = True
            self._writer_task = asyncio.create_task(self._background_writer())
            
            print(f"SPADE Message Logger started for scenario: {scenario}")
            
        except Exception as e:
            print(f"Error starting SPADE Message Logger: {e}")
            self._is_running = False
            raise
    
    async def stop(self) -> None:
        """Stop the message logger"""
        async with self._lock:
            if not self._is_running:
                return
                
            self._is_running = False
            
            # Cancel writer task and flush remaining entries
            if self._writer_task:
                self._writer_task.cancel()
                try:
                    await self._writer_task
                except asyncio.CancelledError:
                    pass
            
            await self._flush_remaining_entries()
            print("SPADE Message Logger stopped")
    
    async def log_message_sent(self, agent_name: str, message: Message) -> None:
        """Log a message being sent"""
        if not self._is_running:
            return
        
        # Extract receiver(s) - SPADE messages typically have one receiver
        receivers = str(message.to) if message.to else ""
        
        # Truncate content to match JADE behavior (first 100 chars)
        content = str(message.body)[:100] if message.body else ""
        
        entry = MessageLogEntry(
            timestamp=datetime.now(),
            agent=agent_name,
            agent_action="SEND",
            sender=agent_name,
            receivers=receivers,
            performative=message.get_metadata("performative") or "UNKNOWN",
            conversation_id=message.get_metadata("conversation-id") or "",
            content=content,
            sequence_id=self._get_next_sequence_id()
        )
        
        self._log_queue.append(entry)
    
    async def log_message_received(self, agent_name: str, message: Message) -> None:
        """Log a message being received"""
        if not self._is_running:
            return
        
        # Extract sender
        sender = str(message.sender) if message.sender else "UNKNOWN"
        
        # Truncate content to match JADE behavior
        content = str(message.body)[:100] if message.body else ""
        
        entry = MessageLogEntry(
            timestamp=datetime.now(),
            agent=agent_name,
            agent_action="RECEIVE",
            sender=sender,
            receivers=agent_name,
            performative=message.get_metadata("performative") or "UNKNOWN",
            conversation_id=message.get_metadata("conversation-id") or "",
            content=content,
            sequence_id=self._get_next_sequence_id()
        )
        
        self._log_queue.append(entry)
    
    def _get_next_sequence_id(self) -> int:
        """Get next sequence ID (thread-safe)"""
        self._sequence_counter += 1
        return self._sequence_counter
    
    async def _background_writer(self) -> None:
        """Background task to write log entries to file"""
        try:
            while self._is_running or self._log_queue:
                if not self._log_queue:
                    await asyncio.sleep(0.1)
                    continue
                
                # Process entries in batches for efficiency
                batch = []
                for _ in range(min(100, len(self._log_queue))):  # Process up to 100 entries at once
                    if self._log_queue:
                        batch.append(self._log_queue.popleft())
                
                if batch:
                    await self._write_batch(batch)
                    
        except asyncio.CancelledError:
            # Write remaining entries before cancellation
            await self._flush_remaining_entries()
            raise
        except Exception as e:
            print(f"Error in message logger background writer: {e}")
    
    async def _write_batch(self, entries: list) -> None:
        """Write a batch of entries to file"""
        if not entries or not self._log_path:
            return
            
        try:
            async with self._write_lock:
                batch_content = "\n".join(entry.to_csv_row() for entry in entries) + "\n"
                async with aiofiles.open(self._log_path, 'a') as f:
                    await f.write(batch_content)
        except Exception as e:
            print(f"Error writing message log batch: {e}")
    
    async def _flush_remaining_entries(self) -> None:
        """Flush any remaining entries in the queue"""
        if not self._log_queue:
            return
            
        try:
            remaining_entries = list(self._log_queue)
            self._log_queue.clear()
            await self._write_batch(remaining_entries)
        except Exception as e:
            print(f"Error flushing remaining message logs: {e}")