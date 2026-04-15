# Trigger Integration Guide for Button Intercept

This guide explains how to integrate the DeviceTriggers library into button_sequence.cpp to send trigger events when buttons are pressed.

## Files Added

1. **DeviceTriggers.h** - Trigger library (copied from TestESP32)
2. **trigger_mappings.json** - Configuration file for trigger mappings
3. **button_sequence.h** - Header file for button_sequence.cpp

## Changes Required to button_sequence.cpp

### 1. Add Includes (after existing includes, around line 17)

```cpp
#ifdef ARDUINO
#define ESP32 1  // NB - AsyncHttp library requires this
#include <Wire.h>
#ifdef PCA_9555
#include <PCA95x5.h>
#endif // PCA9555
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <AsyncTCP.h>
#include <AsyncHTTPRequest_Generic.h>
#include <WiFi.h>          // ADD THIS
#include <HTTPClient.h>    // ADD THIS
#include "DeviceTriggers.h" // ADD THIS
#else
```

### 2. Add Global Trigger Variables (after line 100, before "Forward declarations")

```cpp
#ifdef ARDUINO
// Trigger system globals
TriggerDevice* triggerDevice = nullptr;
std::shared_ptr<ButtonTrigger> channelTriggers[NUM_INPUT_CHANNELS];
bool triggerEnabled[NUM_INPUT_CHANNELS];
String triggerNames[NUM_INPUT_CHANNELS];
#endif
```

### 3. Add loadTriggerMappingsFromFile() Function (after loadPatternsFromFile(), around line 1150)

```cpp
#ifdef ARDUINO
// Load trigger mappings from trigger_mappings.json
void loadTriggerMappingsFromFile() {
  // Initialize trigger enabled array
  for (int i = 0; i < NUM_INPUT_CHANNELS; i++) {
    triggerEnabled[i] = false;
    triggerNames[i] = "";
  }
  
  if (!LittleFS.exists("/trigger_mappings.json")) {
    Serial.println("trigger_mappings.json not found, triggers disabled");
    return;
  }
  
  File file = LittleFS.open("/trigger_mappings.json", "r");
  if (!file) {
    Serial.println("Failed to open trigger_mappings.json");
    return;
  }
  
  // Read file into string
  String jsonString = file.readString();
  file.close();
  
  // Parse JSON
  DynamicJsonDocument doc(4096);
  DeserializationError error = deserializeJson(doc, jsonString);
  
  if (error) {
    Serial.print("trigger_mappings.json parsing failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  // Get trigger server configuration
  String triggerServerURL = doc["trigger_server"]["url"].as<String>();
  int triggerServerPort = doc["trigger_server"]["port"].as<int>();
  String deviceName = doc["device_name"].as<String>();
  
  Serial.println("=== Trigger Configuration ===");
  Serial.print("Server: ");
  Serial.print(triggerServerURL);
  Serial.print(":");
  Serial.println(triggerServerPort);
  Serial.print("Device: ");
  Serial.println(deviceName);
  
  // Create TriggerDevice
  triggerDevice = new TriggerDevice(deviceName, triggerServerURL, triggerServerPort);
  
  // Process channel mappings
  if (doc.containsKey("channel_to_trigger")) {
    JsonArray channelMappings = doc["channel_to_trigger"];
    for (JsonVariant channelMapping : channelMappings) {
      int channel = channelMapping["channel"].as<int>();
      String triggerName = channelMapping["trigger_name"].as<String>();
      bool enabled = channelMapping["enabled"].as<bool>();
      
      if (channel >= 0 && channel < NUM_INPUT_CHANNELS) {
        triggerEnabled[channel] = enabled;
        triggerNames[channel] = triggerName;
        
        if (enabled) {
          // Create ButtonTrigger for this channel
          channelTriggers[channel] = triggerDevice->AddButtonTrigger(triggerName, false, 100);
          Serial.print("Channel ");
          Serial.print(channel);
          Serial.print(" -> Trigger: ");
          Serial.println(triggerName);
        }
      }
    }
  }
  
  // Register device with trigger server
  if (triggerDevice != nullptr) {
    triggerDevice->RegisterDevice();
    Serial.println("Trigger device registered");
  }
  
  Serial.println("=== Trigger Configuration Complete ===");
}
#endif
```

