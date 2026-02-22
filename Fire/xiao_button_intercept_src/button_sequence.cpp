//#define ARDUINO  // NB - predefined if in Arduino IDE

// #define ESP32_DEV // Two configs - esp32 dev board, with all i/o onboard, or xiao with io on pca9555
#ifndef ESP32_DEV 
#define PCA_9555
#endif

#ifdef ARDUINO
#define ESP32 1  // NB - AsyncHttp library requires this
#include <Wire.h>
#ifdef PCA_9555
#include <PCA95x5.h>
#endif // PCA9555
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <AsyncTCP.h>
#include <AsyncHTTPRequest_Generic.h>   // https://github.com/khoih-prog/AsyncHTTPRequest_Generic
#else
#include <stdio.h>
#include <cstdint>
#include <chrono>
#include <cstring>
#include <unistd.h>
#endif // ARDUINO

// I need a way to swap things over in to follower mode for basic testing.
bool bFollowerOnly = true;

// Please only define on of these (if any). They set up the special sequences on the specific
// flame control boxes. Perhaps one day I will have an ESP32 rather than a trinketPro on the board,
// and I'll be able to dynamically update config files. That day is not today.


// #define PERCH
#define COCKATOO

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
#ifdef ESP32_DEV
const int outputs[] = {4, 5, 6, 7, 15, 16, 17, 18};
const int gpioInputs[] = {1, 2, 42, 41, 40, 39, 38, 37, 36, 35, 48, 47};
// other bits - D8, D9-D14
#else  // ie, XIAO with PCA9555
const int outputs[] = {D7, D8, D9, D10, D0, D3, D2, D1}; // XXX D9 is strapping; problematic for initial output.
// Note with input mask - 0x0001 - 0x0080 are on the first port, which is completely used for input 0x0800 - 0x0100 are second port
const uint16_t gpioInputMask[] = {0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080, 0x0800, 0x0400, 0x0200, 0x0100};
#endif // ESP32_DEV
#endif // ARDUINO

const int NUM_INPUT_CHANNELS = 12;
const int NUM_OUTPUT_CHANNELS = 8;
static constexpr int INVALID_OUTPUT_CHANNEL = -1;

// Forward declarations
void initMillis();
#ifndef ARDUINO
uint32_t millis();
#endif
bool readRawInput(int channelId, uint16_t gpioRawData, int curTimeMs);
void writeOutput(int outputChannel, bool output);


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
        if (outputChannel != INVALID_OUTPUT_CHANNEL) {
          playState[outputChannel].buttonPressed = output;
          playState[outputChannel].valid = true;
        }
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

// For chase - starting at different times
Section poof[] = {{true, 500},{false, 200}, {false, -1}};
Section longPoof[] = {{true, 1000}, {false, 200}, {false, -1}};

// XXX - There *may* be a way, avoiding templates, to initialize arrays in a nicer-looking way
// than this. I do not know what it is. (I'm avoiding templates because I don't want to create any
// sort of templates on a very memory limited embedded device).
ChannelSequence universalJDVBird(-1, 0, JDVBird);
ChannelSequence universalChirpChirp(-1, 0, chirpChirp);
ChannelSequence universalPoof(-1, 0, poof);
ChannelSequence universalLongPoof(-1, 0, longPoof);

ChannelSequence* universalJDVBirdArray[] = {&universalJDVBird, NULL};
ChannelSequence* universalChirpChirpArray[] = {&universalChirpChirp, NULL};
ChannelSequence* universalPoofArray[] = {&universalPoof, NULL};
ChannelSequence* universalLongPoofArray[] = {&universalLongPoof, NULL};

Program JDVBirdProgram(universalJDVBirdArray, "JDVBird");
Program chirpChirpProgram(universalChirpChirpArray, "ChirpChirp");
Program poofProgram(universalPoofArray, "Poof");
Program longPoofProgram(universalLongPoofArray, "LongPoof");

ChannelSequence thisThenThatJDVBird(4, 0, JDVBird);
ChannelSequence thisThenThatChirpChirp(5, 100, chirpChirp);

ChannelSequence* thisThenThatArray[] = {&thisThenThatJDVBird, &thisThenThatChirpChirp, NULL};
Program thisThenThatProgram(thisThenThatArray, "ThisAndThat");

ChannelSequence* stdAndOtherArray[] = {&thisThenThatJDVBird, &universalChirpChirp, NULL};
Program stdAndOtherProgram(stdAndOtherArray, "StdAndOther");

