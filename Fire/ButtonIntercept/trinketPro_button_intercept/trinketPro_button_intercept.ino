#include "button_sequence.h"
#if 0
#include <Wire.h>
#include <PCA95x5.h>

// #define TEST
//#define DEBUG

// NB - for debugging, need to take off channels 0 and 1 for the moment b/c FTDI
#ifdef DEBUG
const int inputs[] = {15,14,4,12,11,10};
const int outputs[] = {3,13,5,6,8,9}; 
#else 
const int inputs[] = {0,1,15,14,4,12,11,10};
const int outputs[] = {17,16,3,13,5,6,8,9}; 
#endif

const int NUM_CHIPS = 2;
const int PCA9555_ADDRESS[NUM_CHIPS] = {0x20, 0x27};

#ifdef DEBUG
const int NUM_CHANNELS = 6;
#else
const int NUM_CHANNELS = 8;
#endif

uint8_t channelModes[8]; // would be NUM CHANNELS, if I hadn't fucked up the wiring...

PCA9555 ioex[NUM_CHIPS];

void setupForInput(int chipId) {
  if (chipId < 0 || chipId >= NUM_CHIPS) {
    return;
  }
  ioex[chipId].attach(Wire, PCA9555_ADDRESS[chipId]);
  ioex[chipId].polarity(PCA95x5::Polarity::ORIGINAL_ALL);
  ioex[chipId].direction(PCA95x5::Direction::IN_ALL);
}

void readChannelModes() {
  uint16_t rawData1 = ioex[0].read();
  uint16_t rawData2 = ioex[1].read();

  // I appear to be interpreting on and off incorrectly...
  rawData1 = ~rawData1;
  rawData2 = ~rawData2;
 
#ifdef DEBUG
  Serial.print("Raw data, chip 0: ");
  Serial.println(rawData1, BIN);
  Serial.print("Raw data, chip 1: ");
  Serial.println(rawData2, BIN);
#endif

  // Now interpret that data. Unfortunately I've made an unholy mess
  // of the wiring to bit conversion.
  channelModes[0] = ((rawData2 & 0x80) >> 7) |
               ((rawData2 & 0x40) >> 5) | 
               ((rawData2 & 0x20) >> 3);
  channelModes[1] = ((rawData2 & 0x10) >> 4) |
               ((rawData2 & 0x8) >> 2) | 
               ((rawData2 & 0x4) >> 0);
  channelModes[2] = ((rawData2 & 0x2) >> 1) |
               ((rawData2 & 0x1) << 1) | 
               ((rawData2 & 0x100) >> 6);
  channelModes[3] = ((rawData2 & 0x200) >> 9) |
               ((rawData2 & 0x400) >> 9) | 
               ((rawData2 & 0x800) >> 9);
  channelModes[4] = ((rawData1 & 0x80) >> 7) |
               ((rawData1 & 0x40) >> 5) | 
               ((rawData1 & 0x20) >> 3);
  channelModes[5] = ((rawData1 & 0x10) >> 4) |
               ((rawData1 & 0x8) >> 2) | 
               ((rawData1 & 0x4) >> 0);
  channelModes[6] = ((rawData1 & 0x2) >> 1) |
               ((rawData1 & 0x1) << 1) | 
               ((rawData1 & 0x100) >> 6);
  channelModes[7] = ((rawData1 & 0x200) >> 9) |
               ((rawData1 & 0x400) >> 9) | 
               ((rawData1 & 0x800) >> 9);

#ifdef DEBUG
  for (int i=0; i<8; i++) {
    Serial.print("Channel ");
    Serial.print(i);
    Serial.print(" set to ");
    Serial.println(channelModes[i]);
  }
#endif
}

// Channel State machine
// pressed - can transition to transition_unpressed  (current state - pressed. Transitions if state is unpressed)
// unpressed - can transition to transition_pressed  (current state - unpressed. Transitions if state is pressed)
// transition_pressed - can transition to playback or wait_unpressed (current state - pressed, transitions if state changes within hold time, or hold time met )
// playback - if pressed, go to wait_pressed. If not pressed, go to transition_unpressed (current state - don't care. Plays program. 
// transition_unpressed - can transition to wait_unpressed or wait_pressed (current state - unpressed, transitions if state changes within hold time, or hold time met)
// playheadTime

