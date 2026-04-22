# Art-Net CLI Utility

A command-line tool for sending Art-Net commands to LED control devices. Built with Rust using [`clap`](https://docs.rs/clap/) for CLI parsing.

## Features

- **Save Command**: Persist current LED state to device database with OEM code filtering
- **DMX Output**: Send raw DMX data to control LED strips with customizable universe selection
- **Multiple Data Formats**: Support hex strings, comma-separated decimals, or space-separated decimals

## Building

```bash
cd artnet_cli
cargo build --release
```

The executable will be at `target/release/artnet_cli.exe`

## Usage

### Send Save Command

Sends the `save_defaults` Art-Net command with OEM code `0x666c` to persist the current LED state:

```bash
artnet_cli.exe 192.168.1.100 save
```

This will:

1. Connect to `192.168.1.100:6454` (standard Art-Net port)
2. Send a custom Art-Net Command packet with:
   - OEM Code: `0x666c` (matches your embedded code filter)
   - Command Data: `"save_defaults"`
3. Device receives and saves current LED strip state to database

### Send DMX Output

Send raw DMX data to control LED strips:

```bash
artnet_cli.exe 192.168.1.100 dmx "FF0000FF"
```

Data format options:

**Hex string** (most compact):

```bash
artnet_cli.exe 192.168.1.100 dmx "FF0000FF"    # Red, Green, Blue, brightness
```

**Comma-separated decimals**:

```bash
artnet_cli.exe 192.168.1.100 dmx "255,0,0,255"  # Same as above
```

**Space-separated decimals**:

```bash
artnet_cli.exe 192.168.1.100 dmx "255 0 0 255"
```

**With universe option** (default is 0):

```bash
artnet_cli.exe 192.168.1.100 dmx "FF0000" --universe 1
artnet_cli.exe 192.168.1.100 dmx "FF0000" -u 1  # Short form
```

DMX data constraints:

- Minimum: 1 byte
- Maximum: 512 bytes (standard DMX universe size)
- All formats are automatically validated

## Protocol Details

### Art-Net Command (Save)

Packet structure:

```
Offset  Field           Size    Value
0       ID              8       "Art-Net\0"
8       OpCode          2       0x8000 (little-endian)
10      ProtVer         2       0x000E (big-endian, version 14)
12      EstMan          2       0x6C66 (little-endian, OEM code "fl")
14      Est Code        1       0x00
15      Filler          9       0x00 (reserved)
24      Data            512     Command string
```

### Art-Net DMX Output

Packet structure:

```
Offset  Field           Size    Value
0       ID              8       "Art-Net\0"
8       OpCode          2       0x0050 (little-endian)
10      ProtVer         2       0x000E (big-endian, version 14)
12      Sequence        1       0x00
13      Physical        1       0x00
14      Universe        2       Universe number (little-endian)
16      Length          2       Data length (big-endian)
18      Data            1-512   DMX channel data
```

## Compatibility

- **Embedded Device**: RP2040 (Raspberry Pi Pico) with ekv database
- **OEM Code Filter**: `0x666c` ("fl" in ASCII)
- **Command**: `save_defaults` (triggers pixel persistence to database)
- **Database Key**: `"default_pixels"` (4080 bytes: 4 strips × 340 pixels × 3 bytes RGB)

## Examples

### Save LED state after configuration

```bash
# Configure LED strips via DMX, then save
artnet_cli.exe 192.168.1.100 dmx "255,128,0,255,0,0,0,255,0,128,128,0"
artnet_cli.exe 192.168.1.100 save
```

### Full RGB color sequence for 4 pixel test pattern

```bash
# RGBW test: Red, Green, Blue, White
artnet_cli.exe 192.168.1.100 dmx "FF,00,00,00,FF,00,00,00,FF,FF,FF,FF"
```

### Send data to specific universe

```bash
artnet_cli.exe 192.168.1.100 dmx "FF0000" --universe 5
```

## Troubleshooting

**"Connection refused"**: Make sure the target device is on the network and listening on port 6454

**"Data format not recognized"**: Check that hex strings don't have odd length or decimals are 0-255

**Command not received**: Verify the device has the OEM code filter enabled (0x666c) and is looking for `save_defaults` command

## License

This is part of the Flaming Lotus Girls led_node embedded system.
