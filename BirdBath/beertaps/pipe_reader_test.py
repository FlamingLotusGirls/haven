#!/usr/bin/env python3
"""
Named Pipe Reader Test
Reads pickled data from the shared named pipe created by adc_reader.py instances
Shows a dashboard view with current values and staleness for each channel
"""

import pickle
import argparse
import struct
import os
import sys
import time
import select
import fcntl
import termios


class PipeReader:
    def __init__(self, pipe_path):
        """Initialize pipe reader with a single pipe path"""
        self.pipe_path = pipe_path
        self.pipe_fd = None
        self.buffer = b''  # Buffer for incomplete messages
        self.channels = {}  # Dict to store channel data and timestamps
        self.setup_pipe()
        
    def setup_pipe(self):
        """Open named pipe for reading"""
        if not os.path.exists(self.pipe_path):
            print(f"Warning: Pipe {self.pipe_path} does not exist. Creating it...")
            try:
                os.mkfifo(self.pipe_path)
            except OSError as e:
                print(f"Failed to create pipe {self.pipe_path}: {e}")
                sys.exit(1)
        
        # Open pipe in non-blocking mode for continuous reading
        try:
            self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY | os.O_NONBLOCK)
            # Set to blocking mode after opening
            flags = fcntl.fcntl(self.pipe_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.pipe_fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        except Exception as e:
            print(f"Failed to open pipe {self.pipe_path}: {e}")
            sys.exit(1)
    
    def read_messages(self):
        """Read and yield messages from the pipe buffer"""
        try:
            # Read available data
            chunk = os.read(self.pipe_fd, 4096)
            if not chunk:
                # Pipe closed, reopen it
                os.close(self.pipe_fd)
                self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY | os.O_NONBLOCK)
                flags = fcntl.fcntl(self.pipe_fd, fcntl.F_GETFL)
                fcntl.fcntl(self.pipe_fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                return
            
            self.buffer += chunk
            
            # Process complete messages from buffer
            while len(self.buffer) >= 4:
                # Try to read length header
                length = struct.unpack('>I', self.buffer[:4])[0]
                
                # Check if we have the complete message
                if len(self.buffer) >= 4 + length:
                    # Extract the message
                    pickled_data = self.buffer[4:4+length]
                    self.buffer = self.buffer[4+length:]
                    
                    # Unpickle the object
                    try:
                        data = pickle.loads(pickled_data)
                        yield data
                    except Exception as e:
                        if hasattr(self, 'verbose') and self.verbose:
                            print(f"Error unpickling data: {e}")
                else:
                    # Wait for more data
                    break
                    
        except (BlockingIOError, OSError):
            pass
        except Exception as e:
            if hasattr(self, 'verbose') and self.verbose:
                print(f"Error reading from pipe: {e}")
    
    def clear_screen(self):
        """Clear the terminal screen"""
        print("\033[2J\033[H", end='')
    
    def format_age(self, age):
        """Format age in seconds to a readable string"""
        if age < 1:
            return f"{age:.1f}s "
        elif age < 10:
            return f"{age:.1f}s "
        elif age < 60:
            return f"{int(age)}s  "
        elif age < 3600:
            return f"{int(age/60)}m  "
        else:
            return f"{int(age/3600)}h  "
    
    def get_value_bar(self, value, width=20):
        """Create a visual bar for the value (-1.0 to 1.0)"""
        # Normalize to 0-1 range
        normalized = (value + 1.0) / 2.0
        filled = int(normalized * width)
        
        # Create bar with center marker
        bar = ['─'] * width
        center = width // 2
        bar[center] = '┼'  # Center marker at 0
        
        # Fill the bar
        if value < 0:
            # Fill from center to left
            pos = int((1.0 + value) * center)
            for i in range(pos, center):
                bar[i] = '█'
        else:
            # Fill from center to right
            for i in range(center + 1, center + 1 + int(value * center)):
                if i < width:
                    bar[i] = '█'
        
        return ''.join(bar)
    
    def run(self):
        """Main loop - read from pipe and display dashboard"""
        self.clear_screen()
        print(f"ADC Channel Monitor - {self.pipe_path}")
        print("Press Ctrl+C to stop\n")
        
        last_display_time = time.time()
        display_interval = 0.1  # Update display 10 times per second
        
        try:
            while True:
                # Use select to wait for data with short timeout
                ready, _, _ = select.select([self.pipe_fd], [], [], 0.01)
                
                if ready:
                    # Read and process messages
                    for data in self.read_messages():
                        channel = data.get('channel', 'unknown')
                        value = data.get('value', 0.0)
                        timestamp = data.get('timestamp', time.time())
                        
                        # Store or update channel data
                        self.channels[channel] = {
                            'value': value,
                            'timestamp': timestamp,
                            'last_update': time.time()
                        }
                
                # Update display at controlled rate
                current_time = time.time()
                if current_time - last_display_time >= display_interval:
                    # Move cursor to home position
                    print("\033[H", end='')
                    
                    # Header
                    print(f"ADC Channel Monitor - {self.pipe_path}")
                    print("Press Ctrl+C to stop\n")
                    print(f"{'Channel':25s} {'Value':8s} {'Bar':<22s} {'Age':6s}")
                    print("─" * 65)
                    
                    # Sort channels by name for consistent display
                    sorted_channels = sorted(self.channels.keys())
                    
                    # Display each channel
                    for channel in sorted_channels:
                        data = self.channels[channel]
                        value = data['value']
                        age = current_time - data['last_update']
                        
                        # Color code based on staleness
                        if age < 0.5:
                            color = "\033[92m"  # Bright green - fresh
                        elif age < 2.0:
                            color = "\033[93m"  # Yellow - recent
                        elif age < 10.0:
                            color = "\033[91m"  # Red - stale
                        else:
                            color = "\033[90m"  # Gray - very stale
                        
                        # Value bar
                        bar = self.get_value_bar(value)
                        
                        # Print channel data
                        print(f"{color}{channel:25s} {value:+8.4f} [{bar}] {self.format_age(age)}\033[0m")
                    
                    # Clear any remaining lines
                    print("\033[K" * (20 - len(sorted_channels)), end='')
                    
                    last_display_time = current_time
                
        except KeyboardInterrupt:
            print("\n\nStopping pipe reader...")
        finally:
            # Close pipe
            if self.pipe_fd is not None:
                os.close(self.pipe_fd)


def main():
    parser = argparse.ArgumentParser(description='ADC Channel Monitor - Dashboard view of channel values')
    parser.add_argument('pipe', nargs='?', default='/tmp/beertap_pipe',
                       help='Path to named pipe (default: /tmp/beertap_pipe)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output (show errors)')
    parser.add_argument('--scroll', action='store_true',
                       help='Use scrolling output instead of dashboard')
    
    args = parser.parse_args()
    
    # Create reader
    reader = PipeReader(args.pipe)
    if args.verbose:
        reader.verbose = True
    
    # Run
    reader.run()


if __name__ == "__main__":
    main()
