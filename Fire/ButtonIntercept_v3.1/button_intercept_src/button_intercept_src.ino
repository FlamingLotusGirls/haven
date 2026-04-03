#include "button_sequence.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>  // Note that I'm going to have to create the file system on each board
#include <ArduinoJson.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"


// WiFi credentials - read out of little FS
String g_ssid = "not";
String g_password = "set";
String g_netName = "foobar";

AsyncWebServer server(8000);

void initWiFi(const char* ssid, const char* password) {
  WiFi.mode(WIFI_STA);
  Serial.printf("Connecting to wifi, ssid: %s, pwd %s\n", ssid, password);
  WiFi.begin(ssid, password);
  WiFi.setAutoReconnect(true);
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
#define WIFI_PRINT_THRESHOLD 100

// Server setup, mDNS, and trigger registration are all handled by WiFiEvent (event-driven).
// This function just prints a dot periodically while waiting for a connection, so there is
// visible feedback on the serial console without blocking anything.
void wifiLoopCheck() {
  if (WiFi.status() != WL_CONNECTED) {
    if (++numWifiDisconnectedChecks >= WIFI_PRINT_THRESHOLD) {
      Serial.print(WiFi.status());
      Serial.print(".");
      numWifiDisconnectedChecks = 0;
    }
  }
}

// Get wifi username and password out of LittleFS configuration
// file
void retrieveWifiCredentials(String& ssid, String& netPass, String& netName)
{
  // FIRST: Get SSID and password
  if (!LittleFS.exists("/network.json")) {
    Serial.println("network.json not found, using default network credentials");
  } else {
    File file = LittleFS.open("/network.json", "r");
    if (!file) {
      Serial.println("Failed to open network.json, using default network credentials");
    } else {
      // Read file into string
      String jsonString = file.readString();
      Serial.print("Json string is ");
      Serial.println(jsonString);
      file.close();

      // Parse JSON
      DynamicJsonDocument doc(4096);
      DeserializationError error = deserializeJson(doc, jsonString);
      
      if (error) {
        Serial.print("network.json parsing failed: ");
        Serial.println(error.c_str());
      } else {
        if (doc.containsKey("ssid")) {
          ssid = doc["ssid"].as<String>();
        } else {
          Serial.println("Document does not contain ssid!");
        }

        if (doc.containsKey("password")) {
          netPass = doc["password"].as<String>();
        } else {
          Serial.println("Document does not contain password!");
        }
      }
    }
  }
  Serial.printf("Attempting to connect to network %s, pwd %s\n", ssid.c_str(), netPass.c_str());

  // SECOND - Get netname
  File file = LittleFS.open("/netname.txt", "r");
  if (!file){
      Serial.println("Failed to open netname file");
    } else {
      netName = file.readStringUntil('\n');
      file.close();
      Serial.print("mdns name is ");
      Serial.println(netName + ".local");
  }
}

void WiFiEvent(WiFiEvent_t event, WiFiEventInfo_t event_info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.print("IP Address: ");
      Serial.println(WiFi.localIP());

      // MDNS and the web server must only be started once — calling server.begin() or
      // MDNS.begin() on an already-running instance crashes or leaks resources.
      // Use a static flag so subsequent reconnects skip re-init but still re-register.
      {
        static bool s_serverStarted = false;
        if (!s_serverStarted) {
          if (!MDNS.begin(g_netName.c_str())) {
            Serial.println("Error starting mDNS");
          } else {
            Serial.println("mDNS responder started");
          }
          setupWebServer();
          s_serverStarted = true;
        } else {
          Serial.println("WiFi reconnected — web server already running, skipping re-init");
        }
      }

      break;

    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.print("!!! WiFi lost. Reconnecting automatically. Reason: ");
      Serial.println(event_info.wifi_sta_disconnected.reason);

      Serial.printf("  Wifi RSSI %d\n", WiFi.RSSI());

      // ESP32 handles reconnection automatically because WiFi.setAutoReconnect(true) is set.
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

  // Connect to buttons, load button configuration, and then load wifi
  // Note that we're using the netName as the unique identifier for both the mDNS system
  // and the trigger system.
  retrieveWifiCredentials(g_ssid, g_password, g_netName);
  buttonSetup(g_netName);
  initWiFi(g_ssid.c_str(), g_password.c_str());

  Serial.println("Setup running on Core: " + String(xPortGetCoreID()));

  Serial.println("System ready!");
}

void loop() {
  buttonLoop();
  wifiLoopCheck();
  delay(10); // Small delay to prevent watchdog issues
}
