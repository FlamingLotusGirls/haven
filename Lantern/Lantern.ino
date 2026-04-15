#include <FastLED.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <Matter.h>
#include <MatterEndPoints/MatterOnOffLight.h>
#include "lantern_webserver.h"

// Preferences object for NVS
Preferences preferences;

// Matter Light device
MatterOnOffLight matterLight;

// Light power state
bool lightPower = true;  // Light is on by default

// WiFi Configuration - UPDATE THESE WITH YOUR CREDENTIALS
String ssid;
String password;

// LED Configuration
#define LED_PIN     D0         // GPIO pin connected to the WS2812 LED data line
#define NUM_LEDS    1          // Number of LEDs (single LED)
#define LED_TYPE    WS2812B    // LED type
#define COLOR_ORDER GRB        // Color order for WS2812B

// Runtime configurable variables (HSV: Hue 0-255, Saturation 0-255, Value 0-255)
uint8_t colorA_hue = 160;      // Blue hue (default)
uint8_t colorA_sat = 255;      // Full saturation
uint8_t colorA_val = 255;      // Full brightness

uint8_t colorB_hue = 0;        // Red hue (default)
uint8_t colorB_sat = 255;      // Full saturation
uint8_t colorB_val = 255;      // Full brightness

unsigned long transitionTime = 20000;   // Transition time in milliseconds (20 seconds default)
#define DITHER_FREQUENCY    60         // Dithering frequency in Hz (60 = smooth to human eye)

// LED array
CRGB leds[NUM_LEDS];

// Transition variables
unsigned long transitionStart = 0;
bool transitioningToB = true;  // Direction of transition
bool isTransitioning = false;

// Temporal dithering variables
unsigned long lastDitherTime = 0;
unsigned long ditherPeriod = 1000 / DITHER_FREQUENCY;  // Period in milliseconds
bool showColorA = true;  // Which color to currently show in dither cycle

void onMatterEvent(matterEvent_t eventType, const chip::DeviceLayer::ChipDeviceEvent* eventInfo) {
  Serial.printf("Matter event received\n");
}

