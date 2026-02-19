# Haven OSC Proxy Server

## Overview

The OSC Proxy Server bridges the Haven Trigger Gateway with OSC (Open Sound Control) clients. It receives trigger events from the Trigger Gateway and forwards them as OSC messages to configured OSC clients based on user-defined mappings.

## Features

- **TCP Socket Integration**: Registers with the Trigger Gateway as a TCP_SOCKET service for reliable trigger event delivery
- **Web-Based Configuration**: User-friendly web interface for managing trigger-to-OSC mappings
- **Dynamic OSC Client Configuration**: Configure OSC client IP address and port through the web interface
- **Flexible Mapping System**: Map any trigger to any OSC address with customizable arguments
- **Variable Substitution**: Use trigger values dynamically in OSC messages with `${value}`, `${value:int}`, or `${value:float}`
- **Enable/Disable Mappings**: Toggle mappings on/off without deleting them
- **Real-time Status Monitoring**: View socket server and OSC client status at a glance
- **Persistent Configuration**: All mappings and settings are saved and restored on restart

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────┐
│ Trigger Gateway │ ──TCP──>│   OSC Proxy      │ ──OSC──>│ OSC Client  │
│  (Port 5002)    │         │  (Port 5100)     │  UDP    │ (Port 8000) │
└─────────────────┘         └──────────────────┘         └─────────────┘
                                     │
                                     │ HTTP
                                     ▼
                            ┌──────────────────┐
                            │  Web Interface   │
                            │  (Port 5003)     │
                            └──────────────────┘
```

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- Flask (web server)
- python-osc (OSC protocol support)
- requests (HTTP client for gateway communication)

### 2. Verify Trigger Gateway is Running

The OSC Proxy requires the Trigger Gateway to be running:

```bash
python trigger_gateway.py --port 5002
```

## Usage

### Starting the OSC Proxy Server

Basic usage (defaults to port 5003 for web interface, port 5100 for socket server):

```bash
python osc_proxy.py
```

With custom ports:

```bash
python osc_proxy.py --port 5003 --service-port 5100 --gateway http://localhost:5002
```

Command line options:
- `--port`: Port for the web interface (default: 5003)
- `--service-port`: Port for the TCP socket server that receives triggers (default: 5100)
- `--gateway`: URL of the Trigger Gateway (default: http://localhost:5002)

### Accessing the Web Interface

Open your browser to:
```
http://localhost:5003
```

## Configuration

### 1. Configure OSC Client

In the web interface, set the OSC client destination:

1. **OSC Host/IP**: The IP address of the OSC client (e.g., `127.0.0.1` for localhost, or `192.168.1.100` for a remote machine)
2. **OSC Port**: The UDP port the OSC client is listening on (e.g., `8000`)
3. Click **Update OSC Client**
4. Click **Test Connection** to send a test message to `/test`

### 2. Create Trigger-to-OSC Mappings

1. Click **➕ Add New Mapping**
2. Select a **Trigger** from the dropdown (triggers are automatically fetched from the Gateway)
3. Enter an **OSC Address** (e.g., `/synth/note`, `/light/brightness`)
4. Add **OSC Arguments** (optional):
   - Click **Add Argument** to add arguments
   - Use literal values: `100`, `1.5`, `"hello"`
   - Use variable substitution:
     - `${value}` - Insert trigger value as string
     - `${value:int}` - Convert trigger value to integer
     - `${value:float}` - Convert trigger value to float
5. Click **Save Mapping**

### 3. Managing Mappings

Each mapping shows:
- 🎯 **Trigger name**
- ➜ **OSC address**
- **Arguments** (if any)

Actions available:
- **⏸ Disable/▶️ Enable**: Toggle the mapping without deleting it
- **✏️ Edit**: Modify the mapping
- **🗑️ Delete**: Remove the mapping permanently

## Examples

### Example 1: Simple Button Trigger

**Trigger**: `RedButton` (On/Off type)
**OSC Mapping**: 
- Address: `/button/red`
- Args: `${value:int}`

When the button is pressed (value=1), sends: `/button/red 1`
When the button is released (value=0), sends: `/button/red 0`

### Example 2: Slider with Multiple Parameters

**Trigger**: `Slider1` (Continuous type, range 0.0-1.0)
**OSC Mapping**:
- Address: `/synth/volume`
- Args: `${value:float}`, `main`

When slider is at 0.75, sends: `/synth/volume 0.75 "main"`

### Example 3: Discrete Selector

**Trigger**: `ModeSelector` (Discrete type, values 1-5)
**OSC Mapping**:
- Address: `/system/mode`
- Args: `${value:int}`

When selector is at position 3, sends: `/system/mode 3`

### Example 4: OneShot Trigger

**Trigger**: `FireButton` (OneShot type)
**OSC Mapping**:
- Address: `/effect/fire`
- Args: `trigger`

When button is pressed, sends: `/effect/fire "trigger"`

## Configuration Files

### osc_proxy_config.json

Stores all proxy configuration:
- OSC client host and port
- Trigger-to-OSC mappings
- Gateway URL
- Service port

Example:
```json
{
  "osc_client": {
    "host": "127.0.0.1",
    "port": 8000
  },
  "mappings": [
    {
      "id": 1,
      "trigger_name": "RedButton",
      "osc_address": "/button/red",
      "osc_args": ["${value:int}"],
      "enabled": true,
      "created_at": "2026-02-18T09:30:00"
    }
  ],
  "gateway_url": "http://localhost:5002",
  "service_port": 5100
}
```

## Service Registration

The OSC Proxy automatically registers itself with the Trigger Gateway on startup using the TCP_SOCKET protocol. This establishes a persistent connection for receiving trigger events.

Registration details:
- **Service Name**: `OSC_Proxy`
- **Protocol**: `TCP_SOCKET` (persistent connection)
- **Host**: `localhost`
- **Port**: Configured via `--service-port` (default: 5100)

To verify registration, check the Trigger Gateway's web interface or query:
```bash
curl http://localhost:5002/api/services
```

## Trigger Event Flow

1. **Device sends trigger** → Trigger Gateway
2. **Gateway dispatches event** → OSC Proxy (via TCP socket)
3. **OSC Proxy processes event**:
   - Looks up trigger name in mappings
   - Checks if mapping is enabled
   - Substitutes variables in OSC arguments
4. **OSC Proxy sends OSC message** → OSC Client (via UDP)

## Troubleshooting

### OSC Client Not Receiving Messages

1. **Check OSC client configuration**:
   - Verify the host IP and port are correct
   - Use the "Test Connection" button to send a test message

2. **Check firewall settings**:
   - Ensure UDP traffic is allowed on the OSC port
   - For remote clients, check network firewall rules

3. **Verify OSC client is listening**:
   - Most OSC clients will show incoming messages
   - Try a simple OSC receiver like `oscdump` or `TouchOSC`

### Not Receiving Triggers

1. **Check socket server status**:
   - Status bar should show "Socket: Running on :5100"
   - If offline, restart the OSC Proxy

2. **Verify gateway registration**:
   - Check the gateway's services list
   - OSC_Proxy should be listed with socket_connected: true

3. **Check trigger mappings**:
   - Ensure trigger names match exactly
   - Verify mappings are enabled

### Variables Not Substituting

1. **Check trigger has value**:
   - OneShot triggers don't have values
   - On/Off, Discrete, and Continuous triggers should have values

2. **Verify variable syntax**:
   - Use `${value}`, `${value:int}`, or `${value:float}`
   - Check for typos in the variable name

## API Endpoints

The OSC Proxy exposes a REST API for configuration:

### Get Configuration
```
GET /api/config
```

### Update OSC Client
```
PUT /api/config/osc-client
Content-Type: application/json

