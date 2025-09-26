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


def load_configuration(config_file: str) -> tuple[List[str], float]:
    """
    Load pattern configuration from a YAML file.
    
    Args:
        config_file (str): Path to the configuration file
        
    Returns:
        tuple[List[str], float]: List of pattern names to run and frame interval in seconds
        
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
        
        patterns = config['patterns']
        
        # Validate that patterns is a list of strings
        if not isinstance(patterns, list):
            raise ValueError("Patterns must be a list")
        
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise ValueError("All pattern names must be strings")
        
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
        
        print(f"Loaded {len(patterns)} patterns: {', '.join(patterns)}")
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
        for i, pattern_name in enumerate(patterns):
            try:
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
                
                processes.append((process, pattern_name, i))
                pipes.append(parent_conn)
                
            except Exception as e:
                print(f"Error creating process for pattern {pattern_name}: {str(e)}")
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
        for process, pattern_name, process_id in processes:
            try:
                process.start()
                print(f"Started process {process_id} ({pattern_name}) with PID: {process.pid}")
            except Exception as e:
                print(f"Error starting process {process_id} ({pattern_name}): {str(e)}")
        
        if args.daemon:
            print("Running pattern processes as daemons")
        
        try:
            # Main frame generation loop with configurable timing
            print(f"\nStarting frame generation loop ({frame_interval*1000:.1f}ms intervals). Press Ctrl+C to stop.")
            frame_number = 0
            start_time = time.time()
            
            while True:
                frame_start = time.time()
                
                # Calculate input value based on time
                input_value = (time.time() - start_time) % 100.0
                
                # Send frame request to all pattern processes
                for i, pipe in enumerate(pipes):
                    try:
                        pipe.send(('start_frame', input_value))
                    except Exception as e:
                        print(f"Error sending frame request to process {i}: {str(e)}")
                
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
