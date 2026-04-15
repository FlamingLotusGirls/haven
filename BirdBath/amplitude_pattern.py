import numpy as np
import math
import time
from pattern import Pattern


class AmplitudePattern(Pattern):
    """
    A concrete Pattern implementation that sets the amplitude of all the valves in response to
    the input.
    """

    def __init__(self, values_array: np.ndarray):
        """
        Initialize TestPattern with a sine wave frequency.

        Args:
            values_array (np.ndarray): Shared 36-element numpy array for nozzle values
        """
        super().__init__(values_array)

    def Frame(self, input_value: float) -> np.ndarray:
        """
        Nozzle output strictly follows the input.

        Args:
            input (float): Input parameter for the frame generation

        Returns:
            np.ndarray: A 36-element numpy array of floats
        """
        self.values_array.fill(input_value)

        # Return the shared values array
        return self.values_array
