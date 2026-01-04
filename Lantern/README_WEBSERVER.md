# WS2812 LED Web Server Control

This enhanced version of the WS2812 color transition controller adds WiFi connectivity and a web-based interface for runtime control of LED colors and transition timing.

## New Features

- **WiFi Connectivity**: Connects to your WiFi network
- **Web Interface**: Beautiful, responsive web UI for controlling the LED
- **REST API**: HTTP endpoints for programmatic control
- **Runtime Configuration**: Change colors and transition time without re-uploading code
- **Live Preview**: See color changes in the web interface before applying them

## File Structure

```
Lantern.ino                  - Main Arduino sketch with LED control logic
lantern_webserver.h/cpp      - Web server setup and REST API handlers
webpage.h                    - HTML/CSS/JavaScript web interface
```

## Setup Instructions

### 1. WiFi Configuration
Wifi Configuration is held in NVRAM. To update it, add a line to the setup()
function to add the ssid and password strings, such as -
preferences.putString("ssid", "my_ssid");

Upload the sketch on your ESP32 board once, then *delete* these lines and upload
the sketch again.

(see next section for how to upload)

### 2. Upload to ESP32

1. Open `Lantern.ino` in Arduino IDE
2. Select your ESP32 board from Tools > Board
3. Select the correct COM port
4. Click Upload

### 3. Find the Device

1. Open Serial Monitor (115200 baud)
2. After connecting to WiFi, you'll see:
   - IP address (e.g., `192.168.1.100`)
   - mDNS hostname: `flg_lantern.local`

### 4. Access the Web Interface

Open your web browser and navigate to either:
- **http://flg_lantern.local** (recommended - easier to remember)
- Or the IP address shown in the Serial Monitor

**Note**: mDNS (`.local` addresses) work automatically on most devices. If `flg_lantern.local` doesn't work, use the IP address instead.

## Web Interface Features

### Color A Section
- **Color Picker**: Visual color selector - click to choose any color
- **HSV Display**: Shows the HSV values that will be sent to the LED
- **Set Color A Button**: Apply the selected color to Color A

### Color B Section
- **Color Picker**: Visual color selector - click to choose any color
- **HSV Display**: Shows the HSV values that will be sent to the LED
- **Set Color B Button**: Apply the selected color to Color B

**Note**: The color picker uses RGB input but automatically converts to HSV for the LED controller. HSV is better for smooth color transitions on LEDs.

### Transition Settings
- **Transition Time**: Set the duration of transitions in milliseconds (100-300000 ms)
  - Example: 5000 = 5 seconds, 20000 = 20 seconds, 60000 = 1 minute

### Status Messages
The interface shows success or error messages when settings are applied.

## REST API Endpoints

All endpoints return JSON responses.

### GET /
Returns the web interface HTML page.

### POST /api/colorA
Set Color A HSV values.

**Parameters:**
- `h` - Hue (0-255)
- `s` - Saturation (0-255)
- `v` - Value/Brightness (0-255)

**Example:**
```bash
curl -X POST "http://192.168.1.100/api/colorA?h=160&s=255&v=200"
```

**Response:**
```json
{
  "status": "success",
  "message": "Color A updated"
}
```

### POST /api/colorB
Set Color B HSV values.

**Parameters:**
- `h` - Hue (0-255)
- `s` - Saturation (0-255)
- `v` - Value/Brightness (0-255)

**Example:**
```bash
curl -X POST "http://192.168.1.100/api/colorB?h=0&s=255&v=200"
```

**Response:**
```json
{
  "status": "success",
  "message": "Color B updated"
}
```

### POST /api/transition
Set transition time.

**Parameters:**
- `time` - Transition time in milliseconds (100-300000)

**Example:**
```bash
curl -X POST "http://192.168.1.100/api/transition?time=10000"
```

**Response:**
```json
{
  "status": "success",
  "message": "Transition time updated"
}
```

### GET /api/status
Get current LED settings.

