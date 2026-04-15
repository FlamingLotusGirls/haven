#!/usr/bin/env python3
"""
I2C Bus Scanner for Raspberry Pi
Specifically looks for ADS1115 ADC at common addresses
"""

import smbus2
import time

def scan_i2c_bus(bus_number=1):
    """
    Scan I2C bus for connected devices
    bus_number: 1 for newer Pi models, 0 for very old ones
    """
    print(f"Scanning I2C bus {bus_number}...")
    print("     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f")
    
    try:
        bus = smbus2.SMBus(bus_number)
        
        for i in range(0, 128):
            try:
                # Try to read from device
                bus.read_byte(i)
                if i < 16:
                    print(f"{i:02x}: {i:02x}", end="")
                else:
                    if i % 16 == 0:
                        print(f"\n{i//16:x}0:", end="")
                    print(f" {i:02x}", end="")
            except:
                if i < 16:
                    print(f"{i:02x}: --", end="")
                else:
                    if i % 16 == 0:
                        print(f"\n{i//16:x}0:", end="")
                    print(" --", end="")
        
        print("\n")
        bus.close()
        
    except Exception as e:
        print(f"Error accessing I2C bus: {e}")
        return False
    
    return True

def check_ads1115():
    """
    Specifically check for ADS1115 at common addresses
    """
    ads1115_addresses = [0x48, 0x49, 0x4A, 0x4B]
    print("\nChecking specifically for ADS1115 at common addresses:")
    
    try:
        bus = smbus2.SMBus(1)
        found_devices = []
        
        for addr in ads1115_addresses:
            try:
                # Try to read from the device
                bus.read_byte(addr)
                print(f"✓ Found device at 0x{addr:02X}")
                found_devices.append(addr)
            except:
                print(f"✗ No device found at 0x{addr:02X}")
        
        bus.close()
        return found_devices
        
    except Exception as e:
        print(f"Error checking ADS1115: {e}")
        return []

def test_ads1115_communication(address):
    """
    Test basic communication with ADS1115
    """
    print(f"\nTesting communication with ADS1115 at 0x{address:02X}:")
    
    try:
        import board
        import busio
        import adafruit_ads1x15.ads1115 as ADS
        
        # Create I2C bus
        i2c = busio.I2C(board.SCL, board.SDA)
        
        # Create ADS object
        ads = ADS.ADS1115(i2c, address=address)
        
        # Try to read from channel 0
        from adafruit_ads1x15.analog_in import AnalogIn
        chan = AnalogIn(ads, ADS.P0)
        
        voltage = chan.voltage
        print(f"✓ Successfully read voltage from A0: {voltage:.3f}V")
        return True
        
    except Exception as e:
        print(f"✗ Communication test failed: {e}")
        return False

if __name__ == "__main__":
    print("Raspberry Pi I2C Scanner")
    print("=" * 40)
    
    # Scan the bus
    scan_i2c_bus()
    
    # Check for ADS1115 specifically
    found_devices = check_ads1115()
    
    # Test communication if device found
    if found_devices:
        print(f"\nFound {len(found_devices)} ADS1115 device(s)")
        for addr in found_devices:
            test_ads1115_communication(addr)
    else:
        print("\nNo ADS1115 devices found!")
        print("\nTroubleshooting tips:")
        print("1. Check wiring:")
        print("   - VDD to 3.3V or 5V")
        print("   - GND to Ground")
        print("   - SCL to GPIO 3 (Pin 5)")
        print("   - SDA to GPIO 2 (Pin 3)")
        print("2. Verify I2C is enabled: sudo raspi-config")
        print("3. Check connections with multimeter")
        print("4. Try different ADDR pin configuration")
