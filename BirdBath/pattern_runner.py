import importlib
import inspect
import numpy as np
from typing import Type, Any
from pattern import Pattern


class PatternRunner:
    """
    A class that instantiates and runs Pattern-derived classes by name.
    """
    
    def __init__(self, pattern_class_name: str):
        """
        Initialize PatternRunner with a Pattern-derived class name.
        
        Args:
            pattern_class_name (str): Name of the class derived from Pattern
        """
        self.pattern_class_name = pattern_class_name
        self.values_array = np.zeros(36, dtype=np.float64)  # Create shared numpy array
        self.pattern_instance = self._instantiate_pattern_class()
    
    def _instantiate_pattern_class(self) -> Pattern:
        """
        Instantiate the Pattern-derived class by name.
        
        Returns:
            Pattern: An instance of the specified Pattern-derived class
            
        Raises:
            ImportError: If the class cannot be imported
            AttributeError: If the class doesn't exist in the module
            TypeError: If the class is not derived from Pattern
        """
        try:
            # Try to import from the current module/namespace first
            # This assumes the Pattern-derived class is available in the current scope
            current_module = importlib.import_module('__main__')
            
            # Check if the class exists in the current module
            if hasattr(current_module, self.pattern_class_name):
                pattern_class = getattr(current_module, self.pattern_class_name)
            else:
                # If not found in main, try to import from a module with various naming conventions
                module_names_to_try = [
                    self.pattern_class_name.lower(),  # TestPattern -> testpattern
                    # Convert CamelCase to snake_case: TestPattern -> test_pattern
                    ''.join(['_' + c.lower() if c.isupper() and i > 0 else c.lower() 
                            for i, c in enumerate(self.pattern_class_name)])
                ]
                
                pattern_class = None
                for module_name in module_names_to_try:
                    try:
                        module = importlib.import_module(module_name)
                        pattern_class = getattr(module, self.pattern_class_name)
                        break  # Successfully found the class
                    except (ImportError, AttributeError):
                        continue  # Try the next naming convention
                
                if pattern_class is None:
                    raise ImportError(f"Could not find class '{self.pattern_class_name}' in any of these modules: {module_names_to_try}")
            
            # Verify that the class is derived from Pattern
            if not (inspect.isclass(pattern_class) and issubclass(pattern_class, Pattern)):
                raise TypeError(f"Class '{self.pattern_class_name}' must be derived from Pattern")
            
            # Instantiate the class with the shared values array
            return pattern_class(self.values_array)
            
        except Exception as e:
            raise ImportError(f"Failed to instantiate '{self.pattern_class_name}': {str(e)}")
    
    def run_frame(self, input_value: float):
        """
        Run the Frame method on the instantiated pattern.
        
        Args:
            input_value (float): Input parameter for the Frame method
            
        Returns:
            np.ndarray: A 36-element numpy array of floats (the shared values array)
        """
        result = self.pattern_instance.Frame(input_value)
        # The Frame method should return the same array reference as self.values_array
        # but we return the result from Frame to maintain the interface
        return result
    
    def get_pattern_instance(self) -> Pattern:
        """
        Get the instantiated pattern instance.
        
        Returns:
            Pattern: The instantiated Pattern-derived class
        """
        return self.pattern_instance
