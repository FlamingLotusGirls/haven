# haven - BirdBath

Code supporting the BirdBath sculpture, a 36 valve, fully controllable, fire sculpture. It's
like a birdbath except with flames instead of water.

The BirdBath valve technology is based on LightCurve, developed by Sam Cooler and Sequoia Alexander.
Control software, patterns, and webUI developed by Carolyn Wales and Brian Bulkowski.

---

## Quick start

Note that by default, the birdbath controller should start *automatically* (it is a system service)
on the BirdBath raspberry pi. You can run it on a different platform (like a Mac) for debugging
or for pattern development.

```bash
cd /path/to/BirdBath
python3 BirdBathController.py
# Web UI: http://<ip>:8080/
```

---

## Web controller — `BirdBathController.py`

The single entry point for running the sculpture.  It owns:

- An HTTP server (default port 8080) that serves the web UI and a REST API
- A frame loop that drives pattern processes and sends ArtNet frames to the hardware controllers
- Mode persistence across restarts (`birdbath_state.json`)

### Modes

| Mode | Description |
|------|-------------|
| **run** | Frame loop is active; patterns consume tap input and drive nozzle output |
| **configure** | Frame loop is idle; web UI exposes nozzle calibration and pattern config |

Switch modes from either web page via the banner button, or at startup:

```bash
python3 BirdBathController.py --mode run       # force run on next boot
python3 BirdBathController.py --mode configure
```

### Command-line flags

| Flag | Default | Description |
|------|---------|-------------|
| `--config` / `-c` | `patterns.yaml` | Pattern configuration file |
| `--driver-config` | `driver_config.yaml` | ArtNet controller / nozzle-range config |
| `--mode` | persisted | Override startup mode (`run` or `configure`) |
| `--port` | `8080` | HTTP server port |
| `--daemon` / `-d` | off | Run pattern subprocesses as daemons |

---

## Run mode — Nozzle Visualization (`nozzle_visualization.html`)

Live canvas showing all 36 nozzles colour-coded by current output value
(red = positive, blue = negative, dark = zero).

### Input source

Below the page heading, a toggle switches the input source for all patterns:

| Source | Behaviour |
|--------|-----------|
| **Hardware** | Values come from the beertap ADC pipe (`/tmp/beertap_pipe`) |
| **Web UI Mock** | A slider panel appears with one slider (−1.0 → +1.0) per tap channel.  Moving a slider immediately updates the pattern and the visualization. |

The channel list for the mock sliders is populated from `GET /beertaps/channels`
(all 6 configured taps); on non-Pi machines where the beertap library is absent
it falls back to the channels listed in `patterns.yaml`.

### REST endpoints (run mode)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/nozzles` | Current 36-element frame array (JSON) |
| `GET` | `/input/source` | Current source (`hardware`/`mock`) + mock values |
| `POST` | `/input/source` | Body `{"source":"hardware"\|"mock"}` — switch source |
| `POST` | `/input/mock` | Body `{"channel":"tap1","value":0.5}` — set mock value |

---

## Configure mode (`configuration.html`)

Two-tab interface:

### Tab 1 — Nozzle Calibration

Click any nozzle on the canvas to set its low/high ArtNet range and send
test positions directly to the hardware controller.  Values are persisted
in `driver_config.yaml`.

### Tab 2 — Pattern Config

View and edit `patterns.yaml` — choose which pattern class runs and which
tap input channel feeds it.  Changes take effect on the next switch to run mode.

### Beertap tab

Manage tap calibration from the web UI without SSH:

- View all 6 tap channels and their current voltage calibration range
- Start/stop the ADC reader systemd services
- Run a timed min-max voltage capture for any channel
- Save new calibration values

### Configure REST endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/nozzle/{id}/calibration` | Read low/high for nozzle 0–35 |
| `PUT` | `/nozzle/{id}/calibration/{high\|low}` | Set calibration endpoint |
| `PUT` | `/nozzle/{id}/position` | Send raw ArtNet position (0–255) |
| `GET` | `/patterns/available` | List concrete Pattern subclasses |
| `GET` | `/patterns/config` | Current `patterns.yaml` as JSON |
| `PUT` | `/patterns/config` | Overwrite `patterns.yaml` |
| `GET` | `/beertaps/channels` | All tap channels + calibration |
| `GET` | `/beertaps/service` | ADC service statuses |
| `POST` | `/beertaps/service` | `{"action":"start"\|"stop"}` |
| `GET` | `/beertaps/channels/{name}/voltage` | Live single voltage read |
| `POST` | `/beertaps/channels/{name}/capture` | Timed min-max capture |
| `PUT` | `/beertaps/channels/{name}/calibration` | Save calibration |

---

## Patterns

Patterns live in the `patterns/` package.  Each is a concrete subclass of
`Pattern` (from `pattern.py`) implementing a `Frame(input_value)` method that
returns a 36-element numpy array.

`patterns.yaml` maps pattern classes to tap input channels:

```yaml
patterns:
  - pattern: AmplitudePattern
    input_channel: tap1
frame_interval_ms: 100
```

Up to 6 patterns can run simultaneously; their output frames are summed and
clamped to [−1.0, 1.0] before being sent to the ArtNet controllers.

---

## Beertap hardware

The "beertaps" are two sets of three beer taps whose sliding liquid valves
have been replaced by custom 3D-printed parts.  Each tap contains a 15 mm
20 kΩ linear potentiometer (Digikey) read differentially via an
Adafruit ADS1115 (product 1085).

Due to potential for long cable runs, differential mode is used over ethernet:
one pair carries V+/GND, the other three carry WIPER/GND(return).

Three ADS1115 boards are mounted in a custom box with two RJ45 connectors
(one per keg) and an I2C connection to the Raspberry Pi.

See `beertaps/README.md` for full hardware setup, calibration, and service
installation instructions.

---

## Systemd service installation

The service file lives at `systemd/birdbath-controller.service`.

```bash
# 1. Copy to systemd
sudo cp systemd/birdbath-controller.service /etc/systemd/system/

# 2. Reload daemon
sudo systemctl daemon-reload

# 3. Enable on boot
sudo systemctl enable birdbath-controller.service

# 4. Start now
sudo systemctl start birdbath-controller.service

# 5. Check status / logs
sudo systemctl status birdbath-controller.service
sudo journalctl -u birdbath-controller.service -f
```

The service starts after `network.target` and requests (but does not require)
the three ADC reader services — the controller handles a missing hardware pipe
gracefully by defaulting all inputs to 0.0.

`Restart=on-failure` means the service restarts if it crashes but stays stopped
after a clean `systemctl stop`.

`KillMode=mixed` + `TimeoutStopSec=30` gives the pattern subprocesses time to
exit cleanly on `systemctl stop` or `systemctl restart`.

---

## RPI configuration

The Raspberry Pi runs Raspberry Pi OS Bookworm and is configured as a Wi-Fi
access point so the ArtNet controller boards can connect without an external
router.
