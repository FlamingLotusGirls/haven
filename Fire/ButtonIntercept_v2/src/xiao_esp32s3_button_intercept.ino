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
    // Wifi connection established. Set up mDNS, setup webserver
    if (!wifiConnected) {
      wifiConnected = true;
      Serial.println();
      Serial.print("Connected to WiFi! IP address: ");
      Serial.println(WiFi.localIP());

      File file = LittleFS.open("/netname.txt", "r");
      if (!file){
        Serial.println("Failed to open netname file");
      } else {
        String netName = file.readStringUntil('\n');
        Serial.print("mdns name is ");
        Serial.print(netName);
        Serial.print(".local");
        if (!MDNS.begin(netName.c_str())) { // Set the hostname
          Serial.println("Error starting mDNS");
        } else {
          Serial.println("mDNS responder started");
        }
      }
      setupWebServer();
    }
  }
}

void setup() {
  Serial.begin(115200);  
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
