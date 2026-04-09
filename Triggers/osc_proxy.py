#!/usr/bin/env python3
"""
Haven OSC Proxy Server

Proxies trigger events from the Trigger Gateway to OSC clients.
Provides a web interface for mapping triggers to OSC commands.
"""

from flask import Flask, request, jsonify, send_from_directory
import json
import os
import socket
import tempfile
import threading
import requests
from datetime import datetime
from pythonosc import udp_client
from pythonosc.osc_message_builder import OscMessageBuilder
import time
import argparse

app = Flask(__name__)

CONFIG_FILE = 'osc_proxy_config.json'
GATEWAY_URL = 'http://localhost:5002'
MODE_SERVICE_URL = 'http://localhost:5003'
SERVICE_NAME = 'OSC_Proxy'

# Global configuration
config = {
    'osc_client': {
        'host': '127.0.0.1',
        'port': 8000
    },
    'mappings': [],
    'osc_aliases': [],      # list of {id, alias, osc_address, osc_args, description}
    'gateway_url': GATEWAY_URL,
    'mode_service_url': MODE_SERVICE_URL,
    'service_port': 5100
}

# ── Mode tracking ──────────────────────────────────────────────────────────────
# Cached active mode, updated every ~10 s by the mode-poll thread.
# Empty string means "no active mode".
_active_mode = ''
_active_mode_lock = threading.Lock()


def get_current_mode():
    """Return the cached active mode name ('' if none)."""
    with _active_mode_lock:
        return _active_mode


def _poll_mode_service():
    """Background thread: poll the mode service every 10 s and cache the result."""
    global _active_mode
    while True:
        try:
            url = config.get('mode_service_url', MODE_SERVICE_URL)
            r = requests.get(f"{url}/api/modes/active", timeout=4)
            if r.status_code == 200:
                new_mode = r.json().get('active_mode') or ''
                with _active_mode_lock:
                    if new_mode != _active_mode:
                        print(f"[mode] active mode changed: '{_active_mode}' → '{new_mode}'")
                        _active_mode = new_mode
        except Exception as e:
            # Mode service may not be running — silently keep the last known mode
            print(f"[mode] could not reach mode service: {e}")
        time.sleep(10)

# OSC client instance
osc_client_instance = None

# Socket server for receiving trigger events
socket_server = None
socket_server_thread = None
server_running = False

# Protects all read-modify-write operations on the config dict.
# Flask threads mutate config['mappings'] and config['osc_client'];
# the socket-server thread reads config['mappings'] in process_trigger_event.
config_lock = threading.Lock()


def load_config():
    """Load configuration from file."""
    global config, osc_client_instance
    if not os.path.exists(CONFIG_FILE):
        save_config()
        return
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded = json.load(f)
            config.update(loaded)
        
        # Initialize OSC client with loaded config
        init_osc_client()
        
        print(f"Configuration loaded from {CONFIG_FILE}")
    except Exception as e:
        print(f"Error loading config: {e}")


def save_config():
    """Save configuration to file atomically.

    Callers must hold config_lock for the full load→modify→save cycle.
    """
    tmpname = None
    try:
        config_dir = os.path.dirname(os.path.abspath(CONFIG_FILE)) or '.'
        with tempfile.NamedTemporaryFile('w', dir=config_dir, suffix='.tmp', delete=False) as f:
            tmpname = f.name
            json.dump(config, f, indent=2)
        os.replace(tmpname, CONFIG_FILE)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        if tmpname:
            try:
                os.unlink(tmpname)
            except OSError:
                pass
        return False


def init_osc_client():
    """Initialize or reinitialize the OSC client."""
    global osc_client_instance
    try:
        osc_client_instance = udp_client.SimpleUDPClient(
            config['osc_client']['host'],
            config['osc_client']['port']
        )
        print(f"OSC client initialized: {config['osc_client']['host']}:{config['osc_client']['port']}")
    except Exception as e:
        print(f"Error initializing OSC client: {e}")
        osc_client_instance = None


def register_with_gateway():
    """Register this service with the Trigger Gateway."""
    try:
        registration_data = {
            'name': SERVICE_NAME,
            'port': config['service_port'],
            'host': 'localhost',
            'protocol': 'TCP_SOCKET'
        }
        
        response = requests.post(
            f"{config['gateway_url']}/api/register",
            json=registration_data,
            timeout=5
        )
        
        if response.status_code == 200:
            print(f"Successfully registered with gateway as {SERVICE_NAME}")
            return True
        else:
            print(f"Failed to register with gateway: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Error registering with gateway: {e}")
        return False


