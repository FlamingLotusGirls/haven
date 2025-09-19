//#define ARDUINO
#ifdef ARDUINO
#include <Wire.h>
#include <PCA95x5.h>
#else
#include <stdio.h>
#include <cstdint>
#include <chrono>
#include <cstring>
#include <unistd.h>
#endif

/// BUTTON_SEQUENCE.CPP
/// Controller for the button intercept hardware module added to the flame control box for Haven.
/// This software (currently) runs on a trinketPro 5V, and translates the 8 button input signals
/// coming into the box to signals (or sets of signals) to the 8 flame control relays on the
/// main board.
///
/// A single button input is translated to output signals by means of a Program, which wraps
/// one or more Sequences that describe the desired on/off pattern on a specific output channel.
/// A Program in turn is wrapped by a ChannelController, which runs the state machine for its
/// input channel.
///
/// The particular Program associated with an input channel is chosen by a dip switch on the
/// button intercept module. There is one dip switch for each input channel, and each dip switch
/// has 8 possible values.
///
/// Future improvements:
///   - Use an ESP32 instead of a trinketPro. This would require a board spin, but there are
///     several advantages here:
///     1) More I/O. I have only 8 *output* channels, but that's not a good reason to limit the
///        *input channels.
///     2) Configurability. The Programs are currently hard coded, however, decisions about what
///        works best for interactivity are often best made on-site. Being able to download programs
///        into NVRAM on an ESP32 would allow us to easily modify the effects, and would make it
///        easy to have different sets of effects on different boxes.
///     3) Network connectivity. Currently, the only outputs are the flame control relays in the
///        same physical box as the button intercept module. If I have wifi connectivity back to
///        the main brain, I can send arbitrary flame control commands over the RS485 bus. I'm also
///        no longer limited to flame control - I can send lighting and sound commands as well.
///   - Board spin to rationalize IO lines. The wiring to the dip switches is a nightmare - and
//      there's no good reason for that.

// #define DEBUG
#ifndef ARDUINO
#ifndef MOCK_INPUT
#define MOCK_INPUT
#endif
#endif // ~ARDUINO

#ifdef ARDUINO
// NB - for debugging, need to take off channels 0 and 1 for the moment b/c FTDI
#ifdef DEBUG
const int inputs[] = {15,14,4,12,11,10};
const int outputs[] = {3,13,5,6,8,9}; 
#else 
const int inputs[] = {0,1,15,14,4,12,11,10};
const int outputs[] = {17,16,3,13,5,6,8,9}; 
#endif
#endif // ARDUINO

#if defined(ARDUINO) && defined(DEBUG)
const int NUM_INPUT_CHANNELS = 6;
const int NUM_OUTPUT_CHANNELS = 6;
#else
const int NUM_INPUT_CHANNELS = 8;
const int NUM_OUTPUT_CHANNELS = 8;
#endif

// Forward declarations
void initMillis();
#ifndef ARDUINO
uint32_t millis();
#endif
bool readRawInput();
bool writeOutput();


/**********  UTILITY FUNCTIONS ***************/
// The Arduino libraries provide the convenience function millis(), which is the
// milliseconds since the board booted/program started. Create a version of this for
// the non-embedded debug environment.
#ifdef ARDUINO
void initMillis() {
}
#else 
std::chrono::steady_clock::time_point start_time;
void initMillis() {
  start_time = std::chrono::steady_clock::now();
}
uint32_t millis() {
  auto elapsed_duration = std::chrono::steady_clock::now() - start_time;
  long long milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(elapsed_duration).count();
  return (uint32_t)milliseconds;
}
#endif // ARDUINO


/*************** SECTIONS AND PROGRAMS *************/
// A Section is a duration and a button state - on or off, for some period of time.
// A Program is just a wrapper for an array of these things, and can be queried
// for the button states at a specified play time.

struct Section {
  bool onOff;
  int32_t duration;
};

struct ChannelSequence {
  int outputChannel;
  int delayMs;
  Section *section; // array, terminated with {false, 0}

  ChannelSequence(int outputChannelIn, int delayMsIn, Section* sectionIn) : outputChannel(outputChannelIn), delayMs(delayMsIn), section(sectionIn) {
  }
};

typedef struct PlayState {
  bool valid;
  bool buttonPressed;
} PlayState;

