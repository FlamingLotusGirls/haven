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
import math

# Hardware-specific imports only when not in test mode
TEST_MODE = False

def import_hardware_modules():
    """Import hardware-specific modules only when needed"""
    global board, busio, ADS, AnalogIn
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn


class MockChannel:
    """Mock ADC channel for test mode that generates sine wave data"""
    
    def __init__(self, frequency=0.1, amplitude=1.65, offset=-1.65):
        """
        Initialize mock channel with sine wave parameters
        
        Args:
            frequency: Sine wave frequency in Hz
            amplitude: Sine wave amplitude in volts
            offset: DC offset in volts
        """
        self.frequency = frequency
        self.amplitude = amplitude
        self.offset = offset
        self.start_time = time.time()
    
    @property
    def voltage(self):
        """Generate sine wave voltage based on current time"""
        current_time = time.time() - self.start_time
        sine_value = math.sin(2 * math.pi * self.frequency * current_time)
        return self.offset + self.amplitude * sine_value
    
    @property 
    def value(self):
        """Raw ADC value (not used in test mode but provided for compatibility)"""
        return int((self.voltage / 5.0) * 32767)  # Fake 16-bit value


class MockADS:
    """Mock ADS1115 for test mode"""
    
    def __init__(self, i2c=None, address=None):
        self.address = address 
        self.gain = 1


class MockAnalogIn:
    """Mock AnalogIn for test mode"""
    
    def __init__(self, ads, pos_pin, neg_pin):
        # Standard Mock channel - -3.3V to 0V, frequency 0.1
        self.mock_channel = MockChannel(frequency=0.1, amplitude=1.65, offset=-1.65)
    
    @property
    def voltage(self):
        return self.mock_channel.voltage
    
    @property
    def value(self):
        return self.mock_channel.value


class ADCReader:
    def __init__(self, config_file, debug=False, test_mode=False):
        """Initialize ADC reader with configuration from file"""
        self.debug = debug
        self.test_mode = test_mode
        global TEST_MODE
        TEST_MODE = test_mode
        
        if self.test_mode:
            if self.debug:
                print("Running in TEST MODE - using mock sine wave data")
        else:
            # Import hardware modules only when not in test mode
            import_hardware_modules()
        
        self.load_config(config_file)
        self.setup_adc()
        self.setup_named_pipe()
        
    def load_config(self, config_file):
        """Load configuration from JSON file"""
        import json  # Keep json for config loading
        with open(config_file, 'r') as f:
            self.config = json.load(f)
        
        # Validate required fields
        required_fields = ['address', 'channels', 'output_pipe', 'read_interval']
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
        """Initialize I2C and ADC with configured address (or mock in test mode)"""
        try:
            if self.test_mode:
                # Mock setup for test mode
                self.i2c = None  # Not needed in test mode
                self.ads = MockADS(address=self.config['address'])
                
                # Create mock channel objects
                self.channels = []
                for ch_config in self.config['channels']:
                    # Get pin names as strings for mock
                    pos_pin = ch_config['positive_pin']
                    neg_pin = ch_config['negative_pin']
                    
                    # Create mock AnalogIn 
                    channel = MockAnalogIn(self.ads, pos_pin, neg_pin)
                    
                    # Store channel with its configuration
                    self.channels.append({
                        'channel': channel,
                        'name': ch_config['name'],
                        'calibration': ch_config['calibration']
                    })
                
                if self.debug:
                    print(f"Mock ADC initialized with {len(self.channels)} channels generating sine wave data")
                    
            else:
                # Real hardware setup - keep original logic
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
                
                if self.debug:
                    print(f"ADC initialized at address {hex(address)} with {len(self.channels)} channels")
            
        except Exception as e:
            print(f"Error initializing ADC: {e}")
            sys.exit(1)
    
    def setup_named_pipe(self):
        """Create named pipe if it doesn't exist"""
        self.pipe_path = self.config['output_pipe']

        print(f"Creating named pipe {self.pipe_path}")
        
        # Create the pipe if it doesn't exist
        if not os.path.exists(self.pipe_path):
            try:
                os.mkfifo(self.pipe_path)
                if self.debug:
                    print(f"Created named pipe: {self.pipe_path}")
            except OSError as e:
                print(f"Error: Failed to create named pipe {self.pipe_path}: {e}", file=sys.stderr)
                sys.exit(1)
        elif self.debug:
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

        # print(data)
        
        # Pickle the object
        pickled_data = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        
        # Prepend with length of message (4 bytes, big-endian)
        length = len(pickled_data)
        message = struct.pack('>I', length) + pickled_data
        
        try:
            # Open pipe with O_WRONLY to avoid blocking if no reader
            fd = os.open(self.pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            
            # Use file locking to ensure atomic write
            # XXX when running in test mode on mac, I can't use this type of locking
            # Since test mode (currently, at least) has only one writer it should be
            # safe not to lock. 
            if not self.test_mode:
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                # Write the complete message atomically
                os.write(fd, message)
            finally:
                if not self.test_mode:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                
        except (BrokenPipeError, OSError) as e:
            # No reader on the other end, that's okay
            print(f"Problem sending to pipe {e}")
            # pass
    
    def run(self):
        """Main loop - read ADC values and send to pipes"""
        if self.debug:
            mode_str = "TEST MODE (sine wave)" if self.test_mode else "HARDWARE MODE"
            print(f"\nStarting ADC reader in {mode_str} with {self.config['read_interval']}s interval")
            print("Press Ctrl+C to stop\n")
        
        reading_count = 1
        last_debug_time = time.time()
        debug_interval = 1.0  # Print debug info once per second max
        
        try:
            while True:
                # Record start time of read cycle
                cycle_start = time.time()
                
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
                    
                    # Print status only in debug mode and at controlled rate
                    if self.debug and (time.time() - last_debug_time >= debug_interval):
                        print(f"[{reading_count:4d}] {name}: {voltage:.4f}V -> {calibrated_value:+.4f}")
                    
                    # Send to the shared pipe
                    self.send_to_pipe(name, calibrated_value)
                
                # Update debug timing
                if self.debug and (time.time() - last_debug_time >= debug_interval):
                    last_debug_time = time.time()
                
                # Calculate how long the reads took
                cycle_duration = time.time() - cycle_start
                
                # Sleep for the remaining time to maintain the desired interval
                sleep_time = self.config['read_interval'] - cycle_duration
                if sleep_time > 0:
                    time.sleep(sleep_time)
                # If reads took longer than the interval, no sleep (continuous reading)
                
                reading_count += 1
                
        except KeyboardInterrupt:
            if self.debug:
                print("\nADC reader stopped")
        except Exception as e:
            print(f"Error in main loop: {e}", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='ADS1115 ADC Reader with Named Pipe Support')
    parser.add_argument('config', help='Path to configuration file (JSON format)')
    parser.add_argument('--debug', '-d', action='store_true', 
                       help='Enable debug output (default: errors only)')
    parser.add_argument('--test', '-t', action='store_true',
                       help='Enable test mode with sine wave data (no hardware required)')
    
    args = parser.parse_args()
    
    # Check if config file exists
    if not os.path.exists(args.config):
        print(f"Error: Configuration file '{args.config}' not found", file=sys.stderr)
        sys.exit(1)
    
    # Create and run reader
    reader = ADCReader(args.config, debug=args.debug, test_mode=args.test)
    reader.run()


if __name__ == "__main__":
    main()
