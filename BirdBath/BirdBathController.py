#!/usr/bin/env python3
"""
BirdBathController - Main controller for running pattern processes.
"""

import sys
import argparse
import importlib
import multiprocessing
import time
import yaml
import os
import json
import struct
import pickle
import numpy as np
import threading
import socket
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple
from pattern_runner import PatternRunner
from pattern_driver import PatternDriver


# ---------------------------------------------------------------------------
# Mode persistence
# ---------------------------------------------------------------------------

STATE_FILE = 'birdbath_state.json'
DEFAULT_MODE = 'run'
HTTP_PORT = 8080
VALID_MODES = {'run', 'calibrate'}

# ArtNet packet type codes (must match controller firmware)
ARTNET_FRAME = 0
ARTNET_NOZZLE = 1


def load_persisted_mode() -> str:
    """Load the last saved mode from birdbath_state.json, defaulting to 'run'."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
            mode = data.get('mode', DEFAULT_MODE)
            if mode in VALID_MODES:
                return mode
        except Exception as e:
            print(f"Warning: could not read {STATE_FILE}: {e}")
    return DEFAULT_MODE


def save_persisted_mode(mode: str):
    """Atomically persist the current mode to birdbath_state.json."""
    try:
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'mode': mode}, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"Warning: could not save mode to {STATE_FILE}: {e}")


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
            print(f"Attempting to opening pipe {self.pipe_path}")
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
            print("No pipe, no values\n")
            return self.channel_values

        try:
            # Read available data (non-blocking)
            chunk = os.read(self.pipe_fd, 4096)
            if chunk:
                self.buffer += chunk
        except OSError:
            # No data available (EAGAIN/EWOULDBLOCK)
            print("Read latest value: No data")
            return self.channel_values
        except Exception as e:
            print(f"Error reading from pipe: {str(e)}")
            return self.channel_values

        # Process complete messages from buffer
        # Note here that we can end up with more than one message per channel
        # TODO - average values, if we have more than one.
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


# ---------------------------------------------------------------------------
# AppState - shared mutable state, thread-safe
# ---------------------------------------------------------------------------

class AppState:
    """
    Holds all shared state that must be accessed by the frame loop thread,
    the HTTP server thread, and the mode-transition worker thread.
    All mutable fields are protected by self.lock.
    """

    def __init__(self, initial_mode: str):
        self.lock = threading.Lock()
        self._mode: str = initial_mode
        # Latest frame data written by the frame loop, read by GET /nozzles
        self._latest_frame: np.ndarray = np.zeros(36, dtype=np.float64)
        # Subprocess handles for run mode
        self._driver_process = None
        self._driver_conn = None
        self._pattern_processes: list = []
        self._pattern_pipes: list = []
        # Event that tells the frame loop to exit
        self._stop_run_event = threading.Event()
        # Mode transition request
        self._transition_target: Optional[str] = None
        self._transition_event = threading.Event()

    @property
    def mode(self) -> str:
        with self.lock:
            return self._mode

    def _set_mode_unsafe(self, mode: str):
        """Set mode; caller must already hold self.lock."""
        self._mode = mode

    def update_latest_frame(self, frame: np.ndarray):
        with self.lock:
            np.copyto(self._latest_frame, frame)

    def get_latest_frame(self) -> np.ndarray:
        with self.lock:
            return self._latest_frame.copy()

    def store_run_handles(self, driver_process, driver_conn,
                          pattern_processes, pattern_pipes):
        with self.lock:
            self._driver_process = driver_process
            self._driver_conn = driver_conn
            self._pattern_processes = pattern_processes
            self._pattern_pipes = pattern_pipes

    def clear_run_handles(self):
        with self.lock:
            self._driver_process = None
            self._driver_conn = None
            self._pattern_processes = []
            self._pattern_pipes = []

    def get_run_handles(self):
        with self.lock:
            return (self._driver_process, self._driver_conn,
                    list(self._pattern_processes), list(self._pattern_pipes))

    def request_run_stop(self):
        self._stop_run_event.set()

    def clear_run_stop(self):
        self._stop_run_event.clear()

    def is_run_stop_requested(self) -> bool:
        return self._stop_run_event.is_set()

    def request_transition(self, target_mode: str):
        """Ask the transition worker to switch to target_mode."""
        with self.lock:
            self._transition_target = target_mode
        self._transition_event.set()

    def wait_for_transition_request(self, timeout: float = 1.0) -> Optional[str]:
        """Block until a transition is requested or timeout expires."""
        self._transition_event.wait(timeout)
        self._transition_event.clear()
        with self.lock:
            target = self._transition_target
            self._transition_target = None
        return target


def load_configuration(config_file: str) -> Tuple[List[Dict[str, str]], float]:
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


# ---------------------------------------------------------------------------
# Driver config helpers (calibration)
# ---------------------------------------------------------------------------

def load_driver_config(config_file: str = 'driver_config.yaml') -> dict:
    """Load driver_config.yaml, creating a default file if it doesn't exist."""
    if not os.path.exists(config_file):
        default = {
            'controllers': [{'ip': '10.0.0.4'}, {'ip': '10.0.0.5'}, {'ip': '10.0.0.6'}],
            'ranges': [[0, 255]] * 36,
        }
        _save_driver_config(default, config_file)
        return default
    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


