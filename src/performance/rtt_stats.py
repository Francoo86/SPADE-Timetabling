import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
import asyncio
import aiofiles
import json
from pathlib import Path
import statistics

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
import asyncio
import aiofiles
from pathlib import Path
from src.jade_migration.asyncio_singleton import AsyncioSingleton

@dataclass
class RTTMeasurement:
    """Single RTT measurement with metadata"""
    timestamp: datetime
    sender: str
    receiver: str
    conversation_id: str
    performative: str
    rtt: float  # in milliseconds
    message_size: int
    success: bool
    additional_info: Dict = None
    ontology: str = "NOT-SPECIFIED"

    def to_csv_row(self) -> list:
        return [
            self.timestamp.isoformat(),
            self.sender,
            self.receiver,
            self.conversation_id,
            self.performative,
            f"{self.rtt:.3f}",  # 3 decimal places for ms
            str(self.message_size),
            str(self.success),
            json.dumps(self.additional_info) if self.additional_info else "",
            self.ontology
        ]

class RTTLogger(metaclass=AsyncioSingleton):                
    def __init__(self, scenario_name: str):
        self._pending_requests: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._write_queue = asyncio.Queue()
        
        # Set up output directory and file
        self._output_path = Path("agent_output/rtt_logs") / scenario_name
        self._output_path.mkdir(parents=True, exist_ok=True)
        
        # Create a unique filename based on current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._csv_path = self._output_path / f"rtt_measurements_{scenario_name}_{timestamp}.csv"
        
        # For tracking all outgoing messages, not just those with start_request
        self._all_outgoing_messages: Dict[str, dict] = {}
        
        # better lock system
        self._pending_requests_lock = asyncio.Lock()
        self._all_outgoing_messages_lock = asyncio.Lock()
        self._queue_lock = asyncio.Lock()
        
        self._writer_task = None
        self._cleanup_task = None
        
    async def start(self):
        """Initialize the logger and start background writer"""
        # Write headers only if file doesn't exist
        if not self._csv_path.exists():
            async with aiofiles.open(self._csv_path, mode='w', newline='') as f:
                headers = [
                    "Timestamp", "Sender", "Receiver", "ConversationID",
                    "Performative", "RTT_ms", "MessageSize_bytes", "Success",
                    "AdditionalInfo", "Ontology"
                ]
                await f.write(','.join(headers) + '\n')
        
        # Start background writer
        self._writer_task = asyncio.create_task(self._background_writer())
        
        # Start cleanup task for stale entries
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_entries())
        
    async def stop(self):
        """Stop the logger and cleanup"""
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
                
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            
    async def start_request(self, 
                        agent_name: str,
                        conversation_id: str,
                        performative: str,
                        receiver: str,
                        additional_info: Dict = None,
                        ontology: str = "NOT-SPECIFIED") -> None:
        # For CFP to multiple classrooms, add a way to track expected response count
        if not conversation_id:
            print(f"Warning: Empty conversation_id in start_request from {agent_name}")
            return
            
        start_data = {
            'start_time': time.perf_counter_ns(),
            'start_time_wall': time.time(),
            'performative': performative,
            'receiver': receiver,
            'additional_info': additional_info,
            'ontology': ontology,
            'expected_responses': additional_info.get('expected_responses', 1) if additional_info else 1,
            'responses_received': 0
        }
        
        # Use the appropriate lock
        async with self._pending_requests_lock:
            self._pending_requests[conversation_id] = start_data
        
        async with self._all_outgoing_messages_lock:
            self._all_outgoing_messages[conversation_id] = start_data
            
        # print(f"DEBUG: {agent_name} starting request {conversation_id} to {receiver}")
            
    async def record_message_sent(self, agent_name: str, conversation_id: str, 
                               performative: str, 
                               receiver: str,
                               ontology: str = "NOT-SPECIFIED") -> None:
        """Record any outgoing message, even without formal start_request"""
        if not conversation_id:
            print(f"Warning: Empty conversation_id in record_message_sent from {agent_name}")
            return
            
        async with self._lock:
            # Only record if not already tracked by start_request
            if conversation_id not in self._all_outgoing_messages:
                self._all_outgoing_messages[conversation_id] = {
                    'start_time': time.perf_counter_ns(),
                    'start_time_wall': time.time(),
                    'performative': performative,
                    'receiver': receiver,
                    'ontology': ontology
                }
                # print(f"DEBUG: {agent_name} recording message {conversation_id} to {receiver}")
            
    async def record_message_received(self, agent_name: str, conversation_id: str, 
                                performative: str,
                                sender: str,
                                message_size: int = 0,
                                ontology: str = "NOT-SPECIFIED") -> None:
        if not conversation_id:
            print(f"Warning: Empty conversation_id in record_message_received from {agent_name}")
            return
            
        # First, quickly check if message exists without holding the main lock
        outgoing_exists = False
        async with self._all_outgoing_messages_lock:
            outgoing_exists = conversation_id in self._all_outgoing_messages
            if outgoing_exists:
                outgoing_data = self._all_outgoing_messages[conversation_id].copy()  # Make a copy to reduce lock time
        
        if outgoing_exists:
            # Process measurement without holding lock
            end_time_ns = time.perf_counter_ns()
            start_time_ns = outgoing_data['start_time']
            rtt = (end_time_ns - start_time_ns) / 1_000_000
            
            # Create measurement
            measurement = RTTMeasurement(
                timestamp=datetime.now(),
                sender=agent_name,
                receiver=sender,
                conversation_id=conversation_id,
                performative=performative,
                rtt=rtt,
                message_size=message_size,
                success=True,
                ontology=outgoing_data.get('ontology', ontology)
            )
            
            # Queue for writing (using a separate lock if needed)
            async with self._queue_lock:
                await self._write_queue.put(measurement)
                
            # print(f"DEBUG: {agent_name} received response for {conversation_id} from {sender}, RTT={rtt:.3f}ms")
            pass
        else:
            # print(f"DEBUG: {agent_name} received message {conversation_id} from {sender} with no matching sent message")
            pass
                
    async def end_request(self,
                         agent_name: str,
                         conversation_id: str,
                         response_performative: str = None,
                         message_size: int = 0,
                         success: bool = True,
                         extra_info: Dict = None,
                         ontology: str = "NOT-SPECIFIED") -> Optional[float]:
        """Record end of a request and calculate RTT accurately"""
        if not conversation_id:
            print(f"Warning: Empty conversation_id in end_request from {agent_name}")
            return None
            
        async with self._lock:
            # First check _pending_requests (formal requests)
            request_data = self._pending_requests.get(conversation_id)
            
            if not request_data:
                # Then check _all_outgoing_messages (informal tracking)
                request_data = self._all_outgoing_messages.get(conversation_id)
                
            if request_data:
                end_time_ns = time.perf_counter_ns()
                start_time_ns = request_data['start_time']
                rtt = (end_time_ns - start_time_ns) / 1_000_000
                
                # Combine additional info
                additional_info = request_data.get('additional_info', {}) or {}
                if extra_info:
                    additional_info.update(extra_info)
                
                # Create measurement
                measurement = RTTMeasurement(
                    timestamp=datetime.now(),
                    sender=agent_name,
                    receiver=request_data['receiver'],
                    conversation_id=conversation_id,
                    performative=response_performative or request_data['performative'],
                    rtt=rtt,
                    message_size=message_size,
                    success=success,
                    additional_info=additional_info,
                    ontology=ontology or request_data.get('ontology', "NOT-SPECIFIED")
                )
                
                # Queue measurement for writing
                await self._write_queue.put(measurement)
                
                # Remove from _pending_requests but keep in _all_outgoing_messages for multiple responses
                if conversation_id in self._pending_requests:
                    del self._pending_requests[conversation_id]
                
                return rtt
            else:
                # print(f"Warning: No request data found for conversation_id {conversation_id} in end_request")
                return None
            
    async def _cleanup_stale_entries(self):
        """Background task to clean up stale entries"""
        STALE_THRESHOLD_SECONDS = 60  # Consider entries stale after 60s
        
        try:
            while True:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                async with self._lock:
                    now = time.time()
                    stale_convs = []
                    
                    # Check for stale entries in pending requests
                    for conv_id, data in self._pending_requests.items():
                        if now - data.get('start_time_wall', 0) > STALE_THRESHOLD_SECONDS:
                            # agent_name = data.get('agent_name', "UNKNOWN")
                            stale_convs.append(conv_id)
                            # print(f"DEBUG: Removing stale request {conv_id} from {agent_name}")
                    
                    # Remove the stale entries
                    for conv_id in stale_convs:
                        del self._pending_requests[conv_id]
                        
                    # Also clean up very old entries from _all_outgoing_messages
                    all_outgoing_stale = []
                    for conv_id, data in self._all_outgoing_messages.items():
                        if now - data.get('start_time_wall', 0) > STALE_THRESHOLD_SECONDS * 2:  # Double timeout
                            all_outgoing_stale.append(conv_id)
                    
                    for conv_id in all_outgoing_stale:
                        del self._all_outgoing_messages[conv_id]
                        
        except asyncio.CancelledError:
            # Normal cancellation during shutdown
            return
            
    async def _background_writer(self):
        """Background task to write measurements to CSV with batching"""
        try:
            while True:
                # Process in small batches to handle bursts more efficiently
                batch = []
                for _ in range(min(50, self._write_queue.qsize())):
                    try:
                        measurement = self._write_queue.get_nowait()
                        batch.append(measurement)
                    except asyncio.QueueEmpty:
                        break
                        
                if not batch and not self._write_queue.empty():
                    measurement = await self._write_queue.get()
                    batch.append(measurement)
                    
                if batch:
                    try:
                        async with aiofiles.open(self._csv_path, mode='a', newline='') as f:
                            rows = [','.join(m.to_csv_row()) + '\n' for m in batch]
                            await f.write(''.join(rows))
                    except Exception as e:
                        print(f"Error writing RTT measurements batch: {e}")
                    finally:
                        for _ in range(len(batch)):
                            self._write_queue.task_done()
                else:
                    # If no batch was formed, wait a bit
                    await asyncio.sleep(0.01) 
        except asyncio.CancelledError:
            # Flush remaining measurements
            while not self._write_queue.empty():
                try:
                    measurement = self._write_queue.get_nowait()
                    async with aiofiles.open(self._csv_path, mode='a', newline='') as f:
                        row = ','.join(measurement.to_csv_row()) + '\n'
                        await f.write(row)
                except:
                    break
                    
    async def get_statistics(self) -> Dict:
        """Calculate RTT statistics"""
        async with self._lock:
            all_rtts = [m.rtt for m in self._measurements]
            if not all_rtts:
                return {}
                
            return {
                "count": len(all_rtts),
                "min": min(all_rtts),
                "max": max(all_rtts),
                "mean": statistics.mean(all_rtts),
                "median": statistics.median(all_rtts),
                "stdev": statistics.stdev(all_rtts) if len(all_rtts) > 1 else 0
            }
