# Haven Trigger Gateway - Usage Guide

## Overview

The Trigger Gateway is the central hub for the Haven trigger system. It does three things:

1. **Stores trigger definitions** — a catalogue of every named trigger (On/Off, OneShot,
   Discrete, Continuous) and which physical device produces it
2. **Receives trigger events** — devices POST to `/api/trigger-event` when something
   happens; the gateway validates the event and forwards it to all registered services
3. **Dispatches to subscribers** — services (OSC Proxy, Flame Controller, etc.) register
   a persistent TCP socket connection; the gateway pushes every event to them in real time

## Architecture

```
Physical Devices                 Trigger Gateway              Consumer Services
(ESP32, Telephone, etc.)         (Port 5002)                 (Port 5100, etc.)

[Device] ──register-device──▶  [ /api/register-device ]
[Device] ──trigger-event────▶  [ /api/trigger-event   ] ──TCP push──▶ [OSC Proxy]
                                                          ──TCP push──▶ [Flame Ctrl]
[Service]──register─────────▶  [ /api/register        ]
```

## Installation

```bash
pip install -r requirements.txt
```

## Running the Gateway

```bash
python trigger_gateway.py
```

Default port: **5002**. Custom port:

```bash
python trigger_gateway.py --port 5002
```

## Web Interface

Open `http://localhost:5002` to:

- View the recent trigger event log
- See all registered trigger definitions and their `online`/`offline` status
- Inspect which services are registered and connected
- Enable / disable forwarding
- Manually add, edit, or delete trigger definitions

---

## How Devices Integrate

### Step 1: Register the device and its triggers

On startup, a device POSTs its trigger list to `/api/register-device`. The gateway
creates or updates each trigger in `trigger_config.json` and records `last_seen`.

```
POST /api/register-device
Content-Type: application/json

{
  "name": "TouchToneTelephone",
  "ip":   "192.168.1.42",
  "triggers": [
    {"name": "TouchToneTelephone.Button_1", "type": "On/Off"},
    {"name": "TouchToneTelephone.Dial",     "type": "Discrete",
     "range": {"values": [0,1,2,3,4,5,6,7,8,9]}}
  ]
}
```

Response `200`:
```json
{
  "message": "Device registered successfully",
  "device": "TouchToneTelephone",
  "ip": "192.168.1.42",
  "triggers_created": ["TouchToneTelephone.Button_1"],
  "triggers_updated": ["TouchToneTelephone.Dial"]
}
```

Devices should call this endpoint every time they boot (and optionally periodically to
keep `last_seen` fresh). A trigger is shown as `online` in the web UI if it has been
seen within the last 5 minutes.

### Step 2: Send trigger events

When a button is pressed, a dial changes, etc., POST to `/api/trigger-event`:

```
POST /api/trigger-event
Content-Type: application/json

{"name": "TouchToneTelephone.Button_1", "value": 1}
```

Optional fields:

| Field | Description |
|---|---|
| `value` | Current state or value (omit for OneShot triggers) |
| `id` | Device-assigned event ID for deduplication |

The gateway validates that the trigger name exists, caches the value (for non-OneShot
triggers), records it in the rolling log, and dispatches to all registered services.

Response `200`:
```json
{
  "message": "Trigger event received and dispatched",
  "event": {"name": "TouchToneTelephone.Button_1", "value": 1, "timestamp": "…"},
  "dispatched_to": 2,
  "forwarded": true
}
```

> **Note:** The gateway will return `404` if the trigger name is not in
> `trigger_config.json`. Devices must call `/api/register-device` first.

### Step 3: Status-only updates (no dispatch)

Devices can also update the cached state without triggering downstream action — useful
for heartbeats or periodic state sync that should not cause re-processing:

```
POST /api/trigger-status
Content-Type: application/json

{"name": "TouchToneTelephone.Button_1", "value": 0, "id": 42}
```

This updates the in-memory cache only. OneShot triggers are not cached.

---

## How Services Integrate

### Register to receive trigger events

Services register a persistent TCP socket connection. The gateway connects to them
and keeps the connection open, pushing events in real time.

```
POST /api/register
Content-Type: application/json

{
  "name":     "OSC_Proxy",
  "host":     "localhost",
  "port":     5100,
  "protocol": "TCP_SOCKET"
}
```

Supported protocols:

| Protocol | Description |
|---|---|
| `TCP_SOCKET` | Persistent connection (recommended). Gateway connects once and keeps it open. |
| `TCP_CONNECT` | Per-event connection. Gateway opens a new TCP connection for each event. |

On `TCP_SOCKET` registration, the gateway immediately tries to connect to the service.
If the service restarts and re-registers, the gateway closes the old socket and opens a
fresh one.

Each dispatched event is a newline-terminated JSON object:

```json
{"name": "TouchToneTelephone.Button_1", "value": 1, "timestamp": "2026-04-13T09:00:00.123"}\n
```

### Unregister

```
DELETE /api/register/<service_name>
```

Services should call this on clean shutdown; the gateway closes the socket.

---

## API Reference

### Trigger Definitions

#### Get All Triggers
```
GET /api/triggers
```
Returns all trigger definitions with computed `device_status` (`"online"` / `"offline"`):
```json
{
  "triggers": [
    {
      "name": "TouchToneTelephone.Button_1",
      "type": "On/Off",
      "device": "TouchToneTelephone",
      "device_ip": "192.168.1.42",
      "last_seen": "2026-04-13T09:00:00",
      "device_status": "online"
    }
  ],
  "last_modified": "2026-04-13T09:00:01"
}
```

