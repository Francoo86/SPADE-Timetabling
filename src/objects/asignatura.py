from dataclasses import dataclass
from typing import List
import logging

@dataclass
class Asignatura:
    """
    Represents a course or subject with its attributes.
    
    Attributes:
        nombre (str): Name of the subject
        nivel (int): Level of the subject
        semestre (int): Semester when the subject is taught
        horas (int): Hours of instruction
        vacantes (int): Available spots
    """
    nombre: str
    nivel: int
    semestre: int
    horas: int
    vacantes: int

    def __str__(self) -> str:
        """Convert the Asignatura object to a string representation."""
        return f"{self.nombre},{self.nivel},{self.semestre},{self.horas},{self.vacantes}"
    
    @property
    def get_nombre(self) -> str:
        """Get the name of the subject."""
        return self.nombre
    
    @property
    def get_vacantes(self) -> int:
        """Get the number of available spots."""
        return self.vacantes
    
    @property
    def get_horas(self) -> int:
        """Get the number of hours."""
        return self.horas
    
    @classmethod
    def from_string(cls, string: str) -> 'Asignatura':
        """
        Create an Asignatura instance from a string representation.
        
        Args:
            string (str): String representation of Asignatura
            
        Returns:
            Asignatura: New instance created from the string
            
        Raises:
            ValueError: If the string format is invalid
        """
        logging.debug(f"Parsing: {string}")
        try:
            parts = string.split(',')
            logging.debug(f"Parts: {parts}")
            
            if len(parts) != 5:
                raise ValueError(f"Expected 5 parts, got {len(parts)}")
                
            return cls(
                nombre=parts[0],
                nivel=int(parts[1]),
                semestre=int(parts[2]),
                horas=int(parts[3]),
                vacantes=int(parts[4])
            )
        except Exception as e:
            raise ValueError(f"Error parsing Asignatura string: {e}")

    @classmethod
    def parse_asignatura_by_name_cap(cls, crude_string: str) -> 'Asignatura':
        """
        Create an Asignatura instance from a string containing only name and capacity.
        
        Args:
            crude_string (str): String containing name and capacity
            
        Returns:
            Asignatura: New instance with default values except for name and capacity
            
        Raises:
            ValueError: If the string format is invalid
        """
        try:
            partes = crude_string.strip().split(',')
            if len(partes) != 2:
                raise ValueError(f"Expected 2 parts (name,capacity), got {len(partes)}")
                
            return cls(
                nombre=partes[0],
                nivel=0,
                semestre=0,
                horas=0,
                vacantes=int(partes[1])
            )
        except Exception as e:
            raise ValueError(f"Error parsing name and capacity string: {e}")