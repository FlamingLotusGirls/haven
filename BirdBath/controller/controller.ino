
#include <Adafruit_PWMServoDriver.h>
#include <Adafruit_NeoPixel.h>

// #define USE_ARTMODE
// #define USE_SOLENOIDS

#define board_version 2

// NB - The three board addresses are hardcoded to 4, 5, 6. 
// Must recompile when generating software for a different board
#define BOARD_ADDRESS 4

#define ARTNET_FRAME 0
#define ARTNET_NOZZLE 1

Adafruit_NeoPixel rgb_leds(2, D6, NEO_GRB + NEO_KHZ800);
uint32_t led_status = 0;
const uint32_t led_status_okay = rgb_leds.Color(0, 255, 0);
const uint32_t led_status_uninit = rgb_leds.Color(255, 0, 0);

uint32_t led_mode = 0;
const uint32_t led_mode_startup = rgb_leds.Color(255, 0, 0);
const uint32_t led_mode_wifi = rgb_leds.Color(0, 0, 255);
const uint32_t led_mode_artmode = rgb_leds.Color(0, 255, 0);

// PCA9539 i2c GPIO expander
#include "src/lib/PCA9539.h"
PCA9539 pca9539(0x77);

#include <ArtnetWifi.h>

IPAddress ip(10, 0, 0, BOARD_ADDRESS);
IPAddress gateway(10, 0, 0, 9);  // NB - Controlling rpi is acting as access point and router
//IPAddress ip(192, 168, 13, BOARD_ADDRESS);
//IPAddress gateway(192, 168, 13, 1);
IPAddress subnet(255, 255, 255, 0);
const char *ssid = "birdbath";
const char *password = "birdbath";
// const char *ssid = "lightcurve";
// const char *password = "curvelight";
ArtnetWifi artnet;

// SERVOS
const int NUM_VALVES = 12;
float valveStates[NUM_VALVES]; // Stores valve states (0.0 to 1.0)

// XXX - NB - CalMin and CalMax are never written (other than to be set up as their default values)
int calMinAll = 2250;
int calMin[NUM_VALVES];
int calMax[NUM_VALVES];    // max calibration values, define below using range from min (microseconds)
const int calRange = 1500; // usec also, low to high

const int INTERVAL_MAX = 1400;
const int INTERVAL_MIN = 300;

// SOLENOIDS

// this number, out of 100, is the chance a solenoid will turn on in any given cycle
#ifdef USE_ARTMODE
int artModeSolenoidDutyCycle = 30;
#endif // USE_ARTMODE

long startTime = 0;

// Valve

struct ValveData
{
  float currentValue;
  float nextValue;
  unsigned long previousTime;
  unsigned long nextTime;
  unsigned long solenoidToggleTime;
  bool solenoidState;
};

ValveData valveData[NUM_VALVES];

//
// States of Controller
//

// It is always attempting to connect to the network and receive network packets.
// If we've compiled to run with 'artmode', it will do a random test sequence (aka, 'artMode') 
// while waiting for a network packet.
// If we're not compiled for 'artmode', it will simply sit quiescently while waiting for a
// command from the network.
//
#ifdef USE_ARTMODE
bool artModeActive = false;
// if switch1, forceArtMode, but switch2 unforces it
bool forceArtMode = false;
bool preventArtMode = false;
#endif // USE_ARTMODE

bool artnetActive = false;

// set to the millis value when we last did a successful beghinwifi
// does not account for wraparound, so reboot your board every 49 days
unsigned long millisLastBeginWifi = 0;

// interval between wifi inits
#define WIFI_BEGIN_INTERVAL (800)

// when we received the last ArtNet packet
unsigned long millisLastArtnet = 0;

// number of millis without a network packet when we move to artnet
#define ARTNET_PACKET_DELAY (120 * 1000)

//
// set valve

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(0x47);

int valueToMsec(int valveNum, float state)
{
  return (calMin[valveNum] + (calMax[valveNum] - calMin[valveNum]) * state);
}

void controlValve(int valveNum, int servoValue)
{
  pwm.writeMicroseconds(valveNum, servoValue);
}

void setValveState(int valveNum, float state, bool print = 0)
{
  if (state > 1.0)
  {
    Serial.print(" valve set too high ");
    Serial.println(state);
    state = 1.0;
  } // XXX what about low values? 
  valveStates[valveNum] = state;
  int servoValue = valueToMsec(valveNum, state);
  controlValve(valveNum, servoValue);
  if (print)
  {
    Serial.print("Set valve ");
    Serial.print(valveNum + 1);
    Serial.print(" to state ");
    Serial.println(state);
  }
}

