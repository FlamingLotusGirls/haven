# Haven Trigger Dispatch - API Documentation

## Overview
The Trigger Server now supports service registration, trigger event dispatch, and trigger status caching with persistent TCP socket connections.

## Key Features

### 1. Persistent TCP Socket Connections
- For `TCP_SOCKET` protocol, the server establishes and maintains long-standing socket connections to registered services
- Automatic reconnection on socket failures
- Thread-safe socket management

### 2. ID-Based Caching
- Trigger events are cached using **ID** as the primary identifier (not timestamp)
- Important for environments without internet access where system clocks may not be synchronized
- Timestamp is kept for debugging but ID is the key field

## Service Registration

### Register a Service
Register your service to receive trigger events from the Trigger Server.

**Endpoint:** `POST /api/register`

**Request Body:**
```json
{
  "name": "FlameServer",
  "port": 6000,
  "host": "localhost",  // Optional, defaults to "localhost"
  "protocol": "TCP_SOCKET"  // Optional: "TCP_SOCKET", "TCP_CONNECT", "OPC". Defaults to "TCP_SOCKET"
}
```

**Response:**
```json
{
  "message": "Service registered successfully",
  "registration": {
    "name": "FlameServer",
    "port": 6000,
    "host": "localhost",
    "protocol": "TCP_SOCKET",
    "registered_at": "2026-01-11T18:30:00",
    "socket_status": "connected"
  }
}
```

**Protocols:**
- **TCP_SOCKET**: Persistent socket connection (recommended). Server establishes connection immediately and maintains it.
- **TCP_CONNECT**: New connection per event. Server creates a new socket for each trigger event.
- **OPC**: Placeholder for future OPC protocol support.

**Notes:**
- For `TCP_SOCKET`, the server will immediately attempt to establish a persistent connection
- If connection fails, registration will fail with 500 error
- Your service must have a listening socket ready at the specified port before registering

### Unregister a Service
**Endpoint:** `DELETE /api/register/<service_name>`

**Response:**
```json
{
  "message": "Service unregistered successfully"
}
```

### Get All Registrations
**Endpoint:** `GET /api/registrations`

**Response:**
```json
{
  "services": [
    {
      "name": "FlameServer",
      "port": 6000,
      "host": "localhost",
      "protocol": "TCP_SOCKET",
      "registered_at": "2026-01-11T18:30:00",
      "socket_connected": true
    }
  ]
}
```

## Device Registration

### Register a Device
Devices can auto-register themselves with the Trigger Server, automatically creating and updating their trigger definitions.

**Endpoint:** `POST /api/register-device`

**Request Body:**
```json
{
  "name": "RedTelephone",
  "ip": "192.168.1.100",
  "triggers": [
    {
      "name": "Button_1",
      "type": "On/Off"
    },
    {
      "name": "Button_2",
      "type": "OneShot"
    },
    {
      "name": "Dial",
      "type": "Discrete",
      "range": {
        "values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
      }
    }
  ]
}
```

**Response:**
```json
{
  "message": "Device registered successfully",
  "device": "RedTelephone",
  "ip": "192.168.1.100",
  "triggers_created": ["Button_2"],
  "triggers_updated": ["Button_1", "Dial"]
}
```

**Behavior:**
1. Creates triggers in the format `{device_name}.{trigger_name}` (e.g., `RedTelephone.Button_1`)
2. If trigger already exists, updates it with new metadata
3. Adds device metadata to each trigger:
   - `device`: Device name
   - `device_ip`: Device IP address
   - `last_seen`: Current timestamp (for device health monitoring)
4. Preserves `manually_edited` flag if trigger was previously edited manually
5. Returns list of created and updated triggers

**Trigger Naming:**
- Single trigger device: `{device_name}` (e.g., `RedTelephone`)
- Multi-trigger device: `{device_name}.{trigger_name}` (e.g., `RedTelephone.Button_1`)

**Device Health Monitoring:**
- Each registration updates the `last_seen` timestamp
- Devices should register periodically (e.g., on startup and every 5 minutes)
- Triggers show as "online" if seen within last 5 minutes, "offline" otherwise

**Trigger Types:**
- **On/Off**: Binary state (no range needed)
- **OneShot**: Single event (no range needed)
- **Discrete**: Integer values with either:
  - `values`: Array of valid values (e.g., `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`)
  - `min` and `max`: Range of valid values (e.g., `{"min": 1, "max": 5}`)
- **Continuous**: Float values with `min` and `max` (e.g., `{"min": 0.0, "max": 1.0}`)

