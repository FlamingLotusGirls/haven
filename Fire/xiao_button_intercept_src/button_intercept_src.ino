#include "button_sequence.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>  // Note that I'm going to have to create the file system on each board
#include <ArduinoJson.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"


// WiFi credentials - modify as needed
const char* ssid = "sisyphus";
const char* password = "!medea4u";

AsyncWebServer server(8000);

void initWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.println("Connecting to WiFi");
}

void setupLittleFS() {
  if (!LittleFS.begin(true)) {
    Serial.println("An error occurred while mounting LittleFS");
    return;
  }
  Serial.println("LittleFS mounted successfully");
}

void setupWebServer() {
  // Serve static files
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    Serial.println("Webserver running on Core: " + String(xPortGetCoreID()));
    request->send(LittleFS, "/index.html", "text/html");
  });

  server.on("/app.js", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(LittleFS, "/app.js", "application/javascript");
  });

  // API endpoints
  server.on("/api/channels", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(LittleFS, "/channels.json", "application/json");
  });

  server.on("/api/channels", HTTP_POST, [](AsyncWebServerRequest *request){}, NULL,
    [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
      // Save channels data
      File file = LittleFS.open("/channels.json", "w");
      if (file) {
        file.write(data, len);
        file.close();
        request->send(200, "application/json", "{\"status\":\"success\"}");
      } else {
        request->send(500, "application/json", "{\"error\":\"Failed to save channels\"}");
      }
    });

  server.on("/api/patterns", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(LittleFS, "/patterns.json", "application/json");
  });

  server.on("/api/patterns", HTTP_POST, [](AsyncWebServerRequest *request){}, NULL,
    [](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
      // Save patterns data
      File file = LittleFS.open("/patterns.json", "w");
      if (file) {
        file.write(data, len);
        file.close();
        // Reload patterns into the button system
        loadPatternsFromFile();
        request->send(200, "application/json", "{\"status\":\"success\"}");
      } else {
        request->send(500, "application/json", "{\"error\":\"Failed to save patterns\"}");
      }
    });

  server.begin();
  Serial.println("HTTP server started on port 8000");
}

int numWifiDisconnectedChecks = 0;
bool wifiConnected = false;
#define WIFI_PRINT_THRESHOLD 20
void wifiLoopCheck() {
  int wifiStatus = WiFi.status();
  if (wifiStatus != WL_CONNECTED) {
    numWifiDisconnectedChecks++;
    if (numWifiDisconnectedChecks >= WIFI_PRINT_THRESHOLD) {
      Serial.print(wifiStatus);
      Serial.print(".");
      numWifiDisconnectedChecks = 0;
    }
    // If Wifi *was* connected, but now disconnects, print.
    // XXX I'm assuming that we'll try to reconnect automatically.
    if (wifiConnected) {
        Serial.println("Wifi disconnect!!");
        wifiConnected = false;
      }
  } else {
    // Wifi connection established (or re-established).
    if (!wifiConnected) {
      wifiConnected = true;
      Serial.println();
      Serial.print("Connected to WiFi! IP address: ");
      Serial.println(WiFi.localIP());
      Serial.print("RSSI: ");
      Serial.println(WiFi.RSSI());

      // MDNS and the web server must only be started once — calling server.begin() or
      // MDNS.begin() on an already-running instance crashes or leaks resources.
      static bool s_serverStarted = false;
      if (!s_serverStarted) {
        File file = LittleFS.open("/netname.txt", "r");
        if (!file) {
          Serial.println("Failed to open netname file");
        } else {
          String netName = file.readStringUntil('\n');
          file.close();
          Serial.print("mdns name is ");
          Serial.print(netName);
          Serial.println(".local");
          if (!MDNS.begin(netName.c_str())) {
            Serial.println("Error starting mDNS");
          } else {
            Serial.println("mDNS responder started");
          }
        }
        setupWebServer();
        s_serverStarted = true;
      } else {
        Serial.println("WiFi reconnected — web server already running, skipping re-init");
      }

      // Always re-register the trigger device on (re)connect so the server gets
      // the current IP address.
      extern TriggerDevice* triggerDevice;
      if (triggerDevice != nullptr) {
        triggerDevice->RegisterDevice();
        Serial.println("Trigger device re-registered after WiFi reconnect");
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("starting...");
  delay(1000);
  setupLittleFS();
  buttonSetup();
  initWiFi();

  Serial.println("Setup running on Core: " + String(xPortGetCoreID()));

  Serial.println("System ready!");
}

void loop() {
  buttonLoop();
  wifiLoopCheck();
  delay(10); // Small delay to prevent watchdog issues
}
