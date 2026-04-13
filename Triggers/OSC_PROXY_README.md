# Haven OSC Proxy Server

## Overview

The OSC Proxy Server bridges the Haven Trigger Gateway with OSC (Open Sound Control)
clients. It receives trigger events from the Trigger Gateway and forwards them as OSC
messages to configured OSC clients based on user-defined mappings.

## Features

- **TCP Socket Integration** — registers with the Trigger Gateway as a `TCP_SOCKET`
  service for reliable trigger event delivery
- **Scene-Aware Mappings** — each trigger→OSC mapping can be pinned to a specific
  scene; mappings with no scene set fire in every scene
- **OSC Sequences** — a single trigger can fire a *sequence* of timed OSC messages
  (`delay_ms` before each step) instead of a single command
- **Named OSC Aliases** — give human-readable names to frequently-used OSC addresses
  and refer to them by name in the UI
- **Per-Scene `on_enter` Sequences** — automatically fire an OSC sequence whenever a
  scene becomes active
- **Web-Based Configuration** — user-friendly web interface for managing everything
- **Variable Substitution** — use trigger values dynamically with `${value}`,
  `${value:int}`, `${value:float}`
- **Enable/Disable Mappings** — toggle mappings on/off without deleting them
- **Real-time Status Monitoring** — view socket server and OSC client status at a glance
- **Persistent Configuration** — all mappings, aliases and scene config are saved to
  `osc_proxy_config.json` and restored on restart

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
                             │  (Port 5004)     │
                             └──────────────────┘
                                      ▲
                              ┌───────┴────────┐
                              │ Scene Service  │
                              │  (Port 5003)   │
                              └────────────────┘
```

## Installation

### Install Dependencies

```bash
pip install -r requirements.txt
```

This installs: Flask, python-osc, requests.

### Verify Trigger Gateway is Running

```bash
python trigger_gateway.py --port 5002
```

---

## Usage

### Starting the OSC Proxy Server

```bash
python osc_proxy.py
```

Default ports: **5004** for the web interface, **5100** for the TCP socket server.

With custom ports:

```bash
python osc_proxy.py --port 5004 --service-port 5100 --gateway http://localhost:5002
```

Command-line options:

| Option | Default | Description |
|---|---|---|
| `--port` | `5004` | Port for the web interface |
| `--service-port` | `5100` | Port for the TCP socket server (trigger events) |
| `--gateway` | `http://localhost:5002` | Trigger Gateway URL |

### Accessing the Web Interface

```
http://localhost:5004
```

---

## Configuration

### 1. Configure OSC Client

In the web interface, set the OSC client destination:
1. **OSC Host/IP** — IP address of the OSC client (`127.0.0.1` for localhost)
2. **OSC Port** — UDP port the OSC client is listening on (e.g., `8000`)
3. Click **Update OSC Client**
4. Click **Test Connection** to send a `/test` message

### 2. Create Trigger-to-OSC Mappings

1. Click **➕ Add New Mapping**
2. Select a **Trigger** from the dropdown
3. (Optional) select a **Scene** — leave blank to fire in every scene
4. Choose between a single OSC command or a multi-step **Sequence** (see below)
5. Add **OSC Arguments** (optional) with variable substitution:
   - `${value}` — insert trigger value as string
   - `${value:int}` — convert to integer
   - `${value:float}` — convert to float
6. Click **Save Mapping**

---

## Key Concepts

### Single-Command Mappings (legacy / simple)

The original mapping format: one trigger → one OSC message.

```json
{
  "trigger_name": "RedButton",
  "osc_address": "/button/red",
  "osc_args": ["${value:int}"],
  "scene": "",
  "enabled": true
}
```

### OSC Sequences

A mapping can instead specify a `sequence` — an ordered list of steps, each with an
optional pre-delay. Steps are executed in order in a background thread; the first step
fires immediately (`delay_ms: 0`), subsequent steps sleep for their `delay_ms` first.

```json
{
  "trigger_name": "ShowStart",
  "scene": "NightShow",
  "sequence": [
    {"delay_ms":    0, "osc_address": "/lights/fade",  "osc_args": [1.0]},
    {"delay_ms": 2000, "osc_address": "/audio/play",   "osc_args": ["intro"]},
    {"delay_ms": 5000, "osc_address": "/pyro/enable",  "osc_args": [1]}
  ],
  "enabled": true
}
```

