#!/usr/bin/env python3
"""
Haven Trigger Gateway

A simple web server that manages trigger configurations via REST API and web interface.
Triggers are stored in a JSON configuration file (trigger_config.json).

Additionally handles:
- Service registration for receiving trigger events
- Trigger event dispatch to registered services
- Trigger status caching
"""

from flask import Flask, request, jsonify, send_from_directory
import json
import os
import socket
import threading
from datetime import datetime

app = Flask(__name__)

CONFIG_FILE = 'trigger_config.json'
REGISTRATION_FILE = 'service_registrations.json'

# Trigger types
TRIGGER_TYPES = ['On/Off', 'OneShot', 'Discrete', 'Continuous']

# Supported protocols for trigger dispatch
SUPPORTED_PROTOCOLS = ['OSC', 'TCP_SOCKET', 'TCP_CONNECT']

# In-memory cache of current trigger values (ID-based, not timestamp-based)
trigger_cache = {}

# In-memory registry of services
service_registry = []

# Persistent socket connections for TCP_SOCKET services
service_sockets = {}

# Lock for thread-safe socket operations
socket_lock = threading.Lock()


def load_config():
    """Load trigger configuration from file."""
    if not os.path.exists(CONFIG_FILE):
        return {'triggers': [], 'last_modified': None}
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {'triggers': [], 'last_modified': None}


def save_config(config):
    """Save trigger configuration to file."""
    config['last_modified'] = datetime.now().isoformat()
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def validate_trigger(trigger):
    """Validate trigger data structure."""
    if 'name' not in trigger or not trigger['name']:
        return False, "Trigger name is required"
    
    if 'type' not in trigger or trigger['type'] not in TRIGGER_TYPES:
        return False, f"Trigger type must be one of: {', '.join(TRIGGER_TYPES)}"
    
    # Validate range for Discrete and Continuous types
    if trigger['type'] in ['Discrete', 'Continuous']:
        if 'range' not in trigger or not trigger['range']:
            return False, f"Range is required for {trigger['type']} triggers"
    
    return True, None


# REST API Endpoints

@app.route('/')
def index():
    """Serve the main web interface."""
    return send_from_directory('.', 'index.html')


@app.route('/api/triggers', methods=['GET'])
def get_triggers():
    """Get all triggers with device status."""
    config = load_config()
    
    # Add device status to each trigger
    for trigger in config['triggers']:
        if 'last_seen' in trigger:
            trigger['device_status'] = calculate_device_status(trigger['last_seen'])
        else:
            trigger['device_status'] = 'offline'
    
    return jsonify(config)


