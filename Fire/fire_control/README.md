# Haven Fire Control

Flame effect controller for the Haven sculpture. Controls a set of propane poofers
arranged across four bird sculptures (Cockatoo, Osprey, Magpie, and Perch) via RS-485
serial to a set of poofer controller boards. Provides a web UI and REST API for
monitoring, manual control, sequence management, and integration with the Haven
Trigger Server.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  flames_webserver.py                 │
│  Flask REST API (port 5001) + static web dashboard  │
└────────────────┬──────────────────┬─────────────────┘
                 │                  │
    ┌────────────▼──────┐  ┌────────▼──────────────┐
    │ flames_controller │  │  trigger_integration   │
    │  (state manager)  │  │  (Trigger Server link) │
    └────────────┬──────┘  └───────────────────────┘
                 │
    ┌────────────▼──────┐     ┌──────────────────┐
    │    flames_drv     │     │  pattern_manager  │
    │  (serial driver)  │     │  (sequence CRUD)  │
    └────────────┬──────┘     └──────────────────┘
                 │
    ┌────────────▼──────┐
    │  RS-485 serial    │
    │  Poofer boards    │
    └───────────────────┘

Internal event bus: event_manager (pub/sub, used for poofer on/off, global pause, etc.)
```

### Module Summary

| Module | Purpose |
|--------|---------|
| `flames_webserver.py` | Entry point. Flask server, REST API, serves web UI. |
| `flames_controller.py` | High-level state: enabled/disabled poofers, active sequences, global pause/play. All reads and writes of system state go through here. |
| `flames_drv.py` | Low-level driver thread. Translates sequences into time-ordered "bang protocol" RS-485 commands and sends them over serial. |
| `pattern_manager.py` | CRUD for named flame sequences. Loads from / saves to a JSON file. |
| `event_manager.py` | Internal pub/sub event bus. Decouples the driver from the controller. |
| `trigger_integration.py` | Connects to the Haven Trigger Server; listens for trigger events over TCP and maps them to flame sequences. |
| `poofermapping.py` | Maps human-readable poofer names to RS-485 controller board/channel addresses. |
| `mock_event_producer.py` | Simulates driver events for development/testing without hardware. |

---

## Hardware

The poofer controller boards use the **"!" (bang) protocol** over RS-485 at 19200 baud.
Each command has the form:

```
!<boardId><channel><state>.
```

where `boardId` is a two-hex-digit board address, `channel` is the channel letter, and
`state` is `1` (on) or `0` (off). Multiple channels on the same board are separated by
`~`. Example: `!01A1~B1.` fires channels A and B on board 01.

Protocol reference: http://flg.waywardengineer.com/index.php?title=Bang_(!)_Protocol

The serial port is auto-detected at startup: looks for `tty.usbserial*` (macOS/FTDI)
or `ttyUSB0` (Linux/Pi).

### Poofer Layout

| Group | Poofer IDs |
|-------|-----------|
| 🦜 Cockatoo body | C1, C2, C3, C4, C5, C6 |
| 🦜 Cockatoo hair | C_HAIR1, C_HAIR2, C_HAIR3, C_HAIR4 |
| 🦅 Osprey | O_EYES, O_WINGS, O1, O2, O3 |
| 🐦‍⬛ Magpie | M_TAIL, M1, M2, M3 |
| 🪶 Perch | P1, P2, P3, P4 |

Poofer-to-board-address mappings are in `poofermapping.py`. The address format is a
3-character string: first two characters = board ID (hex), third = channel.

---

## Flame Sequences

A flame sequence (pattern) is a named, time-ordered list of poofer firing events stored
as JSON. Sequences are loaded from `std_sequences.json` at startup and can be managed
at runtime via the API or the web UI.

### Sequence Format

```json
{
  "name": "MySequence",
  "modifiable": true,
  "events": [
    { "ids": ["C1", "C2"], "startTime": 0,    "duration": 500 },
    { "ids": ["O1"],        "startTime": 600,  "duration": 300 },
    { "ids": ["M1", "M2"], "startTime": 1000, "duration": 400 }
  ]
}
```

- **`startTime`** — milliseconds from the start of the sequence.
- **`duration`** — how long the poofers fire, in milliseconds.
- **`ids`** — list of poofer names from `poofermapping.py`.
- **`modifiable`** — if `false`, the sequence cannot be edited or deleted via the API.

Constraints enforced by the driver:
- Max 50 events per sequence.
- Total sequence duration ≤ 60 seconds.
- Minimum poofer cycle time: 50 ms (hardware relay limit).

---

## Installation

```bash
pip install -r requirements.txt
# Also install: requests, flask-cors (if not present — see imports in flames_webserver.py)
```

The service expects a utility module `flask_utils` (providing `CORSResponse` and
`JSONResponse`) to be on the Python path. In production, this lives at
`/home/flaming/haven/util`.

---

## Running

### Directly

```bash
cd /home/flaming/haven/Fire/fire_control
python3 flames_webserver.py [--port PORT]
```

Default port is **5001**.

### As a systemd service

```bash
sudo cp flames.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable flames
sudo systemctl start flames
sudo systemctl status flames
```

Logs via `journalctl -u flames -f`.

---

## Web UI

Open `http://<host>:5001/` in a browser. Three tabs:

