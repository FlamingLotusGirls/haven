# Scene Management Service

A simple REST API service for managing scenes. Only one scene can be active at a time.

## Features

- Create and delete scenes
- List all scenes
- Set and get the active scene
- Persistent storage (survives reboots)
- Simple REST API

## Running the Service

```bash
python3 scene_service.py
```

The service runs on **port 5003** by default.

### Custom Port

To run on a different port:

```bash
python3 scene_service.py --port 8080
# or
python3 scene_service.py -p 8080
```

### Command-Line Options

```bash
python3 scene_service.py --help
```

Options:
- `-p, --port PORT` - Port to run the service on (default: 5003)

## API Endpoints

### Create a Scene

```bash
POST /api/scenes
Content-Type: application/json

{
  "name": "performance"
}
```

**Response:**
```json
{
  "message": "Scene 'performance' created",
  "scene": "performance"
}
```

### Delete a Scene

```bash
DELETE /api/scenes/<name>
```

**Example:**
```bash
curl -X DELETE http://localhost:5003/api/scenes/performance
```

**Response:**
```json
{
  "message": "Scene 'performance' deleted"
}
```

### Get All Scenes

```bash
GET /api/scenes
```

**Response:**
```json
{
  "scenes": ["idle", "performance", "show"],
  "active_scene": "performance",
  "count": 3
}
```

### Set Active Scene

```bash
POST /api/scenes/active
Content-Type: application/json

{
  "name": "show"
}
```

**Response:**
```json
{
  "message": "Active scene set to 'show'",
  "active_scene": "show"
}
```

**To clear the active scene:**
```json
{
  "name": null
}
```

### Get Active Scene

```bash
GET /api/scenes/active
```

**Response:**
```json
{
  "active_scene": "show"
}
```

### Health Check

```bash
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "scene_service",
  "scenes_count": 3,
  "active_scene": "show"
}
```

## Usage Examples

### Create some scenes

```bash
# Create scenes
curl -X POST http://localhost:5003/api/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "idle"}'

curl -X POST http://localhost:5003/api/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "performance"}'

curl -X POST http://localhost:5003/api/scenes \
  -H "Content-Type: application/json" \
  -d '{"name": "show"}'
```

### List all scenes

```bash
curl http://localhost:5003/api/scenes | python3 -m json.tool
```

### Set active scene

```bash
curl -X POST http://localhost:5003/api/scenes/active \
  -H "Content-Type: application/json" \
  -d '{"name": "show"}'
```

### Get active scene

```bash
curl http://localhost:5003/api/scenes/active | python3 -m json.tool
```

### Delete a scene

```bash
curl -X DELETE http://localhost:5003/api/scenes/idle
```

## Data Persistence

Scenes are stored in `scenes.json` in the same directory as the service. This file is automatically created and updated when scenes are created, deleted, or the active scene changes.

**Example `scenes.json`:**
```json
{
  "scenes": [
    "idle",
    "performance",
    "show"
  ],
  "active_scene": "show",
  "last_updated": "2026-01-24T17:43:00.123456"
}
```

## Error Handling

The API returns appropriate HTTP status codes:

- **200 OK**: Successful operation
- **201 Created**: Scene successfully created
- **400 Bad Request**: Invalid input or scene already exists
- **404 Not Found**: Scene doesn't exist

**Example error response:**
```json
{
  "error": "Scene 'unknown' does not exist"
}
```

## Running as a Service

To run as a systemd service, install `scene.service` to `/etc/systemd/system/scene.service`:

```ini
[Unit]
Description=FLG Haven Scene Management Service
After=network-online.target
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

Then enable and start:
```bash
sudo systemctl enable scene.service
sudo systemctl start scene.service
sudo systemctl status scene.service
```

## Integration

The scene service integrates with other Haven services to change behavior based on the current scene:

- **Trigger Gateway** — registered as the `SceneService` device; fires a `SceneChange` Discrete trigger whenever the active scene changes.
- **Flame Service** — trigger-to-flame-sequence mappings can be filtered by scene.
- **OSC Proxy** — per-scene `on_enter` sequences and trigger→OSC mappings.
- **Sound / Murmura** — can be linked from the scene service web UI.

Other services can query the active scene:
```bash
ACTIVE_SCENE=$(curl -s http://localhost:5003/api/scenes/active | jq -r '.active_scene')
echo "Current scene: $ACTIVE_SCENE"
```