class Program {
  /// Program
  /// Wrapper for an array of Sections. Stateless.
  public:
    Program(ChannelSequence** sequences, const char* name) : m_sequences(sequences), m_name(name), m_totalPlayTime(0) {
      // Calculate total play time, so we can tell when this program is finished.
      // printf("Initializing program %s\n", name);
      ChannelSequence* curSequence = m_sequences[0];
      int i=0;
      while (curSequence != NULL) {
        // printf(" Getting sequence, delay %d, outputChannel %d, section at %p\n", curSequence->delayMs, curSequence->outputChannel, curSequence->section);
        int sequencePlayTimeMs = curSequence->delayMs;
        int idx = 0;
        Section* curSection = curSequence->section;
        while (curSection->duration >= 0) {
          sequencePlayTimeMs += curSection->duration;
          curSection++;
        }
        // printf("Sequence play time is %d\n", sequencePlayTimeMs);
        if (m_totalPlayTime < sequencePlayTimeMs) {
          m_totalPlayTime = sequencePlayTimeMs;
        }
        i++;
        curSequence = m_sequences[i];
        if (i>2) {
          break;
        }
      }
      // printf("Total play time is %d\n", m_totalPlayTime);
    }

    bool IsFinished(uint32_t playTime) {
      return playTime > m_totalPlayTime;
    }

    bool GetButtonStates(uint32_t playTime, PlayState playState[], int defaultOutputChannel) { // playState is array of size output_channels
      if (playTime > m_totalPlayTime) {
        return false;
      }
      
      ChannelSequence* curSequence = m_sequences[0];
      int i=0;
      while (curSequence != NULL) {
        uint32_t elapsedTime = curSequence->delayMs;
        bool output = false;
        Section* curSection = &(curSequence->section[0]);
        bool timeLessThanSectionEnd = elapsedTime <= playTime;
        // printf("going into while loop? %s\n", timeLessThanSectionEnd ? "true" : "false");
        while ((elapsedTime <= playTime) && (curSection->duration > 0)) {
          output = curSection->onOff;
          elapsedTime += curSection->duration;
          curSection++;
        }
        int outputChannel = curSequence->outputChannel >= 0 ? curSequence->outputChannel : defaultOutputChannel;
        playState[outputChannel].buttonPressed = output;
        playState[outputChannel].valid = true;
        curSequence = m_sequences[++i];
      }

      return true;
    }

    const char* GetName() {
      return m_name;
    }

  private:
    ChannelSequence** m_sequences;
    const char* m_name;
    int m_totalPlayTime;
};

// NB - Section Array must be terminated with {xxx, -1}

// JDV Bird - two longs, followed by 5 shorts
Section JDVBird[] = {{true, 500}, {false, 300}, {true, 500}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 200}, {true, 100}, {false, 500}, {false, -1}};
// Chirp chirp - two shorts.
Section chirpChirp[] = {{true, 75}, {false, 200}, {true, 75}, {false, 200}, {false, -1}};

// XXX - There *may* be a way, avoiding templates, to initialize arrays in a nicer-looking way
// than this. I do not know what it is. (I'm avoiding templates because I don't want to create any
// sort of templates on a very memory limited embedded device).
ChannelSequence universalJDVBird(-1, 0, JDVBird);
ChannelSequence universalChirpChirp(-1, 0, chirpChirp);

ChannelSequence* universalJDVBirdArray[] = {&universalJDVBird, NULL};
ChannelSequence* universalChirpChirpArray[] = {&universalChirpChirp, NULL};

Program JDVBirdProgram(universalJDVBirdArray, "JDVBird");
Program chirpChirpProgram(universalChirpChirpArray, "ChirpChirp");

ChannelSequence thisThenThatJDVBird(4, 0, JDVBird);
ChannelSequence thisThenThatChirpChirp(5, 100, chirpChirp);
ChannelSequence* thisThenThatArray[] = {&thisThenThatJDVBird, &thisThenThatChirpChirp, NULL};
Program thisThenThatProgram(thisThenThatArray, "ThisAndThat");

ChannelSequence* stdAndOtherArray[] = {&thisThenThatJDVBird, &universalChirpChirp, NULL};
Program stdAndOtherProgram(stdAndOtherArray, "StdAndOther");

// 8 possible programs, from 3 bit switch on the board
Program* programs[8] = {NULL, &JDVBirdProgram, &chirpChirpProgram, NULL, NULL, NULL, &stdAndOtherProgram, &thisThenThatProgram};


