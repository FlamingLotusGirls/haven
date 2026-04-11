#!/usr/bin/env python3
"""
Test Input Server for BirdBathController

Serves a web page with sliders for each ADC channel so you can inject
fake test data into the named pipe (/tmp/adc_pipe_main or /tmp/beertap_pipe)
without needing real hardware.

Usage:
    python3 test_input_server.py [--pipe /tmp/beertap_pipe] [--port 8090] [--config patterns.yaml]
"""

import argparse
import errno
import json
import os
import pickle
import struct
import time
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------------------------
# Pipe-writing helper
# ---------------------------------------------------------------------------

def write_to_pipe(pipe_path, channel, value):
    """
    Write a single channel value to the named pipe in the same format that
    adc_reader.py uses:  4-byte big-endian length  +  pickled dict

    Args:
        pipe_path: Path to the named pipe (e.g. /tmp/beertap_pipe)
        channel:   Channel name string (e.g. "tap1")
        value:     Float in the range [-1.0, 1.0]

    Returns:
        (success: bool, message: str)
    """
    # Clamp value to legal range
    value = max(-1.0, min(1.0, float(value)))

    data = {
        'channel': channel,
        'value': value,
        'timestamp': time.time(),
    }

    pickled = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    message = struct.pack('>I', len(pickled)) + pickled

    # Create the pipe if it doesn't exist yet
    if not os.path.exists(pipe_path):
        try:
            os.mkfifo(pipe_path)
            print(f"Created named pipe: {pipe_path}")
        except OSError as e:
            return False, f"Could not create pipe {pipe_path}: {e}"

    try:
        fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, message)
        finally:
            os.close(fd)
        return True, f"Sent {channel}={value:.4f}"
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False, "No reader connected to pipe (is BirdBathController running?)"
        return False, f"Error writing to pipe: {e}"


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class TestInputHandler(BaseHTTPRequestHandler):

    # Injected by create_handler_class()
    pipe_path: str = '/tmp/adc_pipe_main'
    channels: list = ['tap1']
    html_file: str = 'test_input.html'

    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in ('/', '/index.html', '/test_input.html'):
            self._serve_html()
        elif parsed.path == '/channels':
            self._serve_channels()
        else:
            self._send_404()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == '/set_channel':
            self._handle_set_channel()
        else:
            self._send_404()

    # Allow CORS for browser fetch() calls
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    def _serve_html(self):
        """Serve the test input HTML page."""
        html_path = os.path.join(os.path.dirname(__file__), self.html_file)
        if os.path.exists(html_path):
            with open(html_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        else:
            self._send_error(404, f"HTML file not found: {html_path}")

    def _serve_channels(self):
        """Return JSON: { channels: [...], pipe: "..." }"""
        payload = json.dumps({'channels': self.channels, 'pipe': self.pipe_path})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload.encode('utf-8'))

    def _handle_set_channel(self):
        """
        POST body must be JSON: { "channel": "tap1", "value": 0.75 }
        """
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else b''
            data = json.loads(body)

            channel = str(data.get('channel', '')).strip()
            value = float(data.get('value', 0.0))

            if not channel:
                self._send_json(400, {'ok': False, 'error': 'Missing channel name'})
                return

            ok, msg = write_to_pipe(self.pipe_path, channel, value)
            status = 200 if ok else 503
            self._send_json(status, {'ok': ok, 'message': msg,
                                     'channel': channel, 'value': value})

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            self._send_json(400, {'ok': False, 'error': f'Bad request: {e}'})
        except Exception as e:
            self._send_json(500, {'ok': False, 'error': str(e)})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_404(self):
        self.send_response(404)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'404 Not Found')

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_handler_class(pipe_path: str, channels: list, html_file: str):
    class Handler(TestInputHandler):
        pass
    Handler.pipe_path = pipe_path
    Handler.channels = channels
    Handler.html_file = html_file
    return Handler


# ---------------------------------------------------------------------------
# Channel discovery
# ---------------------------------------------------------------------------

def load_channels_from_config(config_file: str) -> list:
    """
    Read patterns.yaml and return the list of unique input_channel names.
    Falls back to ['tap1'] if the file can't be read.
    """
    if not os.path.exists(config_file):
        print(f"Config file '{config_file}' not found; defaulting to channel 'tap1'")
        return ['tap1']

    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        channels = []
        for entry in config.get('patterns', []):
            ch = entry.get('input_channel')
            if ch and ch not in channels:
                channels.append(ch)
        if not channels:
            print("No channels found in config; defaulting to 'tap1'")
            channels = ['tap1']
        return channels
    except Exception as e:
        print(f"Error reading config: {e}; defaulting to 'tap1'")
        return ['tap1']


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='BirdBath Test Input Server – inject fake ADC data via a browser')
    parser.add_argument('--pipe', default='/tmp/adc_pipe_main',
                        help='Named pipe to write to (default: /tmp/adc_pipe_main)')
    parser.add_argument('--port', '-p', type=int, default=8090,
                        help='HTTP port (default: 8090)')
    parser.add_argument('--host', default='0.0.0.0',
                        help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--config', '-c', default='patterns.yaml',
                        help='patterns.yaml to read channel names from (default: patterns.yaml)')
    parser.add_argument('--channels', nargs='+', metavar='CHANNEL',
                        help='Explicit channel names (overrides --config)')
    args = parser.parse_args()

    if args.channels:
        channels = args.channels
    else:
        channels = load_channels_from_config(args.config)

    print(f"BirdBath Test Input Server")
    print(f"  Pipe:     {args.pipe}")
    print(f"  Channels: {', '.join(channels)}")
    print(f"  URL:      http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/")
    print("Press Ctrl+C to stop\n")

    handler_class = create_handler_class(args.pipe, channels, 'test_input.html')
    server = HTTPServer((args.host, args.port), handler_class)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down test input server.")
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