While a sequence is playing, any new instance of the same trigger is suppressed until
the sequence finishes. Old `osc_address`/`osc_args` mappings still work transparently
(they are treated as a single-step sequence with `delay_ms: 0`).

### Named OSC Aliases

Aliases are reusable, human-readable names for OSC address+argument combinations.
Define them once and refer to them by name in the UI (instead of remembering `/path/to/address`).

```json
{
  "id": 1,
  "alias": "FadeToBlue",
  "osc_address": "/lights/color",
  "osc_args": [0, 0, 255],
  "description": "Set lights to full blue"
}
```

### Scene-Aware Mappings

Each mapping has an optional `scene` field:
- **Empty string (`""`)** — fires in **every** scene (global mapping)
- **Named scene** — only fires when that scene is currently active

The active scene is tracked automatically via the `SceneChange` trigger from the scene
service and by polling the scene service every 10 seconds.

### Per-Scene `on_enter` Sequences

Each scene can have an `on_enter` sequence that fires automatically whenever that scene
becomes active (either from a `SceneChange` trigger or initial scene poll).

```json
{
  "scenes": {
    "Daytime": {
      "description": "Daytime ambient mode",
      "on_enter": [
        {"delay_ms":    0, "osc_address": "/lights/brightness", "osc_args": [0.8]},
        {"delay_ms": 1000, "osc_address": "/audio/ambient",     "osc_args": ["day"]}
      ]
    }
  }
}
```

The built-in `Unknown` scene fires its `on_enter` when the scene service is unreachable.
It cannot be deleted.

---

## API Reference

### OSC Client

#### Get Full Configuration
```
GET /api/config
```

#### Update OSC Client
```
PUT /api/config/osc-client
Content-Type: application/json

{"host": "127.0.0.1", "port": 8000}
```

#### Test OSC Message
```
POST /api/test-osc
Content-Type: application/json

{"osc_address": "/test", "osc_args": ["hello", 123]}
```

---

### Trigger Mappings

#### Get All Mappings
```
GET /api/mappings
GET /api/mappings?scene=Daytime    # filter by scene
```

#### Add Mapping (single command)
```
POST /api/mappings
Content-Type: application/json

{
  "trigger_name": "RedButton",
  "osc_address": "/button/red",
  "osc_args": ["${value:int}"],
  "scene": "",
  "enabled": true
}
```

#### Add Mapping (sequence)
```
POST /api/mappings
Content-Type: application/json

{
  "trigger_name": "ShowStart",
  "scene": "NightShow",
  "sequence": [
    {"delay_ms":    0, "osc_address": "/lights/fade", "osc_args": [1.0]},
    {"delay_ms": 2000, "osc_address": "/audio/play",  "osc_args": ["intro"]}
  ],
  "enabled": true
}
```

Response `201`: `{"message": "Mapping added successfully", "mapping": {...}}`

#### Update Mapping
```
PUT /api/mappings/<id>
Content-Type: application/json
```
Same body shape as POST.

#### Delete Mapping
```
DELETE /api/mappings/<id>
```

#### Toggle Mapping Enabled/Disabled
```
POST /api/mappings/<id>/toggle
```

---

### Named OSC Aliases

#### Get All Aliases
```
GET /api/aliases
```
Response: `{"aliases": [...]}`

#### Add Alias
```
POST /api/aliases
Content-Type: application/json

{
  "alias": "FadeToBlue",
  "osc_address": "/lights/color",
  "osc_args": [0, 0, 255],
  "description": "Set lights to full blue"
}
```
Response `201`: `{"message": "Alias added", "alias": {...}}`

#### Update Alias
```
PUT /api/aliases/<id>
Content-Type: application/json

{"alias": "FadeToBlue", "osc_address": "/lights/color", "osc_args": [0, 0, 255]}
```

#### Delete Alias
```
DELETE /api/aliases/<id>
```

---

### Scene Management

#### Get All Scene Configurations
```
GET /api/scenes
```
Response: `{"scenes": {"Daytime": {"on_enter": [...], "description": "..."}, ...}, "active_scene": "Daytime"}`

#### Register a New Scene
```
POST /api/scenes
Content-Type: application/json

{"scene_name": "Daytime", "description": "Daytime ambient mode"}
```
Returns `200` if scene already registered, `201` if newly created.

