# Flame Effect Pattern Manager

A simple web-based interface for managing flame effect patterns and channel mappings for the ESP32C3 button intercept system.

## Quick Start

1. **Start the server:**
   ```bash
   python3 server.py
   ```

2. **Open the web interface:**
   Navigate to http://localhost:8000 in your web browser

3. **Start managing your patterns!**

## Features

### 🔗 Channel Mapping
- Map physical channel indices (0-7) to descriptive solenoid names
- Example: Channel 1 → "Cockatoo1"
- Add, remove, and modify channel mappings

### ⏰ Sequences
- Define timing patterns for flame effects
- Each sequence consists of ON/OFF states with durations in milliseconds 
- Example: `[ON:500ms, OFF:200ms, OFF:-1ms]` (where -1 indicates end of sequence)
- Create, edit, and delete sequences with visual editor

### 🎯 Patterns  
- Combine multiple sequences into complex patterns
- Assign sequences to specific solenoids with timing delays
- Example: "BirdChase" pattern might fire Cockatoo1 immediately, then Cockatoo4 after 500ms
- Visual pattern editor with dropdown selectors

### 🎮 Button Mappings
- Associate button inputs with patterns
- Example: Button 0 triggers "BirdChase" pattern
- Easy assignment interface

## File Structure

- `server.py` - Python HTTP server with REST API
- `index.html` - Web interface 
- `app.js` - Frontend JavaScript logic
- `channels.json` - Channel mapping configuration
- `patterns.json` - Sequences, patterns, and button mappings
- `configurationREADME.md` - Technical specification

## Uploading Files
Initially, you will have to upload the files in the data directory to the ESP32. To do this,
you must do the following:
- Get the uploader plugin for the Arduino IDE - https://randomnerdtutorials.com/arduino-ide-2-install-esp32-littlefs/
- Change the name in the netname file. For haven, we use haven-perch, haven-osprey, haven-magpie, haven-cockatoo1, haven-cockatoo2, and haven-standalone. You do not want to have two devices with the same netname on the network.
- Use the palette in the Arduino IDE (command-shift-P (Mac) or ctl-shift-P to select the Upload LittleFS option.
This should upload the files in the data directory.
If you have problems, make sure that any serial monitors are disconnected.


## Data Format

### channels.json
```json
[
  [1, "Cockatoo1"],
  [2, "Cockatoo4"], 
  [3, "CockatooChick1"]
]
```

### patterns.json
```json
{
  "sequences": {
    "poof": [[true, 500], [false, 200], [false, -1]]
  },
  "patterns": {
    "BirdChase": [["Cockatoo1", 0, "poof"], ["Cockatoo4", 500, "poof"]]
  },
  "pattern_mappings": {
    "0": "BirdChase"
  }
}
```

## Usage Tips

1. **Always save your changes** using the "💾 Save All Changes" button
2. **Create sequences first**, then use them in patterns
3. **Map channels before creating patterns** to see solenoid names in dropdowns
4. **Use -1 duration** to indicate the end of a sequence
5. **Test patterns** by creating simple sequences first

## API Endpoints

- `GET /api/channels` - Retrieve channel mappings
- `POST /api/channels` - Save channel mappings
- `GET /api/patterns` - Retrieve patterns data
- `POST /api/patterns` - Save patterns data

## Troubleshooting

- **Server won't start**: Make sure Python 3 is installed and port 8000 is free
- **Changes not saving**: Check browser console for errors, ensure server is running
- **Missing solenoids in dropdowns**: Make sure channel mappings are created first
- **Pattern not working**: Verify all sequences exist and have valid timing values

## Safety Notes

⚠️ **This system controls flame effects - always follow safety protocols:**
- Test patterns thoroughly before deployment
- Ensure proper safety equipment and procedures
- Never leave flame effects unattended
- Follow all local fire safety regulations
