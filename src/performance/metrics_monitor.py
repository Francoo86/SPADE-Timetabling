import psutil
import time
import csv
from datetime import datetime
import asyncio
from typing import Dict, List, Optional
import pandas as pd

class MetricsMonitor:
    def __init__(self, output_file: str = "mas_metrics.csv", request_log_file: str = "request_metrics.csv"):
        self.output_file = output_file
        self.request_log_file = request_log_file
        self.rtt_measurements: List[float] = []
        self.df_measurements: List[float] = []
        self.cpu_measurements: List[float] = []
        self.negotiation_times: Dict[str, List[float]] = {}
        self.current_negotiations: Dict[str, float] = {}
        
        # Initialize request log file with headers
        with open(request_log_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp',
                'request_id',
                'agent_id',
                'action_type',
                'start_time',
                'end_time',
                'duration',
                'status',
                'details'
            ])
        
    async def measure_rtt(self, agent_id: str, start_time: float, end_time: float):
        """Measure Round Trip Time for message exchange"""
        rtt = end_time - start_time
        self.rtt_measurements.append(rtt)
        await self._save_metrics()
        return rtt
        
    async def measure_df_response(self, num_requests: int, total_time: float):
        """Measure Directory Facilitator response time"""
        df_time = total_time / num_requests
        self.df_measurements.append(df_time)
        await self._save_metrics()
        return df_time
        
    async def measure_cpu_usage(self):
        """Measure CPU usage percentage"""
        cpu_percent = psutil.cpu_percent(interval=1)
        self.cpu_measurements.append(cpu_percent)
        await self._save_metrics()
        return cpu_percent
        
    def start_negotiation(self, professor_id: str, subject_name: str):
        """Start timing a negotiation process"""
        key = f"{professor_id}_{subject_name}"
        self.current_negotiations[key] = time.time()
        
    def end_negotiation(self, professor_id: str, subject_name: str):
        """End timing a negotiation process"""
        key = f"{professor_id}_{subject_name}"
        if key in self.current_negotiations:
            start_time = self.current_negotiations[key]
            duration = time.time() - start_time
            
            if key not in self.negotiation_times:
                self.negotiation_times[key] = []
            self.negotiation_times[key].append(duration)
            
            del self.current_negotiations[key]
            return duration
        return None

    async def log_request(self, 
                         agent_id: str,
                         action_type: str,
                         start_time: float,
                         end_time: float,
                         status: str = "completed",
                         details: str = ""):
        """Log individual request metrics"""
        duration = end_time - start_time
        request_id = f"{agent_id}_{int(start_time * 1000)}"
        
        log_entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'request_id': request_id,
            'agent_id': agent_id,
            'action_type': action_type,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'status': status,
            'details': details
        }
        
        # Save to request log file
        with open(self.request_log_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=log_entry.keys())
            writer.writerow(log_entry)
            
        return log_entry
            
    async def _save_metrics(self):
        """Save metrics to CSV file"""
        try:
            data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rtt_avg': sum(self.rtt_measurements) / len(self.rtt_measurements) if self.rtt_measurements else 0,
                'rtt_max': max(self.rtt_measurements) if self.rtt_measurements else 0,
                'df_avg': sum(self.df_measurements) / len(self.df_measurements) if self.df_measurements else 0,
                'cpu_avg': sum(self.cpu_measurements) / len(self.cpu_measurements) if self.cpu_measurements else 0,
                'cpu_max': max(self.cpu_measurements) if self.cpu_measurements else 0
            }
            
            # Add negotiation times
            for key, times in self.negotiation_times.items():
                data[f'neg_avg_{key}'] = sum(times) / len(times) if times else 0
                data[f'neg_max_{key}'] = max(times) if times else 0

            # Convert to DataFrame and save
            df = pd.DataFrame([data])
            df.to_csv(self.output_file, mode='a', header=not pd.io.common.file_exists(self.output_file), index=False)

        except Exception as e:
            print(f"Error saving metrics: {str(e)}")
            
    def generate_summary(self) -> Dict:
        """Generate summary statistics of all metrics"""
        return {
            'rtt': {
                'avg': sum(self.rtt_measurements) / len(self.rtt_measurements) if self.rtt_measurements else 0,
                'max': max(self.rtt_measurements) if self.rtt_measurements else 0,
                'min': min(self.rtt_measurements) if self.rtt_measurements else 0,
                'count': len(self.rtt_measurements)
            },
            'df': {
                'avg': sum(self.df_measurements) / len(self.df_measurements) if self.df_measurements else 0,
                'max': max(self.df_measurements) if self.df_measurements else 0,
                'min': min(self.df_measurements) if self.df_measurements else 0,
                'count': len(self.df_measurements)
            },
            'cpu': {
                'avg': sum(self.cpu_measurements) / len(self.cpu_measurements) if self.cpu_measurements else 0,
                'max': max(self.cpu_measurements) if self.cpu_measurements else 0,
                'min': min(self.cpu_measurements) if self.cpu_measurements else 0,
                'count': len(self.cpu_measurements)
            },
            'negotiations': {
                key: {
                    'avg': sum(times) / len(times) if times else 0,
                    'max': max(times) if times else 0,
                    'min': min(times) if times else 0,
                    'count': len(times)
                }
                for key, times in self.negotiation_times.items()
            }
        }

# Tracking context manager for easy request timing
class RequestTimer:
    def __init__(self, metrics_monitor, agent_id: str, action_type: str, details: str = ""):
        self.metrics_monitor = metrics_monitor
        self.agent_id = agent_id
        self.action_type = action_type
        self.details = details
        self.start_time = None
        self.status = "completed"
        
    def set_status(self, status: str):
        self.status = status
        
    def set_details(self, details: str):
        self.details = details
        
    async def __aenter__(self):
        self.start_time = time.time()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        end_time = time.time()
        await self.metrics_monitor.log_request(
            self.agent_id,
            self.action_type,
            self.start_time,
            end_time,
            self.status,
            self.details
        )
