# ADC Reader System for ADS1115

This system reads values from ADS1115 ADC controllers over I2C and sends calibrated values (-1.0 to 1.0) through named pipes for inter-process communication.

## Features

- Reads from individual ADS1115 controllers (supports 3 controllers at addresses 0x48, 0x49, 0x4a)
- Each controller reads 2 differential channels
- Calibration system to map voltage ranges to -1.0 to 1.0
- Named pipes (FIFOs) for inter-process communication with multiple writer support
- Systemd service templates for auto-starting
- JSON-based configuration files

## Files

### Main Programs

- `adc_reader.py` - Main ADC reader program that continuously reads values and sends to named pipes
- `calibrate_adc.py` - Interactive calibration tool to set min/max voltage values
- `pipe_reader_test.py` - Test program to read and display data from named pipes

### Configuration Files

- `adc_config_1.json` - Configuration for controller 1 (address 0x48)
- `adc_config_2.json` - Configuration for controller 2 (address 0x49)
- `adc_config_3.json` - Configuration for controller 3 (address 0x4a)

### Systemd Services

- `systemd/adc-reader-1.service` - Service for controller 1
- `systemd/adc-reader-2.service` - Service for controller 2
- `systemd/adc-reader-3.service` - Service for controller 3

## Configuration File Format

```json
{
  "address": "0x48",        // I2C address of the ADS1115
  "gain": 1,                // ADC gain setting
  "channels": [
    {
      "name": "controller1_channel1",  // Unique name for this channel
      "positive_pin": "P0",  // Positive differential input
      "negative_pin": "P1",  // Negative differential input
      "calibration": {
        "min_voltage": 0.0,  // Voltage that maps to -1.0
        "max_voltage": 3.3   // Voltage that maps to +1.0
      }
    },
    // ... more channels
  ],
  "output_pipe": "/tmp/beertap_pipe",  // Shared named pipe for all writers
  "read_interval": 0.05       // Seconds between readings
}
```

## Usage

### Running a Single ADC Reader

```bash
# Make the scripts executable
chmod +x adc_reader.py
chmod +x calibrate_adc.py
chmod +x pipe_reader_test.py

# Run ADC reader for controller 1 (silent mode - errors only)
./adc_reader.py adc_config_1.json

# Run with debug output (shows readings once per second)
./adc_reader.py adc_config_1.json --debug
```

### Calibrating Channels

The calibration tool offers automatic and manual calibration modes:

#### Automatic Calibration (Recommended)
The automatic mode tracks min/max values while you move the control through its range:

```bash
# Interactive mode with automatic calibration option
./calibrate_adc.py adc_config_1.json
# Then select 'A' for automatic calibration

# Quick automatic calibration for channel 1
./calibrate_adc.py adc_config_1.json --quick 1 --set auto
```

During automatic calibration:
1. Move your control smoothly between minimum and maximum positions
2. The system tracks the lowest and highest values in real-time
3. Press Enter when you've covered the full range
4. Confirm to save the tracked values

#### Manual Calibration
For precise control or specific voltage values:

```bash
# Set current reading as minimum for channel 1
./calibrate_adc.py adc_config_1.json --quick 1 --set min

# Set current reading as maximum for channel 2
./calibrate_adc.py adc_config_1.json --quick 2 --set max
```

### Testing Pipe Communication

In one terminal, run the ADC reader:
```bash
./adc_reader.py adc_config_1.json
```

In another terminal, run the pipe reader test:
```bash
# Read from the default shared pipe
./pipe_reader_test.py

# Read from a custom pipe with verbose output
./pipe_reader_test.py /tmp/my_custom_pipe -v
```

### Installing as Systemd Services

1. Copy the service files to systemd directory:
```bash
sudo cp systemd/adc-reader-*.service /etc/systemd/system/
```

2. Reload systemd daemon:
```bash
sudo systemctl daemon-reload
```

