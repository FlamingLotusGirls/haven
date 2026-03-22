#include "button_sequence.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>  // Note that I'm going to have to create the file system on each board
#include <ArduinoJson.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"


// WiFi credentials - read out of little FS
String ssid = "not";
String password = "set";
String netName = "foobar";

AsyncWebServer server(8000);

void initWiFi(const char* ssid, const char* password) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  WiFi.setAutoReconnect(true);
  Serial.println("Connecting to WiFi");
}

void setupLittleFS() {
  if (!LittleFS.begin()) {
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
  }
/*

 else {
    // Wifi connection established. Set up mDNS, setup webserver
    if (!wifiConnected) {
      wifiConnected = true;
      Serial.println();
      Serial.print("Connected to WiFi! IP address: ");
      Serial.println(WiFi.localIP());
      Serial.print("RSSI: ");
      Serial.println(WiFi.RSSI());


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
*/
}

// Get wifi username and password out of LittleFS configuration
// file
void retrieveWifiCredentials(String& ssid, String& netPass, String& netName)
{
  // FIRST: Get SSID and password
  if (!LittleFS.exists("/network.json")) {
    Serial.println("network.json not found, using default network credentials");
  
    File file = LittleFS.open("/network.json", "r");
    if (!file) {
      Serial.println("Failed to open network.json, using default network credentials");
    } else { 
      // Read file into string
      String jsonString = file.readString();
      file.close();

      // Parse JSON
      DynamicJsonDocument doc(4096);
      DeserializationError error = deserializeJson(doc, jsonString);
      
      if (error) {
        Serial.print("network.json parsing failed: ");
        Serial.println(error.c_str());
      } else {
        if (doc.containsKey("ssid")) {
          JsonObject jsonSsid = doc["ssid"];
          serializeJson(jsonSsid, ssid);
        }

        if (doc.containsKey("password")) {
          JsonObject jsonPassword = doc["password"];
          serializeJson(jsonPassword, netPass);
        }
      }
    }
  }

  // SECOND - Get netname
  File file = LittleFS.open("/netname.txt", "r");
  if (!file){
      Serial.println("Failed to open netname file");
    } else {
      netName = file.readStringUntil('\n');  // XXX will this overwrite my string address or change the internal data??
      file.close();
      Serial.printf("mdns name is %s\n", netName + ".local");
  }
}

void WiFiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.print("IP Address: ");
      Serial.println(WiFi.localIP());

      // 1. Restart mDNS
      if (MDNS.begin(netName)) {
          Serial.println("mDNS responder started");
      }

      // 2. Start/Restart Webserver
      setupWebServer();
      Serial.println("HTTP server started");
      break;

    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.println("!!! WiFi lost. Attempting to reconnect...");
      // The ESP32 handles reconnection automatically if WiFi.setAutoReconnect(true) is set
      break;
        
    default: break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("starting...");

  // Mount LittleFS
  setupLittleFS();
  delay(500);

  // Register the Wifi event handler before connecting
  WiFi.onEvent(WiFiEvent);

  // 
  buttonSetup();
  retrieveWifiCredentials(ssid, password, netName);
  initWiFi(ssid.c_str(), password.c_str());

  Serial.println("Setup running on Core: " + String(xPortGetCoreID()));

  Serial.println("System ready!");
}

void loop() {
  buttonLoop();
  wifiLoopCheck();
  delay(10); // Small delay to prevent watchdog issues
}
