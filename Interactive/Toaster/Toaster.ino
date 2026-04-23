/*
 * Toaster - Sends trigger when toast pops!
 * Device: ESP32s3
 *
 * Triggers:
 * - Toaster.Toast - pin 23
 */

// #define SLEEP_ON_IDLE  // NB - some esp32 variants, notably the c3, use different ways of sleeping. Comment this out if you have compilation problems
#include <WiFi.h>
#include <ETH.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_sleep.h>
#include <LittleFS.h>
#include "DeviceTriggers.h"
#include "esp_wifi.h"

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

// Device Configuration
const char* DEVICE_NAME = "Toaster";

// Pin Definitions
const int PIN_TOAST = 23;      // One shot - our toast is done

// Trigger device and triggers (will be initialized in setup after loading config)
TriggerDevice* triggerDevice = nullptr;
std::shared_ptr<OneShotTrigger> toastTrigger;

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.setAutoReconnect(true);
  delay(500);

  // Force station mode and clear any ghost state.
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(1000);
  WiFi.mode(WIFI_STA);

  Serial.println("\n\n=== Toaster Device ===");

  // Load configuration from LittleFS (or use defaults)
  if (!loadConfig()) {
    Serial.println("Using default configuration values");
    // Set defaults
    strlcpy(config.wifi_ssid_primary, "not", sizeof(config.wifi_ssid_primary));
    strlcpy(config.wifi_pass_primary, "set", sizeof(config.wifi_pass_primary));
    strlcpy(config.wifi_ssid_secondary, "not", sizeof(config.wifi_ssid_secondary));
    strlcpy(config.wifi_pass_secondary, "set", sizeof(config.wifi_pass_secondary));
    strlcpy(config.trigger_server, "192.168.5.174", sizeof(config.trigger_server));
    config.trigger_port = 5002;
  }

  // Configure pins. NB - pinMode not required for analog pins
  pinMode(PIN_TOAST, INPUT_PULLUP);

  // Read initial states
  bool initialToastState = (digitalRead(PIN_TOAST) == LOW); // LOW = On, HIGH = Off

  Serial.println(initialToastState ? "TOAST" : "No Toast");

  // Create trigger device with loaded configuration
  triggerDevice = new TriggerDevice(DEVICE_NAME, config.trigger_server, config.trigger_port);

  // Initialize triggers using the library
  toastTrigger = triggerDevice->AddOneShotTrigger("Toast");

  // Connect to WiFi
  connectToWiFi();

#ifdef SLEEP_ON_IDLE
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
#endif // SLEEP_ON_IDLE

  Serial.println("Light sleep enabled:");
  Serial.println("  - Wake on digital pin changes");
  Serial.println("  - Wake every 10 seconds for continuous reading");
  Serial.println("\nSetup complete. Monitoring triggers...\n");
}

void loop() {
  static int prevRead = HIGH;

  // Check WiFi connection; Update() will gate gateway traffic on network status
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Reconnecting...");
    connectToWiFi();
  }

  // Drive registration, keepalive, and reconnect logic.
  // Handles all registration cadence internally; trigger events will be gated until CONNECTED.
  triggerDevice->Update();

  // Check for toast (23) - LOW = On, HIGH = Off
  bool reading = digitalRead(PIN_TOAST);
  if (prevRead == HIGH && reading == LOW) {
    toastTrigger->SendTriggerEvent();
  }
  prevRead = reading;

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

#ifdef SLEEP_ON_IDLE
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
#endif // SLEEP_ON_IDLE
}

void connectToWiFi() {
  Serial.println("\n--- WiFi Connection ---");

  // Try primary network first
  Serial.printf("Attempting connection to Primary (%s)...\n", config.wifi_ssid_primary);

  WiFi.begin(config.wifi_ssid_primary, config.wifi_pass_primary);

  // Wait up to 10 seconds for connection
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && WiFi.status() != WL_CONNECT_FAILED && attempts < 100) {
    delay(500);
    Serial.print(".");
    Serial.print(WiFi.status());
    attempts++;
  }

  // If primary failed, try secondary
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nPrimary network not available.");
    Serial.printf("Attempting connection to Secondary (%s)...\n", config.wifi_ssid_secondary);

    WiFi.disconnect();
    delay(500);  // let the stack finish tearing down before starting a new connection
    WiFi.mode(WIFI_STA);
    delay(500);

    WiFi.begin(config.wifi_ssid_secondary, config.wifi_pass_secondary);

    attempts = 0;
    while (WiFi.status() != WL_CONNECTED && WiFi.status() != WL_CONNECT_FAILED && attempts < 100) {
      delay(500);
      Serial.print(".");
      Serial.print(WiFi.status());
      attempts++;
    }
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("SSID: ");
    Serial.println(WiFi.SSID());
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.printf("BSSID: %s  Channel: %d\n", WiFi.BSSIDstr().c_str(), WiFi.channel());
    Serial.print("Signal Strength: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println("\nFailed to connect to WiFi. Will retry...");
  }
}
