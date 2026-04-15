
#include "lantern_webserver.h"

#include <WebServer.h>
#include <Preferences.h>
#include "webpage.h"

// External references to LED control variables
extern uint8_t colorA_hue;
extern uint8_t colorA_sat;
extern uint8_t colorA_val;
extern uint8_t colorB_hue;
extern uint8_t colorB_sat;
extern uint8_t colorB_val;
extern unsigned long transitionTime;

// External reference to Preferences object
extern Preferences preferences;

// Web server on port 80
WebServer server(80);

// REST API handler: Serve the main HTML page
void handleRoot() {
  server.send(200, "text/html", htmlPage);
}

// REST API handler: Set Color A
void handleSetColorA() {
  if (server.hasArg("h") && server.hasArg("s") && server.hasArg("v")) {
    colorA_hue = constrain(server.arg("h").toInt(), 0, 255);
    colorA_sat = constrain(server.arg("s").toInt(), 0, 255);
    colorA_val = constrain(server.arg("v").toInt(), 0, 255);
    
    // Save to NVS
    preferences.begin("lantern", false);
    preferences.putUChar("colorA_hue", colorA_hue);
    preferences.putUChar("colorA_sat", colorA_sat);
    preferences.putUChar("colorA_val", colorA_val);
    preferences.end();
    
    server.send(200, "application/json", 
      "{\"status\":\"success\",\"message\":\"Color A updated\"}");
    
    Serial.printf("Color A set to H:%d S:%d V:%d (saved to NVS)\n", colorA_hue, colorA_sat, colorA_val);
  } else {
    server.send(400, "application/json", 
      "{\"status\":\"error\",\"message\":\"Missing parameters\"}");
  }
}

// REST API handler: Set Color B
void handleSetColorB() {
  if (server.hasArg("h") && server.hasArg("s") && server.hasArg("v")) {
    colorB_hue = constrain(server.arg("h").toInt(), 0, 255);
    colorB_sat = constrain(server.arg("s").toInt(), 0, 255);
    colorB_val = constrain(server.arg("v").toInt(), 0, 255);
    
    // Save to NVS
    preferences.begin("lantern", false);
    preferences.putUChar("colorB_hue", colorB_hue);
    preferences.putUChar("colorB_sat", colorB_sat);
    preferences.putUChar("colorB_val", colorB_val);
    preferences.end();
    
    server.send(200, "application/json", 
      "{\"status\":\"success\",\"message\":\"Color B updated\"}");
    
    Serial.printf("Color B set to H:%d S:%d V:%d (saved to NVS)\n", colorB_hue, colorB_sat, colorB_val);
  } else {
    server.send(400, "application/json", 
      "{\"status\":\"error\",\"message\":\"Missing parameters\"}");
  }
}

// REST API handler: Set Transition Time
void handleSetTransition() {
  if (server.hasArg("time")) {
    transitionTime = constrain(server.arg("time").toInt(), 100, 300000);
    
    // Save to NVS
    preferences.begin("lantern", false);
    preferences.putULong("transTime", transitionTime);
    preferences.end();
    
    server.send(200, "application/json", 
      "{\"status\":\"success\",\"message\":\"Transition time updated\"}");
    
    Serial.printf("Transition time set to %lu ms (saved to NVS)\n", transitionTime);
  } else {
    server.send(400, "application/json", 
      "{\"status\":\"error\",\"message\":\"Missing time parameter\"}");
  }
}

// REST API handler: Get current status
void handleStatus() {
  String json = "{";
  json += "\"colorA\":{\"h\":" + String(colorA_hue) + ",\"s\":" + String(colorA_sat) + ",\"v\":" + String(colorA_val) + "},";
  json += "\"colorB\":{\"h\":" + String(colorB_hue) + ",\"s\":" + String(colorB_sat) + ",\"v\":" + String(colorB_val) + "},";
  json += "\"transitionTime\":" + String(transitionTime);
  json += "}";
  
  server.send(200, "application/json", json);
}

// Initialize web server routes
void setupWebServer() {
  server.on("/", handleRoot);
  server.on("/api/colorA", HTTP_POST, handleSetColorA);
  server.on("/api/colorB", HTTP_POST, handleSetColorB);
  server.on("/api/transition", HTTP_POST, handleSetTransition);
  server.on("/api/status", HTTP_GET, handleStatus);
  
  server.begin();
  Serial.println("Web server started");
}

// Handle incoming web requests (call this in loop)
void handleWebServer() {
  server.handleClient();
}
