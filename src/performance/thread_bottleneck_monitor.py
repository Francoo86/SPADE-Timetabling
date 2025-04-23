import asyncio
import os
import time
import psutil
import tracemalloc
import linecache
import threading
import gc
import inspect
from datetime import datetime
from pathlib import Path
import csv
import json
import logging
from typing import Dict, List, Optional, Set, Tuple, Any

class ThreadBottleneckMonitor:
    """
    Monitors coroutine bottlenecks by tracking CPU time per task
    and generating task dumps for detailed analysis.
    
    This is the Python equivalent of the Java ThreadBottleneckMonitor,
    adapted for asyncio and Python's memory model.
    """
    
    BASE_PATH = Path("agent_output/PerformanceLogs/ThreadInfo/")
    
    def __init__(self, iteration_number: int, agent_identifier: str, scenario: str):
        """
        Initialize the monitor.
        
        Args:
            iteration_number: Experiment iteration number
            agent_identifier: ID of the agent being monitored
            scenario: Scenario name for grouping results
        """
        self.iteration_id = f"Iteration{iteration_number}"
        self.agent_id = agent_identifier
        self.base_scenario = scenario
        self.monitoring_interval = 1.0  # Default: 1 second
        self.process = psutil.Process()
        
        # Create directories if they don't exist
        self._create_directories()
        
        # Initialize writers
        self.thread_writer = None
        self.mem_writer = None
        self.thread_csv_path = None
        self.mem_csv_path = None
        self._initialize_writers()
        
        # Initialize monitoring state
        self.previous_cpu_times = {}
        self.previous_cpu_percent = {}
        self.previous_memory_info = None
        self.monitoring_task = None
        self.is_monitoring = False
        
        # Track asyncio tasks
        self.task_history = {}
        
        # Enable tracemalloc for memory tracking
        tracemalloc.start(25)  # Keep 25 frames for each allocation
    
    def _create_directories(self):
        """Create necessary directories for logging"""
        # Main logging directory
        main_path = self.BASE_PATH / self.base_scenario
        main_path.mkdir(parents=True, exist_ok=True)
        
        # Thread dumps directory
        dump_path = self.BASE_PATH / "dumps" / self.base_scenario
        dump_path.mkdir(parents=True, exist_ok=True)
        
        # Bottleneck analysis directory
        bottleneck_path = self.BASE_PATH / "bottlenecks" / self.base_scenario
        bottleneck_path.mkdir(parents=True, exist_ok=True)
    
    def _initialize_writers(self):
        """Initialize CSV writers for metrics"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Thread metrics file
        self.thread_csv_path = self.BASE_PATH / self.base_scenario / f"{self.iteration_id}_{timestamp}_thread.csv"
        self.thread_writer = open(self.thread_csv_path, 'w', newline='')
        thread_csv = csv.writer(self.thread_writer)
        thread_csv.writerow([
            "Timestamp", "TaskID", "TaskName", "TaskState", 
            "CPUTime_ns", "UserTime_ns", "CPUPercent", 
            "PendingTime", "RunningTime"
        ])
        
        # Memory metrics file
        self.mem_csv_path = self.BASE_PATH / self.base_scenario / f"{self.iteration_id}_{timestamp}_memory.csv"
        self.mem_writer = open(self.mem_csv_path, 'w', newline='')
        mem_csv = csv.writer(self.mem_writer)
        mem_csv.writerow([
            "Timestamp", "TotalMemory_bytes", "FreeMemory_bytes", 
            "UsedMemory_bytes", "MaxMemory_bytes"
        ])
    
    async def start_monitoring(self, interval_ms: int = 1000):
        """
        Start monitoring thread CPU usage and memory
        
        Args:
            interval_ms: The interval between measurements in milliseconds
        """
        if self.is_monitoring:
            return
            
        self.is_monitoring = True
        self.monitoring_interval = interval_ms / 1000.0  # Convert to seconds
        
        # Start the monitoring task
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Schedule thread dump every 30 seconds
        asyncio.create_task(self._dump_loop())
        
        logging.info(f"Started monitoring for {self.agent_id} with interval {interval_ms}ms")
    
    async def stop_monitoring(self):
        """Stop monitoring and close writers"""
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
        
        # Close writers
        self._close_writers()
        
        # Run final analysis
        self.analyze_bottlenecks()
        
        logging.info(f"Stopped monitoring for {self.agent_id}")
    
    def _close_writers(self):
        """Close file writers"""
        if self.thread_writer:
            self.thread_writer.close()
            self.thread_writer = None
        
        if self.mem_writer:
            self.mem_writer.close()
            self.mem_writer = None
    
    async def _monitoring_loop(self):
        """Main monitoring loop that records metrics at regular intervals"""
        try:
            while self.is_monitoring:
                self._record_thread_metrics()
                self._record_memory_metrics()
                await asyncio.sleep(self.monitoring_interval)
                
        except asyncio.CancelledError:
            logging.info(f"Monitoring loop cancelled for {self.agent_id}")
            raise
        except Exception as e:
            logging.error(f"Error in monitoring loop: {str(e)}")
    
    async def _dump_loop(self):
        """Loop for generating thread dumps at regular intervals"""
        try:
            while self.is_monitoring:
                self.generate_task_dump()
                await asyncio.sleep(30)  # Every 30 seconds
                
        except asyncio.CancelledError:
            logging.info(f"Dump loop cancelled for {self.agent_id}")
            raise
        except Exception as e:
            logging.error(f"Error in dump loop: {str(e)}")
    
    def _record_thread_metrics(self):
        """Record CPU and task metrics"""
        try:
            # Get current timestamp
            timestamp = datetime.now().isoformat()
            
            # Get asyncio tasks
            current_loop = asyncio.get_event_loop()
            all_tasks = asyncio.all_tasks(current_loop)
            
            # Get CPU utilization
            cpu_percent = self.process.cpu_percent(interval=None) / psutil.cpu_count()
            
            # Get Python threads
            threads = threading.enumerate()
            
            thread_csv = csv.writer(self.thread_writer)
            
            # Record asyncio tasks
            for task in all_tasks:
                task_id = id(task)
                task_name = task.get_name()
                task_state = task._state
                
                # Calculate CPU percentage (approximate)
                if task_id in self.previous_cpu_percent:
                    task_cpu = self.previous_cpu_percent[task_id] * 0.7 + (cpu_percent / len(all_tasks)) * 0.3
                else:
                    task_cpu = cpu_percent / len(all_tasks)
                
                self.previous_cpu_percent[task_id] = task_cpu
                
                # Get task timing information
                running_time = 0
                pending_time = 0
                
                if hasattr(task, '_start_time'):
                    if task._state == 'PENDING':
                        pending_time = time.time() - task._start_time
                    else:
                        running_time = time.time() - task._start_time
                
                # Write to CSV
                thread_csv.writerow([
                    timestamp,
                    task_id,
                    task_name,
                    task_state,
                    0,  # CPU time not directly available
                    0,  # User time not directly available
                    task_cpu,
                    pending_time,
                    running_time
                ])
            
            # Record Python threads
            for thread in threads:
                thread_id = thread.ident
                thread_name = thread.name
                thread_state = "RUNNING" if thread.is_alive() else "DEAD"
                
                # Write to CSV
                thread_csv.writerow([
                    timestamp,
                    thread_id,
                    thread_name,
                    thread_state,
                    0,  # CPU time not directly available
                    0,  # User time not directly available
                    0,  # CPU percent not available per thread in Python
                    0,  # No pending time concept for threads
                    0   # No running time concept for threads
                ])
            
            self.thread_writer.flush()
            
        except Exception as e:
            logging.error(f"Error recording thread metrics: {str(e)}")
    
    def _record_memory_metrics(self):
        """Record memory usage metrics"""
        try:
            # Get current timestamp
            timestamp = datetime.now().isoformat()
            
            # Get memory info
            mem_info = self.process.memory_info()
            
            # Get tracemalloc statistics
            current_traced, peak_traced = tracemalloc.get_traced_memory()
            
            # Get Python memory info
            total_memory = mem_info.rss
            free_memory = 0  # Not directly available in Python
            used_memory = mem_info.rss
            max_memory = total_memory  # Not directly available in Python
            
            # Write to CSV
            mem_csv = csv.writer(self.mem_writer)
            mem_csv.writerow([
                timestamp,
                total_memory,
                free_memory,
                used_memory,
                max_memory
            ])
            
            self.mem_writer.flush()
            
            # Update previous memory info
            self.previous_memory_info = mem_info
            
        except Exception as e:
            logging.error(f"Error recording memory metrics: {str(e)}")
    
    def generate_task_dump(self):
        """Generate task dump to a file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dump_path = self.BASE_PATH / "dumps" / self.base_scenario / f"task_dump_{self.agent_id}_{timestamp}.txt"
            
            with open(dump_path, 'w') as dump_file:
                # Write header
                dump_file.write(f"Task Dump generated at {timestamp}\n")
                dump_file.write(f"Agent: {self.agent_id}\n")
                dump_file.write("--------------------------------------------------\n\n")
                
                # Get event loop and tasks
                loop = asyncio.get_event_loop()
                tasks = asyncio.all_tasks(loop)
                
                # Sort tasks by estimated CPU usage
                sorted_tasks = sorted(
                    tasks,
                    key=lambda t: self.previous_cpu_percent.get(id(t), 0),
                    reverse=True
                )
                
                # Write task information
                for i, task in enumerate(sorted_tasks):
                    task_id = id(task)
                    task_name = task.get_name()
                    task_state = task._state
                    task_cpu = self.previous_cpu_percent.get(task_id, 0)
                    
                    dump_file.write(f"Task #{i+1}: {task_name}\n")
                    dump_file.write(f"  ID: {task_id}\n")
                    dump_file.write(f"  State: {task_state}\n")
                    dump_file.write(f"  Est. CPU: {task_cpu:.2f}%\n")
                    
                    # Get stack frame
                    stack = None
                    if not task.done():
                        stack = task.get_stack()
                    
                    if stack:
                        dump_file.write("  Stack:\n")
                        for frame in stack:
                            dump_file.write(f"    {frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}\n")
                    else:
                        dump_file.write("  Stack: Not available\n")
                    
                    # Get exception info if task failed
                    if task.done() and not task.cancelled():
                        try:
                            exc = task.exception()
                            if exc:
                                dump_file.write(f"  Exception: {type(exc).__name__}: {str(exc)}\n")
                        except asyncio.CancelledError:
                            dump_file.write("  Exception: Task was cancelled\n")
                    
                    dump_file.write("\n")
                
                # Write Python threads
                dump_file.write("--------------------------------------------------\n")
                dump_file.write("Python Threads:\n")
                dump_file.write("--------------------------------------------------\n\n")
                
                threads = threading.enumerate()
                for thread in threads:
                    dump_file.write(f"Thread: {thread.name} (ID: {thread.ident})\n")
                    dump_file.write(f"  Alive: {thread.is_alive()}\n")
                    dump_file.write(f"  Daemon: {thread.daemon}\n")
                    dump_file.write("\n")
                
                # Write memory snapshot
                dump_file.write("--------------------------------------------------\n")
                dump_file.write("Memory Snapshot (Top 20 allocations):\n")
                dump_file.write("--------------------------------------------------\n\n")
                
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics('lineno')
                
                for i, stat in enumerate(top_stats[:20], 1):
                    frame = stat.traceback[0]
                    filename = os.path.basename(frame.filename)
                    dump_file.write(f"#{i}: {filename}:{frame.lineno}: {stat.size / 1024:.1f} KiB\n")
                    line = linecache.getline(frame.filename, frame.lineno).strip()
                    dump_file.write(f"    {line}\n\n")
                
                logging.info(f"Generated task dump at {dump_path}")
                
        except Exception as e:
            logging.error(f"Error generating task dump: {str(e)}")
    
    def correlate_with_os_processes(self):
        """
        Correlate Python tasks with OS processes
        
        Note: In Python, most tasks run in the same process, so this
        correlation is less useful than in Java, but we include it for parity.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.BASE_PATH / self.base_scenario / f"task_os_correlation_{self.agent_id}_{timestamp}.txt"
            
            with open(output_path, 'w') as file:
                # Write header
                file.write("Python Task to OS Process correlation\n")
                file.write(f"Timestamp: {timestamp}\n")
                file.write(f"PID: {os.getpid()}\n")
                file.write(f"Agent: {self.agent_id}\n")
                file.write("--------------------------------------------------\n\n")
                
                # Current process info
                proc = psutil.Process()
                file.write(f"Process: {proc.name()} (PID: {proc.pid})\n")
                file.write(f"  CPU: {proc.cpu_percent()}%\n")
                file.write(f"  Memory: {proc.memory_info().rss / (1024*1024):.2f} MB\n")
                file.write(f"  Threads: {proc.num_threads()}\n")
                file.write(f"  Status: {proc.status()}\n")
                
                # Write thread info
                file.write("\nPython Threads:\n")
                for thread in threading.enumerate():
                    file.write(f"  {thread.name} (ID: {thread.ident})\n")
                
                # Get asyncio tasks
                loop = asyncio.get_event_loop()
                tasks = asyncio.all_tasks(loop)
                
                # Write task info
                file.write(f"\nAsyncio Tasks ({len(tasks)}):\n")
                for task in tasks:
                    file.write(f"  {task.get_name()} (ID: {id(task)}, State: {task._state})\n")
                
                # Write system resource info
                file.write("\nSystem Resource Usage:\n")
                file.write(f"  CPU Cores: {psutil.cpu_count()}\n")
                file.write(f"  CPU Usage: {psutil.cpu_percent()}%\n")
                mem = psutil.virtual_memory()
                file.write(f"  Memory Total: {mem.total / (1024*1024*1024):.2f} GB\n")
                file.write(f"  Memory Available: {mem.available / (1024*1024*1024):.2f} GB\n")
                file.write(f"  Memory Used: {mem.percent}%\n")
                
                logging.info(f"Generated OS correlation at {output_path}")
                
        except Exception as e:
            logging.error(f"Error correlating with OS processes: {str(e)}")
    
    def analyze_bottlenecks(self):
        """Analyze task bottlenecks and generate a report"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = self.BASE_PATH / "bottlenecks" / self.base_scenario / f"bottleneck_analysis_{self.agent_id}_{timestamp}.txt"
            
            with open(report_path, 'w') as file:
                # Write header
                file.write("Task Bottleneck Analysis\n")
                file.write(f"Timestamp: {timestamp}\n")
                file.write(f"Agent: {self.agent_id}\n")
                file.write("--------------------------------------------------\n\n")
                
                # Get task statistics
                loop = asyncio.get_event_loop()
                tasks = asyncio.all_tasks(loop)
                
                # Count tasks by state
                state_count = {}
                for task in tasks:
                    state = task._state
                    state_count[state] = state_count.get(state, 0) + 1
                
                # Write task state distribution
                file.write("Task State Distribution:\n")
                file.write("--------------------------------------------------\n")
                for state, count in state_count.items():
                    file.write(f"{state}: {count} tasks\n")
                file.write("\n")
                
                # List top CPU consumers
                file.write("Top Tasks by CPU Usage:\n")
                file.write("--------------------------------------------------\n")
                
                sorted_tasks = sorted(
                    tasks,
                    key=lambda t: self.previous_cpu_percent.get(id(t), 0),
                    reverse=True
                )
                
                for i, task in enumerate(sorted_tasks[:10], 1):
                    task_id = id(task)
                    cpu_percent = self.previous_cpu_percent.get(task_id, 0)
                    file.write(f"{i}. {task.get_name()} (ID: {task_id}) - CPU: {cpu_percent:.2f}%\n")
                
                file.write("\n")
                
                # Analyze memory usage
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics('lineno')
                
                file.write("Top Memory Consumers:\n")
                file.write("--------------------------------------------------\n")
                
                for i, stat in enumerate(top_stats[:10], 1):
                    frame = stat.traceback[0]
                    filename = os.path.basename(frame.filename)
                    file.write(f"{i}. {filename}:{frame.lineno} - {stat.size / 1024:.1f} KiB\n")
                    line = linecache.getline(frame.filename, frame.lineno).strip()
                    file.write(f"   {line}\n")
                
                file.write("\n")
                
                # Event loop analysis
                file.write("Event Loop Analysis:\n")
                file.write("--------------------------------------------------\n")
                
                # Check if slow callback duration threshold is set
                slow_callback_duration = getattr(loop, 'slow_callback_duration', 0.1)
                file.write(f"Slow callback threshold: {slow_callback_duration:.3f} seconds\n")
                
                # Get current time
                now = loop.time()
                file.write(f"Current loop time: {now:.3f} seconds\n")
                
                # Count scheduled tasks
                scheduled_count = 0
                for handle in getattr(loop, '_scheduled', []):
                    if not handle._cancelled:
                        scheduled_count += 1
                
                file.write(f"Scheduled tasks: {scheduled_count}\n")
                
                # Count ready handles
                ready_count = len(getattr(loop, '_ready', []))
                file.write(f"Ready handles: {ready_count}\n")
                
                file.write("\nBottleneck Analysis Complete\n")
                
                logging.info(f"Generated bottleneck analysis at {report_path}")
                
        except Exception as e:
            logging.error(f"Error analyzing bottlenecks: {str(e)}")