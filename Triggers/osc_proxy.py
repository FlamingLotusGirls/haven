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
SCENE_SERVICE_URL = 'http://localhost:5003'
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
    'scene_service_url': SCENE_SERVICE_URL,
    'service_port': 5100,
    # Per-scene configuration.  Each key is a scene name; value has:
    #   on_enter  – OSC sequence steps to fire when this scene becomes active
    #   description – human-readable note
    # 'Unknown' is the built-in fallback used when the scene service is unreachable.
    'scenes': {
        'Unknown': {
            'on_enter': [],
            'description': 'Fallback scene — active when scene service is unreachable'
        }
    }
}

# ── Scene tracking ──────────────────────────────────────────────────────────
# Cached active scene, updated by the scene-poll thread and by scene_change triggers.
# Starts as 'Unknown' — the local fallback used when scene service is unreachable.
_active_scene = 'Unknown'
_active_scene_lock = threading.Lock()


def get_current_scene():
    """Return the cached active scene name ('Unknown' if unreachable)."""
    with _active_scene_lock:
        return _active_scene


def _set_active_scene(name, fire_on_enter=True):
    """Update the cached active scene; fire on_enter sequence if it changed.

    Returns True if the scene actually changed.
    Thread-safe — may be called from both the poll thread and the trigger thread.
    """
    global _active_scene
    with _active_scene_lock:
        old = _active_scene
        changed = (name != old)
        if changed:
            print(f"[scene] active scene: '{old}' → '{name}'")
            _active_scene = name
    if fire_on_enter and changed:
        threading.Thread(target=_apply_scene_on_enter, args=(name,),
                         daemon=True, name=f'scene-enter-{name}').start()
    return changed


def _apply_scene_on_enter(scene_name):
    """Fire the on_enter OSC sequence for the given scene (if any steps are configured)."""
    with config_lock:
        scenes = config.get('scenes', {})
        scene_cfg = scenes.get(scene_name) or scenes.get('Unknown', {})
        steps = scene_cfg.get('on_enter', [])
    if not steps:
        print(f"[scene] No on_enter sequence configured for scene '{scene_name}'")
        return
    print(f"[scene] Firing on_enter for scene '{scene_name}' ({len(steps)} steps)")
    _run_sequence(f'__scene_enter_{scene_name}', steps, scene_name)


def _poll_scene_service():
    """Background thread: poll scene service every 1 s until known, then every 10 s.

    Falls back to the 'Unknown' scene whenever the scene service is unreachable.
    """
    scene_known = False
    while True:
        try:
            url = config.get('scene_service_url', SCENE_SERVICE_URL)
            r = requests.get(f"{url}/api/scenes/active", timeout=4)
            if r.status_code == 200:
                new_scene = r.json().get('active_scene') or 'Unknown'
                _set_active_scene(new_scene)
                scene_known = True
            else:
                scene_known = False
        except Exception as e:
            print(f"[scene] could not reach scene service: {e}")
            scene_known = False
        time.sleep(10 if scene_known else 1)

# Track active sequences per trigger_name.
# Value is the count of mapping-sequence threads currently running for that trigger.
# While count > 0, new triggers of the same name are suppressed.
_active_sequences = {}
_active_sequences_lock = threading.Lock()

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
    # Snapshot the reference once.  init_osc_client() (called under config_lock)
    # can replace osc_client_instance at any time; using a local avoids a
    # check-then-use race where the global becomes None between the guard and the call.
    client = osc_client_instance
    if not client:
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
            client.send_message(osc_address, parsed_args)
        else:
            client.send_message(osc_address, None)
        
        print(f"Sent OSC: {osc_address} {parsed_args}")
        return True
    except Exception as e:
        print(f"Error sending OSC message: {e}")
        return False


def get_mapping_steps(mapping):
    """Return the sequence steps for a mapping.

    Supports both the new ``sequence`` format and the legacy single-command
    ``osc_address`` / ``osc_args`` format so old config files keep working.
    """
    if mapping.get('sequence'):
        return mapping['sequence']
    addr = mapping.get('osc_address', '').strip()
    if addr:
        return [{'delay_ms': 0, 'osc_address': addr, 'osc_args': mapping.get('osc_args', [])}]
    return []


def _run_sequence(trigger_name, steps, trigger_value):
    """Execute one mapping's sequence in a background daemon thread.

    Sleeps *delay_ms* milliseconds before each step, then sends the OSC
    message.  Decrements the active-sequence counter when done.
    """
    try:
        for step in steps:
            delay_ms = step.get('delay_ms', 0)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            osc_address = step.get('osc_address', '').strip()
            osc_args = step.get('osc_args', [])
            if osc_address:
                send_osc_message(osc_address, osc_args, trigger_value)
    except Exception as e:
        print(f"Error in sequence for '{trigger_name}': {e}")
    finally:
        with _active_sequences_lock:
            count = _active_sequences.get(trigger_name, 1) - 1
            if count <= 0:
                _active_sequences.pop(trigger_name, None)
            else:
                _active_sequences[trigger_name] = count
        print(f"Sequence for '{trigger_name}' finished")