#### Get Specific Trigger
```
GET /api/triggers/<trigger_name>
```

#### Add Trigger (manual)
```
POST /api/triggers
Content-Type: application/json

{"name": "ManualButton", "type": "OneShot"}
```
Response `201`.

#### Update Trigger
```
PUT /api/triggers/<trigger_name>
Content-Type: application/json

{"name": "ManualButton", "type": "On/Off"}
```

#### Delete Trigger
```
DELETE /api/triggers/<trigger_name>
```

#### Get Valid Trigger Types
```
GET /api/trigger-types
```
```json
{"types": ["On/Off", "OneShot", "Discrete", "Continuous"]}
```

---

### Trigger Events and Status

#### Fire a Trigger Event (dispatches to services)
```
POST /api/trigger-event
Content-Type: application/json

{"name": "RedButton", "value": 1}
```

#### Update Cached Status (no dispatch)
```
POST /api/trigger-status
Content-Type: application/json

{"name": "RedButton", "value": 0, "id": 7}
```

#### Get All Cached Trigger Values
```
GET /api/trigger-status
```
```json
{
  "triggers": {
    "RedButton": {"value": 0, "type": "On/Off", "timestamp": "…", "id": 7}
  },
  "count": 1
}
```

---

### Trigger Log

#### Get Recent Events
```
GET /api/trigger-log
GET /api/trigger-log?minutes=10&limit=200
```
Returns events newest-first. Default: last 10 minutes, up to 200 entries.
```json
{
  "events": [
    {"timestamp": "…", "name": "RedButton", "value": 1, "forwarded": true}
  ],
  "total": 1,
  "minutes": 10
}
```

#### Clear Log
```
DELETE /api/trigger-log
```

---

### Forwarding Control

Forwarding can be disabled to suppress all dispatch (useful during maintenance or testing).
Events are still received and logged; they are just not sent to registered services.

#### Get Forwarding State
```
GET /api/forwarding
```
```json
{"enabled": true}
```

#### Set Forwarding State
```
POST /api/forwarding
Content-Type: application/json

{"enabled": false}
```
```json
{"enabled": false, "message": "Forwarding disabled"}
```

---

### Service Registry

#### Register a Service
```
POST /api/register
Content-Type: application/json

{"name": "OSC_Proxy", "host": "localhost", "port": 5100, "protocol": "TCP_SOCKET"}
```

#### Unregister a Service
```
DELETE /api/register/<service_name>
```

#### List All Registered Services
```
GET /api/services
```
```json
{
  "services": [
    {
      "name": "OSC_Proxy",
      "host": "localhost",
      "port": 5100,
      "protocol": "TCP_SOCKET",
      "registered_at": "…",
      "socket_connected": true
    }
  ]
}
```

#### Device Registration
```
POST /api/register-device
```
See [How Devices Integrate](#how-devices-integrate) above.

---

## Trigger Types

| Type | Description | Value |
|---|---|---|
| `On/Off` | Binary state (pressed / released) | `0` or `1` |
| `OneShot` | Single event, no persistent state | *(no value)* |
| `Discrete` | One of a fixed set of values | integer from the defined set or range |
| `Continuous` | Smooth range | float within `min`…`max` |

### Trigger Definition Examples

```json
{"name": "RedButton",    "type": "On/Off"}

{"name": "FireButton",   "type": "OneShot"}

{"name": "Dial.Number",  "type": "Discrete",
 "range": {"values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]}}

{"name": "Switch.Pos",   "type": "Discrete",
 "range": {"min": 1, "max": 5}}

{"name": "Slider.Value", "type": "Continuous",
 "range": {"min": 0.0, "max": 1.0}}
```

---

## Trigger Naming Convention

- **Single-trigger device** — use the device name directly:
  `RedTelephone`

- **Multi-trigger device** — prefix with the device name:
  `RedTelephone.Button_1`, `RedTelephone.Dial`

The `device` field in the trigger record tracks which physical device owns the trigger.

---

## Configuration Files

| File | Purpose |
|---|---|
| `trigger_config.json` | Trigger definitions (name, type, range, device metadata) |
| `service_registrations.json` | Persisted service registrations (restored on restart) |

Both are in the same directory as `trigger_gateway.py` and are managed automatically.

---

## Running as a System Service

The `trigger.service` systemd unit file:

```ini
[Unit]
Description=FLG Haven Trigger Gateway
After=network-online.target
Wants=network-online.target

[Service]
Environment="PYTHONPATH=/home/flaming/haven/util"
ExecStart=/usr/bin/python3 /home/flaming/haven/Triggers/trigger_gateway.py
WorkingDirectory=/home/flaming/haven/Triggers
Restart=always
RestartSec=5
User=flaming

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable trigger.service
sudo systemctl start trigger.service
sudo systemctl status trigger.service
```

---

## Related Documentation

- `TRIGGER_DISPATCH.md` — detailed trigger dispatch internals
- `OSC_PROXY_README.md` — OSC Proxy integration
- `SCENE_SERVICE.md` — scene management and `SceneChange` trigger
- `MODE_SERVICE.md` — mode service integration