// Matter callback - called when on/off state changes
bool onMatterLightChange(bool state) {
  lightPower = state;
  Serial.printf("Matter: Light turned %s\n", state ? "ON" : "OFF");
  
  // Save power state to NVS
  preferences.begin("lantern", false);
  preferences.putBool("lightPower", lightPower);
  preferences.end();
  
  // If turning off, set LED to black immediately
  if (!lightPower) {
    leds[0] = CRGB::Black;
    FastLED.show();
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nWS2812 Color Transition with Web Server Starting...");
  
  // Load settings from NVS
  preferences.begin("lantern", false);  // false = read-write mode
  
  // Load Color A settings (use defaults if not set)
  colorA_hue = preferences.getUChar("colorA_hue", 160);
  colorA_sat = preferences.getUChar("colorA_sat", 255);
  colorA_val = preferences.getUChar("colorA_val", 255);
  
  // Load Color B settings (use defaults if not set)
  colorB_hue = preferences.getUChar("colorB_hue", 0);
  colorB_sat = preferences.getUChar("colorB_sat", 255);
  colorB_val = preferences.getUChar("colorB_val", 255);
  
  // Load transition time (use default if not set)
  transitionTime = preferences.getULong("transTime", 20000);

  // Load network ssid and password
  ssid = preferences.getString("ssid", "not");
  password = preferences.getString("password", "set");
  
  // Load light power state (use default if not set)
  lightPower = preferences.getBool("lightPower", true);
  
  preferences.end();
  
  Serial.println("Settings loaded from NVS:");
  Serial.printf("  Color A: H:%d S:%d V:%d\n", colorA_hue, colorA_sat, colorA_val);
  Serial.printf("  Color B: H:%d S:%d V:%d\n", colorB_hue, colorB_sat, colorB_val);
  Serial.printf("  Transition Time: %lu ms\n", transitionTime);
  
  // Initialize FastLED
  FastLED.addLeds<LED_TYPE, LED_PIN, COLOR_ORDER>(leds, NUM_LEDS);
  FastLED.setBrightness(255);
  
  // Start with COLOR_A (HSV)
  leds[0] = CHSV(colorA_hue, colorA_sat, colorA_val);
  FastLED.show();
  
  // Connect to WiFi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid.c_str(), password.c_str());
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IPv4 address: ");
    Serial.println(WiFi.localIP());
    
    // Enable and wait for IPv6 (required for Matter)
    Serial.println("Enabling IPv6...");
    WiFi.enableIPv6();
    
    // Wait for IPv6 to initialize (up to 10 seconds)
    Serial.print("Waiting for IPv6 address");
    for (int i = 0; i < 20; i++) {
      delay(500);
      Serial.print(".");
      String ipv6 = WiFi.linkLocalIPv6().toString();
      if (ipv6 != "::") {
        Serial.println();
        Serial.print("IPv6 address: ");
        Serial.println(ipv6);
        Serial.println("IPv6 configured - Matter should work!");
        break;
      }
      if (i == 19) {
        Serial.println();
        Serial.println("IPv6 address: NOT AVAILABLE (::)");
        Serial.println("WARNING: Your router may not support IPv6");
        Serial.println("Matter requires IPv6 - commissioning may fail");
      }
    }
    
    // Start mDNS service
    if (MDNS.begin("flg_lantern")) {
      Serial.println("mDNS responder started");
      Serial.println("Web UI: http://flg_lantern.local");
    } else {
      Serial.println("Error setting up mDNS responder!");
    }
  } else {
    Serial.println("\nWiFi connection failed. Running in offline mode.");
  }
  
  // Setup web server routes
  setupWebServer();
  
  // Initialize Matter
  Matter.onEvent(onMatterEvent);
  matterLight.begin();
  Matter.begin();

  matterLight.setOnOff(lightPower);
  matterLight.onChange(onMatterLightChange);
  
  Serial.println("\n============================================");
  Serial.println("Matter: Initialized as On/Off Light");
  Serial.println("Matter: Device is ready for commissioning");
  Serial.println("============================================");
  
  // Print Matter commissioning information
  Serial.println("\n** COMMISSIONING INFORMATION **");
  Serial.println();
  Serial.println("To add to Google Home or Alexa:");
  Serial.println("1. Open the app and tap 'Add Device' → 'Matter'");
  Serial.println("2. Use one of these methods:");
  Serial.println();
  
  // Get and print the manual pairing code
  Serial.print("Manual Pairing Code: ");
  Serial.println(Matter.getManualPairingCode());
  Serial.println();
  
  // Get and print the QR code payload
  Serial.println("QR Code Payload:");
  // Serial.println(Matter.getQRCodeURL());
  Serial.println();
  
  Serial.printf("Device State: %s\n", lightPower ? "ON" : "OFF");
  Serial.println("============================================\n");
  
  // If light is off, keep LED off
  if (!lightPower) {
    leds[0] = CRGB::Black;
    FastLED.show();
  }
  
  // Start the first transition after a brief delay
  transitionStart = millis() + 500;
  isTransitioning = true;
  
  Serial.println("Setup complete. Starting color transitions...");
}

