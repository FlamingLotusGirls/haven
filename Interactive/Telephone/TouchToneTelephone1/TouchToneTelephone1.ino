/*
 * TouchToneTelephone1.ino
 *
 * Top-level sketch: setup() and loop() only.
 * All logic lives in the module files alongside this sketch.
 *
 * Hardware:
 *   - XIAO ESP32S3 (Dual Core, 8 MB Flash, 8 MB PSRAM)
 *   - MCP23008-E/P IO Expander (I2C address 0x20)
 *   - L298N H-Bridge for 20 Hz AC ring generation
 *   - MAX98357A I2S Audio Amplifier
 *
 * Module layout:
 *   shared_state.h/cpp  – mutex-protected state shared between HTTP task and loop
 *   config.h/cpp        – loads config.json / triggers.json, WiFi connection
 *   io_expander.h/cpp   – MCP23008 I2C driver, hook-switch, key scanning
 *   audio.h/cpp         – I2S / DTMF tone generation
 *   ringer.h/cpp        – H-bridge ring cadence driver
 *   http_server.h/cpp   – WebServer + FreeRTOS task on Core 0
 *   triggers.h/cpp      – phone-number → trigger mappings
 *   state_machine.h/cpp – telephone state machine (in progress)
 */

#include <WiFi.h>
#include <SD.h>
#include <SPI.h>

#include "shared_state.h"
#include "config.h"
#include "io_expander.h"
#include "audio.h"
#include "ringer.h"
#include "http_server.h"
#include "triggers.h"
#include "state_machine.h"
#include "DeviceTriggers.h"

// ── SD card pins (XIAO ESP32S3, hardware SPI) ────────────────────────────
#define SD_CS_PIN   GPIO_NUM_44
#define SD_MOSI_PIN GPIO_NUM_9
#define SD_MISO_PIN GPIO_NUM_8
#define SD_SCK_PIN  GPIO_NUM_7

// ── Dialing ─────────────────────────────────────────────────────────────
const unsigned long DIAL_TIMEOUT = 5000;  // ms idle before clearing number

// The TelephoneState shows the physical state of the telephone.
// This is related to, but not necessarily exactly the same as,
// the CallState. TelephoneState drives CallState
class TelephoneState {
  bool buttonState[TelephoneButtons::TOTAL]; // State of the keypad buttons
  bool offHook;                              // On or off hook?
  bool isRinging;                            // Ringing or not ringing?  Enabled by RemoteConnection module
  bool incomingCall;                         // Is there an incoming call pending? Enabled by RemoteConnection module
  bool outgoingCall;                         // Is there an outgoing call pending? Enabled by RemoteConnection module
  bool connected;                            // Are we connected to a call? Enabled by either LocalConnection module or RemoteConnection module
  unsigned char dialSequence[16];            // number being dialed. We check to see if the number triggers a local or remote connection
};

// Things that drive telephone state:
// - Button state: Check GPIO
// - Connection state: Check connection module. Runs in a different thread? How does it work.
// - Ringer state: Check ringer module. Ringer module - responsible for ringing bell. Synchronous. Nothing else should be going on.
// - Hook state: Check GPIO

// Let's walk through the connection state. That's really the most complicated bit.
// XXX - what about VAD? how do I get that in? Look at Shawn's code.
// A connection can be local or remote. 
// A local connection has a series of callbacks on it. It can play sounds, listen for sounds, respond to keypresses.
// A remote connection has a socket to the remote telephone. It can listen for sounds, play sounds, and send and receive on the socket.
// So. Connection module (socket) listens for incoming connection. Sets flag (need mutex?) if one is found. (is reading the flag atomic?)
// If we're making an outgoing (non-local) connection, we flag the connection module, which then sets a flag for the outgoing connection
// And it will set the isringing flag as well.
// Okay. So a lot of the complexity here comes from the remote connection and he incoming/outgoing/isRinging logic, and the communication
// between the threads. (?? Do I need to make it multithreaded? Just check the socket in the loop. There are so many http connections
// going on... )

