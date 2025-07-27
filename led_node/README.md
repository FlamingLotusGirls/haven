# How to attach the VSCode Debugger code running on the Raspberry Pi Pico

## Requirements

1. Raspberry Pi Pico ([RP2040](https://www.raspberrypi.com/documentation/microcontrollers/silicon.html#rp2040))

2. [Raspberry Pi Debug Probe](https://www.raspberrypi.com/documentation/microcontrollers/debug-probe.html)

3. Macbook Pro (Apple M2 Pro) running MacOS Sequoia 15.5.

4. VSCode June 2025 (version 1.102)

5. [Debugger for probe-rs](https://marketplace.visualstudio.com/items?itemName=probe-rs.probe-rs-debugger) for VSCode

This debugging code might work on a different stack as well, but this is the only one that has been tested.

## Steps

1. Set a breakpoint, if desired.
2. On the `Run and Debug` tab in VSCode, select `probe-rs-debug` launch configuration.
3. Press F5 to start debugging!
