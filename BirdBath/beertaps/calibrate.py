#!/usr/bin/env python3
"""
Unified ADS1115 Calibration Tool
Calibrates channels across multiple ADC config files by channel name
Loads configuration from calibrate.json
"""

import json
import argparse
import time
import os
import sys
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

from i2c_lock import I2CLock, I2CDeviceInUseError


class UnifiedCalibrator:
    def __init__(self, master_config_file='calibrate.json'):
        """Initialize unified calibrator with master configuration file"""
        self.master_config_file = master_config_file
        self.channel_map = {}  # Maps channel name to (config_file, channel_index, full_config)
        self.active_locks = {}  # Maps I2C address to I2CLock object
        self.load_all_configs()
        
    def load_all_configs(self):
        """Load master config and all referenced ADC config files"""
        # Load master config
        with open(self.master_config_file, 'r') as f:
            master_config = json.load(f)
        
        self.config_files = master_config['config_files']
        self.calibration_margin_percent = master_config.get('calibration_margin_percent', 0.0)
        self.endstop_sample_count = master_config.get('endstop_sample_count', 20)
        
        # Load each ADC config and build channel map
        for config_file in self.config_files:
            if not os.path.exists(config_file):
                print(f"Warning: Config file '{config_file}' not found, skipping")
                continue
            
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Map each channel name to its config file and index
            for i, channel_config in enumerate(config['channels']):
                channel_name = channel_config['name']
                self.channel_map[channel_name] = {
                    'config_file': config_file,
                    'channel_index': i,
                    'adc_config': config,
                    'channel_config': channel_config
                }
        
        if not self.channel_map:
            print("Error: No channels found in any config files")
            sys.exit(1)
        
        print(f"Loaded {len(self.channel_map)} channels from {len(self.config_files)} config files")
    
    def _acquire_lock_for_address(self, address):
        """Acquire I2C lock for an address if not already held"""
        # Normalize address
        if isinstance(address, str):
            address = int(address, 16)
        
        if address in self.active_locks:
            return True  # Already have the lock
        
        try:
            lock = I2CLock(address)
            lock.acquire()
            self.active_locks[address] = lock
            return True
        except I2CDeviceInUseError as e:
            print(str(e))
            return False
    
    def _release_lock_for_address(self, address):
        """Release I2C lock for an address"""
        if isinstance(address, str):
            address = int(address, 16)
        
        if address in self.active_locks:
            self.active_locks[address].release()
            del self.active_locks[address]
    
    def _release_all_locks(self):
        """Release all held I2C locks"""
        for lock in self.active_locks.values():
            lock.release()
        self.active_locks.clear()
    
    def setup_adc_for_channel(self, channel_name, acquire_lock=True):
        """Initialize ADC for a specific channel"""
        if channel_name not in self.channel_map:
            print(f"Error: Channel '{channel_name}' not found")
            return None
        
        channel_info = self.channel_map[channel_name]
        adc_config = channel_info['adc_config']
        
        try:
            # Get address
            address = adc_config['address']
            if isinstance(address, str):
                address = int(address, 16)
            
            # Acquire I2C lock if requested
            if acquire_lock:
                if not self._acquire_lock_for_address(address):
                    return None
            
            # Create I2C bus
            i2c = busio.I2C(board.SCL, board.SDA)
            
            # Create ADS object with configured address
            ads = ADS.ADS1115(i2c, address=address)
            ads.gain = adc_config['gain']
            
            # Create channel object for the specific channel
            ch_config = channel_info['channel_config']
            pos_pin = getattr(ADS, ch_config['positive_pin'])
            neg_pin = getattr(ADS, ch_config['negative_pin'])
            
            channel = AnalogIn(ads, pos_pin, neg_pin)
            
            return {
                'channel': channel,
                'config': ch_config,
                'name': channel_name,
                'config_file': channel_info['config_file'],
                'address': address
            }
            
        except Exception as e:
            print(f"Error initializing ADC for '{channel_name}': {e}")
            return None
    
    def save_channel_config(self, channel_name):
        """Save configuration for a specific channel back to its config file"""
        channel_info = self.channel_map[channel_name]
        config_file = channel_info['config_file']
        
        # Reload the entire config file
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        # Update the specific channel
        channel_index = channel_info['channel_index']
        config['channels'][channel_index] = channel_info['channel_config']
        
        # Save back to file
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
    
    def read_all_current_values(self):
        """Read and display current values from all channels"""
        print("\n" + "="*70)
        print("Current ADC Readings - All Channels")
        print("="*70)
        
        # Group channels by config file and get ADC address
        by_config = {}
        config_addresses = {}
        for name, info in self.channel_map.items():
            config_file = info['config_file']
            if config_file not in by_config:
                by_config[config_file] = []
                # Get ADC address from config
                address = info['adc_config']['address']
                if isinstance(address, str):
                    address = int(address, 16)
                config_addresses[config_file] = address
            by_config[config_file].append(name)
        
        # Display grouped by config file
        for config_file in sorted(by_config.keys()):
            address = config_addresses[config_file]
            adc_address_hex = hex(address)
            
            # Try to acquire lock for this ADC
            if not self._acquire_lock_for_address(address):
                print(f"\n{config_file} (ADC {adc_address_hex}): SKIPPED - device in use")
                continue
            
            print(f"\n{config_file} (ADC {adc_address_hex}):")
            for channel_name in sorted(by_config[config_file]):
                ch_info = self.setup_adc_for_channel(channel_name, acquire_lock=False)
                if ch_info:
                    channel = ch_info['channel']
                    config = ch_info['config']
                    
                    voltage = channel.voltage
                    raw = channel.value
                    
                    cal = config['calibration']
                    min_v = cal['min_voltage']
                    max_v = cal['max_voltage']
                    
                    # Calculate calibrated value with clamping (same as adc_reader.py)
                    if max_v != min_v:
                        normalized = (voltage - min_v) / (max_v - min_v)
                        calibrated = 2.0 * normalized - 1.0
                    else:
                        calibrated = 0.0
                    
                    # Clamp output to exactly -1.0 to 1.0 range
                    calibrated = max(-1.0, min(1.0, calibrated))
                    
                    print(f"  {channel_name:10s}: Calibration: [{min_v:+.4f}V to {max_v:+.4f}V] | "
                          f"Current: {voltage:+.4f}V | Output: {calibrated:+.4f}")
            
            # Release lock for this ADC before moving to next
            self._release_lock_for_address(address)
        
        print("\n" + "="*70)
    
    def auto_calibrate_minmax_capture(self, channel_name, show_header=True):
        """Min-Max Capture calibration mode - tracks min/max while user moves control"""
        ch_info = self.setup_adc_for_channel(channel_name)
        if not ch_info:
            return False
        
        channel = ch_info['channel']
        config = ch_info['config']
        address = ch_info['address']
        
        if show_header:
            print(f"\n" + "="*60)
            print(f"AUTOMATIC CALIBRATION - {channel_name}")
            print("="*60)
        else:
            print(f"\n--- Calibrating {channel_name} (Min-Max Capture) ---")
        
        # Get current calibration and reading
        cal = config['calibration']
        current_voltage = channel.voltage
        print(f"Current calibration: Min: {cal['min_voltage']:+.4f}V | Max: {cal['max_voltage']:+.4f}V | Current reading: {current_voltage:+.4f}V")
        
        # Initialize with current reading
        initial_voltage = current_voltage
        tracked_min = initial_voltage
        tracked_max = initial_voltage
        
        print("\nMove your control through its FULL range")
        print("Press Enter when done, Ctrl+C to cancel\n")
        
        # Start a thread to check for Enter key
        import threading
        done_flag = threading.Event()
        
        def wait_for_enter():
            input()
            done_flag.set()
        
        enter_thread = threading.Thread(target=wait_for_enter)
        enter_thread.daemon = True
        enter_thread.start()
        
        # Display update timing
        display_interval = 0.2  # Update display 5 times per second
        last_display_time = time.time()
        sample_count = 0
        
        # Variables for display
        current_voltage = initial_voltage
        current_raw = 0
        
        try:
            while not done_flag.is_set():
                # Sample as fast as possible
                voltage = channel.voltage
                raw = channel.value
                sample_count += 1
                
                # Update tracked min/max from every sample
                if voltage < tracked_min:
                    tracked_min = voltage
                if voltage > tracked_max:
                    tracked_max = voltage
                
                # Store current values for display
                current_voltage = voltage
                current_raw = raw
                
                # Only update display at controlled rate
                current_time = time.time()
                if current_time - last_display_time >= display_interval:
                    # Calculate what the calibrated value would be
                    if tracked_max != tracked_min:
                        normalized = (current_voltage - tracked_min) / (tracked_max - tracked_min)
                        calibrated = 2.0 * normalized - 1.0
                    else:
                        calibrated = 0.0
                    
                    # Calculate sampling rate
                    elapsed = current_time - last_display_time
                    samples_per_sec = sample_count / elapsed if elapsed > 0 else 0
                    
                    # Display current status
                    print(f"\rCurrent: {current_voltage:.4f}V | "
                          f"Min: {tracked_min:.4f}V | "
                          f"Max: {tracked_max:.4f}V | "
                          f"Range: {tracked_max - tracked_min:.4f}V | "
                          f"Output: {calibrated:+.4f} | "
                          f"({samples_per_sec:.0f} Hz)   ", 
                          end='', flush=True)
                    
                    # Reset counters for next display cycle
                    last_display_time = current_time
                    sample_count = 0
                
        except KeyboardInterrupt:
            print("\n\nCalibration cancelled")
            return False
        
        print(f"\n\nResults for {channel_name}:")
        print(f"  Measured Min: {tracked_min:.4f}V | Max: {tracked_max:.4f}V | Range: {tracked_max - tracked_min:.4f}V")
        
        # Apply calibration margin to contract the range (ensure full -1.0 to +1.0 is reachable)
        voltage_range = tracked_max - tracked_min
        margin_amount = voltage_range * (self.calibration_margin_percent / 100.0)
        adjusted_min = tracked_min + margin_amount
        adjusted_max = tracked_max - margin_amount
        
        if self.calibration_margin_percent > 0:
            print(f"  Calibration margin: {self.calibration_margin_percent}% -> contracting range by {margin_amount:.4f}V on each side")
            print(f"  Adjusted Min: {adjusted_min:.4f}V | Max: {adjusted_max:.4f}V")
        
        if tracked_max - tracked_min < 0.1:
            print("  WARNING: Small range detected - may not have moved through full range")
        
        confirm = input("Apply these values? (y/N): ").strip().lower()
        
        result = False
        if confirm == 'y':
            config['calibration']['min_voltage'] = adjusted_min
            config['calibration']['max_voltage'] = adjusted_max
            self.save_channel_config(channel_name)
            print(f"✓ Calibration saved for {channel_name}")
            result = True
        else:
            print("✗ Calibration skipped")
        
        # Release the lock for this address
        self._release_lock_for_address(address)
        return result
    
    def auto_calibrate_endstop_averaging(self, channel_name, show_header=True):
        """End-Stop Averaging calibration mode - records extremes during multiple crossings"""
        ch_info = self.setup_adc_for_channel(channel_name)
        if not ch_info:
            return False
        
        channel = ch_info['channel']
        config = ch_info['config']
        address = ch_info['address']
        
        if show_header:
            print(f"\n" + "="*60)
            print(f"END-STOP AVERAGING CALIBRATION - {channel_name}")
            print("="*60)
        else:
            print(f"\n--- Calibrating {channel_name} (End-Stop Averaging) ---")
        
        # Calculate midpoint from current calibration
        cal = config['calibration']
        current_min = cal['min_voltage']
        current_max = cal['max_voltage']
        midpoint = (current_min + current_max) / 2.0
        
        # Get current reading
        current_voltage = channel.voltage
        print(f"Current calibration: Min: {current_min:+.4f}V | Max: {current_max:+.4f}V | Current reading: {current_voltage:+.4f}V")
        
        print(f"Using midpoint: {midpoint:.4f}V")
        print(f"Move sensor from max to min {self.endstop_sample_count} times")
        print("Press Ctrl+C to cancel\n")
        
        # Initialize tracking variables
        max_samples = []
        min_samples = []
        
        # Get initial reading to determine starting state
        initial_voltage = channel.voltage
        
        # Single state variable: what are we currently looking for?
        if initial_voltage > midpoint:
            looking_for = 'max'  # Above midpoint, looking for maximum
            current_extreme = initial_voltage
        else:
            looking_for = 'min'  # Below midpoint, looking for minimum
            current_extreme = initial_voltage
        
        had_first_crossing = False  # Don't record until after first midpoint crossing
        
        # Start a thread to check for Enter key (optional early exit)
        import threading
        done_flag = threading.Event()
        
        def wait_for_enter():
            input()
            done_flag.set()
        
        enter_thread = threading.Thread(target=wait_for_enter)
        enter_thread.daemon = True
        enter_thread.start()
        
        # Display update timing
        display_interval = 0.2  # Update display 5 times per second
        last_display_time = time.time()
        sample_count = 0
        
        # Variables for display
        current_voltage = initial_voltage
        latest_max = None
        latest_min = None
        
        try:
            while (len(max_samples) < self.endstop_sample_count or 
                   len(min_samples) < self.endstop_sample_count) and not done_flag.is_set():
                
                # Sample as fast as possible
                voltage = channel.voltage
                sample_count += 1
                current_voltage = voltage
                
                # Update current extreme based on what we're looking for
                if looking_for == 'max':
                    # Looking for maximum - update if we find a higher value
                    if voltage > current_extreme:
                        current_extreme = voltage
                    # Check if we crossed below midpoint
                    if voltage <= midpoint:
                        # Crossed below - record max if we've had first crossing
                        if had_first_crossing and len(max_samples) < self.endstop_sample_count:
                            max_samples.append(current_extreme)
                            latest_max = current_extreme
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"\n[{timestamp}] Recorded MAXIMUM #{len(max_samples)}: {current_extreme:.4f}V (crossed from ABOVE to BELOW)")
                        
                        # Mark first crossing and switch to looking for minimum
                        if not had_first_crossing:
                            had_first_crossing = True
                        looking_for = 'min'
                        current_extreme = voltage
                else:  # looking_for == 'min'
                    # Looking for minimum - update if we find a lower value
                    if voltage < current_extreme:
                        current_extreme = voltage
                    # Check if we crossed above midpoint
                    if voltage > midpoint:
                        # Crossed above - record min if we've had first crossing
                        if had_first_crossing and len(min_samples) < self.endstop_sample_count:
                            min_samples.append(current_extreme)
                            latest_min = current_extreme
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"\n[{timestamp}] Recorded MINIMUM #{len(min_samples)}: {current_extreme:.4f}V (crossed from BELOW to ABOVE)")
                        
                        # Mark first crossing and switch to looking for maximum
                        if not had_first_crossing:
                            had_first_crossing = True
                        looking_for = 'max'
                        current_extreme = voltage
                
                # Update display at controlled rate
                current_time = time.time()
                if current_time - last_display_time >= display_interval:
                    # Calculate sampling rate
                    elapsed = current_time - last_display_time
                    samples_per_sec = sample_count / elapsed if elapsed > 0 else 0
                    
                    # Build display string
                    max_str = f"{len(max_samples)}/{self.endstop_sample_count}"
                    if latest_max is not None:
                        max_str += f" (latest: {latest_max:.4f}V)"
                    
                    min_str = f"{len(min_samples)}/{self.endstop_sample_count}"
                    if latest_min is not None:
                        min_str += f" (latest: {latest_min:.4f}V)"
                    
                    side_str = "ABOVE" if looking_for == 'max' else "BELOW"
                    
                    print(f"\rCurrent: {current_voltage:.4f}V [{side_str}] Midpoint: {midpoint:.4f}V | "
                          f"Maximums: {max_str} | Minimums: {min_str} | "
                          f"({samples_per_sec:.0f} Hz)   ",
                          end='', flush=True)
                    
                    # Reset counters for next display cycle
                    last_display_time = current_time
                    sample_count = 0
        
        except KeyboardInterrupt:
            print("\n\nCalibration cancelled")
            return False
        
        print("\n")
        
        # Check if we have enough samples
        if len(max_samples) < self.endstop_sample_count or len(min_samples) < self.endstop_sample_count:
            print(f"Incomplete: Only collected {len(max_samples)} maximums and {len(min_samples)} minimums")
            print("Need to complete more crossings. Calibration cancelled.")
            self._release_lock_for_address(address)
            return False
        
        # Calculate averages
        avg_max = sum(max_samples) / len(max_samples)
        avg_min = sum(min_samples) / len(min_samples)
        
        print(f"Results for {channel_name}:")
        print(f"  Collected {len(max_samples)} maximums: avg = {avg_max:.4f}V (range: {min(max_samples):.4f}V to {max(max_samples):.4f}V)")
        print(f"  Collected {len(min_samples)} minimums: avg = {avg_min:.4f}V (range: {min(min_samples):.4f}V to {max(min_samples):.4f}V)")
        print(f"  Final calibration range: {avg_max - avg_min:.4f}V")
        print(f"  (No calibration margin applied for end-stop averaging)")
        
        if avg_max - avg_min < 0.1:
            print("  WARNING: Small range detected")
        
        confirm = input("\nApply these values? (y/N): ").strip().lower()
        
        result = False
        if confirm == 'y':
            config['calibration']['min_voltage'] = avg_min
            config['calibration']['max_voltage'] = avg_max
            self.save_channel_config(channel_name)
            print(f"✓ Calibration saved for {channel_name}")
            result = True
        else:
            print("✗ Calibration skipped")
        
        # Release the lock for this address
        self._release_lock_for_address(address)
        return result
    
    def calibrate_channel(self, channel_name):
        """Interactive calibration for a specific channel"""
        ch_info = self.setup_adc_for_channel(channel_name)
        if not ch_info:
            return
        
        channel = ch_info['channel']
        config = ch_info['config']
        address = ch_info['address']
        
        print(f"\n--- Calibrating {channel_name} ---")
        current_voltage = channel.voltage
        print("Current calibration values:")
        print(f"  Min: {config['calibration']['min_voltage']:.3f}V")
        print(f"  Max: {config['calibration']['max_voltage']:.3f}V")
        print(f"  Current reading: {current_voltage:+.4f}V")
        
        while True:
            print("\nOptions:")
            print("  A. End-Stop Averaging (automatic)")
            print("  B. Min-Max Capture (automatic)")
            print("  1. Set current reading as MINIMUM (-1.0)")
            print("  2. Set current reading as MAXIMUM (+1.0)")
            print("  3. Set custom MIN value")
            print("  4. Set custom MAX value")
            print("  5. Monitor current reading")
            print("  Q. Done with this channel")
            
            choice = input("\nChoice: ").strip().upper()
            
            if choice == 'A':
                if self.auto_calibrate_endstop_averaging(channel_name, show_header=False):
                    # Show updated values after auto calibration
                    print(f"\nCurrent calibration for {channel_name}:")
                    print(f"  Min: {config['calibration']['min_voltage']:.4f}V")
                    print(f"  Max: {config['calibration']['max_voltage']:.4f}V")
                
            elif choice == 'B':
                if self.auto_calibrate_minmax_capture(channel_name, show_header=False):
                    # Show updated values after auto calibration
                    print(f"\nCurrent calibration for {channel_name}:")
                    print(f"  Min: {config['calibration']['min_voltage']:.4f}V")
                    print(f"  Max: {config['calibration']['max_voltage']:.4f}V")
                
            elif choice == '1':
                voltage = channel.voltage
                config['calibration']['min_voltage'] = voltage
                self.save_channel_config(channel_name)
                print(f"Set MIN to current reading: {voltage:.4f}V and saved")
                
            elif choice == '2':
                voltage = channel.voltage
                config['calibration']['max_voltage'] = voltage
                self.save_channel_config(channel_name)
                print(f"Set MAX to current reading: {voltage:.4f}V and saved")
                
            elif choice == '3':
                try:
                    value = float(input("Enter MIN voltage value: "))
                    config['calibration']['min_voltage'] = value
                    self.save_channel_config(channel_name)
                    print(f"Set MIN to {value:.4f}V and saved")
                except ValueError:
                    print("Invalid value")
                    
            elif choice == '4':
                try:
                    value = float(input("Enter MAX voltage value: "))
                    config['calibration']['max_voltage'] = value
                    self.save_channel_config(channel_name)
                    print(f"Set MAX to {value:.4f}V and saved")
                except ValueError:
                    print("Invalid value")
                    
            elif choice == '5':
                print("\nMonitoring (press any key to stop)...")
                
                # Display update timing
                display_interval = 0.2  # Update display 5 times per second
                last_display_time = time.time()
                sample_count = 0
                
                # Set up non-blocking input
                import select
                import termios
                import tty
                
                old_settings = termios.tcgetattr(sys.stdin)
                try:
                    tty.setcbreak(sys.stdin.fileno())
                    
                    while True:
                        # Check if any key was pressed (non-blocking)
                        if select.select([sys.stdin], [], [], 0)[0]:
                            # Key pressed, read it and exit
                            sys.stdin.read(1)
                            break
                        
                        # Sample as fast as possible
                        voltage = channel.voltage
                        raw = channel.value
                        sample_count += 1
                        
                        # Only update display at controlled rate
                        current_time = time.time()
                        if current_time - last_display_time >= display_interval:
                            cal = config['calibration']
                            min_v = cal['min_voltage']
                            max_v = cal['max_voltage']
                            
                            if max_v != min_v:
                                normalized = (voltage - min_v) / (max_v - min_v)
                                calibrated = 2.0 * normalized - 1.0
                            else:
                                calibrated = 0.0
                            
                            # Clamp output to exactly -1.0 to 1.0 range (same as adc_reader.py)
                            calibrated = max(-1.0, min(1.0, calibrated))
                            
                            # Calculate sampling rate
                            elapsed = current_time - last_display_time
                            samples_per_sec = sample_count / elapsed if elapsed > 0 else 0
                            
                            print(f"\rVoltage: {voltage:+.4f}V (raw: {raw:5d}) -> "
                                  f"Output: {calibrated:+.4f} ({samples_per_sec:.0f} Hz)   ", 
                                  end='', flush=True)
                            
                            # Reset counters for next display cycle
                            last_display_time = current_time
                            sample_count = 0
                            
                except KeyboardInterrupt:
                    pass
                finally:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    print("\n")
                    
            elif choice == 'Q':
                break
            else:
                print("Invalid choice")
        
        print(f"\nFinal calibration for {channel_name}:")
        print(f"  Min: {config['calibration']['min_voltage']:.4f}V")
        print(f"  Max: {config['calibration']['max_voltage']:.4f}V")
        
        # Release the lock for this address
        self._release_lock_for_address(address)
    
    def run_interactive(self):
        """Run interactive calibration session"""
        print("\n" + "="*70)
        print(f"Unified ADC Calibration Tool")
        print("="*70)
        
        while True:
            print("\nAvailable channels:")
            sorted_names = sorted(self.channel_map.keys())
            for i, name in enumerate(sorted_names, 1):
                config_file = self.channel_map[name]['config_file']
                print(f"  {i}. {name} ({config_file})")
            
            print("\nOptions:")
            print("  [channel name]: Calibrate specific channel by name (e.g., 'tap1')")
            print("  [number]: Calibrate channel by number from list above")
            print("  R: Read current values")
            print("  Q: Quit")
            
            choice = input("\nChoice: ").strip()
            
            if choice.upper() == 'R':
                self.read_all_current_values()
                
            elif choice.upper() == 'Q':
                print("Exiting")
                break
            
            elif choice.isdigit():
                channel_index = int(choice) - 1
                if 0 <= channel_index < len(sorted_names):
                    channel_name = sorted_names[channel_index]
                    self.calibrate_channel(channel_name)
                else:
                    print("Invalid channel number")
            
            elif choice in self.channel_map:
                self.calibrate_channel(choice)
            
            else:
                print(f"Unknown channel: {choice}")


def main():
    parser = argparse.ArgumentParser(description='Unified ADS1115 ADC Calibration Tool')
    parser.add_argument('--config', default='calibrate.json',
                       help='Path to master configuration file (default: calibrate.json)')
    parser.add_argument('--channel', type=str,
                       help='Calibrate specific channel by name (e.g., tap1)')
    
    args = parser.parse_args()
    
    # Check if config file exists
    if not os.path.exists(args.config):
        print(f"Error: Master configuration file '{args.config}' not found")
        sys.exit(1)
    
    calibrator = UnifiedCalibrator(args.config)
    
    if args.channel:
        # Single channel calibration mode - run interactive for that channel
        calibrator.calibrate_channel(args.channel)
    else:
        # Interactive mode
        calibrator.run_interactive()


if __name__ == "__main__":
    main()
