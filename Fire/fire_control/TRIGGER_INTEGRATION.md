# Trigger Integration for Flame Control

## Overview
This integration connects the Flame Control system with the Haven Trigger Server, allowing triggers from devices to automatically start flame sequences.

## Architecture

```
Device → Trigger Server (port 5002) → Flame Server (port 6000) → Flame Sequences
                                           ↓
                                  trigger_mappings.json
```

### Components

1. **Trigger Server** (`~/Devel/FLG/haven/Triggers`)
   - Manages trigger configurations
   - Maintains service registrations
   - Dispatches trigger events via persistent TCP sockets
   - Port: 5002

2. **Flame Server** (`~/Devel/FLG/Haven/Fire/fire_control`)
   - Manages flame sequences/patterns
   - Receives trigger events
   - Maps triggers to flame sequences
   - Port: 5001 (web), 6000 (trigger listener)

3. **trigger_integration.py**
   - Registers with Trigger Server (with automatic retry)
   - Listens for trigger events on port 6000
   - Maintains trigger-to-flame mappings
   - Validates mappings against available triggers
   - Prevents duplicate sequence execution

## Setup & Configuration

### Start Services

1. **Start Trigger Server** (Terminal 1):
```bash
cd ~/Devel/FLG/haven/Triggers
python server.py
```
Server runs on http://localhost:5002

2. **Start Flame Server** (Terminal 2):
```bash
cd ~/Devel/FLG/Haven/Fire/fire_control
python flames_webserver.py
```
Server runs on http://localhost:5001

The Flame Server will automatically:
- Attempt to register with Trigger Server
- Retry every 30 seconds if registration fails
- Establish persistent TCP socket connection
- Load existing trigger mappings from `trigger_mappings.json`

### Configuration Files

**trigger_mappings.json** - Stores trigger-to-flame mappings:
```json
{
  "mappings": [
    {
      "id": 1,
      "trigger_name": "RedTelephone.Button_1",
      "trigger_value": "On",
      "flame_sequence": "Firefly_3_chase",
      "allow_override": false
    }
  ]
}
```

## REST API Endpoints

### Check Integration Status
```bash
GET http://localhost:5001/trigger-integration/status
```

Returns:
```json
{
  "registered": true,
  "trigger_server_url": "http://localhost:5002",
  "listen_port": 6000,
  "mapping_count": 2,
  "available_triggers_count": 5
}
```

### Get Available Triggers
```bash
GET http://localhost:5001/trigger-integration/triggers
```

Returns triggers from Trigger Server (refreshed every 5 minutes).

### Get All Mappings
```bash
GET http://localhost:5001/trigger-integration/mappings
```

### Create New Mapping
```bash
POST http://localhost:5001/trigger-integration/mappings
Content-Type: application/x-www-form-urlencoded

trigger_name=RedTelephone.Button_1&trigger_value=On&flame_sequence=Firefly_3_chase&allow_override=false
```

Parameters:
- `trigger_name` (required): Name of the trigger
- `flame_sequence` (required): Name of the flame sequence to trigger
- `trigger_value` (optional): Specific value to match (e.g., "On", "Off", or numeric)
- `allow_override` (optional): true/false - whether to restart if sequence already active

### Update Mapping
```bash
PUT http://localhost:5001/trigger-integration/mappings/1
Content-Type: application/x-www-form-urlencoded

flame_sequence=NewSequence&allow_override=true
```

### Delete Mapping
```bash
DELETE http://localhost:5001/trigger-integration/mappings/1
```

## Mapping Behavior

### Trigger Value Matching
- If `trigger_value` is specified, the mapping only triggers when the trigger event's value matches
- If `trigger_value` is null/empty, the mapping triggers for any value
- Useful for On/Off triggers where you only want to trigger on "On"

### Duplicate Prevention
- Before triggering a sequence, checks if it's already active using `flames_controller.isFlameEffectActive()`
- **allow_override = false**: Skip if sequence already active (default)
- **allow_override = true**: Stop and restart the sequence

### Example Scenarios

**Scenario 1: Button triggers sequence once**
```json
{
  "trigger_name": "RedTelephone.Button_1",
  "trigger_value": "On",
  "flame_sequence": "Firefly_3_chase",
  "allow_override": false
}
```
- First button press starts sequence
- Additional presses while running are ignored

