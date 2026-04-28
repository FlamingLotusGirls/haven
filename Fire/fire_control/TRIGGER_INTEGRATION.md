# Trigger Integration for Flame Control

## Overview

`trigger_integration.py` connects the Flame Control system with the Haven Trigger
Gateway and Scene Service. When a trigger event arrives that matches a configured
mapping **for the currently active scene**, the corresponding flame sequence is started.

## Architecture

```
Device → Trigger Gateway (port 5002) → Flame Server (port 6000) → Flame Sequences
                                              ↓
                                     trigger_mappings.json
                                     (scene-keyed mappings)
```

### Components

| Component | Purpose |
|---|---|
| **Trigger Gateway** (`Triggers/trigger_gateway.py`) | Dispatches trigger events via persistent TCP socket to all registered services. Port 5002. |
| **Flame Server** (`flames_webserver.py`) | Receives events, looks up scene-appropriate mappings, fires sequences. Port 5001 (web), 6000 (trigger listener). |
| **trigger_integration.py** | Registers with the gateway (with retry), maintains the scene-keyed mapping data, handles `SceneChange` events. |

---

## Setup

### Start Services

```bash
# Terminal 1 — Trigger Gateway
cd ~/haven/Triggers
python trigger_gateway.py

# Terminal 2 — Flame Server
cd ~/haven/Fire/fire_control
python flames_webserver.py
```

The Flame Server will automatically:
- Register with the Trigger Gateway as `"FlameServer"` (retries every 30 s if unavailable)
- Establish a persistent TCP socket connection on port 6000
- Load existing trigger mappings from `trigger_mappings.json`
- Poll the Scene Service every 10 s (1 s until the first scene is known)

---

## Data Model

Mappings are stored in `trigger_mappings.json` keyed by scene name:

```json
{
  "scenes": {
    "BurnsNight": [
      {
        "id": 1,
        "trigger_name": "RedTelephone.Button_1",
        "trigger_value": "On",
        "flame_sequence": "Firefly_3_chase",
        "allow_override": false
      },
      {
        "id": 2,
        "trigger_name": "RedTelephone.Dial",
        "trigger_value_min": 3.0,
        "trigger_value_max": 7.0,
        "flame_sequence": "Mid_Dial_Pattern",
        "allow_override": true
      }
    ],
    "DayScene": []
  }
}
```

**Key concepts:**
- Each mapping belongs to **exactly one scene** — `scene` is required when creating a mapping.
- `DayScene: []` — an explicitly configured scene with **no** mappings ("quiet scene"). This is
  valid and distinct from a scene that has never been configured.
- A scene that has **no entry at all** in `trigger_mappings.json` is *unconfigured*. When the
  active scene is unconfigured, **all trigger dispatch is suppressed** until the scene is
  registered. This prevents accidental firing when the scene service returns a scene that
  nobody has set up mappings for yet.

### Mapping Fields

| Field | Required | Description |
|---|---|---|
| `trigger_name` | ✓ | Full trigger name, e.g. `"RedTelephone.Button_1"` |
| `flame_sequence` | ✓ | Name of the flame sequence to fire |
| `scene` | ✓ *(on create)* | Scene this mapping belongs to |
| `trigger_value` | — | Exact value to match (e.g. `"On"`, `1`). Omit to match any value. |
| `trigger_value_min` | — | Minimum value (float) for continuous/range matching. Mutually exclusive with `trigger_value`. |
| `trigger_value_max` | — | Maximum value (float) for range matching. Used with `trigger_value_min`. |
| `allow_override` | — | If `true`, restart sequence if already running. Default `false`. |

---

## Scene-Aware Dispatch

1. The integration polls the Scene Service every 10 s (1 s until first successful response) to track the active scene.
2. When a `SceneChange` trigger arrives from the gateway, the active scene is updated immediately without waiting for the next poll.
3. When a trigger event arrives, the integration looks up the mappings for the **current active scene only**.
4. If the active scene has no entry in `trigger_mappings.json` (`scene_unconfigured = true`), the event is dropped and a warning is logged. This prevents unintended firing on unconfigured scenes.
5. If the scene is configured but has zero mappings (quiet scene), the event is silently ignored.

---

## REST API

All endpoints are served by `flames_webserver.py` at `http://localhost:5001`.
All POST/PUT body parameters are form-encoded (`application/x-www-form-urlencoded`).

### Status

