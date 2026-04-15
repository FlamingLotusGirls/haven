# Scene Management Service

A REST API service for managing scenes. Only one scene can be active at a time.
Scenes (and schedules) are persisted to `scenes.json` between reboots.

## Features

- Create and delete scenes
- List all scenes and query the active scene
- Set the active scene — fires a `SceneChange` trigger to all registered services
- **Scene scheduling** — activate a scene automatically at a specific time (daily or once)
- Persistent storage (survives reboots, atomic writes)
- Simple web UI at `/`
- REST API

## Running the Service

```bash
python3 scene_service.py
```

The service runs on **port 5003** by default.

### Custom Port

```bash
python3 scene_service.py --port 8080
# or
python3 scene_service.py -p 8080
```

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GATEWAY_URL` | `http://localhost:5002` | Trigger gateway — receives `SceneChange` events and device registration |
| `FLAME_SERVICE_URL` | `http://localhost:5001` | Flame service — polled by `/api/scene-status` |
| `OSC_PROXY_URL` | `http://localhost:5004` | OSC proxy — polled by `/api/scene-status` |
| `MURMURA_URL` | `http://localhost:8765` | Sound service — linked in `/api/scene-status` (not polled) |

---

## API Endpoints

### Scenes

#### Create a Scene

```
POST /api/scenes
Content-Type: application/json

{"name": "performance"}
```

Response `201`:
```json
{"message": "Scene 'performance' created", "scene": "performance"}
```

#### Delete a Scene

```
DELETE /api/scenes/<name>
```

The currently active scene cannot be deleted (returns `400`).

```bash
curl -X DELETE http://localhost:5003/api/scenes/performance
```

#### Get All Scenes

```
GET /api/scenes
```

Response `200`:
```json
{
  "scenes": ["idle", "performance", "show"],
  "active_scene": "performance",
  "count": 3
}
```

#### Set Active Scene

```
POST /api/scenes/active
Content-Type: application/json

{"name": "show"}
```

Response `200`:
```json
{"message": "Active scene set to 'show'", "active_scene": "show"}
```

Setting `"name": null` clears the active scene.

When the active scene changes, the service immediately POSTs a `SceneChange` trigger
to the trigger gateway (non-blocking background thread), so all subscribed services
update without polling.

#### Get Active Scene

```
GET /api/scenes/active
```

Response `200`:
```json
{"active_scene": "show"}
```

---

### Schedules

Schedules activate a scene automatically at a specific time of day.

#### List Schedules

```
GET /api/schedules
```

Response `200`:
```json
{
  "schedules": [
    {
      "id": "b3d2…",
      "scene": "daytime",
      "time": "08:00",
      "repeat": "daily",
      "created": "2026-04-13T09:00:00",
      "last_fired": null
    }
  ]
}
```

#### Create a Schedule

```
POST /api/schedules
Content-Type: application/json

{"scene": "daytime", "time": "08:00", "repeat": "daily"}
```

| Field | Values | Required |
|---|---|---|
| `scene` | must be an existing scene name | ✓ |
| `time` | `"HH:MM"` 24-hour local time | ✓ |
| `repeat` | `"daily"` or `"once"` | ✓ |

Response `201`:
```json
{
  "message": "Schedule created",
  "schedule": {"id": "b3d2…", "scene": "daytime", "time": "08:00", "repeat": "daily", …}
}
```

One-shot (`"repeat": "once"`) schedules are automatically removed after they fire.

#### Update a Schedule

```
PUT /api/schedules/<id>
Content-Type: application/json

{"scene": "nighttime", "time": "20:00", "repeat": "daily"}
```

All three fields are required. `last_fired` is reset so the updated schedule can fire
at the new time.

Response `200`:
```json
{"message": "Schedule updated", "schedule": {…}}
```

#### Delete a Schedule

```
DELETE /api/schedules/<id>
```

Response `200`:
```json
{"message": "Schedule 'b3d2…' deleted"}
```

---

### Scene Status

```
GET /api/scene-status
```

Aggregates configuration for the current scene from the flame service and OSC proxy.
Useful for a dashboard showing what's configured for the active scene.

Response `200`:
```json
{
  "active_scene": "show",
  "flame_service": {
    "url": "http://localhost:5001",
    "reachable": true,
    "mappings": […],
    "configured": true
  },
  "osc_proxy": {
    "url": "http://localhost:5004",
    "reachable": true,
    "on_enter": […],
    "mappings": […],
    "description": "Main show scene",
    "configured": true
  },
  "murmura_url": "http://localhost:8765"
}
```

