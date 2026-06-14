#!/usr/bin/env python3
"""
beertap_calibration_core.py — Shared beertap ADC calibration library.

Used by both calibrate.py (CLI) and BirdBathController.py (web UI).
Provides channel discovery, live voltage reading, timed min-max capture,
calibration persistence, and ADC service control.

Hardware modules (board / busio / adafruit_ads1x15) are imported lazily —
it is safe to import this module on a non-Pi development machine.
"""

import json
import os
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Service names (must match installed systemd unit names)
# ---------------------------------------------------------------------------

ADC_SERVICE_NAMES: List[str] = [
    'adc-reader-1.service',
    'adc-reader-2.service',
    'adc-reader-3.service',
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class ChannelInfo:
    """All static information about one tap channel."""

    def __init__(self, name: str, config_file: str, channel_index: int,
                 adc_address: int, adc_gain: int,
                 positive_pin: int, negative_pin: int,
                 calibration: dict):
        self.name = name
        self.config_file = config_file
        self.channel_index = channel_index
        self.adc_address = adc_address
        self.adc_gain = adc_gain
        self.positive_pin = positive_pin
        self.negative_pin = negative_pin
        self.calibration = calibration  # {'min_voltage': float, 'max_voltage': float}

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'config_file': os.path.basename(self.config_file),
            'calibration': dict(self.calibration),
        }


class CaptureResult:
    """Result of a timed min-max voltage capture run."""

    def __init__(self, channel_name: str, min_voltage: float, max_voltage: float,
                 sample_count: int, duration: float, warning: str = ''):
        self.channel_name = channel_name
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage
        self.sample_count = sample_count
        self.duration = duration
        self.warning = warning

    def to_dict(self) -> dict:
        return {
            'channel_name': self.channel_name,
            'min_voltage': self.min_voltage,
            'max_voltage': self.max_voltage,
            'sample_count': self.sample_count,
            'duration_seconds': round(self.duration, 2),
            'voltage_range': round(self.max_voltage - self.min_voltage, 6),
            'warning': self.warning,
        }


# ---------------------------------------------------------------------------
# Config loading — no I2C required
# ---------------------------------------------------------------------------

def _normalize_address(address) -> int:
    if isinstance(address, str):
        return int(address, 16)
    return int(address)


def load_all_channels(
        calibrate_json: str = 'beertaps/calibrate.json',
) -> Dict[str, ChannelInfo]:
    """
    Read calibrate.json and all referenced adc_config_*.json files.
    Returns {channel_name: ChannelInfo}.  No I2C access.
    """
    base_dir = os.path.dirname(os.path.abspath(calibrate_json))

    with open(calibrate_json, 'r') as f:
        master = json.load(f)

    channels: Dict[str, ChannelInfo] = {}

    for rel_path in master['config_files']:
        config_file = os.path.join(base_dir, rel_path)
        if not os.path.exists(config_file):
            print(f"Warning: {config_file} not found, skipping", file=sys.stderr)
            continue
        with open(config_file, 'r') as f:
            cfg = json.load(f)

        address = _normalize_address(cfg['address'])
        gain = cfg.get('gain', 1)

        for idx, ch in enumerate(cfg['channels']):
            info = ChannelInfo(
                name=ch['name'],
                config_file=config_file,
                channel_index=idx,
                adc_address=address,
                adc_gain=gain,
                positive_pin=ch['positive_pin'],
                negative_pin=ch['negative_pin'],
                calibration=dict(ch['calibration']),
            )
            channels[ch['name']] = info

    return channels


def save_calibration(channel_name: str, min_voltage: float, max_voltage: float,
                     calibrate_json: str = 'beertaps/calibrate.json') -> None:
    """
    Atomically write updated calibration values for one channel back to
    its adc_config_*.json file.
    """
    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        raise ValueError(f"Unknown channel: {channel_name!r}")

    info = channels[channel_name]

    with open(info.config_file, 'r') as f:
        config = json.load(f)

    config['channels'][info.channel_index]['calibration']['min_voltage'] = min_voltage
    config['channels'][info.channel_index]['calibration']['max_voltage'] = max_voltage

    tmp = info.config_file + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, info.config_file)


# ---------------------------------------------------------------------------
# I2C helpers — hardware imported lazily
# ---------------------------------------------------------------------------

def _ensure_beertaps_on_path(calibrate_json: str) -> None:
    """Ensure the beertaps/ directory is on sys.path so i2c_lock can be imported."""
    d = os.path.dirname(os.path.abspath(calibrate_json))
    if d not in sys.path:
        sys.path.insert(0, d)


def _open_adc_channel(info: ChannelInfo):
    """
    Open the I2C bus and return an AnalogIn channel object.
    Caller must already hold the I2C lock for info.adc_address.
    Raises ImportError if hardware libraries are not available.
    """
    import board                                          # type: ignore
    import busio                                          # type: ignore
    import adafruit_ads1x15.ads1115 as ADS               # type: ignore
    from adafruit_ads1x15.analog_in import AnalogIn       # type: ignore

    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS.ADS1115(i2c, address=info.adc_address)
    ads.gain = info.adc_gain
    print("Attempting to get info on the positive and negative pins")
    pos = info.positive_pin
    neg = info.negative_pin
    print("Got info on the positive and negative pins")
    return AnalogIn(ads, pos, neg)


