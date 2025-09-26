#!/usr/bin/env python3
"""
ADS1115 ADC Reader with Named Pipe Queue Support
Reads from a single controller with two differential channels
Sends calibrated values (-1.0 to 1.0) to a named pipe
"""

import pickle
import argparse
import time
import os
import sys
import struct
import fcntl
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn


class ADCReader:
    def __init__(self, config_file):
        """Initialize ADC reader with configuration from file"""
        self.load_config(config_file)
        self.setup_adc()
        self.setup_named_pipes()
        
    def load_config(self, config_file):
        """Load configuration from JSON file"""
        import json  # Keep json for config loading
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # Validate required fields
        required_fields = ['address', 'gain', 'channels', 'output_pipe', 'read_interval']
        for field in required_fields:
            if field not in self.config:
                raise ValueError(f"Missing required field '{field}' in configuration")
        
        # Validate channels have calibration
        for channel in self.config['channels']:
            if 'calibration' not in channel:
                raise ValueError(f"Missing calibration for channel {channel.get('name', 'unnamed')}")
            if 'min_voltage' not in channel['calibration'] or 'max_voltage' not in channel['calibration']:
                raise ValueError(f"Calibration must have min_voltage and max_voltage for channel {channel.get('name', 'unnamed')}")
    
    def setup_adc(self):
        """Initialize I2C and ADC with configured address"""
        try:
            # Create I2C bus
            self.i2c = busio.I2C(board.SCL, board.SDA)
            
            # Create ADS object with configured address
            # Convert hex string to integer if needed
            address = self.config['address']
            if isinstance(address, str):
                address = int(address, 16)
            
            self.ads = ADS.ADS1115(self.i2c, address=address)
            
            # Set gain
            self.ads.gain = self.config['gain']
            
            # Create channel objects
            self.channels = []
            for ch_config in self.config['channels']:
                # Get positive and negative pins
                pos_pin = getattr(ADS, ch_config['positive_pin'])
                neg_pin = getattr(ADS, ch_config['negative_pin'])
                
                # Create AnalogIn object
                channel = AnalogIn(self.ads, pos_pin, neg_pin)
                
                # Store channel with its configuration
                self.channels.append({
                    'channel': channel,
                    'name': ch_config['name'],
                    'calibration': ch_config['calibration']
                })
            
            print(f"ADC initialized at address {hex(address)} with {len(self.channels)} channels")
            
        except Exception as e:
            print(f"Error initializing ADC: {e}")
            sys.exit(1)
    
    def setup_named_pipes(self):
        """Create named pipe if it doesn't exist"""
        self.pipe_path = self.config['output_pipe']
        
        # Create the pipe if it doesn't exist
        if not os.path.exists(self.pipe_path):
            try:
                os.mkfifo(self.pipe_path)
                print(f"Created named pipe: {self.pipe_path}")
            except OSError as e:
                print(f"Failed to create named pipe {self.pipe_path}: {e}")
                sys.exit(1)
        else:
            print(f"Using existing named pipe: {self.pipe_path}")
    
    def calibrate_value(self, voltage, calibration):
        """
        Convert voltage to calibrated value between -1.0 and 1.0
        
        Args:
            voltage: Raw voltage reading from ADC
            calibration: Dict with min_voltage and max_voltage
        
        Returns:
            Float value between -1.0 and 1.0
        """
        min_v = calibration['min_voltage']
        max_v = calibration['max_voltage']
        
        # Clamp voltage to calibration range
        voltage = max(min_v, min(max_v, voltage))
        
        # Map from [min_v, max_v] to [-1.0, 1.0]
        # Formula: output = 2 * ((input - min) / (max - min)) - 1
        if max_v != min_v:
            normalized = (voltage - min_v) / (max_v - min_v)  # 0 to 1
            calibrated = 2.0 * normalized - 1.0  # -1 to 1
        else:
            calibrated = 0.0  # Avoid division by zero
        
        return calibrated
    
    def send_to_pipe(self, channel_name, value):
        """
        Send a pickled Python object through a named pipe
        
        The object contains:
        - channel: String identifier for the channel
        - value: Float between -1.0 and 1.0
        - timestamp: Unix timestamp
        
        Uses file locking to ensure atomic writes with multiple writers
        """
        data = {
            'channel': channel_name,
            'value': value,
            'timestamp': time.time()
        }
        
        # Pickle the object
        pickled_data = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        
        # Prepend with length of message (4 bytes, big-endian)
        length = len(pickled_data)
        message = struct.pack('>I', length) + pickled_data
        
        try:
            # Open pipe with O_WRONLY to avoid blocking if no reader
            fd = os.open(self.pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            
            # Use file locking to ensure atomic write
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                # Write the complete message atomically
                os.write(fd, message)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                
        except (BrokenPipeError, OSError):
            # No reader on the other end, that's okay
            pass
    
    def run(self):
        """Main loop - read ADC values and send to pipes"""
        print(f"\nStarting ADC reader with {self.config['read_interval']}s interval")
        print("Press Ctrl+C to stop\n")
        
        reading_count = 1
        
        try:
            while True:
                # Read each channel
                for i, ch_info in enumerate(self.channels):
                    channel = ch_info['channel']
                    name = ch_info['name']
                    calibration = ch_info['calibration']
                    
                    # Get voltage reading
                    voltage = channel.voltage
                    raw_value = channel.value
                    
                    # Calibrate to -1.0 to 1.0 range
                    calibrated_value = self.calibrate_value(voltage, calibration)
                    
                    # Print status
                    print(f"[{reading_count:4d}] {name}: {voltage:.4f}V (raw: {raw_value:5d}) -> {calibrated_value:+.4f}")
                    
                    # Send to the shared pipe
                    self.send_to_pipe(name, calibrated_value)
                
                reading_count += 1
                time.sleep(self.config['read_interval'])
                
        except KeyboardInterrupt:
            print("\nADC reader stopped")
        except Exception as e:
            print(f"Error in main loop: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='ADS1115 ADC Reader with Named Pipe Support')
    parser.add_argument('config', help='Path to configuration file (JSON format)')
    parser.add_argument('--test-pipes', action='store_true', 
                       help='Test mode: print pipe data instead of writing')
    
    args = parser.parse_args()
    
    # Check if config file exists
    if not os.path.exists(args.config):
        print(f"Error: Configuration file '{args.config}' not found")
        sys.exit(1)
    
    # Create and run reader
    reader = ADCReader(args.config)
    reader.run()


if __name__ == "__main__":
    main()
