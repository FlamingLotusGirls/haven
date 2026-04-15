import math
import numpy as np


class Nozzle:
    """
    Class representing a nozzle with position and control information.
    """
    
    def __init__(self, idx: int, ring_idx: int, section_idx: int, position: int, x: float, y: float, values_array: np.ndarray):
        """
        Initialize a Nozzle with all required parameters.
        
        Args:
            idx (int): The index identifier for this nozzle
            ring_idx (int): The ring index this nozzle belongs to
            section_idx (int): The section index within the ring
            position (int): The position identifier
            x (float): The x coordinate
            y (float): The y coordinate
            values_array (np.ndarray): Shared numpy array for values (36 elements)
        """
        self.idx = idx
        self.ring_idx = ring_idx
        self.section_idx = section_idx
        self.position = position
        self.x = x
        self.y = y
        self.angle = math.atan2(x, y)  # Calculate and cache angle during construction
        self._values_array = values_array  # Reference to shared numpy array
    
    def get_value(self) -> float:
        """
        Get the current value of the nozzle from the shared array.
        
        Returns:
            float: The current value
        """
        return float(self._values_array[self.idx])
    
    def set_value(self, value: float) -> None:
        """
        Set the value of the nozzle in the shared array.
        
        Args:
            value (float): The new value to set
        """
        self._values_array[self.idx] = value
    
    # Property-style access for value (alternative to get/set methods)
    @property
    def value(self) -> float:
        """Property getter for value."""
        return self.get_value()
    
    @value.setter
    def value(self, value: float) -> None:
        """Property setter for value."""
        self.set_value(value)
    
    def __str__(self) -> str:
        """
        String representation of the nozzle.
        
        Returns:
            str: String description of the nozzle
        """
        return f"Nozzle(idx={self.idx}, ring={self.ring_idx}, section={self.section_idx}, pos={self.position}, x={self.x:.2f}, y={self.y:.2f}, angle={self.angle:.3f}, value={self.get_value():.3f})"
    
    def __repr__(self) -> str:
        """
        Detailed string representation of the nozzle.
        
        Returns:
            str: Detailed string representation
        """
        return self.__str__()
