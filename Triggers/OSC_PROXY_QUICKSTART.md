# OSC Proxy Quick Start Guide

## What is the OSC Proxy?

The OSC Proxy bridges trigger events from the Trigger Gateway to OSC (Open Sound Control)
clients. It allows you to map any trigger to any OSC command — or a timed sequence of
OSC commands — through a user-friendly web interface. Mappings can be global (all scenes)
or pinned to a specific scene.

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

Open your browser to: **http://localhost:5004**

### 4. Configure OSC Client

1. Enter your OSC client's IP and port
   - Local testing: `127.0.0.1:8000`
   - Remote client: use the client's IP address
2. Click **Update OSC Client**
3. Click **Test Connection** to verify

### 5. Create Your First Mapping

1. Click **➕ Add New Mapping**
2. Select a trigger from the dropdown
3. (Optional) select a scene — leave blank to fire in every scene
4. Enter an OSC address (e.g., `/test/button`)
5. (Optional) add arguments:
   - `${value:int}` — pass trigger value as integer
   - `${value:float}` — pass as float
   - `${value}` — pass as string
   - Literal values like `100` or `hello`
6. Click **Save Mapping**

---

## Key Features at a Glance

### Scene-Aware Mappings

Each mapping has an optional **scene** field.  Leave it blank and the mapping fires
in every scene.  Set it to a scene name (e.g. `NightShow`) and it only fires when
that scene is active.

```json
{"trigger_name": "ShowStart", "scene": "NightShow", "osc_address": "/show/start"}
```

### OSC Sequences

Instead of a single OSC command, a mapping can execute a *sequence* of timed
steps.  Each step has a `delay_ms` (sleep before sending) and its own address + args.

```json
{
  "trigger_name": "ShowStart",
  "scene": "NightShow",
  "sequence": [
    {"delay_ms":    0, "osc_address": "/lights/fade",  "osc_args": [1.0]},
    {"delay_ms": 2000, "osc_address": "/audio/play",   "osc_args": ["intro"]},
    {"delay_ms": 5000, "osc_address": "/smoke/enable", "osc_args": [1]}
  ]
}
```

While a sequence is playing, any new instance of the same trigger is suppressed
until the sequence finishes.

### Named OSC Aliases

Create reusable, human-readable names for OSC address+argument combinations
(e.g. `FadeToBlue` → `/lights/color 0 0 255`) so you don't have to remember
path strings when building mappings.

Manage aliases via `GET/POST/PUT/DELETE /api/aliases`.

### Per-Scene `on_enter` Sequences

Each scene can define an `on_enter` sequence that fires automatically whenever
the scene becomes active (from a `SceneChange` trigger or poll).

```json
"Daytime": {
  "on_enter": [
    {"delay_ms": 0,    "osc_address": "/lights/brightness", "osc_args": [0.8]},
    {"delay_ms": 1000, "osc_address": "/audio/ambient",     "osc_args": ["day"]}
  ]
}
```

Configure via `PUT /api/scenes/<name>/on_enter`.

---

## Testing

### Simple OSC Receiver

```python
from pythonosc import dispatcher, osc_server

def print_handler(addr, *args):
    print(f"OSC: {addr} {args}")

d = dispatcher.Dispatcher()
d.set_default_handler(print_handler)
server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 8000), d)
print("Listening on 127.0.0.1:8000")
server.serve_forever()
```

### Send a Test Trigger via curl

```bash
curl -X POST http://localhost:5002/api/trigger-event \
  -H "Content-Type: application/json" \
  -d '{"name": "TestButton", "value": 1}'
```

---

## Common Use Cases

### Button Press/Release
- Trigger: `Button1` (On/Off)
- OSC: `/button/1`  args: `${value:int}`
- Result: `/button/1 1` on press, `/button/1 0` on release

### Slider/Fader
- Trigger: `Fader1` (Continuous, 0.0–1.0)
- OSC: `/fader/1`  args: `${value:float}`
- Result: `/fader/1 0.75` at 75%

### Scene-Specific Show Trigger
- Trigger: `BigRedButton` (OneShot), Scene: `NightShow`
- Sequence: lights fade → audio start → smoke enable (timed)

### Auto-configure on Scene Change
- Scene `Daytime` on_enter → `/lights/brightness 0.8`
- Scene `NightShow` on_enter → `/lights/color 0 0 255` + `/smoke/enable 1`

---

## Architecture

```
Device → Trigger Gateway (TCP) → OSC Proxy (TCP Socket) → OSC Client (UDP)
                ↑                        ↓
         Scene Service ──────> Scene tracking + on_enter sequences
                             Web Interface (HTTP) localhost:5004
```

## Ports

| Port | Purpose |
|---|---|
| **5002** | Trigger Gateway |
| **5003** | Scene Service |
| **5004** | OSC Proxy Web Interface |
| **5100** | OSC Proxy TCP socket server (receives triggers) |
| **8000** | OSC Client (default, configurable) |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `"Failed to register with gateway"` | Ensure trigger gateway is running on port 5002 |
| OSC messages not received | Verify IP/port, use Test Connection, check firewall (UDP) |
| Trigger not mapped | Check trigger name matches exactly, mapping is enabled |
| Scene-specific mapping not firing | Check `GET /api/status` → `active_scene` matches the mapping's scene |
| Sequence seems stuck | Check `GET /api/active-sequences` — previous sequence may still be playing |

---

## Command Reference

```bash
# Start with defaults (web on 5004, socket on 5100)
python osc_proxy.py

# Start with custom ports
python osc_proxy.py --port 5004 --service-port 5100

# Start with custom gateway URL
python osc_proxy.py --gateway http://localhost:5002

# Check proxy status
curl http://localhost:5004/api/status

# Get all mappings
curl http://localhost:5004/api/mappings

# Get mappings for a specific scene
curl "http://localhost:5004/api/mappings?scene=NightShow"

# Get all named aliases
curl http://localhost:5004/api/aliases

# Get scene configurations
curl http://localhost:5004/api/scenes

# Check for active (playing) sequences
curl http://localhost:5004/api/active-sequences

# Force refresh of active scene from scene service
curl -X POST http://localhost:5004/api/refresh-scene

# Test OSC send
curl -X POST http://localhost:5004/api/test-osc \
  -H "Content-Type: application/json" \
  -d '{"osc_address": "/test", "osc_args": ["hello"]}'
```

---

## Next Steps

- Full documentation: `OSC_PROXY_README.md`
- Trigger types and gateway setup: `README_USAGE.md`
- Trigger dispatch internals: `TRIGGER_DISPATCH.md`
- Scene management: `SCENE_SERVICE.md`
