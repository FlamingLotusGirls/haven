#!/usr/bin/env python3
"""
Unified ADS1115 Calibration Tool (CLI)
Calibrates tap channels defined in calibrate.json.

Core I2C logic lives in beertap_calibration_core.py and is shared with the web UI.
This module handles the interactive terminal session.
"""

import json
import select
import sys
import termios
import threading
import time
import tty

import beertap_calibration_core
from beertap_calibration_core import (
    ChannelInfo,
    CaptureResult,
    load_all_channels,
    save_calibration,
    read_voltage,
    capture_minmax,
    _ensure_beertaps_on_path,
    _normalize_address,
    _open_adc_channel,
)

DEFAULT_CALIBRATE_JSON = 'calibrate.json'


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_all_current_values(calibrate_json: str) -> None:
    """Read and display current voltage from every channel."""
    channels = load_all_channels(calibrate_json)
    sorted_names = sorted(channels.keys())

    print('\n' + '=' * 70)
    print('Current ADC Readings — All Channels')
    print('=' * 70)

    for name in sorted_names:
        info = channels[name]
        try:
            voltage, calibrated = read_voltage(name, calibrate_json)
            cal = info.calibration
            print(f"  {name:10s}: cal [{cal['min_voltage']:+.4f}V .. {cal['max_voltage']:+.4f}V] | "
                  f"now {voltage:+.4f}V → output {calibrated:+.4f}")
        except Exception as e:
            print(f"  {name:10s}: ERROR — {e}")

    print('=' * 70)


# ---------------------------------------------------------------------------
# CLI calibration methods
# ---------------------------------------------------------------------------

def _cli_minmax_capture(channel_name: str, calibrate_json: str) -> bool:
    """
    Min-Max Capture: sample until the user presses Enter, then apply.
    Uses beertap_calibration_core.capture_minmax with a threading.Event stop trigger.
    """
    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        print(f"Unknown channel: {channel_name!r}")
        return False

    info = channels[channel_name]
    cal = info.calibration
    print(f"\n--- Min-Max Capture: {channel_name} ---")
    print(f"Current calibration: Min {cal['min_voltage']:+.4f}V  Max {cal['max_voltage']:+.4f}V")
    print("\nMove the control through its FULL range.")
    print("Press Enter when done, Ctrl+C to cancel.\n")

    stop_event = threading.Event()

    def wait_for_enter():
        input()
        stop_event.set()

    t = threading.Thread(target=wait_for_enter, daemon=True)
    t.start()

    def progress(elapsed, voltage, mn, mx):
        rng = mx - mn
        print(f"\rCurrent {voltage:+.4f}V | Min {mn:+.4f}V | Max {mx:+.4f}V | "
              f"Range {rng:.4f}V   ",
              end='', flush=True)

    try:
        result = capture_minmax(
            channel_name,
            duration=3600,       # effectively unlimited — stopped by Enter
            calibrate_json=calibrate_json,
            stop_event=stop_event,
            progress_callback=progress,
        )
    except KeyboardInterrupt:
        print('\n\nCalibration cancelled.')
        return False

    print(f'\n\nResults for {channel_name}:')
    print(f'  Min: {result.min_voltage:.4f}V | Max: {result.max_voltage:.4f}V | '
          f'Range: {result.max_voltage - result.min_voltage:.4f}V')
    if result.warning:
        print(f'  WARNING: {result.warning}')

    confirm = input('Apply these values? (y/N): ').strip().lower()
    if confirm == 'y':
        save_calibration(channel_name, result.min_voltage, result.max_voltage, calibrate_json)
        print(f'✓ Calibration saved for {channel_name}')
        return True
    print('✗ Calibration skipped')
    return False


