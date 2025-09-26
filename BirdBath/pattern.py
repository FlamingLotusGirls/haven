from abc import ABC, abstractmethod
import numpy as np
import math
from typing import List
from nozzle import Nozzle


class Pattern(ABC):
    """
    Abstract base class for patterns that generate frame data.
    """
    
    def __init__(self, values_array: np.ndarray):
        """
        Initialize the Pattern with 36 Nozzle objects and a shared values array.
        
        Args:
            values_array (np.ndarray): Shared 36-element numpy array for nozzle values
        """
        self.values_array = values_array
        self.nozzles = self._create_nozzles(values_array)
    
    def _create_nozzles(self, values_array: np.ndarray) -> List[Nozzle]:
        """
        Create the array of 36 Nozzle objects based on the physical layout.
        
        Args:
            values_array (np.ndarray): Shared numpy array for nozzle values
            
        Returns:
            List[Nozzle]: Array of 36 Nozzle objects
        """
        nozzles = []
        nozzle_idx = 0
        
        # Physical configuration of the nozzle layout
        ring_count = [3, 2, 1]  # Number of nozzles in each ring
        ring_radius = [3.0, 2.0, 1.0]  # Radius of each ring
        ring_base_angle = [math.pi/18.0, math.pi/12.0, math.pi/6.0]  # Base angle offset for each ring
        pos_angle = [[0, math.pi/9.0, 2 * math.pi/9.0], [0, math.pi/6.0], [0]]  # Angle offset for each position in each ring
        
        for section_idx in range(0, 6):
            base_angle = section_idx * math.tau / 6.0
            for ring_idx in range(0, 3):
                for pos in range(0, ring_count[ring_idx]):
                    full_angle = base_angle + ring_base_angle[ring_idx] + pos_angle[ring_idx][pos]
                    radius = ring_radius[ring_idx]
                    
                    x = math.sin(full_angle) * radius
                    y = math.cos(full_angle) * radius
                    
                    nozzle = Nozzle(idx=nozzle_idx, ring_idx=ring_idx, section_idx=section_idx,
                                  position=pos, x=x, y=y, values_array=values_array)
                    nozzles.append(nozzle)
                    nozzle_idx += 1
        
        return nozzles
    
    def get_nozzles_in_section(self, section_idx):
      if (section_idx >= 6 or section_idx < 0):
        return []
      return self.nozzles[6*section_idx: 6*section_idx + 6]

    def get_nozzles_in_ring(self, ring_idx):
      if ring_idx == 0:
        result = [nozzle for i in range(0, len(self.nozzles), 6) for nozzle in self.nozzles[i:i+3]]
      elif ring_idx == 1:
        result = [nozzle for i in range(0, len(self.nozzles), 6) for nozzle in self.nozzles[i+3:i+5]]
      elif ring_idx == 2:
        result = [nozzle for i in range(0, len(self.nozzles), 6) for nozzle in self.nozzles[i+5:i+6]]
      else:
        result = []

      return result

    def get_nozzles_at_position(self, ring_idx, position):
      if ring_idx == 0:
         section_pos = position 
      elif ring_idx == 1:
         section_pos = position + 3
      else:
         section_pos = 5
      return self.nozzles[section_pos::6]
    
    @abstractmethod
    def Frame(self, input: float) -> np.ndarray:
        """
        Abstract method to generate a frame of pattern data.
        
        Args:
            input (float): Input parameter for the frame generation
            
        Returns:
            np.ndarray: A 36-element numpy array of floats
        """
        pass
