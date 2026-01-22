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
#include <ETH.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_sleep.h>
#include <LittleFS.h>
#include "DeviceTriggers.h"

// Configuration structure stored in LittleFS
struct DeviceConfig {
  char wifi_ssid_primary[64];
  char wifi_pass_primary[64];
  char wifi_ssid_secondary[64];
  char wifi_pass_secondary[64];
  char trigger_server[64];
  int trigger_port;
};

// Global configuration (loaded from LittleFS or defaults)
DeviceConfig config;

// Load configuration from LittleFS
bool loadConfig() {
  Serial.println("\n--- Loading Configuration from LittleFS ---");
  
  if (!LittleFS.begin(true)) {  // true = format on fail
    Serial.println("Failed to mount LittleFS");
    return false;
  }
  
  if (!LittleFS.exists("/config.json")) {
    Serial.println("Config file does not exist, will use defaults");
    LittleFS.end();
    return false;
  }
  
  File file = LittleFS.open("/config.json", "r");
  if (!file) {
    Serial.println("Failed to open config file");
    LittleFS.end();
    return false;
  }
  
  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, file);
  file.close();
  LittleFS.end();
  
  if (error) {
    Serial.print("Failed to parse config file: ");
    Serial.println(error.c_str());
    return false;
  }
  
  // Load configuration values
  strlcpy(config.wifi_ssid_primary, doc["wifi_ssid_primary"] | "not", sizeof(config.wifi_ssid_primary));
  strlcpy(config.wifi_pass_primary, doc["wifi_pass_primary"] | "set", sizeof(config.wifi_pass_primary));
  strlcpy(config.wifi_ssid_secondary, doc["wifi_ssid_secondary"] | "not", sizeof(config.wifi_ssid_secondary));
  strlcpy(config.wifi_pass_secondary, doc["wifi_pass_secondary"] | "set", sizeof(config.wifi_pass_secondary));
  strlcpy(config.trigger_server, doc["trigger_server"] | "192.168.5.174", sizeof(config.trigger_server));
  config.trigger_port = doc["trigger_port"] | 5002;
  
  Serial.println("Configuration loaded successfully:");
  Serial.printf("  Primary WiFi: %s\n", config.wifi_ssid_primary);
  Serial.printf("  Secondary WiFi: %s\n", config.wifi_ssid_secondary);
  Serial.printf("  Trigger Server: %s:%d\n", config.trigger_server, config.trigger_port);
  
  return true;
}

// Save configuration to LittleFS
bool saveConfig() {
  Serial.println("\n--- Saving Configuration to LittleFS ---");
  
  if (!LittleFS.begin(true)) {
    Serial.println("Failed to mount LittleFS");
    return false;
  }
  
  StaticJsonDocument<512> doc;
  doc["wifi_ssid_primary"] = config.wifi_ssid_primary;
  doc["wifi_pass_primary"] = config.wifi_pass_primary;
  doc["wifi_ssid_secondary"] = config.wifi_ssid_secondary;
  doc["wifi_pass_secondary"] = config.wifi_pass_secondary;
  doc["trigger_server"] = config.trigger_server;
  doc["trigger_port"] = config.trigger_port;
  
  File file = LittleFS.open("/config.json", "w");
  if (!file) {
    Serial.println("Failed to open config file for writing");
    LittleFS.end();
    return false;
  }
  
  if (serializeJson(doc, file) == 0) {
    Serial.println("Failed to write config file");
    file.close();
    LittleFS.end();
    return false;
  }
  
  file.close();
  LittleFS.end();
  
  Serial.println("Configuration saved successfully");
  return true;
}

// Device Configuration (defaults - will be overridden by LittleFS config)
const char* DEVICE_NAME = "TestESP32";

// Pin Definitions
const int PIN_BUTTON = D0;      // TestESP32.Button
const int PIN_DISCRETE_D1 = D1; // TestESP32.Discrete bit 0
const int PIN_DISCRETE_D2 = D2; // TestESP32.Discrete bit 1
const int PIN_ONESHOT = D3;     // TestESP32.OneShot
const int PIN_CONTINUOUS = A10;  // TestESP32.Continuous (analog)

