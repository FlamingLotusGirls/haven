#ifndef LANTERN_WEBSERVER_H
#define LANTERN_WEBSERVER_H

// REST API handler: Serve the main HTML page
void handleRoot();
// REST API handler: Set Color A
void handleSetColorA();
// REST API handler: Set Color B
void handleSetColorB();
// REST API handler: Set Transition Time
void handleSetTransition();
// REST API handler: Get current status
void handleStatus();

// Initialize web server routes
void setupWebServer();

// Handle incoming web requests (call this in loop)
void handleWebServer();
#endif // LANTERN_WEBSERVER_H
