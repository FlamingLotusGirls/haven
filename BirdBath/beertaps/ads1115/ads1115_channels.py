#!/usr/bin/env python3
"""
ADS1115 test with detailed config register decoding
Shows what's actually happening in the chip
"""

import smbus2
import time

class ADS1115:
    # ADS1115 registers
    REG_CONVERSION = 0x00
    REG_CONFIG = 0x01
    REG_LO_THRESH = 0x02
    REG_HI_THRESH = 0x03
    
    # Config register bit definitions
    CONFIG_OS_MASK = 0x8000
    CONFIG_MUX_MASK = 0x7000
    CONFIG_PGA_MASK = 0x0E00
    CONFIG_MODE_MASK = 0x0100
    CONFIG_DR_MASK = 0x00E0
    CONFIG_COMP_MODE_MASK = 0x0010
    CONFIG_COMP_POL_MASK = 0x0008
    CONFIG_COMP_LAT_MASK = 0x0004
    CONFIG_COMP_QUE_MASK = 0x0003
    
    # Lookup tables for config decoding
    MUX_CONFIGS = {
        0x0000: "Differential: AIN0 - AIN1",
        0x1000: "Differential: AIN0 - AIN3", 
        0x2000: "Differential: AIN1 - AIN3",
        0x3000: "Differential: AIN2 - AIN3",
        0x4000: "Single-ended: AIN0",
        0x5000: "Single-ended: AIN1",
        0x6000: "Single-ended: AIN2",
        0x7000: "Single-ended: AIN3"
    }
    
    PGA_CONFIGS = {
        0x0000: ("±6.144V", "2/3x", 6.144),
        0x0200: ("±4.096V", "1x", 4.096),
        0x0400: ("±2.048V", "2x", 2.048),
        0x0600: ("±1.024V", "4x", 1.024),
        0x0800: ("±0.512V", "8x", 0.512),
        0x0A00: ("±0.256V", "16x", 0.256)
    }
    
    DATA_RATES = {
        0x0000: "8 SPS",
        0x0020: "16 SPS", 
        0x0040: "32 SPS",
        0x0060: "64 SPS",
        0x0080: "128 SPS",
        0x00A0: "250 SPS",
        0x00C0: "475 SPS",
        0x00E0: "860 SPS"
    }
    
    COMP_QUEUE = {
        0x0000: "1 conversion",
        0x0001: "2 conversions",
        0x0002: "4 conversions", 
        0x0003: "Disabled"
    }
    
    def __init__(self, bus=1, address=0x48):
        self.bus = smbus2.SMBus(bus)
        self.address = address
    
    def read_config(self):
        """Read and decode the configuration register"""
        config_bytes = self.bus.read_i2c_block_data(self.address, self.REG_CONFIG, 2)
        config_val = (config_bytes[0] << 8) | config_bytes[1]
        return config_val
    
    def decode_config(self, config_val):
        """Decode configuration register into human-readable format"""
        print(f"\nConfiguration Register: 0x{config_val:04X}")
        print("=" * 50)
        
        # Operational status
        os_bit = config_val & self.CONFIG_OS_MASK
        print(f"OS (Operational Status): {'Start conversion' if os_bit else 'No effect'}")
        
        # Multiplexer
        mux_val = config_val & self.CONFIG_MUX_MASK
        mux_desc = self.MUX_CONFIGS.get(mux_val, "Unknown")
        print(f"MUX (Input Multiplexer): {mux_desc}")
        
        # Programmable Gain Amplifier
        pga_val = config_val & self.CONFIG_PGA_MASK
        if pga_val in self.PGA_CONFIGS:
            range_str, gain_str, voltage_range = self.PGA_CONFIGS[pga_val]
            print(f"PGA (Gain): {range_str} (Gain {gain_str})")
        else:
            print(f"PGA (Gain): Unknown (0x{pga_val:04X})")
            voltage_range = 2.048  # default
        
        # Operating mode
        mode_bit = config_val & self.CONFIG_MODE_MASK
        print(f"MODE: {'Single-shot' if mode_bit else 'Continuous'}")
        
        # Data rate
        dr_val = config_val & self.CONFIG_DR_MASK
        dr_desc = self.DATA_RATES.get(dr_val, "Unknown")
        print(f"DR (Data Rate): {dr_desc}")
        
        # Comparator mode
        comp_mode = config_val & self.CONFIG_COMP_MODE_MASK
        print(f"COMP_MODE: {'Window' if comp_mode else 'Traditional'}")
        
        # Comparator polarity
        comp_pol = config_val & self.CONFIG_COMP_POL_MASK
        print(f"COMP_POL: {'Active HIGH' if comp_pol else 'Active LOW'}")
        
        # Comparator latching
        comp_lat = config_val & self.CONFIG_COMP_LAT_MASK
        print(f"COMP_LAT: {'Latching' if comp_lat else 'Non-latching'}")
        
        # Comparator queue
        comp_que = config_val & self.CONFIG_COMP_QUE_MASK
        que_desc = self.COMP_QUEUE.get(comp_que, "Unknown")
        print(f"COMP_QUE: {que_desc}")
        
        return voltage_range
    
    def set_channel_and_read(self, channel=0, gain=0x0400):
        """Set channel configuration and read value"""
        if channel < 0 or channel > 3:
            raise ValueError("Channel must be 0-3")
        
        # Calculate MUX setting for single-ended channel
        mux_setting = 0x4000 + (channel << 12)
        
        # Build configuration
        config = (0x8000 |      # Start single conversion
                  mux_setting | # Channel selection  
                  gain |        # Gain setting
                  0x0100 |      # Single-shot mode
                  0x0080 |      # 128 SPS
                  0x0003)       # Disable comparator
        
        print(f"\nSetting up channel A{channel}:")
        print(f"Writing config: 0x{config:04X}")
        
        # Write configuration
        config_bytes = [(config >> 8) & 0xFF, config & 0xFF]
        self.bus.write_i2c_block_data(self.address, self.REG_CONFIG, config_bytes)
        
        # Read back and decode what we just wrote
        actual_config = self.read_config()
        voltage_range = self.decode_config(actual_config)
        
        # Wait for conversion
        time.sleep(0.01)
        
        # Read conversion result
        result = self.bus.read_i2c_block_data(self.address, self.REG_CONVERSION, 2)
        raw_value = (result[0] << 8) | result[1]
        
        # Convert to signed
        if raw_value > 32767:
            raw_value -= 65536
        
        # Convert to voltage
        voltage = (raw_value * voltage_range) / 32767.0
        
        print(f"\nConversion Result:")
        print(f"Raw bytes: 0x{result[0]:02X} 0x{result[1]:02X}")
        print(f"Raw value: {raw_value}")
        print(f"Voltage: {voltage:.6f}V")
        
        return raw_value, voltage
    
    def close(self):
        self.bus.close()

def main():
    print("ADS1115 Configuration Analysis Tool")
    print("=" * 50)
    
    try:
        ads = ADS1115(address=0x48)
        
        # Read initial configuration
        print("Initial configuration:")
        initial_config = ads.read_config()
        ads.decode_config(initial_config)
        
        # Test each channel
        for channel in range(4):
            print(f"\n{'='*60}")
            print(f"TESTING CHANNEL A{channel}")
            print(f"{'='*60}")
            
            raw, voltage = ads.set_channel_and_read(channel)
            
            input(f"\nPress Enter to continue to next channel...")
        
        # Demonstrate different gain settings on channel 0
        print(f"\n{'='*60}")
        print("TESTING DIFFERENT GAIN SETTINGS ON A0")
        print(f"{'='*60}")
        
        gain_settings = [
            (0x0000, "±6.144V"),
            (0x0200, "±4.096V"), 
            (0x0400, "±2.048V"),
            (0x0600, "±1.024V")
        ]
        
        for gain_val, gain_desc in gain_settings:
            print(f"\n--- Testing {gain_desc} range ---")
            raw, voltage = ads.set_channel_and_read(0, gain_val)
            input("Press Enter for next gain setting...")
        
        ads.close()
        print("\nTest completed!")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
