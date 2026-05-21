#pragma once
#include <Arduino.h>
#define TRIGGER_OVER_WIFI
#ifdef TRIGGER_OVER_WIFI
#include <HWCDC.h>
#include <WiFi.h>
#else
#include <ETH.h>
#endif 
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <vector>
#include <memory>

// ── Forward declaration ───────────────────────────────────────────────────
class TriggerDevice;

// ── Trigger (abstract base) ───────────────────────────────────────────────
class Trigger {
public:
  String GetName() { return m_name; }
  bool   SendTriggerEvent();
  virtual ~Trigger() {}

  friend class TriggerDevice;

protected:
  Trigger(TriggerDevice& device, String name) : m_device(device), m_name(name) {}

  virtual void   addTriggerRegistrationJson(JsonObject& parent) = 0;
  virtual String getCurrentValueAsString() = 0;

  TriggerDevice& m_device;
  String         m_name;
  int32_t        m_currentMsgId = 0;
};

// ── ButtonTrigger ─────────────────────────────────────────────────────────
class ButtonTrigger : public Trigger {
public:
  bool CheckForEventAndSend(bool onOff);
  bool GetCurrentValue() { return m_currentState; }
  virtual ~ButtonTrigger() {}

  friend class TriggerDevice;

protected:
  ButtonTrigger(TriggerDevice& device, String name, bool initialValue, int debounceTimeMs = 50);
  virtual void   addTriggerRegistrationJson(JsonObject& baseObject);
  virtual String getCurrentValueAsString();

  bool m_currentState;
  bool m_lastReading;
  int  m_debounceTimeMs;
  int  m_lastChangeTime;
};

// ── OneShotTrigger ────────────────────────────────────────────────────────
class OneShotTrigger : public Trigger {
public:
  virtual ~OneShotTrigger() {}
  friend class TriggerDevice;

protected:
  OneShotTrigger(TriggerDevice& device, String name);
  virtual void   addTriggerRegistrationJson(JsonObject& baseObject);
  virtual String getCurrentValueAsString();
};

// ── DiscreteTrigger ───────────────────────────────────────────────────────
class DiscreteTrigger : public Trigger {
public:
  bool CheckForEventAndSend(int value);
  virtual ~DiscreteTrigger() {}
  friend class TriggerDevice;

protected:
  DiscreteTrigger(TriggerDevice& device, String name, std::vector<int> range, int initialValue, int debounceTimeMs = 50);
  virtual void   addTriggerRegistrationJson(JsonObject& baseObject);
  virtual String getCurrentValueAsString();

  int              m_currentState;
  std::vector<int> m_values;
  int              m_debounceTimeMs;
  int              m_lastReading;
  int              m_lastChangeTime;
};

// ── ContinuousTrigger ─────────────────────────────────────────────────────
class ContinuousTrigger : public Trigger {
public:
  bool CheckForEventAndSend(float value);
  virtual ~ContinuousTrigger() {}
  friend class TriggerDevice;

protected:
  ContinuousTrigger(TriggerDevice& device, String name, float maxVal, float minVal, float initialValue, float marginPercent = 5);
  virtual void   addTriggerRegistrationJson(JsonObject& baseObject);
  virtual String getCurrentValueAsString();

  float m_currentState;
  float m_maxVal;
  float m_minVal;
  float m_margin;
};

// ── TriggerDevice ─────────────────────────────────────────────────────────
class TriggerDevice {
public:
  TriggerDevice(String name, String triggerServerURL, int16_t triggerServerPort,
                int16_t listenerPort = 5000, bool useWifi = true, int httpTimeout = 5000);
  ~TriggerDevice();

  // Factory methods – inline because they are trivial wrappers
  std::shared_ptr<ButtonTrigger> AddButtonTrigger(String name, bool initialValue, int debounceTimeMs = 50) {
    auto t = std::shared_ptr<ButtonTrigger>(new ButtonTrigger(*this, name, initialValue, debounceTimeMs));
    m_triggers.push_back(t);
    return t;
  }
  std::shared_ptr<DiscreteTrigger> AddDiscreteTrigger(String name, std::vector<int> range, int initialValue, int debounceTimeMs = 50) {
    auto t = std::shared_ptr<DiscreteTrigger>(new DiscreteTrigger(*this, name, range, initialValue, debounceTimeMs));
    m_triggers.push_back(t);
    return t;
  }
  std::shared_ptr<ContinuousTrigger> AddContinuousTrigger(String name, float maxVal, float minVal, float initialVal, float marginPercent = 5) {
    auto t = std::shared_ptr<ContinuousTrigger>(new ContinuousTrigger(*this, name, maxVal, minVal, initialVal, marginPercent));
    m_triggers.push_back(t);
    return t;
  }
  std::shared_ptr<OneShotTrigger> AddOneShotTrigger(String name) {
    auto t = std::shared_ptr<OneShotTrigger>(new OneShotTrigger(*this, name));
    m_triggers.push_back(t);
    return t;
  }

  void   RegisterDevice();
  String GetName()                 { return m_name; }
  bool   IsHttpQueueEmpty()        { return uxQueueMessagesWaiting(m_httpQueue) == 0; }
  int    GetNumberRequestsPending(){ return uxQueueMessagesWaiting(m_httpQueue); }

  // HTTP worker task (static so it can be passed to xTaskCreate)
  static void httpWorkerTask(void* parameter);

  friend class Trigger;
  friend class ButtonTrigger;
  friend class OneShotTrigger;
  friend class ContinuousTrigger;
  friend class DiscreteTrigger;

private:
  struct HttpWorkerParameters {
    int          httpTimeoutMs;
    int          maxAgeMs;
    QueueHandle_t httpQueue;
  };

  bool sendTriggerEvent(Trigger& trigger);

  String   m_name;
  String   m_triggerServerURL;
  int16_t  m_triggerServerPort;
  int16_t  m_listenerPort;
  bool     m_usesWifi;
  int      m_httpTimeout;

  std::vector<std::shared_ptr<Trigger>> m_triggers;
  QueueHandle_t m_httpQueue     = NULL;
  TaskHandle_t  m_httpTaskHandle = NULL;
};
