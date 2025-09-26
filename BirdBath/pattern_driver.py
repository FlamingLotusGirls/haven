import numpy as np
import yaml
import os
import socket
import struct
from typing import List, Tuple, Dict


class PatternDriver:
    """
    Concrete class for pattern drivers that receive and process final frame data.
    """
    
    def __init__(self, config_file: str = 'driver_config.yaml'):
        """
        Initialize the PatternDriver with configuration.
        
        Args:
            config_file (str): Path to the YAML configuration file containing controller IPs and ranges
        """
        self.config_file = config_file
        self.controllers, self.ranges = self._load_configuration()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.artnet_port = 6454  # Standard Artnet port
        self.sequence = 0  # Artnet sequence counter
    
    def _load_configuration(self) -> Tuple[List[Dict], List[Tuple[float, float]]]:
        """
        Load configuration from YAML file containing controller IPs and 36 pairs of [start, end] values.
        
        Returns:
            Tuple[List[Dict], List[Tuple[float, float]]]: Controller info and list of 36 (start, end) tuples
            
        Raises:
            FileNotFoundError: If the configuration file doesn't exist
            yaml.YAMLError: If the configuration file is not valid YAML
            ValueError: If the configuration format is invalid
        """
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(f"PatternDriver configuration file not found: {self.config_file}")
        
        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            # Configuration should be a dictionary with 'controllers' and 'ranges' keys
            if not isinstance(config, dict):
                raise ValueError("Configuration must be a dictionary")
            
            if 'controllers' not in config or 'ranges' not in config:
                raise ValueError("Configuration must contain 'controllers' and 'ranges' keys")
            
            # Validate controllers
            controllers = config['controllers']
            if not isinstance(controllers, list) or len(controllers) != 3:
                raise ValueError("Configuration must contain exactly 3 controllers")
            
            for i, controller in enumerate(controllers):
                if not isinstance(controller, dict) or 'ip' not in controller:
                    raise ValueError(f"Controller {i} must have an 'ip' field")
            
            # Validate ranges
            ranges_config = config['ranges']
            if not isinstance(ranges_config, list) or len(ranges_config) != 36:
                raise ValueError(f"Configuration must contain exactly 36 ranges, found {len(ranges_config)}")
            
            ranges = []
            for i, pair in enumerate(ranges_config):
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError(f"Range {i} must be a [start, end] pair, got: {pair}")
                
                start, end = pair
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                    raise ValueError(f"Start and end values must be numbers in range {i}: {pair}")
                
                ranges.append((float(start), float(end)))
            
            print(f"PatternDriver loaded configuration: 3 controllers, 36 ranges from {self.config_file}")
            return controllers, ranges
            
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Invalid YAML in PatternDriver configuration file: {str(e)}")
    
    def _create_artnet_packet(self, universe: int, data: List[Tuple[bool, float]]) -> bytes:
        """
        Create an Artnet packet with the given data.
        
        Args:
            universe (int): Artnet universe number
            data (List[Tuple[bool, float]]): List of (bool, float) tuples for the packet
            
        Returns:
            bytes: Complete Artnet packet
        """
        # Artnet header
        header = b"Art-Net\x00"  # 8 bytes
        opcode = struct.pack("<H", 0x5000)  # ArtDMX opcode (little endian)
        protocol_version = struct.pack(">H", 14)  # Protocol version (big endian)
        sequence = struct.pack("B", self.sequence)  # Sequence
        physical = struct.pack("B", 0)  # Physical input/output port
        universe_bytes = struct.pack("<H", universe)  # Universe (little endian)
        
        # Data length (2 bytes per tuple: 1 byte bool + 1 byte for float as byte)
        data_length = struct.pack(">H", len(data) * 2)  # Big endian
        
        # Pack data as series of [bool, float] where bool is always 0 and float is converted to byte
        packet_data = bytearray()
        for bool_val, float_val in data:
            packet_data.append(0)  # Bool is always 0 (false)
            # Convert float to byte (0-255 range)
            byte_val = max(0, min(255, int(float_val)))
            packet_data.append(byte_val)
        
        # Combine all parts
        packet = header + opcode + protocol_version + sequence + physical + universe_bytes + data_length + packet_data
        
        # Update sequence counter
        self.sequence = (self.sequence + 1) % 256
        
        return packet
    
    def Frame(self, frame_data: np.ndarray) -> None:
        """
        Process final frame data and send Artnet packets to controllers.
        
        Args:
            frame_data (np.ndarray): A 36-element numpy array of floats with values in [-1.0, 1.0]
        """
        if len(frame_data) != 36:
            print(f"Warning: Expected 36 values, got {len(frame_data)}")
            return
        
        # Map each frame value from [-1.0, 1.0] to its corresponding [start, end] range
        mapped_values = []
        for i, value in enumerate(frame_data):
            if i < len(self.ranges):
                start, end = self.ranges[i]
                # Map from [-1.0, 1.0] to [start, end]
                mapped_value = start + (value + 1.0) * (end - start) / 2.0
                mapped_values.append(mapped_value)
            else:
                mapped_values.append(value)  # Fallback if not enough ranges
        
        # Split data into 3 groups of 12 channels each and send to controllers
        for controller_idx, controller in enumerate(self.controllers):
            start_channel = controller_idx * 12
            end_channel = start_channel + 12
            
            # Create data tuples for this controller (12 channels)
            controller_data = []
            for i in range(start_channel, end_channel):
                if i < len(mapped_values):
                    # Each tuple is [bool, float] where bool is always False
                    controller_data.append((False, mapped_values[i]))
                else:
                    controller_data.append((False, 0.0))  # Fallback
            
            # Create and send Artnet packet
            try:
                packet = self._create_artnet_packet(controller_idx, controller_data)
                self.socket.sendto(packet, (controller['ip'], self.artnet_port))
            except Exception as e:
                print(f"Error sending Artnet packet to controller {controller_idx} ({controller['ip']}): {str(e)}")
        
        # Log status occasionally
        if hasattr(self, '_frame_count'):
            self._frame_count += 1
        else:
            self._frame_count = 1
            
        if self._frame_count % 100 == 0:
            mapped_array = np.array(mapped_values)
            print(f"PatternDriver sent frame {self._frame_count}: input range [{frame_data.min():.3f}, {frame_data.max():.3f}] -> output range [{mapped_array.min():.3f}, {mapped_array.max():.3f}]")
    
    def __del__(self):
        """
        Clean up socket when object is destroyed.
        """
        if hasattr(self, 'socket'):
            self.socket.close()