/******************** CHANNELS AND CHANNELCONTROLLERS ****************/
// A ChannelController takes an input on a specified input channel, and decides what that means for 
// an output channel. This could be simply following the input channel on the default output channel, 
// or playing a complicated program across one or more output channels

enum ChannelControllerState {
  WAIT_FOR_PRESS,
  WAIT_FOR_UNPRESS,
  PLAYBACK
};

enum class ChannelControllerMode {
  Follower,
  Program,
};

class ChannelController {
public:
  ChannelController() : m_program(NULL), m_mode(ChannelControllerMode::Follower), m_inputChannel(s_inputChannel++), m_nextProgram(NULL), m_state(WAIT_FOR_UNPRESS) {
    m_defaultOutputChannel = m_inputChannel;
    memset(m_outputState, 0, NUM_OUTPUT_CHANNELS*sizeof(PlayState));
  }

  void setProgram(Program* program) {
    if (program != m_program) {
      if (m_state == PLAYBACK) {
#ifdef ARDUINO
#ifdef DEBUG
        Serial.print("New program queued on channel ");
        Serial.println(m_inputChannel);
#endif
#else
        printf("New program on channel %d, queued\n", m_inputChannel);
#endif
        m_nextProgram = program;
      } else {
        m_program = program;
        m_mode = m_program == NULL ? ChannelControllerMode::Follower : ChannelControllerMode::Program;
        m_nextProgram = NULL;
        m_state = WAIT_FOR_PRESS;
#ifdef ARDUINO
#ifdef DEBUG
        Serial.print("New program on channel ");
        Serial.print(m_inputChannel);
        Serial.print(", program ");
        Serial.println(m_program == NULL ? ":follower " : m_program->GetName());
#endif
#else
        printf("New program on channel %d, program %s\n", m_inputChannel, m_program == NULL ? ":follower " : m_program->GetName());
#endif 
      }
    }
  }

  void update(bool buttonPressed, uint32_t curTimeMs) {
    if (m_mode == ChannelControllerMode::Follower) {
      m_outputState[m_defaultOutputChannel].valid = true;
      m_outputState[m_defaultOutputChannel].buttonPressed = buttonPressed;
    } else {
      switch(m_state) {
        case WAIT_FOR_PRESS: 
          if (buttonPressed) {
#ifdef ARDUINO
#ifdef DEBUG
            Serial.print("Channel: ");
            Serial.print(m_inputChannel);
            Serial.print(", Transition Pressed -> PLAYBACK ");
            Serial.println(curTimeMs);
#endif
#else
            printf("Channel: %d, Transition Pressed -> PLAYBACK %d\n", m_inputChannel, curTimeMs);
#endif // ARDUINO
            m_state = PLAYBACK;
            m_playbackStartMs = curTimeMs; // XXX next loop, so 50 ms delay. Fixme
          }
          break;
        case WAIT_FOR_UNPRESS:
          if (!buttonPressed) {
            m_state = WAIT_FOR_PRESS;
          }
          break;
        case PLAYBACK:
          {
            int playheadTimeMs = curTimeMs - m_playbackStartMs;
            if (m_program->IsFinished(playheadTimeMs)) {
#ifdef ARDUINO
#ifdef DEBUG
              Serial.print("Channel: ");
              Serial.print(m_inputChannel);
              Serial.print(", PLAYBACK FINISHED, ");
              Serial.println(curTimeMs);
#endif
#else
              printf("Channel: %d, PLAYBACK FINISHED, %d\n", m_inputChannel, curTimeMs);
#endif // ARDUINO
              m_state = WAIT_FOR_UNPRESS;     
              if (m_nextProgram != NULL) {
                m_program = m_nextProgram;
                m_nextProgram = NULL;
                }
            } else {
              memset(m_outputState, 0, NUM_OUTPUT_CHANNELS*sizeof(PlayState));
              m_program->GetButtonStates(playheadTimeMs, m_outputState, m_defaultOutputChannel);
            }
          }
          break;
        default:
          break;
      }
    }
  }

  PlayState* getPlayState() {
    return m_outputState;
  }