3. Enable services to start on boot:
```bash
sudo systemctl enable adc-reader-1.service
sudo systemctl enable adc-reader-2.service
sudo systemctl enable adc-reader-3.service
```

4. Start the services:
```bash
sudo systemctl start adc-reader-1.service
sudo systemctl start adc-reader-2.service
sudo systemctl start adc-reader-3.service
```

5. Check service status:
```bash
sudo systemctl status adc-reader-1.service
sudo systemctl status adc-reader-2.service
sudo systemctl status adc-reader-3.service
```

6. View logs:
```bash
sudo journalctl -u adc-reader-1.service -f
```

## Named Pipe Data Format

Data is sent through a single shared named pipe as pickled Python objects with a 4-byte length header. The pipe supports multiple uncoordinated writers using file locking for atomic writes.

The Python object contains:
```python
{
  "channel": "controller1_channel1",  # Unique channel name from config
  "value": 0.5432,                    # Calibrated value (-1.0 to 1.0)
  "timestamp": 1635789012.345         # Unix timestamp
}
```

The message format:
1. 4 bytes (big-endian uint32): Length of pickled data
2. N bytes: Pickled Python object (using pickle protocol)

## Reading from Named Pipes in Your Application

Example Python code to read from the shared pipe:

```python
import struct
import pickle
import os

class PipeReader:
    def __init__(self, pipe_path='/tmp/adc_pipe_main'):
        self.pipe_path = pipe_path
        self.buffer = b''
        
        # Open pipe for reading
        self.pipe_fd = os.open(pipe_path, os.O_RDONLY)
    
    def read_messages(self):
        """Read and yield messages from the pipe"""
        # Read available data
        chunk = os.read(self.pipe_fd, 4096)
        if not chunk:
            return
        
        self.buffer += chunk
        
        # Process complete messages from buffer
        while len(self.buffer) >= 4:
            # Read length header
            length = struct.unpack('>I', self.buffer[:4])[0]
            
            # Check if we have the complete message
            if len(self.buffer) >= 4 + length:
                # Extract and unpickle the message
                pickled_data = self.buffer[4:4+length]
                self.buffer = self.buffer[4+length:]
                
                data = pickle.loads(pickled_data)
                yield data
            else:
                break

# Example usage
reader = PipeReader('/tmp/adc_pipe_main')
for message in reader.read_messages():
    print(f"Channel: {message['channel']}")
    print(f"Value: {message['value']}")
    print(f"Timestamp: {message['timestamp']}")
```

## Hardware Setup

The system expects ADS1115 ADCs connected via I2C:
- Controller 1: Address 0x48
- Controller 2: Address 0x49  
- Controller 3: Address 0x4a

Each controller reads two differential channels:
- Channel 1: P0 (positive) and P1 (negative)
- Channel 2: P2 (positive) and P3 (negative)

## Dependencies

Install required Python packages using the provided requirements file:
```bash
pip3 install -r beertaps/requirements.txt
```

Or install manually:
```bash
pip3 install adafruit-circuitpython-ads1x15 adafruit-blinka
```

## Troubleshooting

1. **Permission errors on I2C**: Add user to i2c group:
   ```bash
   sudo usermod -a -G i2c $USER
   ```

2. **Named pipe already exists**: The programs will use existing pipes. To recreate:
   ```bash
   rm /tmp/adc_pipe_main
   ```

3. **Multiple writers conflict**: The system uses file locking (fcntl) to ensure atomic writes when multiple ADC readers write to the same pipe. Each write is guaranteed to be complete and not interleaved with other writers.

4. **No data on pipes**: Check that the ADC reader is running and the I2C devices are connected properly:
   ```bash
   i2cdetect -y 1
   ```

5. **Service not starting**: Check logs for errors:
   ```bash
   sudo journalctl -u adc-reader-1.service -n 50
   ```

## License

This project is part of the Haven BirdBath system.