**Example: ESP32/Arduino Device Registration**
```cpp
#include <HTTPClient.h>
#include <ArduinoJson.h>

void registerDevice() {
  HTTPClient http;
  http.begin("http://192.168.1.10:5002/api/register-device");
  http.addHeader("Content-Type", "application/json");
  
  StaticJsonDocument<512> doc;
  doc["name"] = "RedTelephone";
  doc["ip"] = WiFi.localIP().toString();
  
  JsonArray triggers = doc.createNestedArray("triggers");
  
  JsonObject button1 = triggers.createNestedObject();
  button1["name"] = "Button_1";
  button1["type"] = "On/Off";
  
  JsonObject dial = triggers.createNestedObject();
  dial["name"] = "Dial";
  dial["type"] = "Discrete";
  JsonObject dialRange = dial.createNestedObject("range");
  JsonArray dialValues = dialRange.createNestedArray("values");
  for (int i = 0; i <= 9; i++) {
    dialValues.add(i);
  }
  
  String jsonPayload;
  serializeJson(doc, jsonPayload);
  
  int httpCode = http.POST(jsonPayload);
  
  if (httpCode == 200) {
    Serial.println("Device registered successfully");
  } else {
    Serial.printf("Registration failed: %d\n", httpCode);
  }
  
  http.end();
}
```

**Example: Python Device Registration**
```python
import requests
import json

def register_device(server_url, device_name, ip_address, triggers):
    """Register device with trigger server."""
    data = {
        "name": device_name,
        "ip": ip_address,
        "triggers": triggers
    }
    
    response = requests.post(
        f"{server_url}/api/register-device",
        json=data
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"Device registered: {result['device']}")
        print(f"  Created: {result['triggers_created']}")
        print(f"  Updated: {result['triggers_updated']}")
    else:
        print(f"Registration failed: {response.status_code}")
        print(response.text)

# Example usage
triggers = [
    {"name": "Button_1", "type": "On/Off"},
    {"name": "Button_2", "type": "OneShot"},
    {
        "name": "Slider",
        "type": "Continuous",
        "range": {"min": 0.0, "max": 1.0}
    }
]

register_device(
    "http://192.168.1.10:5002",
    "TestDevice",
    "192.168.1.100",
    triggers
)
```

**Best Practices:**
1. Register on device startup
2. Re-register periodically (every 5 minutes) to update `last_seen`
3. Use descriptive trigger names (e.g., `Button_Red`, `Dial_Phone`)
4. Include all triggers in each registration (even if unchanged)
5. Use consistent trigger types across registrations

**Error Responses:**
- 400: Missing required fields or invalid trigger data
- 500: Failed to save configuration

## Trigger Events

### Send a Trigger Event (from Device)
Devices send trigger events to the server, which validates, caches, and dispatches to all registered services.

**Endpoint:** `POST /api/trigger-event`

**Request Body:**
```json
{
  "name": "RedTelephone.Button_1",
  "value": "On",  // Optional: not needed for OneShot triggers
  "id": 12345     // Optional but HIGHLY RECOMMENDED: primary identifier
}
```

**Response:**
```json
{
  "message": "Trigger event received and dispatched",
  "event": {
    "name": "RedTelephone.Button_1",
    "value": "On",
    "id": 12345,
    "timestamp": "2026-01-11T18:35:00"
  },
  "dispatched_to": 2
}
```

**Behavior:**
1. Validates trigger exists in configuration (returns 404 if not found)
2. Caches the event with ID (except for OneShot triggers)
3. Dispatches to all registered services via their specified protocol
4. For TCP_SOCKET services, uses persistent socket (with auto-reconnect on failure)

**Event Format Sent to Services:**
Services receive events as JSON with newline delimiter:
```json
{"name": "RedTelephone.Button_1", "value": "On", "id": 12345, "timestamp": "2026-01-11T18:35:00"}\n
```

### Send Trigger Status Update (from Device)
Status updates only update the cache - they are NOT dispatched to services. Used for startup synchronization.

**Endpoint:** `POST /api/trigger-status`

**Request Body:**
```json
{
  "name": "RedTelephone.Button_1",
  "value": "Off",
  "id": 12340 
}
```

**Response:**
```json
{
  "message": "Trigger status updated",
  "trigger": "RedTelephone.Button_1",
  "value": "Off",
  "id": 12340
}
```

**Use Cases:**
- Device startup: send current state without triggering actions
- Periodic heartbeat: update server with current state
- Recovery: resynchronize state after connection loss

