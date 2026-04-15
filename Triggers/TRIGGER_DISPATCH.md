# Haven Trigger Dispatch - Technical Reference

## Overview

The Trigger Gateway supports service registration, trigger event dispatch, and
trigger status caching with persistent TCP socket connections.

This document focuses on the dispatch mechanics. For a higher-level overview see
`TRIGGERS_USAGE.md`; for service-specific integration see `OSC_PROXY_README.md` and
`SCENE_SERVICE.md`.

---

## Key Design Decisions

### Persistent TCP Socket Connections

For `TCP_SOCKET` protocol, the gateway establishes a long-standing connection to the
service at registration time and keeps it open. Each trigger event is written to the
socket as a newline-terminated JSON line. Thread-safe locking ensures concurrent
dispatches to the same service are serialised.

On send failure the gateway automatically attempts to reconnect and retry once.

### ID-Based Caching

Trigger events are cached using **`id`** as the primary identifier (not `timestamp`).
This is important for Haven deployments without internet access where system clocks may
not be synchronised across devices. Timestamps are still recorded for debugging.

### Forwarding Control

All trigger events are received, logged, and cached regardless of the forwarding state.
Dispatch to registered services can be enabled/disabled independently — useful for
maintenance, testing, or startup sequencing.

---

## Service Registration

### Register a Service

Register your service to receive trigger events.

```
POST /api/register
Content-Type: application/json

{
  "name":     "FlameServer",
  "port":     6000,
  "host":     "localhost",    // optional, default "localhost"
  "protocol": "TCP_SOCKET"   // optional, default "TCP_SOCKET"
}
```

**Supported protocols:**

| Protocol | Description |
|---|---|
| `TCP_SOCKET` | Persistent connection (recommended). Gateway connects immediately and keeps the socket open. Re-registration closes the old socket and opens a fresh one. |
| `TCP_CONNECT` | Per-event connection. Gateway opens a new TCP socket for each trigger event. |

For `TCP_SOCKET`, the service must have a listening socket ready before calling
`/api/register`. If the connection cannot be established, registration returns `500`.

Response `200`:
```json
{
  "message": "Service registered successfully",
  "registration": {
    "name": "FlameServer",
    "port": 6000,
    "host": "localhost",
    "protocol": "TCP_SOCKET",
    "registered_at": "2026-04-13T09:00:00",
    "socket_status": "connected"
  }
}
```

### Unregister a Service

```
DELETE /api/register/<service_name>
```

Services should call this on clean shutdown; the gateway closes the socket.

### List All Registered Services

```
GET /api/services
```

```json
{
  "services": [
    {
      "name": "FlameServer",
      "port": 6000,
      "host": "localhost",
      "protocol": "TCP_SOCKET",
      "registered_at": "2026-04-13T09:00:00",
      "socket_connected": true
    }
  ]
}
```

`socket_connected` reflects whether the gateway currently has a live socket to the
service. A `false` here means events cannot be delivered until the service re-registers.

---

## Device Registration

### Register a Device

```
POST /api/register-device
Content-Type: application/json

{
  "name": "RedTelephone",
  "ip":   "192.168.1.100",
  "triggers": [
    {"name": "RedTelephone.Button_1", "type": "On/Off"},
    {"name": "RedTelephone.Button_2", "type": "OneShot"},
    {
      "name": "RedTelephone.Dial",
      "type": "Discrete",
      "range": {"values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]}
    }
  ]
}
```

> **Note on naming:** Trigger names are passed through exactly as provided — the gateway
> does **not** auto-prefix names with the device name. By convention, multi-trigger
> devices should use `DeviceName.TriggerName` format (e.g., `RedTelephone.Button_1`).
> Single-trigger devices can use just the device name (e.g., `RedTelephone`).

Response `200`:
```json
{
  "message": "Device registered successfully",
  "device": "RedTelephone",
  "ip": "192.168.1.100",
  "triggers_created": ["RedTelephone.Button_2"],
  "triggers_updated": ["RedTelephone.Button_1", "RedTelephone.Dial"]
}
```

**Behaviour:**
- Creates new triggers or updates existing ones in `trigger_config.json`
- Stamps `last_seen` on every trigger in the registration
- Preserves the `manually_edited` flag so hand-edited definitions survive re-registration
- A trigger is shown as `online` in the web UI if `last_seen` is within the last 5 minutes

**Best practices:**
1. Call on every device boot to ensure `trigger_config.json` is current
2. Re-register periodically (every 5 minutes) to keep `last_seen` fresh
3. Always include all triggers, even unchanged ones

