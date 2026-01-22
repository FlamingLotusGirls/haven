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

// HTTP Request Queue Structure with timestamp
struct HTTPRequest {
  String url;
  String payload;
  bool isRegistration;
  unsigned long timestamp;  // millis() when queued
};

// FreeRTOS queue for HTTP requests
QueueHandle_t httpQueue = NULL;
TaskHandle_t httpTaskHandle = NULL;

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

// HTTP Worker Task - runs in separate thread
void httpWorkerTask(void* parameter) {
  HTTPRequest request;
  HTTPClient http;
  const unsigned long MAX_AGE_MS = 3000;  // 3 seconds - discard older requests
  
  while (true) {
    // Wait for requests in queue (blocks until available)
    if (xQueueReceive(httpQueue, &request, portMAX_DELAY) == pdTRUE) {
      // Check if request is too old
      unsigned long age = millis() - request.timestamp;
      if (age > MAX_AGE_MS) {
        Serial.printf("[HTTP Thread] Discarding stale %s request (age: %lu ms)\n",
                      request.isRegistration ? "registration" : "trigger", age);
        continue;  // Skip this request
      }
      
      Serial.printf("[HTTP Thread] Processing %s request to %s (age: %lu ms)\n", 
                    request.isRegistration ? "registration" : "trigger", 
                    request.url.c_str(), age);
      
      http.begin(request.url);
      http.addHeader("Content-Type", "application/json");
      http.setTimeout(5000); // 5 second timeout
      
      int httpCode = http.POST(request.payload);
      
      if (httpCode > 0) {
        if (httpCode == 200 || httpCode == 201) {
          Serial.printf("[HTTP Thread] %s successful (code %d)\n", 
                        request.isRegistration ? "Registration" : "Trigger", 
                        httpCode);
        } else {
          Serial.printf("[HTTP Thread] %s failed with code %d\n",
                        request.isRegistration ? "Registration" : "Trigger",
                        httpCode);
        }
      } else {
        Serial.printf("[HTTP Thread] %s error: %s\n",
                      request.isRegistration ? "Registration" : "Trigger",
                      http.errorToString(httpCode).c_str());
      }
      
      http.end();
    }
  }
}

// START TRIGGER LIBRARY (moved to top for proper compilation order)
class TriggerDevice;

class Trigger{
public:
  String GetName() {
      return m_name;
  };
  bool SendTriggerEvent();
  virtual ~Trigger() {};

  friend class TriggerDevice;

protected:
    Trigger(TriggerDevice& device, String name) : m_device(device), m_name(name) {}
    virtual void addTriggerRegistrationJson(JsonObject& parent) = 0;
    virtual String getCurrentValueAsString() = 0;

    TriggerDevice& m_device;
    String m_name;
    int32_t m_currentMsgId = 0;
};

class ButtonTrigger : public Trigger {
public:
  bool CheckForEventAndSend(bool onOff);
  bool GetCurrentValue() {
      return m_currentState;
  }
  virtual ~ButtonTrigger() {};
  friend class TriggerDevice;

protected:
  ButtonTrigger(TriggerDevice& device, String name, bool initialValue, int debounceTimeMs=50);
  virtual void addTriggerRegistrationJson(JsonObject& baseObject) {
    baseObject["type"] = "On/Off";
  }
  virtual String getCurrentValueAsString() {
    return m_currentState ? "On" : "Off";
  }
  bool m_currentState;
  bool m_lastReading;
  int m_debounceTimeMs;
  int m_lastChangeTime;
};

class OneShotTrigger : public Trigger {
public:
  friend class TriggerDevice;
    virtual ~OneShotTrigger() {};
protected:
  OneShotTrigger(TriggerDevice& device, String name);
  virtual void addTriggerRegistrationJson(JsonObject& baseObject) {
      baseObject["type"] = "OneShot";
  };
  virtual String getCurrentValueAsString() {
      return "";
  };
};

class DiscreteTrigger : public Trigger {
public:
  bool CheckForEventAndSend(int value); 
  virtual ~DiscreteTrigger() {};
  friend class TriggerDevice;
protected: 
  DiscreteTrigger(TriggerDevice& device, String name, std::vector<int>range, int initialValue, int debounceTimeMs=50);
  virtual void addTriggerRegistrationJson(JsonObject& baseObject) {
    baseObject["type"] = "Discrete";
    JsonObject discreteRange = baseObject.createNestedObject("range");
    JsonArray discreteValues = discreteRange.createNestedArray("values");
    for (int value : m_values) {
      discreteValues.add(value);
    }
  };
  virtual String getCurrentValueAsString() {
    return String(m_currentState);
  };
  int m_currentState;
  std::vector<int> m_values;
  int m_debounceTimeMs;
  int m_lastReading;
  int m_lastChangeTime;
};

