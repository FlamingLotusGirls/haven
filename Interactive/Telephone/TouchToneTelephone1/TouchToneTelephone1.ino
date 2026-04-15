/*
 * TouchToneTelephone1.ino
 * 
 * Reads button presses from a touch-tone telephone keypad and sends triggers
 * when specific phone numbers are dialed.
 * 
 * Hardware:
 *   - XIAO ESP32S3 (Dual Core, 8MB Flash, 8MB PSRAM)
 *   - MCP23008-E/P IO Expander (I2C address 0x20)
 *   - L298N H-Bridge for 20Hz AC generation
 *   - MAX98357A I2S Audio Amplifier
 * 
 * MCP23008 Pin Mapping:
 *   GP0-GP3: Rows 1-4
 *   GP4-GP6: Columns 1-3
 *   GP7: Hook switch
 * 
 * Keypad Layout:
 *   Row 1: 1 2 3
 *   Row 2: 4 5 6
 *   Row 3: 7 8 9
 *   Row 4: * 0 #
 * 
 * Required Arduino Libraries:
 *   - Adafruit MCP23017 (supports both MCP23008 and MCP23017)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <Wire.h>
#include <driver/i2s.h>
#include <SD.h>
#include <SPI.h>
#include "DeviceTriggers.h"

// Configuration structure
struct TelephoneConfig {
  char wifi_ssid[64];
  char wifi_pass[64];
  char trigger_server[64];
  int trigger_port;
  char device_name[64];
};

// Trigger mapping structures
struct PhoneTrigger {
  String phone_number;
  String trigger_name;
  std::shared_ptr<OneShotTrigger> trigger;
};

struct GenericTrigger {
  String trigger_name;
  std::shared_ptr<OneShotTrigger> trigger;
};

// Global configuration
TelephoneConfig config;
TriggerDevice* triggerDevice = nullptr;
std::vector<PhoneTrigger> phoneTriggers;
std::vector<GenericTrigger> genericTriggers;

// I2C Configuration for MCP23008 (XIAO ESP32S3)
#define I2C_SDA GPIO_NUM_5   // SDA (D4)
#define I2C_SCL GPIO_NUM_6   // SCL (D5)

// MCP23008 Pin Definitions
const int ROW_PINS[4] = {0, 1, 2, 3};     // GP0-GP3: Keypad rows
const int COL_PINS[3] = {4, 5, 6};        // GP4-GP6: Keypad columns
#define HOOK_SWITCH_MCP_PIN 7             // GP7: Hook switch (was unused)
#define MCP23008_ADDR 0x20

// L298N H-Bridge Configuration (No ENA - tie ENA pin HIGH on L298N board)
#define HBRIDGE_IN1 GPIO_NUM_1   // Direction pin 1 (D0)
#define HBRIDGE_IN2 GPIO_NUM_2   // Direction pin 2 (D1)

// SD Card - Standard 4-wire SPI (hardware SPI pins)
#define SD_CS_PIN   GPIO_NUM_44   // Chip Select (RX)
#define SD_MOSI_PIN GPIO_NUM_9   // MOSI (hardware SPI)
#define SD_MISO_PIN GPIO_NUM_8   // MISO (hardware SPI)
#define SD_SCK_PIN  GPIO_NUM_7   // SCK (hardware SPI, D8)

// I2S Configuration for MAX98357A
#define I2S_NUM         I2S_NUM_0
#define I2S_BCK_PIN     GPIO_NUM_4   // Bit clock (D3)
#define I2S_WS_PIN      GPIO_NUM_43  // Word select (TX/D6)
#define I2S_DOUT_PIN    GPIO_NUM_3  // Data out (D2)
#define SAMPLE_RATE     16000        // 16kHz sample rate
#define TONE_DURATION   200          // Tone duration in ms


// DTMF Frequency Table (Hz)
// Row frequencies: 697, 770, 852, 941
// Col frequencies: 1209, 1336, 1477
const int DTMF_FREQ_ROW[4] = {697, 770, 852, 941};

const int DTMF_FREQ_COL[3] = {1209, 1336, 1477};

// 20Hz AC Generation via Timer
#define AC_FREQ_HZ 20
#define HALF_PERIOD_US 25000  // 25ms = 1/(2*20Hz)
volatile bool hbridgeRunning = false;
volatile bool hbridgePolarity = false;
hw_timer_t *hbridgeTimer = NULL;

// Keypad mapping
const char KEYPAD[4][3] = {
  {'1', '2', '3'},
  {'4', '5', '6'},
  {'7', '8', '9'},
  {'*', '0', '#'}
};

// Button tracking
const unsigned long DEBOUNCE_DELAY = 50;
bool buttonState[4][3] = {false};
bool lastButtonReading[4][3] = {false};
unsigned long lastDebounceTime[4][3] = {0};

// Phone number tracking
String dialedNumber = "";
const unsigned long DIAL_TIMEOUT = 5000;
unsigned long lastDigitTime = 0;

// Registration tracking
const unsigned long REGISTRATION_INTERVAL = 120000;
unsigned long lastRegistrationTime = 0;

// Audio task for continuous I2S streaming
TaskHandle_t audioTaskHandle = NULL;
volatile int currentToneRow = -1;
volatile int currentToneCol = -1;
portMUX_TYPE audioMux = portMUX_INITIALIZER_UNLOCKED;

uint8_t readRegister(int reg) {
  int ret;
  size_t numBytes;
  Wire.beginTransmission(MCP23008_ADDR);
  numBytes = Wire.write(reg);
  if (numBytes != 1) {
    Serial.printf("WIRE unable to write, returning %d\n", numBytes);
    return 0;
  }
  ret = Wire.endTransmission(true); // release control of bus
  if (ret) { 
    Serial.printf("WIRE end transmission fails, %d\n", ret);
    return 0;
  }

  numBytes = Wire.requestFrom(MCP23008_ADDR, 1);
  if (numBytes != 1) {
    Serial.printf("WIRE request returns error %d\n", numBytes);
    return 0;
  }

  ret = Wire.read();
  if (ret == -1) {
    Serial.printf("WIRE read returns error %d\n", ret);
    return 0;
  }

  return (uint8_t)ret;
}

void writeRegister(int reg, int val){
  int ret;
  size_t numBytes;
  Wire.beginTransmission(MCP23008_ADDR);
  numBytes = Wire.write(reg); // pullup status register
  if (numBytes != 1) {
    Serial.printf("WIRE unable to write, returning %d\n", numBytes);
    return;
  }
  numBytes = Wire.write(val); // pullup status register
  if (numBytes != 1) {
    Serial.printf("WIRE unable to write, returning %d\n", numBytes);
    return;
  }
  ret = Wire.endTransmission(true); // release control of bus
  if (ret) { 
    Serial.printf("WIRE end transmission fails, %d\n", ret);
    return;
  }
  Serial.printf("Wrote 0x%x to %d\n", val, reg);
}

// Audio streaming task - runs continuously feeding I2S
void audioTask(void *parameter) {
  const int CHUNK_SIZE = 128;  // Small chunks for responsive streaming
  int16_t buffer[CHUNK_SIZE];
  
  double phaseLow = 0.0;
  double phaseHigh = 0.0;
  
  while (true) {
    int row, col;
    
    // Safely read current tone
    portENTER_CRITICAL(&audioMux);
    row = currentToneRow;
    col = currentToneCol;
    portEXIT_CRITICAL(&audioMux);
    
    if (row >= 0 && col >= 0) {
      // Generate tone
      int freqLow = DTMF_FREQ_ROW[row];
      int freqHigh = DTMF_FREQ_COL[col];
      
      double phaseIncrementLow = 2.0 * PI * (double)freqLow / (double)SAMPLE_RATE;
      double phaseIncrementHigh = 2.0 * PI * (double)freqHigh / (double)SAMPLE_RATE;
      
      for (int i = 0; i < CHUNK_SIZE; i++) {
        double sample1 = sin(phaseLow);
        double sample2 = sin(phaseHigh);
        buffer[i] = (int16_t)((sample1 + sample2) * 16000.0);
        
        phaseLow += phaseIncrementLow;
        phaseHigh += phaseIncrementHigh;
        
        if (phaseLow >= 6.283185307) phaseLow -= 6.283185307;
        if (phaseHigh >= 6.283185307) phaseHigh -= 6.283185307;
      }
    } else {
      // Generate silence
      memset(buffer, 0, CHUNK_SIZE * sizeof(int16_t));
      phaseLow = 0.0;
      phaseHigh = 0.0;
    }
    
    // Write to I2S (blocks if buffer full - that's OK)
    size_t bytes_written;
    i2s_write(I2S_NUM, buffer, CHUNK_SIZE * sizeof(int16_t), &bytes_written, portMAX_DELAY);
  }
}

// Start/update tone (called from main loop)
void setTone(int row, int col) {
  portENTER_CRITICAL(&audioMux);
  currentToneRow = row;
  currentToneCol = col;
  portEXIT_CRITICAL(&audioMux);
}

// Stop tone (silence)
void stopTone() {
  portENTER_CRITICAL(&audioMux);
  currentToneRow = -1;
  currentToneCol = -1;
  portEXIT_CRITICAL(&audioMux);
}

// Timer interrupt handler - toggles H-bridge polarity for AC output
void IRAM_ATTR onTimer() {
  if (hbridgeRunning) {
    hbridgePolarity = !hbridgePolarity;
    if (hbridgePolarity) {
      // Forward: IN1=HIGH, IN2=LOW
      digitalWrite(HBRIDGE_IN1, HIGH);
      digitalWrite(HBRIDGE_IN2, LOW);
    } else {
      // Reverse: IN1=LOW, IN2=HIGH
      digitalWrite(HBRIDGE_IN1, LOW);
      digitalWrite(HBRIDGE_IN2, HIGH);
    }
  }
}

// I2S initialization for MAX98357A
void initI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 16,    // Increased from 8 to 16 buffers
    .dma_buf_len = 512,     // Increased from 64 to 512 samples per buffer
    .use_apll = false,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0
  };
  
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCK_PIN,
    .ws_io_num = I2S_WS_PIN,
    .data_out_num = I2S_DOUT_PIN,
    .data_in_num = I2S_PIN_NO_CHANGE
  };
  
  i2s_driver_install(I2S_NUM, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM, &pin_config);
  i2s_zero_dma_buffer(I2S_NUM);
  
  Serial.println("I2S initialized for MAX98357A");
}

// Generate and play DTMF tone - generate all samples first, then stream
void playDTMF(int row, int col) {
  int freqLow = DTMF_FREQ_ROW[row];
  int freqHigh = DTMF_FREQ_COL[col];
  
  Serial.printf("Playing DTMF: %d Hz + %d Hz\n", freqLow, freqHigh);
  
  int numSamples = (SAMPLE_RATE * TONE_DURATION) / 1000;
  
  // Allocate buffer for entire tone
  int16_t *buffer = (int16_t*)malloc(numSamples * sizeof(int16_t));
  if (buffer == NULL) {
    Serial.println("ERROR: Failed to allocate audio buffer");
    return;
  }
  
  // Generate all samples with precise phase
  double phaseLow = 0.0;
  double phaseHigh = 0.0;
  double phaseIncrementLow = 2.0 * PI * (double)freqLow / (double)SAMPLE_RATE;
  double phaseIncrementHigh = 2.0 * PI * (double)freqHigh / (double)SAMPLE_RATE;
  
  for (int i = 0; i < numSamples; i++) {
    double sample1 = sin(phaseLow);
    double sample2 = sin(phaseHigh);
    
    // Mix and scale to 16-bit
    buffer[i] = (int16_t)((sample1 + sample2) * 16000.0);
    
    // Increment phase
    phaseLow += phaseIncrementLow;
    phaseHigh += phaseIncrementHigh;
    
    // Wrap phase
    if (phaseLow >= 6.283185307) phaseLow -= 6.283185307;
    if (phaseHigh >= 6.283185307) phaseHigh -= 6.283185307;
  }
  
  // Stream all samples to I2S in one write
  size_t bytes_written;
  i2s_write(I2S_NUM, buffer, numSamples * sizeof(int16_t), &bytes_written, portMAX_DELAY);
  
  free(buffer);
}

// H-Bridge control functions (ENA must be tied HIGH on L298N board)
void hbridgeStart() {
  hbridgeRunning = true;
  hbridgePolarity = false;
  
  // Start with forward direction
  digitalWrite(HBRIDGE_IN1, HIGH);
  digitalWrite(HBRIDGE_IN2, LOW);
  
  // Start timer to alternate polarity
  timerStart(hbridgeTimer);
  
  Serial.println("H-Bridge: STARTED (20Hz AC output)");
}

void hbridgeStop() {
  timerStop(hbridgeTimer);
  hbridgeRunning = false;
  
  // Brake: both LOW
  digitalWrite(HBRIDGE_IN1, LOW);
  digitalWrite(HBRIDGE_IN2, LOW);
  
  Serial.println("H-Bridge: STOPPED");
}

// Hook switch detection - now on MCP23008 GP7
bool isOffHook(uint8_t gpioPortRead) {
  return !(gpioPortRead && HOOK_SWITCH_MCP_PIN);
}

// Load configuration from LittleFS
bool loadConfig() {
  Serial.println("\n--- Loading Configuration from LittleFS ---");
  
  if (!LittleFS.begin(true)) {
    Serial.println("Failed to mount LittleFS");
    return false;
  }
  
  if (!LittleFS.exists("/triggers.json")) {
    Serial.println("Config file /triggers.json does not exist");
    LittleFS.end();
    return false;
  }
  
  File file = LittleFS.open("/triggers.json", "r");
  if (!file) {
    Serial.println("Failed to open config file");
    LittleFS.end();
    return false;
  }
  
  DynamicJsonDocument doc(2048);
  DeserializationError error = deserializeJson(doc, file);
  file.close();
  LittleFS.end();
  
  if (error) {
    Serial.print("Failed to parse config file: ");
    Serial.println(error.c_str());
    return false;
  }
  
  strlcpy(config.wifi_ssid, doc["wifi_ssid"] | "not_set", sizeof(config.wifi_ssid));
  strlcpy(config.wifi_pass, doc["wifi_pass"] | "not_set", sizeof(config.wifi_pass));
  strlcpy(config.trigger_server, doc["trigger_server"] | "192.168.5.174", sizeof(config.trigger_server));
  config.trigger_port = doc["trigger_port"] | 5002;
  strlcpy(config.device_name, doc["device_name"] | "Telephone", sizeof(config.device_name));
  
  Serial.println("Configuration loaded successfully:");
  Serial.printf("  Device Name: %s\n", config.device_name);
  Serial.printf("  WiFi: %s\n", config.wifi_ssid);
  Serial.printf("  Trigger Server: %s:%d\n", config.trigger_server, config.trigger_port);
  
  triggerDevice = new TriggerDevice(config.device_name, config.trigger_server, config.trigger_port);
  
  JsonArray triggers = doc["triggers"];
  if (triggers.isNull()) {
    Serial.println("No triggers defined in config");
    return true;
  }
  
  Serial.println("\nTrigger Configuration:");
  
  int phoneCount = 0;
  int genericCount = 0;
  
  for (JsonObject triggerObj : triggers) {
    String triggerName = triggerObj["name"].as<String>();
    
    if (triggerObj.containsKey("phone_number")) {
      PhoneTrigger phoneTrigger;
      phoneTrigger.phone_number = triggerObj["phone_number"].as<String>();
      phoneTrigger.trigger_name = triggerName;
      phoneTrigger.trigger = triggerDevice->AddOneShotTrigger(phoneTrigger.trigger_name);
      phoneTriggers.push_back(phoneTrigger);
      
      Serial.printf("  %s -> %s.%s\n", 
                    phoneTrigger.phone_number.c_str(), 
                    config.device_name,
                    phoneTrigger.trigger_name.c_str());
      phoneCount++;
    } else {
      GenericTrigger genericTrigger;
      genericTrigger.trigger_name = triggerName;
      genericTrigger.trigger = triggerDevice->AddOneShotTrigger(genericTrigger.trigger_name);
      genericTriggers.push_back(genericTrigger);
      genericCount++;
    }
  }
  
  Serial.printf("\nTotal triggers: %d phone-based, %d generic\n", phoneCount, genericCount);
  
  return true;
}

void connectToWiFi() {
  Serial.println("\n--- WiFi Connection ---");
  Serial.print("Connecting to ");
  Serial.print(config.wifi_ssid);
  Serial.println("...");
  
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

void checkForTriggerMatch() {
  for (PhoneTrigger& phoneTrigger : phoneTriggers) {
    if (dialedNumber == phoneTrigger.phone_number) {
      Serial.println("\n*** PHONE NUMBER MATCH ***");
      Serial.printf("Dialed: %s -> Triggering: %s.%s\n", 
                    dialedNumber.c_str(),
                    config.device_name,
                    phoneTrigger.trigger_name.c_str());
      
      phoneTrigger.trigger->SendTriggerEvent();
      
      dialedNumber = "";
      lastDigitTime = millis();
      return;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n=== Touch-Tone Telephone Trigger Device ===");
  
  // Initialize I2C with explicit pins
  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.println("\n--- I2C Initialized ---");
  Serial.printf("  SDA: GPIO %d\n", I2C_SDA);
  Serial.printf("  SCL: GPIO %d\n", I2C_SCL);
  Wire.setClock(10000);

  // Scan I2C bus for devices
  delay(2000);
  Serial.println("\n--- Scanning I2C Bus ---");
  int devicesFound = 0;
  for (byte address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();
    
    if (error == 0) {
      Serial.printf("  I2C device found at address 0x%02X\n", address);
      devicesFound++;
    }
  }
  
  if (devicesFound == 0) {
    Serial.println("  WARNING: No I2C devices found!");
    Serial.println("  Check:");
    Serial.println("    - SDA/SCL connections");
    Serial.println("    - Pull-up resistors (3.3k on SDA and SCL)");
    Serial.println("    - MCP23008 power (VDD=3.3V)");
    Serial.println("    - Address pins (A0,A1,A2 to GND for 0x20)");
  } else {
    Serial.printf("  Found %d I2C device(s)\n", devicesFound);
  }
  
  // Initialize MCP23008
  Serial.println("\n--- Initializing MCP23008 IO Expander ---");
  Serial.printf("  Expected address: 0x%02X\n", MCP23008_ADDR);

/*
  if (!MCP.begin(true)) {
    Serial.println("!!!!!MCP BEGIN FAILURE!!!!!!");
  }

  Serial.print("Connect: ");
  Serial.println(MCP.isConnected());

  //  all at once.
  if (!MCP.pinMode8(0xFF)) {
    Serial.println("**** MCP PINMODE FAILURE!!!!");
  }
  */
  /*
  //  set individual pins
  for (int pin = 0; pin < 8; pin++)
  {
    MCP.pinMode1(pin, INPUT);
  */
  
  /*
  int retryCount = 0;
  while (retryCount++ < 4) {
    Serial.println("Attempting to connect to IO expander");
    if (!mcp.begin_I2C(MCP23008_ADDR)) {
      Serial.println("ERROR: Failed to initialize MCP23008!");
      Serial.println("\nTroubleshooting steps:");
      Serial.println("  1. Verify MCP23008 is powered (3.3V on VDD pin)");
      Serial.println("  2. Check I2C connections:");
      Serial.printf("     - SDA: GPIO %d to MCP23008 SDA\n", I2C_SDA);
      Serial.printf("     - SCL: GPIO %d to MCP23008 SCL\n", I2C_SCL);
      Serial.println("  3. Add 4.7k pull-up resistors on SDA and SCL to 3.3V");
      Serial.println("  4. Verify address pins: A0=GND, A1=GND, A2=GND (for 0x20)");
      Serial.println("  5. Check if device appears in I2C scan above");
      delay(1000);
    }
    break;
  }
  if (retryCount < 4) {
    Serial.println("MCP23008 initialized successfully!");
  } else {
    Serial.println("Failed to initialize MCP23008!!");
  }
  
  // Configure MCP23008 pins
  for (int i = 0; i < 4; i++) {
    mcp.pinMode(ROW_PINS[i], INPUT_PULLUP);
  }
  for (int i = 0; i < 3; i++) {
    mcp.pinMode(COL_PINS[i], INPUT_PULLUP);
  }
  // Configure hook switch pin
  mcp.pinMode(HOOK_SWITCH_MCP_PIN, INPUT_PULLUP);
  */
  delay(200);

  for (int i=0; i<4; i++) {
    readRegister(0x06);
    delay(200);
  }

  // Set all ports as input
  Serial.println("Attempting to set register 0 (GPIO config)) write 0xFF all 1 (input)");
  writeRegister(0x00, 0xFF);
  delay(10);

  // pullups
  Serial.println("Attempting to set register 6 (GPIO pullup) to all 1s (all input pullup)");
  writeRegister(0x06, 0xFF);

  delay(10);

  // Read io...
  uint8_t gpio = readRegister(0x09);

  // Initialize Hook Switch (on MCP23008 GP7)
  Serial.println("\n--- Initializing Hook Switch ---");
  Serial.printf("  Hook Switch: MCP23008 GP%d\n", HOOK_SWITCH_MCP_PIN);
  Serial.printf("  Current State: %s\n", isOffHook(gpio) ? "OFF-HOOK" : "ON-HOOK");
  
  // Initialize L298N H-Bridge for AC generation (NO ENA PIN)
  Serial.println("\n--- Initializing L298N H-Bridge (20Hz AC) ---");
  Serial.println("  NOTE: Tie L298N ENA pin HIGH on board");
  
  pinMode(HBRIDGE_IN1, OUTPUT);
  pinMode(HBRIDGE_IN2, OUTPUT);
  
  digitalWrite(HBRIDGE_IN1, LOW);
  digitalWrite(HBRIDGE_IN2, LOW);
  
  /*
  // Create timer for 20Hz AC generation (alternates every 25ms)
  hbridgeTimer = timerBegin(1000000);  // 1MHz timer frequency
  timerAttachInterrupt(hbridgeTimer, &onTimer);
  timerAlarm(hbridgeTimer, HALF_PERIOD_US, true, 0);  // 25000us period, auto-reload
  */
  
  Serial.println("L298N H-Bridge initialized for 20Hz AC output!");
  Serial.printf("  IN1: GPIO %d\n", HBRIDGE_IN1);
  Serial.printf("  IN2: GPIO %d\n", HBRIDGE_IN2);
  Serial.printf("  AC Frequency: %d Hz\n", AC_FREQ_HZ);
  Serial.println("  State: STOPPED");
  
  // Initialize SD Card (Standard 4-wire SPI)
  Serial.println("\n--- Initializing SD Card (4-wire SPI) ---");
  
  // Initialize SPI with all 4 pins (CLK, MISO, MOSI, CS)
  SPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);
  
  if (SD.begin(SD_CS_PIN)) {
    Serial.println("SD Card initialized successfully!");
    uint64_t cardSize = SD.cardSize() / (1024 * 1024);
    Serial.printf("  SD Card Size: %llu MB\n", cardSize);
    Serial.printf("  CS: GPIO %d\n", SD_CS_PIN);
    Serial.printf("  SCK: GPIO %d\n", SD_SCK_PIN);
    Serial.printf("  MOSI: GPIO %d\n", SD_MOSI_PIN);
    Serial.printf("  MISO: GPIO %d\n", SD_MISO_PIN);
  } else {
    Serial.println("WARNING: SD Card initialization failed");
    Serial.println("  System will continue without SD card");
  }
  
  // Initialize I2S for MAX98357A
  Serial.println("\n--- Initializing I2S Audio (MAX98357A) ---");
  initI2S();
  Serial.printf("  BCK: GPIO %d\n", I2S_BCK_PIN);
  Serial.printf("  WS: GPIO %d\n", I2S_WS_PIN);
  Serial.printf("  DOUT: GPIO %d\n", I2S_DOUT_PIN);
  Serial.printf("  Sample Rate: %d Hz\n", SAMPLE_RATE);
  Serial.println("  DTMF tones enabled");
  
  // Give I2S time to fully initialize
  delay(100);
  
  /*
  // Start audio streaming task on Core 1 (ESP32S3 is dual core)
  Serial.println("\n--- Starting Audio Task ---");
  xTaskCreatePinnedToCore(
    audioTask,              // Function
    "AudioTask",            // Name
    8192,                   // Stack size
    NULL,                   // Parameters
    1,                      // Priority
    &audioTaskHandle,       // Handle
    1                       // Core 1 (Core 0 runs loop())
  );
  Serial.println("Audio task started on Core 1 (ESP32S3 dual core)");
  delay(100);  // Let task start
  */
  
  // Load configuration
  if (!loadConfig()) {
    Serial.println("ERROR: Failed to load configuration");
    while (1) delay(1000);
  }
  
  // Connect to WiFi
  connectToWiFi();
  
  // Register device
  if (triggerDevice && WiFi.status() == WL_CONNECTED) {
    triggerDevice->RegisterDevice();
    lastRegistrationTime = millis();
  }
  
  Serial.println("\nSetup complete. Ready to detect phone numbers.\n");
}

