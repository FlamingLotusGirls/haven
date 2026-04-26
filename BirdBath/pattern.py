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
        ring_radius = [3.0, 2.0, 1.0]  # Radius of each ring (outer, middle, inner)
        ring_base_angle = [math.pi/18.0, math.pi/12.0, math.pi/6.0]  # Base angle offset for each ring
        pos_angle = [[0, math.pi/9.0, 2 * math.pi/9.0], [0, math.pi/6.0], [0]]  # Angle offset for each position in each ring
        
        # New nozzle ordering within each section (ring_idx, pos_within_ring):
        # Outer row (left to right): nozzles 1, 4, 6 → slots 0, 3, 5 → (ring 0, pos 0/1/2)
        # Middle row (left to right): nozzles 2, 5  → slots 1, 4 → (ring 1, pos 0/1)
        # Inner row: nozzle 3                        → slot 2     → (ring 2, pos 0)
        # So within each section the controller channel order maps to physical positions as:
        #   slot 0 → outer-left  (ring 0, pos 0)
        #   slot 1 → middle-left (ring 1, pos 0)
        #   slot 2 → inner       (ring 2, pos 0)
        #   slot 3 → outer-mid   (ring 0, pos 1)
        #   slot 4 → middle-right(ring 1, pos 1)
        #   slot 5 → outer-right (ring 0, pos 2)
        section_layout = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (0, 2)]
        
        for section_idx in range(0, 6):
            base_angle = -section_idx * math.tau / 6.0
            for (ring_idx, pos) in section_layout:
                full_angle = base_angle - ring_base_angle[ring_idx] - pos_angle[ring_idx][pos]
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
        # outer ring: slots 0, 3, 5 within each section
        result = [nozzle for i in range(0, len(self.nozzles), 6)
                  for nozzle in [self.nozzles[i+0], self.nozzles[i+3], self.nozzles[i+5]]]
      elif ring_idx == 1:
        # middle ring: slots 1, 4 within each section
        result = [nozzle for i in range(0, len(self.nozzles), 6)
                  for nozzle in [self.nozzles[i+1], self.nozzles[i+4]]]
      elif ring_idx == 2:
        # inner ring: slot 2 within each section
        result = [nozzle for i in range(0, len(self.nozzles), 6)
                  for nozzle in [self.nozzles[i+2]]]
      else:
        result = []

      return result

    def get_nozzles_at_position(self, ring_idx, position):
      if ring_idx == 0:
        # outer ring: pos 0 → slot 0, pos 1 → slot 3, pos 2 → slot 5
        section_pos = [0, 3, 5][position]
      elif ring_idx == 1:
        # middle ring: pos 0 → slot 1, pos 1 → slot 4
        section_pos = [1, 4][position]
      else:
        # inner ring: only pos 0 → slot 2
        section_pos = 2
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