def process_trigger_event(trigger_event):
    """Process a trigger event and fire the associated OSC sequence(s)."""
    trigger_name = trigger_event.get('name')
    trigger_value = trigger_event.get('value')

    print(f"Processing trigger event: {trigger_name} = {trigger_value}")

    # ── Scene change: update active scene and fire on_enter ──────────────────
    if trigger_name == 'SceneChange':
        new_scene = str(trigger_value) if trigger_value is not None else 'Unknown'
        _set_active_scene(new_scene, fire_on_enter=True)
        return   # scene_change is not a normal trigger mapping
    # ─────────────────────────────────────────────────────────────────────────

    # ── Busy-check ────────────────────────────────────────────────────────────
    # If any sequence for this trigger is still running, suppress the new event.
    with _active_sequences_lock:
        if _active_sequences.get(trigger_name, 0) > 0:
            print(f"Sequence for '{trigger_name}' still playing — ignoring new trigger")
            return
    # ──────────────────────────────────────────────────────────────────────────

    active_scene = get_current_scene()

    with config_lock:
        current_mappings = list(config['mappings'])

    # Collect all matching, enabled, scene-allowed mappings with their resolved steps
    to_fire = []
    for mapping in current_mappings:
        if mapping.get('trigger_name') != trigger_name:
            continue
        if not mapping.get('enabled', True):
            continue

        # ── Scene gate ────────────────────────────────────────────────────────
        # mapping['scene'] is the scene this mapping belongs to.
        # Empty string means "fire in every scene".
        mapping_scene = mapping.get('scene', '') or ''
        if mapping_scene and mapping_scene != active_scene:
            print(f"[scene] skipping mapping {mapping.get('id')} "
                  f"(active='{active_scene}', mapping_scene='{mapping_scene}')")
            continue
        # ──────────────────────────────────────────────────────────────────────

        steps = get_mapping_steps(mapping)
        if steps:
            to_fire.append(steps)

    if not to_fire:
        print(f"No OSC mapping found for trigger: {trigger_name}")
        return

    # Register all threads as active before starting any, so a near-instant
    # completion of the first thread does not clear the guard prematurely.
    with _active_sequences_lock:
        _active_sequences[trigger_name] = len(to_fire)

    for steps in to_fire:
        t = threading.Thread(
            target=_run_sequence,
            args=(trigger_name, steps, trigger_value),
            daemon=True
        )
        t.start()


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
    # Serialise under config_lock so concurrent write operations (append,
    # in-place update) cannot produce a torn JSON view.
    with config_lock:
        snapshot = json.dumps(config)
    return app.response_class(snapshot, mimetype='application/json')


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
    """Get all trigger-to-OSC mappings.

    Optional query param: ?scene=<name>  — return only mappings for that scene.
    """
    scene_filter = request.args.get('scene', '').strip()
    with config_lock:
        mappings = list(config['mappings'])   # shallow copy keeps list stable
    if scene_filter:
        mappings = [m for m in mappings if m.get('scene', '') == scene_filter]
    return jsonify({'mappings': mappings})


@app.route('/api/mappings', methods=['POST'])
def add_mapping():
    """Add a new trigger-to-OSC mapping.

    Required body fields: trigger_name, scene (single scene name or '' for all scenes),
    and either osc_address or sequence.
    """
    mapping = request.get_json()

    # Validate required fields
    if 'trigger_name' not in mapping or not mapping['trigger_name']:
        return jsonify({'error': 'trigger_name is required'}), 400

    # Accept either new 'sequence' format or legacy 'osc_address' format
    has_address  = bool(mapping.get('osc_address', '').strip())
    has_sequence = bool(mapping.get('sequence') and isinstance(mapping['sequence'], list))
    if not has_address and not has_sequence:
        return jsonify({'error': 'Either osc_address or sequence is required'}), 400

    # Legacy normalisation
    if has_address and 'osc_args' not in mapping:
        mapping['osc_args'] = []
    if has_address and not isinstance(mapping.get('osc_args'), list):
        return jsonify({'error': 'osc_args must be an array'}), 400

    # scene: which scene this mapping belongs to ('' = fire in every scene)
    mapping.setdefault('scene', '')

    # Add metadata
    mapping['enabled'] = mapping.get('enabled', True)
    mapping['created_at'] = datetime.now().isoformat()

    # Auto-register the scene entry if it doesn't exist yet
    scene = mapping.get('scene', '')
    if scene:
        with config_lock:
            scenes = config.setdefault('scenes', {})
            if scene not in scenes:
                scenes[scene] = {'on_enter': [], 'description': ''}
    
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

    has_address  = bool(updated_mapping.get('osc_address', '').strip())
    has_sequence = bool(updated_mapping.get('sequence') and isinstance(updated_mapping['sequence'], list))
    if not has_address and not has_sequence:
        return jsonify({'error': 'Either osc_address or sequence is required'}), 400

    if has_address and 'osc_args' not in updated_mapping:
        updated_mapping['osc_args'] = []
    if has_address and not isinstance(updated_mapping.get('osc_args'), list):
        return jsonify({'error': 'osc_args must be an array'}), 400

    # scene: which scene this mapping belongs to ('' = fire in every scene)
    updated_mapping.setdefault('scene', '')
    
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


