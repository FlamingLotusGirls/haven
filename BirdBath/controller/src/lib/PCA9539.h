/*
 * clsPCA9539.h
 *
 *  Created on: 27 jul. 2015
 *      Author: Nico
 */

#ifndef PCA9539_H_
#define PCA9539_H_

#if defined(ARDUINO) && ARDUINO >= 100
#include "Arduino.h"
#else
#include "WProgram.h"
#endif

#define DEBUG 1

/** enum with names of ports ED0 - ED15 */
enum
{
    pca_A0,
    pca_A1,
    pca_A2,
    pca_A3,
    pca_A4,
    pca_A5,
    pca_A6,
    pca_A7,
    pca_B0,
    pca_B1,
    pca_B2,
    pca_B3,
    pca_B4,
    pca_B5,
    pca_B6,
    pca_B7
};

//
// PCA9555 defines
//
#define NXP_INPUT 0
#define NXP_OUTPUT 2
#define NXP_INVERT 4
#define NXP_CONFIG 6

class PCA9539
{
public:
    PCA9539(uint8_t address);                      // constructor
    void pinMode(uint8_t pin, uint8_t IOMode);     // pinMode
    uint8_t digitalRead(uint8_t pin);              // digitalRead
    void digitalWrite(uint8_t pin, uint8_t value); // digitalWrite

private:
    //
    // low level methods
    //
    uint16_t I2CGetValue(uint8_t address, uint8_t reg);
    void I2CSetValue(uint8_t address, uint8_t reg, uint8_t value);

    union
    {
        struct
        {
            uint8_t _configurationRegister_low;  // low order byte
            uint8_t _configurationRegister_high; // high order byte
        };
        uint16_t _configurationRegister; // 16 bits presentation
    };
    union
    {
        struct
        {
            uint8_t _valueRegister_low;  // low order byte
            uint8_t _valueRegister_high; // high order byte
        };
        uint16_t _valueRegister;
    };
    uint8_t _address; // address of port this class is supporting
    int _error;       // error code from I2C
};

#endif /* PCA9539_H_ */