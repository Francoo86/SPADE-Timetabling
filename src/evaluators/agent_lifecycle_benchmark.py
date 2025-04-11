import time
import asyncio
import aiofiles
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

class AgentLifecycleBenchmark:
    """Benchmarks agent lifecycle operations for comparison with JADE"""
    
    def __init__(self, output_file: str = "agent_lifecycle_metrics.csv"):
        self.output_file = Path("agent_output") / output_file
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()
        self._initialize_file()
        
    def _initialize_file(self):
        """Initialize CSV file with headers"""
        if not self.output_file.exists():
            with open(self.output_file, 'w', newline='') as f:
                f.write('timestamp,agent_id,operation,start_time,end_time,duration_ms\n')
                
    async def track_start(self, agent):
        """Track the complete agent.start() operation time"""
        start_time = time.perf_counter()
        agent_id = str(agent.jid).split("@")[0]
        
        # Store original setup method
        original_setup = agent.setup
        setup_complete = asyncio.Event()
        
        # Wrap the setup method to detect completion
        async def wrapped_setup(self):
            try:
                await original_setup()
            finally:
                setup_complete.set()
                
        # Replace the setup method
        agent.setup = wrapped_setup.__get__(agent)
        
        # Start the agent
        await agent.start()
        
        # Wait for setup to complete
        await setup_complete.wait()
        
        # Calculate time
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000
        
        # Log the result
        await self._log_operation(agent_id, "start", start_time, end_time, duration_ms)
        return duration_ms
    
    async def track_stop(self, agent):
        """Track the complete agent.stop() operation time"""
        start_time = time.perf_counter()
        agent_id = str(agent.jid).split("@")[0]
        
        # Stop the agent
        await agent.stop()
        
        # Calculate time
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000
        
        # Log the result
        await self._log_operation(agent_id, "stop", start_time, end_time, duration_ms)
        return duration_ms
    
    async def _log_operation(self, agent_id: str, operation: str, start_time: float, 
                           end_time: float, duration_ms: float):
        """Log the operation to CSV file"""
        timestamp = datetime.now().isoformat()
        
        async with self._write_lock:
            async with aiofiles.open(self.output_file, 'a') as f:
                row = f"{timestamp},{agent_id},{operation},{start_time:.6f},{end_time:.6f},{duration_ms:.3f}\n"
                await f.write(row)
                
    async def generate_summary(self) -> Dict:
        """Generate summary statistics from the collected data"""
        operations = {"start": [], "stop": []}
        
        async with aiofiles.open(self.output_file, 'r') as f:
            # Skip header
            content = await f.read()
            lines = content.splitlines()[1:]
            
            for line in lines:
                parts = line.split(',')
                if len(parts) >= 6:
                    op = parts[2]
                    duration = float(parts[5])
                    if op in operations:
                        operations[op].append(duration)
        
        summary = {}
        for op, durations in operations.items():
            if durations:
                summary[op] = {
                    "count": len(durations),
                    "avg_ms": sum(durations) / len(durations),
                    "min_ms": min(durations),
                    "max_ms": max(durations)
                }
            else:
                summary[op] = {"count": 0, "avg_ms": 0, "min_ms": 0, "max_ms": 0}
                
        return summary