// The CallState describes what the phone should be *doing*. It
// depends on the TelephoneState, which describes the underlying *physical* state of the phone.
enum class CallState {
  INACTIVE,  // do nothing (transitions: from any state when hook is placed)
  DIAL_TONE, // play dial tone (transitions: From inactive when hook is taken. 
             //                              From INCOMING in corner case - incoming is cancelled as user picks up. Or timeout
             //                              From CONNECTED if call drops
             //                              From CONNECTION_ROUTING if timeout
  DIALING,   // in the middle of dialing, play button tones. (transitions: from DIAL_TONE)
  INCOMING,  // ring bell (transition: from INACTIVE)
  CONNECTION_ROUTING, // Have dialed. Trying to figure out what to do with the connection (transition: From DIALING)
  AWAITING_CONNECTION,   // Play simulated ringing in headset (transition: from CONNECTION_ROUTING)
  CONNECTED, // Do whatever connection things, play button tones (transition: from AWAITING CONNECTION, if outgoing. From INCOMING, for incoming call)
  BUSY,      // Play busy signal. (transition: From CONNECTION_ROUTING if the callee phone is unavailable)
  OFF_HOOK_TIMEOUT1,  // 'If you'd like to make a call' (transition: From DIALING, from BUSY on timeout)
  OFF_HOOK_TIMEOUT2   // beep beep beep beep beep (transition: from OFF_HOOK_TIMEOUT1)
  OFF_HOOK   // Do nothing. Been off hook for too long. (transition: from OFF_HOOK_TIMEOUT2)
};

// Other state variables
static unsigned long lastDigitTime = 0;
static TriggerDevice*   gTriggerDevice = nullptr;
static TelephoneConfig* gConfig = nullptr;
static TelephoneState   gTelephoneState;
static unsigned long    gInactivityTimeout = 0;  // timeout, used for various off-hook situations
static constexpr OFF_HOOK_INACTIVITY_TIMEOUT = 10000; // 10 seconds

// ═════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n=== Touch-Tone Telephone Trigger Device ===");

  // Initialize physical representation of state of telephone
  initTelephoneState(gTelephoneState);

  // initSharedState(); // XXX - do I actually want this shared state thing? All it does is create a state mutex, which is used for the ringer and the udpPort. 

  // IO expander (I2C + MCP23008)
  initIOExpander();

  // H-bridge ringer
  initRinger();

  // SD card (standard 4-wire SPI)
  Serial.println("\n--- Initializing SD Card ---");
  SPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);
  if (SD.begin(SD_CS_PIN)) {
    Serial.printf("SD card OK  (%llu MB)\n", SD.cardSize() / (1024 * 1024));
  } else {
    Serial.println("WARNING: SD card not found – continuing without it");
  }

  // I2S audio (MAX98357A)
  Serial.println("\n--- Initializing I2S Audio ---");
  initI2S();
  delay(100);   // let I2S stabilise  XXX probably don't need this?

  // Configuration (WiFi credentials + trigger server info)
  if ((gConfig = loadConfig()) == nullptr) {
    Serial.println("ERROR: Failed to load configuration");
    while (1) delay(1000);
  }

  // WiFi. The timeout is very long, and is not appropriate for wifi disconnects.
  // XXX how to handle this? Other core it?
  connectToWiFi();

  // Create trigger device and register hardcoded phone-number mappings
  // XXX - the various local connections should register triggers. Should be InitConnections rather than InitTriggers
  gTriggerDevice = new TriggerDevice(config->device_name,
                                    config->trigger_server,
                                    config->trigger_port);
  initTriggers(gTriggerDevice);

  // Triggers
  registerTriggers();

  Serial.println("\nSetup complete. Ready.\n");
}


void copyTelephoneState(TelephoneState& telephoneState, TelephoneState* copyBuffer) {
  if (copyBuffer) {
    memcpy(copyBuffer, &telephoneState, sizeof(TelephoneState));
  }
}

void initTelephoneState(TelephoneState& telephoneState) {
  memset(telephoneState, 0, sizeof(telephoneState));
  for (int i=0; i<TelephoneButtons::TOTAL; i++) {
    telephoneState.buttons[i] = false;
  }
}


