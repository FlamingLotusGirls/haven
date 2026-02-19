#!/usr/bin/env python3
"""
Mode Management Service

A simple REST API service that manages modes. Only one mode can be active at a time.
Modes are persisted to a JSON file between reboots.

Endpoints:
  POST   /api/modes           - Create a new mode
  DELETE /api/modes/<name>    - Delete a mode
  GET    /api/modes           - Get list of all modes
  POST   /api/modes/active    - Set the active mode
  GET    /api/modes/active    - Get the active mode
"""

from flask import Flask, request, jsonify
import json
import os
import logging
import argparse
from datetime import datetime

app = Flask(__name__)

# Configuration
MODES_FILE = 'modes.json'
DEFAULT_PORT = 5003

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class ModeManager:
    """Manages modes with persistence"""
    
    def __init__(self, filename=MODES_FILE):
        self.filename = filename
        self.modes = set()
        self.active_mode = None
        self.load_modes()
    
    def load_modes(self):
        """Load modes from JSON file"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    self.modes = set(data.get('modes', []))
                    self.active_mode = data.get('active_mode')
                    logger.info(f"Loaded {len(self.modes)} modes from {self.filename}")
                    if self.active_mode:
                        logger.info(f"Active mode: {self.active_mode}")
            except Exception as e:
                logger.error(f"Error loading modes: {e}")
                self.modes = set()
                self.active_mode = None
        else:
            logger.info(f"No existing modes file found, starting fresh")
            self.save_modes()
    
    def save_modes(self):
        """Save modes to JSON file"""
        try:
            data = {
                'modes': list(self.modes),
                'active_mode': self.active_mode,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.filename, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.modes)} modes to {self.filename}")
        except Exception as e:
            logger.error(f"Error saving modes: {e}")
    
    def create_mode(self, name):
        """Create a new mode"""
        if not name or not isinstance(name, str):
            return False, "Mode name must be a non-empty string"
        
        name = name.strip()
        if not name:
            return False, "Mode name cannot be empty"
        
        if name in self.modes:
            return False, f"Mode '{name}' already exists"
        
        self.modes.add(name)
        self.save_modes()
        logger.info(f"Created mode: {name}")
        return True, f"Mode '{name}' created"
    
    def delete_mode(self, name):
        """Delete a mode"""
        if name not in self.modes:
            return False, f"Mode '{name}' does not exist"
        
        self.modes.remove(name)
        
        # If deleting the active mode, clear it
        if self.active_mode == name:
            self.active_mode = None
            logger.info(f"Cleared active mode (was '{name}')")
        
        self.save_modes()
        logger.info(f"Deleted mode: {name}")
        return True, f"Mode '{name}' deleted"
    
    def get_modes(self):
        """Get list of all modes"""
        return sorted(list(self.modes))
    
    def set_active_mode(self, name):
        """Set the active mode"""
        if name is None:
            # Allow clearing the active mode
            self.active_mode = None
            self.save_modes()
            logger.info("Cleared active mode")
            return True, "Active mode cleared"
        
        if name not in self.modes:
            return False, f"Mode '{name}' does not exist"
        
        self.active_mode = name
        self.save_modes()
        logger.info(f"Set active mode: {name}")
        return True, f"Active mode set to '{name}'"
    
    def get_active_mode(self):
        """Get the active mode"""
        return self.active_mode


# Initialize mode manager
mode_manager = ModeManager()


@app.route('/api/modes', methods=['POST'])
def create_mode():
    """Create a new mode"""
    data = request.get_json()
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Missing required field: name'}), 400
    
    success, message = mode_manager.create_mode(data['name'])
    
    if success:
        return jsonify({
            'message': message,
            'mode': data['name']
        }), 201
    else:
        return jsonify({'error': message}), 400


@app.route('/api/modes/<name>', methods=['DELETE'])
def delete_mode(name):
    """Delete a mode"""
    success, message = mode_manager.delete_mode(name)
    
    if success:
        return jsonify({'message': message}), 200
    else:
        return jsonify({'error': message}), 404


@app.route('/api/modes', methods=['GET'])
def get_modes():
    """Get list of all modes"""
    modes = mode_manager.get_modes()
    active = mode_manager.get_active_mode()
    
    return jsonify({
        'modes': modes,
        'active_mode': active,
        'count': len(modes)
    }), 200


@app.route('/api/modes/active', methods=['POST'])
def set_active_mode():
    """Set the active mode"""
    data = request.get_json()
    
    # Allow null/None to clear the active mode
    mode_name = data.get('name') if data else None
    
    success, message = mode_manager.set_active_mode(mode_name)
    
    if success:
        return jsonify({
            'message': message,
            'active_mode': mode_name
        }), 200
    else:
        return jsonify({'error': message}), 400


@app.route('/api/modes/active', methods=['GET'])
def get_active_mode():
    """Get the active mode"""
    active = mode_manager.get_active_mode()
    
    return jsonify({
        'active_mode': active
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'mode_service',
        'modes_count': len(mode_manager.modes),
        'active_mode': mode_manager.active_mode
    }), 200


if __name__ == '__main__':
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Mode Management Service')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT,
                        help=f'Port to run the service on (default: {DEFAULT_PORT})')
    args = parser.parse_args()
    
    port = args.port
    
    logger.info("=" * 60)
    logger.info("Mode Management Service Starting")
    logger.info("=" * 60)
    logger.info(f"Modes file: {MODES_FILE}")
    logger.info(f"Current modes: {mode_manager.get_modes()}")
    logger.info(f"Active mode: {mode_manager.get_active_mode()}")
    logger.info("")
    logger.info("API Endpoints:")
    logger.info("  POST   /api/modes           - Create a new mode")
    logger.info("  DELETE /api/modes/<name>    - Delete a mode")
    logger.info("  GET    /api/modes           - Get list of all modes")
    logger.info("  POST   /api/modes/active    - Set the active mode")
    logger.info("  GET    /api/modes/active    - Get the active mode")
    logger.info("  GET    /health              - Health check")
    logger.info("")
    logger.info(f"Starting server on port {port}...")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