def _cli_endstop_averaging(channel_name: str, calibrate_json: str,
                            endstop_sample_count: int = 20) -> bool:
    """
    End-Stop Averaging: record the extreme voltage each time the handle
    crosses the midpoint.  Average across N crossings.
    """
    _ensure_beertaps_on_path(calibrate_json)
    from i2c_lock import I2CLock, I2CDeviceInUseError  # type: ignore

    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        print(f"Unknown channel: {channel_name!r}")
        return False

    info = channels[channel_name]
    cal = info.calibration
    current_min = cal['min_voltage']
    current_max = cal['max_voltage']
    midpoint = (current_min + current_max) / 2.0

    print(f"\n--- End-Stop Averaging: {channel_name} ---")
    print(f"Current calibration: Min {current_min:+.4f}V  Max {current_max:+.4f}V  "
          f"Midpoint {midpoint:+.4f}V")
    print(f"Move sensor from max to min {endstop_sample_count} times.")
    print("Press Ctrl+C to cancel.\n")

    try:
        i2c_lock = I2CLock(info.adc_address)
        i2c_lock.acquire()
    except I2CDeviceInUseError as e:
        print(str(e))
        return False

    try:
        ch = _open_adc_channel(info)

        max_samples, min_samples = [], []
        initial_voltage = ch.voltage
        looking_for = 'max' if initial_voltage > midpoint else 'min'
        current_extreme = initial_voltage
        had_first_crossing = False
        latest_max = latest_min = None

        display_interval = 0.2
        last_display = time.time()
        sample_count = 0
        current_voltage = initial_voltage

        # Optional Enter-key early exit
        done_flag = threading.Event()

        def wait_for_enter():
            input()
            done_flag.set()

        enter_thread = threading.Thread(target=wait_for_enter, daemon=True)
        enter_thread.start()

        try:
            while (len(max_samples) < endstop_sample_count or
                   len(min_samples) < endstop_sample_count) and not done_flag.is_set():

                voltage = ch.voltage
                sample_count += 1
                current_voltage = voltage

                if looking_for == 'max':
                    if voltage > current_extreme:
                        current_extreme = voltage
                    if voltage <= midpoint:
                        if had_first_crossing and len(max_samples) < endstop_sample_count:
                            max_samples.append(current_extreme)
                            latest_max = current_extreme
                            ts = time.strftime('%H:%M:%S')
                            print(f'\n[{ts}] MAX #{len(max_samples)}: {current_extreme:.4f}V')
                        had_first_crossing = True
                        looking_for = 'min'
                        current_extreme = voltage
                else:
                    if voltage < current_extreme:
                        current_extreme = voltage
                    if voltage > midpoint:
                        if had_first_crossing and len(min_samples) < endstop_sample_count:
                            min_samples.append(current_extreme)
                            latest_min = current_extreme
                            ts = time.strftime('%H:%M:%S')
                            print(f'\n[{ts}] MIN #{len(min_samples)}: {current_extreme:.4f}V')
                        had_first_crossing = True
                        looking_for = 'max'
                        current_extreme = voltage

                now = time.time()
                if now - last_display >= display_interval:
                    side = 'ABOVE' if looking_for == 'max' else 'BELOW'
                    max_s = f"{len(max_samples)}/{endstop_sample_count}"
                    if latest_max is not None:
                        max_s += f" (last {latest_max:.4f}V)"
                    min_s = f"{len(min_samples)}/{endstop_sample_count}"
                    if latest_min is not None:
                        min_s += f" (last {latest_min:.4f}V)"
                    print(f'\r{current_voltage:+.4f}V [{side}] | '
                          f'Maxes: {max_s} | Mins: {min_s}   ',
                          end='', flush=True)
                    elapsed = now - last_display
                    last_display = now
                    sample_count = 0

        except KeyboardInterrupt:
            print('\n\nCalibration cancelled.')
            return False

        print('\n')

        if len(max_samples) < endstop_sample_count or len(min_samples) < endstop_sample_count:
            print(f'Incomplete: {len(max_samples)} maxima, {len(min_samples)} minima collected.')
            return False

        avg_max = sum(max_samples) / len(max_samples)
        avg_min = sum(min_samples) / len(min_samples)

        print(f'Results for {channel_name}:')
        print(f'  {len(max_samples)} maxima avg: {avg_max:.4f}V '
              f'(range {min(max_samples):.4f}..{max(max_samples):.4f}V)')
        print(f'  {len(min_samples)} minima avg: {avg_min:.4f}V '
              f'(range {min(min_samples):.4f}..{max(min_samples):.4f}V)')
        print(f'  Final calibration range: {avg_max - avg_min:.4f}V')

        if avg_max - avg_min < 0.1:
            print('  WARNING: Small range detected')

        confirm = input('\nApply these values? (y/N): ').strip().lower()
        if confirm == 'y':
            save_calibration(channel_name, avg_min, avg_max, calibrate_json)
            print(f'✓ Calibration saved for {channel_name}')
            return True
        print('✗ Calibration skipped')
        return False

    finally:
        i2c_lock.release()


