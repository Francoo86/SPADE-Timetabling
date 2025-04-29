import asyncio
import os
import time
import psutil
import gc
from datetime import datetime
from pathlib import Path
import csv
import logging
from typing import Dict, List, Optional

class CentralizedPerformanceMonitor:
    """
    A lightweight centralized monitor for tracking CPU and memory usage across multiple agents
    without causing significant performance overhead.
    """
    
    # Shared lock and file path for all instances
    _lock = asyncio.Lock()
    _initialized = False
    _csv_path = None
    _base_path = Path("agent_output/PerformanceLogs/")
    
    @classmethod
    async def initialize(cls, scenario: str):
        """Initialize the shared CSV file for all monitors"""
        async with cls._lock:
            if cls._initialized:
                return
                
            # Create directory
            output_dir = cls._base_path / scenario
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Set CSV path
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cls._csv_path = output_dir / f"agent_metrics_{scenario}_{timestamp}.csv"
            
            # Create CSV with headers
            with open(cls._csv_path, 'w', newline='') as f:
                csv_writer = csv.writer(f)
                csv_writer.writerow([
                    "Timestamp", 
                    "AgentID",
                    "AgentType",
                    "CPU_Percent", 
                    "Memory_RSS_MB", 
                    "Memory_VMS_MB", 
                    "Memory_Percent",
                    "Num_Threads",
                    "Num_Tasks"
                ])
                
            cls._initialized = True
            logging.info(f"Initialized centralized performance monitoring for scenario: {scenario}")
    
    def __init__(self, agent_identifier: str, agent_type: str, scenario: str):
        """
        Initialize a monitor instance for a specific agent.
        
        Args:
            agent_identifier: ID of the agent being monitored
            agent_type: Type of agent (Professor, Sala, Supervisor, etc.)
            scenario: Scenario name for grouping results
        """
        self.agent_id = agent_identifier
        self.agent_type = agent_type
        self.scenario = scenario
        self.monitoring_interval = 5.0  # 5 seconds default
        self.process = psutil.Process()
        
        # Buffer to reduce contention on the CSV file
        self.data_points = []
        self.max_buffer_size = 10  # Write after 10 data points
        
        # Monitoring state
        self.monitoring_task = None
        self.is_monitoring = False
    
    async def start_monitoring(self, interval_sec: float = 1):
        """
        Start monitoring with reduced overhead
        
        Args:
            interval_sec: The interval between measurements in seconds
        """
        # First ensure the shared CSV file is initialized
        await self.__class__.initialize(self.scenario)
        
        if self.is_monitoring:
            return
            
        self.is_monitoring = True
        self.monitoring_interval = max(1, interval_sec)  # Ensure minimum 5 second interval
        
        # Start the monitoring task
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logging.info(f"Started monitoring for {self.agent_id} with interval {self.monitoring_interval}s")
    
    async def stop_monitoring(self):
        """Stop monitoring and ensure data is written"""
        if not self.is_monitoring:
            return
            
        self.is_monitoring = False
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None
        
        # Write any remaining data
        if self.data_points:
            await self._write_buffer()
        logging.info(f"Stopped monitoring for {self.agent_id}")
    
    async def _monitoring_loop(self):
        """Main monitoring loop with reduced overhead"""
        try:
            while self.is_monitoring:
                self._collect_metrics()
                
                # Only write to disk when buffer is full
                if len(self.data_points) >= self.max_buffer_size:
                    await self._write_buffer()
                
                await asyncio.sleep(self.monitoring_interval)
                
        except asyncio.CancelledError:
            # Write remaining data before cancellation
            if self.data_points:
                await self._write_buffer()
            raise
        except Exception as e:
            logging.error(f"Error in monitoring loop: {str(e)}")
            # Try to write data even on error
            if self.data_points:
                await self._write_buffer()
    
    def _collect_metrics(self):
        """Collect basic performance metrics with minimal overhead"""
        try:
            timestamp = datetime.now().isoformat()
            
            # Basic CPU and memory metrics - use interval=None for non-blocking
            cpu_percent = self.process.cpu_percent(interval=None)
            
            # Memory metrics
            mem_info = self.process.memory_info()
            memory_rss_mb = mem_info.rss / (1024 * 1024)
            memory_vms_mb = mem_info.vms / (1024 * 1024)
            
            # Get memory percent - lighter than detailed memory tracking
            memory_percent = self.process.memory_percent()
            
            # Count threads and tasks (cheaply)
            num_threads = self.process.num_threads()
            num_tasks = len(asyncio.all_tasks()) if hasattr(asyncio, 'all_tasks') else 0
            
            # Store metrics in buffer
            self.data_points.append([
                timestamp,
                self.agent_id,
                self.agent_type,
                cpu_percent,
                memory_rss_mb,
                memory_vms_mb,
                memory_percent,
                num_threads,
                num_tasks
            ])
            
        except Exception as e:
            logging.error(f"Error collecting metrics for {self.agent_id}: {str(e)}")
    
    async def _write_buffer(self):
        """Write buffered data to shared CSV file"""
        if not self.data_points:
            return
            
        try:
            # Use class lock to prevent multiple agents writing at once
            async with self.__class__._lock:
                with open(self.__class__._csv_path, 'a', newline='') as f:
                    csv_writer = csv.writer(f)
                    csv_writer.writerows(self.data_points)
            
            # Clear buffer after writing
            self.data_points.clear()
            
        except Exception as e:
            logging.error(f"Error writing metrics to file for {self.agent_id}: {str(e)}")
    
    def get_current_metrics(self) -> Dict:
        """Get current metrics as a dictionary - useful for API endpoints"""
        try:
            cpu_percent = self.process.cpu_percent(interval=None)
            mem_info = self.process.memory_info()
            
            return {
                "timestamp": datetime.now().isoformat(),
                "agent_id": self.agent_id,
                "agent_type": self.agent_type,
                "cpu_percent": cpu_percent,
                "memory_rss_mb": mem_info.rss / (1024 * 1024),
                "memory_vms_mb": mem_info.vms / (1024 * 1024),
                "memory_percent": self.process.memory_percent(),
                "num_threads": self.process.num_threads(),
                "num_tasks": len(asyncio.all_tasks()) if hasattr(asyncio, 'all_tasks') else 0
            }
        except Exception as e:
            logging.error(f"Error getting current metrics for {self.agent_id}: {str(e)}")
            return {"error": str(e)}