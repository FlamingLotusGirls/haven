#!/usr/bin/env python3
"""
Named Pipe Reader Test
Reads pickled data from the shared named pipe created by adc_reader.py instances
"""

import pickle
import argparse
import struct
import os
import sys
import time
import select


class PipeReader:
    def __init__(self, pipe_path):
        """Initialize pipe reader with a single pipe path"""
        self.pipe_path = pipe_path
        self.pipe_fd = None
        self.buffer = b''  # Buffer for incomplete messages
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
        
        # Open pipe in blocking mode for continuous reading
        try:
            self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY)
            print(f"Opened pipe: {self.pipe_path}")
        except Exception as e:
            print(f"Failed to open pipe {self.pipe_path}: {e}")
            sys.exit(1)
    
    def read_messages(self):
        """Read and yield messages from the pipe buffer"""
        try:
            # Read available data (non-blocking)
            chunk = os.read(self.pipe_fd, 4096)
            if not chunk:
                # Pipe closed, reopen it
                os.close(self.pipe_fd)
                self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY)
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
                        print(f"Error unpickling data: {e}")
                else:
                    # Wait for more data
                    break
                    
        except (BlockingIOError, OSError):
            pass
        except Exception as e:
            print(f"Error reading from pipe: {e}")
    
    def run(self):
        """Main loop - read from pipe and display data"""
        print(f"\nListening for data on pipe: {self.pipe_path}")
        print("Press Ctrl+C to stop\n")
        print(f"{'Time':8s} | {'Channel':25s} | {'Value':8s}")
        print("-" * 50)
        
        message_count = 0
        
        try:
            while True:
                # Use select to wait for data with timeout
                ready, _, _ = select.select([self.pipe_fd], [], [], 0.1)
                
                if ready:
                    # Read and process messages
                    for data in self.read_messages():
                        message_count += 1
                        channel = data.get('channel', 'unknown')
                        value = data.get('value', 0.0)
                        timestamp = data.get('timestamp', 0)
                        
                        # Format timestamp
                        time_str = time.strftime('%H:%M:%S', time.localtime(timestamp))
                        
                        print(f"{time_str} | {channel:25s} | {value:+.4f}")
                        
                        # Also print raw data in verbose mode
                        if hasattr(self, 'verbose') and self.verbose:
                            print(f"      Raw: {data}")
                
        except KeyboardInterrupt:
            print("\n\nStopping pipe reader...")
        finally:
            # Close pipe
            if self.pipe_fd is not None:
                os.close(self.pipe_fd)
                print(f"Closed pipe: {self.pipe_path}")


def main():
    parser = argparse.ArgumentParser(description='Named Pipe Reader Test for Pickled ADC Data')
    parser.add_argument('pipe', nargs='?', default='/tmp/adc_pipe_main',
                       help='Path to named pipe (default: /tmp/adc_pipe_main)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output (show raw data)')
    
    args = parser.parse_args()
    
    # Create reader
    reader = PipeReader(args.pipe)
    if args.verbose:
        reader.verbose = True
    
    # Run
    reader.run()


if __name__ == "__main__":
    main()