typedef struct Section {
  bool onOff;
  uint32_t duration;
};

// NB - 'Sequence' is actually a pointer to a null-Section terminated array of Sections
typedef struct Sequence {
  Section* section;
};

// NB - Section Array must be terminated with {false, 0}
// JDV Bird - two longs, followed by 5 shorts
Section JDVBird[] = {{true, 500}, {false, 300}, {true, 500}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 500}, {false, 0}};
// Chirp chirp - two shorts.
Section chirpChirp[] = {{true, 75}, {false, 200}, {true, 75}, {false, 200}, {false, 0}};

// 8 possible sequences, from 3 bit switch on the board
Sequence sequences[8] = {NULL, JDVBird, chirpChirp, NULL, NULL, NULL, NULL, NULL};

class Program {
  public:
    Program(Sequence sequence) : m_sections(sequence.section), m_buttonState(false) {
      int idx = 0;
      Section* curSection;
      do {
         curSection = &m_sections[idx++];
      } while ((curSection->onOff) || (curSection->duration > 0));
      m_nSections = idx;

      m_totalPlayTime = 0;
      for (int i=0; i<m_nSections; i++) {
        m_totalPlayTime += m_sections[i].duration;
      }
    }

    bool IsFinished(uint32_t playTime) {
      return playTime > m_totalPlayTime;
    }

    bool GetButtonState(uint32_t playTime) {
      if (playTime > m_totalPlayTime) {
        return false;
      }
      
      uint32_t elapsedTime = 0;
      int curSection = 0;
      while (elapsedTime < playTime) {
        elapsedTime += m_sections[curSection++].duration;
      }

      bool newState = m_sections[curSection - 1].onOff;
      if (newState != m_buttonState) {
        m_buttonState = newState;
      }
      return m_sections[curSection - 1].onOff;
    }

  private:
    Section* m_sections;
    int m_nSections;
    int m_totalPlayTime;
    bool m_buttonState;
};

enum ChannelState {
  PRESSED,
  UNPRESSED,
  TRANSITION_PRESSED,
  PLAYBACK,
  TRANSITION_UNPRESSED
};

enum class Mode {
  Follower,
  Program,
};

// ChannelController starts in state UNPRESSED.a
class ChannelController {
public:
  ChannelController(int sequenceIdx = 0) : m_channel(s_channel++), m_sequenceIdx(-1), m_nextSequenceIdx(-1), m_program(NULL), m_state(UNPRESSED), m_playheadTimeMs(0), m_transitionStartTimeMs(0), m_playState(false) {
  }

  void setProgram(int sequenceIdx) {
    if (sequenceIdx != m_sequenceIdx) {
      if (m_state == PLAYBACK) {
#ifdef DEBUG
        Serial.print("New program on channel ");
        Serial.print(m_channel);
        Serial.println(", queued");
#endif
        m_nextSequenceIdx = sequenceIdx;
      } else {
        if (m_program != NULL) {
          delete m_program;
        }
        if (sequences[sequenceIdx].section == NULL) {
          // special case - the null program (follower)
          m_program = NULL;
        } else {
          m_program = new Program(sequences[sequenceIdx]);
        }
        m_mode = m_program == NULL ? Mode::Follower : Mode::Program;
        m_sequenceIdx = sequenceIdx;
        m_nextSequenceIdx = -1;
        m_state = UNPRESSED;
#ifdef DEBUG
        Serial.print("New program on channel ");
        Serial.print(m_channel);
        Serial.print(m_mode == Mode::Follower ? ": follower" : ": program ");
        if (m_mode != Mode::Follower) {
          Serial.println(sequenceIdx);
        } else {
          Serial.println("");
        }
#endif
      }
    }
  }

  // I need to think of this as something that maps button presses to poofer responses. The channel metaphor isn't quite right. 
  // ButtonChannelController -> Poofer Program