class ContinuousTrigger : public Trigger {
public:
  bool CheckForEventAndSend(float value);
  virtual ~ContinuousTrigger() {};
  friend class TriggerDevice;
protected:
  ContinuousTrigger(TriggerDevice& device, String name, float maxVal, float minVal, float initialValue, float marginPercent=5);
  virtual void addTriggerRegistrationJson(JsonObject& baseObject) {
    baseObject["type"] = "Continuous";
    JsonObject continuousRange = baseObject.createNestedObject("range");
    continuousRange["min"] = m_minVal;
    continuousRange["max"] = m_maxVal;
  };
  virtual String getCurrentValueAsString() {
    return String(m_currentState);
  };
  float m_currentState;
  float m_maxVal;
  float m_minVal;
  float m_margin;
};

class TriggerDevice {
public: 
    TriggerDevice(String name, String triggerServerURL, int16_t triggerServerPort, int16_t listenerPort = 5000, bool useWifi=true) 
    : m_name(name), m_triggerServerURL(triggerServerURL), m_triggerServerPort(triggerServerPort), m_listenerPort(listenerPort), m_usesWifi(useWifi) {
    };
    
    ~TriggerDevice() {
    }
    
    std::shared_ptr<ButtonTrigger> AddButtonTrigger(String name, bool initialValue, int debounceTimeMs=50) {
        std::shared_ptr<ButtonTrigger> buttonTrigger = std::shared_ptr<ButtonTrigger>(new ButtonTrigger(*this, name, initialValue, debounceTimeMs));
        m_triggers.push_back(buttonTrigger);
        return buttonTrigger;
    };
    std::shared_ptr<DiscreteTrigger> AddDiscreteTrigger(String name, std::vector<int>range, int initialValue, int debounceTimeMs=50) {
        std::shared_ptr<DiscreteTrigger> discreteTrigger = std::shared_ptr<DiscreteTrigger>(new DiscreteTrigger(*this, name, range, initialValue, debounceTimeMs));
        m_triggers.push_back(discreteTrigger);
        return discreteTrigger;
    };
    std::shared_ptr<ContinuousTrigger> AddContinuousTrigger(String name, float maxVal, float minVal, float initialVal, float marginPercent=5) {
        std::shared_ptr<ContinuousTrigger> continuousTrigger = std::shared_ptr<ContinuousTrigger>(new ContinuousTrigger(*this, name, maxVal, minVal, initialVal, marginPercent));
        m_triggers.push_back(continuousTrigger);
        return continuousTrigger;
    };
    std::shared_ptr<OneShotTrigger> AddOneShotTrigger(String name) {
        std::shared_ptr<OneShotTrigger> oneShotTrigger = std::shared_ptr<OneShotTrigger>(new OneShotTrigger(*this, name));
        m_triggers.push_back(oneShotTrigger);
        return oneShotTrigger;
    };

    void RegisterDevice() {
        if (m_usesWifi) {
            if (WiFi.status() != WL_CONNECTED) {
                Serial.println("Cannot register - no WiFi connection");
                return;
            }
        } else {
            // Check Ethernet connection
            if (!ETH.linkUp()) {
                Serial.println("Cannot register - no Ethernet connection");
                return;
            }
        }
  
        Serial.println("\n--- Device Registration ---");
  
        String url = String("http://") + m_triggerServerURL + ":" + m_triggerServerPort + "/api/register-device";
  
        Serial.print("Registering at: ");
        Serial.println(url);
  
        // Create registration JSON
        StaticJsonDocument<512> doc;
        doc["name"] = m_name;
        if (m_usesWifi) {
            doc["ip"] = WiFi.localIP().toString();
        } else {
            // Get IP address from Ethernet
            doc["ip"] = ETH.localIP().toString();
        }
  
        JsonArray triggers = doc.createNestedArray("triggers");
        for (std::shared_ptr<Trigger> trigger : m_triggers) {
            JsonObject triggerObject = triggers.createNestedObject();
            triggerObject["name"] = m_name + "."  + trigger->GetName();
            trigger->addTriggerRegistrationJson(triggerObject);
        }

        // Serialize JSON
        String jsonPayload;
        serializeJson(doc, jsonPayload);
  
        Serial.println("Registration payload:");
        Serial.println(jsonPayload);
  
        // Queue the request for the HTTP worker thread
        HTTPRequest request;
        request.url = url;
        request.payload = jsonPayload;
        request.isRegistration = true;
        request.timestamp = millis();  // Add timestamp
        
        if (xQueueSend(httpQueue, &request, pdMS_TO_TICKS(100)) != pdTRUE) {
            Serial.println("Failed to queue registration request - queue full");
        }
    };

    String GetName() {
        return m_name;
    };
    
    // Check if HTTP queue has space (for sleep coordination)
    bool IsHttpQueueEmpty() {
        return uxQueueMessagesWaiting(httpQueue) == 0;
    };

    friend class ButtonTrigger;
    friend class OneShotTrigger;
    friend class ContinuousTrigger;
    friend class DiscreteTrigger;
    friend class Trigger;

private:
    String m_name;
    String m_triggerServerURL;
    int16_t m_triggerServerPort;
    int16_t m_listenerPort;
    std::vector<std::shared_ptr<Trigger>> m_triggers;
    bool m_usesWifi;
    
