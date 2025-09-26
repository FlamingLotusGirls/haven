#!/usr/bin/env python3
"""
Simple web server that serves nozzle data via REST API and visualization page.
"""

import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading
import argparse


class NozzleDataHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for serving nozzle data and visualization.
    """
    
    def __init__(self, *args, data_file='nozzle_data.json', **kwargs):
        self.data_file = data_file
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/nozzles':
            self._serve_nozzle_data()
        elif parsed_path.path == '/' or parsed_path.path == '/index.html':
            self._serve_visualization()
        else:
            self._send_404()
    
    def _serve_nozzle_data(self):
        """Serve nozzle data as JSON array of 36 floats."""
        try:
            # Read nozzle data from file
            nozzle_values = self._read_nozzle_data()
            
            # Convert to JSON string and encode to bytes
            json_data = json.dumps(nozzle_values)
            
            # Send JSON response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')  # Enable CORS
            self.end_headers()
            
            self.wfile.write(json_data.encode('utf-8'))
            
        except Exception as e:
            print(f"Error serving nozzle data: {str(e)}")
            self._send_error(500, f"Internal server error: {str(e)}")
    
    def _read_nozzle_data(self):
        """Read nozzle data from JSON file with error handling."""
        if not os.path.exists(self.data_file):
            # Return zeros if file doesn't exist yet
            return [0.0] * 36
        
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                
            # Validate data format
            if isinstance(data, list) and len(data) == 36:
                return [float(x) for x in data]
            else:
                print(f"Invalid data format in {self.data_file}, returning zeros")
                return [0.0] * 36
                
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading {self.data_file}: {str(e)}, returning zeros")
            return [0.0] * 36
    
    def _serve_visualization(self):
        """Serve the nozzle visualization HTML file."""
        try:
            # Try to read the nozzle_visualization.html file
            if os.path.exists('nozzle_visualization.html'):
                with open('nozzle_visualization.html', 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
            else:
                # Fallback if visualization file doesn't exist
                self._serve_fallback_index()
                
        except Exception as e:
            print(f"Error serving visualization: {str(e)}")
            self._send_error(500, f"Error loading visualization: {str(e)}")
    
    def _serve_fallback_index(self):
        """Serve a fallback index page if visualization file is missing."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Nozzle Data API</title>
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
                <h1>Nozzle Data API</h1>
                
                <div class="error">
                    <strong>Warning:</strong> nozzle_visualization.html file not found. 
                    Please ensure the visualization file is in the same directory as this server.
                </div>
                
                <p>Simple REST API for accessing nozzle data from BirdBathController.</p>
                
                <h2>Endpoints</h2>
                <div class="endpoint">
                    <strong>GET /nozzles</strong><br>
                    Returns an array of 36 floating point values representing current nozzle states.<br>
                    <code>Content-Type: application/json</code>
                </div>
                
                <h2>Example</h2>
                <p><a href="/nozzles" target="_blank">GET /nozzles</a></p>
                
                <h2>Usage</h2>
                <p>This server reads nozzle data from <code>nozzle_data.json</code> which is updated by BirdBathController.</p>
            </div>
        </body>
        </html>
        """
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _send_404(self):
        """Send 404 Not Found response."""
        self.send_response(404)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'404 Not Found')
    
    def _send_error(self, code, message):
        """Send error response."""
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to customize logging."""
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {format % args}")


def create_handler_class(data_file):
    """Create a handler class with the specified data file."""
    class Handler(NozzleDataHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, data_file=data_file, **kwargs)
    return Handler


def main():
    """Main function to start the web server."""
    parser = argparse.ArgumentParser(description='Nozzle Data Web Server')
    parser.add_argument('--port', '-p', type=int, default=8080,
                       help='Port to run the server on (default: 8080)')
    parser.add_argument('--host', default='localhost',
                       help='Host to bind to (default: localhost)')
    parser.add_argument('--data-file', default='nozzle_data.json',
                       help='JSON file containing nozzle data (default: nozzle_data.json)')
    
    args = parser.parse_args()
    
    # Create handler class with data file
    handler_class = create_handler_class(args.data_file)
    
    # Create and start server
    server = HTTPServer((args.host, args.port), handler_class)
    
    print(f"Starting nozzle data server on http://{args.host}:{args.port}")
    print(f"Reading data from: {args.data_file}")
    print("Serving visualization from: nozzle_visualization.html")
    print("Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
