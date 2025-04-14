import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
import asyncio
import aiofiles
import json
from pathlib import Path
import statistics

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

class RTTLogger:
    def __init__(self, agent_name: str, scenario_name: str):
        """Initialize the RTT logger"""
        self.agent_name = agent_name
        self._pending_requests: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._write_queue = asyncio.Queue()
        
        # Set up output directory and file with fixed name
        self._output_path = Path("agent_output/rtt_logs")
        self._output_path.mkdir(parents=True, exist_ok=True)
        self._csv_path = self._output_path / f"rtt_measurements_{scenario_name}.csv"
        
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
        
    async def stop(self):
        """Stop the logger and cleanup"""
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            
    async def start_request(self, conversation_id: str,
                           performative: str,
                           receiver: str,
                           additional_info: Dict = None,
                           ontology: str = "NOT-SPECIFIED") -> None:
        """Record start of a request with precise timing"""
        async with self._lock:
            self._pending_requests[conversation_id] = {
                'start_time': time.perf_counter_ns(),  # Use perf_counter for precise timing
                'performative': performative,
                'receiver': receiver,
                'additional_info': additional_info
            }
            
    async def end_request(self,
                         conversation_id: str,
                         response_performative: str = None,
                         message_size: int = 0,
                         success: bool = True,
                         extra_info: Dict = None,
                         ontology: str = "NOT-SPECIFIED") -> Optional[float]:
        """Record end of a request and calculate RTT accurately"""
        async with self._lock:
            request_data = self._pending_requests.get(conversation_id)
            if not request_data:
                return None
                
            # Calculate RTT in milliseconds using perf_counter
            end_time_ns = time.perf_counter_ns()
            start_time_ns = request_data['start_time']
            rtt = (end_time_ns - start_time_ns) / 1_000_000  # Convert ns to ms
            
            # Combine additional info
            additional_info = request_data.get('additional_info', {})
            if extra_info:
                additional_info.update(extra_info)
            
            # Create measurement
            measurement = RTTMeasurement(
                timestamp=datetime.now(),  # Wall clock time for logging
                sender=self.agent_name,
                receiver=request_data['receiver'],
                conversation_id=conversation_id,
                performative=response_performative,
                rtt=rtt,
                message_size=message_size,
                success=success,
                additional_info=additional_info,
                ontology=ontology
            )
            
            # Queue measurement for writing
            await self._write_queue.put(measurement)
            
            del self._pending_requests[conversation_id]
            return rtt
            
    async def _background_writer(self):
        """Background task to write measurements to CSV"""
        try:
            while True:
                measurement = await self._write_queue.get()
                try:
                    async with aiofiles.open(self._csv_path, mode='a', newline='') as f:
                        row = ','.join(measurement.to_csv_row()) + '\n'
                        await f.write(row)
                except Exception as e:
                    print(f"Error writing RTT measurement: {e}")
                finally:
                    self._write_queue.task_done()
                    
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
