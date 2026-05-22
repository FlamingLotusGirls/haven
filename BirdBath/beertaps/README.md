# Beertaps: ADC Reader System

Reads position values from six beer-tap potentiometers via three ADS1115 ADC
chips over I2C and streams calibrated values (−1.0 to +1.0) to a shared named
pipe consumed by `BirdBathController.py`.

---

## Features

- Three ADS1115 controllers at I2C addresses `0x48`, `0x49`, `0x4a`; two
  differential channels each → six tap channels (`tap1`–`tap6`)
- Calibration maps raw voltage ranges to [−1.0, +1.0]
- Shared named pipe (`/tmp/beertap_pipe`) with file-locked atomic writes
  supports multiple concurrent writer processes
- Systemd service templates for automatic startup
- Calibration available both from the **command line** (`calibrate.py`) and
  from the **BirdBathController web UI** (Configure → Beertap tab)

---

## Files

### Main programs

| File | Description |
|------|-------------|
| `adc_reader.py` | Continuous ADC reader; writes to named pipe |
| `calibrate.py` | Unified interactive calibration tool (CLI) |
| `beertap_calibration_core.py` | Shared calibration library used by both `calibrate.py` and `BirdBathController.py` |
| `i2c_lock.py` | File-based I2C device locking |

> **Note:** The older `calibrate_adc.py` is superseded by `calibrate.py` +
> `beertap_calibration_core.py`.  New code should use the current tools.

### Configuration files

| File | ADC address | Tap channels |
|------|-------------|--------------|
| `adc_config_1.json` | `0x48` | tap3, tap4 |
| `adc_config_2.json` | `0x49` | tap5, tap6 |
| `adc_config_3.json` | `0x4a` | tap1, tap2 |
| `calibrate.json` | — | Master config; lists all three `adc_config_*.json` files |
| `adc_config_mock.json` | — | Development / testing without hardware |

### Systemd services

- `systemd/adc-reader-1.service` — controller at `0x48`
- `systemd/adc-reader-2.service` — controller at `0x49`
- `systemd/adc-reader-3.service` — controller at `0x4a`

---

## Configuration file format

```json
{
  "address": "0x48",
  "gain": 1,
  "channels": [
    {
      "name": "tap3",
      "positive_pin": "P0",
      "negative_pin": "P1",
      "calibration": {
        "min_voltage": -3.300875,
        "max_voltage": -0.000125
      }
    }
  ],
  "output_pipe": "/tmp/beertap_pipe",
  "read_interval": 0.05
}
```

`calibrate.json` is the master index:

```json
{
  "config_files": ["adc_config_1.json", "adc_config_2.json", "adc_config_3.json"],
  "calibration_margin_percent": 5.0,
  "endstop_sample_count": 20
}
```

---

## Running the ADC readers

```bash
# Run one reader directly (for testing)
./adc_reader.py adc_config_1.json

# With debug output (prints readings once/second)
./adc_reader.py adc_config_1.json --debug
```

---

## Calibration

### ⚠️ Stop the services first

Calibration needs exclusive I2C access.  Stop the reader services before
running the calibration tool (or use the web UI, which handles this for you):

```bash
sudo systemctl stop adc-reader-1.service adc-reader-2.service adc-reader-3.service
```

### CLI calibration — `calibrate.py`

```bash
# Interactive menu (lists all channels, choose by name or number)
cd /path/to/BirdBath
python3 beertaps/calibrate.py

# Jump straight to a specific channel
python3 beertaps/calibrate.py --channel tap1
```

Inside the interactive menu, per-channel options include:

| Option | Description |
|--------|-------------|
| **A** | Min-Max Capture — sweep the tap through full range, press Enter when done |
| **B** | End-Stop Averaging — record N midpoint crossings for a statistical average |
| **1 / 2** | Set current live reading as MIN or MAX immediately |
| **3 / 4** | Enter a custom voltage as MIN or MAX |
| **5** | Monitor live voltage + calibrated output |

### Web UI calibration

With `BirdBathController.py` running in **configure** mode, open the
**Beertap** tab in the web UI:

1. The page shows all six channels with current calibration ranges.
2. Use the **Stop services** button before reading live voltages or capturing.
3. Click a channel to open a capture panel — set duration and click **Capture**.
4. Review the result and click **Save** to persist the new min/max.
5. **Restart services** when done.