unsigned long millisLastDisplayValves = 0; // Add this global variable at the top of your code

#define DISPLAY_VALVE_DELAY 1000

// XXX - I would like to send a UDP status packet in response to a query

void displayValves(unsigned long currentTime, bool force = 0)
{
  if (currentTime < millisLastDisplayValves + DISPLAY_VALVE_DELAY)
  {
    return;
  }
  millisLastDisplayValves = currentTime;

  printWifiStatus();

  Serial.println("");
  for (int i = 0; i < NUM_VALVES; i++)
  {
    Serial.print("Valve ");
    Serial.print(i + 1);
    Serial.print(": |");
    int position = (int)(valveStates[i] * 16);
    for (int j = 0; j <= 16; j++)
    {
      if (j == position)
      {
        Serial.print("X");
      }
      else
      {
        Serial.print(" ");
      }
    }
    Serial.print("| Cal: (");
    Serial.print(calMin[i]);
    Serial.print(", ");
    Serial.print(calMax[i]);
    Serial.print(") Val: ");
    Serial.print(valveStates[i], 2);
    Serial.print(" (");
    Serial.print(valueToMsec(i, valveStates[i]));
    Serial.println(")");
  }
  // drawDisplay();
}

//
// set solenoid
#ifdef USE_SOLENOIDS
// ValveNum is the pin number on the controller
void setSolenoidState(int valveNum, bool state)
{
  pca9539.digitalWrite(valveNum, state);
}
#endif // USE_SOLENOIDS

//
// Wifi helper functions

// This should be called repeatedly, with a delay of at least 1ms between calls, until
// `isWifiConnected` returns true.
void beginWifi()
{
  millisLastBeginWifi = millis();
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  WiFi.useStaticBuffers(true);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
  WiFi.setMinSecurity(WIFI_AUTH_WEP);
  WiFi.config(ip, gateway, subnet);
  WiFi.begin(ssid, password);
}
// Returns true when we are ready to start receiving artnet.
bool isWifiConnected()
{
  return WiFi.status() == WL_CONNECTED;
}

void printWifiStatus()
{
  if (isWifiConnected())
  {

    Serial.println("Wifi Connected ");
    Serial.print("SSID: ");
    Serial.println(WiFi.SSID());

    IPAddress ip = WiFi.localIP();
    Serial.print("IP Address: ");
    Serial.println(ip);

    long rssi = WiFi.RSSI();
    Serial.print("signal strength (RSSI):");
    Serial.print(rssi);
    Serial.println(" dBm");


  }
  else
  {
    Serial.print("Wifi NOT Connected: ");
    Serial.println("Status: ");
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
  }
}

//
// ArtNet
// These functions process incoming ArtNet packets

// This must be called after wifi is connected
void beginArtnet()
{
  artnetActive = true;
  artnet.begin();
  artnet.setArtDmxCallback(onDmxFrame);

  led_mode = led_mode_wifi;
  update_rgb_led_color();
}

void endArtnet()
{
  artnet.stop();
  artnetActive = false;
}

// This must be called repeatedly in a loop, with a delay of at least 1ms between calls.
void receiveArtnet()
{
  artnet.read();
}

// Do not call this directly, it will be called when you call `receiveArtnet`.

// Okay, we have a problem for calibration. The artnet packet does not have a way to 
// adjust just a single value, which is extremely useful for calibration.
// Okay, so I'm going to modify the artnet packets.
void onDmxFrame(uint16_t universe, uint16_t numBytesReceived, uint8_t sequence, uint8_t *data)
{
  millisLastArtnet = millis();
#ifdef USE_ARTMODE
  artModeActive = false;
#endif

  if (numBytesReceived < 2) {
    return;
  }

  // Using 2 artnet channels (a.k.a. bytes) per nozzle - first byte for solenoid, second for servo.
  // Adding a header (one byte per packet) that describes the packet type. The type can be one of
  // ARTNET_FRAME - Data is an array of two-byte packets, one element in the array per nozzle
  // ARTNET_NOZZLE - Data is a single two-byte packet with a header for the index of the nozzle
  uint8_t frameType = data[0];
  if (frameType == ARTNET_NOZZLE) {
    uint8_t nozzleIndex = data[1];
    if (nozzleIndex < NUM_VALVES && numBytesReceived >= 4) {
#ifdef USE_SOLENOIDS
      setSolenoidState(nozzleIndex, data[2]);
#endif 
      setValveState(nozzleIndex, float(data[3]) / 255.0);
    }
  } else { // frameType == ARTNET_FRAME
    int numNozzlesReceived = min(numBytesReceived / 2, NUM_VALVES);
    for (int nozzleIndex = 0; nozzleIndex < numNozzlesReceived; nozzleIndex++) {
      int valveDataStartIndex = nozzleIndex * 2;
#ifdef USE_SOLENOIDS
      uint8_t solenoidByte = data[valveDataStartIndex];
      setSolenoidState(nozzleIndex, solenoidByte > 0);
#endif // USE_SOLENOIDS
      uint8_t servoByte = data[valveDataStartIndex + 1];
      float servoByteFloat = (float)servoByte;
      setValveState(nozzleIndex, servoByteFloat / 255.0);
    }
  }
}

