#!/usr/bin/env python3
"""
Trigger Integration Module

Integrates the Flame Control system with the Haven Trigger Server.
Handles:
- Registration with trigger server (with automatic retry)
- Listening for trigger events via TCP socket
- Managing trigger-to-flame-sequence mappings (scene-forward data model)
- Triggering flame sequences based on incoming triggers
- Preventing duplicate sequence execution

JSON data model (trigger_mappings.json):
    {
      "scenes": {
        "BurnsNight": [
          {"id": 1, "trigger_name": "...", "flame_sequence": "...",
           "allow_override": false, ...}
        ],
        "DayScene": []          <- explicitly configured, no mappings (valid "quiet scene")
      }
    }

The top-level grouping is the SCENE, not the individual trigger mapping.
Individual mappings no longer carry a "modes" list; scene membership is
expressed by which scene key the mapping lives under.

An entry with an empty list means the scene is explicitly configured with
no fire mappings — this is a valid operational state ("quiet scene") and is
distinct from a scene that has never been configured at all.
"""

import copy
import json
import logging
import requests
import socket
import threading
import time
from threading import Lock
import flames_controller
import pattern_manager

logger = logging.getLogger("flames")


class TriggerIntegration:
    def __init__(self, trigger_server_url="http://localhost:5002",
                 listen_port=6000, mode_service_url="http://localhost:5003"):
        self.trigger_server_url = trigger_server_url
        self.listen_port = listen_port
        self.mode_service_url = mode_service_url
        self.service_name = "FlameServer"

        # Thread / running state
        self.registered = False
        self.registration_thread = None
        self.listen_thread = None
        self.running = False

        # Scene-forward mapping storage:
        #   { scene_name: [ {id, trigger_name, flame_sequence, allow_override, ...}, ... ] }
        # A key whose value is [] means "configured with no mappings" (quiet scene).
        # A scene NOT in this dict has never been configured.
        self.scene_data = {}
        self.mappings_lock = Lock()
        self.mappings_file = "trigger_mappings.json"

        # Available triggers from trigger server
        self.available_triggers = []
        self.triggers_lock = Lock()

        # Mode management.
        # "Unknown" is the boot-time sentinel; replaced only when the mode
        # service returns a real (non-null) mode name.
        self.available_modes = []
        self.active_mode = "Unknown"
        self.modes_lock = Lock()

        # True when the active scene is known but NOT present in scene_data.
        # A scene present in scene_data with zero mappings is NOT unconfigured.
        # Protected by modes_lock.
        self.scene_unconfigured = False

        # Socket server
        self.server_socket = None
        self.client_socket = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self):
        """Start the integration service."""
        logger.info("Starting Trigger Integration")
        self.running = True

        self.load_mappings()

        self.registration_thread = threading.Thread(
            target=self._registration_loop, daemon=True)
        self.registration_thread.start()

        self.listen_thread = threading.Thread(
            target=self._listen_for_triggers, daemon=True)
        self.listen_thread.start()

        self.refresh_thread = threading.Thread(
            target=self._refresh_triggers_loop, daemon=True)
        self.refresh_thread.start()

        self.mode_refresh_thread = threading.Thread(
            target=self._refresh_modes_loop, daemon=True)
        self.mode_refresh_thread.start()

        logger.info("Trigger Integration started")

    def shutdown(self):
        """Shutdown the integration service."""
        logger.info("Shutting down Trigger Integration")
        self.running = False
        for sock in (self.server_socket, self.client_socket):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        logger.info("Trigger Integration shut down")

    # =========================================================================
    # Background threads
    # =========================================================================

    def _registration_loop(self):
        while self.running:
            if not self.registered:
                try:
                    self._register_with_server()
                    if not self.registered:
                        logger.warning("Registration failed, will retry in 30 s")
                        time.sleep(30)
                except Exception as e:
                    logger.error(f"Error during registration: {e}")
                    time.sleep(30)
            else:
                time.sleep(60)

    def _register_with_server(self):
        try:
            response = requests.post(
                f"{self.trigger_server_url}/api/register",
                json={"name": self.service_name, "port": self.listen_port,
                      "host": "localhost", "protocol": "TCP_SOCKET"},
                timeout=10
            )
            if response.status_code == 200:
                self.registered = True
                logger.info(f"Registered with Trigger Server: {response.json()}")
                self._fetch_available_triggers()
                return True
            else:
                logger.error(f"Registration failed: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"Cannot connect to Trigger Server at {self.trigger_server_url}")
            return False
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False

    def _listen_for_triggers(self):
        logger.info(f"Starting TCP listener on port {self.listen_port}")
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(('localhost', self.listen_port))
            self.server_socket.listen(5)
            logger.info(f"Listening for trigger events on port {self.listen_port}")
            while self.running:
                try:
                    self.server_socket.settimeout(1.0)
                    try:
                        client_socket, address = self.server_socket.accept()
                        logger.info(f"Accepted connection from {address}")
                        self.client_socket = client_socket
                        self._handle_connection(client_socket)
                    except socket.timeout:
                        continue
                except Exception as e:
                    if self.running:
                        logger.error(f"Error in listen loop: {e}")
                        time.sleep(1)
        except Exception as e:
            logger.error(f"Failed to bind to port {self.listen_port}: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()

    def _handle_connection(self, client_socket):
        buffer = ""
        try:
            client_socket.settimeout(1.0)
            while self.running:
                try:
                    data = client_socket.recv(1024).decode('utf-8')
                    if not data:
                        logger.info("Connection closed by remote")
                        break
                    buffer += data
                    logger.info("Received trigger data")
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            try:
                                self._handle_trigger_event(json.loads(line))
                            except json.JSONDecodeError as e:
                                logger.error(f"Invalid JSON received: {line} - {e}")
                except socket.timeout:
                    continue
                except socket.error as e:
                    logger.info(f"Socket error, connection closed: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error handling connection: {e}")
                    break
        finally:
            try:
                client_socket.close()
            except Exception:
                pass

    def _refresh_triggers_loop(self):
        while self.running:
            try:
                self._fetch_available_triggers()
                self._validate_mappings()
            except Exception as e:
                logger.error(f"Error refreshing triggers: {e}")
            time.sleep(300)

    def _refresh_modes_loop(self):
        """Poll the mode service at 1 s until a real mode is known, then 10 s."""
        fast_poll = True
        while self.running:
            try:
                self._fetch_modes()
                self._fetch_active_mode()
                if fast_poll:
                    with self.modes_lock:
                        known = self.active_mode not in (None, "Unknown")
                    if known:
                        fast_poll = False
                        logger.info("Known mode received; switching to 10 s poll interval")
            except Exception as e:
                logger.error(f"Error refreshing modes: {e}")
            time.sleep(1 if fast_poll else 10)

    # =========================================================================
    # Mode / scene helpers
    # =========================================================================

    # Name of the special trigger pushed by mode_service on every scene change.
    SCENE_TRIGGER_NAME = 'SceneChange'

    def _update_scene_configured_flag(self):
        """Recompute whether the current active scene is present in scene_data.

        A scene is "configured" if it has ANY entry in scene_data, even with
        an empty mappings list (quiet / intentionally-silent scene).
        The 'Unknown' boot-time sentinel is always treated as configured so
        dispatch is not suppressed before the mode service responds.

        Updates self.scene_unconfigured (protected by modes_lock).
        Must be called with neither lock held.
        """
        with self.modes_lock:
            scene = self.active_mode

        if scene in (None, 'Unknown'):
            with self.modes_lock:
                self.scene_unconfigured = False
            return

        with self.mappings_lock:
            configured = scene in self.scene_data

        with self.modes_lock:
            was_unconfigured = self.scene_unconfigured
            self.scene_unconfigured = not configured

        if not configured and not was_unconfigured:
            logger.info(
                "Scene '%s' is not registered in trigger config — "
                "all trigger dispatch disabled until this scene is configured.",
                scene
            )
        elif configured and was_unconfigured:
            logger.info(
                "Scene '%s' is now configured; re-enabling trigger dispatch.",
                scene
            )

    def _fetch_modes(self):
        try:
            response = requests.get(
                f"{self.mode_service_url}/api/modes", timeout=5)
            if response.status_code == 200:
                data = response.json()
                with self.modes_lock:
                    self.available_modes = data.get('modes', [])
                logger.debug(f"Fetched {len(self.available_modes)} modes")
                return True
            logger.debug(f"Failed to fetch modes: {response.status_code}")
            return False
        except requests.exceptions.ConnectionError:
            logger.debug(f"Cannot connect to Mode Service at {self.mode_service_url}")
            return False
        except Exception as e:
            logger.debug(f"Error fetching modes: {e}")
            return False

    def _fetch_active_mode(self):
        """Fetch the active mode. Never replaces a known mode with null."""
        try:
            response = requests.get(
                f"{self.mode_service_url}/api/modes/active", timeout=5)
            if response.status_code == 200:
                data = response.json()
                active_mode = data.get('active_mode')
                _changed = False
                with self.modes_lock:
                    if active_mode is not None:
                        if self.active_mode != active_mode:
                            logger.info(f"Active mode: {self.active_mode} -> {active_mode}")
                            self.active_mode = active_mode
                            _changed = True
                    else:
                        logger.warning(
                            "Mode service has no active mode set; "
                            "retaining current mode=%r", self.active_mode)
                if _changed:
                    self._update_scene_configured_flag()
                return True
            logger.debug(f"Failed to fetch active mode: {response.status_code}")
            return False
        except requests.exceptions.ConnectionError:
            logger.debug(f"Cannot connect to Mode Service at {self.mode_service_url}")
            return False
        except Exception as e:
            logger.debug(f"Error fetching active mode: {e}")
            return False

    def refresh_active_mode(self):
        """Force a synchronous re-fetch. Returns (success, active_mode)."""
        ok = self._fetch_active_mode()
        with self.modes_lock:
            return ok, self.active_mode

    def _fetch_available_triggers(self):
        try:
            response = requests.get(
                f"{self.trigger_server_url}/api/triggers", timeout=10)
            if response.status_code == 200:
                with self.triggers_lock:
                    self.available_triggers = response.json().get('triggers', [])
                logger.debug(f"Fetched {len(self.available_triggers)} triggers")
                return True
            logger.error(f"Failed to fetch triggers: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error fetching triggers: {e}")
            return False

    def _validate_mappings(self):
        with self.mappings_lock:
            trigger_names = {t['name'] for t in self.available_triggers}
            for scene_name, mappings in self.scene_data.items():
                for m in mappings:
                    if m['trigger_name'] not in trigger_names:
                        logger.warning(
                            "Scene '%s': mapping references non-existent trigger: "
                            "%s -> %s", scene_name, m['trigger_name'], m['flame_sequence'])

    # =========================================================================
    # Event dispatch
    # =========================================================================

    def _handle_trigger_event(self, event):
        """Process an incoming trigger event and fire mapped flame sequences."""
        trigger_name  = event.get('name')
        trigger_value = event.get('value')

        logger.info(f"Received trigger: {trigger_name}, value: {trigger_value}")

        # ── Scene-change fast path ───────────────────────────────────────────
        if trigger_name == self.SCENE_TRIGGER_NAME and trigger_value is not None:
            scene_changed = False
            with self.modes_lock:
                if self.active_mode != trigger_value:
                    logger.info(f"Scene updated via trigger: {self.active_mode} -> {trigger_value}")
                    self.active_mode = trigger_value
                    scene_changed = True
            if scene_changed:
                self._update_scene_configured_flag()
            # Fall through so any flame mapping on SceneChange still fires.

        with self.modes_lock:
            current_mode      = self.active_mode
            scene_unconfigured = self.scene_unconfigured

        if scene_unconfigured:
            logger.info(
                "Trigger '%s' suppressed — scene '%s' has no trigger configuration",
                trigger_name, current_mode)
            return

        # Get a snapshot of the current scene's mappings (outside the lock)
        with self.mappings_lock:
            scene_mappings = list(self.scene_data.get(current_mode, []))

        for mapping in scene_mappings:
            if mapping['trigger_name'] != trigger_name:
                continue

            # ── Value matching ───────────────────────────────────────────────
            if 'trigger_value_min' in mapping or 'trigger_value_max' in mapping:
                try:
                    numeric_value = float(trigger_value) if trigger_value is not None else None
                    if numeric_value is None:
                        continue
                    if 'trigger_value_min' in mapping and mapping['trigger_value_min'] is not None:
                        if numeric_value < float(mapping['trigger_value_min']):
                            continue
                    if 'trigger_value_max' in mapping and mapping['trigger_value_max'] is not None:
                        if numeric_value > float(mapping['trigger_value_max']):
                            continue
                except (ValueError, TypeError):
                    logger.warning(
                        "Could not convert trigger value '%s' to numeric for range check",
                        trigger_value)
                    continue
            else:
                if mapping.get('trigger_value') and mapping['trigger_value'] != trigger_value:
                    continue

            # ── Fire ─────────────────────────────────────────────────────────
            flame_sequence = mapping['flame_sequence']
            allow_override = mapping.get('allow_override', False)
            is_active = flames_controller.isFlameEffectActive(flame_sequence)

            if is_active and not allow_override:
                logger.info(f"Sequence '{flame_sequence}' already active, skipping")
                continue

            if is_active and allow_override:
                logger.info(f"Restarting sequence '{flame_sequence}'")
                flames_controller.stopFlameEffect(flame_sequence)
                time.sleep(0.1)

            logger.info(f"Triggering flame sequence: {flame_sequence}")
            flames_controller.doFlameEffect(flame_sequence)

    # =========================================================================
    # Persistence — load / save
    # =========================================================================

    def load_mappings(self):
        """Load scene-forward mappings from file, auto-migrating legacy format."""
        try:
            with open(self.mappings_file, 'r') as f:
                data = json.load(f)

            if 'scenes' in data:
                # New scene-forward format
                with self.mappings_lock:
                    self.scene_data = data['scenes']
                total = sum(len(v) for v in self.scene_data.values())
                logger.info(
                    "Loaded %d mappings across %d scenes",
                    total, len(self.scene_data))

            elif 'mappings' in data:
                # Legacy flat format (modes list per mapping) — migrate once
                logger.info("Migrating legacy trigger_mappings.json to scene-forward format")
                scene_data = {}
                for m in data.get('mappings', []):
                    modes = m.get('modes', [])
                    scene_name = modes[0] if modes else '_unscoped'
                    mapping = {k: v for k, v in m.items() if k != 'modes'}
                    if scene_name not in scene_data:
                        scene_data[scene_name] = []
                    scene_data[scene_name].append(mapping)
                with self.mappings_lock:
                    self.scene_data = scene_data
                total = sum(len(v) for v in scene_data.values())
                logger.info(
                    "Migrated %d mappings into %d scenes",
                    total, len(scene_data))
                self.save_mappings()   # persist migrated format immediately
            else:
                with self.mappings_lock:
                    self.scene_data = {}

        except FileNotFoundError:
            logger.info("No mapping file found, starting with empty scene data")
            self.scene_data = {}
        except Exception as e:
            logger.error(f"Error loading mappings: {e}")
            self.scene_data = {}

    def save_mappings(self):
        """Persist scene_data to trigger_mappings.json."""
        try:
            with self.mappings_lock:
                data = {'scenes': copy.deepcopy(self.scene_data)}
            with open(self.mappings_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("Saved trigger mappings")
            return True
        except Exception as e:
            logger.error(f"Error saving mappings: {e}")
            return False

    # =========================================================================
    # Public CRUD
    # =========================================================================

    def get_mappings(self):
        """Return a flat list of all mappings; each has a 'scene' field added."""
        with self.mappings_lock:
            result = []
            for scene_name, mappings in self.scene_data.items():
                for m in mappings:
                    result.append(dict(m, scene=scene_name))
        return result

    def get_mapping(self, mapping_id):
        """Return a single mapping by ID (with 'scene' field), or None."""
        with self.mappings_lock:
            for scene_name, mappings in self.scene_data.items():
                for m in mappings:
                    if m.get('id') == mapping_id:
                        return dict(m, scene=scene_name)
        return None

    def get_configured_scenes(self):
        """Return sorted list of scene names that have an explicit entry in scene_data."""
        with self.mappings_lock:
            return sorted(self.scene_data.keys())

    def register_scene(self, name):
        """Ensure scene_data has an entry for name (creates empty list if absent)."""
        with self.mappings_lock:
            if name not in self.scene_data:
                self.scene_data[name] = []
            else:
                return True   # already exists — nothing to do
        self.save_mappings()
        self._update_scene_configured_flag()
        logger.info(f"Registered scene: {name}")
        return True

    def delete_scene(self, name):
        """Delete a scene and all its mappings."""
        with self.mappings_lock:
            if name not in self.scene_data:
                return False
            del self.scene_data[name]
        self.save_mappings()
        self._update_scene_configured_flag()
        logger.info(f"Deleted scene: {name}")
        return True

    def _next_id(self):
        """Return the next available globally-unique mapping ID (call inside lock)."""
        all_ids = [m.get('id', 0)
                   for scene_list in self.scene_data.values()
                   for m in scene_list]
        return max(all_ids + [0]) + 1

    def add_mapping(self, scene, trigger_name, trigger_value, flame_sequence,
                    allow_override=False, trigger_value_min=None, trigger_value_max=None):
        """Add a new trigger-to-flame mapping to a scene."""
        with self.mappings_lock:
            mapping_id = self._next_id()
            mapping = {
                'id': mapping_id,
                'trigger_name': trigger_name,
                'flame_sequence': flame_sequence,
                'allow_override': allow_override,
            }
            if trigger_value_min is not None:
                mapping['trigger_value_min'] = float(trigger_value_min)
            if trigger_value_max is not None:
                mapping['trigger_value_max'] = float(trigger_value_max)
            if (trigger_value is not None
                    and trigger_value_min is None
                    and trigger_value_max is None):
                mapping['trigger_value'] = trigger_value

            if scene not in self.scene_data:
                self.scene_data[scene] = []
            self.scene_data[scene].append(mapping)

        self.save_mappings()
        self._update_scene_configured_flag()
        logger.info(f"Added mapping: {trigger_name} -> {flame_sequence} (scene: {scene})")
        return dict(mapping, scene=scene)

    def update_mapping(self, mapping_id, scene=None, trigger_name=None,
                       trigger_value=None, flame_sequence=None, allow_override=None,
                       trigger_value_min=None, trigger_value_max=None):
        """Update an existing mapping. Optionally move it to a different scene."""
        found = False
        with self.mappings_lock:
            for scene_name, mappings in self.scene_data.items():
                for i, mapping in enumerate(mappings):
                    if mapping['id'] != mapping_id:
                        continue
                    # Field updates
                    if trigger_name  is not None: mapping['trigger_name']  = trigger_name
                    if flame_sequence is not None: mapping['flame_sequence'] = flame_sequence
                    if allow_override is not None: mapping['allow_override'] = allow_override

                    # Value updates (same logic as before)
                    if trigger_value_min is not None or trigger_value_max is not None:
                        mapping.pop('trigger_value', None)
                        if trigger_value_min not in (None, ''):
                            mapping['trigger_value_min'] = float(trigger_value_min)
                        elif trigger_value_min == '':
                            mapping.pop('trigger_value_min', None)
                        if trigger_value_max not in (None, ''):
                            mapping['trigger_value_max'] = float(trigger_value_max)
                        elif trigger_value_max == '':
                            mapping.pop('trigger_value_max', None)
                    elif trigger_value is not None:
                        mapping.pop('trigger_value_min', None)
                        mapping.pop('trigger_value_max', None)
                        if trigger_value != '':
                            mapping['trigger_value'] = trigger_value
                        else:
                            mapping.pop('trigger_value', None)

                    # Optional scene move
                    if scene is not None and scene != scene_name:
                        mappings.pop(i)
                        if scene not in self.scene_data:
                            self.scene_data[scene] = []
                        self.scene_data[scene].append(mapping)

                    found = True
                    break
                if found:
                    break

        if found:
            self.save_mappings()
            self._update_scene_configured_flag()
            logger.info(f"Updated mapping {mapping_id}")
        return found

    def delete_mapping(self, mapping_id):
        """Delete a trigger mapping by ID."""
        deleted = False
        with self.mappings_lock:
            for scene_name in list(self.scene_data):
                before = len(self.scene_data[scene_name])
                self.scene_data[scene_name] = [
                    m for m in self.scene_data[scene_name] if m['id'] != mapping_id]
                if len(self.scene_data[scene_name]) < before:
                    deleted = True
                    break

        if deleted:
            self.save_mappings()
            self._update_scene_configured_flag()
            logger.info(f"Deleted mapping {mapping_id}")
        return deleted

    def copy_scene_mappings(self, from_scene, to_scene):
        """Duplicate all mappings from from_scene into to_scene.

        Returns the number of new mappings created.
        If from_scene is in scene_data but empty, registers to_scene as empty
        and returns 0 (this is intentional — duplicating a quiet scene).
        """
        new_mappings = []
        with self.mappings_lock:
            if from_scene not in self.scene_data:
                return 0
            source = self.scene_data[from_scene]
            next_id = self._next_id()
            for src in source:
                nm = copy.deepcopy(src)
                nm['id'] = next_id
                next_id += 1
                new_mappings.append(nm)
            if to_scene not in self.scene_data:
                self.scene_data[to_scene] = []
            self.scene_data[to_scene].extend(new_mappings)

        self.save_mappings()
        self._update_scene_configured_flag()
        logger.info("Copied %d mappings from scene '%s' → '%s'",
                    len(new_mappings), from_scene, to_scene)
        return len(new_mappings)

    # =========================================================================
    # Public accessors
    # =========================================================================

    def get_available_triggers(self):
        """Return cached trigger list (maintained by the background refresh thread)."""
        with self.triggers_lock:
            return self.available_triggers.copy()

    def get_available_modes(self):
        """Return cached mode list (maintained by _refresh_modes_loop). Never blocks."""
        with self.modes_lock:
            return self.available_modes.copy()

    def get_active_mode(self):
        """Return cached active mode (maintained by _refresh_modes_loop). Never blocks."""
        with self.modes_lock:
            return self.active_mode

    def get_active_mode_cached(self):
        """Alias for get_active_mode — kept for backward compatibility."""
        return self.get_active_mode()

    def get_status(self):
        with self.modes_lock:
            active_mode       = self.active_mode
            scene_unconfigured = self.scene_unconfigured
        with self.mappings_lock:
            total_mappings    = sum(len(v) for v in self.scene_data.values())
            configured_scenes = sorted(self.scene_data.keys())
        return {
            'registered':              self.registered,
            'trigger_server_url':      self.trigger_server_url,
            'listen_port':             self.listen_port,
            'mapping_count':           total_mappings,
            'available_triggers_count': len(self.available_triggers),
            'available_modes_count':   len(self.available_modes),
            'active_mode':             active_mode,
            'scene_unconfigured':      scene_unconfigured,
            'configured_scenes':       configured_scenes,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

_integration = None


def init(trigger_server_url="http://localhost:5002", listen_port=6000):
    global _integration
    _integration = TriggerIntegration(trigger_server_url, listen_port)
    _integration.start()
    return _integration


def shutdown():
    global _integration
    if _integration:
        _integration.shutdown()


def get_integration():
    return _integration
