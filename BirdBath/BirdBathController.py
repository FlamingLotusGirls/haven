#!/usr/bin/env python3
"""
BirdBathController - Main controller for running pattern processes.
"""

import sys
import argparse
import multiprocessing
import time
import yaml
import os
import json
import struct
import pickle
import numpy as np
from typing import List, Dict, Any
from pattern_runner import PatternRunner
from pattern_driver import PatternDriver


def pattern_driver_process(conn):
    """
    Process function that creates and runs a PatternDriver.
    
    Args:
        conn: Pipe connection object for communication with main process
    """
    try:
        print("Starting pattern driver process")
        
        # Create the PatternDriver
        driver = PatternDriver()
        print("Successfully created PatternDriver")
        
        # Main driver execution loop - wait for frame data
        frame_count = 0
        while True:
            try:
                # Wait for frame data from main process
                message = conn.recv()
                
                if message is None or message == 'shutdown':
                    print("Pattern driver process received shutdown signal")
                    break
                
                if isinstance(message, tuple) and len(message) == 2:
                    command, frame_data = message
                    if command == 'frame_data':
                        # Process frame data with the PatternDriver
                        driver.Frame(frame_data)
                        
                        frame_count += 1
                        if frame_count % 100 == 0:  # Print status every 100 frames
                            print(f"Pattern driver - Frame {frame_count}: Processed frame data")
                    else:
                        print(f"Pattern driver received unknown command: {command}")
                else:
                    print(f"Pattern driver received invalid message format: {message}")
                
            except EOFError:
                print("Pattern driver - pipe closed by main process")
                break
            except Exception as e:
                print(f"Error in pattern driver process: {str(e)}")
                break
                
    except Exception as e:
        print(f"Failed to create PatternDriver: {str(e)}")
        return
    finally:
        conn.close()


def pattern_process(pattern_name: str, process_id: int, conn):
    """
    Process function that creates and runs a PatternRunner with pipe communication.
    
    Args:
        pattern_name (str): Name of the pattern class to instantiate and run
        process_id (int): Unique identifier for this process (0-5)
        conn: Pipe connection object for communication with main process
    """
    try:
        print(f"Starting pattern process {process_id} with pattern: {pattern_name}")
        
        # Create the PatternRunner with the specified pattern
        runner = PatternRunner(pattern_name)
        print(f"Successfully created PatternRunner for {pattern_name} (Process {process_id})")
        
        # Main pattern execution loop - wait for frame requests
        frame_count = 0
        while True:
            try:
                # Wait for frame request from main process
                message = conn.recv()
                
                if message is None or message == 'shutdown':
                    print(f"Pattern process {process_id} ({pattern_name}) received shutdown signal")
                    break
                
                if isinstance(message, tuple) and len(message) == 2:
                    command, input_value = message
                    if command == 'start_frame':
                        # Generate frame with the provided input value
                        result = runner.run_frame(input_value)
                        
                        # Send result back to main process
                        conn.send(result)
                        
                        frame_count += 1
                        if frame_count % 100 == 0:  # Print status every 100 frames
                            print(f"Process {process_id} ({pattern_name}) - Frame {frame_count}: Generated {len(result)} values")
                    else:
                        print(f"Process {process_id} ({pattern_name}) received unknown command: {command}")
                else:
                    print(f"Process {process_id} ({pattern_name}) received invalid message format: {message}")
                
            except EOFError:
                print(f"Pattern process {process_id} ({pattern_name}) - pipe closed by main process")
                break
            except Exception as e:
                print(f"Error in pattern process {process_id} ({pattern_name}): {str(e)}")
                break
                
    except Exception as e:
        print(f"Failed to create PatternRunner for {pattern_name} (Process {process_id}): {str(e)}")
        return
    finally:
        conn.close()


