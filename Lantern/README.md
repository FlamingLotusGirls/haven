# WS2812 LED Color Transition for ESP32c2 with HSV and Temporal Dithering

This project provides smooth color transitions for a single WS2812 LED using an ESP32c2 microcontroller, Arduino framework, and the FastLED library. It uses HSV color space for more natural color transitions and temporal dithering for ultra-smooth visual effects, especially during very slow transitions.

## Hardware Requirements

- ESP32c2 development board
- Single WS2812 LED (or WS2812B LED strip with one LED)
- Jumper wires
- Breadboard (optional)
- 5V power supply (if using many LEDs, though not needed for a single LED)

## Wiring

| ESP32c2 Pin | WS2812 LED Pin |
|-------------|----------------|
| GPIO 2      | DIN (Data In)  |
| 3.3V        | VCC            |
| GND         | GND            |

**Note:** For a single WS2812 LED, the ESP32c2's 3.3V output should be sufficient. For multiple LEDs or strips, you may need a 5V external power supply.

## Software Requirements

### Arduino IDE Setup

1. **Install Arduino IDE** (version 1.8.x or 2.x)

2. **Install ESP32 Board Package:**
   - Open Arduino IDE
   - Go to `File > Preferences`
   - Add this URL to "Additional Board Manager URLs":
     ```
     https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
     ```
   - Go to `Tools > Board > Board Manager`
   - Search for "ESP32" and install the package by Espressif Systems

3. **Install FastLED Library:**
   - Go to `Tools > Manage Libraries`
   - Search for "FastLED"
   - Install the FastLED library by Daniel Garcia

### Board Configuration

- **Board:** ESP32C2 Dev Module (or similar ESP32c2 board)
- **Upload Speed:** 921600
- **CPU Frequency:** 160MHz
- **Flash Frequency:** 80MHz
- **Flash Mode:** QIO
- **Flash Size:** 4MB (depending on your board)
- **Partition Scheme:** Default 4MB with spiffs
- **Core Debug Level:** None (or Info for debugging)

## Configuration Options

The program uses HSV color space and temporal dithering. Customize these constants in `ws2812_color_transition.ino`:

```cpp
// HSV Color Configuration (Hue: 0-255, Saturation: 0-255, Value: 0-255)
#define LED_PIN           2       // GPIO pin for LED data
#define COLOR_A_HUE       0       // Red hue (0-255)
#define COLOR_A_SAT       255     // Full saturation
#define COLOR_A_VAL       255     // Full brightness
#define COLOR_B_HUE       160     // Blue hue
#define COLOR_B_SAT       255     // Full saturation
#define COLOR_B_VAL       255     // Full brightness
#define TRANSITION_TIME   2000    // Transition time in milliseconds
#define DITHER_FREQUENCY  60      // Dithering frequency in Hz
```

### HSV Color Space Benefits

**HSV (Hue, Saturation, Value) provides more intuitive color control:**
- **Hue (0-255):** Color wheel position - 0=Red, 64=Yellow, 96=Green, 128=Cyan, 160=Blue, 192=Purple, 224=Pink
- **Saturation (0-255):** Color intensity - 0=Gray/White, 255=Full color
- **Value (0-255):** Brightness - 0=Off/Black, 255=Full brightness

### Temporal Dithering Explained

Temporal dithering creates smoother color transitions by rapidly alternating between adjacent quantized color values:
- **High-precision calculation:** Intermediate colors are calculated with floating-point precision
- **Adjacent value dithering:** Alternates between floor/ceiling values (e.g., between 127 and 128)
- **Fractional duty cycles:** Time ratio based on fractional part (e.g., 127.3 = 70% at 127, 30% at 128)
- **Effectively higher bit-depth:** Creates perception of values between the 8-bit quantized steps
- **Smooth slow transitions:** Perfect for very slow transitions where individual steps would be visible

## How It Works

1. **Initialization:** LED starts with COLOR_A (HSV)
2. **Precision Interpolation:** Calculate exact intermediate HSV values with floating-point precision
3. **Quantization:** Find adjacent integer values (floor and ceil) for each HSV channel
4. **Temporal Dithering:** Rapidly alternate between adjacent values based on fractional parts
5. **Visual Perception:** Your eye perceives the average, creating smooth sub-pixel precision
6. **Hue Wraparound:** Special handling for hue values to take shortest path around color wheel
7. **Pause:** Brief 500ms solid color pause between transitions
8. **Direction Reversal:** Transitions back in opposite direction
9. **Continuous Loop:** Process repeats indefinitely

**Example:** For intermediate hue value 127.3, the LED shows hue 127 for 70% of each dither cycle and hue 128 for 30%, creating the visual perception of hue 127.3 - much smoother than jumping directly from 127 to 128.

## Troubleshooting

### Common Issues

1. **LED not lighting up:**
   - Check wiring connections
   - Verify power supply
   - Ensure GPIO pin number is correct

2. **Colors not as expected:**
   - Try different COLOR_ORDER settings: `GRB`, `RGB`, `BGR`
   - Some WS2812 variants have different color orders

3. **Erratic behavior:**
   - Add a capacitor (100-1000μF) across power lines
   - Ensure stable 3.3V/5V supply
   - Keep data line wires short

### ESP32c2 Specific Notes

- The ESP32c2 is a newer, more power-efficient variant of ESP32
- It has fewer GPIO pins than ESP32, but GPIO 2 should work fine
- 3.3V logic levels are compatible with WS2812 LEDs
- If you experience issues, try GPIO pins 0, 1, or 4

## Serial Monitor Output

Connect to the serial monitor at 115200 baud to see transition status messages:

```
WS2812 Color Transition Starting...
Setup complete. Starting color transitions...
Transition complete. Next direction: to COLOR_B
Transition complete. Next direction: to COLOR_A
...
```

## Extending the Code

### Multiple LEDs
To control multiple LEDs, change:
```cpp
#define NUM_LEDS    10  // For 10 LEDs
```

### Different Transition Patterns
You can modify the `blendColors` function to implement different transition curves:
- Ease-in/ease-out
- Sinusoidal transitions
- Color wheel rotations

## License

This code is provided as-is for educational and hobbyist use.
