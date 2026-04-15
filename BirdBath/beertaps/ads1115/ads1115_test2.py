import smbus2
import time

# Simple quick test
bus = smbus2.SMBus(1)
ads_addr = 0x48

# Read config to verify communication
config = bus.read_i2c_block_data(ads_addr, 1, 2)
print(f'Config register: 0x{config[0]:02X}{config[1]:02X}')

# Test all channels quickly
for ch in range(4):
    # Set channel (simplified)
    mux = 0x40 + (ch << 4)  # Single-ended channels
    config_val = 0x8000 | (mux << 8) | 0x0200  # Start conversion, channel, gain
    bus.write_i2c_block_data(ads_addr, 1, [(config_val >> 8) & 0xFF, config_val & 0xFF])
    time.sleep(0.01)
    
    # Read result
    result = bus.read_i2c_block_data(ads_addr, 0, 2)
    raw = (result[0] << 8) | result[1]
    if raw > 32767: raw -= 65536
    voltage = (raw * 4.096) / 32767
    print(f'A{ch}: {voltage:.3f}V (raw: {raw})')

bus.close()