//
// SWITCHES
// there are three switches on the board. THey seem to be
// right after the solenoids, thus they should be at pins 12, 13, 14

int switch1 = -1;
int switch2 = -1;
int switch3 = -1;

void readSwitches()
{

  // this doesn't seem to work?
  //  switch1 = pca9539.digitalRead(12);
  //  switch2 = pca9539.digitalRead(13);
  //  switch3 = pca9539.digitalRead(14);

  switch1 = 0;
  switch2 = 0;
  switch3 = 0;
}

// RGB LED functions

void update_rgb_led_color()
{
  if (board_version < 2) return;
  rgb_leds.setPixelColor(0, led_status);
  rgb_leds.setPixelColor(1, led_mode);
  rgb_leds.show();
}

//
//
// ARDUINO ENTRY POINTS
//
// setup

void setup()
{
  Serial.begin(115200);
  delay(1000);
  Serial.println("START");

  // initialize RGB LEDs for status and mode
  if (board_version >= 2)
  {
    rgb_leds.begin();
    rgb_leds.show();
    rgb_leds.setBrightness(50); // 50/255 
    led_status = led_status_uninit;
    led_mode = led_mode_startup;
    update_rgb_led_color();
  }

  // we have a pin that is the RST for the 9539
  Serial.println(" setting reset pin to low ");
  pinMode( D3, OUTPUT);
  digitalWrite( D3, HIGH);


  // initialize solenoid pins
  pca9539.pinMode(pca_A0, OUTPUT); // 0
  pca9539.pinMode(pca_A1, OUTPUT); // 1
  pca9539.pinMode(pca_A2, OUTPUT); // 2
  pca9539.pinMode(pca_A3, OUTPUT); // 3
  pca9539.pinMode(pca_A4, OUTPUT); // 4
  pca9539.pinMode(pca_A5, OUTPUT); // 5
  pca9539.pinMode(pca_A6, OUTPUT); // 6
  pca9539.pinMode(pca_A7, OUTPUT); // 7
  pca9539.pinMode(pca_B0, OUTPUT); // 8
  pca9539.pinMode(pca_B1, OUTPUT); // 9
  pca9539.pinMode(pca_B2, OUTPUT); // 10
  pca9539.pinMode(pca_B3, OUTPUT); // 11
  pca9539.pinMode(pca_B4, OUTPUT); // 12
  // I believe these are input switches but didn't work?
#if 0
  pca9539.pinMode(pca_B5, OUTPUT); // SW1
  pca9539.pinMode(pca_B6, OUTPUT); // SW2
  pca9539.pinMode(pca_B7, OUTPUT); // SW3
#else
  pca9539.pinMode(pca_B5, INPUT); // SW1
  pca9539.pinMode(pca_B6, INPUT); // SW2
  pca9539.pinMode(pca_B7, INPUT); // SW3
#endif


  // Initialize the servo system
  pwm.begin();
  Serial.println("servo pwm output begun");
  pwm.setOscillatorFrequency(25200000);
  pwm.setPWMFreq(50); // Analog servos run at ~50 Hz updates

  // get the initial switch state
  readSwitches();

  // initialize the valve structure and set servos to SAFE
  for (int i = 0; i < NUM_VALVES; i++)
  {
    valveStates[i] = 0.0;
    calMin[i] = calMinAll;            // Default values
    calMax[i] = calMin[i] - calRange; // Default values
#ifdef USE_SOLENOIDS
    // enable and turn off solenoid outputs
    setSolenoidState(i, 0); // Initially off
#endif
  }

  led_status = led_status_okay;
  update_rgb_led_color();

  // Start trying to connect to wifi
  beginWifi();

  //
  Serial.println("Servos: all 0.5");
  // Set each valve to zero (again)
  for (int i = 0; i < NUM_VALVES; i++)
  {
    setValveState(i, 0.5);
  }
  delay(1000); // Wait for 1 second

  // Pulse all valves to 0.2
  Serial.println("Servos: all 0.3");
  for (int i = 0; i < NUM_VALVES; i++)
  {
    setValveState(i, 0.3);
  }
  delay(200); // Wait for 1 second

  // Set all valves back to zero
  Serial.println("Servos: 0.5");
  for (int i = 0; i < NUM_VALVES; i++)
  {
    setValveState(i, 0.5);
  }
  delay(1000); // Wait for 2 second
}