    bool sendTriggerEvent(Trigger& trigger) {
        StaticJsonDocument<256> doc;
        doc["name"] = m_name + "." + trigger.m_name;
        doc["value"] = trigger.getCurrentValueAsString();
        doc["id"] = trigger.m_currentMsgId++;
  
        String jsonPayload;
        serializeJson(doc, jsonPayload);

        Serial.println("Queueing trigger: " + jsonPayload);

        // Queue the request for the HTTP worker thread
        HTTPRequest request;
        request.url = String("http://") + m_triggerServerURL + ":" + m_triggerServerPort + "/api/trigger-event";
        request.payload = jsonPayload;
        request.isRegistration = false;
        request.timestamp = millis();  // Add timestamp
        
        if (xQueueSend(httpQueue, &request, pdMS_TO_TICKS(100)) != pdTRUE) {
            Serial.println("Failed to queue trigger request - queue full");
            return false;
        }
        
        return true;  // Request was queued
    }
};

// Implementations
bool Trigger::SendTriggerEvent() {
    return m_device.sendTriggerEvent(*this);
}

ButtonTrigger::ButtonTrigger(TriggerDevice& device, String name, bool initialValue, int debounceTimeMs) : Trigger(device, name), 
m_currentState(initialValue), m_debounceTimeMs(debounceTimeMs) {
    m_lastChangeTime = millis();
    m_lastReading = m_currentState;
};

bool ButtonTrigger::CheckForEventAndSend(bool onOff) {
  bool triggerSent = false;
  if (m_lastReading != onOff) {
    m_lastChangeTime = millis();
    m_lastReading = onOff;
  }
  if (m_lastReading != m_currentState && millis() > m_lastChangeTime + m_debounceTimeMs) {
    m_currentState = onOff;
    triggerSent = m_device.sendTriggerEvent(*this);
  }
  return triggerSent;
}

DiscreteTrigger::DiscreteTrigger(TriggerDevice& device, String name, std::vector<int>range, int initialValue, int debounceTimeMs) : Trigger(device, name), 
m_values(range), m_currentState(initialValue), m_debounceTimeMs(debounceTimeMs) {
    m_lastChangeTime = millis();
    m_lastReading = m_currentState;
}

bool DiscreteTrigger::CheckForEventAndSend(int value) {
  int count = std::count(m_values.begin(), m_values.end(), value);
  if (count <= 0) {
    Serial.printf("Value %d not legal for trigger %s\n", value, (m_device.GetName() + "." + m_name).c_str());
    return false;
  }
  bool triggerSent = false;
  if (m_lastReading != value) {
    m_lastChangeTime = millis();
    m_lastReading = value;
  }
  if (m_lastReading != m_currentState && millis() > m_lastChangeTime + m_debounceTimeMs) {
    m_currentState = value;
    triggerSent = m_device.sendTriggerEvent(*this);
  }
  return triggerSent;
}

ContinuousTrigger::ContinuousTrigger(TriggerDevice& device, String name, float maxVal, float minVal, float initialValue, float marginPercent) : Trigger(device, name), 
m_maxVal(maxVal), m_minVal(minVal), m_currentState(initialValue){
    m_margin = abs(m_maxVal - m_minVal) * marginPercent/200.0f;
}

bool ContinuousTrigger::CheckForEventAndSend(float value) {
  if (value < m_minVal || value > m_maxVal) {
    Serial.printf("Value %f not legal for trigger %s\n", value, (m_device.GetName() + "." + m_name).c_str());
    return false;
  }
  bool triggerSent = false;
  if (abs(value - m_currentState) > m_margin) {
      m_currentState = value;
      triggerSent = m_device.sendTriggerEvent(*this);
  }
  return triggerSent;
}

OneShotTrigger::OneShotTrigger(TriggerDevice& device, String name) : Trigger(device, name) {};
// END TRIGGER LIBRARY

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
  
  // Create HTTP request queue (holds up to 10 requests)
  httpQueue = xQueueCreate(10, sizeof(HTTPRequest));
  if (httpQueue == NULL) {
    Serial.println("Failed to create HTTP queue!");
    while(1) delay(1000); // Halt
  }
  
  // Create HTTP worker task (runs on Core 0, main loop runs on Core 1)
  xTaskCreatePinnedToCore(
    httpWorkerTask,      // Task function
    "HTTP_Worker",       // Task name
    8192,                // Stack size (bytes)
    NULL,                // Task parameters
    1,                   // Priority (1 = low, higher numbers = higher priority)
    &httpTaskHandle,     // Task handle
    0                    // Core ID (0 = Core 0, 1 = Core 1)
  );
  
  Serial.println("HTTP worker thread started on Core 0");
  Serial.println("  - Requests older than 3 seconds will be discarded");
  
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
    Serial.printf("Warning: HTTP queue still has %d requests pending\n", uxQueueMessagesWaiting(httpQueue));
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
