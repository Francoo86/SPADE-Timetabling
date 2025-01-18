from dataclasses import dataclass
from typing import Dict, List
import jsonpickle

@dataclass
class ClassroomAvailability:
    """
    A class to hold classroom availability data.
    
    Attributes:
        codigo (str): The classroom code
        campus (str): The campus name
        capacidad (int): The classroom capacity
        available_blocks (Dict[str, List[int]]): Dictionary mapping days to lists of available blocks
    """
    codigo: str
    campus: str
    capacidad: int
    available_blocks: Dict[str, List[int]]

    def __init__(self, codigo: str, campus: str, capacidad: int, 
                 available_blocks: Dict[str, List[int]]):
        """
        Initialize a ClassroomAvailability instance.

        Args:
            codigo (str): The classroom code
            campus (str): The campus name
            capacidad (int): The classroom capacity
            available_blocks (Dict[str, List[int]]): Dictionary mapping days to lists of available blocks
        """
        self.codigo = codigo
        self.campus = campus
        self.capacidad = capacidad
        self.available_blocks = available_blocks

    def get_codigo(self) -> str:
        """Get the classroom code."""
        return self.codigo

    def get_campus(self) -> str:
        """Get the campus name."""
        return self.campus

    def get_capacidad(self) -> int:
        """Get the classroom capacity."""
        return self.capacidad

    def get_available_blocks(self) -> Dict[str, List[int]]:
        """Get the dictionary of available blocks by day."""
        return self.available_blocks

    def save_to_file(self, filename: str) -> None:
        """
        Save the classroom availability data to a file using pickle.
        
        Args:
            filename (str): The name of the file to save to
        """
        with open(filename, 'wb') as f:
            jsonpickle.dumps(self, f)

    @classmethod
    def load_from_file(cls, filename: str) -> 'ClassroomAvailability':
        """
        Load classroom availability data from a file.
        
        Args:
            filename (str): The name of the file to load from
            
        Returns:
            ClassroomAvailability: The loaded classroom availability instance
        """
        with open(filename, 'rb') as f:
            return jsonpickle.loads(f.read())

    def __str__(self) -> str:
        """Return a string representation of the classroom availability."""
        return (f"ClassroomAvailability(codigo='{self.codigo}', "
                f"campus='{self.campus}', capacidad={self.capacidad}, "
                f"available_blocks={self.available_blocks})")