def read_voltage(channel_name: str,
                 calibrate_json: str = 'beertaps/calibrate.json',
                 ) -> Tuple[float, float]:
    """
    Read one voltage sample from the named channel.
    Acquires the I2C lock, reads, and immediately releases.

    Returns (raw_voltage, calibrated_value) where calibrated ∈ [-1.0, 1.0].

    Raises I2CDeviceInUseError if the adc_reader service holds the lock.
    Raises ValueError if the channel name is unknown.
    """
    _ensure_beertaps_on_path(calibrate_json)
    from i2c_lock import I2CLock  # type: ignore

    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        raise ValueError(f"Unknown channel: {channel_name!r}")
    info = channels[channel_name]

    with I2CLock(info.adc_address):
        ch = _open_adc_channel(info)
        voltage = ch.voltage

    cal = info.calibration
    calibrated = _apply_calibration(voltage, cal['min_voltage'], cal['max_voltage'])
    return voltage, calibrated


def capture_minmax(
        channel_name: str,
        duration: float = 10.0,
        calibrate_json: str = 'beertaps/calibrate.json',
        stop_event=None,
        progress_callback: Optional[Callable[[float, float, float, float], None]] = None,
) -> CaptureResult:
    """
    Sample the named channel as fast as possible for up to *duration* seconds
    (or until stop_event is set) and return the min/max voltages observed.

    Args:
        channel_name:       Tap name, e.g. "tap1".
        duration:           Maximum capture time in seconds.
        calibrate_json:     Path to calibrate.json.
        stop_event:         Optional threading.Event; capture ends when set.
        progress_callback:  Called ~5×/second with
                            (elapsed_seconds, current_voltage,
                             tracked_min, tracked_max).
                            Useful for CLI live-display.

    The I2C lock is held for the full duration of the capture.
    Raises I2CDeviceInUseError if the adc_reader service holds the lock.
    """
    _ensure_beertaps_on_path(calibrate_json)
    from i2c_lock import I2CLock  # type: ignore

    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        raise ValueError(f"Unknown channel: {channel_name!r}")
    info = channels[channel_name]

    with I2CLock(info.adc_address):
        ch = _open_adc_channel(info)

        initial = ch.voltage
        tracked_min = initial
        tracked_max = initial
        sample_count = 0
        start = time.time()
        last_cb = start

        while True:
            elapsed = time.time() - start
            if elapsed >= duration:
                break
            if stop_event is not None and stop_event.is_set():
                break

            voltage = ch.voltage
            sample_count += 1
            if voltage < tracked_min:
                tracked_min = voltage
            if voltage > tracked_max:
                tracked_max = voltage

            now = time.time()
            if progress_callback is not None and (now - last_cb) >= 0.2:
                progress_callback(elapsed, voltage, tracked_min, tracked_max)
                last_cb = now

    actual_duration = time.time() - start
    warning = ''
    if tracked_max - tracked_min < 0.1:
        warning = 'Small range detected — may not have moved through full range'

    return CaptureResult(
        channel_name=channel_name,
        min_voltage=tracked_min,
        max_voltage=tracked_max,
        sample_count=sample_count,
        duration=actual_duration,
        warning=warning,
    )


# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------

def get_service_status() -> Dict[str, str]:
    """
    Return {service_name: status} for each ADC reader service.
    Status is typically 'active', 'inactive', 'failed', or 'unknown'.
    """
    result: Dict[str, str] = {}
    for svc in ADC_SERVICE_NAMES:
        try:
            r = subprocess.run(
                ['sudo', 'systemctl', 'is-active', svc],
                capture_output=True, text=True, timeout=5,
            )
            result[svc] = r.stdout.strip() or 'unknown'
        except Exception:
            result[svc] = 'unknown'
    return result


def stop_adc_services() -> Tuple[bool, str]:
    """Stop all adc-reader services.  Returns (success, message)."""
    errors = []
    for svc in ADC_SERVICE_NAMES:
        try:
            r = subprocess.run(
                ['sudo', 'systemctl', 'stop', svc],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                errors.append(f'{svc}: {r.stderr.strip()}')
        except Exception as e:
            errors.append(f'{svc}: {e}')
    if errors:
        return False, '; '.join(errors)
    return True, 'All ADC reader services stopped'


def start_adc_services() -> Tuple[bool, str]:
    """Start all adc-reader services.  Returns (success, message)."""
    errors = []
    for svc in ADC_SERVICE_NAMES:
        try:
            r = subprocess.run(
                ['sudo', 'systemctl', 'start', svc],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                errors.append(f'{svc}: {r.stderr.strip()}')
        except Exception as e:
            errors.append(f'{svc}: {e}')
    if errors:
        return False, '; '.join(errors)
    return True, 'All ADC reader services started'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_calibration(voltage: float, min_v: float, max_v: float) -> float:
    if max_v == min_v:
        return 0.0
    calibrated = 2.0 * ((voltage - min_v) / (max_v - min_v)) - 1.0
    return max(-1.0, min(1.0, calibrated))