**Scenario 2: Dial position changes effect**
```json
{
  "trigger_name": "Dial.Number",
  "trigger_value": "5",
  "flame_sequence": "Pattern_Five",
  "allow_override": true
}
```
- Dial set to 5 starts Pattern_Five
- If already running, restarts it

**Scenario 3: Multiple sequences from one trigger**
```json
[
  {
    "trigger_name": "MasterSwitch",
    "trigger_value": "On",
    "flame_sequence": "Startup_Sequence"
  },
  {
    "trigger_name": "MasterSwitch",
    "trigger_value": "Off",
    "flame_sequence": "Shutdown_Sequence"
  }
]
```

## Validation & Monitoring

### Automatic Validation
Every 5 minutes, the system:
1. Fetches available triggers from Trigger Server
2. Validates all mappings
3. Logs warnings for mappings referencing non-existent triggers

Example log output:
```
WARNING: Mapping references non-existent trigger: OldTrigger -> Firefly_3_chase
```

### Registration Monitoring
- Logs registration attempts and failures
- Automatically retries every 30 seconds if Trigger Server is unavailable
- Logs successful registration with socket status

### Trigger Event Logging
Each received trigger event is logged:
```
INFO: Received trigger event: RedTelephone.Button_1, value: On, id: 12345
INFO: Triggering flame sequence: Firefly_3_chase
```

## Troubleshooting

### Integration Not Working

**Check status:**
```bash
curl http://localhost:5001/trigger-integration/status
```

**Common Issues:**

1. **registered: false**
   - Trigger Server not running
   - Check logs for connection errors
   - Server will auto-retry every 30 seconds

2. **mapping_count: 0**
   - No mappings configured
   - Use POST endpoint to create mappings

3. **Socket connection failed**
   - Port 6000 already in use
   - Check firewall settings

### Trigger Not Firing Sequence

**Check these:**

1. **Is trigger in configuration?**
```bash
curl http://localhost:5002/api/triggers
```

2. **Does mapping exist?**
```bash
curl http://localhost:5001/trigger-integration/mappings
```

3. **Check trigger value matching:**
   - If mapping specifies trigger_value="On", only "On" events will trigger
   - Leave trigger_value empty to trigger on any value

4. **Is sequence already active?**
   - If allow_override=false, won't re-trigger
   - Check flame server: `curl http://localhost:5001/flame`

5. **Check logs:**
```bash
# Tail flame server logs
python flames_webserver.py 2>&1 | grep "trigger"
```

### Port Conflicts

**Trigger Server port changed to 5002** to avoid conflict with Flame Server (5001)

Ports used:
- 5001: Flame Server web interface
- 5002: Trigger Server web interface  
- 6000: Trigger event listener (Flame Server)

## Example Usage

### 1. Create triggers in Trigger Server
```bash
curl -X POST http://localhost:5002/api/triggers \
  -H "Content-Type: application/json" \
  -d '{"name": "RedButton", "type": "On/Off"}'
```

### 2. Create mapping in Flame Server
```bash
curl -X POST http://localhost:5001/trigger-integration/mappings \
  -d "trigger_name=RedButton&trigger_value=On&flame_sequence=Firefly_3_chase"
```

### 3. Send trigger event (from device)
```bash
curl -X POST http://localhost:5002/api/trigger-event \
  -H "Content-Type: application/json" \
  -d '{"name": "RedButton", "value": "On", "id": 1001}'
```

### 4. Verify sequence started
```bash
curl http://localhost:5001/flame
```

Look for Firefly_3_chase with `"active": true`

## Integration Features Summary

✅ **Automatic Registration** - Retries every 30 seconds until successful  
✅ **Persistent Connection** - TCP socket maintained for efficient event delivery  
✅ **Mapping Persistence** - Stored in trigger_mappings.json  
✅ **Validation** - Warns about non-existent triggers  
✅ **Duplicate Prevention** - Configurable per-mapping  
✅ **Value Matching** - Trigger only on specific values  
✅ **ID-based Events** - Compatible with trigger server's ID-based caching  
✅ **Thread-safe** - Proper locking for concurrent access  
✅ **Comprehensive Logging** - Full visibility into operations