**Error responses:** `400` (missing fields / invalid trigger data), `500` (save failure)

### ESP32/Arduino Example

```cpp
#include <HTTPClient.h>
#include <ArduinoJson.h>

void registerDevice() {
  HTTPClient http;
  http.begin("http://192.168.1.10:5002/api/register-device");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["name"] = "RedTelephone";
  doc["ip"]   = WiFi.localIP().toString();

  JsonArray triggers = doc.createNestedArray("triggers");

  JsonObject button1 = triggers.createNestedObject();
  button1["name"] = "RedTelephone.Button_1";
  button1["type"] = "On/Off";

  JsonObject dial = triggers.createNestedObject();
  dial["name"] = "RedTelephone.Dial";
  dial["type"] = "Discrete";
  JsonArray dialValues = dial.createNestedObject("range").createNestedArray("values");
  for (int i = 0; i <= 9; i++) dialValues.add(i);

  String payload;
  serializeJson(doc, payload);
  int code = http.POST(payload);
  Serial.printf("Registration: %d\n", code);
  http.end();
}
```

### Python Device Example

```python
import requests

def register_device(server_url, device_name, ip_address, triggers):
    response = requests.post(
        f"{server_url}/api/register-device",
        json={"name": device_name, "ip": ip_address, "triggers": triggers}
    )
    if response.status_code == 200:
        r = response.json()
        print(f"Registered {r['device']}: created={r['triggers_created']} updated={r['triggers_updated']}")
    else:
        print(f"Registration failed {response.status_code}: {response.text}")

GATEWAY = "http://192.168.1.10:5002"

register_device(GATEWAY, "RedTelephone", "192.168.1.100", [
    {"name": "RedTelephone.Button_1", "type": "On/Off"},
    {"name": "RedTelephone.Button_2", "type": "OneShot"},
    {"name": "RedTelephone.Slider",   "type": "Continuous", "range": {"min": 0.0, "max": 1.0}},
])
```

---

## Trigger Events

### Fire a Trigger Event

Validates the trigger, updates the cache, records in the rolling log, and dispatches
to all registered services (when forwarding is enabled).

```
POST /api/trigger-event
Content-Type: application/json

{
  "name":  "RedTelephone.Button_1",
  "value": 1,       // optional — omit for OneShot triggers
  "id":    12345    // optional but strongly recommended
}
```

Response `200`:
```json
{
  "message": "Trigger event received and dispatched",
  "event": {
    "name":      "RedTelephone.Button_1",
    "value":     1,
    "id":        12345,
    "timestamp": "2026-04-13T09:00:00.123"
  },
  "dispatched_to": 2,
  "forwarded": true
}
```

`forwarded: false` means forwarding is currently disabled — the event was logged and
cached but not sent to any registered services.

Returns `404` if the trigger name is not in `trigger_config.json`.

**Wire format sent to services (newline-delimited JSON):**
```json
{"name": "RedTelephone.Button_1", "value": 1, "id": 12345, "timestamp": "2026-04-13T09:00:00.123"}\n
```

### Status-Only Update (no dispatch)

Updates the in-memory cache without dispatching to any service. Use for startup
state sync or periodic heartbeats that should not cause downstream actions.

```
POST /api/trigger-status
Content-Type: application/json

{"name": "RedTelephone.Button_1", "value": 0, "id": 12340}
```

Response `200`:
```json
{"message": "Trigger status updated", "trigger": "RedTelephone.Button_1", "value": 0, "id": 12340}
```

OneShot triggers are not cached and return `400` if sent here.

### Get Cached Trigger Values

```
GET /api/trigger-status
```

```json
{
  "triggers": {
    "RedTelephone.Button_1": {
      "value":     0,
      "id":        12340,
      "timestamp": "2026-04-13T09:00:00",
      "type":      "On/Off"
    }
  },
  "count": 1
}
```

---

## Trigger Log

A rolling in-memory log of all received trigger events (newest-first).

### Get Recent Events

```
GET /api/trigger-log
GET /api/trigger-log?minutes=10&limit=200
```

Default: last 10 minutes, up to 200 entries.

```json
{
  "events": [
    {
      "timestamp": "2026-04-13T09:00:01",
      "name":      "RedTelephone.Button_1",
      "value":     1,
      "id":        12345,
      "forwarded": true
    }
  ],
  "total":   1,
  "minutes": 10
}
```

The `forwarded` field records whether the event was dispatched at the time it arrived.

### Clear Log

```
DELETE /api/trigger-log
```

---

## Forwarding Control

Forwarding can be disabled to suppress dispatch without stopping event reception.
Events are still received, cached, and logged while forwarding is off.