```
GET /trigger-integration/status
```

```json
{
  "registered":               true,
  "trigger_server_url":       "http://localhost:5002",
  "listen_port":              6000,
  "mapping_count":            5,
  "available_triggers_count": 12,
  "available_scenes_count":   3,
  "active_scene":             "BurnsNight",
  "scene_unconfigured":       false,
  "configured_scenes":        ["BurnsNight", "DayScene"]
}
```

`scene_unconfigured: true` means the active scene has no entry in `trigger_mappings.json`
and all trigger dispatch is currently suppressed.

### Triggers

```
GET /trigger-integration/triggers
```

Returns the list of triggers currently registered with the Trigger Gateway (refreshed every 5 minutes).

### Scenes

```
GET /trigger-integration/scenes
```

```json
{
  "scenes":            ["BurnsNight", "DayScene", "Setup"],
  "active_scene":      "BurnsNight",
  "configured_scenes": ["BurnsNight", "DayScene"]
}
```

- `scenes` — scene names from the Scene Service
- `configured_scenes` — scenes that have an entry in `trigger_mappings.json`

```
GET /trigger-integration/scenes/active
```

```json
{"active_scene": "BurnsNight"}
```

```
POST /trigger-integration/scenes
scene_name=DayScene
```

Registers a scene with an empty mapping list (creates a "quiet scene" entry).
Returns `201` on creation.

```
DELETE /trigger-integration/scenes/<scene_name>
```

Deletes the scene entry **and all its mappings**. Returns `200` on success, `404` if not found.

```
POST /api/refresh-scene
```

Forces an immediate re-fetch of the active scene from the Scene Service.
Returns `{"active_scene": "...", "refreshed": true|false}`.

### Mappings

```
GET /trigger-integration/mappings
```

Returns a flat list of all mappings across all scenes, each with a `scene` field:

```json
{
  "mappings": [
    {
      "id": 1,
      "scene": "BurnsNight",
      "trigger_name": "RedTelephone.Button_1",
      "trigger_value": "On",
      "flame_sequence": "Firefly_3_chase",
      "allow_override": false
    }
  ]
}
```

```
POST /trigger-integration/mappings
trigger_name=RedTelephone.Button_1&trigger_value=On&flame_sequence=Firefly_3_chase&scene=BurnsNight&allow_override=false
```

**`scene` is required.** Optional: `trigger_value`, `trigger_value_min`, `trigger_value_max`, `allow_override`.

Returns `201` on success:
```json
{"message": "Mapping created", "mapping": {...}}
```

```
POST /trigger-integration/mappings/copy-scene
from_scene=BurnsNight&to_scene=BurnsNight_v2
```

Duplicates all mappings from `from_scene` into `to_scene` with new IDs.
`to_scene` is registered (even if `from_scene` is empty).
Returns `{"from_scene": "...", "to_scene": "...", "copied_count": N}`.

```
GET /trigger-integration/mappings/<id>
```

```
PUT /trigger-integration/mappings/<id>
trigger_name=...&flame_sequence=...&allow_override=true
```

Optional `scene` parameter moves the mapping to a different scene.
All other parameters are optional (only provided fields are updated).

```
DELETE /trigger-integration/mappings/<id>
```

---

## Mapping Behaviour

### Trigger Value Matching

A trigger event matches a mapping when:
- `trigger_name` matches exactly, **and**
- One of:
  - No value constraint is set (fires on any value)
  - `trigger_value` is set and equals the event's `value` (string comparison)
  - `trigger_value_min`/`trigger_value_max` are set and `min ≤ float(value) ≤ max`

### Duplicate Prevention

Before firing a sequence, the integration checks whether it's already active:

- **`allow_override: false`** (default) — if the sequence is already active, the trigger is silently ignored.
- **`allow_override: true`** — the running sequence is stopped and restarted.

### Validation

Every 5 minutes the integration fetches the trigger list from the gateway and logs
warnings for any mapping that references a trigger name not in the gateway's catalogue.
This does **not** disable the mapping — it's advisory only.

---

## Examples

### Scenario 1: Button triggers a sequence

```json
{
  "scene": "BurnsNight",
  "trigger_name": "RedTelephone.Button_1",
  "trigger_value": "On",
  "flame_sequence": "Firefly_3_chase",
  "allow_override": false
}
```

First button press starts `Firefly_3_chase`. Additional presses while it's running are ignored.

