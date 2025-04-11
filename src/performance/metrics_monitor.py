import psutil
import time
import csv
import os
from datetime import datetime
import asyncio
from typing import Dict, List, Optional, Deque
from collections import deque
from asyncio import Lock
import aiofiles

class MetricsMonitor:
    def __init__(self, output_file: str = "mas_metrics.csv", request_log_file: str = "request_metrics.csv",
                 flush_interval: int = 30, buffer_size: int = 1000, scenario: str = "small"):
        self.output_file = os.path.join("agent_output", scenario, output_file)
        self.request_log_file = os.path.join("agent_output", scenario, request_log_file)
        self.scenario = scenario
        self.flush_interval = flush_interval
        self.buffer_size = buffer_size
        self.write_lock = Lock()
        
        # Use deques for better performance with fixed size
        self.metrics_buffer: Deque[Dict] = deque(maxlen=buffer_size)
        self.request_buffer: Deque[Dict] = deque(maxlen=buffer_size)
        
        # Metrics storage (in-memory)
        self.rtt_measurements: Deque[float] = deque(maxlen=1000)
        self.df_measurements: Deque[float] = deque(maxlen=1000)
        self.cpu_measurements: Deque[float] = deque(maxlen=1000)
        self.negotiation_times: Dict[str, List[float]] = {}
        self.current_negotiations: Dict[str, float] = {}

        # Initialize files if they don't exist
        self._initialize_files()
        
        # Start periodic flush task
        self.flush_task = None
        self.is_running = False

    def _initialize_files(self):
        """Initialize CSV files with headers if they don't exist"""
        if not os.path.exists(self.request_log_file):
            with open(self.request_log_file, 'w') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'request_id', 'agent_id', 'action_type',
                    'start_time', 'end_time', 'duration', 'status', 'details'
                ])
                
        if not os.path.exists(self.output_file):
            with open(self.output_file, 'w') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'rtt_avg', 'rtt_max', 
                    'df_avg', 'cpu_avg', 'cpu_max'
                ])

    async def start(self):
        """Start the metrics monitor and periodic flush"""
        if not self.is_running:
            self.is_running = True
            self.flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """Stop the metrics monitor and flush remaining data"""
        if self.is_running:
            self.is_running = False
            if self.flush_task:
                self.flush_task.cancel()
                try:
                    await self.flush_task
                except asyncio.CancelledError:
                    pass
            # Final flush
            await self._flush_all()

    def measure_rtt(self, agent_id: str, start_time: float, end_time: float):
        """Non-blocking RTT measurement"""
        rtt = end_time - start_time
        self.rtt_measurements.append(rtt)
        # Schedule metrics update without waiting
        asyncio.create_task(self._schedule_metrics_update())
        return rtt
        
    def measure_df_response(self, num_requests: int, total_time: float):
        """Non-blocking DF response measurement"""
        df_time = total_time / num_requests
        self.df_measurements.append(df_time)
        asyncio.create_task(self._schedule_metrics_update())
        return df_time
        
    def measure_cpu_usage(self):
        """Non-blocking CPU measurement"""
        cpu_percent = psutil.cpu_percent(interval=0.1)  # Reduced interval
        self.cpu_measurements.append(cpu_percent)
        asyncio.create_task(self._schedule_metrics_update())
        return cpu_percent
        
    def start_negotiation(self, professor_id: str, subject_name: str):
        """Start tracking a negotiation process"""
        key = f"{professor_id}_{subject_name}"
        self.current_negotiations[key] = time.time()
        
    async def end_negotiation(self, professor_id: str, subject_name: str):
        """End tracking a negotiation process"""
        key = f"{professor_id}_{subject_name}"
        if key in self.current_negotiations:
            start_time = self.current_negotiations[key]
            end_time = time.time()
            duration = end_time - start_time
            
            if key not in self.negotiation_times:
                self.negotiation_times[key] = []
            self.negotiation_times[key].append(duration)
            
            # Schedule log write without waiting
            asyncio.create_task(self._schedule_request_log(
                agent_id=professor_id,
                action_type="negotiation",
                start_time=start_time,
                end_time=end_time,
                details=f"Subject: {subject_name}"
            ))
            
            del self.current_negotiations[key]
            return duration
        return None

    async def log_request(self, agent_id: str, action_type: str,
                         start_time: float, end_time: float,
                         status: str = "completed", details: str = ""):
        """Non-blocking request logging"""
        # Schedule log write without waiting
        asyncio.create_task(self._schedule_request_log(
            agent_id=agent_id,
            action_type=action_type,
            start_time=start_time,
            end_time=end_time,
            status=status,
            details=details
        ))

    async def _schedule_request_log(self, **kwargs):
        """Add request log to buffer"""
        duration = kwargs['end_time'] - kwargs['start_time']
        request_id = f"{kwargs['agent_id']}_{int(kwargs['start_time'] * 1000)}"
        
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'request_id': request_id,
            'agent_id': kwargs['agent_id'],
            'action_type': kwargs['action_type'],
            'start_time': f"{kwargs['start_time']:.6f}",
            'end_time': f"{kwargs['end_time']:.6f}",
            'duration': f"{duration:.6f}",
            'status': kwargs['status'],
            'details': kwargs['details'].replace('"', "'")
        }
        
        self.request_buffer.append(log_entry)
        
        # Flush if buffer is full
        if len(self.request_buffer) >= self.buffer_size:
            asyncio.create_task(self._flush_requests())

    async def _schedule_metrics_update(self):
        """Add metrics update to buffer"""
        if not self.rtt_measurements and not self.df_measurements and not self.cpu_measurements:
            return
            
        metrics = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'rtt_avg': f"{sum(self.rtt_measurements)/len(self.rtt_measurements):.6f}" if self.rtt_measurements else "0.0",
            'rtt_max': f"{max(self.rtt_measurements):.6f}" if self.rtt_measurements else "0.0",
            'df_avg': f"{sum(self.df_measurements)/len(self.df_measurements):.6f}" if self.df_measurements else "0.0",
            'cpu_avg': f"{sum(self.cpu_measurements)/len(self.cpu_measurements):.6f}" if self.cpu_measurements else "0.0",
            'cpu_max': f"{max(self.cpu_measurements):.6f}" if self.cpu_measurements else "0.0"
        }
        
        self.metrics_buffer.append(metrics)
        
        # Flush if buffer is full
        if len(self.metrics_buffer) >= self.buffer_size:
            asyncio.create_task(self._flush_metrics())

    async def _periodic_flush(self):
        """Periodically flush buffers to files"""
        while self.is_running:
            await asyncio.sleep(self.flush_interval)
            await self._flush_all()

    async def _flush_all(self):
        """Flush all buffers to files"""
        await self._flush_metrics()
        await self._flush_requests()

    async def _flush_metrics(self):
        """Flush metrics buffer to file"""
        if not self.metrics_buffer:
            return
            
        metrics_to_write = list(self.metrics_buffer)
        self.metrics_buffer.clear()
        
        try:
            async with self.write_lock:
                async with asyncio.timeout(5):  # 5 second timeout
                    async with aiofiles.open(self.output_file, mode='a') as f:
                        for metrics in metrics_to_write:
                            csv_line = (
                                f"{metrics['timestamp']},"
                                f"{metrics['rtt_avg']},"
                                f"{metrics['rtt_max']},"
                                f"{metrics['df_avg']},"
                                f"{metrics['cpu_avg']},"
                                f"{metrics['cpu_max']}\n"
                            )
                            await f.write(csv_line)
        except Exception as e:
            print(f"Error flushing metrics: {str(e)}")

    async def _flush_requests(self):
        """Flush request buffer to file"""
        if not self.request_buffer:
            return
            
        requests_to_write = list(self.request_buffer)
        self.request_buffer.clear()
        
        try:
            async with self.write_lock:
                async with asyncio.timeout(5):  # 5 second timeout
                    async with aiofiles.open(self.request_log_file, mode='a') as f:
                        for request in requests_to_write:
                            csv_line = (
                                f"{request['timestamp']},"
                                f"{request['request_id']},"
                                f"{request['agent_id']},"
                                f"{request['action_type']},"
                                f"{request['start_time']},"
                                f"{request['end_time']},"
                                f"{request['duration']},"
                                f"{request['status']},"
                                f"\"{request['details']}\"\n"
                            )
                            await f.write(csv_line)
        except Exception as e:
            print(f"Error flushing requests: {str(e)}")

    def generate_summary(self) -> Dict:
        """Generate summary statistics"""
        return {
            'rtt': self._calculate_stats(list(self.rtt_measurements)),
            'df': self._calculate_stats(list(self.df_measurements)), 
            'cpu': self._calculate_stats(list(self.cpu_measurements)),
            'negotiations': {
                key: self._calculate_stats(times)
                for key, times in self.negotiation_times.items()
            }
        }
    
    def _calculate_stats(self, data: List[float]) -> Dict:
        """Calculate statistics from data"""
        if not data:
            return {'avg': 0, 'max': 0, 'min': 0, 'count': 0}
        return {
            'avg': sum(data)/len(data),
            'max': max(data),
            'min': min(data),
            'count': len(data)
        }