  static int s_inputChannel;  // For convenience. Allows me to auto-increment the channel id in the ctor, which allows me to statically allocate an array of controllers.
private:
  int m_inputChannel;  // Input channel controlled by this ChannelController
  int m_defaultOutputChannel; // For follower, default output channel. For now, this is the same idx as the input channel
  Program* m_program;  // Program playing on this channel.
  Program* m_nextProgram;  // Used if old program is playing when new program is specified
  ChannelControllerMode m_mode = ChannelControllerMode::Follower;  // Convenience. Null program means output directly follows channel input
  ChannelControllerState m_state; // Playing? Waiting for button press?
  PlayState m_outputState[NUM_OUTPUT_CHANNELS];  // current output
  uint32_t m_playbackStartMs;
};

int ChannelController::s_inputChannel = 0;

ChannelController controllers[NUM_INPUT_CHANNELS];

#ifdef ARDUINO
const int NUM_PCA9555_CHIPS = 2;
const int PCA9555_ADDRESS[NUM_PCA9555_CHIPS] = {0x20, 0x27};
PCA9555 ioex[NUM_PCA9555_CHIPS];

void initI2C() {
  Wire.begin();
  for (int i=0; i<NUM_PCA9555_CHIPS; i++){
    ioex[i].attach(Wire, PCA9555_ADDRESS[i]);
    ioex[i].polarity(PCA95x5::Polarity::ORIGINAL_ALL);
    ioex[i].direction(PCA95x5::Direction::IN_ALL);
  }
}

void readChannelModes(uint8_t channelModes[]) {
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
#endif // ARDUINO

void initChannelControllers() {
#ifdef ARDUINO
  uint8_t channelModes[8]; // would be NUM_INPUT_CHANNELS, if I hadn't fucked up the wiring...
  readChannelModes(channelModes);
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    controllers[i].setProgram(programs[channelModes[i]]);
  }
#else
  // At the moment, programs 1, 2, 6, and 7 are non-trivial
  controllers[1].setProgram(programs[6]);
  controllers[2].setProgram(programs[7]);
#endif
}

/********** FAKE INPUT ********/
// Fake input on/off
#ifdef MOCK_INPUT
enum class InputTestType {
  DebounceOn = 0,
  DebounceOff,
  LongPress,
  NewPress,
};

Section debounceOn[] = {{true, 40}, {false, 60}, {true, 80}, {false, 20}, {true, 150}, {false, -1}}; // debounce on
Section debounceOff[] = {{true, 200}, {false, 60}, {true, 80}, {false, 20}, {true, 80}, {false, 200}, {false, -1}}; // debounce off
Section longPress[] = {{true, 7000}, {false, -1}}; // long press
Section newPress[] = {{true, 500}, {false, 200}, {true, 500}, {false, -1}};  // new press

ChannelSequence debounceOnSequence(1,0,debounceOn);
ChannelSequence debounceOffSequence(1,0,debounceOff);
ChannelSequence longPressSequence(1,0,longPress);
ChannelSequence newPressSequence(1,0,newPress);
ChannelSequence* inputSequenceDebounceOn[] = {&debounceOnSequence, NULL};
ChannelSequence* inputSequenceDebounceOff[] = {&debounceOffSequence, NULL};
ChannelSequence* inputSequenceLongPress[] = {&longPressSequence, NULL};
ChannelSequence* inputSequenceNewPress[] = {&newPressSequence, NULL};

Program debounceOnProgram(inputSequenceDebounceOn, "DebounceOn");
Program debounceOffProgram(inputSequenceDebounceOff, "DebounceOff");
Program debounceLongPress(inputSequenceLongPress, "LongPress");
Program debounceNewPress(inputSequenceNewPress, "NewPress");

Program inputPrograms[] = {debounceOnProgram, debounceOffProgram, debounceLongPress, debounceNewPress}; 

