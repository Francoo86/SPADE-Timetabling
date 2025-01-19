from dataclasses import dataclass
from typing import Optional, Dict, List
from .static.agent_enums import Day, Actividad

@dataclass
class Asignatura:
    nombre: str
    nivel: int
    paralelo: str
    horas: int
    vacantes: int
    campus: str
    codigo_asignatura: str
    actividad: Actividad

    def __str__(self) -> str:
        return f"{self.nombre},{self.nivel},{self.paralelo},{self.horas},{self.vacantes},{self.campus},{self.codigo_asignatura}"

    # lets implement getters
    def get_nombre(self) -> str:
        return self.nombre
    
    def get_nivel(self) -> int:
        return self.nivel
    
    def get_paralelo(self) -> str:
        return self.paralelo
    
    def get_horas(self) -> int:
        return self.horas
    
    def get_vacantes(self) -> int:
        return self.vacantes
    
    def get_campus(self) -> str:
        return self.campus
    
    def get_codigo_asignatura(self) -> str:
        return self.codigo_asignatura
    
    def get_actividad(self) -> Actividad:
        return self.actividad

    @staticmethod
    def from_json(json_obj: dict) -> 'Asignatura':
        return Asignatura(
            nombre=json_obj["Nombre"],
            nivel=int(json_obj["Nivel"]),
            paralelo=json_obj["Paralelo"],
            horas=int(json_obj["Horas"]),
            vacantes=int(json_obj["Vacantes"]),
            campus=json_obj["Campus"],
            codigo_asignatura=json_obj["CodigoAsignatura"],
            actividad=Actividad[json_obj["Actividad"].upper()]
        )

@dataclass
class AsignacionSala:
    nombre_asignatura: str
    satisfaccion: int
    capacidad: float

    def get_nombre_asignatura(self) -> str:
        return self.nombre_asignatura

    def get_satisfaccion(self) -> int:
        return self.satisfaccion

    def get_capacidad(self) -> float:
        return self.capacidad

@dataclass
class AssignationData:
    ultimo_dia_asignado: Optional[Day] = None
    sala_asignada: Optional[str] = None
    ultimo_bloque_asignado: int = -1

    def clear(self) -> None:
        self.ultimo_dia_asignado = None
        self.sala_asignada = None
        self.ultimo_bloque_asignado = -1

    def assign(self, dia: Day, sala: str, bloque: int) -> None:
        self.ultimo_dia_asignado = dia
        self.sala_asignada = sala
        self.ultimo_bloque_asignado = bloque

    def get_ultimo_dia_asignado(self) -> Optional[Day]:
        return self.ultimo_dia_asignado

    def get_sala_asignada(self) -> str:
        return self.sala_asignada if self.sala_asignada is not None else ""

    def has_sala_asignada(self) -> bool:
        return self.sala_asignada is not None

    def set_sala_asignada(self, sala_asignada: str) -> None:
        self.sala_asignada = sala_asignada

    def get_ultimo_bloque_asignado(self) -> int:
        return self.ultimo_bloque_asignado

@dataclass
class BloqueInfo:
    campus: str
    bloque: int

    def __str__(self) -> str:
        return f"BloqueInfo{{campus='{self.campus}', bloque={self.bloque}}}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BloqueInfo):
            return False
        return (self.bloque == other.bloque and 
                self.campus == other.campus)

    def __hash__(self) -> int:
        result = hash(self.campus) if self.campus else 0
        result = 31 * result + self.bloque
        return result

    def get_campus(self) -> str:
        return self.campus

    def get_bloque(self) -> int:
        return self.bloque

    def set_campus(self, campus: str) -> None:
        self.campus = campus

    def set_bloque(self, bloque: int) -> None:
        self.bloque = bloque