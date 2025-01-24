from typing import Dict, Any, Optional, List
import json
import asyncio
import aiofiles
from pathlib import Path 
import os
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ProfessorScheduleUpdate:
    nombre: str
    schedule_data: Dict[str, Any]
    asignaturas: List[Any]
    timestamp: datetime = datetime.now()

class ProfesorScheduleStorage:
    _instance = None
    _lock = asyncio.Lock()
    WRITE_THRESHOLD = 20

    def __init__(self):
        self._pending_updates: Dict[str, ProfessorScheduleUpdate] = {}
        self._all_professor_names = set()
        self._update_count = 0
        self._write_lock = asyncio.Lock()
        self._output_path = Path(os.getcwd()) / "agent_output"
        self._output_path.mkdir(exist_ok=True)

    @classmethod
    async def get_instance(cls) -> 'ProfesorScheduleStorage':
        if not cls._instance:
            async with cls._lock:
                if not cls._instance:
                    cls._instance = cls()
        return cls._instance

    async def update_schedule(self, nombre: str, schedule_data: Dict[str, Any], asignaturas: List[Any]) -> None:
        """Add or update a professor's schedule"""
        try:
            print(f"[DEBUG] Adding/updating schedule for professor {nombre}")

            # Count assignments
            assignment_count = len(schedule_data.get("Asignaturas", []))
            print(f"[DEBUG] Professor {nombre} has {assignment_count} total assignments")

            # Store update in memory with timestamp
            update = ProfessorScheduleUpdate(nombre, schedule_data, asignaturas)
            
            async with self._write_lock:
                self._pending_updates[nombre] = update
                self._all_professor_names.add(nombre)
                self._update_count += 1

                # Check if we should write to disk
                if self._update_count >= self.WRITE_THRESHOLD:
                    await self._flush_updates()

        except Exception as e:
            print(f"[ERROR] Error adding professor schedule for {nombre}: {str(e)}")
            raise

    async def _flush_updates(self) -> None:
        """Write pending updates to file"""
        if not await self._write_lock.acquire():
            return

        try:
            if not self._pending_updates:
                return

            json_array = []
            for update in self._pending_updates.values():
                profesor_json = {
                    "Nombre": update.nombre,
                    "Asignaturas": update.schedule_data.get("Asignaturas", []),
                    "Solicitudes": len(update.asignaturas),
                    "AsignaturasCompletadas": len(update.schedule_data.get("Asignaturas", [])),
                }
                json_array.append(profesor_json)

            if json_array:
                output_file = self._output_path / "Horarios_asignados.json"
                async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(json_array, indent=2, ensure_ascii=False))
                print(f"Successfully wrote {len(self._pending_updates)} professor schedules to file")

            self._pending_updates.clear()
            self._update_count = 0

        except Exception as e:
            print(f"Error writing professor schedules to file: {str(e)}")
            raise
        finally:
            self._write_lock.release()

    async def generate_json_file(self) -> None:
        """Generate final JSON file with all professor schedules"""
        async with self._write_lock:
            await self._flush_updates()

            json_array = []
            for nombre in self._all_professor_names:
                update = self._pending_updates.get(nombre)
                if update:
                    profesor_json = {
                        "Nombre": update.nombre,
                        "Asignaturas": update.schedule_data.get("Asignaturas", []),
                        "Solicitudes": len(update.asignaturas),
                        "AsignaturasCompletadas": len(update.schedule_data.get("Asignaturas", [])),
                    }
                    json_array.append(profesor_json)

            if json_array:
                output_file = self._output_path / "Horarios_asignados.json"
                async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(json_array, indent=2, ensure_ascii=False))
                print(f"Generated final Horarios_asignados.json with {len(json_array)} professors")

    async def force_flush(self) -> None:
        """Force write pending updates to file"""
        async with self._write_lock:
            await self._flush_updates()

    def get_pending_update_count(self) -> int:
        """Get number of pending updates"""
        return len(self._pending_updates)