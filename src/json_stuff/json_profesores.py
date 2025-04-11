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
        # FIXME: La implementacion no solía guardar todas las actualizaciones
        self._all_updates: Dict[str, ProfessorScheduleUpdate] = {}
        self._all_professor_names = set()
        self._update_count = 0
        self._write_lock = asyncio.Lock()
        self._output_path = Path(os.getcwd()) / "agent_output"
        self._output_path.mkdir(exist_ok=True)
        
    def set_scenario(self, scenario: str) -> None:
        """Set the scenario for output path"""
        self._output_path = Path(os.getcwd()) / "agent_output" / scenario
        self._output_path.mkdir(parents=True, exist_ok=True)
        print(f"[DEBUG] Output path set to {self._output_path}")

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
            assignment_count = len(schedule_data.get("Asignaturas", []))
            print(f"[DEBUG] Professor {nombre} has {assignment_count} total assignments")

            update = ProfessorScheduleUpdate(nombre, schedule_data, asignaturas)
            
            async with self._write_lock:
                self._pending_updates[nombre] = update
                self._all_updates[nombre] = update
                self._all_professor_names.add(nombre)
                self._update_count += 1

                if self._update_count >= self.WRITE_THRESHOLD:
                    await self._write_updates_to_file()

        except Exception as e:
            print(f"[ERROR] Error adding professor schedule for {nombre}: {str(e)}")
            raise

    async def _write_updates_to_file(self) -> None:
        """Write updates to file - assumes lock is already held"""
        try:
            if not self._all_updates:
                return

            json_array = []

            for update in self._all_updates.values():
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
                    await f.flush()
                print(f"Successfully wrote {len(json_array)} professor schedules to file")

            # Only clear pending updates, keep complete history
            self._pending_updates.clear()
            self._update_count = 0

        except Exception as e:
            print(f"[ERROR] Error writing professor schedules to file: {str(e)}")
            raise

    async def generate_json_file(self) -> None:
        """Generate final JSON file with all professor schedules"""
        try:
            async with self._write_lock:
                print(f"[DEBUG] Processing {len(self._all_professor_names)} professors")
                
                json_array = []

                for update in self._all_updates.values():
                    try:
                        profesor_json = {
                            "Nombre": update.nombre,
                            "Asignaturas": update.schedule_data.get("Asignaturas", []),
                            "Solicitudes": len(update.asignaturas),
                            "AsignaturasCompletadas": len(update.schedule_data.get("Asignaturas", [])),
                        }
                        json_array.append(profesor_json)
                        print(f"[DEBUG] Processed professor {update.nombre}: "
                              f"{len(profesor_json['Asignaturas'])} assignments")
                    except Exception as e:
                        print(f"[ERROR] Error processing professor {update.nombre}: {str(e)}")
                        continue

                if json_array:
                    try:
                        output_file = self._output_path / "Horarios_asignados.json"
                        async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                            await f.write(json.dumps(json_array, indent=2, ensure_ascii=False))
                            await f.flush()
                            
                        print(f"[SUCCESS] Generated Horarios_asignados.json with {len(json_array)} professors")
                        if output_file.exists():
                            print(f"[DEBUG] File size: {output_file.stat().st_size} bytes")
                    except Exception as e:
                        print(f"[ERROR] Error writing output file: {str(e)}")
                else:
                    print("[WARN] No professor data to write")

        except Exception as e:
            print(f"[ERROR] Critical error in generate_json_file: {str(e)}")
            raise

    async def force_flush(self) -> None:
        """Force write pending updates to file"""
        async with self._write_lock:
            await self._write_updates_to_file()

    def get_pending_update_count(self) -> int:
        """Get number of pending updates"""
        return len(self._pending_updates)

    def get_total_update_count(self) -> int:
        """Get total number of professors with updates"""
        return len(self._all_updates)