def calculate_device_status(last_seen):
    """
    Calculate device status based on last_seen timestamp.
    Returns: 'online' or 'offline'
    """
    if not last_seen:
        print(f"DEBUG: No last_seen, returning offline")
        return 'offline'
    
    try:
        # Parse the last_seen timestamp (ISO 8601 format)
        # Handle formats like: 2026-01-17T08:44:52.088752
        last_seen_str = last_seen.replace('Z', '').replace('T', ' ')
        
        # Try parsing with microseconds
        try:
            last_seen_dt = datetime.strptime(last_seen_str, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            # Try without microseconds
            last_seen_dt = datetime.strptime(last_seen_str, '%Y-%m-%d %H:%M:%S')
        
        # Calculate time difference - both timestamps are naive (no timezone)
        now = datetime.now()
        time_delta = now - last_seen_dt
        minutes_ago = time_delta.total_seconds() / 60
        
        print(f"DEBUG: last_seen={last_seen}, now={now.isoformat()}, minutes_ago={minutes_ago:.2f}")
        
        # Consider device online if seen within last 5 minutes
        if minutes_ago < 5:
            print(f"DEBUG: Returning online (< 5 minutes)")
            return 'online'
        else:
            print(f"DEBUG: Returning offline (>= 5 minutes)")
            return 'offline'
    except Exception as e:
        print(f"Error parsing last_seen '{last_seen}': {e}")
        import traceback
        traceback.print_exc()
        return 'offline'


@app.route('/api/triggers', methods=['POST'])
def add_trigger():
    """Add a new trigger."""
    trigger = request.get_json()
    
    # Validate trigger
    valid, error_msg = validate_trigger(trigger)
    if not valid:
        return jsonify({'error': error_msg}), 400
    
    config = load_config()
    
    # Check if trigger with same name already exists
    if any(t['name'] == trigger['name'] for t in config['triggers']):
        return jsonify({'error': 'Trigger with this name already exists'}), 400
    
    config['triggers'].append(trigger)
    
    if save_config(config):
        return jsonify({'message': 'Trigger added successfully', 'trigger': trigger}), 201
    else:
        return jsonify({'error': 'Failed to save configuration'}), 500


@app.route('/api/triggers/<trigger_name>', methods=['GET'])
def get_trigger(trigger_name):
    """Get a specific trigger by name."""
    config = load_config()
    trigger = next((t for t in config['triggers'] if t['name'] == trigger_name), None)
    
    if trigger:
        return jsonify(trigger)
    else:
        return jsonify({'error': 'Trigger not found'}), 404


@app.route('/api/triggers/<trigger_name>', methods=['PUT'])
def update_trigger(trigger_name):
    """Update an existing trigger."""
    updated_trigger = request.get_json()
    
    # Validate trigger
    valid, error_msg = validate_trigger(updated_trigger)
    if not valid:
        return jsonify({'error': error_msg}), 400
    
    config = load_config()
    
    # Find and update the trigger
    for i, trigger in enumerate(config['triggers']):
        if trigger['name'] == trigger_name:
            # If name is being changed, check for conflicts
            if updated_trigger['name'] != trigger_name:
                if any(t['name'] == updated_trigger['name'] for t in config['triggers']):
                    return jsonify({'error': 'Trigger with new name already exists'}), 400
            
            config['triggers'][i] = updated_trigger
            
            if save_config(config):
                return jsonify({'message': 'Trigger updated successfully', 'trigger': updated_trigger})
            else:
                return jsonify({'error': 'Failed to save configuration'}), 500
    
    return jsonify({'error': 'Trigger not found'}), 404


@app.route('/api/triggers/<trigger_name>', methods=['DELETE'])
def delete_trigger(trigger_name):
    """Delete a trigger."""
    config = load_config()
    
    # Find and remove the trigger
    original_length = len(config['triggers'])
    config['triggers'] = [t for t in config['triggers'] if t['name'] != trigger_name]
    
    if len(config['triggers']) < original_length:
        if save_config(config):
            return jsonify({'message': 'Trigger deleted successfully'})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
    else:
        return jsonify({'error': 'Trigger not found'}), 404


@app.route('/api/trigger-types', methods=['GET'])
def get_trigger_types():
    """Get available trigger types."""
    return jsonify({'types': TRIGGER_TYPES})


@app.route('/api/register-device', methods=['POST'])
def register_device():
    """
    Register a device and automatically create/update its triggers.
    Expected data: {
        name: device name,
        ip: device IP address,
        triggers: [{name, type, range (optional)}]
    }
    
    This updates/creates triggers in trigger_config.json with device metadata.
    """
    data = request.get_json()
    
    if 'name' not in data or not data['name']:
        return jsonify({'error': 'Device name is required'}), 400
    
    if 'triggers' not in data or not isinstance(data['triggers'], list):
        return jsonify({'error': 'Triggers array is required'}), 400
    
    device_name = data['name']
    device_ip = data.get('ip', 'unknown')
    triggers_data = data['triggers']
    
    print(f"Device registration request from {device_name} ({device_ip})")
    
    # Load current trigger configuration
    config = load_config()
    
    # Track created/updated triggers
    created = []
    updated = []
    errors = []
    
    # Current timestamp for last_seen
    last_seen = datetime.now().isoformat()
    
    # Process each trigger from the device
    for trigger_data in triggers_data:
        # Validate trigger data
        valid, error_msg = validate_trigger(trigger_data)
        if not valid:
            errors.append(f"{trigger_data.get('name', 'unknown')}: {error_msg}")
            continue
        
        trigger_name = trigger_data['name']
        
        # Add device metadata to trigger
        trigger_data['device'] = device_name
        trigger_data['device_ip'] = device_ip
        trigger_data['last_seen'] = last_seen
        
        # Check if trigger already exists
        existing_idx = next((i for i, t in enumerate(config['triggers']) 
                           if t['name'] == trigger_name), None)
        
        if existing_idx is not None:
            # Update existing trigger, preserving any manual edits but updating device info
            existing = config['triggers'][existing_idx]
            trigger_data['manually_edited'] = existing.get('manually_edited', False)
            config['triggers'][existing_idx] = trigger_data
            updated.append(trigger_name)
        else:
            # Create new trigger
            trigger_data['manually_edited'] = False
            config['triggers'].append(trigger_data)
            created.append(trigger_name)
    
    # Save updated configuration
    if save_config(config):
        response = {
            'message': 'Device registered successfully',
            'device': device_name,
            'ip': device_ip,
            'triggers_created': created,
            'triggers_updated': updated
        }
        
        if errors:
            response['errors'] = errors
        
        print(f"Device {device_name} registered: {len(created)} created, {len(updated)} updated")
        return jsonify(response), 200
    else:
        return jsonify({'error': 'Failed to save trigger configuration'}), 500


# Socket Connection Management

def establish_socket_connection(service_name, host, port):
    """
    Establish a persistent TCP socket connection to a service.
    Returns the socket object or None if connection fails.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.settimeout(10)  # 10 second timeout for connection
        sock.connect((host, port))
        sock.settimeout(None)  # Remove timeout for ongoing communication
        print(f"Established persistent socket to {service_name} on {host}:{port}")
        return sock
    except Exception as e:
        print(f"Failed to establish socket to {service_name} on {host}:{port}: {e}")
        return None


def close_socket_connection(service_name):
    """Close and remove a persistent socket connection."""
    with socket_lock:
        if service_name in service_sockets:
            try:
                service_sockets[service_name].close()
                print(f"Closed socket connection to {service_name}")
            except Exception as e:
                print(f"Error closing socket to {service_name}: {e}")
            finally:
                del service_sockets[service_name]


def reconnect_socket(service_name, host, port):
    """Attempt to reconnect a broken socket."""
    print(f"Attempting to reconnect to {service_name}...")
    close_socket_connection(service_name)
    
    sock = establish_socket_connection(service_name, host, port)
    if sock:
        with socket_lock:
            service_sockets[service_name] = sock
        return True
    return False


def send_via_persistent_socket(service_name, sock, event_data):
    """
    Send data via a persistent socket.
    Returns True if successful, False if socket needs reconnection.
    """
    try:
        message = json.dumps(event_data) + '\n'
        sock.sendall(message.encode('utf-8'))
        return True
    except (socket.error, BrokenPipeError, ConnectionResetError) as e:
        print(f"Socket error sending to {service_name}: {e}")
        return False


# Service Registration and Trigger Dispatch Endpoints

def load_registrations():
    """Load service registrations from file."""
    global service_registry
    if not os.path.exists(REGISTRATION_FILE):
        service_registry = []
        return
    
    try:
        with open(REGISTRATION_FILE, 'r') as f:
            service_registry = json.load(f)
        
        # Re-establish TCP_SOCKET connections for registered services
        for service in service_registry:
            if service['protocol'] == 'TCP_SOCKET':
                host = service.get('host', 'localhost')
                sock = establish_socket_connection(service['name'], host, service['port'])
                if sock:
                    with socket_lock:
                        service_sockets[service['name']] = sock
    except Exception as e:
        print(f"Error loading registrations: {e}")
        service_registry = []


def save_registrations():
    """Save service registrations to file."""
    try:
        with open(REGISTRATION_FILE, 'w') as f:
            json.dump(service_registry, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving registrations: {e}")
        return False


@app.route('/api/register', methods=['POST'])
def register_service():
    """
    Register a service to receive trigger events.
    Required: name, port
    Optional: protocol (defaults to TCP_SOCKET), host (defaults to localhost)
    """
    data = request.get_json()
    
    if 'name' not in data or not data['name']:
        return jsonify({'error': 'Service name is required'}), 400
    
    if 'port' not in data:
        return jsonify({'error': 'Port is required'}), 400
    
    # Set defaults
    protocol = data.get('protocol', 'TCP_SOCKET')
    host = data.get('host', 'localhost')
    
    if protocol not in SUPPORTED_PROTOCOLS:
        return jsonify({'error': f'Protocol must be one of: {", ".join(SUPPORTED_PROTOCOLS)}'}), 400
    
    # Check if service already registered
    existing = next((s for s in service_registry if s['name'] == data['name']), None)
    
    registration = {
        'name': data['name'],
        'port': data['port'],
        'host': host,
        'protocol': protocol,
        'registered_at': datetime.now().isoformat()
    }
    
    # For TCP_SOCKET, establish persistent connection
    if protocol == 'TCP_SOCKET':
        # Close existing connection if any
        if existing:
            close_socket_connection(data['name'])
        
        sock = establish_socket_connection(data['name'], host, data['port'])
        if sock:
            with socket_lock:
                service_sockets[data['name']] = sock
            registration['socket_status'] = 'connected'
        else:
            registration['socket_status'] = 'failed'
            return jsonify({'error': f'Failed to establish socket connection to {host}:{data["port"]}'}), 500
    
    if existing:
        # Update existing registration
        service_registry[service_registry.index(existing)] = registration
        message = 'Service registration updated'
    else:
        # Add new registration
        service_registry.append(registration)
        message = 'Service registered successfully'
    
    save_registrations()
    
    return jsonify({'message': message, 'registration': registration}), 200


@app.route('/api/register/<service_name>', methods=['DELETE'])
def unregister_service(service_name):
    """Unregister a service and close its socket connection."""
    global service_registry
    
    service = next((s for s in service_registry if s['name'] == service_name), None)
    
    if not service:
        return jsonify({'error': 'Service not found'}), 404
    
    # Close socket connection if it exists
    if service['protocol'] == 'TCP_SOCKET':
        close_socket_connection(service_name)
    
    service_registry = [s for s in service_registry if s['name'] != service_name]
    save_registrations()
    
    return jsonify({'message': 'Service unregistered successfully'})


@app.route('/api/services', methods=['GET'])
def get_services():
    """Get all registered services with socket status."""
    services_with_status = []
    
    for service in service_registry:
        service_info = service.copy()
        if service['protocol'] == 'TCP_SOCKET':
            with socket_lock:
                service_info['socket_connected'] = service['name'] in service_sockets
        services_with_status.append(service_info)
    
    return jsonify({'services': services_with_status})


def dispatch_trigger_event(trigger_event):
    """
    Dispatch a trigger event to all registered services.
    Uses persistent sockets for TCP_SOCKET protocol.
    """
    def send_to_service(service, event_data):
        try:
            protocol = service['protocol']
            port = service['port']
            host = service.get('host', 'localhost')
            service_name = service['name']
            
            if protocol == 'TCP_SOCKET':
                # Use persistent socket
                with socket_lock:
                    sock = service_sockets.get(service_name)
                
                if sock:
                    success = send_via_persistent_socket(service_name, sock, event_data)
                    if success:
                        print(f"Sent trigger event to {service_name} via persistent socket")
                    else:
                        # Attempt reconnection
                        if reconnect_socket(service_name, host, port):
                            with socket_lock:
                                sock = service_sockets.get(service_name)
                            if sock and send_via_persistent_socket(service_name, sock, event_data):
                                print(f"Sent trigger event to {service_name} after reconnection")
                            else:
                                print(f"Failed to send after reconnection to {service_name}")
                        else:
                            print(f"Failed to reconnect to {service_name}")
                else:
                    print(f"No socket connection for {service_name}, attempting to establish...")
                    if reconnect_socket(service_name, host, port):
                        with socket_lock:
                            sock = service_sockets.get(service_name)
                        if sock and send_via_persistent_socket(service_name, sock, event_data):
                            print(f"Sent trigger event to {service_name} after establishing connection")
            
            elif protocol == 'TCP_CONNECT':
                # Create new connection for each event
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                try:
                    sock.connect((host, port))
                    message = json.dumps(event_data) + '\n'
                    sock.sendall(message.encode('utf-8'))
                    print(f"Sent trigger event to {service_name} via TCP_CONNECT")
                except Exception as e:
                    print(f"Error sending via TCP_CONNECT to {service_name}: {e}")
                finally:
                    sock.close()
            
            elif protocol == 'OSC':
                # OSC protocol placeholder
                print(f"OSC protocol not yet implemented for {service_name}")
                
        except Exception as e:
            print(f"Error dispatching to {service_name}: {e}")
    
    # Dispatch to all registered services in separate threads
    for service in service_registry:
        thread = threading.Thread(target=send_to_service, args=(service, trigger_event))
        thread.daemon = True
        thread.start()


@app.route('/api/trigger-event', methods=['POST'])
def trigger_event():
    """
    Receive a trigger event from a device.
    Expected data: {name, value (optional), id (optional)}
    
    Validates trigger exists in config, caches the value with ID, and dispatches to registered services.
    """
    data = request.get_json()

    print(f"DATA is: {data}")

    if 'name' not in data or not data['name']:
        return jsonify({'error': 'Trigger name is required'}), 400
    
    trigger_name = data['name']
    
    # Check if trigger exists in configuration
    config = load_config()
    trigger_def = next((t for t in config['triggers'] if t['name'] == trigger_name), None)
    
    if not trigger_def:
        error_msg = f"Trigger '{trigger_name}' not found in configuration"
        print(f"ERROR: {error_msg}")
        return jsonify({'error': error_msg}), 404
    
    # Build trigger event
    trigger_event = {
        'name': trigger_name,
        'timestamp': datetime.now().isoformat()
    }
    
    # Add value if provided (not for OneShot triggers)
    if 'value' in data:
        trigger_event['value'] = data['value']
    
    # Add id if provided (ID is the primary identifier)
    if 'id' in data:
        trigger_event['id'] = data['id']
    
    # Cache the trigger value with ID (except for OneShot)
    if trigger_def['type'] != 'OneShot':
        cache_entry = {
            'type': trigger_def['type'],
            'timestamp': trigger_event['timestamp']
        }
        
        if 'value' in trigger_event:
            cache_entry['value'] = trigger_event['value']
        
        # ID is the primary identifier - much more important than timestamp
        if 'id' in trigger_event:
            cache_entry['id'] = trigger_event['id']
        
        trigger_cache[trigger_name] = cache_entry
    
    # Dispatch to registered services
    dispatch_trigger_event(trigger_event)
    
    return jsonify({
        'message': 'Trigger event received and dispatched',
        'event': trigger_event,
        'dispatched_to': len(service_registry)
    }), 200


@app.route('/api/trigger-status', methods=['POST'])
def trigger_status():
    """
    Receive a trigger status update from a device.
    Expected data: {name, value, id (optional)}
    
    Updates the cache only with ID, does NOT dispatch to services.
    """
    data = request.get_json()
    
    if 'name' not in data or not data['name']:
        return jsonify({'error': 'Trigger name is required'}), 400
    
    trigger_name = data['name']
    
    # Check if trigger exists in configuration
    config = load_config()
    trigger_def = next((t for t in config['triggers'] if t['name'] == trigger_name), None)
    
    if not trigger_def:
        return jsonify({'error': f"Trigger '{trigger_name}' not found in configuration"}), 404
    
    # Only cache for On/Off, Discrete, and Continuous triggers
    if trigger_def['type'] != 'OneShot' and 'value' in data:
        cache_entry = {
            'value': data['value'],
            'timestamp': datetime.now().isoformat(),
            'type': trigger_def['type']
        }
        
        # ID is the primary identifier
        if 'id' in data:
            cache_entry['id'] = data['id']
        
        trigger_cache[trigger_name] = cache_entry
        
        return jsonify({
            'message': 'Trigger status updated',
            'trigger': trigger_name,
            'value': data['value'],
            'id': data.get('id')
        }), 200
    
    return jsonify({'error': 'Invalid trigger type or missing value'}), 400


@app.route('/api/trigger-status', methods=['GET'])
def get_trigger_status():
    """
    Get current cached values (with IDs) for all On/Off, Discrete, and Continuous triggers.
    """
    return jsonify({
        'triggers': trigger_cache,
        'count': len(trigger_cache)
    })


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Haven Trigger Server')
    parser.add_argument('--port', type=int, default=5002, 
                        help='Port to run the web server on (default: 5002)')
    args = parser.parse_args()
    
    port = args.port
    
    print("Haven Trigger Server starting...")
    print(f"Configuration file: {CONFIG_FILE}")
    print(f"Registration file: {REGISTRATION_FILE}")
    
    # Load existing registrations and re-establish TCP_SOCKET connections
    print("Loading service registrations...")
    load_registrations()
    print(f"Loaded {len(service_registry)} registered service(s)")
    
    print(f"Web interface: http://localhost:{port}")
    print("API endpoints:")
    print(f"  - Trigger Configuration: http://localhost:{port}/api/triggers")
    print(f"  - Service Registration: http://localhost:{port}/api/register")
    print(f"  - Trigger Events: http://localhost:{port}/api/trigger-event")
    print(f"  - Trigger Status: http://localhost:{port}/api/trigger-status")
    
    app.run(host='0.0.0.0', port=port, debug=True)