def _save_driver_config(config: dict, config_file: str = 'driver_config.yaml'):
    """Atomically write driver_config.yaml."""
    tmp = config_file + '.tmp'
    with open(tmp, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, indent=2)
    os.replace(tmp, config_file)


def discover_available_patterns(patterns_dir: str = 'patterns') -> List[str]:
    """
    Scan the patterns/ package directory and return the names of all concrete
    Pattern subclasses found there.

    Each *.py file (except __init__.py) is imported as patterns.<stem>.
    Any class that is a non-abstract subclass of Pattern is included.
    importlib caches modules in sys.modules, so repeated calls are cheap.
    """
    import glob
    import inspect as _inspect
    from pattern import Pattern as _Pattern

    found: List[str] = []
    pattern_files = glob.glob(os.path.join(patterns_dir, '*.py'))

    for filepath in sorted(pattern_files):
        stem = os.path.splitext(os.path.basename(filepath))[0]
        if stem == '__init__':
            continue
        module_name = f'patterns.{stem}'
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            print(f"Warning: could not import {module_name}: {e}")
            continue

        for name, obj in _inspect.getmembers(module, _inspect.isclass):
            if (issubclass(obj, _Pattern)
                    and obj is not _Pattern
                    and not _inspect.isabstract(obj)
                    and obj.__module__ == module_name):
                found.append(name)

    return sorted(found)


# ---------------------------------------------------------------------------
# Run mode lifecycle helpers
# ---------------------------------------------------------------------------

def start_run_mode(app_state: AppState, config_file: str, daemon: bool = False):
    """
    Load pattern config, start PatternDriver + PatternRunner subprocesses, store
    handles in app_state.  Returns (patterns, frame_interval).
    """
    patterns, frame_interval = load_configuration(config_file)
    descriptions = [f"{p['pattern']}({p['input_channel']})" for p in patterns]
    print(f"Starting run mode: {', '.join(descriptions)}, interval {frame_interval*1000:.1f}ms")

    driver_parent_conn, driver_child_conn = multiprocessing.Pipe()
    driver_process = multiprocessing.Process(
        target=pattern_driver_process, args=(driver_child_conn,), name="PatternDriver"
    )
    if daemon:
        driver_process.daemon = True
    driver_process.start()
    driver_child_conn.close()
    print(f"Started PatternDriver (PID {driver_process.pid})")

    processes, pipes = [], []
    for i, pcfg in enumerate(patterns):
        parent_conn, child_conn = multiprocessing.Pipe()
        proc = multiprocessing.Process(
            target=pattern_process,
            args=(pcfg['pattern'], i, child_conn),
            name=f"Pattern-{i}-{pcfg['pattern']}",
        )
        if daemon:
            proc.daemon = True
        proc.start()
        child_conn.close()
        processes.append((proc, pcfg['pattern'], pcfg['input_channel'], i))
        pipes.append(parent_conn)
        print(f"Started Pattern-{i} ({pcfg['pattern']}, PID {proc.pid})")

    app_state.store_run_handles(driver_process, driver_parent_conn, processes, pipes)
    return patterns, frame_interval


