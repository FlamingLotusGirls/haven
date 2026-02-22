# Touch-Tone Telephone Trigger Device

This Arduino sketch for ESP32 reads button presses from a touch-tone telephone keypad and sends trigger events when specific phone numbers are dialed.

## Hardware Configuration

### GPIO Mapping
All reads from the touch tone telephone use the IO Expander, not the main ESP32
- **Rows 1-4**: GPIO 0-3
- **Columns 1-3**: GPIO 4-6

### Keypad Layout
```
Row 1: 1 2 3
Row 2: 4 5 6
Row 3: 7 8 9
Row 4: * 0 #
```

### Signal Logic
- All GPIOs use **INPUT_PULLUP**
- A GPIO is considered **active when LOW** (connected to ground)
- A button is detected as pressed when **BOTH** its row and column GPIOs are LOW

## Configuration

The sketch reads configuration from `/triggers.json` stored in LittleFS.

### Configuration File Format

```json
{
  "device_name": "Telephone",
  "wifi_ssid": "your_wifi_ssid",
  "wifi_pass": "your_wifi_password",
  "trigger_server": "192.168.5.174", // or wherever you are running the trigger gateway
  "trigger_port": 5002,
  "triggers": [
    {
      "name": "Emergency",
      "phone_number": "911"
    },
    {
      "name": "FireStation",
      "phone_number": "5551234"
    }
  ]
}
```

### Configuration Parameters

- **device_name**: Name of the device (used in trigger registration)
- **wifi_ssid**: WiFi network SSID
- **wifi_pass**: WiFi password
- **trigger_server**: IP address of the trigger gateway
- **trigger_port**: Port of the trigger gateway (typically 5002)
- **triggers**: Array of phone number to trigger mappings
  - **name**: Trigger name (will be registered as `{device_name}.{name}`)
  - **phone_number**: Phone number to dial (digits 0-9 only)

## Uploading Configuration

### Using Arduino IDE

1. Install the **ESP32 Filesystem Uploader** plugin
2. Place your `triggers.json` file in the `data/` folder
3. Select **Tools > ESP32 Sketch Data Upload**
4. The file will be uploaded to the ESP32's LittleFS filesystem

### Using PlatformIO

1. Place your `triggers.json` file in the `data/` folder
2. Run: `pio run --target uploadfs`

## Usage

### Dialing Phone Numbers

1. Press digits 0-9 to dial a phone number
2. The sketch tracks the complete number as you dial
3. When the dialed number matches a configured trigger, it sends a trigger event
4. **Special Keys**:
   - **\***: Clears the current dialed number
   - **#**: Completes the dialing (optional - triggers fire automatically on match)
   
### Dial Timeout

If no digit is pressed for **5 seconds**, the current dialed number is automatically cleared.

## Trigger Integration

This sketch integrates with the Haven Trigger System using the `DeviceTriggers.h` library.

### Trigger Type

All phone number triggers are **OneShot** triggers, meaning they fire once when the phone number is dialed.

### Registration

- The device automatically registers with the trigger server on startup
- Re-registration occurs every **2 minutes** to maintain the connection
- All triggers are registered as `{device_name}.{trigger_name}`

### Example

If your configuration has:
```json
{
  "device_name": "Telephone",
  "triggers": [
    {
      "name": "Emergency",
      "phone_number": "911"
    }
  ]
}
```

Then dialing **911** will fire the trigger `Telephone.Emergency`.

## Serial Monitor Output

The sketch provides detailed feedback via Serial (115200 baud):

- Configuration loading status
- WiFi connection status
- Button press/release events
- Dialed numbers as they're entered
- Trigger matches and events sent
- Device registration confirmations

## Dependencies

Required Arduino libraries:
- WiFi (ESP32 core)
- HTTPClient (ESP32 core)
- ArduinoJson
- LittleFS (ESP32 core)

## Debouncing

Button presses are debounced with a **50ms** delay to prevent false triggers from mechanical bounce.

## Example Workflow

1. Upload the sketch to your ESP32
2. Configure your `data/triggers.json` file
3. Upload the filesystem data
4. Open Serial Monitor at 115200 baud
5. The device will:
   - Load configuration
   - Connect to WiFi
   - Register with the trigger server
6. Dial a configured phone number
7. Watch the Serial Monitor for trigger events
8. The trigger server will receive the event and can route it to other systems

## Troubleshooting

### "Failed to load configuration" Error
- Make sure you've uploaded the `triggers.json` file to LittleFS
- Check that the JSON syntax is valid
- Verify the file is named exactly `triggers.json` (case-sensitive)

### WiFi Not Connecting
- Double-check your WiFi SSID and password in the configuration
- Ensure the WiFi network is available
- Check Serial Monitor for connection attempts

### Triggers Not Firing
- Verify the trigger server is running and accessible
- Check that the phone number exactly matches the configuration
- Look for "PHONE NUMBER MATCH" messages in Serial Monitor
- Ensure WiFi is connected when dialing

### Multiple Button Presses Detected
- This is likely a wiring issue - check your row/column connections
- Verify pull-up resistors are working correctly
- Increase DEBOUNCE_DELAY if needed (currently 50ms)
