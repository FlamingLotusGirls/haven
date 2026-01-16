#!/usr/bin/env python3
"""
Trigger Integration Module

Integrates the Flame Control system with the Haven Trigger Server.
Handles:
- Registration with trigger server (with automatic retry)
- Listening for trigger events via TCP socket
- Managing trigger-to-flame-sequence mappings
- Triggering flame sequences based on incoming triggers
- Preventing duplicate sequence execution
"""

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
    def __init__(self, trigger_server_url="http://localhost:5002", listen_port=6000):
        self.trigger_server_url = trigger_server_url
        self.listen_port = listen_port
        self.service_name = "FlameServer"
        
        # State
        self.registered = False
        self.registration_thread = None
        self.listen_thread = None
        self.running = False
        
        # Mappings: list of {id, trigger_name, trigger_value, flame_sequence, allow_override}
        self.mappings = []
        self.mappings_lock = Lock()
        self.mappings_file = "trigger_mappings.json"
        
        # Available triggers from server
        self.available_triggers = []
        self.triggers_lock = Lock()
        
        # Socket server
        self.server_socket = None
        self.client_socket = None
        
    def start(self):
        """Start the integration service."""
        logger.info("Starting Trigger Integration")
        self.running = True
        
        # Load mappings from file
        self.load_mappings()
        
        # Start registration thread (with retry)
        self.registration_thread = threading.Thread(target=self._registration_loop, daemon=True)
        self.registration_thread.start()
        
        # Start listening thread
        self.listen_thread = threading.Thread(target=self._listen_for_triggers, daemon=True)
        self.listen_thread.start()
        
        # Start trigger refresh thread
        self.refresh_thread = threading.Thread(target=self._refresh_triggers_loop, daemon=True)
        self.refresh_thread.start()
        
        logger.info("Trigger Integration started")
    
    def shutdown(self):
        """Shutdown the integration service."""
        logger.info("Shutting down Trigger Integration")
        self.running = False
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        
        logger.info("Trigger Integration shut down")
    
    def _registration_loop(self):
        """Continuously attempt registration with the trigger server."""
        while self.running:
            if not self.registered:
                try:
                    self._register_with_server()
                    if self.registered:
                        logger.info("Successfully registered with Trigger Server")
                    else:
                        logger.warning("Registration failed, will retry in 30 seconds")
                        time.sleep(30)
                except Exception as e:
                    logger.error(f"Error during registration: {e}")
                    time.sleep(30)
            else:
                # Check registration status periodically
                time.sleep(60)
    
    def _register_with_server(self):
        """Register with the trigger server."""
        try:
            registration_data = {
                "name": self.service_name,
                "port": self.listen_port,
                "host": "localhost",
                "protocol": "TCP_SOCKET"
            }
            
            response = requests.post(
                f"{self.trigger_server_url}/api/register",
                json=registration_data,
                timeout=10
            )
            
            if response.status_code == 200:
                self.registered = True
                logger.info(f"Registered with Trigger Server: {response.json()}")
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
        """Listen for incoming trigger events on TCP socket."""
        logger.info(f"Starting TCP listener on port {self.listen_port}")
        
        # Create server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind(('localhost', self.listen_port))
            self.server_socket.listen(5)
            logger.info(f"Listening for trigger events on port {self.listen_port}")
            
            while self.running:
                try:
                    # Accept connection (this should be from the trigger server)
                    self.server_socket.settimeout(1.0)  # Non-blocking with timeout
                    try:
                        client_socket, address = self.server_socket.accept()
                        logger.info(f"Accepted connection from {address}")
                        self.client_socket = client_socket
                        
                        # Handle the connection
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
        """Handle a persistent connection from the trigger server."""
        buffer = ""
        
        try:
            # Set a timeout so we can check self.running periodically
            client_socket.settimeout(1.0)
            
            while self.running:
                try:
                    data = client_socket.recv(1024).decode('utf-8')
                    if not data:
                        logger.info("Connection closed by remote")
                        break
                    
                    buffer += data
                    
                    # Process complete messages (newline-delimited JSON)
                    logger.info("Received trigger data")
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if line.strip():
                            try:
                                trigger_event = json.loads(line)
                                self._handle_trigger_event(trigger_event)
                            except json.JSONDecodeError as e:
                                logger.error(f"Invalid JSON received: {line} - {e}")
                                
                except socket.timeout:
                    # This is normal - just checking if we should continue running
                    continue
                except socket.error as e:
                    # Socket errors mean connection is broken
                    logger.info(f"Socket error, connection closed: {e}")
                    break
                except Exception as e:
                    # Log but don't crash on other errors
                    logger.error(f"Error handling connection: {e}")
                    break
        finally:
            # Always clean up the socket
            try:
                client_socket.close()
            except:
                pass
    
    def _handle_trigger_event(self, event):
        """Process an incoming trigger event and trigger flame sequences if mapped."""
        trigger_name = event.get('name')
        trigger_value = event.get('value')
        trigger_id = event.get('id')
        
        logger.info(f"Received trigger event: {trigger_name}, value: {trigger_value}, id: {trigger_id}")
        
        # Find matching mappings
        with self.mappings_lock:
            for mapping in self.mappings:
                if mapping['trigger_name'] == trigger_name:
                    # Check if value matches (if specified in mapping)
                    if mapping.get('trigger_value') and mapping['trigger_value'] != trigger_value:
                        continue
                    
                    flame_sequence = mapping['flame_sequence']
                    allow_override = mapping.get('allow_override', False)
                    
                    # Check if sequence is already active
                    is_active = flames_controller.isFlameEffectActive(flame_sequence)
                    
                    if is_active and not allow_override:
                        logger.info(f"Sequence '{flame_sequence}' already active, skipping (allow_override=False)")
                        continue
                    
                    # Trigger the flame sequence
                    if is_active and allow_override:
                        logger.info(f"Stopping and restarting sequence '{flame_sequence}'")
                        flames_controller.stopFlameEffect(flame_sequence)
                        time.sleep(0.1)  # Brief pause
                    
                    logger.info(f"Triggering flame sequence: {flame_sequence}")
                    flames_controller.doFlameEffect(flame_sequence)
    
    def _refresh_triggers_loop(self):
        """Periodically refresh available triggers from the server."""
        while self.running:
            try:
                self._fetch_available_triggers()
                self._validate_mappings()
            except Exception as e:
                logger.error(f"Error refreshing triggers: {e}")
            
            time.sleep(300)  # Refresh every 5 minutes
    
    def _fetch_available_triggers(self):
        """Fetch available triggers from the trigger server."""
        try:
            response = requests.get(
                f"{self.trigger_server_url}/api/triggers",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                with self.triggers_lock:
                    self.available_triggers = data.get('triggers', [])
                logger.debug(f"Fetched {len(self.available_triggers)} triggers from server")
                return True
            else:
                logger.error(f"Failed to fetch triggers: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error fetching triggers: {e}")
            return False
    
    def _validate_mappings(self):
        """Validate that all mapped triggers exist in the trigger server."""
        with self.mappings_lock:
            trigger_names = [t['name'] for t in self.available_triggers]
            
            for mapping in self.mappings:
                if mapping['trigger_name'] not in trigger_names:
                    logger.warning(
                        f"Mapping references non-existent trigger: {mapping['trigger_name']} -> {mapping['flame_sequence']}"
                    )
    
    def load_mappings(self):
        """Load trigger-to-flame mappings from file."""
        try:
            with open(self.mappings_file, 'r') as f:
                data = json.load(f)
                with self.mappings_lock:
                    self.mappings = data.get('mappings', [])
                logger.info(f"Loaded {len(self.mappings)} trigger mappings")
        except FileNotFoundError:
            logger.info("No mapping file found, starting with empty mappings")
            self.mappings = []
        except Exception as e:
            logger.error(f"Error loading mappings: {e}")
            self.mappings = []
    
    def save_mappings(self):
        """Save trigger-to-flame mappings to file."""
        try:
            with self.mappings_lock:
                data = {'mappings': self.mappings}
            
            with open(self.mappings_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info("Saved trigger mappings")
            return True
        except Exception as e:
            logger.error(f"Error saving mappings: {e}")
            return False
    
    def get_mappings(self):
        """Get all trigger-to-flame mappings."""
        with self.mappings_lock:
            return self.mappings.copy()
    
    def add_mapping(self, trigger_name, trigger_value, flame_sequence, allow_override=False):
        """Add a new trigger-to-flame mapping."""
        mapping = None
        with self.mappings_lock:
            # Generate ID
            mapping_id = max([m.get('id', 0) for m in self.mappings] + [0]) + 1
            
            mapping = {
                'id': mapping_id,
                'trigger_name': trigger_name,
                'trigger_value': trigger_value,
                'flame_sequence': flame_sequence,
                'allow_override': allow_override
            }
            
            self.mappings.append(mapping)
        
        self.save_mappings()
        logger.info(f"Added mapping: {trigger_name} -> {flame_sequence}")
        return mapping
    
    def update_mapping(self, mapping_id, trigger_name=None, trigger_value=None, 
                      flame_sequence=None, allow_override=None):
        """Update an existing mapping."""
        found = False
        with self.mappings_lock:
            for mapping in self.mappings:
                if mapping['id'] == mapping_id:
                    if trigger_name is not None:
                        mapping['trigger_name'] = trigger_name
                    if trigger_value is not None:
                        mapping['trigger_value'] = trigger_value
                    if flame_sequence is not None:
                        mapping['flame_sequence'] = flame_sequence
                    if allow_override is not None:
                        mapping['allow_override'] = allow_override
                    found = True
                    break
        
        if found:
            self.save_mappings()
            logger.info(f"Updated mapping {mapping_id}")
            return True
        
        return False
    
    def delete_mapping(self, mapping_id):
        """Delete a trigger-to-flame mapping."""
        deleted = False
        with self.mappings_lock:
            original_length = len(self.mappings)
            self.mappings = [m for m in self.mappings if m['id'] != mapping_id]
            
            if len(self.mappings) < original_length:
                deleted = True
        
        if deleted:
            self.save_mappings()
            logger.info(f"Deleted mapping {mapping_id}")
            return True
        
        return False
    
    def get_available_triggers(self):
        """Get list of available triggers from the trigger server."""
        with self.triggers_lock:
            return self.available_triggers.copy()
    
    def get_status(self):
        """Get integration status."""
        return {
            'registered': self.registered,
            'trigger_server_url': self.trigger_server_url,
            'listen_port': self.listen_port,
            'mapping_count': len(self.mappings),
            'available_triggers_count': len(self.available_triggers)
        }


# Global instance
_integration = None

def init(trigger_server_url="http://localhost:5002", listen_port=6000):
    """Initialize the trigger integration module."""
    global _integration
    _integration = TriggerIntegration(trigger_server_url, listen_port)
    _integration.start()
    return _integration

def shutdown():
    """Shutdown the trigger integration module."""
    global _integration
    if _integration:
        _integration.shutdown()

def get_integration():
    """Get the global integration instance."""
    return _integration