  /* Update channel controller based on state of physical button */
  void update(bool buttonPressed, uint32_t curTimeMs) {
   // XXX there are too many button states here for me this morning - buttonpressed, buttonstate, play state?
    bool oldPlayState = m_playState;
    if (m_mode == Mode::Follower) {
      m_playState = buttonPressed;     
    } else { 
      switch(m_state) {
        case PRESSED: // waiting in pressed state
          if (!buttonPressed) {
            m_state = TRANSITION_UNPRESSED;
#ifdef DEBUG
            Serial.print("Channel: ");
            Serial.print(m_channel);
            Serial.print(", Wait Pressed -> Transition Unpressed,  ");
            Serial.println(curTimeMs);
#endif
            m_transitionStartTimeMs = curTimeMs;
          }
          break;
        case UNPRESSED:
          if (buttonPressed) {
            m_state = TRANSITION_PRESSED;
#ifdef DEBUG
            Serial.print("Channel: ");
            Serial.print(m_channel);
            Serial.print(", Wait Unpressed -> Transition Pressed,  ");
            Serial.println(curTimeMs);
#endif
            m_transitionStartTimeMs = curTimeMs;
          }
          break;
        case TRANSITION_PRESSED:
          // If we read button PRESSED for the duration of the transition time, start playback
          if (buttonPressed) {
            uint32_t deltaTime = curTimeMs - m_transitionStartTimeMs; // Not worrying about wrap; 59 days
            if (deltaTime > DEBOUNCE_TIMEOUT_MS) {
#ifdef DEBUG
              Serial.print("Channel: ");
              Serial.print(m_channel);
              Serial.print(", Transition Pressed -> PLAYBACK, ");
              Serial.println(curTimeMs);
#endif
              m_state = PLAYBACK;
              m_playbackStartMs = curTimeMs; // XXX next loop, so 50 ms delay. Fixme
              m_playheadTimeMs = 0;
              m_transitionStartTimeMs = 0;
            }
          } else {
            // If at any time during the transition time we read button UNPRESSED, go to UNPRESSED
            // state
#ifdef DEBUG
            Serial.print("Channel: ");
            Serial.print(m_channel);
            Serial.print(", Transition Pressed -> Wait Unpressed,  ");
            Serial.println(curTimeMs);
#endif
            m_state = UNPRESSED;
            m_transitionStartTimeMs = 0;
          }
          break;
        case TRANSITION_UNPRESSED:
          if (!buttonPressed) {
            uint32_t deltaTime = curTimeMs - m_transitionStartTimeMs; // NB not worrying about wrap
            if (deltaTime > DEBOUNCE_TIMEOUT_MS) {
#ifdef DEBUG
              Serial.print("Channel: ");
              Serial.print(m_channel);
              Serial.print(", Transition UnPressed -> Wait Unpressed,  ");
              Serial.println(curTimeMs);
#endif
              m_state = UNPRESSED;
              m_playheadTimeMs = 0;
              m_transitionStartTimeMs = 0;
            }
          } else {
            m_state = PRESSED;
#ifdef DEBUG
            Serial.print("Channel: ");
            Serial.print(m_channel);
            Serial.print("Transition UnPressed -> Wait Pressed,  ");
            Serial.println(curTimeMs);
#endif
            m_transitionStartTimeMs = 0;
          }
          break;
        case PLAYBACK:
          int m_playheadTimeMs = curTimeMs - m_playbackStartMs;
          if (m_program->IsFinished(m_playheadTimeMs)) {
#ifdef DEBUG
            Serial.print("Channel: ");
            Serial.print(m_channel);
            Serial.print(", PLAYBACK FINISHED,  ");
            Serial.println(curTimeMs);
#endif
            if (buttonPressed) {
              m_state = PRESSED;
            } else {
              m_state = TRANSITION_UNPRESSED;
              m_transitionStartTimeMs = 0;
            }
            // XXX why am I doing this?
            delete m_program;
            m_program = NULL;
            if (m_nextSequenceIdx >= 0) {
              m_program = new Program(sequences[m_nextSequenceIdx]);
              m_nextSequenceIdx = -1;
            }
          } else {
            bool playState = m_program->GetButtonState(m_playheadTimeMs);  // What about program that plays on multiple channels? XXX
            if (m_playState != playState) {
#ifdef DEBUG
              Serial.print("Channel: ");
              Serial.print(m_channel);
              Serial.print(", Playback state Transition: ");
              if (playState) {
                Serial.print("PRESSED,  ");
              } else {
                Serial.print("UNPRESSED,  ");
              }
              Serial.println(curTimeMs);
#endif
              m_playState = playState;
            }
          }
          break;
        default:
          break;
      }
    }
#ifdef DEBUG
    if (m_playState != oldPlayState) {
      Serial.print("Channel: ");
      Serial.print(m_channel);
      Serial.print(" write ");
      Serial.print(m_playState ? "PRESSED, " : "UNPRESSED, ");
      Serial.println(curTimeMs);
    }
#endif
    if (m_playState != oldPlayState) {
#ifdef DEBUG
      Serial.print("Changing play state on channel ");
      Serial.print(m_channel);
      Serial.print(", button pressed ");
      Serial.println(m_playState ? "PRESSED" : "UNPRESSED");
#endif // DEBUG
      // NB - Pressed corresponds to pulling the output low.
      digitalWrite(outputs[m_channel], m_playState ? HIGH : LOW);
    }
  }