### Get Current Trigger Status
Query the current cached values for all triggers.

**Endpoint:** `GET /api/trigger-status`

**Response:**
```json
{
  "triggers": {
    "RedTelephone.Button_1": {
      "value": "On",
      "id": 12345,
      "timestamp": "2026-01-11T18:35:00",
      "type": "On/Off"
    },
    "Dial.Number": {
      "value": 5,
      "id": 12346,
      "timestamp": "2026-01-11T18:36:00",
      "type": "Discrete"
    }
  },
  "count": 2
}
```

## Implementation Example: Service Listener

Here's a simple Python service that listens for trigger events:

```python
import socket
import json

def listen_for_triggers(port=6000):
    """
    Simple trigger event listener for TCP_SOCKET protocol.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('localhost', port))
    server_socket.listen(5)
    
    print(f"Listening for trigger events on port {port}...")
    
    while True:
        client_socket, address = server_socket.accept()
        print(f"Connection from {address}")
        
        # Handle connection
        buffer = ""
        while True:
            try:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                
                # Process complete messages (newline-delimited)
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line:
                        trigger_event = json.loads(line)
                        handle_trigger(trigger_event)
                        
            except Exception as e:
                print(f"Error: {e}")
                break

def handle_trigger(event):
    """Process received trigger event."""
    print(f"Received trigger: {event['name']}")
    print(f"  Value: {event.get('value', 'N/A')}")
    print(f"  ID: {event.get('id', 'N/A')}")
    print(f"  Timestamp: {event.get('timestamp', 'N/A')}")
    
    # Your trigger handling logic here
    # e.g., start a flame program, play sound, control lights

if __name__ == '__main__':
    listen_for_triggers()
```

## Implementation Example: Device

Here's how a device would send trigger events:

```python
import requests
import json

TRIGGER_SERVER = "http://localhost:5001"

def send_trigger_event(name, value=None, event_id=None):
    """Send a trigger event to the server."""
    data = {"name": name}
    
    if value is not None:
        data["value"] = value
    
    if event_id is not None:
        data["id"] = event_id
    
    response = requests.post(
        f"{TRIGGER_SERVER}/api/trigger-event",
        json=data
    )
    
    return response.json()

def send_trigger_status(name, value, event_id=None):
    """Send a status update (no dispatch)."""
    data = {
        "name": name,
        "value": value
    }
    
    if event_id is not None:
        data["id"] = event_id
    
    response = requests.post(
        f"{TRIGGER_SERVER}/api/trigger-status",
        json=data
    )
    
    return response.json()

# Example usage
if __name__ == '__main__':
    # Send status on startup
    send_trigger_status("RedTelephone.Button_1", "Off", event_id=1000)
    
    # Send trigger event when button pressed
    send_trigger_event("RedTelephone.Button_1", "On", event_id=1001)
    
    # Send another event when released
    send_trigger_event("RedTelephone.Button_1", "Off", event_id=1002)
```

## Error Handling

### Trigger Not Found (404)
If a trigger event is sent for a trigger not in the configuration:
```json
{
  "error": "Trigger 'UnknownTrigger' not found in configuration"
}
```

The server logs this error and does NOT forward the event to services.

### Socket Connection Failed (500)
If TCP_SOCKET registration fails to establish connection:
```json
{
  "error": "Failed to establish socket connection to localhost:6000"
}
```

### Automatic Reconnection
For TCP_SOCKET services:
- If a socket breaks during event dispatch, the server automatically attempts to reconnect
- If reconnection succeeds, the event is delivered
- If reconnection fails, an error is logged but dispatch continues to other services

## Cache Behavior

### What Gets Cached
- **On/Off** triggers: value and ID
- **Discrete** triggers: value and ID  
- **Continuous** triggers: value and ID
- **OneShot** triggers: NOT cached (no persistent state)

### Cache Fields
```json
{
  "value": <trigger value>,
  "id": <event id>,           // Primary identifier
  "timestamp": <ISO 8601>,     // Secondary, for debugging
  "type": <trigger type>
}
```

### Cache Updates
- Updated on `/api/trigger-event` (with dispatch)
- Updated on `/api/trigger-status` (no dispatch)
- Retrieved via `/api/trigger-status` GET

## Server Startup Behavior

On startup, the server:
1. Loads trigger configuration from `trigger_config.json`
2. Loads service registrations from `service_registrations.json`
3. Re-establishes TCP_SOCKET connections to all registered services
4. Logs connection status for each service

This ensures persistent services remain registered across server restarts.
