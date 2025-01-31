import csv
import asyncio
import aiofiles
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass
from pathlib import Path
import os

@dataclass
class DFOperation:
    """Represents a single DF operation with timing data"""
    agent_id: str
    operation: str  # 'search', 'register', 'deregister', 'cache_hit'
    timestamp: datetime
    response_time_ms: float
    num_results: int
    status: str

class DFMetricsTracker:
    """Tracks metrics for Directory Facilitator operations"""
    
    def __init__(self, output_file: str = "df_metrics.csv"):
        self.output_file = Path("agent_output") / output_file
        self._lock = asyncio.Lock()
        self._cache: Dict[str, Dict] = {}  # Simple cache for DF operations
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_file()

    def _initialize_file(self):
        """Initialize CSV file with headers"""
        if not self.output_file.exists():
            with open(self.output_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Agent_ID',
                    'Timestamp',
                    'Operation',
                    'ResponseTime_ms',
                    'NumResults',
                    'Status'
                ])

    async def log_operation(self, operation: DFOperation):
        """Log a DF operation with timing data"""
        async with self._lock:
            async with aiofiles.open(self.output_file, 'a', newline='') as f:
                row = [
                    operation.agent_id,
                    operation.timestamp.isoformat(),
                    operation.operation,
                    f"{operation.response_time_ms:.0f}",
                    str(operation.num_results),
                    operation.status
                ]
                await f.write(','.join(row) + '\n')

    def _make_hashable(self, obj):
        """Convert a dictionary into a hashable format"""
        if isinstance(obj, dict):
            return frozenset((k, self._make_hashable(v)) for k, v in sorted(obj.items()))
        elif isinstance(obj, list):
            return tuple(self._make_hashable(elem) for elem in obj)
        elif isinstance(obj, set):
            return frozenset(self._make_hashable(elem) for elem in obj)
        return obj

    def _generate_cache_key(self, agent_id: str, operation: str, params: Dict) -> str:
        """Generate a cache key from parameters"""
        try:
            hashable_params = self._make_hashable(params)
            return f"{agent_id}:{operation}:{hash(hashable_params)}"
        except Exception:
            # Fallback if hashing fails
            return f"{agent_id}:{operation}:{datetime.now().timestamp()}"

    def check_cache(self, agent_id: str, operation: str, params: Dict) -> Optional[Dict]:
        """Check if operation result is in cache"""
        cache_key = self._generate_cache_key(agent_id, operation, params)
        return self._cache.get(cache_key)

    def update_cache(self, agent_id: str, operation: str, params: Dict, result: Dict):
        """Update cache with operation result"""
        cache_key = self._generate_cache_key(agent_id, operation, params)
        self._cache[cache_key] = result

    async def analyze_operations(self) -> Dict:
        """Analyze DF operations and generate statistics"""
        stats = {
            'register': {'count': 0, 'total_time': 0, 'avg_time': 0},
            'deregister': {'count': 0, 'total_time': 0, 'avg_time': 0},
            'search': {'count': 0, 'total_time': 0, 'avg_time': 0},
            'cache_hit': {'count': 0, 'total_time': 0, 'avg_time': 0}
        }
        
        async with aiofiles.open(self.output_file, 'r') as f:
            lines = await f.readlines()
            # Skip header
            for line in lines[1:]:
                agent_id, timestamp, operation, response_time, num_results, status = line.strip().split(',')
                if status.startswith('success'):
                    op_stats = stats[operation]
                    op_stats['count'] += 1
                    op_stats['total_time'] += float(response_time)
        
        # Calculate averages
        for op_stats in stats.values():
            if op_stats['count'] > 0:
                op_stats['avg_time'] = op_stats['total_time'] / op_stats['count']
                
        return stats

def calculate_df_metric(self, start_time: float, end_time: float, num_requests: int) -> float:
        """Calculate DF metric using the provided formula"""
        if num_requests == 0:
            return 0
        return (end_time - start_time) / num_requests