def unregister_from_gateway():
    """Unregister this service from the Trigger Gateway."""
    try:
        response = requests.delete(
            f"{config['gateway_url']}/api/register/{SERVICE_NAME}",
            timeout=5
        )
        
        if response.status_code == 200:
            print(f"Successfully unregistered from gateway")
        else:
            print(f"Failed to unregister from gateway: {response.status_code}")
    except Exception as e:
        print(f"Error unregistering from gateway: {e}")


def get_available_triggers():
    """Fetch available triggers from the gateway."""
    try:
        response = requests.get(
            f"{config['gateway_url']}/api/triggers",
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get('triggers', [])
        else:
            print(f"Failed to get triggers from gateway: {response.status_code}")
            return []
    except Exception as e:
        print(f"Error fetching triggers from gateway: {e}")
        return []


def parse_osc_value(value_str, trigger_value):
    """
    Parse OSC value string, supporting variable substitution.
    ${value} will be replaced with the trigger value.
    ${value:int} will convert to integer.
    ${value:float} will convert to float.
    """
    if not isinstance(value_str, str):
        return value_str
    
    # Check for variable substitution
    if '${value}' in value_str:
        return value_str.replace('${value}', str(trigger_value))
    elif '${value:int}' in value_str:
        try:
            return int(trigger_value)
        except (ValueError, TypeError):
            return 0
    elif '${value:float}' in value_str:
        try:
            return float(trigger_value)
        except (ValueError, TypeError):
            return 0.0
    
    # Try to parse as number
    try:
        if '.' in value_str:
            return float(value_str)
        else:
            return int(value_str)
    except ValueError:
        # Return as string
        return value_str


def send_osc_message(osc_address, osc_args, trigger_value=None):
    """Send an OSC message."""
    if not osc_client_instance:
        print("OSC client not initialized")
        return False
    
    try:
        # Parse arguments with variable substitution
        parsed_args = []
        for arg in osc_args:
            parsed_arg = parse_osc_value(arg, trigger_value)
            parsed_args.append(parsed_arg)
        
        # Send OSC message
        if parsed_args:
            osc_client_instance.send_message(osc_address, parsed_args)
        else:
            osc_client_instance.send_message(osc_address, None)
        
        print(f"Sent OSC: {osc_address} {parsed_args}")
        return True
    except Exception as e:
        print(f"Error sending OSC message: {e}")
        return False


def process_trigger_event(trigger_event):
    """Process a trigger event and send corresponding OSC messages."""
    trigger_name = trigger_event.get('name')
    trigger_value = trigger_event.get('value')
    
    print(f"Processing trigger event: {trigger_name} = {trigger_value}")

    # Snapshot active mode once for this event (avoids repeated lock acquisitions).
    active_mode = get_current_mode()

    # Take a snapshot of the current mappings under the lock so mutations from
    # Flask threads do not race with our iteration (which may call send_osc_message,
    # an operation we do not want to hold the lock across).
    with config_lock:
        current_mappings = list(config['mappings'])
    
    # Find matching mappings
    matched = False
    for mapping in current_mappings:
        if mapping.get('trigger_name') == trigger_name:
            # Check if this mapping is enabled
            if not mapping.get('enabled', True):
                continue

            # ── Mode gate ──────────────────────────────────────────────────────
            # If the mapping specifies one or more modes, only fire when the
            # active mode is in that list.  An empty (or absent) modes list
            # means "active in all modes".
            allowed_modes = mapping.get('modes', [])
            if allowed_modes:                       # non-empty → restrict
                if active_mode not in allowed_modes:
                    print(f"[mode] skipping mapping {mapping.get('id')} "
                          f"(active='{active_mode}', allowed={allowed_modes})")
                    continue
            # ──────────────────────────────────────────────────────────────────

            osc_address = mapping.get('osc_address')
            osc_args = mapping.get('osc_args', [])
            
            if osc_address:
                send_osc_message(osc_address, osc_args, trigger_value)
                matched = True
    
    if not matched:
        print(f"No OSC mapping found for trigger: {trigger_name}")


def handle_client_connection(client_socket, client_address):
    """Handle a single client connection."""
    print(f"Client connected from {client_address}")
    buffer = ""
    MAX_BUFFER = 65536  # 64 KB — close connection if no newline arrives by then
    
    try:
        while server_running:
            data = client_socket.recv(4096)
            if not data:
                break
            
            # Decode and add to buffer
            buffer += data.decode('utf-8')
            
            # Guard against unbounded buffer growth from malformed / run-away clients
            if len(buffer) > MAX_BUFFER:
                print(f"Buffer limit exceeded from {client_address}, closing connection")
                break
            
            # Process complete JSON messages (newline-delimited)
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                
                if line:
                    try:
                        trigger_event = json.loads(line)
                        process_trigger_event(trigger_event)
                    except json.JSONDecodeError as e:
                        print(f"Error parsing trigger event: {e}")
    except Exception as e:
        print(f"Error handling client connection: {e}")
    finally:
        client_socket.close()
        print(f"Client disconnected from {client_address}")


def run_socket_server():
    """Run the TCP socket server to receive trigger events."""
    global socket_server, server_running
    
    socket_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    socket_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        socket_server.bind(('0.0.0.0', config['service_port']))
        socket_server.listen(5)
        socket_server.settimeout(1.0)  # Timeout to check server_running flag
        
        print(f"Socket server listening on port {config['service_port']}")
        
        while server_running:
            try:
                client_socket, client_address = socket_server.accept()
                # Handle each connection in a separate thread
                client_thread = threading.Thread(
                    target=handle_client_connection,
                    args=(client_socket, client_address)
                )
                client_thread.daemon = True
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if server_running:
                    print(f"Error accepting connection: {e}")
    except Exception as e:
        print(f"Error starting socket server: {e}")
    finally:
        if socket_server:
            socket_server.close()
        print("Socket server stopped")


def start_socket_server():
    """Start the socket server in a separate thread."""
    global socket_server_thread, server_running
    
    if socket_server_thread and socket_server_thread.is_alive():
        print("Socket server already running")
        return
    
    server_running = True
    socket_server_thread = threading.Thread(target=run_socket_server)
    socket_server_thread.daemon = True
    socket_server_thread.start()


def stop_socket_server():
    """Stop the socket server."""
    global server_running, socket_server
    
    server_running = False
    
    if socket_server:
        socket_server.close()
    
    if socket_server_thread:
        socket_server_thread.join(timeout=2)


# Flask Web Interface

@app.route('/')
def index():
    """Serve the web interface."""
    return send_from_directory('.', 'osc_proxy.html')


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration."""
    return jsonify(config)


@app.route('/api/config/osc-client', methods=['PUT'])
def update_osc_client():
    """Update OSC client configuration."""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Request body required'}), 400
    
    with config_lock:
        if 'host' in data:
            config['osc_client']['host'] = data['host']
        
        if 'port' in data:
            try:
                config['osc_client']['port'] = int(data['port'])
            except ValueError:
                return jsonify({'error': 'Invalid port number'}), 400
        
        # Reinitialize OSC client
        init_osc_client()
        
        save_config()
    
    return jsonify({
        'message': 'OSC client configuration updated',
        'osc_client': config['osc_client']
    })


@app.route('/api/triggers', methods=['GET'])
def get_triggers():
    """Get available triggers from the gateway."""
    triggers = get_available_triggers()
    return jsonify({'triggers': triggers})


@app.route('/api/mappings', methods=['GET'])
def get_mappings():
    """Get all trigger-to-OSC mappings."""
    return jsonify({'mappings': config['mappings']})


@app.route('/api/mappings', methods=['POST'])
def add_mapping():
    """Add a new trigger-to-OSC mapping."""
    mapping = request.get_json()
    
    # Validate required fields
    if 'trigger_name' not in mapping or not mapping['trigger_name']:
        return jsonify({'error': 'trigger_name is required'}), 400
    
    if 'osc_address' not in mapping or not mapping['osc_address']:
        return jsonify({'error': 'osc_address is required'}), 400
    
    # Ensure osc_args is a list
    if 'osc_args' not in mapping:
        mapping['osc_args'] = []
    elif not isinstance(mapping['osc_args'], list):
        return jsonify({'error': 'osc_args must be an array'}), 400
    
    # Add metadata
    mapping['enabled'] = mapping.get('enabled', True)
    mapping['created_at'] = datetime.now().isoformat()
    
    with config_lock:
        # Assign ID atomically — two concurrent POSTs would otherwise compute
        # the same max_id and produce duplicate IDs.
        if config['mappings']:
            max_id = max(m.get('id', 0) for m in config['mappings'])
            mapping['id'] = max_id + 1
        else:
            mapping['id'] = 1
        
        config['mappings'].append(mapping)
        save_config()
    
    return jsonify({
        'message': 'Mapping added successfully',
        'mapping': mapping
    }), 201


@app.route('/api/mappings/<int:mapping_id>', methods=['PUT'])
def update_mapping(mapping_id):
    """Update an existing mapping."""
    updated_mapping = request.get_json()
    
    # Validate required fields (no config access — safe outside the lock)
    if 'trigger_name' not in updated_mapping or not updated_mapping['trigger_name']:
        return jsonify({'error': 'trigger_name is required'}), 400
    
    if 'osc_address' not in updated_mapping or not updated_mapping['osc_address']:
        return jsonify({'error': 'osc_address is required'}), 400
    
    # Ensure osc_args is a list
    if 'osc_args' not in updated_mapping:
        updated_mapping['osc_args'] = []
    elif not isinstance(updated_mapping['osc_args'], list):
        return jsonify({'error': 'osc_args must be an array'}), 400
    
    with config_lock:
        # Find the mapping
        mapping_idx = next((i for i, m in enumerate(config['mappings']) if m.get('id') == mapping_id), None)
        
        if mapping_idx is None:
            return jsonify({'error': 'Mapping not found'}), 404
        
        # Preserve metadata
        updated_mapping['id'] = mapping_id
        updated_mapping['created_at'] = config['mappings'][mapping_idx].get('created_at', datetime.now().isoformat())
        updated_mapping['updated_at'] = datetime.now().isoformat()
        updated_mapping['enabled'] = updated_mapping.get('enabled', True)
        
        config['mappings'][mapping_idx] = updated_mapping
        save_config()
    
    return jsonify({
        'message': 'Mapping updated successfully',
        'mapping': updated_mapping
    })


@app.route('/api/mappings/<int:mapping_id>', methods=['DELETE'])
def delete_mapping(mapping_id):
    """Delete a mapping."""
    with config_lock:
        original_length = len(config['mappings'])
        config['mappings'] = [m for m in config['mappings'] if m.get('id') != mapping_id]
        
        if len(config['mappings']) < original_length:
            save_config()
            return jsonify({'message': 'Mapping deleted successfully'})
        else:
            return jsonify({'error': 'Mapping not found'}), 404


@app.route('/api/mappings/<int:mapping_id>/toggle', methods=['POST'])
def toggle_mapping(mapping_id):
    """Toggle a mapping enabled/disabled."""
    with config_lock:
        mapping = next((m for m in config['mappings'] if m.get('id') == mapping_id), None)
        
        if not mapping:
            return jsonify({'error': 'Mapping not found'}), 404
        
        mapping['enabled'] = not mapping.get('enabled', True)
        save_config()
    
    return jsonify({
        'message': 'Mapping toggled',
        'enabled': mapping['enabled']
    })


@app.route('/api/test-osc', methods=['POST'])
def test_osc():
    """Test sending an OSC message."""
    data = request.get_json()
    
    osc_address = data.get('osc_address')
    osc_args = data.get('osc_args', [])
    
    if not osc_address:
        return jsonify({'error': 'osc_address is required'}), 400
    
    if not isinstance(osc_args, list):
        return jsonify({'error': 'osc_args must be an array'}), 400
    
    success = send_osc_message(osc_address, osc_args)
    
    if success:
        return jsonify({'message': 'OSC message sent successfully'})
    else:
        return jsonify({'error': 'Failed to send OSC message'}), 500


@app.route('/api/modes', methods=['GET'])
def get_modes():
    """Fetch the list of modes and active mode from the mode service.

    The UI calls this to populate the mode checkboxes in the mapping modal.
    Returns whatever the mode service has; returns an empty list gracefully
    if the mode service is unreachable.
    """
    try:
        url = config.get('mode_service_url', MODE_SERVICE_URL)
        r = requests.get(f"{url}/api/modes", timeout=4)
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception as e:
        print(f"[mode] get_modes proxy error: {e}")

    # Fallback: return cached active mode + empty list
    return jsonify({'modes': [], 'active_mode': get_current_mode()})


@app.route('/api/aliases', methods=['GET'])
def get_aliases():
    """Return all OSC address aliases."""
    return jsonify({'aliases': config.get('osc_aliases', [])})


@app.route('/api/aliases', methods=['POST'])
def add_alias():
    """Add a new OSC alias."""
    data = request.get_json()
    if not data or not data.get('alias', '').strip():
        return jsonify({'error': 'alias (human-readable name) is required'}), 400
    if not data.get('osc_address', '').strip():
        return jsonify({'error': 'osc_address is required'}), 400
    if 'osc_args' in data and not isinstance(data['osc_args'], list):
        return jsonify({'error': 'osc_args must be an array'}), 400

    with config_lock:
        aliases = config.setdefault('osc_aliases', [])
        max_id = max((a.get('id', 0) for a in aliases), default=0)
        entry = {
            'id': max_id + 1,
            'alias': data['alias'].strip(),
            'osc_address': data['osc_address'].strip(),
            'osc_args': data.get('osc_args', []),
            'description': data.get('description', '').strip()
        }
        aliases.append(entry)
        save_config()

    return jsonify({'message': 'Alias added', 'alias': entry}), 201


@app.route('/api/aliases/<int:alias_id>', methods=['PUT'])
def update_alias(alias_id):
    """Update an existing OSC alias."""
    data = request.get_json()
    if not data or not data.get('alias', '').strip():
        return jsonify({'error': 'alias (human-readable name) is required'}), 400
    if not data.get('osc_address', '').strip():
        return jsonify({'error': 'osc_address is required'}), 400
    if 'osc_args' in data and not isinstance(data['osc_args'], list):
        return jsonify({'error': 'osc_args must be an array'}), 400

    with config_lock:
        aliases = config.setdefault('osc_aliases', [])
        idx = next((i for i, a in enumerate(aliases) if a.get('id') == alias_id), None)
        if idx is None:
            return jsonify({'error': 'Alias not found'}), 404
        aliases[idx].update({
            'alias': data['alias'].strip(),
            'osc_address': data['osc_address'].strip(),
            'osc_args': data.get('osc_args', []),
            'description': data.get('description', '').strip()
        })
        save_config()

    return jsonify({'message': 'Alias updated', 'alias': aliases[idx]})


@app.route('/api/aliases/<int:alias_id>', methods=['DELETE'])
def delete_alias(alias_id):
    """Delete an OSC alias."""
    with config_lock:
        aliases = config.setdefault('osc_aliases', [])
        orig_len = len(aliases)
        config['osc_aliases'] = [a for a in aliases if a.get('id') != alias_id]
        if len(config['osc_aliases']) < orig_len:
            save_config()
            return jsonify({'message': 'Alias deleted'})
        return jsonify({'error': 'Alias not found'}), 404


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get server status."""
    return jsonify({
        'service_name': SERVICE_NAME,
        'socket_server_running': server_running,
        'socket_server_port': config['service_port'],
        'osc_client_initialized': osc_client_instance is not None,
        'osc_client_config': config['osc_client'],
        'gateway_url': config['gateway_url'],
        'active_mode': get_current_mode(),
        'mappings_count': len(config['mappings'])
    })


def cleanup():
    """Cleanup on shutdown."""
    print("\nShutting down...")
    stop_socket_server()
    unregister_from_gateway()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Haven OSC Proxy Server')
    parser.add_argument('--port', type=int, default=5004,
                        help='Port for web interface (default: 5004)')
    parser.add_argument('--service-port', type=int, default=5100,
                        help='Port for trigger socket server (default: 5100)')
    parser.add_argument('--gateway', type=str, default='http://localhost:5002',
                        help='Trigger Gateway URL (default: http://localhost:5002)')
    args = parser.parse_args()
    
    # Update config with command line arguments
    config['service_port'] = args.service_port
    config['gateway_url'] = args.gateway
    
    print("Haven OSC Proxy Server starting...")
    print(f"Configuration file: {CONFIG_FILE}")
    
    # Load configuration
    load_config()
    
    # Start mode-service polling thread
    mode_thread = threading.Thread(target=_poll_mode_service, daemon=True, name='mode-poller')
    mode_thread.start()
    print(f"Mode service polling: {config.get('mode_service_url', MODE_SERVICE_URL)}")

    # Start socket server
    start_socket_server()
    
    # Register with gateway (with retry)
    max_retries = 3
    for attempt in range(max_retries):
        if register_with_gateway():
            break
        else:
            print(f"Registration attempt {attempt + 1}/{max_retries} failed")
            if attempt < max_retries - 1:
                time.sleep(2)
    
    print(f"Web interface: http://localhost:{args.port}")
    print(f"Socket server: localhost:{config['service_port']}")
    print(f"OSC client: {config['osc_client']['host']}:{config['osc_client']['port']}")
    
    try:
        app.run(host='0.0.0.0', port=args.port, debug=False)
    finally:
        # Single cleanup path — covers both Ctrl-C (KeyboardInterrupt) and
        # SIGTERM from systemd (raises SystemExit).  A separate
        # except-KeyboardInterrupt block would cause a double-cleanup.
        cleanup()