class InputTest {
public:
  InputTest(InputTestType testType = InputTestType::DebounceOn) {
    m_testProgram = &inputPrograms[(int)testType];
    printf("Input Test, program is %s\n", m_testProgram->GetName());
    for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
      m_oldInput[i] = false;
      m_cachedInput[i].buttonPressed = false;
      m_cachedInput[i].valid = false;
    }
    m_running = false;
    m_cachedTime = 0;
    m_inputValid = false;
  }

  void Start(uint32_t startTimeMs = 0) {
    m_startTimeMs = startTimeMs != 0 ? startTimeMs : millis();
    m_running = true;
  }

  void Stop() {
    m_running = false;
  }

  bool GetButtonState(int channel, uint32_t timeMs = 0) {
    if (!m_running || timeMs < m_startTimeMs) {
       return false;
    }

    if (timeMs != m_cachedTime || m_cachedTime == 0) {
      uint32_t playTimeMs = timeMs == 0 ? millis() - m_startTimeMs : timeMs - m_startTimeMs;
      m_inputValid = m_testProgram->GetButtonStates(playTimeMs, m_cachedInput, channel);
    }
    bool newInput = !m_inputValid ? false : !m_cachedInput[channel].valid ? false : m_cachedInput[channel].buttonPressed;
    if (newInput != m_oldInput[channel]) {
      printf("%d: Raw state change! Channel %d to %s\n", timeMs, channel, newInput ? "PRESSED" : "UNPRESSED");
      m_oldInput[channel] = newInput;
    }
    m_cachedTime = timeMs;
    return newInput;
  }

  void changeTest(InputTestType testType) {
    m_testProgram = &inputPrograms[(int)testType];
    for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
      m_oldInput[i] = false;
    }
  }

private:
  uint32_t m_startTimeMs;
  bool m_oldInput[NUM_INPUT_CHANNELS];
  bool m_running = false;
  Program* m_testProgram;
  uint32_t m_cachedTime;
  PlayState m_cachedInput[NUM_INPUT_CHANNELS];
  bool m_inputValid = false;
};

InputTest inputTest;
#endif // MOCK_INPUT

/************** IO **************/

// either going to be reading from a Program or getting data from the actual device
bool readRawInput(int inputChannel, int curTimeMs) {
#ifdef ARDUINO
  bool input = digitalRead(inputs[inputChannel]);
#ifdef DEBUG
/*
  Serial.print("Reading value ");
  Serial.print(input ? "HIGH " : "LOW ");
  Serial.print("from channel ");
  Serial.print(inputChannel);
  Serial.print(", pin ");
  Serial.println(inputs[inputChannel]);
  */
#endif // DEBUG
  // NB - PRESSED is when the pin is held LOW, hence the negation
  return !input; 
  // !digitalRead(inputs[inputChannel]);
#else
  return inputTest.GetButtonState(inputChannel, curTimeMs);
#endif
}

void writeOutput(int outputChannel, bool output) {
#ifdef ARDUINO
#ifdef DEBUG
/*
  Serial.print("Writing value ");
  Serial.print(output ? "PRESSED " : "UNPRESSED ");
  Serial.print("to output channel ");
  Serial.print(outputChannel);
  Serial.print(", pin ");
  Serial.println(outputs[outputChannel]);
  */
 #endif 
  digitalWrite(outputs[outputChannel], output ? HIGH : LOW); // XXX 'PRESSED' seems to be pulling the wire HIGH, which is not my memory of how it works.
#else
  // printf("WRITING %s to outputChannel %d\n", output ? "PRESSED" : "UNPRESSED",  outputChannel);
#endif
}

class Debouncer {
  public:
    Debouncer() {
      for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
        inputState[i] = false;
        inputStateChangePending[i] = false;
        inputStateChangeTime[i] = 0;
      }
      debounceTimerMs = 100;
    }
    bool Debounce(int channel, bool input, int curTimeMs) {
      if (input == true) {
        // printf("BUTTON PRESS on channel %d\n", channel);
      }
      if (inputStateChangePending[channel]) {
        if (input == inputState[channel]) {
          // change fails debounce state.
          inputStateChangePending[channel] = false;
        } else {
          if (curTimeMs > inputStateChangeTime[channel] + debounceTimerMs) {
            // debounce success, change state
            inputState[channel] = input;
          }
        }
      } else {
        if (input != inputState[channel]) {
          inputStateChangePending[channel] = true;
          inputStateChangeTime[channel] = curTimeMs;
        }
      }
      return inputState[channel];
    }

  private:
    bool inputState[NUM_INPUT_CHANNELS];
    bool inputStateChangePending[NUM_INPUT_CHANNELS];
    int  inputStateChangeTime[NUM_INPUT_CHANNELS];
    int debounceTimerMs;

};

Debouncer debouncer;
bool inputButtonStates[NUM_INPUT_CHANNELS];

void readInputButtonStates(int curTimeMs) {
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    bool buttonState = readRawInput(i, curTimeMs);
    inputButtonStates[i] = debouncer.Debounce(i, buttonState, curTimeMs);
  }
}