#ifdef COCKATOO
ChannelSequence chaseFirst(7, 0, poof);
ChannelSequence chaseSecond(4, 500, poof);
ChannelSequence chaseThird(3, 1000, poof);
ChannelSequence chaseFourth(0, 1500, poof);
#else
#ifdef PERCH
ChannelSequence chaseFirst(7, 0, poof);
ChannelSequence chaseSecond(6, 500, poof);
ChannelSequence chaseThird(5, 1000, poof);
ChannelSequence chaseFourth(4, 1500, poof);
#endif //PERCH
#endif //COCKATOO

ChannelSequence chaseFirstOnOne(7, 0, poof);
ChannelSequence chaseSecondOnTwo(1, 500, poof);
ChannelSequence chaseThirdOnThree(2, 1000, poof);
ChannelSequence chaseFourthOnFour(3, 1500, poof);
ChannelSequence chaseFifthOnFive(4, 2000, poof);
ChannelSequence chaseSixthOnSix(5, 2500, poof);
ChannelSequence chaseSeventhOnSeven(6, 3000, poof);
ChannelSequence chaseEigthOnEight(7, 3500, poof);

ChannelSequence poof1(0, 0, poof);
ChannelSequence poof2(1, 0, poof);
ChannelSequence poof3(2, 0, poof);
ChannelSequence poof4(3, 0, poof);
ChannelSequence poof5(4, 0, poof);
ChannelSequence poof6(5, 0, poof);
ChannelSequence poof7(6, 0, poof);
ChannelSequence poof8(7, 0, poof);

ChannelSequence longPoof1(0, 0, longPoof);
ChannelSequence longPoof2(1, 0, longPoof);
ChannelSequence longPoof3(2, 0, longPoof);
ChannelSequence longPoof4(3, 0, longPoof);
ChannelSequence longPoof5(4, 0, longPoof);
ChannelSequence longPoof6(5, 0, longPoof);
ChannelSequence longPoof7(6, 0, longPoof);
ChannelSequence longPoof8(7, 0, longPoof);

#ifdef  COCKATOO
ChannelSequence* allPoofArray[] = {&poof8, &poof5, &poof4, &poof1, NULL};
ChannelSequence* chaseArray[] = {&chaseFirst, &chaseSecond, &chaseThird, &chaseFourth, NULL};
#else 
#ifdef PERCH
ChannelSequence* allPoofArray[] = {&longPoof8, &longPoof7, &longPoof6, &longPoof5,  NULL};
ChannelSequence* chaseArray[] = {&chaseFirst, &chaseSecond, &chaseThird, &chaseFourth, NULL};
#else
ChannelSequence* chaseArray[] = {&chaseFirstOnOne, &chaseSecondOnTwo, &chaseThirdOnThree, &chaseFourthOnFour, &chaseFifthOnFive, 
                                 &chaseSixthOnSix, &chaseSeventhOnSeven, &chaseEighthOnEight, NULL};
ChannelSequence* allPoofArray[] = {&poof1, &poof2, &poof3, &poof4, &poof5, &poof6, &poof7, &poof8, NULL};
#endif // PERCH
#endif // COCKATOO

Program chaseProgram(chaseArray, "Chase");
Program allPoofProgram(allPoofArray, "AllPoof");


// 8 possible programs, from 3 bit switch on the board
Program* programs[8] = {NULL, &JDVBirdProgram, &chirpChirpProgram, &chaseProgram, &allPoofProgram, &longPoofProgram, &poofProgram, &stdAndOtherProgram};

// XXX Test code for trying to understand why the PCA555 can't be read
int8_t csw_pca_read_bytes(const uint8_t reg, uint8_t* data, const uint8_t size);

#ifdef ARDUINO
// Storage for dynamically loaded sequences and programs
struct NamedSequence {
  String name;
  Section* sections;
  NamedSequence() : sections(nullptr) {}
};

struct NamedProgram {
  String name;
  Program* program;
  NamedProgram() : program(nullptr) {}
};

const int MAX_DYNAMIC_SEQUENCES = 16;
const int MAX_DYNAMIC_PROGRAMS = 16;

NamedSequence dynamicSequences[MAX_DYNAMIC_SEQUENCES];
NamedProgram dynamicPrograms[MAX_DYNAMIC_PROGRAMS];
int dynamicSequenceCount = 0;
int dynamicProgramCount = 0;

