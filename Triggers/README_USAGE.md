# Haven Trigger Server - Usage Guide

## Overview
The Haven Trigger Server is a simple Python web server that manages trigger configurations via a REST API and web interface. It stores trigger configurations in a JSON file and provides endpoints for other services (flame, sound, light) to retrieve trigger definitions.

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Running the Server

Start the server:
```bash
python server.py
```

The server will start on `http://localhost:5000`

## Web Interface

Open your browser to `http://localhost:5000` to access the web interface where you can:
- Add new triggers
- Edit existing triggers
- Delete triggers
- View all configured triggers

## REST API Endpoints

### Get All Triggers
```
GET /api/triggers
```
Returns all triggers and metadata.

Response:
```json
{
  "triggers": [
    {
      "name": "RedTelephone.Button_1",
      "type": "On/Off"
    }
  ],
  "last_modified": "2026-01-10T17:00:00"
}
```

### Get Specific Trigger
```
GET /api/triggers/<trigger_name>
```
Returns a specific trigger by name.

### Add New Trigger
```
POST /api/triggers
Content-Type: application/json

{
  "name": "RedTelephone.Button_1",
  "type": "On/Off"
}
```

### Update Trigger
```
PUT /api/triggers/<trigger_name>
Content-Type: application/json

{
  "name": "RedTelephone.Button_1",
  "type": "OneShot"
}
```

### Delete Trigger
```
DELETE /api/triggers/<trigger_name>
```

### Get Available Trigger Types
```
GET /api/trigger-types
```
Returns the list of valid trigger types.

## Trigger Types

1. **On/Off** - Binary state trigger (on or off)
2. **OneShot** - Single event trigger
3. **Discrete** - Discrete values (requires range)
4. **Continuous** - Continuous values (requires range)

## Trigger Definition Examples

### On/Off Trigger
```json
{
  "name": "RedTelephone",
  "type": "On/Off"
}
```

### Discrete Trigger with Values
```json
{
  "name": "Dial.Number",
  "type": "Discrete",
  "range": {
    "values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
  }
}
```

### Discrete Trigger with Range
```json
{
  "name": "Switch.Position",
  "type": "Discrete",
  "range": {
    "min": 1,
    "max": 5
  }
}
```

### Continuous Trigger
```json
{
  "name": "Slider.Value",
  "type": "Continuous",
  "range": {
    "min": 0.0,
    "max": 1.0
  }
}
```

## Trigger Naming Convention

- **Single trigger device**: Use the device name as the trigger name
  - Example: `RedTelephone`

- **Multiple trigger device**: Prefix with device name
  - Example: `RedTelephone.Button_1`, `RedTelephone.Button_2`

## Configuration File

Triggers are stored in `trigger_config.json` in the same directory as the server. This file is automatically created when the first trigger is added.

## Integration with Other Services

Other services (Flame Server, Sound Server, Light Server) can retrieve trigger configurations by making GET requests to `/api/triggers`. They should poll this endpoint periodically or implement a refresh mechanism to stay updated with trigger configuration changes.

Example integration code:
```python
import requests

# Get all triggers
response = requests.get('http://localhost:5000/api/triggers')
triggers = response.json()['triggers']

# Process triggers for your service
for trigger in triggers:
    print(f"Trigger: {trigger['name']}, Type: {trigger['type']}")
```