def _cli_monitor_channel(channel_name: str, calibrate_json: str) -> None:
    """Continuously display live voltage + calibrated output until a key is pressed."""
    _ensure_beertaps_on_path(calibrate_json)
    from i2c_lock import I2CLock, I2CDeviceInUseError  # type: ignore

    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        print(f"Unknown channel: {channel_name!r}")
        return

    info = channels[channel_name]
    print('\nMonitoring (press any key to stop)...')

    try:
        i2c_lock = I2CLock(info.adc_address)
        i2c_lock.acquire()
    except I2CDeviceInUseError as e:
        print(str(e))
        return

    try:
        ch = _open_adc_channel(info)
        cal = info.calibration
        display_interval = 0.2
        last_display = time.time()
        sample_count = 0

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while True:
                if select.select([sys.stdin], [], [], 0)[0]:
                    sys.stdin.read(1)
                    break
                voltage = ch.voltage
                raw = ch.value
                sample_count += 1
                now = time.time()
                if now - last_display >= display_interval:
                    calibrated = beertap_calibration_core._apply_calibration(
                        voltage, cal['min_voltage'], cal['max_voltage'])
                    elapsed = now - last_display
                    hz = sample_count / elapsed if elapsed > 0 else 0
                    print(f'\rVoltage {voltage:+.4f}V (raw {raw:5d}) → '
                          f'output {calibrated:+.4f} ({hz:.0f} Hz)   ',
                          end='', flush=True)
                    last_display = now
                    sample_count = 0
        except KeyboardInterrupt:
            pass
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            print('\n')

    finally:
        i2c_lock.release()


def _calibrate_channel_interactive(channel_name: str, calibrate_json: str,
                                   endstop_sample_count: int) -> None:
    """Full interactive calibration menu for one channel."""
    channels = load_all_channels(calibrate_json)
    if channel_name not in channels:
        print(f"Unknown channel: {channel_name!r}")
        return

    info = channels[channel_name]
    cal = info.calibration
    print(f'\n--- Calibrating {channel_name} ---')
    print(f'Current calibration: Min {cal["min_voltage"]:.4f}V  Max {cal["max_voltage"]:.4f}V')

    while True:
        print('\nOptions:')
        print('  A. Min-Max Capture (sweep through full range, press Enter when done)')
        print('  B. End-Stop Averaging (N midpoint crossings)')
        print('  1. Set current reading as MINIMUM (−1.0)')
        print('  2. Set current reading as MAXIMUM (+1.0)')
        print('  3. Set custom MIN voltage')
        print('  4. Set custom MAX voltage')
        print('  5. Monitor live readings')
        print('  Q. Done')

        choice = input('\nChoice: ').strip().upper()

        if choice == 'A':
            _cli_minmax_capture(channel_name, calibrate_json)
            # Reload calibration to show updated values
            channels = load_all_channels(calibrate_json)
            info = channels.get(channel_name)
            if info:
                cal = info.calibration
                print(f'Current calibration: Min {cal["min_voltage"]:.4f}V  '
                      f'Max {cal["max_voltage"]:.4f}V')

        elif choice == 'B':
            _cli_endstop_averaging(channel_name, calibrate_json, endstop_sample_count)
            channels = load_all_channels(calibrate_json)
            info = channels.get(channel_name)
            if info:
                cal = info.calibration
                print(f'Current calibration: Min {cal["min_voltage"]:.4f}V  '
                      f'Max {cal["max_voltage"]:.4f}V')

        elif choice == '1':
            try:
                voltage, _ = read_voltage(channel_name, calibrate_json)
                channels = load_all_channels(calibrate_json)
                info = channels[channel_name]
                cal = info.calibration
                save_calibration(channel_name, voltage, cal['max_voltage'], calibrate_json)
                print(f'Set MIN to {voltage:.4f}V and saved')
            except Exception as e:
                print(f'Error: {e}')

        elif choice == '2':
            try:
                voltage, _ = read_voltage(channel_name, calibrate_json)
                channels = load_all_channels(calibrate_json)
                info = channels[channel_name]
                cal = info.calibration
                save_calibration(channel_name, cal['min_voltage'], voltage, calibrate_json)
                print(f'Set MAX to {voltage:.4f}V and saved')
            except Exception as e:
                print(f'Error: {e}')

        elif choice == '3':
            try:
                value = float(input('Enter MIN voltage: '))
                channels = load_all_channels(calibrate_json)
                info = channels[channel_name]
                cal = info.calibration
                save_calibration(channel_name, value, cal['max_voltage'], calibrate_json)
                print(f'Set MIN to {value:.4f}V and saved')
            except ValueError:
                print('Invalid value')

        elif choice == '4':
            try:
                value = float(input('Enter MAX voltage: '))
                channels = load_all_channels(calibrate_json)
                info = channels[channel_name]
                cal = info.calibration
                save_calibration(channel_name, cal['min_voltage'], value, calibrate_json)
                print(f'Set MAX to {value:.4f}V and saved')
            except ValueError:
                print('Invalid value')

        elif choice == '5':
            _cli_monitor_channel(channel_name, calibrate_json)

        elif choice == 'Q':
            break
        else:
            print('Invalid choice')

    # Show final calibration
    channels = load_all_channels(calibrate_json)
    if channel_name in channels:
        cal = channels[channel_name].calibration
        print(f'\nFinal calibration for {channel_name}: '
              f'Min {cal["min_voltage"]:.4f}V  Max {cal["max_voltage"]:.4f}V')


