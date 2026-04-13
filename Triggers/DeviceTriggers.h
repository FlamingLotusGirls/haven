#include <WiFi.h>
#include <ETH.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// Callback invoked by the HTTP worker task (Core 0) after an HTTP request completes
// or is discarded.
//   succeeded  - true for HTTP 200/201; false otherwise
//   httpCode   - raw HTTP status code (positive), negative HTTPClient error code,
//                or 0 if the request was discarded as stale (never sent)
//   userData   - the pointer passed alongside the callback
// NOTE: This fires on Core 0; callers are responsible for any cross-core safety.
typedef void (*HttpResultCallback)(bool succeeded, int httpCode, void* userData);

// Gateway connection status as managed by TriggerDevice::Update().
//   DISCONNECTED - last registration failed (or never attempted); retries at RECONNECT_INTERVAL_MS
//   PENDING      - registration request is in-flight; trigger events are gated
//   CONNECTED    - last registration succeeded; trigger events are sent normally
// Written on Core 0 (callback), read on Core 1 (Update / sendTriggerEvent).
// On Xtensa LX7 (ESP32-S3), aligned 32-bit accesses are atomic at the hardware level;
// volatile prevents the compiler from caching the value in a register.
enum class GatewayStatus { DISCONNECTED, PENDING, CONNECTED };

// HTTP Request Queue Structure with timestamp
// Using fixed-size char arrays instead of String to avoid dangling pointer issues
// when passing through FreeRTOS queue.
// 'callback' and 'callbackData' are plain values — no heap allocation, no ownership.
struct HTTPRequest {
  char url[256];            // Fixed size to safely copy through queue
  char payload[512];        // Fixed size for JSON payload
  bool isRegistration;
  unsigned long timestamp;  // millis() when queued
  HttpResultCallback callback;    // nullable; called by HTTP worker on completion
  void*              callbackData; // passed as userData to callback
};

// START TRIGGER LIBRARY (moved to top for proper compilation order)
class TriggerDevice;

class Trigger{
public:
  String GetName() {
      return m_name;
  };
  // SendTriggerEvent: optional callback is called on Core 0 with result.
  bool SendTriggerEvent(HttpResultCallback callback = nullptr, void* callbackData = nullptr);
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
  // Registration cadence constants
  static const unsigned long KEEPALIVE_INTERVAL_MS = 120000;  // re-register when CONNECTED
  static const unsigned long RECONNECT_INTERVAL_MS  =  3000; // retry when DISCONNECTED

  TriggerDevice(String name, String triggerServerURL, int16_t triggerServerPort, int16_t listenerPort=5000, bool useWifi=true, int httpTimeout=5000) 
  : m_name(name), m_triggerServerURL(triggerServerURL), m_triggerServerPort(triggerServerPort), m_listenerPort(listenerPort), m_usesWifi(useWifi), m_httpTimeout(httpTimeout) {
    // Create HTTP request queue (holds up to 10 requests)
    m_httpQueue = xQueueCreate(10, sizeof(HTTPRequest));
    if (m_httpQueue == NULL) {
      Serial.println("Failed to create HTTP queue!");
      return;
    }

    // Heap-allocate params so they remain valid when the task starts up.
    // The task is responsible for deleting this after reading the values.
    HttpWorkerParameters* params = new HttpWorkerParameters();
    params->httpTimeoutMs = m_httpTimeout;
    params->maxAgeMs = 3000;
    params->httpQueue = m_httpQueue;
    
    // Create HTTP worker task (runs on Core 0, main loop runs on Core 1)
    // (NB - esp32c3 only has one core)
    xTaskCreatePinnedToCore(
      httpWorkerTask,        // Task function
      "HTTP_Worker",         // Task name
      8192,                  // Stack size (bytes)
      (void *)params,        // Task parameters (heap-allocated, task will delete)
      1,                     // Priority (1 = low, higher numbers = higher priority)
      &m_httpTaskHandle,     // Task handle
      0                      // Core ID (0 = Core 0, 1 = Core 1)
    );
    
    Serial.println("HTTP worker thread started on Core 0");
    Serial.println("  - Requests older than 3 seconds will be discarded");
  };
  