// ── Periodic re-registration ─────────────────────────────────────────────
static constexpr REGISTRATION_INTERVAL = 120000; // 2 minute registration interval
static unsigned long gLastTriggerRegistrationTime = 0;

void connectToWiFi() {
  Serial.println("\n--- WiFi Connection ---");
  Serial.printf("Connecting to %s ...\n", config.wifi_ssid);

  WiFi.begin(config.wifi_ssid, config.wifi_pass);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed to connect to WiFi");
  }
}

void wifiUpdate(unsigned long currentTime) {
  // ── WiFi watchdog ────────────────────────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected – reconnecting...");
    connectToWiFi();
  } // XXX - need to make this non-blocking

  // ── Periodic trigger-server re-registration ──────────────────────────
  if (WiFi.status() == WL_CONNECTED) {
    if (gTriggerDevice && (currentTime - gLastTriggerRegistrationTime >= REGISTRATION_INTERVAL)) {
      gTriggerDevice->RegisterDevice();
      gLastTriggerRegistrationTime = currentTime;
    }
  }
}

void registerTriggers() {
  if (WiFi.status() == WL_CONNECTED) {
    gTriggerDevice->RegisterDevice();
    lastRegistrationTime = millis();
    startHttpServer();   // spawns Core-0 task  // XXX what happens if wifi goes away?
  } else {
    Serial.println("WARNING: No WiFi – HTTP server not started");
  }
}

// ═════════════════════════════════════════════════════════════════════════

CallState oldCallState = NO_CALL;
// why don't I just do a buffer swap rather than a copy?
void getTelephoneState(TelephoneState* telephoneStateOut) {
  // read buttons
  // read hook
  // Check flag for whether ringer is ringing
  // Check for whether there is an incoming call pending (flag from another thread)
  // Check for whether we're connected
  // Check for whether there's an outgoing call
  // Check for whether we're in the middle of dialing
}

// Determine new CallState based on current CallState and TelephoneState
// The *only* responsibilty of this function is to determine the CallState.
// It sets no state variables and has no side effects.
CallState runStateMachine(TelephoneState& telephoneState, CallState currentCallState) {
  CallState newCallState = currentCallState;
  switch (currentCallState) {
  case CallState::INACTIVE:
    if (telephoneState.incomingCall) {
      newCallState = CallState::INCOMING;
    } else if (telephoneState.offHook) { 
      newCallState = CallState::DIAL_TONE;
    }
  break;
  case CallState::DIAL_TONE:
    if (!telephoneState.offHook) {
      // User hung up. change state to INACTIVE
      newCallState = CallState::INACTIVE;
    } else if (buttonsPressed(telephoneState)) {
      newCallState = CallState::DIALING;
    } else if (currentTime > gInactivityTimeout) {
      newCallState = CallState::OFF_HOOK_TIMEOUT_1;
    }
  break;
  case CallState::DIALING:
    if (!telephoneState.offHook) {
      newCallState = CallState::INACTIVE;
    } else if (telephoneState.outgoingCall) {
      newCallState = CallState::CONNECTION_ROUTING;
    } else if (buttonsPressed(telephoneState)) {
    } else if (currentTime > gInactivityTimeout) {
      newCallState = CallState::OFF_HOOK_TIMEOUT_1;
    }
  break;
  case CallState::INCOMING:
    if (!telephoneState.incomingCall) {
      if (telephoneState.offHook) {
        newCallState = CallState::DIAL_TONE;
      } else {
        newCallState = CallState::INACTIVE;
      }
    } else if (telephoneState.offHook) {
      newCallState = CallState::CONNECTED.
      // XXX TODO Connect to other side.
    }
  break;
  case CallState::CONNECTION_ROUTING:
    // XXX - check connection status. Should be busy, available, connected, or unknown
    ConnectionStatus connectionStatus = GetConnectionStatus();
    if (connectionStatus == ConnectionStatus::BUSY) {
      newCallState = CallState::Busy;
    } else if (connectionStatus == ConnectionStatus::AVAILABLE) {
      newCallState = CallState::AWAITING_CONNECTION;
    } else if (connectionStatus == ConnectionStatus::CONNECTED) {
      newCallState = CallState::CONNECTED;
    } else if (currentTime > gInactivityTimeout) {
      newCallState = OFF_HOOK_TIMEOUT1;
    } else {
     // do nothing. Still trying to figure out how to handle this connection request
    }
  break;
  case CallState::AWAITING_CONNECTION:
    if (telephoneState.connected) {
      newCallState = CallState::CONNECTED; 
    } else if (!telephoneState.offHook) {
      // Change state to INACTIVE
      newCallState = CallState::INACTIVE;
    } else if (!telephoneState.outGoingCall) {
      newCallState = CallState::DIAL_TONE;
    } else if (currentTime > gInactivityTimeout) {
      newCallState = CallState::OFF_HOOK_TIMEOUT1;
    }
    break;
  case CallState::CONNECTED:
    if (!telephoneState.offHook) {
      newCallState = CallState::INACTIVE;
    } else if (!telephoneState.connected) {
      newCallState = CallState::DIAL_TONE;
    }
    break;
  case CallState::BUSY:
    if (!telephoneState.offHook) {
      newCallState = CallState::INACTIVE;
    } else if (currentTime > gInactivityTimeout) {
      newCallState = OFF_HOOK_TIMEOUT_1;
    }
    break;
  case CallState::OFF_HOOK_TIMEOUT_1:
    if (!telephoneState.offHook) {
      newCallState = CallState::INACTIVE;
    } else if (currentTime > gInactivityTimeout) {
      newCallState = OFF_HOOK_TIMEOUT2;
    }
    break;
  case CallState::OFF_HOOK_TIMEOUT_2:
    if (!telephoneState.offHook) {
      newCallState = CallState::INACTIVE;
    } else if (currentTime > gInactivityTimeout) {
      newCallState = CallState::OFF_HOOK;
    }
    break;
  case CallState::OFF_HOOK:  // NB - this is off hook, timed out.
    if (!telephoneState.offHook) {
      newCallState = CallState::INACTIVE;
    }
    break;
    default:
    break;
  }
 return newCallState;
}