bool consolidatedOutput[NUM_OUTPUT_CHANNELS];

void initIO() {
#ifdef ARDUINO
#ifdef DEBUG
  Serial.begin(9600);
#endif
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    pinMode(inputs[i], INPUT_PULLUP);
  }
  for (int j=0; j<NUM_OUTPUT_CHANNELS; j++) {
    digitalWrite(outputs[j], LOW); // making sure output starts low
    pinMode(outputs[j], OUTPUT);
  }
#endif // ARDUINO
  memset(consolidatedOutput, 0, NUM_OUTPUT_CHANNELS*sizeof(bool));
}

void buttonLoop() {
  // Read data, send to the channel controllers.
  int curTimeMs = millis();
  bool consolidatedOutputDebugCopy[NUM_OUTPUT_CHANNELS];
  memcpy(consolidatedOutputDebugCopy, consolidatedOutput, NUM_OUTPUT_CHANNELS*sizeof(bool));
  memset(consolidatedOutput, 0, NUM_OUTPUT_CHANNELS*sizeof(bool));

  readInputButtonStates(curTimeMs);

  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    controllers[i].update(inputButtonStates[i], curTimeMs);
    PlayState* playState = controllers[i].getPlayState();
    for (int j=0; j<NUM_OUTPUT_CHANNELS; j++) {
      // For the moment, if any program says that the button is pressed, it's pressed.
      if (playState->valid && playState->buttonPressed) {
        consolidatedOutput[j] = true;
      }
      playState++;
    }
  }

  for (int k=0; k<NUM_OUTPUT_CHANNELS; k++) {
    if (consolidatedOutput[k] != consolidatedOutputDebugCopy[k]) {
#ifdef ARDUINO
#ifdef DEBUG
      Serial.print(curTimeMs);
      Serial.print(": TOGGLE output ");
      Serial.print(k);
      Serial.print(" to ");
      Serial.print(consolidatedOutput[k] ? "PRESSED" : "UNPRESSED");
      Serial.print(", input on same channel was ");
      Serial.println(inputButtonStates[k] ? "PRESSED" : "UNPRESSED");
#endif // DEBUG
#else // ~ARDUINO
      printf("%d: TOGGLE output %d to %s, input on same channel was %s\n", curTimeMs, k, consolidatedOutput[k] ? "PRESSED" : "UNPRESSED", inputButtonStates[k] ? "PRESSED" : "UNPRESSED");
#endif // ~ARDUINO
    }
    writeOutput(k, consolidatedOutput[k]);
  }
}

void buttonSetup() {
  initMillis();
  initIO();
#ifdef ARDUINO
  initI2C();
  initChannelControllers();
#ifdef DEBUG
  Serial.println("Starting...");
#endif // DEBUG
#else // ~ARDUINO
  printf("Starting...\n");
#ifdef MOCK_INPUT
  inputTest.Start();
#endif
#endif // ARDUINO
}

#ifndef ARDUINO
int main(int argc, char** argv){
  printf("Doing main...\n");
  buttonSetup();

  /* This is test code - should go somewhere else with expected results. 
  printf("Input test raw state at 0 is %s\n", inputTest.GetButtonState(1, curTime + 0) ? "PRESSED" : "UNPRESSED");
  printf("Input test raw state at 95 is %s\n", inputTest.GetButtonState(1, curTime + 95) ? "PRESSED" : "UNPRESSED");
  printf("Input test raw state at 100 is %s\n", inputTest.GetButtonState(1, curTime + 100) ? "PRESSED" : "UNPRESSED");
  printf("Input test raw state at 300 is %s\n", inputTest.GetButtonState(1, curTime + 300) ? "PRESSED" : "UNPRESSED");
  printf("Input test raw state at 1000 is %s\n", inputTest.GetButtonState(1, curTime + 1000) ? "PRESSED" : "UNPRESSED");
  */
  struct timespec ts;
  ts.tv_sec = 0;             // 0 seconds
  ts.tv_nsec = 1 * 50000000;  // 1 millisecond = 1,000,000 nanoseconds
  while(millis() < 7000) {
    buttonLoop(); 
    nanosleep(&ts, NULL); // 50 ms sleep
  }
  printf("Ending!\n");
  return 0;
}
#endif // ~ARDUINO
