# import enums
from enum import Enum

class TipoContrato(Enum):
    JORNADA_COMPLETA = 0
    MEDIA_JORNADA = 1
    JORNADA_PARCIAL = 2
    
class Actividad(Enum):
    TEORIA = 0
    LABORATORIO = 1
    PRACTICA = 2
    TALLER = 3
    AYUDANTIA = 4
    TUTORIA = 5
    
ACTIVIDAD_MAPPING = {
    "teo": Actividad.TEORIA,
    "lab": Actividad.LABORATORIO,
    "pra": Actividad.PRACTICA,
    "tal": Actividad.TALLER,
    "ayu": Actividad.AYUDANTIA,
    "tut": Actividad.TUTORIA
}

# Move the translation function outside the Enum
def translate_actividad(activity: str) -> Actividad:
    return ACTIVIDAD_MAPPING.get(activity.lower(), Actividad.TEORIA)

class NegotiationState(Enum):
    SETUP = 0
    COLLECTING_PROPOSALS = 1
    EVALUATING_PROPOSALS = 2
    FINISHED = 3
    
class Day(str, Enum):
    LUNES = "LUNES"
    MARTES = "MARTES"
    MIERCOLES = "MIERCOLES"
    JUEVES = "JUEVES"
    VIERNES = "VIERNES"

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