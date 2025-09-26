#!/usr/bin/env python3
"""
ADS1115 Calibration Tool
Helps set calibration values for ADC channels by reading current values
and updating the configuration file
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


class ADCCalibrator:
    def __init__(self, config_file):
        """Initialize calibrator with configuration file"""
        self.config_file = config_file
        self.load_config()
        self.setup_adc()
        
    def load_config(self):
        """Load configuration from JSON file"""
        with open(self.config_file, 'r') as f:
            self.config = json.load(f)
    
    def save_config(self):
        """Save configuration back to JSON file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def setup_adc(self):
        """Initialize I2C and ADC with configured address"""
        try:
            # Create I2C bus
            self.i2c = busio.I2C(board.SCL, board.SDA)
            
            # Create ADS object with configured address
            address = self.config['address']
            if isinstance(address, str):
                address = int(address, 16)
            
            self.ads = ADS.ADS1115(self.i2c, address=address)
            self.ads.gain = self.config['gain']
            
            # Create channel objects
            self.channels = []
            for ch_config in self.config['channels']:
                pos_pin = getattr(ADS, ch_config['positive_pin'])
                neg_pin = getattr(ADS, ch_config['negative_pin'])
                
                channel = AnalogIn(self.ads, pos_pin, neg_pin)
                
                self.channels.append({
                    'channel': channel,
                    'config': ch_config,
                    'name': ch_config['name']
                })
            
            print(f"ADC initialized at address {hex(address)}")
            
        except Exception as e:
            print(f"Error initializing ADC: {e}")
            sys.exit(1)
    
    def read_current_values(self):
        """Read and display current values from all channels"""
        print("\n" + "="*60)
        print("Current ADC Readings:")
        print("="*60)
        
        for i, ch_info in enumerate(self.channels):
            channel = ch_info['channel']
            name = ch_info['name']
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
            
            print(f"\nChannel {i+1}: {name}")
            print(f"  Current voltage: {voltage:.4f}V (raw: {raw})")
            print(f"  Current calibration: [{min_v:.3f}V, {max_v:.3f}V]")
            print(f"  Calibrated output: {calibrated:+.4f}")
            
        print("\n" + "="*60)
    
    def auto_calibrate_channel(self, channel_index, show_header=True):
        """Automatic calibration mode - tracks min/max while user moves control"""
        if channel_index >= len(self.channels):
            print(f"Invalid channel index: {channel_index}")
            return False
        
        ch_info = self.channels[channel_index]
        channel = ch_info['channel']
        name = ch_info['name']
        config = ch_info['config']
        
        if show_header:
            print(f"\n" + "="*60)
            print(f"AUTOMATIC CALIBRATION - {name}")
            print("="*60)
        else:
            print(f"\n--- Calibrating {name} ---")
        
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
        
        print(f"\n\nResults for {name}:")
        print(f"  Min: {tracked_min:.4f}V | Max: {tracked_max:.4f}V | Range: {tracked_max - tracked_min:.4f}V")
        
        if tracked_max - tracked_min < 0.1:
            print("  WARNING: Small range detected - may not have moved through full range")
        
        confirm = input("Apply these values? (y/N): ").strip().lower()
        
        if confirm == 'y':
            config['calibration']['min_voltage'] = tracked_min
            config['calibration']['max_voltage'] = tracked_max
            self.save_config()
            print(f"✓ Calibration saved for {name}")
            return True
        else:
            print("✗ Calibration skipped")
            return False
    
    def auto_calibrate_all(self):
        """Calibrate all channels in sequence automatically"""
        print("\n" + "="*60)
        print("AUTOMATIC CALIBRATION - ALL CHANNELS")
        print("="*60)
        print("\nThis will calibrate all channels in sequence.")
        print("For each channel:")
        print("  1. Move the control through its FULL range")
        print("  2. Press Enter when done")
        print("  3. Confirm to save values immediately")
        print("\nPress Ctrl+C at any time to cancel")
        
        results = []
        
        for i in range(len(self.channels)):
            success = self.auto_calibrate_channel(i, show_header=False)
            results.append(success)
            
            # Brief pause between channels
            if i < len(self.channels) - 1 and success:
                print("\nMoving to next channel...")
                time.sleep(1)
        
        # Summary
        print("\n" + "="*60)
        print("CALIBRATION COMPLETE")
        print("="*60)
        for i, ch_info in enumerate(self.channels):
            name = ch_info['name']
            if results[i]:
                cal = ch_info['config']['calibration']
                print(f"✓ {name}: [{cal['min_voltage']:.3f}V to {cal['max_voltage']:.3f}V]")
            else:
                print(f"✗ {name}: Not calibrated")
    
    def calibrate_channel(self, channel_index):
        """Interactive calibration for a specific channel"""
        if channel_index >= len(self.channels):
            print(f"Invalid channel index: {channel_index}")
            return
        
        ch_info = self.channels[channel_index]
        channel = ch_info['channel']
        name = ch_info['name']
        config = ch_info['config']
        
        print(f"\n--- Calibrating {name} ---")
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
            print("  6. Done with this channel")
            
            choice = input("\nChoice: ").strip().upper()
            
            if choice == 'A':
                if self.auto_calibrate_channel(channel_index):
                    # Show updated values after auto calibration
                    print(f"\nCurrent calibration for {name}:")
                    print(f"  Min: {config['calibration']['min_voltage']:.4f}V")
                    print(f"  Max: {config['calibration']['max_voltage']:.4f}V")
                
            elif choice == '1':
                voltage = channel.voltage
                config['calibration']['min_voltage'] = voltage
                self.save_config()
                print(f"Set MIN to current reading: {voltage:.4f}V and saved")
                
            elif choice == '2':
                voltage = channel.voltage
                config['calibration']['max_voltage'] = voltage
                self.save_config()
                print(f"Set MAX to current reading: {voltage:.4f}V and saved")
                
            elif choice == '3':
                try:
                    value = float(input("Enter MIN voltage value: "))
                    config['calibration']['min_voltage'] = value
                    self.save_config()
                    print(f"Set MIN to {value:.4f}V and saved")
                except ValueError:
                    print("Invalid value")
                    
            elif choice == '4':
                try:
                    value = float(input("Enter MAX voltage value: "))
                    config['calibration']['max_voltage'] = value
                    self.save_config()
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
                    
            elif choice == '6':
                break
            else:
                print("Invalid choice")
        
        print(f"\nFinal calibration for {name}:")
        print(f"  Min: {config['calibration']['min_voltage']:.4f}V")
        print(f"  Max: {config['calibration']['max_voltage']:.4f}V")
    
    def run_interactive(self):
        """Run interactive calibration session"""
        print("\n" + "="*60)
        print(f"ADC Calibration Tool - {self.config_file}")
        print("="*60)
        
        while True:
            self.read_current_values()
            
            print("\nOptions:")
            print("  A: Auto-calibrate ALL channels (recommended)")
            print("  1-{}: Calibrate specific channel".format(len(self.channels)))
            print("  R: Read current values again")
            print("  Q: Quit")
            
            choice = input("\nChoice: ").strip().upper()
            
            if choice == 'A':
                self.auto_calibrate_all()
            
            elif choice.isdigit():
                channel_index = int(choice) - 1
                if 0 <= channel_index < len(self.channels):
                    self.calibrate_channel(channel_index)
                else:
                    print("Invalid channel number")
                    
            elif choice == 'R':
                continue
                
            elif choice == 'Q':
                print("Exiting")
                break
                
            else:
                print("Invalid choice")
    
    def quick_calibrate(self, channel_index, mode):
        """Quick calibration mode for setting min or max"""
        if channel_index >= len(self.channels):
            print(f"Invalid channel index: {channel_index}")
            return
        
        ch_info = self.channels[channel_index]
        channel = ch_info['channel']
        name = ch_info['name']
        config = ch_info['config']
        
        if mode == 'auto':
            # Run automatic calibration (saves automatically when user confirms)
            self.auto_calibrate_channel(channel_index)
        else:
            voltage = channel.voltage
            
            if mode == 'min':
                config['calibration']['min_voltage'] = voltage
                self.save_config()
                print(f"Set {name} MIN to {voltage:.4f}V and saved")
            elif mode == 'max':
                config['calibration']['max_voltage'] = voltage
                self.save_config()
                print(f"Set {name} MAX to {voltage:.4f}V and saved")
            else:
                print(f"Invalid mode: {mode}")
                return


def main():
    parser = argparse.ArgumentParser(description='ADS1115 ADC Calibration Tool')
    parser.add_argument('config', help='Path to configuration file (JSON format)')
    parser.add_argument('--quick', type=int, metavar='CHANNEL',
                       help='Quick calibrate mode: specify channel number (1-based)')
    parser.add_argument('--set', choices=['min', 'max', 'auto'],
                       help='Used with --quick: min/max for current reading, auto for automatic calibration')
    
    args = parser.parse_args()
    
    # Check if config file exists
    if not os.path.exists(args.config):
        print(f"Error: Configuration file '{args.config}' not found")
        sys.exit(1)
    
    calibrator = ADCCalibrator(args.config)
    
    if args.quick is not None and args.set is not None:
        # Quick calibration mode
        calibrator.quick_calibrate(args.quick - 1, args.set)
    else:
        # Interactive mode
        calibrator.run_interactive()


if __name__ == "__main__":
    main()
