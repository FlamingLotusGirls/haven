//#define ARDUINO  // NB - predefined if in Arduino IDE
#include "button_sequence.h"

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
#include <WiFi.h>
#include <HTTPClient.h>
#include <string>   // std::string used in Program::m_name (available in ESP32 GCC toolchain)
#include "DeviceTriggers.h"
#else
#include <stdio.h>
#include <cstdint>
#include <chrono>
#include <cstring>
#include <string>   // std::string used in Program::m_name
#include <unistd.h>
#endif // ARDUINO

// Operating mode — selected by the 3-bit DIP switch.
//   DIP=7 : FollowerOnly    – output mirrors input, no triggers sent     (field test)
//   DIP=6 : TriggerOnly     – triggers sent to network, no local output  (network-only test)
//   DIP=5 : FollowerTrigger – output mirrors input AND triggers sent      (hybrid)
//   DIP=0–4 : Normal        – programs run, triggers sent                (production)
enum class OperatingMode {
  Normal,           // Programs run; triggers sent to network
  FollowerOnly,     // Output follows input directly; no triggers  (DIP=7)
  TriggerOnly,      // Triggers sent; no local solenoid output     (DIP=6)
  FollowerTrigger,  // Output follows input; triggers also sent    (DIP=5)
};

bool bFollowerOnly = false;              // True in any non-Normal mode; blocks setProgram()
static OperatingMode g_operatingMode = OperatingMode::Normal;  // Set by DIP switch in buttonLoop()

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
const uint16_t gpioInputMask[] = {0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0080, 0x0040, 0x0020, 0x0800, 0x0400, 0x0200, 0x0100};
#endif // ESP32_DEV
#endif // ARDUINO

const int NUM_INPUT_CHANNELS = 12;
const int NUM_OUTPUT_CHANNELS = 8;
static constexpr int INVALID_OUTPUT_CHANNEL = -1;

#ifdef ARDUINO
// Trigger system globals
static TriggerDevice* triggerDevice = nullptr;
static std::shared_ptr<ButtonTrigger> channelTriggers[NUM_INPUT_CHANNELS];
static bool triggerEnabled[NUM_INPUT_CHANNELS];
static String triggerNames[NUM_INPUT_CHANNELS];
#endif

// Forward declarations
static void initMillis();
#ifndef ARDUINO
uint32_t millis();
#endif
static bool readRawInput(int channelId, uint16_t gpioRawData, int curTimeMs);
static void writeOutput(int outputChannel, bool output);