class PipeReader:
    """
    Class to read messages from the ADC named pipe and track multiple channels.
    """
    
    def __init__(self, pipe_path='/tmp/adc_pipe_main'):
        self.pipe_path = pipe_path
        self.buffer = b''
        self.pipe_fd = None
        self.channel_values = {}  # Dictionary to store latest value for each channel
        
    def open_pipe(self):
        """Open the named pipe for reading."""
        try:
            if not os.path.exists(self.pipe_path):
                print(f"Warning: Named pipe {self.pipe_path} does not exist. Using default input values 0.0")
                return False
            
            self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY | os.O_NONBLOCK)
            print(f"Opened named pipe: {self.pipe_path}")
            return True
        except Exception as e:
            print(f"Error opening named pipe {self.pipe_path}: {str(e)}")
            return False
    
    def read_latest_values(self):
        """
        Read all available messages from the pipe and update channel values.
        
        Returns:
            Dict[str, float]: Dictionary mapping channel names to their latest values
        """
        if self.pipe_fd is None:
            return self.channel_values
        
        try:
            # Read available data (non-blocking)
            chunk = os.read(self.pipe_fd, 4096)
            if chunk:
                self.buffer += chunk
        except OSError:
            # No data available (EAGAIN/EWOULDBLOCK)
            return self.channel_values
        except Exception as e:
            print(f"Error reading from pipe: {str(e)}")
            return self.channel_values
        
        # Process complete messages from buffer
        while len(self.buffer) >= 4:
            try:
                # Read length header
                length = struct.unpack('>I', self.buffer[:4])[0]
                
                # Check if we have the complete message
                if len(self.buffer) >= 4 + length:
                    # Extract and unpickle the message
                    pickled_data = self.buffer[4:4+length]
                    self.buffer = self.buffer[4+length:]
                    
                    data = pickle.loads(pickled_data)
                    
                    # Extract channel and value
                    if isinstance(data, dict) and 'channel' in data and 'value' in data:
                        channel = data['channel']
                        value = float(data['value'])
                        # Clamp to expected range just in case
                        value = max(-1.0, min(1.0, value))
                        
                        # Update channel value
                        self.channel_values[channel] = value
                else:
                    break
            except Exception as e:
                print(f"Error parsing pipe message: {str(e)}")
                # Clear buffer on parse error
                self.buffer = b''
                break
        
        return self.channel_values
    
    def get_channel_value(self, channel: str) -> float:
        """
        Get the latest value for a specific channel.
        
        Args:
            channel (str): Channel name to get value for
            
        Returns:
            float: Latest value for the channel, or 0.0 if channel not found
        """
        return self.channel_values.get(channel, 0.0)
    
    def close_pipe(self):
        """Close the named pipe."""
        if self.pipe_fd is not None:
            try:
                os.close(self.pipe_fd)
            except:
                pass
            self.pipe_fd = None


def write_nozzle_data(final_result: np.ndarray, data_file: str = 'nozzle_data.json'):
    """
    Write nozzle data to JSON file for web server consumption.
    
    Args:
        final_result (np.ndarray): 36-element array of nozzle values
        data_file (str): Path to JSON file to write
    """
    try:
        # Convert numpy array to Python list for JSON serialization
        nozzle_values = final_result.tolist()
        
        # Write to temporary file first, then rename for atomic operation
        temp_file = data_file + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(nozzle_values, f)
        
        # Atomic rename to avoid partial reads
        os.rename(temp_file, data_file)
        
    except Exception as e:
        # Clean up temp file if it exists
        temp_file = data_file + '.tmp'
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        raise e