### Scenario 2: Continuous slider with range

```json
{
  "scene": "BurnsNight",
  "trigger_name": "RedTelephone.Dial",
  "trigger_value_min": 3.0,
  "trigger_value_max": 7.0,
  "flame_sequence": "Mid_Dial_Pattern",
  "allow_override": true
}
```

Fires when the dial value is between 3 and 7 (inclusive). Restarts if already running.

### Scenario 3: Multiple sequences from one trigger (On/Off)

Create two separate mappings for the same trigger:

```json
{"scene": "BurnsNight", "trigger_name": "MasterSwitch", "trigger_value": "On",  "flame_sequence": "Startup_Sequence"}
{"scene": "BurnsNight", "trigger_name": "MasterSwitch", "trigger_value": "Off", "flame_sequence": "Shutdown_Sequence"}
```

### Scenario 4: Quiet scene

```bash
curl -X POST http://localhost:5001/trigger-integration/scenes \
  -d "scene_name=DayScene"
```

`DayScene` is now configured with no mappings — triggers are silently ignored during the day, but the system doesn't suppress dispatch as "unconfigured".

---

## curl Examples

```bash
# Check integration status
curl http://localhost:5001/trigger-integration/status

# List scenes (from scene service + which are configured locally)
curl http://localhost:5001/trigger-integration/scenes

# Register a new scene
curl -X POST http://localhost:5001/trigger-integration/scenes \
  -d "scene_name=DayScene"

# Create a mapping
curl -X POST http://localhost:5001/trigger-integration/mappings \
  -d "trigger_name=RedTelephone.Button_1&trigger_value=On&flame_sequence=Firefly_3_chase&scene=BurnsNight"

# Copy scene mappings
curl -X POST http://localhost:5001/trigger-integration/mappings/copy-scene \
  -d "from_scene=BurnsNight&to_scene=BurnsNight_v2"

# Update a mapping
curl -X PUT http://localhost:5001/trigger-integration/mappings/1 \
  -d "flame_sequence=NewSequence&allow_override=true"

# Move a mapping to a different scene
curl -X PUT http://localhost:5001/trigger-integration/mappings/1 \
  -d "scene=DayScene"

# Delete a mapping
curl -X DELETE http://localhost:5001/trigger-integration/mappings/1

# Delete a scene (and all its mappings)
curl -X DELETE http://localhost:5001/trigger-integration/scenes/DayScene

# Force scene refresh
curl -X POST http://localhost:5001/api/refresh-scene

# End-to-end test: fire a trigger event and watch it dispatch
curl -X POST http://localhost:5002/api/trigger-event \
  -H "Content-Type: application/json" \
  -d '{"name": "RedTelephone.Button_1", "value": "On", "id": 1001}'

# Verify sequence started
curl http://localhost:5001/flame | python3 -m json.tool | grep -A3 Firefly
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `registered: false` | Trigger Gateway not running — server retries every 30 s |
| `scene_unconfigured: true` | Active scene has no entry in `trigger_mappings.json` — create it with `POST /trigger-integration/scenes` |
| Mapping not firing | Verify `active_scene` matches the mapping's `scene` field in `GET /trigger-integration/status` |
| Wrong value matching | Check `trigger_value` / `trigger_value_min`/`trigger_value_max` vs. actual event value in `GET /api/trigger-log` on the gateway |
| Sequence not restarting | Check `allow_override`; if `false`, sequence must finish before it can be re-triggered |
| Port 6000 already in use | Another process is on that port; change `listen_port` in `flames_webserver.py` |

---

## Integration Features Summary

- ✅ **Automatic registration** — retries every 30 s until the gateway responds
- ✅ **Persistent TCP socket** — events pushed in real time, not polled
- ✅ **Scene-keyed mappings** — each mapping belongs to one scene; only fires when that scene is active
- ✅ **Quiet scenes** — explicitly configured empty-mapping list suppresses firing without "unconfigured" warnings
- ✅ **SceneChange handling** — scene updated immediately on `SceneChange` trigger without waiting for poll
- ✅ **Value matching** — exact value or float range for continuous triggers
- ✅ **Duplicate prevention** — configurable per-mapping with `allow_override`
- ✅ **Copy-scene** — duplicate mappings from one scene to another in one call
- ✅ **Thread-safe** — all shared state protected by locks
- ✅ **Persistent mappings** — saved to `trigger_mappings.json` after every change
