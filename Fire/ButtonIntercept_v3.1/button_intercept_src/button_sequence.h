#ifndef BUTTON_SEQUENCE_H
#define BUTTON_SEQUENCE_H

#ifdef ARDUINO
#include <Arduino.h>
#endif

// Function declarations for button_sequence.cpp
void buttonSetup(String& netname);
void buttonLoop();
void loadPatternsFromFile();
bool registerTriggerDevice();

#endif // BUTTON_SEQUENCE_H
