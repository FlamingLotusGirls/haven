# OSC Proxy Quick Start Guide

## What is the OSC Proxy?

The OSC Proxy bridges trigger events from the Trigger Gateway to OSC (Open Sound Control) clients. It allows you to map any trigger to any OSC command through a user-friendly web interface.

## Quick Setup (5 minutes)

### 1. Start the Trigger Gateway (if not already running)

```bash
python trigger_gateway.py --port 5002
```

### 2. Start the OSC Proxy

```bash
python osc_proxy.py
```

### 3. Open the Web Interface

Open your browser to: **http://localhost:5003**

### 4. Configure OSC Client

1. In the web interface, enter your OSC client's IP and port
   - For local testing: `127.0.0.1:8000`
   - For remote clients: Use the client's IP address
2. Click **Update OSC Client**
3. Click **Test Connection** to verify

### 5. Create Your First Mapping

1. Click **➕ Add New Mapping**
2. Select a trigger from the dropdown
3. Enter an OSC address (e.g., `/test/button`)
4. (Optional) Add arguments:
   - Use `${value:int}` to pass the trigger value as an integer
   - Use `${value:float}` for float values
   - Use literal values like `100` or `hello`
5. Click **Save Mapping**

## Testing

### Test with a Simple OSC Receiver

Create a test receiver (`osc_test_receiver.py`):

```python
from pythonosc import dispatcher
from pythonosc import osc_server

def print_handler(unused_addr, *args):
    print(f"OSC Message: {unused_addr} {args}")

dispatcher = dispatcher.Dispatcher()
dispatcher.set_default_handler(print_handler)

server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 8000), dispatcher)
print("Listening for OSC on 127.0.0.1:8000")
server.serve_forever()
```

Run it:
```bash
python osc_test_receiver.py
```

### Send a Test Trigger

Use curl to send a trigger event to the gateway:

```bash
curl -X POST http://localhost:5002/api/trigger-event \
  -H "Content-Type: application/json" \
  -d '{"name": "TestButton", "value": 1}'
```

You should see the OSC message in your receiver!

## Common Use Cases

### Button Press/Release
- Trigger: `Button1` (On/Off)
- OSC: `/button/1` with args `${value:int}`
- Result: Sends `/button/1 1` on press, `/button/1 0` on release

### Slider/Fader
- Trigger: `Fader1` (Continuous, 0.0-1.0)
- OSC: `/fader/1` with args `${value:float}`
- Result: Sends `/fader/1 0.75` when slider is at 75%

### Mode Selector
- Trigger: `ModeSwitch` (Discrete, 1-4)
- OSC: `/mode/select` with args `${value:int}`
- Result: Sends `/mode/select 3` when switch is in position 3

## Architecture

```
Device → Trigger Gateway (TCP) → OSC Proxy (TCP Socket) → OSC Client (UDP)
                                        ↓
                                  Web Interface (HTTP)
                                   localhost:5003
```

## Ports Used

- **5002**: Trigger Gateway (must be running first)
- **5003**: OSC Proxy Web Interface
- **5100**: OSC Proxy Socket Server (receives triggers)
- **8000**: OSC Client (default, configurable)

## Troubleshooting

### "Failed to register with gateway"
- Ensure the Trigger Gateway is running on port 5002
- Check if there are any firewall issues

### OSC messages not received
- Verify OSC client IP and port are correct
- Use the "Test Connection" button
- Check if OSC client is actually listening

### Trigger not mapped
- Ensure the trigger name exactly matches
- Check that the mapping is enabled (not disabled)
- Verify the trigger exists in the gateway

## Next Steps

- Read the full documentation: `OSC_PROXY_README.md`
- Learn about trigger types: `README_USAGE.md`
- Understand trigger dispatch: `TRIGGER_DISPATCH.md`

## Command Reference

```bash
# Start OSC Proxy with defaults
python osc_proxy.py

# Start with custom ports
python osc_proxy.py --port 5003 --service-port 5100

# Start with custom gateway URL
python osc_proxy.py --gateway http://localhost:5002

# Check if proxy is running
curl http://localhost:5003/api/status

# Get all mappings
curl http://localhost:5003/api/mappings

# Test OSC send
curl -X POST http://localhost:5003/api/test-osc \
  -H "Content-Type: application/json" \
  -d '{"osc_address": "/test", "osc_args": ["hello"]}'
```

## Files Created

- `osc_proxy.py` - Main Python server
- `osc_proxy.html` - Web interface
- `osc_proxy_config.json` - Configuration (auto-created)
- `OSC_PROXY_README.md` - Full documentation
- `OSC_PROXY_QUICKSTART.md` - This file

Happy mapping! 🎵