/**********  UTILITY FUNCTIONS ***************/
// The Arduino libraries provide the convenience function millis(), which is the
// milliseconds since the board booted/program started. Create a version of this for
// the non-embedded debug environment.
#ifdef ARDUINO
static void initMillis() {
}
#else 
std::chrono::steady_clock::time_point start_time;
static void initMillis() {
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
      Serial.printf("!!! Total play time for program %s is %d\n", name, m_totalPlayTime);
    }

    bool IsFinished(uint32_t playTime) {
      static int s_count = 0;
      if (s_count >= 100) {
        Serial.printf("TripleBurst isFinished called, playTime %ul, m_totalPlayTime %ul\n", playTime, m_totalPlayTime);
        s_count = 0;
      }
      s_count++;
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
      return m_name.c_str();
    }

  private:
    ChannelSequence** m_sequences;
    // std::string owns a copy of the name, preventing the dangling-pointer bug
    // that occurs when Program is constructed from a local String's c_str().
    std::string m_name;
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
ChannelSequence chaseEighthOnEight(7, 3500, poof);

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
// int8_t csw_pca_read_bytes(const uint8_t reg, uint8_t* data, const uint8_t size);

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
  // Owned ChannelSequence objects so loadPatternsFromFile() can free them on reload.
  ChannelSequence** channelSeqs;   // the null-terminated pointer array passed to Program
  int channelSeqCount;             // number of live (non-null) entries in channelSeqs
  NamedProgram() : program(nullptr), channelSeqs(nullptr), channelSeqCount(0) {}
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
      Serial.println("Channel Controller Set program - follower only!");
      return;
    }
    // nullptr means "reset to Follower immediately".  Never defer this through the
    // m_nextProgram queuing path — the caller (loadPatternsFromFile) will delete the
    // old Program object right after this call, so m_program must not be left pointing
    // at it in any state, including PLAYBACK.
    if (program == nullptr) {
      m_program     = nullptr;
      m_nextProgram = nullptr;
      m_mode  = ChannelControllerMode::Follower;
      m_state = WAIT_FOR_UNPRESS;  // require button release before any new press is accepted
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

  void cancel() {
    m_nextProgram = NULL; 
    m_state = WAIT_FOR_PRESS;
    memset(m_outputState, 0, NUM_OUTPUT_CHANNELS*sizeof(PlayState));
  }

  void setTestMode(bool tf) {
    if (tf) {
      cancel();
    }
    bFollowerOnly = tf;
  }

  // Override the default output channel for this input.
  // Normally input N drives output N; call this to redirect it to a different
  // output (e.g. when the paired output has a hardware fault and a spare output
  // is available).  An invalid outputChannel value is clamped to
  // INVALID_OUTPUT_CHANNEL so the channel simply produces no output.
  void setDefaultOutputChannel(int outputChannel) {
    m_defaultOutputChannel = (outputChannel >= 0 && outputChannel < NUM_OUTPUT_CHANNELS)
                             ? outputChannel : INVALID_OUTPUT_CHANNEL;
  }

  int getDefaultOutputChannel() const {
    return m_defaultOutputChannel;
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
    if (m_mode == ChannelControllerMode::Follower || bFollowerOnly) {
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
            Serial.printf("Channel %d, start PLAYBACK\n", m_inputChannel);
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
            // Zero outputs at the top so both the "finished" and "still playing"
            // paths start from a clean slate — no stale buttonPressed values linger.
            memset(m_outputState, 0, NUM_OUTPUT_CHANNELS*sizeof(PlayState));
            int playheadTimeMs = curTimeMs - m_playbackStartMs;
            if (m_program->IsFinished(playheadTimeMs)) {
#ifdef ARDUINO
#ifdef DEBUG
              Serial.print("Channel: ");
              Serial.print(m_inputChannel);
              Serial.print(", PLAYBACK FINISHED, ");
              Serial.println(curTimeMs);
#endif
              Serial.printf("Channel: %d, PLAYBACK FINISHED, %d\n", m_inputChannel, curTimeMs);
#else
              printf("Channel: %d, PLAYBACK FINISHED, %d\n", m_inputChannel, curTimeMs);
#endif // ARDUINO
              m_state = WAIT_FOR_UNPRESS;
              if (m_nextProgram != NULL) {
                m_program = m_nextProgram;
                m_nextProgram = NULL;
              }
            } else {
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
// Mutex to protect controllers[] from concurrent access between the main loop
// (Core 1) and the ESPAsyncWebServer task (which calls setProgram via loadPatternsFromFile).
SemaphoreHandle_t g_controllersMutex = NULL;
#endif

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

static uint16_t readGPIOInput() {
#ifdef ESP32_DEV
  uint16_t input = 0;
  for (int i=0; i<NUM_INPUT_CHANNELS; i++){
    input |= digitalRead(gpioInputs[i]) << i;
  }
  return input;
#else
#ifdef PCA_9555
  // Top bit is actually output, and we don't want it in our data
  return ioex.read() & 0x7FFF;
#endif
   return 0;
#endif // ESP32_DEV
}

static int8_t readDIPSwitch(uint16_t gpioRawData) {
#ifdef PCA_9555
  // NB: parentheses are critical here — & has lower precedence than >>, so without
  // them the shifts apply to the constants, not to the masked result.
  return (((gpioRawData & 0x1000) >> 10) +
          ((gpioRawData & 0x2000) >> 12) + 
          ((gpioRawData & 0x4000) >> 14));
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
static bool readRawInput(int inputChannel, uint16_t gpioRawData, int curTimeMs) {
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

static void writeOutput(int outputChannel, bool output) {
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
  Serial.printf("WRITING %s to outputChannel %d\n", output ? "PRESSED" : "UNPRESSED",  outputChannel);
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

static void readInputButtonStates(uint16_t gpioRawData, int curTimeMs) {
  // Triggers are sent in Normal, TriggerOnly, and FollowerTrigger modes.
  const bool sendTriggers = (g_operatingMode == OperatingMode::Normal     ||
                             g_operatingMode == OperatingMode::TriggerOnly ||
                             g_operatingMode == OperatingMode::FollowerTrigger);
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    bool oldButtonState = inputButtonStates[i];
    bool buttonState = readRawInput(i, gpioRawData, curTimeMs);
    inputButtonStates[i] = debouncer.Debounce(i, buttonState, curTimeMs);
    if (inputButtonStates[i] != oldButtonState) {
      Serial.print("ButtonChange on channel ");
      Serial.print(i);
      Serial.println(oldButtonState ? ",now UNPRESSED" : ",now PRESSED");

      // TRIGGER INTEGRATION: Send trigger event if enabled for this mode
      #ifdef ARDUINO
      if (sendTriggers && triggerEnabled[i] && channelTriggers[i] != nullptr) {
        channelTriggers[i]->CheckForEventAndSend(inputButtonStates[i]);
        Serial.print("Trigger sent for channel ");
        Serial.println(i);
      }
      #endif
    }
  }
}

bool consolidatedOutput[NUM_OUTPUT_CHANNELS];

static void initIO() {
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

/*
uint8_t csw_read_pca() {
  uint16_t data = 0;
  // 0 and 1 here are the first and second input ports
  csw_pca_read_bytes(0, (uint8_t*)&data, 1);
  csw_pca_read_bytes(1, ((uint8_t*)&data) + 1, 1);
  Serial.print("PCA read returns ");
  Serial.println(data, HEX);
  Serial.println(data & 0x7FFF, HEX);
  // Note that we only use 15 of the 16 bits - the high bit is the output of the LED
  return (data & 0x7FFF);
}
*/

static uint16_t g_oldGpioRawData = 0xFFFF;
static uint8_t g_oldDipSwitch = 0;
void buttonLoop() {
  // Update connection to trigger gateway
  if (triggerDevice != nullptr) {
    triggerDevice->Update();
  }
  // Read data, send to the channel controllers.
  int curTimeMs = millis();
  
  bool consolidatedOutputDebugCopy[NUM_OUTPUT_CHANNELS];
  memcpy(consolidatedOutputDebugCopy, consolidatedOutput, NUM_OUTPUT_CHANNELS*sizeof(bool));
  memset(consolidatedOutput, 0, NUM_OUTPUT_CHANNELS*sizeof(bool));

  uint16_t gpioRawData = readGPIOInput();
  if (gpioRawData != g_oldGpioRawData) {
  // #ifdef DEBUG
    Serial.print("Data change! Old data was ");
    Serial.print(g_oldGpioRawData, BIN);
    Serial.print(", new data is ");
    Serial.println(gpioRawData, BIN);
  // #endif

    g_oldGpioRawData = gpioRawData;
  }
  // Read DIP switch to determine operating mode.
  //   DIP=7 : FollowerOnly    (output mirrors input, no triggers)
  //   DIP=6 : TriggerOnly     (triggers only, no local output)
  //   DIP=5 : FollowerTrigger (output mirrors input + triggers)
  //   DIP=0–4 : Normal        (programs run, triggers sent)
  // Detect transitions so active programs are canceled exactly once on mode change.
  uint8_t dipSwitch = readDIPSwitch(gpioRawData);
  if (g_oldDipSwitch != dipSwitch) {
    OperatingMode newMode;
    if      (dipSwitch == 7) newMode = OperatingMode::FollowerOnly;
    else if (dipSwitch == 6) newMode = OperatingMode::TriggerOnly;
    else if (dipSwitch == 5) newMode = OperatingMode::FollowerTrigger;
    else                     newMode = OperatingMode::Normal;

    if (newMode != g_operatingMode) {
      static const char* modeNames[] = {"Normal", "FollowerOnly", "TriggerOnly", "FollowerTrigger"};
      Serial.printf("Operating mode: %s -> %s (DIP=%d)\n",
                    modeNames[(int)g_operatingMode], modeNames[(int)newMode], dipSwitch);

      // On any transition away from Normal: immediately cancel in-flight programs.
      if (newMode != OperatingMode::Normal || g_operatingMode != OperatingMode::Normal) {
#ifdef ARDUINO
        if (g_controllersMutex != NULL) xSemaphoreTake(g_controllersMutex, portMAX_DELAY);
#endif
        for (int i = 0; i < NUM_INPUT_CHANNELS; i++) {
          controllers[i].cancel();
        }
#ifdef ARDUINO
        if (g_controllersMutex != NULL) xSemaphoreGive(g_controllersMutex);
#endif
      }
      // bFollowerOnly blocks setProgram() in any non-Normal mode
      bFollowerOnly = (newMode != OperatingMode::Normal);
      g_operatingMode = newMode;
    }
    g_oldDipSwitch = dipSwitch;
  }

  readInputButtonStates(gpioRawData, curTimeMs);

  // Take the mutex before accessing controllers[]. The web server task may call
  // setProgram() concurrently; portMAX_DELAY is safe here because the web handler
  // holds the mutex only for the brief setProgram() calls.
#ifdef ARDUINO
  if (g_controllersMutex != NULL) xSemaphoreTake(g_controllersMutex, portMAX_DELAY);
#endif
  for (int i=0; i<NUM_INPUT_CHANNELS; i++) {
    if (g_operatingMode == OperatingMode::TriggerOnly) {
      // Trigger-only: no local output at all — consolidatedOutput stays zeroed.
    } else if (g_operatingMode == OperatingMode::FollowerOnly ||
               g_operatingMode == OperatingMode::FollowerTrigger) {
      // Follower modes: output directly mirrors input, bypassing all program logic.
      // Programs were already canceled on the transition into this mode.
      if (i < NUM_OUTPUT_CHANNELS) {
        consolidatedOutput[i] = inputButtonStates[i];
      }
    } else {
      // Normal mode: run programs via controllers.
      controllers[i].update(inputButtonStates[i], curTimeMs);
      PlayState* playState = controllers[i].getPlayState();
      for (int j=0; j<NUM_OUTPUT_CHANNELS; j++) {
        if (playState->valid && playState->buttonPressed) {
          consolidatedOutput[j] = true;
        }
        playState++;
      }
    }
  }
#ifdef ARDUINO
  if (g_controllersMutex != NULL) xSemaphoreGive(g_controllersMutex);
#endif

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
  // An optional 3rd element [channelIndex, solenoidName, outputOverride] redirects
  // the default output channel (field repair: swap a bad output to a spare one).
  bool anyRemapped = false;
  if (doc.is<JsonArray>()) {
    JsonArray channelArray = doc.as<JsonArray>();
    for (JsonArray::iterator it = channelArray.begin(); it != channelArray.end(); ++it) {
      JsonArray mapping = *it;
      if (mapping.size() >= 2) {
        int channelIndex = mapping[0];
        String solenoidName = mapping[1].as<String>();
        
        if (channelIndex >= 0 && channelIndex < 8) {
          channelAlias[channelIndex] = solenoidName;
          Serial.print("Channel ");
          Serial.print(channelIndex);
          Serial.print(" mapped to: ");
          Serial.println(solenoidName);

          // Optional output override (3rd element).
          // Absent or null → identity mapping (input N → output N).
          int outputOverride = channelIndex;
          if (mapping.size() >= 3 && !mapping[2].isNull()) {
            outputOverride = mapping[2].as<int>();
          }
          controllers[channelIndex].setDefaultOutputChannel(outputOverride);

          if (outputOverride != channelIndex) {
            anyRemapped = true;
            Serial.print("  *** OUTPUT REMAP: input ");
            Serial.print(channelIndex);
            Serial.print(" (");
            Serial.print(solenoidName);
            Serial.print(") → output ");
            Serial.println(outputOverride);
          }
        }
      }
    }
  }
  Serial.println("Channels loaded from file successfully");
  if (anyRemapped) {
    Serial.println("*** WARNING: One or more output channel remaps are active.");
    Serial.println("*** Check the web UI channel table for details.");
  }
}

// Dynamic sequence and pattern loading from JSON files
void loadPatternsFromFile() {
  // Free any data allocated by a previous call so we don't leak on hot-reload.
  // Reset controllers to follower mode first so they don't hold dangling Program pointers.
  if (g_controllersMutex != NULL) xSemaphoreTake(g_controllersMutex, portMAX_DELAY);
  for (int i = 0; i < NUM_INPUT_CHANNELS; i++) {
    controllers[i].setProgram(nullptr);
  }
  if (g_controllersMutex != NULL) xSemaphoreGive(g_controllersMutex);

  // Free dynamic sequences (Section[] arrays)
  for (int i = 0; i < dynamicSequenceCount; i++) {
    delete[] dynamicSequences[i].sections;
    dynamicSequences[i].sections = nullptr;
    dynamicSequences[i].name = "";
  }
  dynamicSequenceCount = 0;

  // Free dynamic programs: each ChannelSequence*, the pointer array, and the Program
  for (int i = 0; i < dynamicProgramCount; i++) {
    if (dynamicPrograms[i].channelSeqs != nullptr) {
      for (int j = 0; j < dynamicPrograms[i].channelSeqCount; j++) {
        delete dynamicPrograms[i].channelSeqs[j];
        dynamicPrograms[i].channelSeqs[j] = nullptr;
      }
      delete[] dynamicPrograms[i].channelSeqs;
      dynamicPrograms[i].channelSeqs = nullptr;
      dynamicPrograms[i].channelSeqCount = 0;
    }
    delete dynamicPrograms[i].program;
    dynamicPrograms[i].program = nullptr;
    dynamicPrograms[i].name = "";
  }
  dynamicProgramCount = 0;

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
      
      // Count sections to allocate memory.
      // Allocate sectionCount + 1 so we can always write the {false, -1} sentinel that
      // Program's constructor and GetButtonStates() require to know where the array ends.
      int sectionCount = sequenceData.size();
      Section* dynamicSection = new Section[sectionCount + 1];

      int index = 0;
      for (JsonArray::iterator it = sequenceData.begin(); it != sequenceData.end(); ++it) {
        JsonArray sectionData = *it;
        if (sectionData.size() == 2) {
          dynamicSection[index].onOff = sectionData[0].as<bool>();
          dynamicSection[index].duration = sectionData[1].as<int32_t>();
          index++;
        }
      }
      // Write the required sentinel so Program's traversal loops terminate safely.
      dynamicSection[index] = {false, -1};

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
      
      // Create channel sequences for this pattern.
      // Named channelSeqArray (not dynamicSequences) to avoid shadowing the global
      // NamedSequence dynamicSequences[] array declared above.
      int sequenceCount = patternData.size();
      ChannelSequence** channelSeqArray = new ChannelSequence*[sequenceCount + 1];
      
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
              channelSeqArray[index] = channelSeq;
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
      
      channelSeqArray[index] = nullptr; // Null-terminate

      // Create program from the channel sequences
      if (index > 0 && dynamicProgramCount < MAX_DYNAMIC_PROGRAMS) {
        Program* dynamicProgram = new Program(channelSeqArray, patternName.c_str());

        // Store program and ownership of channelSeqArray so it can be freed on reload
        dynamicPrograms[dynamicProgramCount].name = patternName;
        dynamicPrograms[dynamicProgramCount].program = dynamicProgram;
        dynamicPrograms[dynamicProgramCount].channelSeqs = channelSeqArray;
        dynamicPrograms[dynamicProgramCount].channelSeqCount = index;
        dynamicProgramCount++;

        Serial.print("Created dynamic program: ");
        Serial.println(patternName);
      } else {
        // No valid channels or programs array full — free the pointer array now
        delete[] channelSeqArray;
        if (dynamicProgramCount >= MAX_DYNAMIC_PROGRAMS) {
          Serial.println("Warning: Maximum dynamic programs reached");
        }
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
      
      // Set the program for this button — take mutex since buttonLoop() may be
      // reading controllers[] on Core 1 at the same time.
      if (buttonIndex < NUM_INPUT_CHANNELS && selectedProgram != nullptr) {
        if (g_controllersMutex != NULL) xSemaphoreTake(g_controllersMutex, portMAX_DELAY);
        controllers[buttonIndex].setProgram(selectedProgram);
        if (g_controllersMutex != NULL) xSemaphoreGive(g_controllersMutex);
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

// Load trigger mappings from trigger_mappings.json
void loadTriggerMappingsFromFile(String& deviceName) {
  // Clean up any previous TriggerDevice.
  // Clear channelTriggers[] shared_ptrs first: each ButtonTrigger holds a reference
  // to its TriggerDevice, so we must release those refs before deleting the device.
  for (int i = 0; i < NUM_INPUT_CHANNELS; i++) {
    channelTriggers[i].reset();  // releases shared_ptr, may delete ButtonTrigger
  }
  if (triggerDevice != nullptr) {
    delete triggerDevice;        // kills HTTP task + queue, then destroys m_triggers
    triggerDevice = nullptr;
  }

  // Initialize trigger enabled array
  for (int i = 0; i < NUM_INPUT_CHANNELS; i++) {
    triggerEnabled[i] = false;
    triggerNames[i] = "";
  }
  
  if (!LittleFS.exists("/trigger_mappings.json")) {
    Serial.println("trigger_mappings.json not found, triggers disabled");
    return;
  }
  
  File file = LittleFS.open("/trigger_mappings.json", "r");
  if (!file) {
    Serial.println("Failed to open trigger_mappings.json");
    return;
  }
  
  // Read file into string
  String jsonString = file.readString();
  file.close();
  
  // Parse JSON
  DynamicJsonDocument doc(4096);
  DeserializationError error = deserializeJson(doc, jsonString);
  
  if (error) {
    Serial.print("trigger_mappings.json parsing failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  // Get trigger server configuration
  String triggerServerURL = doc["trigger_server"]["url"].as<String>();
  int triggerServerPort = doc["trigger_server"]["port"].as<int>();
  // String deviceName = doc["device_name"].as<String>(); // NB - I'm going to use the passed-in netname, rather than the device name read here, as the core id here
  
  Serial.println("=== Trigger Configuration ===");
  Serial.print("Server: ");
  Serial.print(triggerServerURL);
  Serial.print(":");
  Serial.println(triggerServerPort);
  Serial.print("Device: ");
  Serial.println(deviceName);
  
  // Create TriggerDevice
  triggerDevice = new TriggerDevice(deviceName, triggerServerURL, triggerServerPort);
  
  // Process channel mappings
  if (doc.containsKey("channel_to_trigger")) {
    JsonArray channelMappings = doc["channel_to_trigger"];
    for (JsonVariant channelMapping : channelMappings) {
      int channel = channelMapping["channel"].as<int>();
      String triggerName = channelMapping["trigger_name"].as<String>();
      bool enabled = channelMapping["enabled"].as<bool>();
      
      if (channel >= 0 && channel < NUM_INPUT_CHANNELS) {
        triggerEnabled[channel] = enabled;
        triggerNames[channel] = triggerName;
        
        if (enabled) {
          // Create ButtonTrigger for this channel.
          // debounceTimeMs=0: hardware debounce in readInputButtonStates() already ensures
          // CheckForEventAndSend is only called on stable state changes, so no additional
          // software debounce is needed here.
          channelTriggers[channel] = triggerDevice->AddButtonTrigger(triggerName, false, 0);
          Serial.print("Channel ");
          Serial.print(channel);
          Serial.print(" -> Trigger: ");
          Serial.println(triggerName);
        }
      }
    }
  }

  Serial.println("=== Trigger Configuration Complete ===");
}
#endif


void buttonSetup(String& netName) {
  sleep(1);
  initMillis();
  initIO();
#ifdef ARDUINO
  g_controllersMutex = xSemaphoreCreateMutex();
  if (g_controllersMutex == NULL) {
    Serial.println("ERROR: Failed to create controllers mutex!");
  }
  Serial.println("Trying to set up i2c");
  initI2C();
  // Try to load configuration from files first, fallback to hardcoded
  if (LittleFS.begin()) {
    loadChannelsFromFile();  // Load channel aliases
    loadPatternsFromFile();  // Load pattern mappings
    loadTriggerMappingsFromFile(netName); // Load trigger mappings
  } else {
    // initChannelControllers(); // Use hardcoded patterns
  }
  // Initial read of DIP switches and buttons...
  g_oldGpioRawData = readGPIOInput();
  g_oldDipSwitch = readDIPSwitch(g_oldGpioRawData);
  Serial.println("Buttons Starting...");
  Serial.print("  Initial DIP switch read is ");
  Serial.println(g_oldDipSwitch, BIN);
  Serial.print("  Initial GPIO read is ");
  Serial.println(g_oldGpioRawData, BIN);

  // Set initial operating mode from DIP switch
  if      (g_oldDipSwitch == 7) g_operatingMode = OperatingMode::FollowerOnly;
  else if (g_oldDipSwitch == 6) g_operatingMode = OperatingMode::TriggerOnly;
  else if (g_oldDipSwitch == 5) g_operatingMode = OperatingMode::FollowerTrigger;
  else                          g_operatingMode = OperatingMode::Normal;
  bFollowerOnly = (g_operatingMode != OperatingMode::Normal);
  Serial.printf("Initial operating mode: %d (DIP=%d)\n", (int)g_operatingMode, g_oldDipSwitch);

#else // ~ARDUINO
  printf("Buttons Starting...\n");
#ifdef MOCK_INPUT
  inputTest.Start();
#endif
#endif // ARDUINO
}

/*
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
*/


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