TelephoneState gTelephoneState;  // XXX need to initialize
CallState gCallState = CallState::INACTIVE;

// I need a pointer to a callback function for the connection
// A connection gets defined as
// A callback for cancel
// A callback for loop
// A callback for setup
// A callback for current status.
// And the connection can do whatever the fuck it wants

void IncomingCallTerminate() {
  if (gTelephoneState.incomingCall) {
    // XXX TODO send message back to caller terminating the call
    // This means I need the address of the caller
    gTelephoneState.incomingCall = false;
    Serial.println("CONNECTION: Terminating incoming call");
  }
}

void OutgoingCallTerminate() {
  if (gTelephoneState.outgoingCall) {
    // XXX TODO send message back to recipient terminating the call
    // XXX this means I need the address of the recipient
    gTelephoneState.outgoingCall = false;
    Serial.println("CONNECTION: Terminating out going call");
  }
}

void ConnectionCancel() {
  if (gTelephoneState.connected) {
    Serial.println("CONNECTION: Notifying current connection of cancelation");
    // connectionCancelCallback(gTelephoneState, gCallState);
    gTelephoneState.connected = false;
  }
}

void StopSound() {
  Serial.println("SOUND: Stopping all sounds");
}

void RingerStop() {
  if (gTelephoneState.isRinging) {
    Serial.println("RINGER: Stopping ringer");
    gTelephoneState.isRinging = false;
  }
}

void PlayDialTone() {
  Serial.println("SOUND: Starting Dial Tone");
}

void PlayBusySignal() {
  Serial.println("SOUND: Playing Busy Signal");
}

void PlayRinging() {
  Serial.println("SOUND: Playing simulated Ringing");
}

void PlayIfYoudLikeToMakeACall() {
  Serial.println("SOUND: Playing if you'd like to make a call...");
}

void PlayBeepBeepBeep() {
  Serial.println("SOUND: Playing Beep beep beep");
}