@app.route('/api/available-scenes', methods=['GET'])
def available_scenes():
    """Fetch the list of scenes and active scene from the scene service.

    Returns whatever the scene service has; returns an empty list gracefully
    if the scene service is unreachable.
    """
    try:
        url = config.get('scene_service_url', SCENE_SERVICE_URL)
        r = requests.get(f"{url}/api/scenes", timeout=4)
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception as e:
        print(f"[scene] available_scenes proxy error: {e}")

    # Fallback: return cached active scene + empty list
    return jsonify({'scenes': [], 'active_scene': get_current_scene()})


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


@app.route('/api/active-sequences', methods=['GET'])
def get_active_sequences():
    """Return the names of triggers whose sequences are currently playing."""
    with _active_sequences_lock:
        active = list(_active_sequences.keys())
    return jsonify({'active_sequences': active})


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get server status."""
    with _active_sequences_lock:
        active_seq_count = sum(_active_sequences.values())
    # Read all config fields atomically so a concurrent update_osc_client /
    # add_mapping cannot produce an inconsistent status snapshot.
    with config_lock:
        service_port    = config['service_port']
        osc_client_cfg  = dict(config['osc_client'])
        gateway_url     = config['gateway_url']
        mappings_count  = len(config['mappings'])
        client_ready    = osc_client_instance is not None
    return jsonify({
        'service_name': SERVICE_NAME,
        'socket_server_running': server_running,
        'socket_server_port': service_port,
        'osc_client_initialized': client_ready,
        'osc_client_config': osc_client_cfg,
        'gateway_url': gateway_url,
        'active_scene': get_current_scene(),
        'mappings_count': mappings_count,
        'active_sequences': active_seq_count
    })


@app.route('/api/refresh-scene', methods=['POST'])
def refresh_scene():
    """Force an immediate re-poll of the scene service and update the active scene."""
    try:
        url = config.get('scene_service_url', SCENE_SERVICE_URL)
        r = requests.get(f"{url}/api/scenes/active", timeout=4)
        if r.status_code == 200:
            new_scene = r.json().get('active_scene') or 'Unknown'
            changed = _set_active_scene(new_scene)
            return jsonify({'active_scene': new_scene, 'changed': changed}), 200
        else:
            return jsonify({'error': f'Scene service returned {r.status_code}',
                            'active_scene': get_current_scene()}), 502
    except Exception as e:
        return jsonify({'error': str(e), 'active_scene': get_current_scene()}), 503


# ── Scene configuration API ─────────────────────────────────────────────────

@app.route('/api/scenes', methods=['GET'])
def get_scenes():
    """Return all per-scene configurations plus the currently active scene."""
    with config_lock:
        scenes = dict(config.get('scenes', {}))
    return jsonify({'scenes': scenes, 'active_scene': get_current_scene()}), 200


@app.route('/api/scenes/<scene_name>/on_enter', methods=['PUT'])
def set_scene_on_enter(scene_name):
    """Set or replace the on_enter OSC sequence for a scene.

    Body: { "on_enter": [ {"delay_ms": 0, "osc_address": "/foo", "osc_args": [1]}, ... ],
            "description": "optional note" }
    Creates the scene entry if it doesn't already exist.
    """
    data = request.get_json()
    if not data or 'on_enter' not in data:
        return jsonify({'error': 'on_enter array is required'}), 400
    if not isinstance(data['on_enter'], list):
        return jsonify({'error': 'on_enter must be an array of step objects'}), 400

    with config_lock:
        scenes = config.setdefault('scenes', {})
        if scene_name not in scenes:
            scenes[scene_name] = {}
        scenes[scene_name]['on_enter'] = data['on_enter']
        if 'description' in data:
            scenes[scene_name]['description'] = data['description']
        save_config()

    return jsonify({'message': f'on_enter for scene "{scene_name}" saved',
                    'scene': scene_name,
                    'on_enter': data['on_enter']}), 200


@app.route('/api/scenes/<scene_name>/copy', methods=['POST'])
def copy_scene(scene_name):
    """POST /api/scenes/<scene_name>/copy  body: {"new_name": "..."}

    Deep-copy the source scene's on_enter config to a new scene name.
    Returns 404 if the source scene doesn't exist, 409 if new_name already exists.
    """
    import copy as _copy
    data = request.get_json(silent=True) or {}
    new_name = (data.get('new_name') or '').strip()
    if not new_name:
        return jsonify({'error': 'new_name is required'}), 400
    with config_lock:
        scenes = config.setdefault('scenes', {})
        if scene_name not in scenes:
            return jsonify({'error': f"Scene '{scene_name}' not found"}), 404
        if new_name in scenes:
            return jsonify({'error': f"Scene '{new_name}' already exists"}), 409
        scenes[new_name] = _copy.deepcopy(scenes[scene_name])
        # Clear the description so the copy is clearly a new scene
        scenes[new_name].pop('description', None)
        save_config()
    print(f"[scene] Copied scene config: '{scene_name}' → '{new_name}'")
    return jsonify({'scene': new_name, 'copied_from': scene_name,
                    'config': scenes[new_name]}), 201


@app.route('/api/scenes', methods=['POST'])
def register_scene():
    """Register a new scene with an empty configuration.

    Body: { "scene_name": "...", "description": "..." (optional) }
    Creates a scene entry even if no trigger mappings exist yet.
    Returns 409 if the scene already exists.
    """
    data = request.get_json(silent=True) or {}
    scene_name = (data.get('scene_name') or '').strip()
    if not scene_name:
        return jsonify({'error': 'scene_name is required'}), 400
    with config_lock:
        scenes = config.setdefault('scenes', {})
        if scene_name in scenes:
            return jsonify({'message': f"Scene '{scene_name}' already registered",
                            'scene': scene_name}), 200
        scenes[scene_name] = {
            'on_enter': [],
            'description': data.get('description', '').strip()
        }
        save_config()
    print(f"[scene] Registered new scene: '{scene_name}'")
    return jsonify({'message': f"Scene '{scene_name}' registered",
                    'scene': scene_name}), 201


@app.route('/api/scenes/sync', methods=['GET'])
def scenes_sync():
    """Return sync information between the scene service and locally configured scenes.

    Response JSON:
      { "configured_scenes": [...],      -- scenes in osc_proxy_config.json
        "scene_service_scenes": [...],   -- scenes from the scene service ([] on error)
        "active_scene": "..."            -- currently active scene
      }
    """
    with config_lock:
        configured = sorted(config.get('scenes', {}).keys())

    scene_service_scenes = []
    try:
        url = config.get('scene_service_url', SCENE_SERVICE_URL)
        r = requests.get(f"{url}/api/scenes", timeout=4)
        if r.status_code == 200:
            scene_service_scenes = r.json().get('scenes', [])
    except Exception as e:
        print(f"[scene-sync] could not reach scene service: {e}")

    return jsonify({
        'configured_scenes': configured,
        'scene_service_scenes': scene_service_scenes,
        'active_scene': get_current_scene(),
    }), 200


@app.route('/api/scenes/<scene_name>', methods=['DELETE'])
def delete_scene(scene_name):
    """Delete a scene's configuration AND all trigger mappings that belong to it.

    The 'Unknown' scene cannot be deleted — it is the built-in fallback.
    """
    if scene_name == 'Unknown':
        return jsonify({'error': "'Unknown' is the built-in fallback scene and cannot be deleted"}), 400
    with config_lock:
        scenes = config.get('scenes', {})
        if scene_name not in scenes:
            return jsonify({'error': f"Scene '{scene_name}' not found"}), 404
        del scenes[scene_name]
        # Also remove all trigger mappings that belong to this scene.
        before = len(config['mappings'])
        config['mappings'] = [m for m in config['mappings']
                              if m.get('scene', '') != scene_name]
        removed = before - len(config['mappings'])
        save_config()
    print(f"[scene] Deleted scene '{scene_name}' + {removed} mapping(s)")
    return jsonify({'message': f"Scene '{scene_name}' deleted",
                    'mappings_removed': removed}), 200


# ── End scene API ────────────────────────────────────────────────────────────


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
    
    # Start scene-service polling thread
    scene_thread = threading.Thread(target=_poll_scene_service, daemon=True, name='scene-poller')
    scene_thread.start()
    print(f"Scene service polling: {config.get('scene_service_url', SCENE_SERVICE_URL)}")

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