---

### Health Check

```
GET /health
```

Response `200`:
```json
{
  "status": "healthy",
  "service": "scene_service",
  "scenes_count": 3,
  "active_scene": "show",
  "schedules_count": 1
}
```

---

## Usage Examples

```bash
# Create scenes
curl -X POST http://localhost:5003/api/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "idle"}'

curl -X POST http://localhost:5003/api/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "daytime"}'

curl -X POST http://localhost:5003/api/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "show"}'

# List all scenes
curl http://localhost:5003/api/scenes | python3 -m json.tool

# Set active scene
curl -X POST http://localhost:5003/api/scenes/active \
  -H "Content-Type: application/json" \
  -d '{"name": "show"}'

# Get active scene
curl http://localhost:5003/api/scenes/active | python3 -m json.tool

# Schedule daytime scene at 08:00 every day
curl -X POST http://localhost:5003/api/schedules \
  -H "Content-Type: application/json" \
  -d '{"scene": "daytime", "time": "08:00", "repeat": "daily"}'

# Schedule show scene at 21:30, one time only
curl -X POST http://localhost:5003/api/schedules \
  -H "Content-Type: application/json" \
  -d '{"scene": "show", "time": "21:30", "repeat": "once"}'

# List schedules
curl http://localhost:5003/api/schedules | python3 -m json.tool

# Delete a schedule
curl -X DELETE http://localhost:5003/api/schedules/<id>

# Delete a scene
curl -X DELETE http://localhost:5003/api/scenes/idle
```

---

## Data Persistence

Scenes and schedules are stored in `scenes.json` (same directory as the service).
Writes are atomic (temp-file + rename) so a crash mid-write never corrupts the file.

**Example `scenes.json`:**
```json
{
  "scenes": ["idle", "daytime", "show"],
  "active_scene": "show",
  "schedules": [
    {
      "id": "b3d2…",
      "scene": "daytime",
      "time": "08:00",
      "repeat": "daily",
      "created": "2026-04-13T09:00:00",
      "last_fired": "2026-04-13T08:00:01"
    }
  ],
  "last_updated": "2026-04-13T08:00:01.123456"
}
```

---

## Error Handling

| Status | Meaning |
|---|---|
| `200 OK` | Successful operation |
| `201 Created` | Scene or schedule created |
| `400 Bad Request` | Invalid input, duplicate name, or attempting to delete the active scene |
| `404 Not Found` | Scene or schedule does not exist |

**Example error response:**
```json
{"error": "Scene 'unknown' does not exist"}
```

---

## Running as a Service

The `scene.service` systemd unit file:

```ini
[Unit]
Description=FLG Haven Scene Management Service
After=network-online.target trigger.service
Wants=network-online.target

[Service]
Environment="PYTHONPATH=/home/flaming/haven/util"
ExecStart=/usr/bin/python3 /home/flaming/haven/Triggers/scene_service.py
WorkingDirectory=/home/flaming/haven/Triggers
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5
User=flaming

[Install]
WantedBy=multi-user.target
```

Install and enable:
```bash
sudo systemctl enable scene.service
sudo systemctl start scene.service
sudo systemctl status scene.service
```

> **Note:** `After=trigger.service` is listed as a soft dependency. The scene service
> starts and serves requests immediately regardless; it retries gateway registration
> in the background (up to 30 attempts × 2 s) so a brief startup race is handled
> automatically.

---

## Integration

The scene service integrates with other Haven services:

- **Trigger Gateway** — registered as the `SceneService` device at startup
  (with background retry). Fires a `SceneChange` Discrete trigger on every active-scene
  change (manual *and* scheduled), so downstream services update without polling.
- **Flame Service** — trigger-to-flame-sequence mappings are organised by scene; the
  flame service subscribes to `SceneChange` via the gateway.
- **OSC Proxy** — per-scene `on_enter` sequences and trigger→OSC mappings.
- **Sound / Murmura** — can be linked from the scene service web UI.

Other services can query the active scene directly:
```bash
ACTIVE_SCENE=$(curl -s http://localhost:5003/api/scenes/active | jq -r '.active_scene')
echo "Current scene: $ACTIVE_SCENE"
```