# ---------------------------------------------------------------------------
# Main interactive loop
# ---------------------------------------------------------------------------

def run_interactive(calibrate_json: str = DEFAULT_CALIBRATE_JSON) -> None:
    try:
        with open(calibrate_json) as f:
            master = json.load(f)
    except FileNotFoundError:
        print(f'Error: {calibrate_json!r} not found')
        sys.exit(1)

    endstop_sample_count = master.get('endstop_sample_count', 20)

    print('\n' + '=' * 70)
    print('Unified ADC Calibration Tool')
    print('=' * 70)

    while True:
        try:
            channels = load_all_channels(calibrate_json)
        except Exception as e:
            print(f'Error loading channels: {e}')
            sys.exit(1)

        sorted_names = sorted(channels.keys())
        print('\nAvailable channels:')
        for i, name in enumerate(sorted_names, 1):
            cal = channels[name].calibration
            print(f'  {i}. {name}  '
                  f'(min {cal["min_voltage"]:+.4f}V, max {cal["max_voltage"]:+.4f}V)')

        print('\nOptions:')
        print('  [name] or [number]: calibrate that channel')
        print('  R: read current values from all channels')
        print('  Q: quit')

        choice = input('\nChoice: ').strip()

        if choice.upper() == 'R':
            _print_all_current_values(calibrate_json)

        elif choice.upper() == 'Q':
            print('Exiting')
            break

        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sorted_names):
                _calibrate_channel_interactive(sorted_names[idx], calibrate_json,
                                               endstop_sample_count)
            else:
                print('Invalid channel number')

        elif choice in channels:
            _calibrate_channel_interactive(choice, calibrate_json, endstop_sample_count)

        else:
            print(f'Unknown channel: {choice!r}')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Unified ADS1115 ADC Calibration Tool')
    parser.add_argument('--config', default=DEFAULT_CALIBRATE_JSON,
                        help='Master config file (default: calibrate.json)')
    parser.add_argument('--channel', type=str,
                        help='Calibrate specific channel by name (e.g. tap1)')
    args = parser.parse_args()

    if not __import__('os').path.exists(args.config):
        print(f'Error: {args.config!r} not found')
        sys.exit(1)

    if args.channel:
        with open(args.config) as f:
            master = __import__('json').load(f)
        endstop_sample_count = master.get('endstop_sample_count', 20)
        _calibrate_channel_interactive(args.channel, args.config, endstop_sample_count)
    else:
        run_interactive(args.config)


if __name__ == '__main__':
    main()