def stop_run_mode(app_state: AppState):
    """Signal the frame loop to exit and shut down all run-mode subprocesses."""
    app_state.request_run_stop()
    driver_proc, driver_conn, processes, pipes = app_state.get_run_handles()

    for target_conn in ([driver_conn] if driver_conn else []) + pipes:
        try:
            target_conn.send('shutdown')
        except Exception:
            pass
    for target_conn in ([driver_conn] if driver_conn else []) + pipes:
        try:
            target_conn.close()
        except Exception:
            pass

    all_procs = ([driver_proc] if driver_proc else []) + [p for p, *_ in processes]
    for proc in all_procs:
        if proc and proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
                proc.join()

    app_state.clear_run_handles()
    app_state.clear_run_stop()
    print("Run mode subprocesses stopped.")


# ---------------------------------------------------------------------------
# Calibration helpers (ArtNet + UDP status)
# ---------------------------------------------------------------------------

def query_controller_status(controller_ip: str, timeout: float = 0.25) -> Optional[list]:
    """Send a UDP STATUS request; return list of 12 raw values or None on timeout."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(b"STATUS", (controller_ip, 7777))
            data, _ = sock.recvfrom(1024)
            values = list(data)
            if len(values) < 12:
                values.extend([0] * (12 - len(values)))
            return values[:12]
        finally:
            sock.close()
    except socket.timeout:
        return None
    except Exception as e:
        print(f"Error querying controller {controller_ip}: {e}")
        return None


def send_nozzle_position_artnet(nozzle_id: int, raw_value: float, controllers: list) -> bool:
    """Send a single-nozzle ArtNet position command to the correct controller."""
    controller_idx = nozzle_id // 12
    channel_in_controller = nozzle_id % 12
    if controller_idx >= len(controllers):
        print(f"Controller index {controller_idx} out of range for nozzle {nozzle_id}")
        return False
    controller_ip = controllers[controller_idx]['ip']

    header = b"Art-Net\x00"
    opcode = struct.pack("<H", 0x5000)
    proto = struct.pack(">H", 14)
    universe = struct.pack("<H", controller_idx)
    payload = bytearray([ARTNET_NOZZLE, channel_in_controller, 0, max(0, min(255, int(raw_value)))])
    data_length = struct.pack(">H", len(payload))
    packet = header + opcode + proto + b"\x00\x00" + universe + data_length + bytes(payload)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (controller_ip, 6454))
        return True
    except Exception as e:
        print(f"Error sending ArtNet for nozzle {nozzle_id}: {e}")
        return False
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class BirdbathHTTPHandler(BaseHTTPRequestHandler):
    """
    Mode-aware HTTP handler.  app_state and driver_config_file are injected
    as class attributes by make_handler_class().
    """
    app_state: AppState = None
    driver_config_file: str = 'driver_config.yaml'
    patterns_config_file: str = 'patterns.yaml'
    _controllers_cache: Optional[list] = None

    def do_GET(self):
        path = urlparse(self.path).path
        mode = self.app_state.mode

        if path in ('/', '/index.html'):
            self._serve_page(mode)
        elif path == '/nozzles':
            self._serve_run_nozzles() if mode == 'run' else self._serve_calibrate_nozzles()
        elif path == '/mode':
            self._send_json(200, {'mode': mode})
        elif path == '/patterns/available':
            self._get_available_patterns()
        elif path == '/patterns/config':
            self._get_patterns_config()
        else:
            m = re.match(r'^/nozzle/(\d+)/calibration$', path)
            if m:
                self._get_nozzle_calibration(int(m.group(1)))
            else:
                self._send_404()

    def do_PUT(self):
        path = urlparse(self.path).path
        m = re.match(r'^/nozzle/(\d+)/calibration/(high|low)$', path)
        if m:
            self._set_nozzle_calibration(int(m.group(1)), m.group(2))
            return
        m = re.match(r'^/nozzle/(\d+)/position$', path)
        if m:
            self._set_nozzle_position(int(m.group(1)))
            return
        if path == '/patterns/config':
            self._put_patterns_config()
            return
        self._send_404()

    def do_POST(self):
        if urlparse(self.path).path == '/mode':
            self._handle_mode_switch()
        else:
            self._send_404()

    def _serve_page(self, mode: str):
        filename = 'nozzle_visualization.html' if mode == 'run' else 'nozzle_calibration.html'
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        else:
            self._send_json(404, {'error': f'Page not found: {filename}'})

    def _serve_run_nozzles(self):
        self._send_json(200, self.app_state.get_latest_frame().tolist())

    def _serve_calibrate_nozzles(self):
        controllers = self._get_controllers()
        all_values, controller_responses = [], {}
        for idx, ctrl in enumerate(controllers):
            ip = ctrl['ip']
            values = query_controller_status(ip)
            if values is not None:
                controller_responses[str(idx)] = {'ip': ip, 'status': 'success', 'values': values}
                all_values.extend(values)
            else:
                controller_responses[str(idx)] = {'ip': ip, 'status': 'timeout', 'values': [0]*12}
                all_values.extend([0]*12)
        all_values = (all_values + [0]*36)[:36]
        self._send_json(200, {'nozzle_count': 36, 'values': all_values,
                              'controllers': controller_responses, 'timestamp': time.time()})

    def _handle_mode_switch(self):
        body = self._read_json_body()
        if body is None:
            return
        target = body.get('mode')
        if target not in VALID_MODES:
            self._send_json(400, {'error': f'mode must be one of {sorted(VALID_MODES)}'})
            return
        self.app_state.request_transition(target)
        self._send_json(200, {'status': 'ok', 'requested_mode': target})

    def _get_nozzle_calibration(self, nozzle_id: int):
        if not self._require_calibrate_mode():
            return
        if not self._validate_nozzle_id(nozzle_id):
            return
        config = load_driver_config(self.driver_config_file)
        rng = config.get('ranges', [[0,255]]*36)[nozzle_id]
        self._send_json(200, {'nozzle_id': nozzle_id, 'calibration': {'low': rng[0], 'high': rng[1]}})

    def _set_nozzle_calibration(self, nozzle_id: int, endpoint: str):
        if not self._require_calibrate_mode():
            return
        if not self._validate_nozzle_id(nozzle_id):
            return
        body = self._read_json_body()
        if body is None:
            return
        try:
            value = int(body.get('value', 0 if endpoint == 'low' else 255))
        except (ValueError, TypeError):
            self._send_json(400, {'error': 'value must be an integer'}); return
        if not (0 <= value <= 255):
            self._send_json(400, {'error': 'value must be between 0 and 255'}); return
        config = load_driver_config(self.driver_config_file)
        if 'ranges' not in config:
            config['ranges'] = [[0, 255]] * 36
        while len(config['ranges']) <= nozzle_id:
            config['ranges'].append([0, 255])
        rng = config['ranges'][nozzle_id] if isinstance(config['ranges'][nozzle_id], list) else [0, 255]
        config['ranges'][nozzle_id] = [rng[0], value] if endpoint == 'high' else [value, rng[1]]
        _save_driver_config(config, self.driver_config_file)
        self._send_json(200, {'nozzle_id': nozzle_id, 'range': config['ranges'][nozzle_id]})

    def _set_nozzle_position(self, nozzle_id: int):
        if not self._require_calibrate_mode():
            return
        if not self._validate_nozzle_id(nozzle_id):
            return
        body = self._read_json_body()
        if body is None:
            return
        try:
            raw_value = int(body.get('value', 0))
        except (ValueError, TypeError):
            self._send_json(400, {'error': 'value must be an integer'}); return
        if not (0 <= raw_value <= 255):
            self._send_json(400, {'error': 'value must be between 0 and 255'}); return
        ok = send_nozzle_position_artnet(nozzle_id, float(raw_value), self._get_controllers())
        if ok:
            self._send_json(200, {'nozzle_id': nozzle_id, 'raw_value': raw_value})
        else:
            self._send_json(500, {'error': f'Failed to send ArtNet to nozzle {nozzle_id}'})

    def _require_calibrate_mode(self) -> bool:
        if self.app_state.mode != 'calibrate':
            self._send_json(409, {'error': 'Only available in calibrate mode'})
            return False
        return True

    def _validate_nozzle_id(self, nozzle_id: int) -> bool:
        if not (0 <= nozzle_id < 36):
            self._send_json(400, {'error': f'Nozzle ID {nozzle_id} must be 0-35'})
            return False
        return True

    def _get_controllers(self) -> list:
        if BirdbathHTTPHandler._controllers_cache is None:
            try:
                BirdbathHTTPHandler._controllers_cache = load_driver_config(
                    self.driver_config_file).get('controllers',
                    [{'ip': '10.0.0.4'}, {'ip': '10.0.0.5'}, {'ip': '10.0.0.6'}])
            except Exception:
                BirdbathHTTPHandler._controllers_cache = [
                    {'ip': '10.0.0.4'}, {'ip': '10.0.0.5'}, {'ip': '10.0.0.6'}]
        return BirdbathHTTPHandler._controllers_cache

    def _read_json_body(self) -> Optional[dict]:
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            self._send_json(400, {'error': 'Request body required'}); return None
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'))
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json(400, {'error': f'Invalid JSON: {e}'}); return None

    def _send_json(self, code: int, data):
        payload = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(payload)

    def _get_available_patterns(self):
        """Return list of all concrete Pattern subclasses in the patterns/ directory."""
        try:
            names = discover_available_patterns()
            self._send_json(200, {'patterns': names})
        except Exception as e:
            self._send_json(500, {'error': f'Error discovering patterns: {e}'})

    def _get_patterns_config(self):
        """Return current patterns.yaml as JSON."""
        try:
            with open(self.patterns_config_file, 'r') as f:
                config = yaml.safe_load(f)
            self._send_json(200, config)
        except FileNotFoundError:
            self._send_json(404, {'error': f'Config file not found: {self.patterns_config_file}'})
        except Exception as e:
            self._send_json(500, {'error': f'Error reading config: {e}'})

    def _put_patterns_config(self):
        """Validate and atomically write a new patterns.yaml. Calibrate mode only."""
        if not self._require_calibrate_mode():
            return
        body = self._read_json_body()
        if body is None:
            return

        # Validate structure
        patterns = body.get('patterns')
        if not isinstance(patterns, list) or len(patterns) == 0:
            self._send_json(400, {'error': "\"patterns\" must be a non-empty list"}); return
        if len(patterns) > 6:
            self._send_json(400, {'error': 'Maximum 6 patterns allowed'}); return

        available = discover_available_patterns()
        for i, entry in enumerate(patterns):
            if not isinstance(entry, dict):
                self._send_json(400, {'error': f'Entry {i} must be an object'}); return
            if 'pattern' not in entry or 'input_channel' not in entry:
                self._send_json(400, {'error': f"Entry {i} must have 'pattern' and 'input_channel'"}); return
            if entry['pattern'] not in available:
                self._send_json(400, {'error': f"Unknown pattern '{entry['pattern']}'. Available: {available}"}); return
            if not isinstance(entry['input_channel'], str) or not entry['input_channel']:
                self._send_json(400, {'error': f"Entry {i}: 'input_channel' must be a non-empty string"}); return

        frame_interval_ms = body.get('frame_interval_ms', 100)
        if not isinstance(frame_interval_ms, (int, float)) or frame_interval_ms <= 0:
            self._send_json(400, {'error': "'frame_interval_ms' must be a positive number"}); return

        # Build the config dict and write atomically
        new_config = {
            'patterns': [{'pattern': e['pattern'], 'input_channel': e['input_channel']}
                         for e in patterns],
            'frame_interval_ms': frame_interval_ms,
        }
        tmp = self.patterns_config_file + '.tmp'
        try:
            with open(tmp, 'w') as f:
                yaml.dump(new_config, f, default_flow_style=False, indent=2)
            os.replace(tmp, self.patterns_config_file)
        except Exception as e:
            self._send_json(500, {'error': f'Error writing config: {e}'}); return

        self._send_json(200, {'status': 'ok', 'config': new_config})

    def _send_404(self):
        self._send_json(404, {'error': 'Not Found'})

    def log_message(self, fmt, *args):
        print(f"[HTTP {time.strftime('%H:%M:%S')}] {fmt % args}")


def make_handler_class(app_state: AppState, driver_config_file: str,
                       patterns_config_file: str = 'patterns.yaml'):
    """Return a BirdbathHTTPHandler subclass with class-level state injected."""
    class Handler(BirdbathHTTPHandler):
        pass
    Handler.app_state = app_state
    Handler.driver_config_file = driver_config_file
    Handler.patterns_config_file = patterns_config_file
    return Handler


def start_http_server(app_state: AppState, port: int, driver_config_file: str,
                      patterns_config_file: str = 'patterns.yaml') -> HTTPServer:
    """Start the HTTP server on a daemon thread; return the server object."""
    server = HTTPServer(('0.0.0.0', port),
                        make_handler_class(app_state, driver_config_file, patterns_config_file))
    threading.Thread(target=server.serve_forever, daemon=True, name="HTTPServer").start()
    print(f"HTTP server started on http://0.0.0.0:{port}/")
    return server


def main():
    """
    Main function that creates processes to run patterns from a configuration file.
    """
    parser = argparse.ArgumentParser(description='BirdBath Pattern Controller')
    parser.add_argument('--config', '-c',
                       default='patterns.yaml',
                       help='Configuration file containing pattern names (default: patterns.yaml)')
    parser.add_argument('--driver-config',
                        default='driver_config.yaml',
                        help='Driver/calibration config file (default: driver_config.yaml)')
    parser.add_argument('--mode', choices=list(VALID_MODES), default=None,
                        help='Override startup mode (run|calibrate); persists as new default')
    parser.add_argument('--port', type=int, default=HTTP_PORT,
                        help=f'HTTP server port (default: {HTTP_PORT})')
    parser.add_argument('--daemon', '-d',
                       action='store_true',
                       help='Run pattern processes as daemons')

    args = parser.parse_args()

    # Mode persistence and HTTP server (started ONCE, reused across all mode transitions)
    if args.mode is not None:
        save_persisted_mode(args.mode)
    initial_mode = args.mode or load_persisted_mode()
    app_state = AppState(initial_mode)
    http_server = start_http_server(app_state, args.port, args.driver_config, args.config)

    print(f"BirdBathController starting. Mode: '{initial_mode}'. Web UI: http://localhost:{args.port}/")

    # Outer mode loop — runs forever until Ctrl+C.
    # Mode transitions (calibrate ↔ run) restart this loop without creating
    # a new HTTP server or a new AppState.
    while True:
      try:
        current_mode = app_state.mode

        # If in calibrate mode, just wait for a run transition
        if current_mode == 'calibrate':
            print("Calibrate mode active. Use the web UI to switch to run mode.")
            while True:
                next_mode = app_state.wait_for_transition_request(timeout=1.0)
                if next_mode == 'run':
                    with app_state.lock:
                        app_state._set_mode_unsafe('run')
                    save_persisted_mode('run')
                    break
            continue   # back to top of while True; will now enter run-mode branch

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
        pipe_reader = PipeReader('/tmp/beertap_pipe')
        pipe_opened = pipe_reader.open_pipe()

        # Store handles so stop_run_mode() can shut them down on a mode switch
        app_state.store_run_handles(driver_process, driver_parent_conn, processes, pipes)

        pending_mode = None

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

                # Store frame data in shared state for HTTP /nozzles endpoint
                app_state.update_latest_frame(final_result)

                frame_number += 1
                if frame_number % 100 == 0:  # Print status every 100 frames
                    print(f"Main process - Frame {frame_number}: Summed {len(valid_results)} results, range [{final_result.min():.3f}, {final_result.max():.3f}]")

                # Check for a mode-switch request from the web UI
                pending_mode = app_state.wait_for_transition_request(timeout=0)
                if pending_mode and pending_mode != 'run':
                    print(f"Mode switch requested: run -> {pending_mode}")
                    break

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
            for process, pattern_name, input_channel, process_id in processes:
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
            for process, pattern_name, input_channel, process_id in processes:
                if process.is_alive():
                    process.join(timeout=5)

                    if process.is_alive():
                        print(f"Force killing process {process_id} ({pattern_name})...")
                        process.kill()
                        process.join()

            print("All processes terminated")
            return  # Ctrl+C path exits here; fall-through only on mode switch

        # --- Mode-switch path: frame loop exited via break (not Ctrl+C) ---
        if pending_mode:
            pipe_reader.close_pipe()
            stop_run_mode(app_state)

            with app_state.lock:
                app_state._set_mode_unsafe(pending_mode)
            save_persisted_mode(pending_mode)
            # Loop back; the calibrate or run branch at the top will handle the new mode.
            continue

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