void loop() {
  // Handle web server requests
  handleWebServer();
  
  unsigned long currentMillis = millis();
  
  // Only update LED if light is powered on
  if (!lightPower) {
    // Light is off - ensure LED stays off
    leds[0] = CRGB::Black;
    FastLED.show();
    delay(100);  // Longer delay when off to save power
    return;
  }
  
  if (isTransitioning && currentMillis >= transitionStart) {
    // Calculate transition progress (0.0 to 1.0)
    unsigned long elapsed = currentMillis - transitionStart;
    float progress = (float)elapsed / transitionTime;
    
    if (progress >= 1.0) {
      // Transition complete
      progress = 1.0;
      isTransitioning = false;
      
      // Switch direction for next transition
      transitioningToB = !transitioningToB;
      
      // Schedule next transition
      transitionStart = currentMillis + 500;  // 500ms pause between transitions
      isTransitioning = true;
      
      /*
      Serial.print("Transition complete. Next direction: ");
      Serial.println(transitioningToB ? "to COLOR_B" : "to COLOR_A");
      */
    }
    
    // Calculate precise intermediate HSV values with sub-pixel precision
    float hue1, sat1, val1, hue2, sat2, val2;
    if (transitioningToB) {
      hue1 = colorA_hue;
      sat1 = colorA_sat;
      val1 = colorA_val;
      hue2 = colorB_hue;
      sat2 = colorB_sat;
      val2 = colorB_val;
    } else {
      hue1 = colorB_hue;
      sat1 = colorB_sat;
      val1 = colorB_val;
      hue2 = colorA_hue;
      sat2 = colorA_sat;
      val2 = colorA_val;
    }
    
    // Linear interpolation with high precision
    float preciseHue = hue1 + (hue2 - hue1) * progress;
    float preciseSat = sat1 + (sat2 - sat1) * progress;
    float preciseVal = val1 + (val2 - val1) * progress;
    
    // Temporal dithering: Check if it's time to update
    if (currentMillis - lastDitherTime >= ditherPeriod) {
      lastDitherTime = currentMillis;
      
      // Get the two adjacent quantized values for each channel
      uint8_t hue_low = (uint8_t)floor(preciseHue);
      uint8_t hue_high = (uint8_t)ceil(preciseHue);
      uint8_t sat_low = (uint8_t)floor(preciseSat);
      uint8_t sat_high = (uint8_t)ceil(preciseSat);
      uint8_t val_low = (uint8_t)floor(preciseVal);
      uint8_t val_high = (uint8_t)ceil(preciseVal);
      
      // Calculate fractional parts for dithering
      float hue_frac = preciseHue - hue_low;
      float sat_frac = preciseSat - sat_low;
      float val_frac = preciseVal - val_low;
      
      // Use a simple temporal dithering pattern
      static uint8_t ditherPhase = 0;
      ditherPhase++;
      
      // Dither each channel independently based on fractional part
      uint8_t dithered_hue = ((ditherPhase & 0x1F) < (hue_frac * 31)) ? hue_high : hue_low;
      uint8_t dithered_sat = (((ditherPhase >> 1) & 0x1F) < (sat_frac * 31)) ? sat_high : sat_low;
      uint8_t dithered_val = (((ditherPhase >> 2) & 0x1F) < (val_frac * 31)) ? val_high : val_low;
      
      // Handle hue wraparound (0-255 is circular)
      if (abs((int)hue2 - (int)hue1) > 128) {
        // Take the shorter path around the color wheel
        if (hue2 > hue1) {
          preciseHue = hue1 - (256 - hue2 + hue1) * progress;
        } else {
          preciseHue = hue1 + (256 - hue1 + hue2) * progress;
        }
        if (preciseHue < 0) preciseHue += 256;
        if (preciseHue >= 256) preciseHue -= 256;
        
        hue_low = (uint8_t)floor(preciseHue);
        hue_high = (uint8_t)ceil(preciseHue);
        if (hue_high >= 256) hue_high = 0;
        hue_frac = preciseHue - floor(preciseHue);
        dithered_hue = ((ditherPhase & 0x1F) < (hue_frac * 31)) ? hue_high : hue_low;
      }
      
      CHSV currentColor = CHSV(dithered_hue, dithered_sat, dithered_val);
      leds[0] = currentColor;
      FastLED.show();
    }
  } else {
    // When not transitioning, show solid color
    CHSV solidColor;
    if (transitioningToB) {
      solidColor = CHSV(colorA_hue, colorA_sat, colorA_val);
    } else {
      solidColor = CHSV(colorB_hue, colorB_sat, colorB_val);
    }
    leds[0] = solidColor;
    FastLED.show();
  }
  
  // Small delay - adjusted for dithering frequency
  delay(2);
}
