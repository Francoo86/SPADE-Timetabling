from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import asyncio
from datetime import datetime, timedelta
import json
from aioxmpp import JID

# from performance.df_analysis import DFOperation, DFMetricsTracker
import time

@dataclass
class AgentCapability:
    """Represents an agent's capabilities and properties"""
    service_type: str
    properties: Dict[str, any]
    last_updated: datetime

@dataclass
class AgentInfo:
    """Complete information about an agent"""
    jid: JID
    capabilities: List[AgentCapability]
    last_heartbeat: datetime

class AgentKnowledgeBase:
    """
    A distributed knowledge base for agent discovery and capability management.
    Replaces JADE's Directory Facilitator functionality in SPADE.
    """
    _instance = None
    _instance_lock = asyncio.Lock()
    _initialized = False

    def __init__(self, ttl_seconds: int = 300):
        self._agents: Dict[str, AgentInfo] = {}
        self._capabilities: Dict[str, Set[str]] = {}  # service_type -> set of JIDs
        self._ttl = timedelta(seconds=ttl_seconds)
        self._register_lock = asyncio.Lock()
        self._search_lock = asyncio.Lock()
        self._cleanup_task = None
        self._cache = {}

    @classmethod
    async def get_instance(cls) -> 'AgentKnowledgeBase':
        if not cls._instance:
            async with cls._instance_lock:
                if not cls._instance:
                    cls._instance = cls()
                    if not cls._initialized:
                        await cls._instance.start()
                        cls._initialized = True
        return cls._instance
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __make_hashable(self, obj):
        """Convert a dictionary into a hashable format"""
        if isinstance(obj, dict):
            return frozenset((k, self.__make_hashable(v)) for k, v in sorted(obj.items()))
        elif isinstance(obj, list):
            return tuple(self.__make_hashable(elem) for elem in obj)
        elif isinstance(obj, set):
            return frozenset(self.__make_hashable(elem) for elem in obj)
        return obj
    
    def _generate_cache_key(self, agent_id: str, operation: str, params: Dict) -> str:
        """Generate a cache key from parameters"""
        try:
            hashable_params = self.__make_hashable(params)
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

    async def start(self):
        """Start the knowledge base and its maintenance tasks"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            
    def set_scenario(self, scenario: str):
        """Set the scenario for the knowledge base"""
        self.scenario = scenario

    async def stop(self):
        """Stop the knowledge base and cleanup"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            finally:
                self._cleanup_task = None

    async def register_agent(self, jid: JID, capabilities: List[AgentCapability]) -> bool:
        """Enhanced registration with DF metrics tracking"""
        start_time = time.perf_counter()
        agent_id = str(jid).split("@")[0]  # Extract agent name from JID
        
        try:
            async with self._register_lock:
                # Update agent info
                self._agents[str(jid)] = AgentInfo(
                    jid=jid,
                    capabilities=capabilities,
                    last_heartbeat=datetime.now()
                )
                
                # Update capability indices
                for cap in capabilities:
                    if cap.service_type not in self._capabilities:
                        self._capabilities[cap.service_type] = set()
                    self._capabilities[cap.service_type].add(str(jid))
                
                # Calculate response time
                end_time = time.perf_counter()
                response_time = (end_time - start_time) * 1000
                
                return True
                
        except Exception as e:
            end_time = time.perf_counter()
            response_time = (end_time - start_time) * 1000
            raise

    async def deregister_agent(self, jid: JID) -> bool:
        """Enhanced deregistration with DF metrics tracking"""
        start_time = time.perf_counter()
        agent_id = str(jid).split("@")[0]
        
        try:
            async with asyncio.timeout(10):
                async with self._register_lock:
                    jid_str = str(jid)
                    if jid_str not in self._agents:
                        return False

                    # Remove from capability indices
                    agent_info = self._agents[jid_str]
                    num_capabilities = 0
                    for cap in agent_info.capabilities:
                        if cap.service_type in self._capabilities:
                            self._capabilities[cap.service_type].discard(jid_str)
                            num_capabilities += 1
                            if not self._capabilities[cap.service_type]:
                                del self._capabilities[cap.service_type]

                    # Remove agent info
                    del self._agents[jid_str]
                    
                    # Calculate response time
                    end_time = time.perf_counter()
                    response_time = (end_time - start_time) * 1000
                    
                    return True
        except Exception as e:
            end_time = time.perf_counter()
            response_time = (end_time - start_time) * 1000
            
            # raise custom exception or log error
            raise Exception(f"Error deregistering agent {jid}: {str(e)}")

    async def search(self, service_type: Optional[str] = None, properties: Optional[Dict[str, any]] = None) -> List[AgentInfo]:
        """Enhanced search with DF metrics tracking"""
        start_time = time.perf_counter()
        agent_id = properties.get("agent_id", "unknown") if properties else "unknown"
        
        try:
            # Check cache first
            cache_params = {"service_type": service_type, "properties": properties}
            cached_result = self.check_cache(agent_id, "search", cache_params)
            
            if cached_result:
                return cached_result

            async with self._search_lock:
                results = []
                candidate_jids = (self._capabilities.get(service_type, set()) 
                                if service_type else set(self._agents.keys()))
                
                for jid_str in candidate_jids:
                    agent = self._agents.get(jid_str)
                    if not agent:
                        continue
                        
                    if properties:
                        for cap in agent.capabilities:
                            if cap.service_type == service_type:
                                matches = all(
                                    key in cap.properties and cap.properties[key] == value
                                    for key, value in properties.items()
                                )
                                if matches:
                                    results.append(agent)
                                    break
                    else:
                        results.append(agent)

            # Calculate response time
            end_time = time.perf_counter()
            response_time = (end_time - start_time) * 1000
            
            self.update_cache(agent_id, "search", cache_params, results)
            
            return results
            
        except Exception as e:
            end_time = time.perf_counter()
            response_time = (end_time - start_time) * 1000
            
            raise Exception(f"Error searching for agents: {str(e)}")
    
    async def _cleanup_loop(self):
        """Periodically remove expired agent registrations"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                # await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in cleanup loop: {e}")

    async def _cleanup_expired(self):
        """Remove agents that haven't sent heartbeats within TTL"""
        async with self._register_lock:
            now = datetime.now()
            expired = []
            
            for jid_str, info in self._agents.items():
                if now - info.last_heartbeat > self._ttl:
                    expired.append(JID.fromstr(jid_str))
            
            for jid in expired:
                await self.deregister_agent(jid)

    async def export_state(self) -> str:
        """Export current state as JSON string"""
        async with self._register_lock:
            state = {
                "agents": {
                    jid: {
                        "capabilities": [
                            {
                                "service_type": cap.service_type,
                                "properties": cap.properties,
                                "last_updated": cap.last_updated.isoformat()
                            }
                            for cap in info.capabilities
                        ],
                        "last_heartbeat": info.last_heartbeat.isoformat()
                    }
                    for jid, info in self._agents.items()
                }
            }
            return json.dumps(state, indent=2)

    @classmethod
    async def import_state(cls, state_json: str) -> 'AgentKnowledgeBase':
        """Create new knowledge base instance from exported state"""
        kb = cls()
        state = json.loads(state_json)
        
        async with kb._register_lock:
            for jid_str, agent_data in state["agents"].items():
                capabilities = [
                    AgentCapability(
                        service_type=cap["service_type"],
                        properties=cap["properties"],
                        last_updated=datetime.fromisoformat(cap["last_updated"])
                    )
                    for cap in agent_data["capabilities"]
                ]
                
                kb._agents[jid_str] = AgentInfo(
                    jid=JID.fromstr(jid_str),
                    capabilities=capabilities,
                    last_heartbeat=datetime.fromisoformat(agent_data["last_heartbeat"])
                )
                
                # Rebuild capability indices
                for cap in capabilities:
                    if cap.service_type not in kb._capabilities:
                        kb._capabilities[cap.service_type] = set()
                    kb._capabilities[cap.service_type].add(jid_str)
                    
        return kb
    
    @classmethod
    async def reset_instance(cls):
        """Reset the singleton instance (useful for testing)"""
        if cls._instance:
            await cls._instance.stop()
            cls._instance = None