---

## Systemd service installation

```bash
# 1. Copy service files
sudo cp systemd/adc-reader-*.service /etc/systemd/system/

# 2. Reload daemon
sudo systemctl daemon-reload

# 3. Enable on boot
sudo systemctl enable adc-reader-1.service adc-reader-2.service adc-reader-3.service

# 4. Start now
sudo systemctl start adc-reader-1.service adc-reader-2.service adc-reader-3.service

# 5. Check status
sudo systemctl status adc-reader-1.service

# 6. View logs
sudo journalctl -u adc-reader-1.service -f
```

> **pyenv note:** The service files assume pyenv.  If you installed Python
> system-wide, update the `ExecStart` path in each `.service` file.

### sudoers for web UI service control

`BirdBathController.py` calls `sudo systemctl start/stop` via the web UI.
Install the provided sudoers snippet so this works without a password:

```bash
sudo cp sudoers.d/birdbath-adc /etc/sudoers.d/
sudo chmod 440 /etc/sudoers.d/birdbath-adc
```

---

## Named pipe data format

All three reader processes write to a single shared pipe (`/tmp/beertap_pipe`)
using file locking for atomic writes.

Each message is a length-prefixed pickled Python dict:

```
[4 bytes big-endian uint32: length of pickled data]
[N bytes: pickle of {"channel": "tap1", "value": 0.5432, "timestamp": 1234567890.0}]
```

`value` is always in [−1.0, +1.0].

### Reading from the pipe in Python

```python
import struct, pickle, os

class PipeReader:
    def __init__(self, pipe_path='/tmp/beertap_pipe'):
        self.pipe_path = pipe_path
        self.buffer = b''
        self.pipe_fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)

    def read_latest_values(self):
        try:
            chunk = os.read(self.pipe_fd, 4096)
            if chunk:
                self.buffer += chunk
        except OSError:
            return  # no data yet

        while len(self.buffer) >= 4:
            length = struct.unpack('>I', self.buffer[:4])[0]
            if len(self.buffer) < 4 + length:
                break
            data = pickle.loads(self.buffer[4:4 + length])
            self.buffer = self.buffer[4 + length:]
            print(f"{data['channel']}: {data['value']:+.4f}")
```

---

## I2C device locking

All tools that access the hardware (`adc_reader.py`, `calibrate.py`) use
`i2c_lock.py` to acquire an exclusive file lock under `/var/lock/` before
touching the I2C bus.

If a second process tries to open the same ADC while it is locked, it gets:

```
************************************************************
*  ERROR: I2C DEVICE IN USE
************************************************************
  ADS1115 at 0x48 is in use by PID 1234 (adc_reader.py)
  Stop that process first, e.g.:
    sudo systemctl stop adc-reader-1.service
************************************************************
```

---

## Hardware

| Component | Details |
|-----------|---------|
| Pi | Raspberry Pi OS Bookworm |
| ADC | Adafruit ADS1115 × 3 (product 1085) |
| Pot | 15 mm 20 kΩ linear potentiometer (Digikey) |
| Wiring | Differential over ethernet (1 pair V+/GND, 3 pairs WIPER/GND) |
| I2C addresses | `0x48`, `0x49`, `0x4a` (set via ADDR pin) |

Each ADS1115 reads two differential channels:
- Channel A: pins P0 (+) / P1 (−)
- Channel B: pins P2 (+) / P3 (−)

---

## Dependencies

```bash
pip3 install -r beertaps/requirements.txt
# or manually:
pip3 install adafruit-circuitpython-ads1x15 adafruit-blinka
```

The `beertap_calibration_core` module imports hardware libraries lazily, so
it is safe to `import beertap_calibration_core` on a non-Pi development
machine — hardware calls only happen when actually invoked.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Permission error on I2C | `sudo usermod -a -G i2c $USER` |
| "I2C device in use" during calibration | Stop the reader services first |
| No data on pipe | Verify ADC is connected: `i2cdetect -y 1` |
| Service not starting | Check logs: `sudo journalctl -u adc-reader-1.service -n 50` |
| Web UI can't start/stop services | Install `sudoers.d/birdbath-adc` (see above) |

---

This code is part of the Haven BirdBath system.
