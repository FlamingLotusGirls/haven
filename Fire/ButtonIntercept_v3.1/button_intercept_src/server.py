#!/usr/bin/env python3
"""
Simple web server for managing flame effect patterns and channel mappings
"""

import http.server
import socketserver
import json
import os
import urllib.parse
from datetime import datetime

class PatternHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    def load_json_file(self, filename):
        """Load JSON file or return default structure if file doesn't exist"""
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        # Return default structures
        if filename == 'channels.json':
            return []  # Empty list of channel mappings
        elif filename == 'patterns.json':
            return {
                "sequences": {},
                "patterns": {},
                "pattern_mappings": {}
            }
        return {}
    
    def save_json_file(self, filename, data):
        """Save data to JSON file"""
        try:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving {filename}: {e}")
            return False
    
    def do_GET(self):
        if self.path == '/':
            self.path = '/index.html'
        elif self.path == '/api/channels':
            self.send_json_response(self.load_json_file('channels.json'))
            return
        elif self.path == '/api/patterns':
            self.send_json_response(self.load_json_file('patterns.json'))
            return
        
        super().do_GET()
    
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(post_data)
        except:
            self.send_error_response(400, "Invalid JSON")
            return
        
        if self.path == '/api/channels':
            if self.save_json_file('channels.json', data):
                self.send_json_response({"status": "success"})
            else:
                self.send_error_response(500, "Failed to save channels")
        elif self.path == '/api/patterns':
            if self.save_json_file('patterns.json', data):
                self.send_json_response({"status": "success"})
            else:
                self.send_error_response(500, "Failed to save patterns")
        else:
            self.send_error_response(404, "Not found")
    
    def send_json_response(self, data):
        """Send JSON response"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def send_error_response(self, code, message):
        """Send error response"""
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

def main():
    PORT = 8010
    
    with socketserver.TCPServer(("", PORT), PatternHandler) as httpd:
        print(f"Server running at http://localhost:{PORT}")
        print("Press Ctrl+C to stop the server")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            httpd.shutdown()

if __name__ == "__main__":
    main()