{
  "host": "127.0.0.1",
  "port": 8000
}
```

### Get Available Triggers
```
GET /api/triggers
```

### Get All Mappings
```
GET /api/mappings
```

### Add Mapping
```
POST /api/mappings
Content-Type: application/json

{
  "trigger_name": "RedButton",
  "osc_address": "/button/red",
  "osc_args": ["${value:int}"],
  "enabled": true
}
```

### Update Mapping
```
PUT /api/mappings/<id>
Content-Type: application/json

{
  "trigger_name": "RedButton",
  "osc_address": "/button/red/updated",
  "osc_args": ["${value:int}"],
  "enabled": true
}
```

### Delete Mapping
```
DELETE /api/mappings/<id>
```

### Toggle Mapping
```
POST /api/mappings/<id>/toggle
```

### Test OSC Message
```
POST /api/test-osc
Content-Type: application/json

{
  "osc_address": "/test",
  "osc_args": ["hello", 123]
}
```

### Get Server Status
```
GET /api/status
```

## Integration Examples

### Using with Max/MSP

In Max/MSP, use the `udpreceive` object:

```
[udpreceive 8000]
|
[OpenSoundControl]
|
[route /button/red /synth/volume]
```

### Using with Pure Data

In Pure Data, use `[netreceive -u -b]`:

```
[netreceive -u -b 8000]
|
[oscparse]
|
[route /button/red /synth/volume]
```

### Using with TouchOSC

1. Open TouchOSC settings
2. Set OSC Connection to receive on port 8000
3. Create controls that listen to the OSC addresses you've mapped

### Using with Python OSC Client

```python
from pythonosc import dispatcher
from pythonosc import osc_server

def handle_button(unused_addr, value):
    print(f"Button value: {value}")

dispatcher = dispatcher.Dispatcher()
dispatcher.map("/button/red", handle_button)

server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 8000), dispatcher)
print("Listening for OSC messages on port 8000")
server.serve_forever()
```

## Production Deployment

### Running as a System Service

Create a systemd service file `/etc/systemd/system/osc-proxy.service`:

```ini
[Unit]
Description=Haven OSC Proxy Server
After=network.target trigger-gateway.service
Requires=trigger-gateway.service

[Service]
Type=simple
User=haven
WorkingDirectory=/home/haven/Triggers
ExecStart=/usr/bin/python3 /home/haven/Triggers/osc_proxy.py --port 5003
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable osc-proxy.service
sudo systemctl start osc-proxy.service
```

### Monitoring

Check service status:
```bash
sudo systemctl status osc-proxy.service
```

View logs:
```bash
sudo journalctl -u osc-proxy.service -f
```

## Security Considerations

1. **Network Access**: The OSC Proxy listens on all interfaces (0.0.0.0). In production, consider restricting to localhost or specific IPs.

2. **No Authentication**: The web interface has no authentication. Use a reverse proxy with authentication for public access.

3. **OSC Protocol**: OSC uses UDP which is connectionless. Ensure your network is trusted.

## Support and Development

- **Project**: Haven Art Installation
- **Repository**: FlamingLotusGirls/haven
- **Related Files**: 
  - `trigger_gateway.py` - Main trigger gateway server
  - `README_USAGE.md` - Trigger system documentation
  - `TRIGGER_DISPATCH.md` - Trigger dispatch documentation

## License

Part of the Haven project by Flaming Lotus Girls.
