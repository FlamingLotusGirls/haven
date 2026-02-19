# Mode Management Service

A simple REST API service for managing modes. Only one mode can be active at a time.

## Features

- Create and delete modes
- List all modes
- Set and get the active mode
- Persistent storage (survives reboots)
- Simple REST API

## Running the Service

```bash
python3 mode_service.py
```

The service runs on **port 5003** by default.

### Custom Port

To run on a different port:

```bash
python3 mode_service.py --port 8080
# or
python3 mode_service.py -p 8080
```

### Command-Line Options

```bash
python3 mode_service.py --help
```

Options:
- `-p, --port PORT` - Port to run the service on (default: 5003)

## API Endpoints

### Create a Mode

```bash
POST /api/modes
Content-Type: application/json

{
  "name": "performance"
}
```

**Response:**
```json
{
  "message": "Mode 'performance' created",
  "mode": "performance"
}
```

### Delete a Mode

```bash
DELETE /api/modes/<name>
```

**Example:**
```bash
curl -X DELETE http://localhost:5003/api/modes/performance
```

**Response:**
```json
{
  "message": "Mode 'performance' deleted"
}
```

### Get All Modes

```bash
GET /api/modes
```

**Response:**
```json
{
  "modes": ["idle", "performance", "show"],
  "active_mode": "performance",
  "count": 3
}
```

### Set Active Mode

```bash
POST /api/modes/active
Content-Type: application/json

{
  "name": "show"
}
```

**Response:**
```json
{
  "message": "Active mode set to 'show'",
  "active_mode": "show"
}
```

**To clear the active mode:**
```json
{
  "name": null
}
```

### Get Active Mode

```bash
GET /api/modes/active
```

**Response:**
```json
{
  "active_mode": "show"
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
  "service": "mode_service",
  "modes_count": 3,
  "active_mode": "show"
}
```

## Usage Examples

### Create some modes

```bash
# Create modes
curl -X POST http://localhost:5003/api/modes \
  -H "Content-Type: application/json" \
  -d '{"name": "idle"}'

curl -X POST http://localhost:5003/api/modes \
  -H "Content-Type: application/json" \
  -d '{"name": "performance"}'

curl -X POST http://localhost:5003/api/modes \
  -H "Content-Type: application/json" \
  -d '{"name": "show"}'
```

### List all modes

```bash
curl http://localhost:5003/api/modes | python3 -m json.tool
```

### Set active mode

```bash
curl -X POST http://localhost:5003/api/modes/active \
  -H "Content-Type: application/json" \
  -d '{"name": "show"}'
```

### Get active mode

```bash
curl http://localhost:5003/api/modes/active | python3 -m json.tool
```

### Delete a mode

```bash
curl -X DELETE http://localhost:5003/api/modes/idle
```

## Data Persistence

Modes are stored in `modes.json` in the same directory as the service. This file is automatically created and updated when modes are created, deleted, or the active mode changes.

**Example `modes.json`:**
```json
{
  "modes": [
    "idle",
    "performance",
    "show"
  ],
  "active_mode": "show",
  "last_updated": "2026-01-24T17:43:00.123456"
}
```

## Error Handling

The API returns appropriate HTTP status codes:

- **200 OK**: Successful operation
- **201 Created**: Mode successfully created
- **400 Bad Request**: Invalid input or mode already exists
- **404 Not Found**: Mode doesn't exist

**Example error response:**
```json
{
  "error": "Mode 'unknown' does not exist"
}
```

## Running as a Service

To run as a systemd service, create `/etc/systemd/system/mode-service.service`:

```ini
[Unit]
Description=Mode Management Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/Triggers
ExecStart=/usr/bin/python3 /path/to/Triggers/mode_service.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start:
```bash
sudo systemctl enable mode-service
sudo systemctl start mode-service
sudo systemctl status mode-service
```

## Integration

The mode service can be integrated with other services to change behavior based on the current mode. For example:

- Trigger mappings could be mode-specific
- Flame patterns could change based on mode
- Different modes for setup, testing, and show

Other services can query the active mode:
```bash
ACTIVE_MODE=$(curl -s http://localhost:5003/api/modes/active | jq -r '.active_mode')
echo "Current mode: $ACTIVE_MODE"
```