  static int s_channel;

private:
  const int DEBOUNCE_TIMEOUT_MS = 130;
  
  Program* m_program;
  int m_sequenceIdx;
  int m_nextSequenceIdx;
  Mode m_mode = Mode::Follower;
  ChannelState m_state;
  uint32_t m_transitionStartTimeMs;
  int m_channel;
  bool m_playState = HIGH;
  uint32_t m_playbackStartMs;
  uint32_t m_playheadTimeMs;
};

int ChannelController::s_channel = 0;

ChannelController controllers[NUM_CHANNELS];
/*
#ifdef TEST

// Fake input on/off
enum class InputTestType { // XXX what about standard, like I was doing before?
  DebounceOn = 0,
  DebounceOff,
  LongPress,
  NewPress,
  Follower,
};

Section debounceOn[] = {{true, 40}, {false, 60}, {true, 80}, {false, 20}, {true, 150}, {false, 0}}; // debounce on
Section debounceOff[] = {{true, 200}, {false, 60}, {true, 80}, {false, 20}, {true, 80}, {false, 200}, {false, 0}}; // debounce off
Section longPress[] = {{true, 7000}, {false, 0}}; // long press
Section newPress[] = {{true, 500}, {false, 200}, {true, 500}, {false, 0}};  // new press

Section* testSections[] = {debounceOn, debounceOff, longPress, newPress}; 


class InputTest {
  public:
  InputTest(InputTestType testType = InputTestType::DebounceOn) {
    m_testProgram = new Program(testSections[(int)testType]);
    m_oldInput = false;
    m_running = false;
  }

  void Start(uint32_t startTimeMs = 0) {
    m_startTimeMs = startTimeMs != 0 ? startTimeMs : millis();
    m_running = true;
  }

  void Stop() {
    m_running = false;
  }

  bool GetButtonState(uint32_t timeMs = 0) {
    if (!m_running) {
       return false;
    }
    
    uint32_t playTimeMs = timeMs == 0 ? millis() - m_startTimeMs : timeMs - m_startTimeMs;
    bool newInput =  m_testProgram->GetButtonState(playTimeMs);
    if (newInput != m_oldInput) {
#ifdef DEBUG
    Serial.print("State change! ");
    Serial.print(newInput ? "PRESSED, " : "UNPRESSED, ");
    Serial.println(millis());
#endif
    m_oldInput = newInput; 
  }
  return newInput;
}

  void changeTest(InputTestType testType) {
    delete m_testProgram;
    m_testProgram = new Program(testSections[(int)testType]);
  }

private: 
  uint32_t m_startTimeMs;
  bool m_oldInput;
  bool m_running = false;
  Program* m_testProgram;
};

InputTest inputTest;

#endif // TEST
*/
bool outputActive[NUM_CHANNELS];

int tickTime;

