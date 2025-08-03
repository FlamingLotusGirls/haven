#include <WiFi.h>
#include <ArduinoJson.h>
#include <WiFiClient.h>

// Copy example_wifi_secrets.h to wifi_secrets.h to define WIFI_SSID and WIFI_PASS.
#include "wifi_secrets.h"

IPAddress MY_IP(192, 168, 7, 198);
IPAddress SERVER_IP(192, 168, 7, 207);
unsigned int SERVER_PORT = 5204;
IPAddress GATEWAY(192, 168, 1, 1);
IPAddress SUBNET(255, 255, 255, 0);

const int BUTTON_PIN = 23;
const int INDICATOR_LED_PIN = 2;

enum WifiState
{
  WifiState_TRY_WIFI,
  WifiState_CONNECTED
};
WifiState wifiState = WifiState_TRY_WIFI;
int wifiLoopCounter = 0;
void beginWifi()
{
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  WiFi.useStaticBuffers(true);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
  WiFi.setMinSecurity(WIFI_AUTH_WEP);
  WiFi.config(MY_IP, GATEWAY, SUBNET);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}
void tryWifiLoop()
{
  if (WiFi.status() == WL_CONNECTED)
  {
    if (wifiState == WifiState_TRY_WIFI)
    {
      // Just connected successfully
      wifiState = WifiState_CONNECTED;
      Serial.println("");
      Serial.print("Connected to \"");
      Serial.print(WIFI_SSID);
      Serial.println("\"");
      Serial.print("IP address: ");
      Serial.println(WiFi.localIP());
      Serial.print("RSSI Strength: ");
      Serial.println(WiFi.RSSI());
    }
  } else {
    if (wifiState == WifiState_TRY_WIFI)
    {
      Serial.print("Wifi Status: ");
      switch (WiFi.status())
      {
      case WL_NO_SHIELD:
        Serial.println("WL_NO_SHIELD");
        break;
      case WL_IDLE_STATUS:
        Serial.println("WL_IDLE_STATUS");
        break;
      case WL_NO_SSID_AVAIL:
        Serial.println("WL_NO_SSID_AVAIL");
        break;
      case WL_SCAN_COMPLETED:
        Serial.println("WL_SCAN_COMPLETED");
        break;
      case WL_CONNECTED:
        Serial.println("WL_CONNECTED");
        break;
      case WL_CONNECT_FAILED:
        Serial.println("WL_CONNECT_FAILED");
        break;
      case WL_CONNECTION_LOST:
        Serial.println("WL_CONNECTION_LOST");
        break;
      case WL_DISCONNECTED:
        Serial.println("WL_DISCONNECTED");
        break;
      }
      beginWifi();
      delay(1000);
    } else {
      Serial.println("Lost wifi connection, reconnecting.");
      wifiState = WifiState_TRY_WIFI;
      beginWifi();
      delay(1000);
    }
  }
}

int buttonStatus = 0;

WiFiClient tcpClient;

void connectToTcpServer() {
  Serial.println("Connecting to TCP server...");
  if (tcpClient.connect(SERVER_IP, SERVER_PORT)) {
    Serial.println("Connected to TCP server");
  } else {
    Serial.println("TCP connection failed");
  }
}

void sendButtonStatus() {
  StaticJsonDocument<100> jsonDoc;
  jsonDoc["method"] = "inputEvent";
  JsonObject params = jsonDoc.createNestedObject("params");
  params["buttonStatus"] = buttonStatus;
  String jsonString;
  serializeJson(jsonDoc, jsonString);
  tcpClient.println(jsonString);
  Serial.print("Sent JSON: ");
  Serial.println(jsonString);
}

void setup()
{
  // Serial.begin(9600);
  pinMode(INDICATOR_LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT);
  buttonStatus = digitalRead(BUTTON_PIN);
}

void loop()
{
  tryWifiLoop();

  if (!tcpClient.connected()) {
    connectToTcpServer();
    delay(1000);
  }

  int oldButtonStatus = buttonStatus;
  buttonStatus = digitalRead(BUTTON_PIN);
  if (buttonStatus == HIGH)
  {
    if (oldButtonStatus == LOW) {
      sendButtonStatus();
    }
    digitalWrite(INDICATOR_LED_PIN, HIGH);
  }
  else
  {
    if (oldButtonStatus == HIGH) {
      sendButtonStatus();
    }
    digitalWrite(INDICATOR_LED_PIN, LOW);
  }

  delay(1);
}