unsigned long lastTime = 0;
void loop() {
  unsigned long currentTime = millis();
  
  // Test: continuous tone while looping
  // setTone(1, 2);  // Set tone for button "2" (697 Hz + 1336 Hz)

/*
  // Check WiFi
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Reconnecting...");
    connectToWiFi();
  }
*/
  
  /*
  // Periodic registration
  if (triggerDevice && (currentTime - lastRegistrationTime >= REGISTRATION_INTERVAL)) {
    triggerDevice->RegisterDevice();
    lastRegistrationTime = currentTime;
  }
  */
  
  // Dial timeout
  if (dialedNumber.length() > 0 && (currentTime - lastDigitTime > DIAL_TIMEOUT)) {
    Serial.print("Dial timeout. Clearing: ");
    Serial.println(dialedNumber);
    dialedNumber = "";
  }
  
  uint8_t mcpGPIOData = readRegister(0x09);

  // Read keypad
  bool rowActive[4];
  for (int r = 0; r < 4; r++) {
    rowActive[r] = (mcpGPIOData & (1<<r)) == 0;
  }
  
  bool colActive[3];
  for (int c = 0; c < 3; c++) {
    colActive[c] = (mcpGPIOData & (1 <<(c + 4))) == 0;
  }
  
  // Check buttons
  for (int r = 0; r < 4; r++) {
    for (int c = 0; c < 3; c++) {
      bool currentReading = rowActive[r] && colActive[c];
      
      if (currentReading != lastButtonReading[r][c]) {
        lastDebounceTime[r][c] = currentTime;
        lastButtonReading[r][c] = currentReading;
      }
      
      if ((currentTime - lastDebounceTime[r][c]) > DEBOUNCE_DELAY) {
        if (currentReading != buttonState[r][c]) {
          buttonState[r][c] = currentReading;
          
          char key = KEYPAD[r][c];
          if (buttonState[r][c]) {
            Serial.print("Button PRESSED: '");
            Serial.print(key);
            Serial.println("'");
            
            // Play DTMF tone
            playDTMF(r, c);
            
            if (key >= '0' && key <= '9') {
              dialedNumber += key;
              lastDigitTime = currentTime;
              Serial.print("Dialed: ");
              Serial.println(dialedNumber);
              checkForTriggerMatch();
            } else if (key == '#') {
              Serial.print("Complete: ");
              Serial.println(dialedNumber);
              checkForTriggerMatch();
            } else if (key == '*') {
              Serial.println("Clearing");
              dialedNumber = "";
              lastDigitTime = currentTime;
            }
          }
        }
      }
    }
  }
  
  delay(1);
}
