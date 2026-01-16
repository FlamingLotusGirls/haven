/*
 * TestESP32 - Trigger Device for Haven Trigger Server
 * Device: Xiao ESP32s3
 * 
 * Triggers:
 * - TestESP32.Button (On/Off) - D0 pin
 * - TestESP32.Discrete - D1 and D2 pins (binary combination)
 * - TestESP32.Continuous - A0 analog pin (placeholder)
 * - TestESP32.OneShot - D3 pin (placeholder)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// Device Configuration
const char* DEVICE_NAME = "TestESP32";
const char* TRIGGER_SERVER = "192.168.5.174";
const int TRIGGER_PORT = 5002;

// WiFi Networks (in priority order)
const char* WIFI_SSID_PRIMARY = "flg-haven";
const char* WIFI_PASS_PRIMARY = "fuckoffanddie";
const char* WIFI_SSID_SECONDARY = "medea";
const char* WIFI_PASS_SECONDARY = "!medea4u";

// Pin Definitions
const int PIN_BUTTON = D0;      // TestESP32.Button
const int PIN_DISCRETE_D1 = D1; // TestESP32.Discrete bit 0
const int PIN_DISCRETE_D2 = D2; // TestESP32.Discrete bit 1
const int PIN_ONESHOT = D3;     // TestESP32.OneShot
const int PIN_CONTINUOUS = A4;  // TestESP32.Continuous (analog)

// Debounce Configuration
const unsigned long DEBOUNCE_DELAY = 50; // milliseconds

// Button State Tracking
struct ButtonState {
  int pin;
  bool currentState;
  bool lastReading;
  unsigned long lastDebounceTime;
  bool lastSentState;
};

ButtonState buttonD0 = {PIN_BUTTON, HIGH, HIGH, 0, HIGH};
ButtonState discreteD1 = {PIN_DISCRETE_D1, HIGH, HIGH, 0, HIGH};
ButtonState discreteD2 = {PIN_DISCRETE_D2, HIGH, HIGH, 0, HIGH};

// Discrete value tracking
int lastDiscreteValue = 0;

// Trigger ID counter
unsigned long triggerIdCounter = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n=== TestESP32 Trigger Device ===");
  
  // Configure pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_DISCRETE_D1, INPUT_PULLUP);
  pinMode(PIN_DISCRETE_D2, INPUT_PULLUP);
  pinMode(PIN_ONESHOT, INPUT_PULLUP);
  pinMode(PIN_CONTINUOUS, INPUT);
  
  // Read initial states
  buttonD0.currentState = digitalRead(PIN_BUTTON);
  buttonD0.lastSentState = buttonD0.currentState;
  
  discreteD1.currentState = digitalRead(PIN_DISCRETE_D1);
  discreteD2.currentState = digitalRead(PIN_DISCRETE_D2);
  
  // Calculate initial discrete value
  lastDiscreteValue = calculateDiscreteValue();
  
  Serial.print("Initial Button State: ");
  Serial.println(buttonD0.currentState == HIGH ? "Off" : "On");
  Serial.print("Initial Discrete Value: ");
  Serial.println(lastDiscreteValue);
  
  // Connect to WiFi
  connectToWiFi();
  
  // Register device with trigger server
  registerDevice();
  
  Serial.println("Setup complete. Monitoring triggers...\n");
}

void loop() {
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Reconnecting...");
    connectToWiFi();
  }
  
  // Check Button (D0)
  checkButton();
  
  // Check Discrete (D1, D2)
  checkDiscrete();
  
  // TODO: Add Continuous trigger monitoring here
  // TODO: Add OneShot trigger monitoring here
  
  delay(10); // Small delay to prevent excessive CPU usage
}

void connectToWiFi() {
  Serial.println("\n--- WiFi Connection ---");
  
  // Try primary network first
  Serial.print("Attempting to connect to ");
  Serial.print(WIFI_SSID_PRIMARY);
  Serial.println("...");
  
  WiFi.begin(WIFI_SSID_PRIMARY, WIFI_PASS_PRIMARY);
  
  // Wait up to 10 seconds for connection
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  // If primary failed, try secondary
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nPrimary network not available.");
    Serial.print("Attempting to connect to ");
    Serial.print(WIFI_SSID_SECONDARY);
    Serial.println("...");

    WiFi.mode(WIFI_OFF);
    
    WiFi.begin(WIFI_SSID_SECONDARY, WIFI_PASS_SECONDARY);
    
    attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
      delay(500);
      Serial.print(".");
      attempts++;
    }
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("SSID: ");
    Serial.println(WiFi.SSID());
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("Signal Strength: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println("\nFailed to connect to WiFi. Will retry...");
  }
}

void registerDevice() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Cannot register - no WiFi connection");
    return;
  }
  
  Serial.println("\n--- Device Registration ---");
  
  HTTPClient http;
  String url = String("http://") + TRIGGER_SERVER + ":" + TRIGGER_PORT + "/api/register-device";
  
  Serial.print("Registering at: ");
  Serial.println(url);
  
  // Create registration JSON
  StaticJsonDocument<512> doc;
  doc["name"] = DEVICE_NAME;
  doc["ip"] = WiFi.localIP().toString();
  
  JsonArray triggers = doc.createNestedArray("triggers");
  
  // Button trigger
  JsonObject button = triggers.createNestedObject();
  button["name"] = String(DEVICE_NAME) + ".Button";
  button["type"] = "On/Off";
  
  // Discrete trigger
  JsonObject discrete = triggers.createNestedObject();
  discrete["name"] = String(DEVICE_NAME) + ".Discrete";
  discrete["type"] = "Discrete";
  JsonObject discreteRange = discrete.createNestedObject("range");
  JsonArray discreteValues = discreteRange.createNestedArray("values");
  discreteValues.add(0);
  discreteValues.add(1);
  discreteValues.add(2);
  discreteValues.add(3);
  
  // Serialize JSON
  String jsonPayload;
  serializeJson(doc, jsonPayload);
  
  Serial.println("Registration payload:");
  Serial.println(jsonPayload);
  
  // Send registration request
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  
  int httpCode = http.POST(jsonPayload);
  
  if (httpCode > 0) {
    Serial.print("Registration response code: ");
    Serial.println(httpCode);
    
    if (httpCode == 200 || httpCode == 201) {
      String response = http.getString();
      Serial.println("Registration successful!");
      Serial.println(response);
    } else {
      Serial.println("Registration failed:");
      Serial.println(http.getString());
    }
  } else {
    Serial.print("Registration error: ");
    Serial.println(http.errorToString(httpCode));
  }
  
  http.end();
}

void checkButton() {
  int reading = digitalRead(PIN_BUTTON);
  
  // Check if reading changed (debouncing)
  if (reading != buttonD0.lastReading) {
    buttonD0.lastDebounceTime = millis();
  }
  
  // If enough time has passed, consider it a valid state change
  if ((millis() - buttonD0.lastDebounceTime) > DEBOUNCE_DELAY) {
    if (reading != buttonD0.currentState) {
      buttonD0.currentState = reading;
      
      // Only send if state actually changed from last sent state
      if (buttonD0.currentState != buttonD0.lastSentState) {
        // LOW = On, HIGH = Off
        String value = (buttonD0.currentState == LOW) ? "On" : "Off";
        sendTrigger("TestESP32.Button", value);
        buttonD0.lastSentState = buttonD0.currentState;
      }
    }
  }
  
  buttonD0.lastReading = reading;
}

void checkDiscrete() {
  int readingD1 = digitalRead(PIN_DISCRETE_D1);
  int readingD2 = digitalRead(PIN_DISCRETE_D2);
  
  bool changed = false;
  
  // Debounce D1
  if (readingD1 != discreteD1.lastReading) {
    discreteD1.lastDebounceTime = millis();
  }
  
  if ((millis() - discreteD1.lastDebounceTime) > DEBOUNCE_DELAY) {
    if (readingD1 != discreteD1.currentState) {
      discreteD1.currentState = readingD1;
      changed = true;
    }
  }
  
  discreteD1.lastReading = readingD1;
  
  // Debounce D2
  if (readingD2 != discreteD2.lastReading) {
    discreteD2.lastDebounceTime = millis();
  }
  
  if ((millis() - discreteD2.lastDebounceTime) > DEBOUNCE_DELAY) {
    if (readingD2 != discreteD2.currentState) {
      discreteD2.currentState = readingD2;
      changed = true;
    }
  }
  
  discreteD2.lastReading = readingD2;
  
  // If either pin changed, calculate new value and send trigger
  if (changed) {
    int newValue = calculateDiscreteValue();
    
    if (newValue != lastDiscreteValue) {
      sendTrigger("TestESP32.Discrete", String(newValue));
      lastDiscreteValue = newValue;
    }
  }
}

int calculateDiscreteValue() {
  // HIGH = 0, LOW = 1 (inverted logic with pullups)
  int bit0 = (discreteD1.currentState == LOW) ? 1 : 0;
  int bit1 = (discreteD2.currentState == LOW) ? 1 : 0;
  
  // Binary combination: D2 is MSB, D1 is LSB
  return (bit1 << 1) | bit0;
}

void sendTrigger(String triggerName, String value) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Cannot send trigger - no WiFi connection");
    return;
  }
  
  HTTPClient http;
  String url = String("http://") + TRIGGER_SERVER + ":" + TRIGGER_PORT + "/api/trigger-event";
  
  // Create trigger event JSON
  StaticJsonDocument<256> doc;
  doc["name"] = triggerName;
  doc["value"] = value;
  doc["id"] = triggerIdCounter++;
  
  String jsonPayload;
  serializeJson(doc, jsonPayload);
  
  Serial.print("Sending trigger: ");
  Serial.print(triggerName);
  Serial.print(" = ");
  Serial.print(value);
  Serial.print(" (ID: ");
  Serial.print(triggerIdCounter - 1);
  Serial.println(")");
  
  // Send trigger event
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  
  int httpCode = http.POST(jsonPayload);
  
  if (httpCode > 0) {
    if (httpCode == 200) {
      Serial.println("  ✓ Trigger sent successfully");
    } else {
      Serial.print("  ✗ Unexpected response: ");
      Serial.println(httpCode);
    }
  } else {
    Serial.print("  ✗ Send error: ");
    Serial.println(http.errorToString(httpCode));
  }
  
  http.end();
}
