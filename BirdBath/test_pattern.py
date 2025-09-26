import numpy as np
import math
import time
from pattern import Pattern


class TestPattern(Pattern):
    """
    A concrete Pattern implementation that sweeps a sine wave through nozzles based on their angles.
    """
    
    def __init__(self, values_array: np.ndarray):
        """
        Initialize TestPattern with a sine wave frequency.
        
        Args:
            values_array (np.ndarray): Shared 36-element numpy array for nozzle values
        """
        super().__init__(values_array)
        self.frequency = 0.3  # Hard-coded frequency
        self.start_time = time.time()  # Record creation time
    
    def Frame(self, input: float) -> np.ndarray:
        """
        Generate a frame of sine wave pattern data based on nozzle angles.
        
        Args:
            input (float): Input parameter for the frame generation (not used in this pattern)
            
        Returns:
            np.ndarray: A 36-element numpy array of floats
        """
        # Calculate current time since pattern creation
        current_time = time.time() - self.start_time
        
        # Generate sine wave values for each nozzle based on its angle
        for nozzle in self.nozzles:
            # Calculate sine value: sin(angle + frequency * time)
            sine_value = math.sin(nozzle.angle + self.frequency * current_time)
            
            # Set the value directly in the shared array via the nozzle
            nozzle.set_value(sine_value)
        
        # Return the shared values array
        return self.values_array