### 4. Call loadTriggerMappingsFromFile() in buttonSetup() (around line 1170)

```cpp
void buttonSetup() {
  sleep(1);
  initMillis();
  initIO();
#ifdef ARDUINO
  Serial.println("Trying to set up i2c");
  initI2C();
  // Try to load configuration from files first, fallback to hardcoded
  if (LittleFS.begin()) {
    loadChannelsFromFile();     // Load channel aliases
    loadPatternsFromFile();     // Load pattern mappings
    loadTriggerMappingsFromFile(); // ADD THIS LINE - Load trigger mappings
  } else {
    // initChannelControllers(); // Use hardcoded patterns
  }
#ifdef DEBUG
  Serial.println("Starting...");
#endif // DEBUG
#else // ~ARDUINO
  printf("Starting...\n");
#ifdef MOCK_INPUT
  inputTest.Start();
#endif
#endif // ARDUINO
}
```

### 5. Send Trigger Events in readInputButtonStates() (around line 1035)

Replace the existing function with:

```cpp
void readInputButtonStates(uint16_t gpioRawData, int curTimeMs) {
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    bool oldButtonState = inputButtonStates[i];
    bool buttonState = readRawInput(i, gpioRawData, curTimeMs);
    inputButtonStates[i] = debouncer.Debounce(i, buttonState, curTimeMs);
    
    if (inputButtonStates[i] != oldButtonState) {
      Serial.print("ButtonChange on channel ");
      Serial.print(i);
      Serial.println(oldButtonState ? ",now UNPRESSED" : ",now PRESSED");
      
      // TRIGGER INTEGRATION: Send trigger event if enabled
      #ifdef ARDUINO
      if (triggerEnabled[i] && channelTriggers[i] != nullptr) {
        channelTriggers[i]->CheckForEventAndSend(inputButtonStates[i]);
        Serial.print("Trigger sent for channel ");
        Serial.println(i);
      }
      #endif
    }
  }
}
```

## Configuration File

The `trigger_mappings.json` file should be uploaded to LittleFS with this structure:

```json
{
  "trigger_server": {
    "url": "192.168.1.100",
    "port": 5002
  },
  "device_name": "ButtonIntercept",
  "channel_to_trigger": [
    {
      "channel": 0,
      "trigger_name": "Button0",
      "enabled": true
    },
    ...
  ]
}
```

## How It Works

1. **Startup**: `buttonSetup()` loads trigger mappings from JSON file
2. **TriggerDevice Created**: Connects to trigger server at specified URL/port
3. **ButtonTriggers Created**: One per enabled channel
4. **Device Registration**: Registers all triggers with the server
5. **Event Loop**: When button state changes, `CheckForEventAndSend()` is called
6. **HTTP Queue**: Trigger events are queued and sent by background thread

## Benefits

- **Non-blocking**: HTTP requests sent in background thread (Core 0)
- **Configurable**: Easy to enable/disable triggers per channel
- **Debounced**: Uses existing debounce logic before sending
- **Compatible**: Doesn't interfere with existing flame control
- **Networked**: Sends events to central trigger gateway

## Testing

1. Upload trigger_mappings.json to LittleFS
2. Compile and upload button_intercept_src.ino
3. Press buttons on channels
4. Check Serial Monitor for "Trigger sent for channel X"
5. Verify events arrive at trigger gateway

## Troubleshooting

- **No triggers sent**: Check trigger_mappings.json is in LittleFS
- **Connection errors**: Verify trigger server URL/port
- **Queue full**: Reduce button press frequency or increase queue size in DeviceTriggers.h