//
// ARDUINO ENTRY POINT
//
// loop

// XXX NB - So apparently the switches are for reading art mode!

#ifdef USE_ARTMODE
void checkArtMode() {
  if (switch1 && (!forceArtMode))
  {
    Serial.println(" switch 1 detected: forcing ArtMode");
    forceArtMode = true;
    preventArtMode = false;
  }
  if (switch2 && (!preventArtMode))
  {
    Serial.println(" switch 2 detected: prevent artmode");
    forceArtMode = false;
    preventArtMode = true;
  }
  if (switch3 && (forceArtMode || preventArtMode))
  {
    Serial.println(" switch 3 detected: normal mode ");
    forceArtMode = false;
    preventArtMode = false;
  }

  // art mode if it's forced, not if it's prevented, or if its been a while since a packet
  if ((!preventArtMode) &&
      (forceArtMode || (currentTime > millisLastArtnet + ARTNET_PACKET_DELAY)))
  {
    if (artModeActive == false)
    {
      initArtMode();
    }
    updateArtMode(currentTime);
  }
}
#endif // USE_ARTMODE

void loop()
{
  unsigned long currentTime = millis();

  // this will only display occasionally
  displayValves(currentTime, 0);

#ifdef USE_ARTMODE
  // Switch1: safe valves and enter artmode immediately
  readSwitches();
  checkArtMode();
#endif 
  
  // if we're not connected, attempt to connect
  if (!isWifiConnected())
  {

    // if we're not connected but we had an artnet listener, stop it
    if (artnetActive == true)
    {
      endArtnet();
    }

    // occasionally, reinit the wifi unit
    if (currentTime > millisLastBeginWifi + WIFI_BEGIN_INTERVAL)
    {
      printWifiStatus();
      Serial.println("Attempting to connect to wifi");
      beginWifi();
    }
  }
  else // wifiIsConnected
  {
    if (artnetActive == false)
    {
      beginArtnet();
    }
    receiveArtnet();
  }

  delay(2); // Delay(1) supposedly important for ArtNet, it's also not good to overdrive
}


#ifdef USE_ARTMODE
//
// Art Mode
// this is the default the sculpture goes into when it's not receiving network

void initArtMode()
{
  for (int i = 0; i < NUM_VALVES; i++)
  {
    valveData[i].currentValue = 0.0;
    valveData[i].nextValue = random(0, 100) / 100.0;
    valveData[i].previousTime = millis();
    valveData[i].nextTime = millis() + random(1000, 2000); // Random time between 1 to 5 seconds
    valveData[i].solenoidToggleTime = valveData[i].previousTime + random(0, (valveData[i].nextTime - valveData[i].previousTime));
    valveData[i].solenoidState = random(2); // Randomly set to true or false
  }
  artModeActive = true;
  led_mode = led_mode_artmode;
  update_rgb_led_color();
}

void updateArtMode(unsigned long currentTime)
{
  for (int i = 0; i < NUM_VALVES; i++)
  {
    if (currentTime >= valveData[i].nextTime)
    {
      // Update data for next interpolation cycle

      // Serial.print(valveData[i].previousTime);
      valveData[i].previousTime = valveData[i].nextTime;
      valveData[i].nextTime = currentTime + random(INTERVAL_MIN, INTERVAL_MAX);
      valveData[i].currentValue = valveData[i].nextValue;
      valveData[i].nextValue = random(0, 100) / 100.0;
    }

    // Interpolate valve position
    float t = (float)(currentTime - valveData[i].previousTime) / (valveData[i].nextTime - valveData[i].previousTime);
    float interpolatedValue = lerp(valveData[i].currentValue, valveData[i].nextValue, t);
    setValveState(i, interpolatedValue);

#ifdef USE_SOLENOIDS
    // Change solenoid value
    if (currentTime >= valveData[i].solenoidToggleTime && currentTime < valveData[i].nextTime)
    {
      // Determine if the solenoid should be turned on based on the duty cycle
      bool shouldTurnOn = random(100) < artModeSolenoidDutyCycle;
      setSolenoidState(i, shouldTurnOn);

      valveData[i].solenoidToggleTime = valveData[i].nextTime + random(0, (valveData[i].nextTime - currentTime));
      valveData[i].solenoidState = shouldTurnOn;
    }
#endif
  }

  // displayValves(currentTime);
}

#endif // USE_ARTMODE
