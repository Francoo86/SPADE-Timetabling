# import enums
from enum import Enum

class TipoContrato(Enum):
    JORNADA_COMPLETA = 1
    MEDIA_JORNADA = 2
    JORNADA_PARCIAL = 3
    
class Actividad(Enum):
    TEORIA = 1
    LABORATORIO = 2
    PRACTICA = 3
    TALLER = 4
    AYUDANTIA = 5
    TUTORIA = 6
    
class Day(str, Enum):
    LUNES = "Lunes"
    MARTES = "Martes"
    MIERCOLES = "Miercoles"
    JUEVES = "Jueves"
    VIERNES = "Viernes"

    @property
    def display_name(self):
        return self.value

    @classmethod
    def from_string(cls, day : str):
        try:
            return cls[day.upper()]
        except KeyError:
            # Handle display names
            for d in cls:
                if d.value.lower() == day.lower():
                    return d
            raise ValueError(f"No matching day found for: {day}")