from dataclasses import dataclass
import csv
from datetime import datetime
from typing import Dict, Optional, List
import statistics
import asyncio
from pathlib import Path
import aiofiles
import json
import os

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

    def to_csv_row(self) -> List[str]:
        """Convert measurement to CSV row"""
        return [
            self.timestamp.isoformat(),
            self.sender,
            self.receiver,
            self.conversation_id,
            self.performative,
            f"{self.rtt:.2f}",
            str(self.message_size),
            str(self.success),
            json.dumps(self.additional_info) if self.additional_info else "",
            self.ontology
        ]

    @staticmethod
    def get_csv_headers() -> List[str]:
        """Get CSV header row"""
        return [
            "Timestamp",
            "Sender",
            "Receiver", 
            "ConversationID",
            "Performative",
            "RTT_ms",
            "MessageSize_bytes",
            "Success",
            "AdditionalInfo",
            "Ontology"
        ]

class RTTLogger:
    """Asynchronous RTT logging system with CSV output"""
    _shared_csv_path = Path("agent_output/rtt_logs") / f"rtt_measurements_{datetime.now().strftime('%Y%m%d_%H-%M-%S')}.csv"
    _shared_lock = asyncio.Lock()  # Class-level lock for file access
    _is_initialized = False  # Class-level flag to track header writing
    
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self._measurements: List[RTTMeasurement] = []
        self._lock = asyncio.Lock()
        self._pending_requests: Dict[str, dict] = {}
        self._write_queue = asyncio.Queue()
        
        self._shared_csv_path.parent.mkdir(parents=True, exist_ok=True)
        # self._output_path = Path("agent_output/rtt_logs")
        # self._output_path.mkdir(parents=True, exist_ok=True)
        #self._csv_path = self._output_path / f"rtt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Start background writer task
        self._writer_task = None
        
    async def start(self):
        """Start the logging system"""
        # Initialize CSV file with headers if not already done
        async with RTTLogger._shared_lock:
            if not RTTLogger._is_initialized:
                async with aiofiles.open(self._shared_csv_path, mode='w', newline='') as f:
                    await f.write(','.join(RTTMeasurement.get_csv_headers()) + '\n')
                RTTLogger._is_initialized = True
                
        # Start background writer
        self._writer_task = asyncio.create_task(self._background_writer())
        
    async def stop(self):
        """Stop the logging system"""
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            
    async def start_request(self, 
                           conversation_id: str,
                           performative: str,
                           receiver: str,
                           additional_info: Dict = None,
                           ontology : str = "NOT-SPECIFIED") -> None:
        """Record start of a request with metadata"""
        async with self._lock:
            conv_onto = conversation_id + ontology
            self._pending_requests[conv_onto] = {
                'start_time': datetime.now(),
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
                         ontology : str = "NOT-SPECIFIED") -> Optional[float]:
        """Record end of a request and calculate RTT"""
        async with self._lock:
            conv_onto = conversation_id + ontology
            request_data = self._pending_requests.get(conv_onto)
            if not request_data:
                return None
                
            end_time = datetime.now()
            start_time = request_data['start_time']
            rtt = (end_time - start_time).total_seconds() * 1000
            
            # Combine additional info
            additional_info = request_data.get('additional_info', {})
            if extra_info and additional_info is not None:
                additional_info.update(extra_info)
            
            # Create measurement
            measurement = RTTMeasurement(
                timestamp=end_time,
                sender=self.agent_name,
                receiver=request_data['receiver'],
                conversation_id=conversation_id,
                performative=request_data['performative'],  # <--- Usar el performative original
                rtt=rtt,
                message_size=message_size,
                success=success,
                additional_info={
                    "response_performative": response_performative,  # <--- Respuesta como metadato
                    **(extra_info if extra_info else {})
                },
                ontology=ontology
            )
            
            # Queue for writing
            await self._write_queue.put(measurement)
            
            conv_onto = conversation_id + ontology
            
            del self._pending_requests[conv_onto]
            return rtt
            
    async def _background_writer(self):
        """Background task to write measurements to CSV"""
        try:
            while True:
                measurement = await self._write_queue.get()
                try:
                    async with RTTLogger._shared_lock:
                        async with aiofiles.open(self._shared_csv_path, mode='a', newline='') as f:
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