// Registration tracking
const unsigned long REGISTRATION_INTERVAL = 120000; // 2 minutes in milliseconds
unsigned long lastRegistrationTime = 0;

// Trigger device and triggers (will be initialized in setup after loading config)
TriggerDevice* triggerDevice = nullptr;
std::shared_ptr<ButtonTrigger> buttonTrigger;
std::shared_ptr<DiscreteTrigger> discreteTrigger;
std::shared_ptr<ContinuousTrigger> continuousTrigger;

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n=== TestESP32 Trigger Device ===");
  
  // Load configuration from LittleFS (or use defaults)
  if (!loadConfig()) {
    Serial.println("Using default configuration values");
    // Set defaults
    strlcpy(config.wifi_ssid_primary, "flg-haven", sizeof(config.wifi_ssid_primary));
    strlcpy(config.wifi_pass_primary, "fuckoffanddie", sizeof(config.wifi_pass_primary));
    strlcpy(config.wifi_ssid_secondary, "medea", sizeof(config.wifi_ssid_secondary));
    strlcpy(config.wifi_pass_secondary, "!medea4u", sizeof(config.wifi_pass_secondary));
    strlcpy(config.trigger_server, "192.168.5.174", sizeof(config.trigger_server));
    config.trigger_port = 5002;
  }
  
  // Configure pins. NB - pinMode not required for analog pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_DISCRETE_D1, INPUT_PULLUP);
  pinMode(PIN_DISCRETE_D2, INPUT_PULLUP);
  pinMode(PIN_ONESHOT, INPUT_PULLUP);
  pinMode(PIN_CONTINUOUS, INPUT);
  analogReadResolution(12); // Set resolution to 12 bits (0-4095)
  analogSetAttenuation(ADC_11db); // Set attenuation to 11dB (0-3.3V range)
  
  // Read initial states
  bool initialButtonState = (digitalRead(PIN_BUTTON) == LOW); // LOW = On, HIGH = Off
  int bit0 = (digitalRead(PIN_DISCRETE_D1) == LOW) ? 1 : 0;
  int bit1 = (digitalRead(PIN_DISCRETE_D2) == LOW) ? 1 : 0;
  int initialDiscreteValue = (bit1 << 1) | bit0;
  
  Serial.print("Initial Button State: ");
  Serial.println(initialButtonState ? "On" : "Off");
  Serial.print("Initial Discrete Value: ");
  Serial.println(initialDiscreteValue);
  
  // Create trigger device with loaded configuration
  triggerDevice = new TriggerDevice(DEVICE_NAME, config.trigger_server, config.trigger_port);
  
  // Initialize triggers using the library
  buttonTrigger = triggerDevice->AddButtonTrigger("Button", initialButtonState, 50);
  discreteTrigger = triggerDevice->AddDiscreteTrigger("Discrete", {0, 1, 2, 3}, initialDiscreteValue, 50);
  continuousTrigger = triggerDevice->AddContinuousTrigger("Continuous", 1.0f, 0.0f, 0.0f, 5.0f);
  
  // Connect to WiFi
  connectToWiFi();
  
  // Register device with trigger server
  triggerDevice->RegisterDevice();
  lastRegistrationTime = millis();
  
  // Configure light sleep wakeup sources
  // Wake on digital input pin changes (any level change)
  esp_sleep_enable_ext1_wakeup(
    (1ULL << PIN_BUTTON) | (1ULL << PIN_DISCRETE_D1) | (1ULL << PIN_DISCRETE_D2) | (1ULL << PIN_ONESHOT),
    ESP_EXT1_WAKEUP_ANY_HIGH  // Wake when any pin goes HIGH (from pullup going LOW means button pressed)
  );
  
  // Also enable wakeup on LOW (for when pins pulled to ground)
  gpio_wakeup_enable((gpio_num_t)PIN_BUTTON, GPIO_INTR_LOW_LEVEL);
  gpio_wakeup_enable((gpio_num_t)PIN_DISCRETE_D1, GPIO_INTR_LOW_LEVEL);
  gpio_wakeup_enable((gpio_num_t)PIN_DISCRETE_D2, GPIO_INTR_LOW_LEVEL);
  gpio_wakeup_enable((gpio_num_t)PIN_ONESHOT, GPIO_INTR_LOW_LEVEL);
  esp_sleep_enable_gpio_wakeup();
  
  // Configure timer wakeup - wake every 10 seconds
  esp_sleep_enable_timer_wakeup(10 * 1000000);  // 10 seconds in microseconds
  
  Serial.println("Light sleep enabled:");
  Serial.println("  - Wake on digital pin changes");
  Serial.println("  - Wake every 10 seconds for continuous reading");
  Serial.println("\nSetup complete. Monitoring triggers...\n");
}