// Helper function to find a dynamic sequence by name
Section* findDynamicSequence(const String& name) {
  for (int i = 0; i < dynamicSequenceCount; i++) {
    if (dynamicSequences[i].name == name) {
      return dynamicSequences[i].sections;
    }
  }
  return nullptr;
}

// Helper function to find a dynamic program by name
Program* findDynamicProgram(const String& name) {
  for (int i = 0; i < dynamicProgramCount; i++) {
    if (dynamicPrograms[i].name == name) {
      return dynamicPrograms[i].program;
    }
  }
  return nullptr;
}
#endif


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
    // If the input channel idx can't be paired with an output channel, set the default output to
    // INVALID_OUTPUT_CHANNEL (-1).
    m_defaultOutputChannel = m_inputChannel < NUM_OUTPUT_CHANNELS ? m_inputChannel : INVALID_OUTPUT_CHANNEL;
    memset(m_outputState, 0, NUM_OUTPUT_CHANNELS*sizeof(PlayState));
  }

  void setProgram(Program* program) {
    if (bFollowerOnly) {
      return;
    }
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
    if (buttonPressed) {
      /*
      Serial.print("Button press received for program listening on channel ");
      Serial.print(m_inputChannel);
      Serial.print(", mode is ");
      Serial.println((int)m_mode);
      */
    }
    if (m_mode == ChannelControllerMode::Follower) {
      if (m_defaultOutputChannel != INVALID_OUTPUT_CHANNEL) {
        m_outputState[m_defaultOutputChannel].valid = true;
        m_outputState[m_defaultOutputChannel].buttonPressed = buttonPressed;
        if (buttonPressed) {
            // Serial.print("Button press received for program listening on channel ");
            // Serial.println(m_inputChannel);
        }
      }
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

// Global channel aliases - initialized with default names, loaded from file
#ifdef ARDUINO
String channelAlias[8] = {
  "Channel 0", "Channel 1", "Channel 2", "Channel 3",
  "Channel 4", "Channel 5", "Channel 6", "Channel 7"
};
#else
const char* channelAlias[8] = {
  "Channel 0", "Channel 1", "Channel 2", "Channel 3",
  "Channel 4", "Channel 5", "Channel 6", "Channel 7"
};
#endif

#ifdef ARDUINO
#ifdef PCA_9555
const int PCA9555_ADDRESS = 0x20;
PCA9555 ioex;
#endif

void initI2C() {
  Wire.begin();
#ifdef PCA_9555
  ioex.attach(Wire, PCA9555_ADDRESS);
  ioex.polarity(PCA95x5::Polarity::ORIGINAL_ALL);
  ioex.direction(PCA95x5::Direction::IN_ALL);
  ioex.direction(PCA95x5::Port::P17, PCA95x5::Direction::OUT); // All input except for an LED
#endif
}

uint16_t readGPIOInput() {
#ifdef ESP32_DEV
  uint16_t input = 0;
  for (int i=0; i<NUM_INPUT_CHANNELS; i++){
    input |= digitalRead(gpioInputs[i]) << i;
  }
  return input;
#else
#ifdef PCA_9555
  return ioex.read();
#endif
   return 0;
#endif // ESP32_DEV
}

int8_t readDIPSwitch(uint16_t gpioRawData) {
#ifdef PCA_9555
  return ((gpioRawData & 0x1000 >> 10) +
           (gpioRawData & 0x2000 >> 12) + 
           (gpioRawData & 0x4000 >> 14));
#else 
  return 0; // XXX Not sure what outputs I'd use for the dip switch with an ESP DEV Board
#endif 
}
#endif // ARDUINO


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
bool readRawInput(int inputChannel, uint16_t gpioRawData, int curTimeMs) {
#ifdef ARDUINO
#ifdef ESP32_DEV
  bool input = gpioRawData & (1 << inputChannel);
#else
  uint16_t gpioChannelMask = gpioInputMask[inputChannel];
  bool input = gpioRawData & gpioChannelMask;
#endif // ESP32_DEV
  // NB - PRESSED is when the pin is held LOW, hence the negation
  return !input; 
#else // Not arduino; running tests
  return inputTest.GetButtonState(inputChannel, curTimeMs);
#endif
}

void setLEDState(bool onOff) {
#ifdef ARDUINO
#ifdef PCA_9555
  bool ret = false;
  ret = ioex.write(PCA95x5::Port::P17, onOff ? PCA95x5::Level::H : PCA95x5::Level::L);
  if (!ret) {
    Serial.println("SetLEDState write fails");
  }
#endif
#endif // ARDUINO
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
// XXX also need to set up the 5555 pins as output
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

void readInputButtonStates(uint16_t gpioRawData, int curTimeMs) {
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    bool oldButtonState = inputButtonStates[i];
    bool buttonState = readRawInput(i, gpioRawData, curTimeMs);
    inputButtonStates[i] = debouncer.Debounce(i, buttonState, curTimeMs);
    if (inputButtonStates[i] != oldButtonState) {
      Serial.print("ButtonChange on channel ");
      Serial.print(i);
      Serial.println(oldButtonState ? ",now UNPRESSED" : ",now PRESSED");
    }
    // XXX if button state change, send udp packet to ... somewhere
  }
}

bool consolidatedOutput[NUM_OUTPUT_CHANNELS];

void initIO() {
#ifdef ARDUINO
#ifdef ESP32_DEV
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    pinMode(gpioInputs[i], INPUT_PULLUP);
  }
#endif // ESP32_DEV
  for (int j=0; j<NUM_OUTPUT_CHANNELS; j++) {   
    digitalWrite(outputs[j], LOW); // making sure output starts low
    pinMode(outputs[j], OUTPUT);
  }
#endif // ARDUINO
  memset(consolidatedOutput, 0, NUM_OUTPUT_CHANNELS*sizeof(bool));
}

uint8_t csw_read_pca() {
  uint16_t data = 0;
  // 0 and 1 here are the first and second input ports
  csw_pca_read_bytes(0, (uint8_t*)&data, 1);
  csw_pca_read_bytes(1, ((uint8_t*)&data) + 1, 1);
  Serial.print("PCA read returns ");
  Serial.println(data, BIN);
  return data;
}

uint16_t oldGpioRawData = 0xFFFF;
int oldTimeMs = 0;
bool ledState = true;
void buttonLoop() {
  // Read data, send to the channel controllers.
  int curTimeMs = millis();
  if (curTimeMs > oldTimeMs + 1000) {
    oldTimeMs = curTimeMs;
    ledState = !ledState;
    setLEDState(ledState);
    Serial.println("Blink!!!");
    csw_read_pca();
    uint16_t libPca = readGPIOInput();
    Serial.print("PCA Library Reads: ");
    Serial.println(libPca, BIN);
  }
  
  bool consolidatedOutputDebugCopy[NUM_OUTPUT_CHANNELS];
  memcpy(consolidatedOutputDebugCopy, consolidatedOutput, NUM_OUTPUT_CHANNELS*sizeof(bool));
  memset(consolidatedOutput, 0, NUM_OUTPUT_CHANNELS*sizeof(bool));

  uint16_t gpioRawData = readGPIOInput();
  if (gpioRawData != oldGpioRawData) {
  // #ifdef DEBUG
    Serial.print("Data change! Old data was ");
    Serial.print(oldGpioRawData, BIN);
    Serial.print(", new data is ");
    Serial.println(gpioRawData, BIN);
  // #endif
    // Send async http post to main pi...

    oldGpioRawData = gpioRawData;
  }
  readInputButtonStates(gpioRawData, curTimeMs);

  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    controllers[i].update(inputButtonStates[i], curTimeMs);
    PlayState* playState = controllers[i].getPlayState();
    for (int j=0; j<NUM_OUTPUT_CHANNELS; j++) {
      // For the moment, if any program says that the button is pressed, it's pressed.
      if (playState->valid && playState->buttonPressed) {
        // Serial.print("Consolidated button press on output channel ");
        // Serial.println(j);
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

// Load channel aliases from channels.json file
#ifdef ARDUINO
void loadChannelsFromFile() {
  // Initialize with default names first
  for (int i = 0; i < 8; i++) {
    channelAlias[i] = "Channel " + String(i);
  }
  
  if (!LittleFS.exists("/channels.json")) {
    Serial.println("channels.json not found, using default channel names");
    return;
  }
  
  File file = LittleFS.open("/channels.json", "r");
  if (!file) {
    Serial.println("Failed to open channels.json");
    return;
  }
  
  // Read file into string
  String jsonString = file.readString();
  file.close();
  
  // Parse JSON
  DynamicJsonDocument doc(4096);
  DeserializationError error = deserializeJson(doc, jsonString);
  
  if (error) {
    Serial.print("channels.json parsing failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  // Process channel mappings - expecting array of [channelIndex, solenoidName]
  if (doc.is<JsonArray>()) {
    JsonArray channelArray = doc.as<JsonArray>();
    for (JsonArray::iterator it = channelArray.begin(); it != channelArray.end(); ++it) {
      JsonArray mapping = *it;
      if (mapping.size() == 2) {
        int channelIndex = mapping[0];
        String solenoidName = mapping[1].as<String>();
        
        if (channelIndex >= 0 && channelIndex < 8) {
          channelAlias[channelIndex] = solenoidName;
          Serial.print("Channel ");
          Serial.print(channelIndex);
          Serial.print(" mapped to: ");
          Serial.println(solenoidName);
        }
      }
    }
  }
  Serial.println("Channels loaded from file successfully");
}

// Dynamic sequence and pattern loading from JSON files
void loadPatternsFromFile() {
  if (!LittleFS.exists("/patterns.json")) {
    Serial.println("patterns.json not found, using hardcoded patterns");
    return;
  }
  
  File file = LittleFS.open("/patterns.json", "r");
  if (!file) {
    Serial.println("Failed to open patterns.json");
    return;
  }
  
  // Read file into string
  String jsonString = file.readString();
  file.close();
  
  // Parse JSON
  DynamicJsonDocument doc(8192); // Adjust size as needed
  DeserializationError error = deserializeJson(doc, jsonString);
  
  if (error) {
    Serial.print("JSON parsing failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  // First, load sequences from JSON
  if (doc.containsKey("sequences")) {
    JsonObject sequences = doc["sequences"];
    for (JsonPair sequencePair : sequences) {
      if (dynamicSequenceCount >= MAX_DYNAMIC_SEQUENCES) {
        Serial.println("Warning: Maximum dynamic sequences reached");
        break;
      }
      
      String sequenceName = sequencePair.key().c_str();
      JsonArray sequenceData = sequencePair.value().as<JsonArray>();
      
      // Count sections to allocate memory
      int sectionCount = sequenceData.size();  
      Section* dynamicSection = new Section[sectionCount];
      
      int index = 0;
      for (JsonArray::iterator it = sequenceData.begin(); it != sequenceData.end(); ++it) {
        JsonArray sectionData = *it;
        if (sectionData.size() == 2) {
          dynamicSection[index].onOff = sectionData[0].as<bool>();
          dynamicSection[index].duration = sectionData[1].as<int32_t>();
          index++;
        }
      }
      
      // Store in the dynamic sequences array
      dynamicSequences[dynamicSequenceCount].name = sequenceName;
      dynamicSequences[dynamicSequenceCount].sections = dynamicSection;
      dynamicSequenceCount++;
      
      Serial.print("Loaded sequence: ");
      Serial.print(sequenceName);
      Serial.print(" with ");
      Serial.print(sectionCount);
      Serial.println(" sections");
    }
  }
  
  // Then load patterns from JSON
  if (doc.containsKey("patterns")) {
    JsonObject patterns = doc["patterns"];
    for (JsonPair patternPair : patterns) {
      String patternName = patternPair.key().c_str();
      JsonArray patternData = patternPair.value().as<JsonArray>();
      
      Serial.print("Loading pattern: ");
      Serial.println(patternName);
      
      // Create channel sequences for this pattern
      int sequenceCount = patternData.size();
      ChannelSequence** dynamicSequences = new ChannelSequence*[sequenceCount + 1];
      
      int index = 0;
      for (JsonArray::iterator it = patternData.begin(); it != patternData.end(); ++it) {
        JsonArray channelData = *it;
        if (channelData.size() == 3) {
          String channelName = channelData[0].as<String>();
          int delayMs = channelData[1].as<int>();
          String sequenceName = channelData[2].as<String>();
          
          // Find channel index by name
          int channelIndex = -1;
          for (int i = 0; i < 8; i++) {
            if (channelAlias[i] == channelName) {
              channelIndex = i;
              break;
            }
          }
          
          if (channelIndex >= 0) {
            // Try to find dynamic sequence first, then fall back to hardcoded
            Section* sequenceSection = findDynamicSequence(sequenceName);
            
            if (sequenceSection == nullptr) {
              // Fall back to hardcoded sequences
              if (sequenceName == "poof") {
                sequenceSection = poof;
              } else if (sequenceName == "quick_burst") {
                sequenceSection = chirpChirp; // Use existing sequence as placeholder
              } else if (sequenceName == "slow_flame") {
                sequenceSection = longPoof; // Use existing sequence as placeholder
              }
            }
            
            if (sequenceSection != nullptr) {
              ChannelSequence* channelSeq = new ChannelSequence(channelIndex, delayMs, sequenceSection);
              dynamicSequences[index] = channelSeq;
              index++;
              
              Serial.print("  Channel: ");
              Serial.print(channelName);
              Serial.print(" (index ");
              Serial.print(channelIndex);
              Serial.print("), delay: ");
              Serial.print(delayMs);
              Serial.print(", sequence: ");
              Serial.println(sequenceName);
            } else {
              Serial.print("  Warning: Sequence '");
              Serial.print(sequenceName);
              Serial.println("' not found");
            }
          } else {
            Serial.print("  Warning: Channel name '");
            Serial.print(channelName);
            Serial.println("' not found in channel aliases");
          }
        }
      }
      
      dynamicSequences[index] = nullptr; // Null terminate
      
      // Create program from dynamic sequences
      if (index > 0 && dynamicProgramCount < MAX_DYNAMIC_PROGRAMS) {
        Program* dynamicProgram = new Program(dynamicSequences, patternName.c_str());
        
        // Store it in the dynamic programs array
        dynamicPrograms[dynamicProgramCount].name = patternName;
        dynamicPrograms[dynamicProgramCount].program = dynamicProgram;
        dynamicProgramCount++;
        
        Serial.print("Created dynamic program: ");
        Serial.println(patternName);
      } else if (dynamicProgramCount >= MAX_DYNAMIC_PROGRAMS) {
        Serial.println("Warning: Maximum dynamic programs reached");
      }
    }
  }
  
  // Load channel mappings for pattern_mappings
  if (doc.containsKey("pattern_mappings")) {
    JsonObject mappings = doc["pattern_mappings"];
    for (JsonPair kv : mappings) {
      int buttonIndex = String(kv.key().c_str()).toInt();
      String patternName = kv.value().as<String>();
      
      // Find matching program by name - check hardcoded programs first, then dynamic programs
      Program* selectedProgram = nullptr;
      
      // Check hardcoded programs first
      for (int i = 0; i < 8; i++) {
        if (programs[i] != nullptr && strcmp(programs[i]->GetName(), patternName.c_str()) == 0) {
          selectedProgram = programs[i];
          break;
        }
      }
      
      // If not found in hardcoded programs, check dynamic programs
      if (selectedProgram == nullptr) {
        selectedProgram = findDynamicProgram(patternName);
      }
      
      // Set the program for this button
      if (buttonIndex < NUM_INPUT_CHANNELS && selectedProgram != nullptr) {
        controllers[buttonIndex].setProgram(selectedProgram);
        Serial.print("Mapped button ");
        Serial.print(buttonIndex);
        Serial.print(" to pattern ");
        Serial.println(patternName);
      } else {
        Serial.print("Warning: Could not find or map pattern '");
        Serial.print(patternName);
        Serial.print("' to button ");
        Serial.println(buttonIndex);
      }
    }
  }
  
  Serial.println("Patterns loaded from file successfully");
}
#endif

void buttonSetup() {
  sleep(1);
  initMillis();
  initIO();
#ifdef ARDUINO
  Serial.println("Trying to set up i2c");
  initI2C();
  // Try to load configuration from files first, fallback to hardcoded
  if (LittleFS.begin()) {
    loadChannelsFromFile();  // Load channel aliases
    loadPatternsFromFile();  // Load pattern mappings
  } else {
    // initChannelControllers(); // Use hardcoded patterns
  }
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


// XXX Test code for trying to understand why the PCA555 can't be read
int8_t csw_pca_read_bytes(const uint8_t reg, uint8_t* data, const uint8_t size) {
  const uint8_t addr =  PCA9555_ADDRESS;
  int ret;
  // Single byte write to the device - register addr
  Wire.beginTransmission(addr);
  ret = Wire.write(reg);
  if (ret != 1) {
    Serial.print("Wire write register returns unexpected value: ");
    Serial.println(ret);
  }
  ret = Wire.endTransmission(false);
  if (ret != 0) {
    Serial.print("End transmission returns error: ");
    Serial.println(ret);
  }
  Wire.requestFrom(addr, size);
  int8_t count = 0;
  while (Wire.available()) data[count++] = Wire.read();
  return count;
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
