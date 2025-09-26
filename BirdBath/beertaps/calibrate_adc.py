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
        print(f"\nConfiguration saved to {self.config_file}")
    
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
            print("  1. Set current reading as MINIMUM (-1.0)")
            print("  2. Set current reading as MAXIMUM (+1.0)")
            print("  3. Set custom MIN value")
            print("  4. Set custom MAX value")
            print("  5. Monitor current reading (updates every 0.5s)")
            print("  6. Done with this channel")
            
            choice = input("\nChoice (1-6): ").strip()
            
            if choice == '1':
                voltage = channel.voltage
                config['calibration']['min_voltage'] = voltage
                print(f"Set MIN to current reading: {voltage:.4f}V")
                
            elif choice == '2':
                voltage = channel.voltage
                config['calibration']['max_voltage'] = voltage
                print(f"Set MAX to current reading: {voltage:.4f}V")
                
            elif choice == '3':
                try:
                    value = float(input("Enter MIN voltage value: "))
                    config['calibration']['min_voltage'] = value
                    print(f"Set MIN to {value:.4f}V")
                except ValueError:
                    print("Invalid value")
                    
            elif choice == '4':
                try:
                    value = float(input("Enter MAX voltage value: "))
                    config['calibration']['max_voltage'] = value
                    print(f"Set MAX to {value:.4f}V")
                except ValueError:
                    print("Invalid value")
                    
            elif choice == '5':
                print("\nMonitoring (press Ctrl+C to stop)...")
                try:
                    while True:
                        voltage = channel.voltage
                        raw = channel.value
                        
                        cal = config['calibration']
                        min_v = cal['min_voltage']
                        max_v = cal['max_voltage']
                        
                        if max_v != min_v:
                            normalized = (voltage - min_v) / (max_v - min_v)
                            calibrated = 2.0 * normalized - 1.0
                        else:
                            calibrated = 0.0
                        
                        print(f"\rVoltage: {voltage:+.4f}V (raw: {raw:5d}) -> Output: {calibrated:+.4f}   ", end='', flush=True)
                        time.sleep(0.5)
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
            print("  1-{}: Calibrate specific channel".format(len(self.channels)))
            print("  R: Read current values again")
            print("  S: Save configuration")
            print("  Q: Quit without saving")
            print("  X: Save and exit")
            
            choice = input("\nChoice: ").strip().upper()
            
            if choice.isdigit():
                channel_index = int(choice) - 1
                if 0 <= channel_index < len(self.channels):
                    self.calibrate_channel(channel_index)
                else:
                    print("Invalid channel number")
                    
            elif choice == 'R':
                continue
                
            elif choice == 'S':
                self.save_config()
                
            elif choice == 'Q':
                confirm = input("Quit without saving? (y/N): ").strip().lower()
                if confirm == 'y':
                    print("Exiting without saving")
                    break
                    
            elif choice == 'X':
                self.save_config()
                print("Configuration saved. Exiting.")
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
        
        voltage = channel.voltage
        
        if mode == 'min':
            config['calibration']['min_voltage'] = voltage
            print(f"Set {name} MIN to {voltage:.4f}V")
        elif mode == 'max':
            config['calibration']['max_voltage'] = voltage
            print(f"Set {name} MAX to {voltage:.4f}V")
        else:
            print(f"Invalid mode: {mode}")
            return
        
        self.save_config()


def main():
    parser = argparse.ArgumentParser(description='ADS1115 ADC Calibration Tool')
    parser.add_argument('config', help='Path to configuration file (JSON format)')
    parser.add_argument('--quick', type=int, metavar='CHANNEL',
                       help='Quick calibrate mode: specify channel number (1-based)')
    parser.add_argument('--set', choices=['min', 'max'],
                       help='Used with --quick to set min or max for current reading')
    
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
