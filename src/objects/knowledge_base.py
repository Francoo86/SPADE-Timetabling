from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import asyncio
from datetime import datetime, timedelta
import json
from aioxmpp import JID

from performance.df_analysis import DFOperation, DFMetricsTracker

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
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        
        filename_with_timestamp = f"df_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.df_tracker = DFMetricsTracker(output_file=filename_with_timestamp)

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

    async def start(self):
        """Start the knowledge base and its maintenance tasks"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

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
        start_time = datetime.now()
        agent_id = str(jid).split("@")[0]  # Extract agent name from JID
        
        try:
            async with self._lock:
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
                end_time = datetime.now()
                response_time = (end_time - start_time).total_seconds() * 1000
                
                # Log registration operation
                await self.df_tracker.log_operation(DFOperation(
                    agent_id=agent_id,
                    operation="register",
                    timestamp=end_time,
                    response_time_ms=response_time,
                    num_results=len(capabilities),  # Number of registered capabilities
                    status="success"
                ))
                
                return True
                
        except Exception as e:
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds() * 1000
            
            await self.df_tracker.log_operation(DFOperation(
                agent_id=agent_id,
                operation="register",
                timestamp=end_time,
                response_time_ms=response_time,
                num_results=0,
                status=f"error: {str(e)}"
            ))
            raise

    async def deregister_agent(self, jid: JID) -> bool:
        """Enhanced deregistration with DF metrics tracking"""
        start_time = datetime.now()
        agent_id = str(jid).split("@")[0]
        
        try:
            async with self._lock:
                jid_str = str(jid)
                if jid_str not in self._agents:
                    await self.df_tracker.log_operation(DFOperation(
                        agent_id=agent_id,
                        operation="deregister",
                        timestamp=datetime.now(),
                        response_time_ms=0,
                        num_results=0,
                        status="not_found"
                    ))
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
                end_time = datetime.now()
                response_time = (end_time - start_time).total_seconds() * 1000
                
                # Log deregistration operation
                await self.df_tracker.log_operation(DFOperation(
                    agent_id=agent_id,
                    operation="deregister",
                    timestamp=end_time,
                    response_time_ms=response_time,
                    num_results=num_capabilities,  # Number of deregistered capabilities
                    status="success"
                ))
                
                return True
                
        except Exception as e:
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds() * 1000
            
            await self.df_tracker.log_operation(DFOperation(
                agent_id=agent_id,
                operation="deregister",
                timestamp=end_time,
                response_time_ms=response_time,
                num_results=0,
                status=f"error: {str(e)}"
            ))
            raise

    async def search(self, service_type: Optional[str] = None, properties: Optional[Dict[str, any]] = None) -> List[AgentInfo]:
        """Enhanced search with DF metrics tracking"""
        start_time = datetime.now()
        agent_id = properties.get("agent_id", "unknown") if properties else "unknown"
        
        try:
            # Check cache first
            cache_params = {"service_type": service_type, "properties": properties}
            cached_result = self.df_tracker.check_cache(agent_id, "search", cache_params)
            
            if cached_result:
                # Log cache hit
                await self.df_tracker.log_operation(DFOperation(
                    agent_id=agent_id,
                    operation="cache_hit",
                    timestamp=datetime.now(),
                    response_time_ms=0,
                    num_results=len(cached_result),
                    status="success"
                ))
                return cached_result

            async with self._lock:
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
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds() * 1000
            
            # Log operation
            await self.df_tracker.log_operation(DFOperation(
                agent_id=agent_id,
                operation="search",
                timestamp=end_time,
                response_time_ms=response_time,
                num_results=len(results),
                status="success"
            ))
            
            # Update cache
            self.df_tracker.update_cache(agent_id, "search", cache_params, results)
            
            return results
            
        except Exception as e:
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds() * 1000
            
            await self.df_tracker.log_operation(DFOperation(
                agent_id=agent_id,
                operation="search",
                timestamp=end_time,
                response_time_ms=response_time,
                num_results=0,
                status=f"error: {str(e)}"
            ))
            raise
    
    async def _cleanup_loop(self):
        """Periodically remove expired agent registrations"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in cleanup loop: {e}")

    async def _cleanup_expired(self):
        """Remove agents that haven't sent heartbeats within TTL"""
        async with self._lock:
            now = datetime.now()
            expired = []
            
            for jid_str, info in self._agents.items():
                if now - info.last_heartbeat > self._ttl:
                    expired.append(JID.fromstr(jid_str))
            
            for jid in expired:
                await self.deregister_agent(jid)

    async def export_state(self) -> str:
        """Export current state as JSON string"""
        async with self._lock:
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
        
        async with kb._lock:
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