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
        ads1 = ADS.ADS1115(i2c, address=0x48)
        ads2 = ADS.ADS1115(i2c, address=0x49)
        ads3 = ADS.ADS1115(i2c, address=0x4a)
        
        # Set gain for 0-3.3V range (best resolution)
        # gain = 2 gives ±2.048V range, but since ADS1115 measures ±, 
        # this gives us 0-4.096V range which is perfect for 3.3V max
        ads1.gain = 1
        ads2.gain = 1
        ads3.gain = 1

        channels = set()

        # Create channel A0
        channels.add( AnalogIn(ads1, ADS.P0, ADS.P1) )
        channels.add( AnalogIn(ads1, ADS.P2, ADS.P3) )
        channels.add( AnalogIn(ads2, ADS.P0, ADS.P1) )
        channels.add( AnalogIn(ads2, ADS.P2, ADS.P3) )
        channels.add( AnalogIn(ads3, ADS.P0, ADS.P1) )
        channels.add( AnalogIn(ads3, ADS.P2, ADS.P3) )
        
        print("ADS1115 Test - Address 0x49, Channel A0 - A1 differential")
        print("Gain: ±2.048V (optimized for 0-3.3V)")
        print("Press Ctrl+C to stop\n")
        
        # Take continuous readings
        reading_count = 1
        while True:
            chan_id = 1
            for channel in channels:
                voltage = channel.voltage
                raw_value = channel.value
                print(f"Reading {chan_id} {reading_count:3d}: {voltage:.4f}V (raw: {raw_value})")
                chan_id += 1
            print("********")

            reading_count += 1
            
            time.sleep(1.0)  # 1 second between readings
            
    except KeyboardInterrupt:
        print("\nTest stopped")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_ads1115_simple()