**Example:**
```bash
curl "http://192.168.1.100/api/status"
```

**Response:**
```json
{
  "colorA": {"h": 160, "s": 255, "v": 255},
  "colorB": {"h": 0, "s": 255, "v": 255},
  "transitionTime": 20000
}
```

## Programming Examples

### Python Example
```python
import requests

# Set Color A to bright green
requests.post('http://192.168.1.100/api/colorA?h=96&s=255&v=255')

# Set Color B to purple
requests.post('http://192.168.1.100/api/colorB?h=192&s=255&v=200')

# Set transition to 5 seconds
requests.post('http://192.168.1.100/api/transition?time=5000')

# Get current status
status = requests.get('http://192.168.1.100/api/status').json()
print(f"Current settings: {status}")
```

### JavaScript Example
```javascript
// Set Color A
fetch('http://192.168.1.100/api/colorA?h=128&s=255&v=255', {
  method: 'POST'
})
  .then(response => response.json())
  .then(data => console.log(data.message));

// Get current status
fetch('http://192.168.1.100/api/status')
  .then(response => response.json())
  .then(data => console.log('Current settings:', data));
```

### Shell Script Example
```bash
#!/bin/bash
IP="192.168.1.100"

# Cycle through rainbow colors
for hue in {0..255..32}; do
  curl -X POST "http://${IP}/api/colorB?h=${hue}&s=255&v=255"
  sleep 10
done
```

## Troubleshooting

### Can't Connect to WiFi
- Verify SSID and password are correct
- Check that your WiFi is 2.4GHz (ESP32c2 doesn't support 5GHz)
- Look at Serial Monitor for connection status
- The device will continue running in offline mode if WiFi fails

### Can't Access Web Interface
- Verify the IP address from Serial Monitor
- Make sure your computer is on the same WiFi network
- Try disabling firewall temporarily to test
- Check if the device is still powered on and connected

### Changes Don't Take Effect
- The web interface updates take effect immediately on the running transition
- Refresh the page to see current values
- Check Serial Monitor for confirmation messages

### Colors Don't Match Preview
- Different WS2812 variants may have different color orders
- Try changing `COLOR_ORDER` in the .ino file (GRB, RGB, BGR)
- The preview uses standard RGB color conversion

## Advanced Usage

### Integration with Home Automation
The REST API can be integrated with home automation systems like:
- **Home Assistant**: Use RESTful command integration
- **Node-RED**: HTTP request nodes
- **IFTTT**: Webhooks
- **Alexa/Google Home**: Via intermediary service

### Scheduled Color Changes
Use cron jobs or task schedulers to change colors at specific times:
```bash
# Warm colors in evening (add to crontab)
0 18 * * * curl -X POST "http://192.168.1.100/api/colorA?h=32&s=200&v=200"
```

### Multiple LED Controllers
If you have multiple LED controllers, you can control them all from a single script by targeting different IP addresses.

## Technical Details

### Memory Usage
The web server and HTML page are stored in program memory (PROGMEM) to minimize RAM usage. The ESP32c2 should have sufficient memory for this application.

### Performance
The web server runs asynchronously with the LED control loop. Web requests are handled quickly without interrupting the smooth LED transitions.

### Security Note
This web server does not implement authentication. Only use it on trusted networks. For production use, consider adding:
- Basic authentication
- HTTPS with SSL certificates
- API key validation

## Color Wheel Reference

HSV Hue values (0-255):
- 0 = Red
- 21 = Orange-Red
- 32 = Orange
- 43 = Yellow-Orange
- 64 = Yellow
- 85 = Yellow-Green
- 96 = Green
- 117 = Green-Cyan
- 128 = Cyan
- 149 = Cyan-Blue
- 160 = Blue
- 171 = Blue-Purple
- 192 = Purple
- 213 = Purple-Magenta
- 224 = Pink/Magenta
- 245 = Magenta-Red

## License

This code is provided as-is for educational and hobbyist use.