void loop() {
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Reconnecting...");
    connectToWiFi();
  }
  
  // Periodic device registration (every 2 minutes)
  unsigned long currentTime = millis();
  if (currentTime - lastRegistrationTime >= REGISTRATION_INTERVAL) {
    triggerDevice->RegisterDevice();
    lastRegistrationTime = currentTime;
  }
  
  // Check Button (D0) - LOW = On, HIGH = Off
  int reading = digitalRead(PIN_BUTTON);
  bool buttonState = (reading == LOW);
  buttonTrigger->CheckForEventAndSend(buttonState);
  
  // Check Discrete (D1, D2)
  int readingD1 = digitalRead(PIN_DISCRETE_D1);
  int readingD2 = digitalRead(PIN_DISCRETE_D2);
  int bit0 = (readingD1 == LOW) ? 1 : 0;
  int bit1 = (readingD2 == LOW) ? 1 : 0;
  int discreteValue = (bit1 << 1) | bit0;
  discreteTrigger->CheckForEventAndSend(discreteValue);
  
  // Check Continuous
  int readingAnalog = analogRead(PIN_CONTINUOUS);
  float continuousValue = ((float)readingAnalog) / 4095.0f;
  continuousTrigger->CheckForEventAndSend(continuousValue);
  
  // Wait for HTTP queue to be empty before sleeping
  // This gives the HTTP worker thread time to process pending requests
  unsigned long waitStart = millis();
  const unsigned long MAX_WAIT_MS = 2000;  // Maximum 2 seconds
  
  while (!triggerDevice->IsHttpQueueEmpty() && (millis() - waitStart < MAX_WAIT_MS)) {
    delay(10);  // Give HTTP thread time to work
  }
  
  if (!triggerDevice->IsHttpQueueEmpty()) {
    Serial.printf("Warning: HTTP queue still has %d requests pending\n", triggerDevice->GetNumberRequestsPending());
  }
  
  // Enter light sleep mode
  // Will wake on pin changes or after 10 seconds timer
  // Note: The HTTP worker task will be suspended during sleep
  Serial.println("Entering light sleep...");
  Serial.flush();  // Make sure serial data is sent before sleeping
  esp_light_sleep_start();
  
  // After waking up
  esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();
  switch(wakeup_reason) {
    case ESP_SLEEP_WAKEUP_EXT1:
      Serial.println("Woke from digital pin change");
      break;
    case ESP_SLEEP_WAKEUP_GPIO:
      Serial.println("Woke from GPIO interrupt");
      break;
    case ESP_SLEEP_WAKEUP_TIMER:
      Serial.println("Woke from timer (10s elapsed)");
      break;
    default:
      Serial.printf("Woke from other reason: %d\n", wakeup_reason);
      break;
  }
}

void connectToWiFi() {
  Serial.println("\n--- WiFi Connection ---");
  
  // Try primary network first
  Serial.print("Attempting to connect to ");
  Serial.print(config.wifi_ssid_primary);
  Serial.println("...");
  
  WiFi.begin(config.wifi_ssid_primary, config.wifi_pass_primary);
  
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
    Serial.print(config.wifi_ssid_secondary);
    Serial.println("...");

    WiFi.mode(WIFI_OFF);
    
    WiFi.begin(config.wifi_ssid_secondary, config.wifi_pass_secondary);
    
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
