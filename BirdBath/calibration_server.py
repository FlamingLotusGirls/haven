#!/usr/bin/env python3
"""
Calibration web server for nozzle calibration management.
Provides REST API endpoints for getting and setting nozzle calibration data.
Reads and writes to driver_config.yaml file.
"""

import json
import os
import time
import argparse
import yaml
import socket
import struct
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import re


class CalibrationHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for nozzle calibration API.
    """
    
    # Class-level cache for controller IPs (shared across all handler instances)
    _controllers = None
    _config_file = None

    DATA_FRAME = 0
    DATA_NOZZLE = 1
    
    def __init__(self, *args, config_file='driver_config.yaml', **kwargs):
        self.config_file = config_file
        
        # Load controller configuration once if not already loaded
        if CalibrationHandler._controllers is None or CalibrationHandler._config_file != config_file:
            CalibrationHandler._config_file = config_file
            CalibrationHandler._controllers = self._load_controllers()
        
        super().__init__(*args, **kwargs)
    
    def _load_controllers(self) -> list:
        """Load controller configuration once during initialization."""
        try:
            config = self._load_driver_config()
            if 'controllers' not in config:
                print("Warning: No controllers found in driver config, using defaults")
                return [
                    {'ip': '10.0.0.4'},
                    {'ip': '10.0.0.5'},
                    {'ip': '10.0.0.6'}
                ]
            
            controllers = config['controllers']
            print(f"Loaded {len(controllers)} controllers: {[c['ip'] for c in controllers]}")
            return controllers
            
        except Exception as e:
            print(f"Error loading controllers, using defaults: {str(e)}")
            return [
                {'ip': '10.0.0.4'},
                {'ip': '10.0.0.5'},
                {'ip': '10.0.0.6'}
            ]
    
    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)
        
        # Serve calibration interface at root
        if parsed_path.path == '/' or parsed_path.path == '/index.html':
            self._serve_calibration_interface()
        # Match GET /nozzles (all nozzle status)
        elif parsed_path.path == '/nozzles':
            self._get_all_nozzle_status()
        # Match GET /nozzle/<id>/calibration
        elif re.match(r'^/nozzle/(\d+)/calibration$', parsed_path.path):
            match = re.match(r'^/nozzle/(\d+)/calibration$', parsed_path.path)
            nozzle_id = int(match.group(1))
            self._get_nozzle_calibration(nozzle_id)
        else:
            self._send_404()
    
    def do_PUT(self):
        """Handle PUT requests."""
        parsed_path = urlparse(self.path)
        
        # Match PUT /nozzle/<id>/calibration/high
        match = re.match(r'^/nozzle/(\d+)/calibration/high$', parsed_path.path)
        if match:
            nozzle_id = int(match.group(1))
            self._set_nozzle_calibration_high(nozzle_id)
            return
        
        # Match PUT /nozzle/<id>/calibration/low
        match = re.match(r'^/nozzle/(\d+)/calibration/low$', parsed_path.path)
        if match:
            nozzle_id = int(match.group(1))
            self._set_nozzle_calibration_low(nozzle_id)
            return
        
        # Match PUT /nozzle/<id>/position
        match = re.match(r'^/nozzle/(\d+)/position$', parsed_path.path)
        if match:
            nozzle_id = int(match.group(1))
            self._set_nozzle_position(nozzle_id)
            return
        
        self._send_404()
    
    def _get_all_nozzle_status(self):
        """Get current valve status from all controllers via UDP."""
        try:
            # Use cached controllers
            if CalibrationHandler._controllers is None:
                self._send_error(500, "Controller configuration not loaded")
                return
            
            all_nozzle_values = []
            controller_responses = {}
            
            # Query each controller via UDP
            for controller_idx, controller in enumerate(CalibrationHandler._controllers):
                controller_ip = controller['ip']
                
                try:
                    # Send UDP STATUS request
                    valve_values = self._query_controller_status(controller_ip)
                    if valve_values is not None:
                        controller_responses[controller_idx] = {
                            'ip': controller_ip,
                            'status': 'success',
                            'values': valve_values
                        }
                        all_nozzle_values.extend(valve_values)
                    else:
                        controller_responses[controller_idx] = {
                            'ip': controller_ip,
                            'status': 'timeout',
                            'values': [0] * 12  # Default to 0 for unreachable controllers
                        }
                        all_nozzle_values.extend([0] * 12)
                        
                except Exception as e:
                    print(f"Error querying controller {controller_idx} ({controller_ip}): {str(e)}")
                    controller_responses[controller_idx] = {
                        'ip': controller_ip,
                        'status': 'error',
                        'error': str(e),
                        'values': [0] * 12
                    }
                    all_nozzle_values.extend([0] * 12)
            
            # Pad to ensure we have exactly 36 values
            while len(all_nozzle_values) < 36:
                all_nozzle_values.append(0)
            
            # Trim to exactly 36 values
            all_nozzle_values = all_nozzle_values[:36]
            
            # Send JSON response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response_data = {
                'nozzle_count': 36,
                'values': all_nozzle_values,
                'controllers': controller_responses,
                'timestamp': time.time()
            }
            
            json_data = json.dumps(response_data, indent=2)
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            print(f"Error getting all nozzle status: {str(e)}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _query_controller_status(self, controller_ip: str, timeout: float = 0.25) -> list:
        """
        Send UDP STATUS request to a controller and return valve values.
        
        Args:
            controller_ip (str): IP address of the controller
            timeout (float): Timeout in seconds for UDP response
            
        Returns:
            list: List of 12 valve values (0-255), or None if failed
        """
        try:
            # Create UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            
            try:
                # Send STATUS request
                status_message = b"STATUS"
                sock.sendto(status_message, (controller_ip, 7777))
                print(f"Sent STATUS request to {controller_ip}:7777")
                
                # Wait for response
                response_data, addr = sock.recvfrom(1024)  # Buffer for up to 1024 bytes
                
                # Convert bytes to list of integers
                valve_values = list(response_data)
                
                print(f"Received {len(valve_values)} valve values from {controller_ip}: {valve_values}")
                
                # Ensure we have exactly 12 values (pad or trim as needed)
                if len(valve_values) < 12:
                    valve_values.extend([0] * (12 - len(valve_values)))
                elif len(valve_values) > 12:
                    valve_values = valve_values[:12]
                
                return valve_values
                
            finally:
                sock.close()
                
        except socket.timeout:
            print(f"Timeout waiting for response from {controller_ip}")
            return None
        except Exception as e:
            print(f"Error querying controller {controller_ip}: {str(e)}")
            return None

    def _get_nozzle_calibration(self, nozzle_id: int):
        """Get calibration data for a specific nozzle."""
        try:
            # Validate nozzle ID
            if not (0 <= nozzle_id < 36):
                self._send_error(400, f"Invalid nozzle ID: {nozzle_id}. Must be 0-35.")
                return
            
            # Load driver config
            config = self._load_driver_config()
            
            # Get nozzle range (calibration data)
            if 'ranges' not in config or len(config['ranges']) <= nozzle_id:
                self._send_error(500, f"Nozzle {nozzle_id} not found in driver configuration")
                return
            
            nozzle_range = config['ranges'][nozzle_id]
            if not isinstance(nozzle_range, list) or len(nozzle_range) != 2:
                self._send_error(500, f"Invalid range format for nozzle {nozzle_id}")
                return
            
            low_value, high_value = nozzle_range
            
            # Send JSON response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response_data = {
                'nozzle_id': nozzle_id,
                'calibration': {
                    'low': low_value,
                    'high': high_value
                }
            }
            
            json_data = json.dumps(response_data, indent=2)
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            print(f"Error getting nozzle {nozzle_id} calibration: {str(e)}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _set_nozzle_calibration_high(self, nozzle_id: int):
        """Set the high calibration value for a nozzle."""
        try:
            # Validate nozzle ID
            if not (0 <= nozzle_id < 36):
                self._send_error(400, f"Invalid nozzle ID: {nozzle_id}. Must be 0-35.")
                return
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length).decode('utf-8')
                try:
                    data = json.loads(body)
                    high_value = int(data.get('value', 255))
                except (json.JSONDecodeError, ValueError, TypeError):
                    self._send_error(400, "Invalid JSON body. Expected: {'value': <int>}")
                    return
            else:
                # Default high value if no body provided
                high_value = 255
            
            # Validate range
            if not (0 <= high_value <= 255):
                self._send_error(400, f"High value must be between 0 and 255, got {high_value}")
                return
            
            # Load, update, and save driver config
            config = self._load_driver_config()
            
            if 'ranges' not in config:
                config['ranges'] = [[0, 255]] * 36
            
            if len(config['ranges']) <= nozzle_id:
                # Extend ranges array if needed
                while len(config['ranges']) <= nozzle_id:
                    config['ranges'].append([0, 255])
            
            # Update high value (second element of the range)
            current_low = config['ranges'][nozzle_id][0] if isinstance(config['ranges'][nozzle_id], list) else 0
            config['ranges'][nozzle_id] = [current_low, high_value]
            
            self._save_driver_config(config)
            
            # Send success response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response_data = {
                'nozzle_id': nozzle_id,
                'high_value': high_value,
                'range': config['ranges'][nozzle_id],
                'message': f'High calibration value set to {high_value} for nozzle {nozzle_id}'
            }
            
            json_data = json.dumps(response_data)
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            print(f"Error setting nozzle {nozzle_id} high calibration: {str(e)}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _set_nozzle_calibration_low(self, nozzle_id: int):
        """Set the low calibration value for a nozzle."""
        try:
            # Validate nozzle ID
            if not (0 <= nozzle_id < 36):
                self._send_error(400, f"Invalid nozzle ID: {nozzle_id}. Must be 0-35.")
                return
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length).decode('utf-8')
                try:
                    data = json.loads(body)
                    low_value = int(data.get('value', 0))
                except (json.JSONDecodeError, ValueError, TypeError):
                    self._send_error(400, "Invalid JSON body. Expected: {'value': <int>}")
                    return
            else:
                # Default low value if no body provided
                low_value = 0
            
            # Validate range
            if not (0 <= low_value <= 255):
                self._send_error(400, f"Low value must be between 0 and 255, got {low_value}")
                return
            
            # Load, update, and save driver config
            config = self._load_driver_config()
            
            if 'ranges' not in config:
                config['ranges'] = [[0, 255]] * 36
            
            if len(config['ranges']) <= nozzle_id:
                # Extend ranges array if needed
                while len(config['ranges']) <= nozzle_id:
                    config['ranges'].append([0, 255])
            
            # Update low value (first element of the range)
            current_high = config['ranges'][nozzle_id][1] if isinstance(config['ranges'][nozzle_id], list) else 255
            config['ranges'][nozzle_id] = [low_value, current_high]
            
            self._save_driver_config(config)
            
            # Send success response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response_data = {
                'nozzle_id': nozzle_id,
                'low_value': low_value,
                'range': config['ranges'][nozzle_id],
                'message': f'Low calibration value set to {low_value} for nozzle {nozzle_id}'
            }
            
            json_data = json.dumps(response_data)
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            print(f"Error setting nozzle {nozzle_id} low calibration: {str(e)}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _set_nozzle_position(self, nozzle_id: int):
        """Set the position for a nozzle by sending Artnet packet with raw value [0, 255]."""
        try:
            # Validate nozzle ID
            if not (0 <= nozzle_id < 36):
                self._send_error(400, f"Invalid nozzle ID: {nozzle_id}. Must be 0-35.")
                return
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self._send_error(400, "Request body required. Expected: {'value': <int>} where value is in [0, 255]")
                return
            
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                # Expect a raw value to send directly to the nozzle
                raw_value = int(data.get('value', 0))
                
                # Validate range [0, 255]
                if not (0 <= raw_value <= 255):
                    self._send_error(400, f"Value must be between 0 and 255, got {raw_value}")
                    return
                
            except (json.JSONDecodeError, ValueError, TypeError):
                self._send_error(400, "Invalid JSON body. Expected: {'value': <int>}")
                return
            
            # Use cached controllers (loaded once during initialization)
            if CalibrationHandler._controllers is None:
                self._send_error(500, "Controller configuration not loaded")
                return
            
            # Send Artnet packet to control the specific nozzle with raw value
            success = self._send_nozzle_artnet_packet(nozzle_id, float(raw_value), CalibrationHandler._controllers)
            
            if success:
                # Send success response
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                response_data = {
                    'nozzle_id': nozzle_id,
                    'raw_value': raw_value,
                    'message': f'Artnet packet sent to nozzle {nozzle_id} with raw value {raw_value}'
                }
                
                json_data = json.dumps(response_data)
                self.wfile.write(json_data.encode('utf-8'))
            else:
                self._send_error(500, f"Failed to send Artnet packet to nozzle {nozzle_id}")
            
        except Exception as e:
            print(f"Error setting nozzle {nozzle_id} position: {str(e)}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _send_nozzle_artnet_packet(self, nozzle_id: int, value: float, controllers: list) -> bool:
        """
        Send Artnet packet to control a specific nozzle.
        
        Args:
            nozzle_id (int): Nozzle ID (0-35)
            value (float): Raw value to send (0-255)
            controllers (list): List of controller configurations
            
        Returns:
            bool: True if packet was sent successfully
        """
        try:
            # Determine which controller this nozzle belongs to
            controller_idx = nozzle_id // 12  # 12 nozzles per controller
            channel_in_controller = nozzle_id % 12
            
            if controller_idx >= len(controllers):
                print(f"Controller index {controller_idx} out of range for nozzle {nozzle_id}")
                return False
            
            controller_ip = controllers[controller_idx]['ip']
            
            # Packet to control a single nozzle has a two-byte header -
            # PacketType (1, in this case)
            # NozzleId
            # followed by the two bytes of data for that nozzle.
            controller_data_header = [CalibrationHandler.DATA_NOZZLE, channel_in_controller]
            controller_data = [[CalibrationHandler.DATA_FRAME, value]]
            
            # Create and send Artnet packet
            packet = self._create_artnet_packet(controller_idx, controller_data_header, controller_data)
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.sendto(packet, (controller_ip, 6454))  # Standard Artnet port
                print(f"Sent Artnet packet to controller {controller_idx} ({controller_ip}) for nozzle {nozzle_id}, raw_value={value:.0f}")
                return True
            finally:
                sock.close()
                
        except Exception as e:
            print(f"Error sending Artnet packet for nozzle {nozzle_id}: {str(e)}")
            return False
    
    def _create_artnet_packet(self, universe: int, data_header: list, data: list) -> bytes:
        """
        Create an Artnet packet with the given data.
        
        Args:
            universe (int): Artnet universe number
            data (list): List of (bool, float) tuples for the packet
            
        Returns:
            bytes: Complete Artnet packet
        """
        # Artnet header
        header = b"Art-Net\x00"  # 8 bytes
        opcode = struct.pack("<H", 0x5000)  # ArtDMX opcode (little endian)
        protocol_version = struct.pack(">H", 14)  # Protocol version (big endian)
        sequence = struct.pack("B", 0)  # Sequence (we'll use 0 for simplicity)
        physical = struct.pack("B", 0)  # Physical input/output port
        universe_bytes = struct.pack("<H", universe)  # Universe (little endian)

        packet_data = bytearray()
        data_header_len = 0

        if data_header[0] == CalibrationHandler.DATA_NOZZLE:
            packet_data.append(CalibrationHandler.DATA_NOZZLE)
            packet_data.append(data_header[1])
            data_header_len = 2
        elif data_header[0] == CalibrationHandler.DATA_FRAME:
            packet_data.append(CalibrationHandler.DATA_FRAME)
            data_header_len = 1
        
        # Data length (2 bytes per tuple: 1 byte bool + 1 byte for float as byte)
        data_length = struct.pack(">H", (len(data) * 2) + data_header_len)  # Big endian
        
        # Pack data as series of [bool, float] where bool is always 0 and float is converted to byte
        packet_data = bytearray()
        for bool_val, float_val in data:
            packet_data.append(0)  # Bool is always 0 (false)
            # Convert float to byte (0-255 range)
            byte_val = max(0, min(255, int(float_val)))
            packet_data.append(byte_val)
        
        # Combine all parts
        packet = header + opcode + protocol_version + sequence + physical + universe_bytes + data_length + packet_data
        
        return packet
    
    def _load_driver_config(self) -> dict:
        """Load driver configuration from YAML file."""
        if not os.path.exists(self.config_file):
            # Create default config if file doesn't exist
            default_config = {
                'controllers': [
                    {'ip': '10.0.0.4'},
                    {'ip': '10.0.0.5'},
                    {'ip': '10.0.0.6'}
                ],
                'ranges': [[0, 255]] * 36
            }
            self._save_driver_config(default_config)
            return default_config
        
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f)
        except (yaml.YAMLError, IOError) as e:
            print(f"Error loading driver config: {str(e)}")
            raise
    
    def _save_driver_config(self, config: dict):
        """Save driver configuration to YAML file."""
        try:
            # Write to temporary file first, then rename for atomic operation
            temp_file = self.config_file + '.tmp'
            with open(temp_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, indent=2)
            
            # Atomic rename to avoid partial reads
            os.rename(temp_file, self.config_file)
            
        except Exception as e:
            # Clean up temp file if it exists
            temp_file = self.config_file + '.tmp'
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
            raise e
    
    def _send_404(self):
        """Send 404 Not Found response."""
        self.send_response(404)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        error_data = {
            'error': 'Not Found',
            'message': 'Endpoint not found',
            'available_endpoints': [
                'GET /nozzles',
                'GET /nozzle/<id>/calibration',
                'PUT /nozzle/<id>/calibration/high',
                'PUT /nozzle/<id>/calibration/low',
                'PUT /nozzle/<id>/position'
            ]
        }
        
        json_data = json.dumps(error_data, indent=2)
        self.wfile.write(json_data.encode('utf-8'))
    
    def _serve_calibration_interface(self):
        """Serve the nozzle calibration HTML interface."""
        try:
            # Try to read the nozzle_calibration.html file
            if os.path.exists('nozzle_calibration.html'):
                with open('nozzle_calibration.html', 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
            else:
                # Fallback if calibration interface file doesn't exist
                self._serve_fallback_interface()
                
        except Exception as e:
            print(f"Error serving calibration interface: {str(e)}")
            self._send_error(500, f"Error loading calibration interface: {str(e)}")
    
    def _serve_fallback_interface(self):
        """Serve a fallback interface if calibration HTML file is missing."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Nozzle Calibration API</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                h1 { color: #333; }
                .endpoint { background: #f8f9fa; padding: 15px; border-radius: 4px; margin: 10px 0; }
                code { background: #e9ecef; padding: 2px 6px; border-radius: 3px; }
                .error { color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 4px; margin: 10px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Nozzle Calibration API</h1>
                
                <div class="error">
                    <strong>Warning:</strong> nozzle_calibration.html file not found. 
                    Please ensure the calibration interface file is in the same directory as this server.
                </div>
                
                <p>REST API for nozzle calibration and direct hardware control.</p>
                
                <h2>Endpoints</h2>
                <div class="endpoint">
                    <strong>GET /nozzle/&lt;id&gt;/calibration</strong><br>
                    Returns calibration data (low/high values) for the specified nozzle.<br>
                    <code>Content-Type: application/json</code>
                </div>
                
                <div class="endpoint">
                    <strong>PUT /nozzle/&lt;id&gt;/calibration/high</strong><br>
                    Sets the high calibration value for the specified nozzle.<br>
                    <code>Body: {"value": 255}</code>
                </div>
                
                <div class="endpoint">
                    <strong>PUT /nozzle/&lt;id&gt;/calibration/low</strong><br>
                    Sets the low calibration value for the specified nozzle.<br>
                    <code>Body: {"value": 0}</code>
                </div>
                
                <div class="endpoint">
                    <strong>PUT /nozzle/&lt;id&gt;/position</strong><br>
                    Sends raw value (0-255) directly to nozzle via Artnet.<br>
                    <code>Body: {"value": 150}</code>
                </div>
                
                <h2>Usage</h2>
                <p>This server reads/writes calibration data from <code>driver_config.yaml</code> and sends Artnet packets for direct nozzle control.</p>
                <p>Nozzle IDs: 0-35 (corresponding to ranges array index in config file)</p>
            </div>
        </body>
        </html>
        """
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _send_error(self, code: int, message: str):
        """Send error response."""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        error_data = {
            'error': f'HTTP {code}',
            'message': message
        }
        
        json_data = json.dumps(error_data)
        self.wfile.write(json_data.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to customize logging."""
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {format % args}")


def create_handler_class(config_file):
    """Create a handler class with the specified config file."""
    class Handler(CalibrationHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, config_file=config_file, **kwargs)
    return Handler


def main():
    """Main function to start the calibration web server."""
    parser = argparse.ArgumentParser(description='Nozzle Calibration Web Server')
    parser.add_argument('--port', '-p', type=int, default=8081,
                       help='Port to run the server on (default: 8081)')
    parser.add_argument('--host', default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--config-file', default='driver_config.yaml',
                       help='YAML config file for driver configuration (default: driver_config.yaml)')
    
    args = parser.parse_args()
    
    # Create handler class with config file
    handler_class = create_handler_class(args.config_file)
    
    # Create and start server
    server = HTTPServer((args.host, args.port), handler_class)
    
    print(f"Starting nozzle calibration server on http://{args.host}:{args.port}")
    print(f"Driver configuration file: {args.config_file}")
    print("\nAvailable endpoints:")
    print("  GET /nozzles                       - Get current status of all nozzles via UDP")
    print("  GET /nozzle/<id>/calibration       - Get calibration data for nozzle")
    print("  PUT /nozzle/<id>/calibration/high  - Set high calibration value (0-255)")
    print("  PUT /nozzle/<id>/calibration/low   - Set low calibration value (0-255)")
    print("  PUT /nozzle/<id>/position          - Set nozzle position (x, y, angle)")
    print("\nNozzle IDs: 0-35 (corresponding to ranges array index)")
    print("Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