  ~TriggerDevice() {
    // Kill the HTTP worker task before releasing the queue.
    // The task is normally blocked on xQueueReceive, so vTaskDelete is safe here.
    if (m_httpTaskHandle != NULL) {
      vTaskDelete(m_httpTaskHandle);
      m_httpTaskHandle = NULL;
    }
    // Release any pending requests and delete the queue.
    if (m_httpQueue != NULL) {
      vQueueDelete(m_httpQueue);
      m_httpQueue = NULL;
    }
    // m_triggers (vector of shared_ptr<Trigger>) is destroyed automatically.
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

  // Call from the main loop to drive registration, keepalive, and reconnect logic.
  //
  // State machine:
  //   DISCONNECTED: queues RegisterDevice() every RECONNECT_INTERVAL_MS → PENDING
  //   PENDING:      waits for registration callback; no further queuing
  //   CONNECTED:    queues RegisterDevice() every KEEPALIVE_INTERVAL_MS (stays CONNECTED
  //                 until a keepalive fails, which transitions back to DISCONNECTED)
  //
  // If network is down, resets to DISCONNECTED immediately.
  // If network just came back up, registers immediately without waiting for the interval.
  void Update() {
    bool networkUp = m_usesWifi ? (WiFi.status() == WL_CONNECTED) : ETH.linkUp();
    if (!networkUp) {
      if (m_gatewayStatus != GatewayStatus::DISCONNECTED) {
        Serial.println("[Gateway] Network down - disconnected from gateway, status DISCONNECTED");
        m_gatewayStatus = GatewayStatus::DISCONNECTED;
      }
      m_networkWasUp = false;
      return;
    }

    // Network is up.  If it just came back, reset the registration timer so the
    // interval check below fires immediately rather than waiting for the next cadence.
    if (!m_networkWasUp) {
      Serial.println("[Gateway] Network came up - registering immediately");
      m_lastRegistrationAttemptMs = 0;
      m_networkWasUp = true;
    }

    // While a registration is in-flight, wait for the callback
    if (m_gatewayStatus == GatewayStatus::PENDING) {
      return;
    }

    unsigned long now = millis();
    unsigned long interval = (m_gatewayStatus == GatewayStatus::CONNECTED) ?
                             KEEPALIVE_INTERVAL_MS : RECONNECT_INTERVAL_MS;

    // m_lastRegistrationAttemptMs == 0 means we've never attempted; register immediately
    if (m_lastRegistrationAttemptMs == 0 || (now - m_lastRegistrationAttemptMs >= interval)) {
      // Only go to PENDING for reconnection attempts, not keepalives.
      // During keepalive we stay CONNECTED until we hear back.
      if (m_gatewayStatus == GatewayStatus::DISCONNECTED) {
        m_gatewayStatus = GatewayStatus::PENDING;
        Serial.println("[Gateway] Attempting registration..., status PENDING");
      } else {
        Serial.println("[Gateway] Sending keepalive registration...");
      }
      m_lastRegistrationAttemptMs = now;
      if (!RegisterDevice(onRegistrationResult, this)) {
        // Queue was full; reset so we retry on the next Update()
        Serial.println("[Gateway] Queue full, status DISCONNECTED");
        m_gatewayStatus = GatewayStatus::DISCONNECTED;
      }
    }
  }

  // Returns current gateway connection status.
  GatewayStatus GetGatewayStatus() const { return m_gatewayStatus; }

  // RegisterDevice: manually queue a registration POST.
  // Returns true if the request was successfully queued.
  // Optional callback invoked on Core 0 when the HTTP response arrives.
  // callbackData is passed through as userData to the callback.
  // Note: Update() calls this internally with its own callback to manage gateway state.
  bool RegisterDevice(HttpResultCallback callback = nullptr, void* callbackData = nullptr) {
    if (m_usesWifi) {
      if (WiFi.status() != WL_CONNECTED) {
        Serial.println("Cannot register - no WiFi connection");
        return false;
      }
    } else {
      if (!ETH.linkUp()) {
        Serial.println("Cannot register - no Ethernet connection");
        return false;
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
      doc["ip"] = ETH.localIP().toString();
    }

    JsonArray triggers = doc.createNestedArray("triggers");
    for (std::shared_ptr<Trigger> trigger : m_triggers) {
      JsonObject triggerObject = triggers.createNestedObject();
      triggerObject["name"] = m_name + "."  + trigger->GetName();
      trigger->addTriggerRegistrationJson(triggerObject);
    }

    String jsonPayload;
    serializeJson(doc, jsonPayload);

    Serial.println("Registration payload:");
    Serial.println(jsonPayload);

    if (url.length() >= sizeof(HTTPRequest::url)) {
      Serial.printf("ERROR: URL too long (%d bytes, max %d)\n", url.length(), sizeof(HTTPRequest::url) - 1);
      return false;
    }
    if (jsonPayload.length() >= sizeof(HTTPRequest::payload)) {
      Serial.printf("ERROR: Payload too long (%d bytes, max %d)\n", jsonPayload.length(), sizeof(HTTPRequest::payload) - 1);
      return false;
    }
    
    HTTPRequest request;
    strcpy(request.url, url.c_str());
    strcpy(request.payload, jsonPayload.c_str());
    request.isRegistration = true;
    request.timestamp = millis();
    request.callback = callback;
    request.callbackData = callbackData;
    
    if (xQueueSend(m_httpQueue, &request, pdMS_TO_TICKS(50)) != pdTRUE) {
      Serial.println("Failed to queue registration request - queue full");
      return false;
    }
    return true;
  };

  String GetName() {
    return m_name;
  };
  
  // Check if HTTP queue is empty (for sleep coordination)
  bool IsHttpQueueEmpty() {
    return uxQueueMessagesWaiting(m_httpQueue) == 0;
  };

  int GetNumberRequestsPending() {
    return uxQueueMessagesWaiting(m_httpQueue);
  };

  // HTTP Worker Task - runs in separate thread on Core 0
  static void httpWorkerTask(void* parameter) {
    HTTPRequest request;
    HTTPClient http;

    HttpWorkerParameters *params = (HttpWorkerParameters *)(parameter);
    int httpTimeoutMs = params->httpTimeoutMs;
    int maxAgeMs = params->maxAgeMs;
    QueueHandle_t httpQueue = params->httpQueue;
    delete params;  // Free heap-allocated params now that we've copied the values

    if (httpQueue == NULL) {
      vTaskDelete(NULL);
      return;
    }
    
    while (true) {
      if (xQueueReceive(httpQueue, &request, portMAX_DELAY) == pdTRUE) {
        // Check if request is too old
        unsigned long age = millis() - request.timestamp;
        if (age > (unsigned long)maxAgeMs) {
          Serial.printf("[HTTP Thread] Discarding stale %s request (age: %lu ms)\n",
                        request.isRegistration ? "registration" : "trigger", age);
          // httpCode = 0 signals "discarded before sending" — see HttpResultCallback docs
          if (request.callback != nullptr) {
            request.callback(false, 0, request.callbackData);
          }
          continue;
        }
        
        Serial.printf("[HTTP Thread] Processing %s request to %s (age: %lu ms)\n", 
                      request.isRegistration ? "registration" : "trigger", 
                      request.url, age);
        
        http.begin(request.url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(httpTimeoutMs);
        
        int httpCode = http.POST(request.payload);
        
        bool succeeded = (httpCode == 200 || httpCode == 201);
        if (httpCode > 0) {
          if (succeeded) {
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

        // Invoke callback on Core 0; caller is responsible for any cross-core safety
        if (request.callback != nullptr) {
          request.callback(succeeded, httpCode, request.callbackData);
        }
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
  QueueHandle_t m_httpQueue = NULL;
  TaskHandle_t m_httpTaskHandle = NULL;
  int m_httpTimeout;

  // Gateway state — written on Core 0 (callback), read on Core 1 (Update/sendTriggerEvent).
  // volatile prevents register-caching; hardware guarantees 32-bit access atomicity on Xtensa.
  volatile GatewayStatus m_gatewayStatus = GatewayStatus::DISCONNECTED;
  volatile unsigned long m_lastRegistrationAttemptMs = 0;  // 0 = never attempted

  // Tracks whether the network was up on the previous Update() call.
  // Used to detect the down→up transition and trigger immediate registration.
  // Only accessed from Core 1 (Update); no synchronization needed.
  bool m_networkWasUp = false;

  // Internal registration-result callback used by Update().
  // Runs on Core 0. Only touches the two volatile state fields.
  static void onRegistrationResult(bool succeeded, int httpCode, void* userData) {
    TriggerDevice* self = static_cast<TriggerDevice*>(userData);
    if (succeeded) {
      if (self->m_gatewayStatus != GatewayStatus::CONNECTED) {
        Serial.println("[Gateway] Connected to trigger server");
      }
      self->m_gatewayStatus = GatewayStatus::CONNECTED;
      Serial.println("Registration successful, status CONNECTED");
    } else {
      if (self->m_gatewayStatus != GatewayStatus::DISCONNECTED) {
        Serial.printf("[Gateway] Lost connection to trigger server (httpCode=%d), consider DISCONNECTED\n", httpCode);
      }
      self->m_gatewayStatus = GatewayStatus::DISCONNECTED;
    }
    // Reset the timer from callback time so the next interval is measured from
    // when we got the result, not from when we queued the request.
    self->m_lastRegistrationAttemptMs = millis();
  }

  // sendTriggerEvent: gates on CONNECTED; drops the event if PENDING or DISCONNECTED.
  bool sendTriggerEvent(Trigger& trigger, HttpResultCallback callback = nullptr, void* callbackData = nullptr) {
    if (m_gatewayStatus != GatewayStatus::CONNECTED) {
      Serial.printf("Trigger '%s' dropped - gateway %s\n",
                    trigger.m_name.c_str(),
                    m_gatewayStatus == GatewayStatus::PENDING ? "PENDING" : "DISCONNECTED");
      return false;
    }
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

    String url = String("http://") + m_triggerServerURL + ":" + m_triggerServerPort + "/api/trigger-event";
    
    if (url.length() >= sizeof(HTTPRequest::url)) {
      Serial.printf("ERROR: URL too long (%d bytes, max %d)\n", url.length(), sizeof(HTTPRequest::url) - 1);
      return false;
    }
    if (jsonPayload.length() >= sizeof(HTTPRequest::payload)) {
      Serial.printf("ERROR: Payload too long (%d bytes, max %d)\n", jsonPayload.length(), sizeof(HTTPRequest::payload) - 1);
      return false;
    }
    
    HTTPRequest request;
    strcpy(request.url, url.c_str());
    strcpy(request.payload, jsonPayload.c_str());
    request.isRegistration = false;
    request.timestamp = millis();
    request.callback = callback;
    request.callbackData = callbackData;
    
    if (xQueueSend(m_httpQueue, &request, pdMS_TO_TICKS(50)) != pdTRUE) {
      Serial.println("Failed to queue trigger request - queue full");
      return false;
    }
    
    return true;
  }
};

// Implementations
bool Trigger::SendTriggerEvent(HttpResultCallback callback, void* callbackData) {
  return m_device.sendTriggerEvent(*this, callback, callbackData);
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
  // Use >= so that debounceTimeMs=0 fires on the same call (handles the case where
  // CheckForEventAndSend is called once per hardware-debounced state change rather than
  // every loop iteration).
  if (m_lastReading != m_currentState && millis() >= m_lastChangeTime + m_debounceTimeMs) {
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