### Control Tab
- **Global Play / Pause** — pause halts all firing immediately; play resumes.
- **Sequence buttons** — fire a named sequence once. Each sequence also has a repeat
  mode: set an interval (seconds) and toggle the 🔄 button to repeat it automatically.
- **Individual poofers** — fire a single poofer or enable/disable it.
- **System Status** — shows global state, all poofer enabled/active states, and all
  sequence enabled/active states.

### Pattern Manager Tab
Create, edit, and delete sequences. Changes are persisted to `std_sequences.json`.

### Trigger Mappings Tab
Configure which incoming trigger events fire which flame sequences. See
[Trigger Integration](#trigger-integration) below.

---

## REST API

Base URL: `http://<host>:5001`

### Global Control

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/flame` | Get full system status (global state, all poofers, all patterns). |
| `POST` | `/flame` | `playState=[pause\|play]` — pause or resume all firing. |

### Poofer Control

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/flame/poofers/<id>` | Get poofer enabled/active status. |
| `POST` | `/flame/poofers/<id>` | `enabled=[true\|false]` — enable or disable a poofer. |

### Pattern/Sequence Management

| Method   | Path | Description |
|----------|------|-------------|
| `GET`    | `/flame/patterns` | List all patterns with status. |
| `POST`   | `/flame/patterns` | `patternData=<json>` — add a new pattern. |
| `GET`    | `/flame/patterns/<name>` | Get pattern status. Add `?full` for full pattern data. |
| `POST`   | `/flame/patterns/<name>` | `active=[true\|false]` start/stop. `enabled=[true\|false]` enable/disable. |
| `DELETE` | `/flame/patterns/<name>` | Delete pattern (persists to file). |
| `POST`   | `/flame/patterns/loops/stop` | Stop all autonomously-looping patterns without a global pause. Useful on scene transitions. |

### Poofer Mapping Management

| Method   | Path | Description |
|----------|------|-------------|
| `GET`    | `/flame/poofer-mappings` | Return all current poofer→board-address mappings. |
| `POST`   | `/flame/poofer-mappings` | Add or overwrite a mapping. Form params: `name`, `address`. |
| `POST`   | `/flame/poofer-mappings/reset-defaults` | Reset all mappings to the built-in defaults. |
| `PUT`    | `/flame/poofer-mappings/<name>` | Update the board address for a named poofer. Form param: `address`. |
| `DELETE` | `/flame/poofer-mappings/<name>` | Remove a poofer mapping. |

### Utilities

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/refresh-scene` | Force an immediate re-fetch of the active scene from the scene service. Returns `{"active_scene": "...", "refreshed": true\|false}`. |

---

## Trigger Integration

`trigger_integration.py` connects this system to the Haven Trigger Server and the
Haven Scene Service. When a trigger event arrives that matches a configured mapping,
the corresponding flame sequence is started.

### How It Works

1. On startup, `TriggerIntegration` registers with the Trigger Server as `"FlameServer"`,
   advertising a TCP socket listener.
2. The Trigger Server pushes events to that TCP socket as newline-delimited JSON:
   ```json
   {"name": "ButtonDevice.Button", "value": "On", "id": 42}
   ```
3. `trigger_integration` looks up matching mappings and calls
   `flames_controller.doFlameEffect(sequenceName)`.

### Default Addresses

| Service | Default |
|---------|---------|
| Trigger Server | `http://localhost:5002` |
| Listener (TCP) | port `6000` |
| Scene Service | `http://localhost:5003` |

Override in `flames_webserver.py`:
```python
trigger_integration.init(trigger_server_url="http://192.168.x.x:5002", listen_port=6000)
```

### Mappings

Mappings are stored in `trigger_mappings.json` and managed via the web UI or the API.

Each mapping specifies:

| Field | Description |
|-------|-------------|
| `trigger_name` | Full trigger name, e.g. `"ButtonDevice.Button"` |
| `scene` | **Required.** The scene this mapping belongs to. The mapping only fires when this scene is active. |
| `trigger_value` | *(optional)* Exact value to match, e.g. `"On"` or `1`. Omit to match any value. |
| `trigger_value_min` / `trigger_value_max` | *(optional)* Range bounds for continuous (float) triggers. Mutually exclusive with `trigger_value`. |
| `flame_sequence` | Name of the flame sequence to run. |
| `allow_override` | If `true`, restarts the sequence if it's already running. Default `false`. |

### Trigger Integration API

| Method | Path | Description |
|--------|------|-------------|
| `GET`   | `/trigger-integration/status` | Registration status, mapping count, active scene, `scene_unconfigured` flag. |
| `GET`   | `/trigger-integration/triggers` | List all triggers known to the Trigger Gateway. |
| `GET`   | `/trigger-integration/scenes` | Available scenes, active scene, and configured scenes. |
| `GET`   | `/trigger-integration/scenes/active` | Currently active scene only. |
| `POST`  | `/trigger-integration/scenes` | Register a scene (create empty config). Form param: `scene_name`. |
| `DELETE`| `/trigger-integration/scenes/<name>` | Delete a scene and all its mappings. |
| `GET`   | `/trigger-integration/mappings` | All trigger→flame mappings (flat list with `scene` field). |
| `POST`  | `/trigger-integration/mappings` | Create a mapping. **`scene` required.** See fields above. |
| `POST`  | `/trigger-integration/mappings/copy-scene` | Copy all mappings from one scene to another. Form params: `from_scene`, `to_scene`. |
| `GET`   | `/trigger-integration/mappings/<id>` | Get specific mapping. |
| `PUT`   | `/trigger-integration/mappings/<id>` | Update mapping. Optional `scene` param moves mapping to a different scene. |
| `DELETE`| `/trigger-integration/mappings/<id>` | Delete mapping. |
| `POST`  | `/api/refresh-scene` | Force immediate re-fetch of active scene from scene service. |

---

## Internal Events

`event_manager` carries these event types between modules:

| `msgType` | `id` | Meaning |
|-----------|------|---------|
| `poofer_on` | poofer ID | Poofer started firing |
| `poofer_off` | poofer ID | Poofer stopped firing |
| `poofer_enabled` | poofer ID | Poofer re-enabled |
| `poofer_disabled` | poofer ID | Poofer disabled |
| `sequence_start` | sequence name | Sequence started |
| `sequence_stop` | sequence name | Sequence stopped |
| `global_pause` | `"all?"` | Global pause issued |
| `global_resume` | `"all?"` | Global resume issued |

---

## File Reference

| File | Purpose |
|------|---------|
| `flames_webserver.py` | Main entry point |
| `flames_controller.py` | High-level state and sequencing control |
| `flames_drv.py` | Serial/RS-485 driver thread |
| `pattern_manager.py` | Sequence persistence and CRUD |
| `event_manager.py` | Internal pub/sub bus |
| `trigger_integration.py` | Trigger Server integration |
| `poofermapping.py` | Poofer name → board address map |
| `mock_event_producer.py` | Simulated events for development |
| `std_sequences.json` | Default/production sequence library |
| `trigger_mappings.json` | Persisted trigger→flame mappings (auto-generated) |
| `.disabled_poofers.json` | Persisted disabled-poofer list (auto-generated) |
| `flames.service` | systemd unit file |
| `static/` | Web UI (HTML/CSS/JS) |