void CancelConnections(TelephoneState& telephoneState) {
  // stop any incoming call
  if (telephoneState.incomingCall) {
   IncomingCallTerminate();
  }
  // stop any outgoing call
  if (telephoneState.outgoingCall) {
    OutgoingCallTerminate();
  }
  // cancel any open connections
  if (telephoneState.connected) {
    ConnectionCancel();
  }
  // XXX TODO - also stop any ringing!
}


// This function is responsible for changing internal state variables in response to a
// desired change in the CallState. 
void changeState(CallState newCallState, CallState oldCallState, TelephoneState& telephoneState, unsigned long currentTime) {
  if (newCallState != oldCallState) {
    gInactivityTimeout = currentTime + OFF_HOOK_INACTIVITY_TIMEOUT;
    switch (newCallState) {
    case CallState::INACTIVE:
      // stop sound
      SoundStop();
      // cancel any pending or active connections
      CancelConnections();
      // stop any ringing
      if (telephoneState.isRinging) {
         RingerStop();
      }
      break;
    case CallState::DIALING:
      // stop previous sound
      SoundStop();
      // Cancel any pending or active connections
      CancelConnections();
      // Play DTMF sound (there *should* be a button down. Just play the sound for the first one we find)
      // XXX need to initiaize the dial sequence. Here's where we want the *changes*!!! XXX TODO
      memset(telephoneState.dialSequence, 0, sizeof(telephoneState.dialSequence));
      for (int i=0; i<TelephoneButtons::TOTAL; i++ ) {
         if (telephoneState.buttonState[i] == true) {
            PlayDTMFSound(i);  // Or is this just later - part of the state, not part of the transition?
            break;
         }
      }
      break;
    case CallState::DIAL_TONE:
      // change sound to dial tone
      PlayDialTone();
      // cancel any pending or active connections. (This will also stop ringing)
      CancelConnections();
      break;
    case CallState::CONNECTION_ROUTING:
      SoundStop();
      RingerStop();
      CancelIncomingConnections();
      CancelConnectedConnections();
      break;
    case CallState::INCOMING:
      SoundStop();
      CancelConnectedConnections();
      CancelOutgoingConnections();
      RingerStart();
      break;
    case CallState::AWAITING_CONNECTION:
      CancelIncomingConnections();
      CancelConnectedConnections();
      PlayRinging();
      break;
    case CallState::BUSY:
      CancelIncomingConnections();
      CancelConnectedConnections();
      PlayBusySignal();
      break;
    case CallState::OFF_HOOK_TIMEOUT1:
      CancelConnections();
      PlayIfYoudLikeToMakeACall();
      break;
    case CallState::OFF_HOOK_TIMEOUT2:
      CancelConnections();
      PlayBeepBeepBeep();
      break;
    case CallState::OFF_HOOK:
      CancelConnections();
      SoundStop();
      break;
    case default:
      Serial.println("Unknown CallState");
      break;
  }
}

// And then depending on the current state, we either
// - feed the sound buffer
// - play a dtmf tone
// - give control to the local connection to do whatever it wants
// - gather the dialed numbers and match against the registered local connections

void loop() {
  unsigned long currentTime = millis();

  // ── Get current state of buttons and call --------------------──────
  GPIOChange& buttonChanges = readButtons(currentTime); // XXX need to figure out how I want to use the button changes.
  newTelephoneState = getTelephoneState(currentTime); 
  CallState newCallState = runStateMachine(oldCallState, newTelephoneState, oldTelephoneState, currentTime);
  changeCallState(newCallState, oldCallState, newTelephoneState, currentTime);

  bool ringerActive = getRingerActive();  // Is ringer *physically* ringing?


  // ── Ringer (HTTP-driven via shared state) ────────────────────────────
  updateRinger(currentTime, ringerActive);

  // ── Dial timeout: clear stale partial number ─────────────────────────
  if (dialedNumber.length() > 0 &&
      (currentTime - lastDigitTime > DIAL_TIMEOUT)) {
    Serial.printf("Dial timeout – clearing: %s\n", dialedNumber.c_str());
    dialedNumber = "";
  }

  delay(1);
}