#### Set `on_enter` Sequence for a Scene
```
PUT /api/scenes/<scene_name>/on_enter
Content-Type: application/json

{
  "on_enter": [
    {"delay_ms": 0,    "osc_address": "/lights/brightness", "osc_args": [0.8]},
    {"delay_ms": 1000, "osc_address": "/audio/ambient",     "osc_args": ["day"]}
  ],
  "description": "Daytime ambient mode"
}
```
Creates the scene entry if it doesn't exist.

#### Copy Scene Configuration
```
POST /api/scenes/<scene_name>/copy
Content-Type: application/json

{"new_name": "Daytime_v2"}
```
Deep-copies on_enter config to the new name. Returns `404` if source not found,
`409` if target already exists.

#### Delete a Scene
```
DELETE /api/scenes/<scene_name>
```
Deletes the scene config **and** all trigger mappings that belong to it.
The `Unknown` scene cannot be deleted (returns `400`).

#### Scene Sync Status
```
GET /api/scenes/sync
```
Returns a comparison between locally configured scenes and scenes in the scene service:
```json
{
  "configured_scenes": ["Daytime", "NightShow", "Unknown"],
  "scene_service_scenes": ["Daytime", "NightShow"],
  "active_scene": "Daytime"
}
```

---

### Status and Utilities

#### Get Server Status
```
GET /api/status
```
```json
{
  "service_name": "OSC_Proxy",
  "socket_server_running": true,
  "socket_server_port": 5100,
  "osc_client_initialized": true,
  "osc_client_config": {"host": "127.0.0.1", "port": 8000},
  "gateway_url": "http://localhost:5002",
  "active_scene": "Daytime",
  "mappings_count": 12,
  "active_sequences": 0
}
```

#### Get Active Trigger Sequences
```
GET /api/active-sequences
```
Returns the names of triggers whose sequences are currently playing:
```json
{"active_sequences": ["ShowStart"]}
```

#### Get Available Triggers (from Gateway)
```
GET /api/triggers
```

#### Get Available Scenes (from Scene Service)
```
GET /api/available-scenes
```

#### Force Scene Refresh
```
POST /api/refresh-scene
```
Immediately re-polls the scene service and updates the active scene.
```json
{"active_scene": "Daytime", "changed": false}
```

---

## Configuration File

### `osc_proxy_config.json`

All settings are saved to this file automatically.

```json
{
  "osc_client": {
    "host": "127.0.0.1",
    "port": 8000
  },
  "gateway_url": "http://localhost:5002",
  "scene_service_url": "http://localhost:5003",
  "service_port": 5100,
  "mappings": [
    {
      "id": 1,
      "trigger_name": "RedButton",
      "osc_address": "/button/red",
      "osc_args": ["${value:int}"],
      "scene": "",
      "enabled": true,
      "created_at": "2026-04-13T09:00:00"
    },
    {
      "id": 2,
      "trigger_name": "ShowStart",
      "scene": "NightShow",
      "sequence": [
        {"delay_ms":    0, "osc_address": "/lights/fade", "osc_args": [1.0]},
        {"delay_ms": 2000, "osc_address": "/audio/play",  "osc_args": ["intro"]}
      ],
      "enabled": true,
      "created_at": "2026-04-13T09:01:00"
    }
  ],
  "osc_aliases": [
    {
      "id": 1,
      "alias": "FadeToBlue",
      "osc_address": "/lights/color",
      "osc_args": [0, 0, 255],
      "description": "Set lights to full blue"
    }
  ],
  "scenes": {
    "Unknown": {
      "on_enter": [],
      "description": "Fallback scene — active when scene service is unreachable"
    },
    "Daytime": {
      "on_enter": [
        {"delay_ms": 0, "osc_address": "/lights/brightness", "osc_args": [0.8]}
      ],
      "description": "Daytime ambient mode"
    }
  }
}
```

---

## Examples

### Example 1: Simple Button Trigger (global)

| Field | Value |
|---|---|
| Trigger | `RedButton` (On/Off) |
| Scene | *(empty — fires in any scene)* |
| OSC Address | `/button/red` |
| Args | `${value:int}` |

Press → `/button/red 1`  ·  Release → `/button/red 0`

### Example 2: Multi-Step Show Sequence

```json
{
  "trigger_name": "ShowStart",
  "scene": "NightShow",
  "sequence": [
    {"delay_ms":    0, "osc_address": "/lights/fade",  "osc_args": [1.0]},
    {"delay_ms": 2000, "osc_address": "/audio/play",   "osc_args": ["intro"]},
    {"delay_ms": 5000, "osc_address": "/pyro/enable",  "osc_args": [1]}
  ]
}
```

