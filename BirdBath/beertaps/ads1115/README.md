# ADS1115 Test Scripts

This directory contains simple test and diagnostic scripts for ADS1115 ADC devices.

## ⚠️ Important: No I2C Locking

**These test scripts do NOT implement I2C device locking** for simplicity.

If you run these scripts while the `adc-reader` services are active, you **will get incorrect/corrupted readings** due to simultaneous I2C access.

### Before Running Test Scripts

Stop all ADC reader services first:

```bash
sudo systemctl stop adc-reader-1.service adc-reader-2.service adc-reader-3.service
```

### After Testing

Restart the services:

```bash
sudo systemctl start adc-reader-1.service adc-reader-2.service adc-reader-3.service
```

## Files

- `ads_all.py` - Test all three ADCs (0x48, 0x49, 0x4a) and all channels
- `ads1115_channels.py` - Test channel configurations
- `ads1115_test.py` - Basic ADC functionality test
- `ads1115_test2.py` - Extended test
- `ads1115_test3.py` - Additional test scenarios
- `ads1115_test4.py` - More test scenarios

## Why No Locking?

These are diagnostic tools meant for quick hardware verification. Adding locking would complicate simple debugging scenarios. The main operational tools (`adc_reader.py`, `calibrate.py`, `calibrate_adc.py`) in the parent directory **do** implement proper I2C locking.