def load_configuration(config_file: str) -> tuple[List[Dict[str, str]], float]:
    """
    Load pattern configuration from a YAML file.
    
    Args:
        config_file (str): Path to the configuration file
        
    Returns:
        tuple[List[Dict[str, str]], float]: List of pattern configs with name and input_channel, and frame interval in seconds
        
    Raises:
        FileNotFoundError: If the configuration file doesn't exist
        yaml.YAMLError: If the configuration file is not valid YAML
        ValueError: If the configuration format is invalid
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file not found: {config_file}")
    
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        # Configuration must be a dictionary with 'patterns' key
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a dictionary")
        
        if 'patterns' not in config:
            raise ValueError("Configuration must contain a 'patterns' key")
        
        patterns_config = config['patterns']
        
        # Validate that patterns is a list
        if not isinstance(patterns_config, list):
            raise ValueError("Patterns must be a list")
        
        patterns = []
        for i, pattern_entry in enumerate(patterns_config):
            if not isinstance(pattern_entry, dict):
                raise ValueError(f"Pattern entry {i} must be a dictionary with 'pattern' and 'input_channel' keys")
            
            if 'pattern' not in pattern_entry:
                raise ValueError(f"Pattern entry {i} must contain 'pattern' key")
            if 'input_channel' not in pattern_entry:
                raise ValueError(f"Pattern entry {i} must contain 'input_channel' key")
            
            pattern_name = pattern_entry['pattern']
            input_channel = pattern_entry['input_channel']
            
            if not isinstance(pattern_name, str):
                raise ValueError(f"Pattern name must be a string, got {type(pattern_name)}")
            if not isinstance(input_channel, str):
                raise ValueError(f"Input channel must be a string, got {type(input_channel)}")
            
            patterns.append({
                'pattern': pattern_name,
                'input_channel': input_channel
            })
        
        # Limit to 6 patterns maximum
        if len(patterns) > 6:
            print(f"Warning: Configuration contains {len(patterns)} patterns, limiting to first 6")
            patterns = patterns[:6]
        
        # Get frame interval (default to 100ms = 0.1 seconds)
        frame_interval_ms = config.get('frame_interval_ms', 100)
        if not isinstance(frame_interval_ms, (int, float)) or frame_interval_ms <= 0:
            raise ValueError("frame_interval_ms must be a positive number")
        
        frame_interval = frame_interval_ms / 1000.0  # Convert to seconds
        
        return patterns, frame_interval
        
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Invalid YAML in configuration file: {str(e)}")


def main():
    """
    Main function that creates processes to run patterns from a configuration file.
    """
    parser = argparse.ArgumentParser(description='BirdBath Pattern Controller')
    parser.add_argument('--config', '-c', 
                       default='patterns.yaml',
                       help='Configuration file containing pattern names (default: patterns.yaml)')
    parser.add_argument('--daemon', '-d', 
                       action='store_true',
                       help='Run pattern processes as daemons')
    
    args = parser.parse_args()
    
    print(f"BirdBathController starting with configuration: {args.config}")
    
    try:
        # Load pattern configuration
        patterns, frame_interval = load_configuration(args.config)
        
        if not patterns:
            print("No patterns found in configuration file")
            sys.exit(1)
        
        pattern_names = [p['pattern'] for p in patterns]
        channels = [p['input_channel'] for p in patterns]
        pattern_descriptions = [f"{p['pattern']}({p['input_channel']})" for p in patterns]
        print(f"Loaded {len(patterns)} patterns: {', '.join(pattern_descriptions)}")
        print(f"Frame interval: {frame_interval*1000:.1f}ms")
        
        # Create pattern driver process and pipe
        driver_parent_conn, driver_child_conn = multiprocessing.Pipe()
        driver_process = multiprocessing.Process(
            target=pattern_driver_process,
            args=(driver_child_conn,),
            name="PatternDriver"
        )
        
        if args.daemon:
            driver_process.daemon = True
        
        # Create processes and pipes for each pattern
        processes = []
        pipes = []
        for i, pattern_config in enumerate(patterns):
            try:
                pattern_name = pattern_config['pattern']
                input_channel = pattern_config['input_channel']
                
                # Create bidirectional pipe for communication
                parent_conn, child_conn = multiprocessing.Pipe()
                
                process = multiprocessing.Process(
                    target=pattern_process,
                    args=(pattern_name, i, child_conn),
                    name=f"Pattern-{i}-{pattern_name}"
                )
                
                # Set as daemon if requested
                if args.daemon:
                    process.daemon = True
                
                # Store process info with input channel for filtering
                processes.append((process, pattern_name, input_channel, i))
                pipes.append(parent_conn)
                
            except Exception as e:
                print(f"Error creating process for pattern {pattern_config['pattern']}: {str(e)}")
                continue
        
        if not processes:
            print("No processes could be created")
            sys.exit(1)
        
        # Start pattern driver process
        print("\nStarting pattern driver process...")
        try:
            driver_process.start()
            print(f"Started pattern driver process with PID: {driver_process.pid}")
        except Exception as e:
            print(f"Error starting pattern driver process: {str(e)}")
            sys.exit(1)
        
        # Start all pattern processes
        print(f"\nStarting {len(processes)} pattern processes...")
        for process, pattern_name, process_id, idx in processes:
            try:
                print("Starting pattern process\n")
                process.start()
                print(f"Started process {process_id} ({pattern_name}) with PID: {process.pid}")
            except Exception as e:
                print(f"Error starting process {process_id} ({pattern_name}): {str(e)}")
        
        if args.daemon:
            print("Running pattern processes as daemons")

        # Initialize pipe reader for hardware input
        pipe_reader = PipeReader('/tmp/adc_pipe_main')
        pipe_opened = pipe_reader.open_pipe()
        
        try:
            # Main frame generation loop with configurable timing
            print(f"\nStarting frame generation loop ({frame_interval*1000:.1f}ms intervals). Press Ctrl+C to stop.")
            if pipe_opened:
                print("Reading input values from hardware via named pipe")
            else:
                print("Using default input value 0.0 (no hardware pipe available)")
            
            frame_number = 0
            
            while True:
                frame_start = time.time()
                
                # Read all channel values from hardware pipe
                pipe_reader.read_latest_values()
                
                # Send frame request to all pattern processes with channel-specific values
                for i, (process, pattern_name, input_channel, process_id) in enumerate(processes):
                    try:
                        # Get the input value for this pattern's specific channel
                        input_value = pipe_reader.get_channel_value(input_channel)
                        pipes[i].send(('start_frame', input_value))
                    except Exception as e:
                        print(f"Error sending frame request to process {i} ({pattern_name}): {str(e)}")
                
                # Collect results from all pattern processes
                results = []
                for i, pipe in enumerate(pipes):
                    try:
                        result = pipe.recv()
                        results.append(result)
                    except Exception as e:
                        print(f"Error receiving result from process {i}: {str(e)}")
                        results.append(None)
                
                # Sum all valid results and clamp to [-1.0, 1.0]
                valid_results = [r for r in results if r is not None]
                if valid_results:
                    # Sum all arrays element-wise
                    summed_result = np.sum(valid_results, axis=0)
                    # Clamp values to [-1.0, 1.0] range
                    final_result = np.clip(summed_result, -1.0, 1.0)
                else:
                    # If no valid results, create zero array
                    final_result = np.zeros(36, dtype=np.float64)
                
                # Send final result to pattern driver process
                try:
                    driver_parent_conn.send(('frame_data', final_result))
                except Exception as e:
                    print(f"Error sending frame data to pattern driver: {str(e)}")
                
                # Write nozzle data to JSON file for web server
                try:
                    write_nozzle_data(final_result)
                except Exception as e:
                    print(f"Error writing nozzle data to file: {str(e)}")
                
                frame_number += 1
                if frame_number % 100 == 0:  # Print status every 100 frames
                    print(f"Main process - Frame {frame_number}: Summed {len(valid_results)} results, range [{final_result.min():.3f}, {final_result.max():.3f}]")
                
                # Maintain configured timing
                frame_duration = time.time() - frame_start
                sleep_time = max(0, frame_interval - frame_duration)
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            print(f"\nShutting down all processes...")
            
            # Close hardware pipe reader
            pipe_reader.close_pipe()
            
            # Send shutdown signal to pattern driver
            try:
                driver_parent_conn.send('shutdown')
            except:
                pass
            
            # Send shutdown signal to all pattern processes
            for i, pipe in enumerate(pipes):
                try:
                    pipe.send('shutdown')
                except:
                    pass  # Pipe might already be closed
            
            # Close all pipes
            try:
                driver_parent_conn.close()
            except:
                pass
            
            for pipe in pipes:
                try:
                    pipe.close()
                except:
                    pass
            
            # Terminate pattern driver process
            if driver_process.is_alive():
                print("Terminating pattern driver process...")
                driver_process.terminate()
            
            # Terminate all pattern processes
            for process, pattern_name, process_id in processes:
                if process.is_alive():
                    print(f"Terminating process {process_id} ({pattern_name})...")
                    process.terminate()
            
            # Wait for pattern driver to terminate
            if driver_process.is_alive():
                driver_process.join(timeout=5)
                if driver_process.is_alive():
                    print("Force killing pattern driver process...")
                    driver_process.kill()
                    driver_process.join()
            
            # Wait for pattern processes to terminate
            for process, pattern_name, process_id in processes:
                if process.is_alive():
                    process.join(timeout=5)
                    
                    if process.is_alive():
                        print(f"Force killing process {process_id} ({pattern_name})...")
                        process.kill()
                        process.join()
            
            print("All processes terminated")
            
    except FileNotFoundError as e:
        print(f"Configuration file error: {str(e)}")
        sys.exit(1)
    except (yaml.YAMLError, ValueError) as e:
        print(f"Configuration error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
