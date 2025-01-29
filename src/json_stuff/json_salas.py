from typing import Dict, Any, Optional, List
import json
import asyncio
import aiofiles
from pathlib import Path
import os
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ScheduleUpdate:
    codigo: str
    campus: str
    schedule_data: Dict[str, Any]
    timestamp: datetime = datetime.now()

class SalaScheduleStorage:
    _instance = None
    _lock = asyncio.Lock()
    WRITE_THRESHOLD = 20

    def __init__(self):
        self._pending_updates: Dict[str, ScheduleUpdate] = {}
        self._all_room_codes = set()
        self._update_count = 0
        self._write_lock = asyncio.Lock()
        self._output_path = Path(os.getcwd()) / "agent_output"
        self._output_path.mkdir(exist_ok=True)

    @classmethod
    async def get_instance(cls) -> 'SalaScheduleStorage':
        if not cls._instance:
            async with cls._lock:
                if not cls._instance:
                    cls._instance = cls()
        return cls._instance

    async def update_schedule(self, codigo: str, campus: str, schedule_data: Dict[str, Any]) -> None:
        """Add or update a room's schedule"""
        try:
            print(f"[DEBUG] Adding/updating schedule for room {codigo}")
            assignment_count = sum(
                1 for day_assignments in schedule_data["horario"].values()
                for assignment in day_assignments if assignment
            )
            print(f"[DEBUG] Room {codigo} has {assignment_count} total assignments")

            update = ScheduleUpdate(codigo, campus, schedule_data)
            
            async with self._write_lock:
                self._pending_updates[codigo] = update
                self._all_room_codes.add(codigo)
                self._update_count += 1

                if self._update_count >= self.WRITE_THRESHOLD:
                    await self._write_updates_to_file()

        except Exception as e:
            print(f"[ERROR] Error adding classroom schedule for {codigo}: {str(e)}")
            raise

    async def _write_updates_to_file(self) -> None:
        """Write updates to file without acquiring additional locks"""
        try:
            if not self._pending_updates:
                return

            json_array = []
            for update in self._pending_updates.values():
                sala_json = {
                    "Codigo": update.codigo,
                    "Campus": update.campus,
                    "Asignaturas": []
                }

                if "horario" in update.schedule_data:
                    for day, assignments in update.schedule_data["horario"].items():
                        for block_idx, assignment in enumerate(assignments, 1):
                            if assignment:
                                asignatura = {
                                    "Nombre": assignment['nombre_asignatura'],
                                    "Capacidad": assignment['capacidad'],
                                    "Bloque": block_idx,
                                    "Dia": day,
                                    "Satisfaccion": assignment['satisfaccion']
                                }
                                sala_json["Asignaturas"].append(asignatura)

                json_array.append(sala_json)

            if json_array:
                output_file = self._output_path / "Horarios_salas.json"
                async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(json_array, indent=2, ensure_ascii=False))
                print(f"Successfully wrote {len(self._pending_updates)} classroom schedules to file")

            self._pending_updates.clear()
            self._update_count = 0

        except Exception as e:
            print(f"Error writing classroom schedules to file: {str(e)}")
            raise

    async def generate_json_file(self) -> None:
        """Generate final JSON file with all room schedules"""
        try:
            async with self._write_lock:
                print(f"[DEBUG] Processing {len(self._all_room_codes)} rooms")
                json_array = []
                
                for room_code in self._all_room_codes:
                    try:
                        update = self._pending_updates.get(room_code)
                        if update:
                            sala_json = {
                                "Codigo": update.codigo,
                                "Campus": update.campus,
                                "Asignaturas": []
                            }
                            
                            if "horario" in update.schedule_data:
                                for day, assignments in update.schedule_data["horario"].items():
                                    for block_idx, assignment in enumerate(assignments, 1):
                                        if assignment:
                                            asignatura = {
                                                "Nombre": assignment['nombre_asignatura'],
                                                "Capacidad": assignment['capacidad'],
                                                "Bloque": block_idx,
                                                "Dia": day,
                                                "Satisfaccion": assignment['satisfaccion']
                                            }
                                            sala_json["Asignaturas"].append(asignatura)
                                            
                            json_array.append(sala_json)
                            print(f"[DEBUG] Processed room {room_code}: {len(sala_json['Asignaturas'])} assignments")
                        else:
                            print(f"[WARN] No data found for room {room_code}")
                            
                    except Exception as e:
                        print(f"[ERROR] Error processing room {room_code}: {str(e)}")
                        continue

                if json_array:
                    try:
                        output_file = self._output_path / "Horarios_salas.json"
                        async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                            await f.write(json.dumps(json_array, indent=2, ensure_ascii=False))
                            await f.flush()
                            
                        print(f"[SUCCESS] Generated Horarios_salas.json with {len(json_array)} rooms")
                        if output_file.exists():
                            print(f"[DEBUG] File size: {output_file.stat().st_size} bytes")
                        
                    except Exception as e:
                        print(f"[ERROR] Error writing output file: {str(e)}")
                else:
                    print("[WARN] No room data to write")

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