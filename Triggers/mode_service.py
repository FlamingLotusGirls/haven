#!/usr/bin/env python3
"""
Mode Management Service

A simple REST API service that manages modes. Only one mode can be active at a time.
Modes are persisted to a JSON file between reboots.

Endpoints:
  POST   /api/modes              - Create a new mode
  DELETE /api/modes/<name>       - Delete a mode (current mode cannot be deleted)
  GET    /api/modes              - Get list of all modes + active mode
  POST   /api/modes/active       - Set the active mode
  GET    /api/modes/active       - Get the active mode

  GET    /api/schedules          - List all mode-activation schedules
  POST   /api/schedules          - Create a schedule  { mode, time:"HH:MM", repeat:"daily"|"once" }
  DELETE /api/schedules/<id>     - Delete a schedule

  GET    /                       - Mode management web UI
"""

from flask import Flask, request, jsonify, send_from_directory
import json
import os
import uuid
import tempfile
import threading
import logging
import argparse
import requests
from datetime import datetime, date

app = Flask(__name__, static_folder='.', static_url_path='')

# Configuration
MODES_FILE = 'modes.json'
DEFAULT_PORT = 5003

# Trigger gateway integration — the mode service acts as a trigger device and fires
# a 'SceneChange' Discrete trigger whenever the active scene changes.
GATEWAY_URL = os.environ.get('GATEWAY_URL', 'http://localhost:5002')
SCENE_TRIGGER_NAME = 'SceneChange'
DEVICE_NAME        = 'ModeService'

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class ModeManager:
    """Manages modes and scheduled activations with persistence."""

    def __init__(self, filename=MODES_FILE):
        self.filename = filename
        self.modes = set()
        self.active_mode = None
        self.schedules = []          # list of schedule dicts
        # Protects all check+modify+save sequences against concurrent Flask threads.
        self._lock = threading.Lock()
        self.load_modes()
        self._start_scheduler()
        # Best-effort: register this service as a device in the gateway at startup.
        threading.Thread(target=self._register_with_gateway,
                         daemon=True, name='scene-trigger-init').start()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_modes(self):
        """Load modes (and schedules) from JSON file."""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    self.modes = set(data.get('modes', []))
                    self.active_mode = data.get('active_mode')
                    self.schedules = data.get('schedules', [])
                    logger.info(f"Loaded {len(self.modes)} modes, "
                                f"{len(self.schedules)} schedules from {self.filename}")
                    if self.active_mode:
                        logger.info(f"Active mode: {self.active_mode}")
            except Exception as e:
                logger.error(f"Error loading modes: {e}")
                self.modes = set()
                self.active_mode = None
                self.schedules = []
        else:
            logger.info("No existing modes file found, starting fresh")
            self.save_modes()

    def save_modes(self):
        """Save modes and schedules to JSON file atomically.

        Writes to a temp file in the same directory then os.replace()-swaps it
        in, so a crash mid-write never leaves modes.json in a corrupt/empty state.
        Must be called with self._lock already held (or from __init__ before any
        threads exist).
        """
        tmpname = None
        try:
            data = {
                'modes': list(self.modes),
                'active_mode': self.active_mode,
                'schedules': self.schedules,
                'last_updated': datetime.now().isoformat()
            }
            save_dir = os.path.dirname(os.path.abspath(self.filename)) or '.'
            with tempfile.NamedTemporaryFile('w', dir=save_dir, suffix='.tmp', delete=False) as f:
                tmpname = f.name
                json.dump(data, f, indent=2)
            os.replace(tmpname, self.filename)
            logger.info(f"Saved {len(self.modes)} modes to {self.filename}")
        except Exception as e:
            logger.error(f"Error saving modes: {e}")
            if tmpname:
                try:
                    os.unlink(tmpname)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Mode CRUD
    # ------------------------------------------------------------------

    def create_mode(self, name):
        """Create a new mode."""
        if not name or not isinstance(name, str):
            return False, "Mode name must be a non-empty string"

        name = name.strip()
        if not name:
            return False, "Mode name cannot be empty"

        with self._lock:
            if name in self.modes:
                return False, f"Mode '{name}' already exists"

            self.modes.add(name)
            self.save_modes()

        logger.info(f"Created mode: {name}")
        # Re-register with the gateway so the SceneChange trigger range includes the new mode.
        threading.Thread(target=self._register_with_gateway,
                         daemon=True, name='scene-trigger-update').start()
        return True, f"Mode '{name}' created"

    def delete_mode(self, name):
        """Delete a mode.  The currently active mode cannot be deleted."""
        with self._lock:
            if name not in self.modes:
                return False, f"Mode '{name}' does not exist"

            if self.active_mode == name:
                return False, f"Cannot delete the currently active mode '{name}'"

            self.modes.discard(name)

            # Remove any schedules that reference this mode
            self.schedules = [s for s in self.schedules if s.get('mode') != name]

            self.save_modes()

        logger.info(f"Deleted mode: {name}")
        # Re-register with the gateway so the SceneChange trigger range drops the deleted mode.
        threading.Thread(target=self._register_with_gateway,
                         daemon=True, name='scene-trigger-update').start()
        return True, f"Mode '{name}' deleted"

    def get_modes(self):
        """Get sorted list of all modes."""
        # Must hold the lock: list(set) iterates the set, and a concurrent
        # create_mode/delete_mode can mutate it mid-iteration, raising
        # RuntimeError: Set changed size during iteration.
        with self._lock:
            return sorted(self.modes)

    def set_active_mode(self, name):
        """Set the active mode (None clears it)."""
        with self._lock:
            if name is None:
                self.active_mode = None
                self.save_modes()
                logger.info("Cleared active mode")
                return True, "Active mode cleared"

            if name not in self.modes:
                return False, f"Mode '{name}' does not exist"

            self.active_mode = name
            self.save_modes()

        logger.info(f"Set active mode: {name}")
        # Push scene_change trigger to gateway so all services update immediately.
        threading.Thread(target=self._push_scene_trigger, args=(name,),
                         daemon=True, name='scene-push').start()
        return True, f"Active mode set to '{name}'"

    # ------------------------------------------------------------------
    # Scene trigger dispatch
    # ------------------------------------------------------------------

    def _push_scene_trigger(self, scene_name):
        """POST a SceneChange trigger event to the trigger gateway (non-blocking)."""
        url = f"{GATEWAY_URL}/api/trigger-event"
        payload = {'name': SCENE_TRIGGER_NAME, 'value': scene_name}
        try:
            resp = requests.post(url, json=payload, timeout=3)
            if resp.status_code == 200:
                logger.info(f"SceneChange trigger dispatched → gateway (scene={scene_name})")
            else:
                logger.warning(f"Gateway returned {resp.status_code} for SceneChange: {resp.text}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not reach trigger gateway for SceneChange: {e}")

    def _register_with_gateway(self):
        """Register this service as a device in the trigger gateway.

        Uses POST /api/register-device so the gateway tracks ModeService as an
        online/offline device and keeps the SceneChange trigger's discrete value
        list in sync with the current set of modes.

        Called at startup and after every create_mode / delete_mode.
        """
        # get_modes() acquires self._lock briefly — must be called OUTSIDE any
        # existing lock to avoid a deadlock.
        modes = self.get_modes()
        url = f"{GATEWAY_URL}/api/register-device"
        payload = {
            'name': DEVICE_NAME,
            'ip': 'localhost',
            'triggers': [{
                'name': SCENE_TRIGGER_NAME,
                'type': 'Discrete',
                'range': {'values': modes},
                'description': 'Active scene broadcast by mode_service on every mode change',
            }],
        }
        try:
            resp = requests.post(url, json=payload, timeout=3)
            if resp.ok:
                logger.info(
                    f"Registered '{SCENE_TRIGGER_NAME}' trigger with gateway "
                    f"(device='{DEVICE_NAME}', modes={modes})"
                )
            else:
                logger.warning(
                    f"Gateway device registration failed: {resp.status_code} {resp.text}"
                )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not reach trigger gateway for device registration: {e}")

    def get_active_mode(self):
        """Get the active mode."""
        with self._lock:
            return self.active_mode

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    def create_schedule(self, mode, time_str, repeat):
        """Create a scheduled mode activation.

        mode     - mode name (must exist)
        time_str - "HH:MM" (24-hour local time)
        repeat   - "daily" | "once"

        Returns (True, schedule_dict) or (False, error_message).
        """
        if mode not in self.modes:
            return False, f"Mode '{mode}' does not exist"

        # Validate time
        try:
            hour, minute = map(int, time_str.strip().split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
            time_str = f"{hour:02d}:{minute:02d}"
        except Exception:
            return False, "time must be in HH:MM format (24-hour)"

        if repeat not in ('daily', 'once'):
            return False, "repeat must be 'daily' or 'once'"

        schedule = {
            'id': str(uuid.uuid4()),
            'mode': mode,
            'time': time_str,
            'repeat': repeat,
            'created': datetime.now().isoformat(),
            'last_fired': None,
        }

        with self._lock:
            self.schedules.append(schedule)
            self.save_modes()

        logger.info(f"Created schedule {schedule['id']}: {mode} @ {time_str} ({repeat})")
        return True, schedule

    def update_schedule(self, schedule_id, mode, time_str, repeat):
        """Update an existing schedule in place.

        Returns (True, updated_dict) or (False, error_message).
        """
        if mode not in self.modes:
            return False, f"Mode '{mode}' does not exist"

        try:
            hour, minute = map(int, time_str.strip().split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
            time_str = f"{hour:02d}:{minute:02d}"
        except Exception:
            return False, "time must be in HH:MM format (24-hour)"

        if repeat not in ('daily', 'once'):
            return False, "repeat must be 'daily' or 'once'"

        with self._lock:
            for s in self.schedules:
                if s['id'] == schedule_id:
                    s['mode'] = mode
                    s['time'] = time_str
                    s['repeat'] = repeat
                    s['last_fired'] = None   # reset so it can fire at new time
                    self.save_modes()
                    logger.info(f"Updated schedule {schedule_id}: {mode} @ {time_str} ({repeat})")
                    return True, dict(s)
            return False, f"Schedule '{schedule_id}' not found"

    def delete_schedule(self, schedule_id):
        """Remove a schedule by id."""
        with self._lock:
            before = len(self.schedules)
            self.schedules = [s for s in self.schedules if s['id'] != schedule_id]
            if len(self.schedules) == before:
                return False, f"Schedule '{schedule_id}' not found"
            self.save_modes()

        logger.info(f"Deleted schedule {schedule_id}")
        return True, f"Schedule '{schedule_id}' deleted"

    def get_schedules(self):
        """Return a copy of all schedules."""
        with self._lock:
            return list(self.schedules)

    # ------------------------------------------------------------------
    # Background scheduler
    # ------------------------------------------------------------------

    def _start_scheduler(self):
        """Start the background thread that fires scheduled modes."""
        t = threading.Thread(target=self._scheduler_loop, daemon=True, name='mode-scheduler')
        t.start()
        logger.info("Mode scheduler started")

    def _scheduler_loop(self):
        """Check schedules every 30 seconds; fire any whose HH:MM matches now."""
        import time
        while True:
            self._check_schedules()
            time.sleep(30)

    def _check_schedules(self):
        now_str = datetime.now().strftime('%H:%M')
        today_str = date.today().isoformat()
        fired_ids = []

        fired_mode = None

        with self._lock:
            for schedule in self.schedules:
                if schedule['time'] != now_str:
                    continue

                # Avoid firing twice in the same minute
                last_fired = schedule.get('last_fired') or ''
                if last_fired.startswith(today_str):
                    continue

                # Fire
                mode = schedule['mode']
                if mode in self.modes:
                    self.active_mode = mode
                    fired_mode = mode   # track for trigger push (works for daily AND once)
                    schedule['last_fired'] = datetime.now().isoformat()
                    logger.info(f"Scheduler: activated mode '{mode}' (schedule {schedule['id']})")
                else:
                    logger.warning(f"Scheduler: mode '{mode}' no longer exists, skipping")

                if schedule['repeat'] == 'once':
                    fired_ids.append(schedule['id'])

            # Remove one-shot schedules that fired
            if fired_ids:
                self.schedules = [s for s in self.schedules if s['id'] not in fired_ids]

            if self.active_mode or fired_ids:
                self.save_modes()

        # Push scene_change trigger for scheduler-activated modes (outside the lock).
        if fired_mode:
            threading.Thread(target=self._push_scene_trigger, args=(fired_mode,),
                             daemon=True, name='scene-push-sched').start()


# ---------------------------------------------------------------------------
# Initialise the manager
# ---------------------------------------------------------------------------
mode_manager = ModeManager()


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Serve the mode management web UI."""
    return send_from_directory('.', 'mode_service.html')


# ---------------------------------------------------------------------------
# Mode API
# ---------------------------------------------------------------------------

@app.route('/api/modes', methods=['POST'])
def create_mode():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Missing required field: name'}), 400

    success, message = mode_manager.create_mode(data['name'])
    if success:
        return jsonify({'message': message, 'mode': data['name']}), 201
    return jsonify({'error': message}), 400


@app.route('/api/modes/<name>', methods=['DELETE'])
def delete_mode(name):
    success, message = mode_manager.delete_mode(name)
    if success:
        return jsonify({'message': message}), 200
    # 400 if it's the active mode, 404 if not found
    code = 400 if 'active' in message else 404
    return jsonify({'error': message}), code


@app.route('/api/modes', methods=['GET'])
def get_modes():
    modes = mode_manager.get_modes()
    active = mode_manager.get_active_mode()
    return jsonify({'modes': modes, 'active_mode': active, 'count': len(modes)}), 200


@app.route('/api/modes/active', methods=['POST'])
def set_active_mode():
    data = request.get_json()
    mode_name = data.get('name') if data else None
    success, message = mode_manager.set_active_mode(mode_name)
    if success:
        return jsonify({'message': message, 'active_mode': mode_name}), 200
    return jsonify({'error': message}), 400


@app.route('/api/modes/active', methods=['GET'])
def get_active_mode():
    return jsonify({'active_mode': mode_manager.get_active_mode()}), 200


# ---------------------------------------------------------------------------
# Schedule API
# ---------------------------------------------------------------------------

@app.route('/api/schedules', methods=['GET'])
def get_schedules():
    return jsonify({'schedules': mode_manager.get_schedules()}), 200


@app.route('/api/schedules', methods=['POST'])
def create_schedule():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    for field in ('mode', 'time', 'repeat'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    success, result = mode_manager.create_schedule(
        data['mode'], data['time'], data['repeat'])
    if success:
        return jsonify({'message': 'Schedule created', 'schedule': result}), 201
    return jsonify({'error': result}), 400


@app.route('/api/schedules/<schedule_id>', methods=['PUT'])
def update_schedule(schedule_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400
    for field in ('mode', 'time', 'repeat'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    success, result = mode_manager.update_schedule(
        schedule_id, data['mode'], data['time'], data['repeat'])
    if success:
        return jsonify({'message': 'Schedule updated', 'schedule': result}), 200
    code = 404 if 'not found' in result else 400
    return jsonify({'error': result}), code


@app.route('/api/schedules/<schedule_id>', methods=['DELETE'])
def delete_schedule(schedule_id):
    success, message = mode_manager.delete_schedule(schedule_id)
    if success:
        return jsonify({'message': message}), 200
    return jsonify({'error': message}), 404


# ---------------------------------------------------------------------------
# Scene Status  (aggregates config from flame service + OSC proxy)
# ---------------------------------------------------------------------------

# Service URLs — override with env vars when the services run on different hosts.
_FLAME_URL   = os.environ.get('FLAME_SERVICE_URL', 'http://localhost:5001')
_OSC_URL     = os.environ.get('OSC_PROXY_URL',     'http://localhost:5004')
_MURMURA_URL = os.environ.get('MURMURA_URL',       'http://localhost:8765')


@app.route('/api/scene-status', methods=['GET'])
def scene_status():
    """GET /api/scene-status

    Returns the current scene's configuration aggregated from:
      - The flame service  (trigger-to-flame-sequence mappings for the scene)
      - The OSC proxy      (on_enter OSC sequence configured for the scene)

    Also returns service URLs so the UI can build clickable links.

    Response shape:
    {
      "active_scene": str | null,
      "flame_service": {
        "url": str,
        "reachable": bool,
        "mappings": [...],   // trigger mappings whose modes contain active_scene
        "configured": bool   // true iff mappings is non-empty
      },
      "osc_proxy": {
        "url": str,
        "reachable": bool,
        "on_enter": [...],   // OSC steps from scenes[active_scene].on_enter
        "description": str,
        "configured": bool
      },
      "murmura_url": str     // link only — not polled
    }
    """
    active_scene = mode_manager.get_active_mode()

    # ── Flame service ──────────────────────────────────────────────────────
    flame = {'url': _FLAME_URL, 'reachable': False, 'mappings': [], 'configured': False}
    try:
        r = requests.get(f"{_FLAME_URL}/trigger-integration/mappings", timeout=3)
        if r.status_code == 200:
            flame['reachable'] = True
            all_mappings = r.json().get('mappings', [])
            if active_scene:
                scene_mappings = [m for m in all_mappings
                                  if active_scene in m.get('modes', [])]
            else:
                scene_mappings = []
            flame['mappings']   = scene_mappings
            flame['configured'] = len(scene_mappings) > 0
    except Exception as e:
        logger.warning("Could not reach flame service for scene-status: %s", e)

    # ── OSC proxy ──────────────────────────────────────────────────────────
    osc = {'url': _OSC_URL, 'reachable': False, 'on_enter': [],
           'mappings': [], 'description': '', 'configured': False}
    try:
        r = requests.get(f"{_OSC_URL}/api/scenes", timeout=3)
        if r.status_code == 200:
            osc['reachable'] = True
            scenes = r.json().get('scenes', {})
            if active_scene and active_scene in scenes:
                scene_cfg = scenes[active_scene]
                on_enter  = scene_cfg.get('on_enter', [])
                osc['on_enter']    = on_enter
                osc['description'] = scene_cfg.get('description', '')

        # Also fetch trigger mappings for this scene (new scene-first API)
        if active_scene and osc['reachable']:
            mr = requests.get(f"{_OSC_URL}/api/mappings",
                              params={'scene': active_scene}, timeout=3)
            if mr.status_code == 200:
                osc['mappings'] = mr.json().get('mappings', [])

        osc['configured'] = len(osc['on_enter']) > 0 or len(osc['mappings']) > 0
    except Exception as e:
        logger.warning("Could not reach OSC proxy for scene-status: %s", e)

    return jsonify({
        'active_scene':  active_scene,
        'flame_service': flame,
        'osc_proxy':     osc,
        'murmura_url':   _MURMURA_URL,
    }), 200


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health():
    # Use the thread-safe accessor methods rather than reading attributes directly.
    return jsonify({
        'status': 'healthy',
        'service': 'mode_service',
        'modes_count': len(mode_manager.get_modes()),
        'active_mode': mode_manager.get_active_mode(),
        'schedules_count': len(mode_manager.get_schedules()),
    }), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Mode Management Service')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT,
                        help=f'Port to run the service on (default: {DEFAULT_PORT})')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Mode Management Service Starting")
    logger.info("=" * 60)
    logger.info(f"Modes file:   {MODES_FILE}")
    logger.info(f"Current modes: {mode_manager.get_modes()}")
    logger.info(f"Active mode:   {mode_manager.get_active_mode()}")
    logger.info(f"Schedules:     {len(mode_manager.get_schedules())}")
    logger.info(f"Web UI:        http://0.0.0.0:{args.port}/")
    logger.info("=" * 60)

    app.run(host='0.0.0.0', port=args.port, debug=False)