Typical uses:
- Disable during startup sequencing until all services are ready
- Disable during maintenance without losing event history

### Get Forwarding State

```
GET /api/forwarding
```

```json
{"enabled": true}
```

### Enable / Disable Forwarding

```
POST /api/forwarding
Content-Type: application/json

{"enabled": false}
```

```json
{"enabled": false, "message": "Forwarding disabled"}
```

---

## The SceneChange Trigger

`SceneChange` is a special Discrete trigger fired by the Scene Service whenever the
active scene changes. It is registered like any other device trigger (via
`/api/register-device` from the scene service) and dispatched to all registered
consumer services.

Consumer services (OSC Proxy, Flame Controller, etc.) handle `SceneChange` events to
update their active-scene state without polling the scene service directly.

**Event format:**
```json
{"name": "SceneChange", "value": "NightShow", "timestamp": "…"}
```

The `value` field is the new scene name as a string.

---

## Cache Behaviour

| Trigger type | Cached? | Cache updated by |
|---|---|---|
| `On/Off` | ✓ | `trigger-event`, `trigger-status` |
| `Discrete` | ✓ | `trigger-event`, `trigger-status` |
| `Continuous` | ✓ | `trigger-event`, `trigger-status` |
| `OneShot` | ✗ | — |

Cache entry fields:
```json
{
  "value":     <current value>,
  "id":        <event id>,      // primary identifier
  "timestamp": <ISO 8601>,      // for debugging
  "type":      <trigger type>
}
```

---

## Server Startup Behaviour

On startup the gateway:
1. Loads trigger definitions from `trigger_config.json`
2. Loads service registrations from `service_registrations.json`
3. Re-establishes `TCP_SOCKET` connections to all previously registered services
4. Starts with forwarding **enabled** (services will receive events as soon as connected)

Service registrations survive gateway restarts. Devices need to re-register on their
own restart to refresh `last_seen`.

---

## Error Reference

| Error | Status | Meaning |
|---|---|---|
| Trigger not found | `404` | Trigger name is not in `trigger_config.json` |
| Socket connection failed | `500` | Gateway could not connect to service at registration |
| Missing required field | `400` | `name`, `port`, or `triggers` array absent |
| Unknown protocol | `400` | Protocol not in `TCP_SOCKET`, `TCP_CONNECT` |

### Automatic Reconnection

For `TCP_SOCKET` services, if a send fails the gateway:
1. Attempts to reconnect
2. If reconnection succeeds, retries the send
3. If reconnection fails, logs an error and continues dispatching to other services

---

## Implementation Example: Service Listener

```python
import socket
import json
import threading

def listen_for_triggers(port=6000, on_trigger=None):
    """
    Minimal TCP_SOCKET trigger listener.
    on_trigger(event_dict) is called for each received event.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', port))
    srv.listen(5)
    print(f"Listening for trigger events on port {port}")

    def handle(conn, addr):
        print(f"Gateway connected from {addr}")
        buf = ""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data.decode('utf-8')
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    if line.strip():
                        event = json.loads(line)
                        if on_trigger:
                            on_trigger(event)
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            conn.close()
            print("Gateway disconnected")

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()


def handle_trigger(event):
    name  = event['name']
    value = event.get('value')
    eid   = event.get('id')
    print(f"Trigger: {name}  value={value}  id={eid}")
    # Your logic here: start flame program, play sound, etc.


if __name__ == '__main__':
    listen_for_triggers(port=6000, on_trigger=handle_trigger)
```

---

## Implementation Example: Device Sender

```python
import requests

GATEWAY = "http://localhost:5002"

def send_trigger(name, value=None, event_id=None):
    """Fire a trigger event (dispatches to services)."""
    data = {"name": name}
    if value is not None:     data["value"] = value
    if event_id is not None:  data["id"]    = event_id
    r = requests.post(f"{GATEWAY}/api/trigger-event", json=data, timeout=5)
    return r.json()

def send_status(name, value, event_id=None):
    """Update cached state without dispatching."""
    data = {"name": name, "value": value}
    if event_id is not None:  data["id"] = event_id
    r = requests.post(f"{GATEWAY}/api/trigger-status", json=data, timeout=5)
    return r.json()

if __name__ == '__main__':
    # On startup: sync state without triggering actions
    send_status("RedTelephone.Button_1", 0, event_id=1000)

    # Button pressed → dispatch to all services
    send_trigger("RedTelephone.Button_1", 1, event_id=1001)

    # Button released
    send_trigger("RedTelephone.Button_1", 0, event_id=1002)
```