void setup() {
  tickTime = millis();

#ifdef DEBUG
  Serial.begin(9600);
#endif

  delay(1000); // timeout for ...?

#ifdef DEBUG
  Serial.println("Starting... Sanity");
#endif

  for (int i=0; i<NUM_CHANNELS; i++) {
    controllers[i].setProgram(0); 
  }

// #ifndef TEST
  // Init I2C bus
  Wire.begin();

  // Set up PCA9555 chips for input
  setupForInput(0);
  setupForInput(1);
// #endif
  
  // Set inputs and outputs on trinket
  for (int i=0; i<NUM_CHANNELS; i++) {
    pinMode(inputs[i], INPUT_PULLUP);
    digitalWrite(outputs[i], LOW); // making sure output starts low
    pinMode(outputs[i], OUTPUT);
    outputActive[i] = false;
  }

#ifdef TEST
  // Setting up programs manually for testing 
#ifdef PATTERN_OUT
  controllers[0].setProgram(1);
#else // FOLLOWER
  controllers[0].setProgram(0);
#endif // PATTERN_OUT
  inputTest.Start();
#else // STANDARD - NO TEST
  readChannelModes();
  for (int i=0; i<NUM_CHANNELS; i++) {
    controllers[i].setProgram(channelModes[i]);
  }
#endif // TEST

  debouncedReadInit();
  delay(1000); // Wait for pins to settle // XXX shouldn't have to do this
}

bool inputState[NUM_CHANNELS]; // init to HIGH
bool inputStateChangePending[NUM_CHANNELS]; // init to false
int  inputStateChangeTime[NUM_CHANNELS]; // init to 0
const int debounceTimerMs = 100;
// NB - this returns the high/low state of the line. Button
// state is pressed LOW, ie, false
bool debouncedReadInit() {
  for (int i=0; i<NUM_CHANNELS; i++) {
    inputState[i] = HIGH;
    inputStateChangePending[i] = false;
    inputStateChangeTime[i] = 0;
  }
}
bool debouncedRead(int channel, int curTimeMs) {
  bool input = digitalRead(inputs[channel]);
#ifdef DEBUG
  if (input == LOW) {
    Serial.print("Raw BUTTON PRESS detected on channel ");
    Serial.println(channel);
  }
#endif
  if (inputStateChangePending[channel]) {
    if (input == inputState[channel]) {
      // change fails debounce state. 
#ifdef DEBUG
        Serial.print("Debounce fail on channel ");
        Serial.println(channel);
#endif
      inputStateChangePending[channel] = false;
    } else {
      if (curTimeMs > inputStateChangeTime[channel] + debounceTimerMs) {
        // debounce success, change state
#ifdef DEBUG
        Serial.print("Debounce success, change state on channel to ");
        Serial.print(input ? "HIGH" : "LOW");
        Serial.print(", channel "); 
        Serial.println(channel);
#endif
        inputState[channel] = input;
      }
    }
  } else {
    if (input != inputState[channel]) {
#ifdef DEBUG
        Serial.print("Potential state change detected, incoming is ");
        Serial.print(input ? "HIGH" : "LOW");
        Serial.print(" ,channel ");
        Serial.println(channel);
#endif
      inputStateChangePending[channel] = true;
      inputStateChangeTime[channel] = curTimeMs;
    }
  }
  return inputState[channel];
}

// XXX - I have multiple levels of debounce here. FIXME
bool firstTime = true;
void loop() {
  // Serial.println("loop...");
  // Read data, send to the channel controllers.
  int curTimeMs = millis(); 
#ifdef TEST
    controllers[0].update(inputTest.GetButtonState(curTimeMs), curTimeMs);
#else
  for (int i=0; i<NUM_CHANNELS; i++) {
    bool buttonState = debouncedRead(i, curTimeMs);
    if (firstTime) {
#ifdef DEBUG
      Serial.print("Initial button read on channel ");
      Serial.print(i);
      Serial.print(" value ");
      Serial.println(buttonState ? "HIGH" : "LOW");
#endif
    } else {
      // Note here that debouncedRead returns HIGH and LOW. HIGH is UNPRESSED, LOW is PRESSED
      controllers[i].update(!debouncedRead(i, curTimeMs), curTimeMs);
    }
  }
  firstTime = false;


  // Every second or so, re-read the channelMode and change the program
  if ((curTimeMs < tickTime) || (curTimeMs > tickTime + 1000)) {
#ifdef DEBUG
    // Serial.println("tick");
#endif
    /*  // XXX - For the moment, let's not change the program in real time
    readChannelModes();
    for (int i=0; i<NUM_CHANNELS; i++) {
      controllers[i].setProgram(channelModes[i]);
    }
    */
    tickTime = curTimeMs;
  }
#endif // TEST
}
#endif // 0

int timeoutMs = 0;
void loop() {
  buttonLoop();
}

void setup() {
  buttonSetup();
}