Fires lights immediately, audio 2 s later, pyro 5 s in — all in one background thread.

### Example 3: Slider / Fader

| Field | Value |
|---|---|
| Trigger | `Slider1` (Continuous, 0.0–1.0) |
| OSC Address | `/synth/volume` |
| Args | `${value:float}`, `main` |

Slider at 75% → `/synth/volume 0.75 "main"`

### Example 4: Scene `on_enter`

When `NightShow` becomes active:
```json
"on_enter": [
  {"delay_ms":    0, "osc_address": "/lights/color",  "osc_args": [0, 0, 255]},
  {"delay_ms": 1000, "osc_address": "/smoke/enable",  "osc_args": [1]}
]
```

---

## Trigger Event Flow

1. Device sends trigger → Trigger Gateway
2. Gateway dispatches event → OSC Proxy (TCP socket, newline-delimited JSON)
3. OSC Proxy processes event:
   - If `SceneChange`: updates active scene, fires `on_enter` for new scene
   - Otherwise: finds all enabled mappings matching trigger name + active scene
   - If a sequence for this trigger is already playing, new event is suppressed
4. OSC Proxy fires each matching mapping's sequence in a background thread
5. Each step: sleep `delay_ms`, send OSC message (UDP)

---

## Troubleshooting

### OSC Client Not Receiving Messages

1. Verify host IP and port — use **Test Connection**
2. Check firewall: UDP must be open on the OSC port
3. Verify OSC client is listening (use `oscdump` or TouchOSC)

### Not Receiving Triggers

1. Status bar should show `Socket: Running on :5100` — restart if offline
2. Check `GET /api/status` → `socket_server_running: true`
3. Check gateway services list: `curl http://localhost:5002/api/services`
   — `OSC_Proxy` should appear with `socket_connected: true`

### Variables Not Substituting

1. OneShot triggers have no value — variable substitution will return empty/0
2. Check syntax: `${value}`, `${value:int}`, `${value:float}`

### Sequence Not Firing

1. Check `GET /api/active-sequences` — if the trigger name appears, a previous
   sequence is still running and new events are being suppressed
2. Verify the mapping's `scene` field matches the currently active scene
   (`GET /api/status` → `active_scene`)

---

## Running as a System Service

Use the provided `osc_proxy.service` file:

```ini
[Unit]
Description=FLG Haven OSC Proxy Service
After=network-online.target trigger.service
Wants=network-online.target

[Service]
Environment="PYTHONPATH=/home/flaming/haven/util"
ExecStart=/usr/bin/python3 /home/flaming/haven/Triggers/osc_proxy.py \
    --service-port 5100 \
    --gateway http://localhost:5002
WorkingDirectory=/home/flaming/haven/Triggers
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
User=flaming

[Install]
WantedBy=multi-user.target
```

Note: `--port` is not specified, so the web interface uses the default **5004**.

Enable and start:
```bash
sudo systemctl enable osc_proxy.service
sudo systemctl start osc_proxy.service
sudo systemctl status osc_proxy.service
sudo journalctl -u osc_proxy.service -f
```

---

## Integration Examples

### Using with Max/MSP

```
[udpreceive 8000]
|
[OpenSoundControl]
|
[route /button/red /synth/volume]
```

### Using with Pure Data

```
[netreceive -u -b 8000]
|
[oscparse]
|
[route /button/red /synth/volume]
```

### Using with Python

```python
from pythonosc import dispatcher, osc_server

def handle_button(addr, value):
    print(f"Button: {value}")

d = dispatcher.Dispatcher()
d.map("/button/red", handle_button)

server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 8000), d)
server.serve_forever()
```

---

## Security Considerations

1. The web interface has no authentication — use a reverse proxy with auth for public access
2. The socket server and web interface listen on all interfaces (`0.0.0.0`) — restrict in production
3. OSC uses UDP (connectionless) — ensure your network is trusted

---

## Related Files

- `osc_proxy.py` — main server
- `osc_proxy.html` — web interface
- `osc_proxy_config.json` — configuration (auto-created)
- `osc_proxy.service` — systemd unit file
- `trigger_gateway.py` — trigger gateway
- `scene_service.py` + `SCENE_SERVICE.md` — scene management
- `README_USAGE.md` — trigger system overview
- `TRIGGER_DISPATCH.md` — trigger dispatch documentation
