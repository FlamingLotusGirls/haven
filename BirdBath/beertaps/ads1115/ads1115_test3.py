#!/usr/bin/env python3
"""
ADS1115 Simple Test - Address 0x49, Channel A0
Focused test for your specific setup
"""

import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

def test_ads1115_simple():
    try:
        # Create I2C bus
        i2c = busio.I2C(board.SCL, board.SDA)
        
        # Create ADS object with your specific address
        ads = ADS.ADS1115(i2c, address=0x49)
        
        # Set gain for 0-3.3V range (best resolution)
        # gain = 2 gives ±2.048V range, but since ADS1115 measures ±, 
        # this gives us 0-4.096V range which is perfect for 3.3V max
        ads.gain = 1
        
        # Create channel A0
        channel = AnalogIn(ads, ADS.P0)
        
        print("ADS1115 Test - Address 0x49, Channel A0")
        print("Gain: ±2.048V (optimized for 0-3.3V)")
        print("Press Ctrl+C to stop\n")
        
        # Take continuous readings
        reading_count = 1
        while True:
            voltage = channel.voltage
            raw_value = channel.value
            
            print(f"Reading {reading_count:3d}: {voltage:.4f}V (raw: {raw_value})")
            reading_count += 1
            
            time.sleep(1.0)  # 1 second between readings
            
    except KeyboardInterrupt:
        print("\nTest stopped")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ads1115_simple()
