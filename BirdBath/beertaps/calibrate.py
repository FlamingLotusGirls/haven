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


class UnifiedCalibrator:
    def __init__(self, master_config_file='calibrate.json'):
        """Initialize unified calibrator with master configuration file"""
        self.master_config_file = master_config_file
        self.channel_map = {}  # Maps channel name to (config_file, channel_index, full_config)
        self.load_all_configs()
        
    def load_all_configs(self):
        """Load master config and all referenced ADC config files"""
        # Load master config
        with open(self.master_config_file, 'r') as f:
            master_config = json.load(f)
        
        self.config_files = master_config['config_files']
        self.calibration_margin_percent = master_config.get('calibration_margin_percent', 0.0)
        
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
    
    def setup_adc_for_channel(self, channel_name):
        """Initialize ADC for a specific channel"""
        if channel_name not in self.channel_map:
            print(f"Error: Channel '{channel_name}' not found")
            return None
        
        channel_info = self.channel_map[channel_name]
        adc_config = channel_info['adc_config']
        
        try:
            # Create I2C bus
            i2c = busio.I2C(board.SCL, board.SDA)
            
            # Create ADS object with configured address
            address = adc_config['address']
            if isinstance(address, str):
                address = int(address, 16)
            
            ads = ADS.ADS1115(i2c, address=address)
            ads.gain = adc_config['gain']
            
            # Create channel object for the specific channel
            ch_config = channel_info['channel_config']
            pos_pin = getattr(ADS, ch_config['positive_pin'])
            neg_pin = getattr(ADS, ch_config['negative_pin'])
            
            channel = AnalogIn(ads, pos_pin, neg_pin)
            
            print(f"ADC initialized at address {hex(address)} for channel '{channel_name}'")
            
            return {
                'channel': channel,
                'config': ch_config,
                'name': channel_name,
                'config_file': channel_info['config_file']
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
        
        # Group channels by config file
        by_config = {}
        for name, info in self.channel_map.items():
            config_file = info['config_file']
            if config_file not in by_config:
                by_config[config_file] = []
            by_config[config_file].append(name)
        
        # Display grouped by config file
        for config_file in sorted(by_config.keys()):
            print(f"\n{config_file}:")
            for channel_name in sorted(by_config[config_file]):
                ch_info = self.setup_adc_for_channel(channel_name)
                if ch_info:
                    channel = ch_info['channel']
                    config = ch_info['config']
                    
                    voltage = channel.voltage
                    raw = channel.value
                    
                    cal = config['calibration']
                    min_v = cal['min_voltage']
                    max_v = cal['max_voltage']
                    
                    # Calculate calibrated value
                    if max_v != min_v:
                        normalized = (voltage - min_v) / (max_v - min_v)
                        calibrated = 2.0 * normalized - 1.0
                    else:
                        calibrated = 0.0
                    
                    print(f"  {channel_name:10s}: {voltage:+.4f}V -> {calibrated:+.4f} "
                          f"(cal: [{min_v:.3f}V, {max_v:.3f}V])")
        
        print("\n" + "="*70)
    
    def auto_calibrate_channel(self, channel_name, show_header=True):
        """Automatic calibration mode - tracks min/max while user moves control"""
        ch_info = self.setup_adc_for_channel(channel_name)
        if not ch_info:
            return False
        
        channel = ch_info['channel']
        config = ch_info['config']
        
        if show_header:
            print(f"\n" + "="*60)
            print(f"AUTOMATIC CALIBRATION - {channel_name}")
            print("="*60)
        else:
            print(f"\n--- Calibrating {channel_name} ---")
        
        # Initialize with current reading
        initial_voltage = channel.voltage
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
        
        # Apply calibration margin to expand the range
        voltage_range = tracked_max - tracked_min
        margin_amount = voltage_range * (self.calibration_margin_percent / 100.0)
        adjusted_min = tracked_min - margin_amount
        adjusted_max = tracked_max + margin_amount
        
        if self.calibration_margin_percent > 0:
            print(f"  Calibration margin: {self.calibration_margin_percent}% -> expanding range by {margin_amount:.4f}V on each side")
            print(f"  Adjusted Min: {adjusted_min:.4f}V | Max: {adjusted_max:.4f}V")
        
        if tracked_max - tracked_min < 0.1:
            print("  WARNING: Small range detected - may not have moved through full range")
        
        confirm = input("Apply these values? (y/N): ").strip().lower()
        
        if confirm == 'y':
            config['calibration']['min_voltage'] = adjusted_min
            config['calibration']['max_voltage'] = adjusted_max
            self.save_channel_config(channel_name)
            print(f"✓ Calibration saved for {channel_name}")
            return True
        else:
            print("✗ Calibration skipped")
            return False
    
    def calibrate_channel(self, channel_name):
        """Interactive calibration for a specific channel"""
        ch_info = self.setup_adc_for_channel(channel_name)
        if not ch_info:
            return
        
        channel = ch_info['channel']
        config = ch_info['config']
        
        print(f"\n--- Calibrating {channel_name} ---")
        print("Current calibration values:")
        print(f"  Min: {config['calibration']['min_voltage']:.3f}V")
        print(f"  Max: {config['calibration']['max_voltage']:.3f}V")
        
        while True:
            print("\nOptions:")
            print("  A. AUTOMATIC calibration (recommended)")
            print("  1. Set current reading as MINIMUM (-1.0)")
            print("  2. Set current reading as MAXIMUM (+1.0)")
            print("  3. Set custom MIN value")
            print("  4. Set custom MAX value")
            print("  5. Monitor current reading")
            print("  Q. Done with this channel")
            
            choice = input("\nChoice: ").strip().upper()
            
            if choice == 'A':
                if self.auto_calibrate_channel(channel_name):
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
                print("\nMonitoring (press Ctrl+C to stop)...")
                
                # Display update timing
                display_interval = 0.2  # Update display 5 times per second
                last_display_time = time.time()
                sample_count = 0
                
                try:
                    while True:
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
                    print("\n")
                    
            elif choice == 'Q':
                break
            else:
                print("Invalid choice")
        
        print(f"\nFinal calibration for {channel_name}:")
        print(f"  Min: {config['calibration']['min_voltage']:.4f}V")
        print(f"  Max: {config['calibration']['max_voltage']:.4f}V")
    
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
    parser.add_argument('--auto', action='store_true',
                       help='Run automatic calibration for specified channel')
    
    args = parser.parse_args()
    
    # Check if config file exists
    if not os.path.exists(args.config):
        print(f"Error: Master configuration file '{args.config}' not found")
        sys.exit(1)
    
    calibrator = UnifiedCalibrator(args.config)
    
    if args.channel:
        # Single channel calibration mode
        if args.auto:
            calibrator.auto_calibrate_channel(args.channel)
        else:
            calibrator.calibrate_channel(args.channel)
    else:
        # Interactive mode
        calibrator.run_interactive()


if __name__ == "__main__":
    main()
