#include <WiFi.h>
#include <ETH.h>
#include <HTTPClient.h>

// HTTP Request Queue Structure with timestamp
// Using fixed-size char arrays instead of String to avoid dangling pointer issues
// when passing through FreeRTOS queue
struct HTTPRequest {
  char url[256];          // Fixed size to safely copy through queue
  char payload[512];      // Fixed size for JSON payload
  bool isRegistration;
  unsigned long timestamp;  // millis() when queued
};

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
  TriggerDevice(String name, String triggerServerURL, int16_t triggerServerPort, int16_t listenerPort=5000, bool useWifi=true, int httpTimeout=5000) 
  : m_name(name), m_triggerServerURL(triggerServerURL), m_triggerServerPort(triggerServerPort), m_listenerPort(listenerPort), m_usesWifi(useWifi), m_httpTimeout(httpTimeout) {
    // Create HTTP request queue (holds up to 10 requests)
    m_httpQueue = xQueueCreate(10, sizeof(HTTPRequest));
    if (m_httpQueue == NULL) {
      Serial.println("Failed to create HTTP queue!");
      return;
    }

    HttpWorkerParameters params;
    params.httpTimeoutMs = m_httpTimeout;
    params.maxAgeMs = 3000;
    params.httpQueue = m_httpQueue;
    
    // Create HTTP worker task (runs on Core 0, main loop runs on Core 1)
    // (NB - esp32c3 only has one core)
    xTaskCreatePinnedToCore(
      httpWorkerTask,        // Task function
      "HTTP_Worker",         // Task name
      8192,                  // Stack size (bytes)
      (void *)&params,       // Task parameters
      1,                     // Priority (1 = low, higher numbers = higher priority)
      &m_httpTaskHandle,     // Task handle
      0                      // Core ID (0 = Core 0, 1 = Core 1)
    );
    
    Serial.println("HTTP worker thread started on Core 0");
    Serial.println("  - Requests older than 3 seconds will be discarded");
    
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
    // Check if strings fit in fixed-size buffers
    if (url.length() >= sizeof(HTTPRequest::url)) {
      Serial.printf("ERROR: URL too long (%d bytes, max %d)\n", url.length(), sizeof(HTTPRequest::url) - 1);
      return;
    }
    if (jsonPayload.length() >= sizeof(HTTPRequest::payload)) {
      Serial.printf("ERROR: Payload too long (%d bytes, max %d)\n", jsonPayload.length(), sizeof(HTTPRequest::payload) - 1);
      return;
    }
    
    HTTPRequest request;
    // Safe to copy - we checked the sizes above
    strcpy(request.url, url.c_str());
    strcpy(request.payload, jsonPayload.c_str());
    request.isRegistration = true;
    request.timestamp = millis();  // Add timestamp
    
    if (xQueueSend(m_httpQueue, &request, pdMS_TO_TICKS(100)) != pdTRUE) {
      Serial.println("Failed to queue registration request - queue full");
    }
  };

  String GetName() {
    return m_name;
  };
  
  // Check if HTTP queue has space (for sleep coordination)
  bool IsHttpQueueEmpty() {
    return uxQueueMessagesWaiting(m_httpQueue) == 0;
  };

  int GetNumberRequestsPending() {
    return uxQueueMessagesWaiting(m_httpQueue);
  };

  // HTTP Worker Task - runs in separate thread
  static void httpWorkerTask(void* parameter) {
    HTTPRequest request;
    HTTPClient http;
    const unsigned long MAX_AGE_MS = 3000;  // 3 seconds - discard older requests

    HttpWorkerParameters *params = (HttpWorkerParameters *)(parameter);
    int httpTimeoutMs = params->httpTimeoutMs;
    int maxAgeMs = params->maxAgeMs;
    QueueHandle_t httpQueue = params->httpQueue;


    if (httpQueue == NULL) {
      return;
    }
    
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
                      request.url, age);
        
        http.begin(request.url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(httpTimeoutMs);
        
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
  };

  friend class ButtonTrigger;
  friend class OneShotTrigger;
  friend class ContinuousTrigger;
  friend class DiscreteTrigger;
  friend class Trigger;

private:
  struct HttpWorkerParameters {
    int httpTimeoutMs;
    int maxAgeMs;
    QueueHandle_t httpQueue;
  };
  String m_name;
  String m_triggerServerURL;
  int16_t m_triggerServerPort;
  int16_t m_listenerPort;
  std::vector<std::shared_ptr<Trigger>> m_triggers;
  bool m_usesWifi;
  // Using free RTOS task/queue to prevent blocking on http calls
  QueueHandle_t m_httpQueue = NULL;
  TaskHandle_t m_httpTaskHandle = NULL;
  int m_httpTimeout;
  
  bool sendTriggerEvent(Trigger& trigger) {
    if (m_httpQueue == NULL) {
      Serial.println("Could not create queue, will not send trigger");
      return false;
    }
    StaticJsonDocument<256> doc;
    doc["name"] = m_name + "." + trigger.m_name;
    doc["value"] = trigger.getCurrentValueAsString();
    doc["id"] = trigger.m_currentMsgId++;

    String jsonPayload;
    serializeJson(doc, jsonPayload);

    Serial.println("Queueing trigger: " + jsonPayload);

    // Queue the request for the HTTP worker thread
    String url = String("http://") + m_triggerServerURL + ":" + m_triggerServerPort + "/api/trigger-event";
    
    // Check if strings fit in fixed-size buffers
    if (url.length() >= sizeof(HTTPRequest::url)) {
      Serial.printf("ERROR: URL too long (%d bytes, max %d)\n", url.length(), sizeof(HTTPRequest::url) - 1);
      return false;
    }
    if (jsonPayload.length() >= sizeof(HTTPRequest::payload)) {
      Serial.printf("ERROR: Payload too long (%d bytes, max %d)\n", jsonPayload.length(), sizeof(HTTPRequest::payload) - 1);
      return false;
    }
    
    HTTPRequest request;
    // Safe to copy - we checked the sizes above
    strcpy(request.url, url.c_str());
    strcpy(request.payload, jsonPayload.c_str());
    request.isRegistration = false;
    request.timestamp = millis();  // Add timestamp
    
    if (xQueueSend(m_httpQueue, &request, pdMS_TO_TICKS(100)) != pdTRUE) {
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

