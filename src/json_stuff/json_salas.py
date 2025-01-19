from typing import Dict, Any
import json
import asyncio
import aiofiles
from pathlib import Path
import os

class RoomScheduleJSON:
    _instance = None
    _lock = asyncio.Lock()
    WRITE_THRESHOLD = 20  # Same as JADE implementation

    def __init__(self):
        self._pending_updates: Dict[str, Dict] = {}
        self._all_room_codes = set()
        self._update_count = 0
        self._write_lock = asyncio.Lock()
        self._output_path = Path(os.getcwd()) / "agent_output"
        self._output_path.mkdir(exist_ok=True)

    @classmethod
    async def get_instance(cls):
        if not cls._instance:
            async with cls._lock:
                if not cls._instance:
                    cls._instance = cls()
        return cls._instance

    async def add_room_schedule(self, codigo: str, campus: str, schedule_data: Dict[str, Any]) -> None:
        """
        Add or update a room's schedule
        Similar to agregarHorarioSala in JADE version
        """
        try:
            print(f"[DEBUG] Adding/updating schedule for room {codigo}")

            # Count assignments
            assignment_count = sum(
                1 for day_assignments in schedule_data["horario"].values()
                for assignment in day_assignments if assignment
            )

            print(f"[DEBUG] Room {codigo} has {assignment_count} total assignments")

            # Store update in memory
            async with self._write_lock:
                self._pending_updates[codigo] = schedule_data
                self._all_room_codes.add(codigo)
                self._update_count += 1

                # Check if we should write to disk
                if self._update_count >= self.WRITE_THRESHOLD:
                    await self._flush_updates()

        except Exception as e:
            print(f"[ERROR] Error adding classroom schedule for {codigo}: {str(e)}")
            raise

    async def _flush_updates(self) -> None:
        """Write pending updates to file"""
        if not await self._write_lock.acquire():
            return

        try:
            if not self._pending_updates:
                return

            json_array = list(self._pending_updates.values())
            
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
        finally:
            self._write_lock.release()

    async def generate_json_file(self) -> None:
        """
        Generate final JSON file with all room schedules
        Similar to generarArchivoJSON in JADE version
        """
        async with self._write_lock:
            await self._flush_updates()

            json_array = []
            for room_code in self._all_room_codes:
                sala_json = self._pending_updates.get(room_code, {"Codigo": room_code, "Asignaturas": []})
                json_array.append(sala_json)

            if json_array:
                output_file = self._output_path / "Horarios_salas.json"
                async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                    await f.write(json.dumps(json_array, indent=2, ensure_ascii=False))
                print(f"Generated final Horarios_salas.json with {len(json_array)} salas")

                for sala in json_array:
                    codigo = sala.get("Codigo", "Unknown")
                    asignaturas = sala.get("Asignaturas", [])
                    print(f"Room {codigo}: {len(asignaturas)} assignments")

    async def force_flush(self) -> None:
        """Force write any pending updates to file"""
        async with self._write_lock:
            await self._flush_updates()

    def get_pending_update_count(self) -> int:
        """Get number of pending updates"""
        return len(self._pending_updates)