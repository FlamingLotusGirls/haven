+Bootloader Changes

In the current version of the button intercept, I'm using a Trinket Pro. (There's no good
reason for this; I just had several lying around from a project years back).

The TrinketPro has just *barely* enough IO ports for what I'm trying to do; I end up using
all available ports. That includes the port associated with flashing the LED, which happens
during the startup bootloader sequence.

If I had had more foresight, or the gods had smiled on me, I would have tied the LED pin
physically to an input rather than an output. Sadly, this was not the case, and the
standard trinket pro bootloader, innocently trying to flash an LED during boot, also signals
to the main board to open a solenoid and let out the fire.

As a safety issue, this is not something we can tolerate. Initially I just refused to attach
a solenoid to that output channel, but that a) reduces the number of solenoids each board
can support, and b) is hardly foolproof - anyone could hook up that channel without realizing
that it was a danger.

My solution to the problem has been to change the bootloader so it doesn't go into a searching
mode during boot that causes it to flash the LED. This is the solution suggested by GitHub
user beargun (https://github.com/beargun/Adafruit-Trinket-Gemma-Bootloader/commit/4451cecf7ebcce8abb9f5a1e9c8c9ab3fe591a3d).
He/She is checking a register to see whether we've rebooted because we've pulled the reset pin,
and only doing the extended bootloader in that situation.

This seems to work great. Using his code as inspiration, I modified the official TrinketPro bootloader
https://github.com/adafruit/Adafruit_ProTrinket_Bootloader
The main.c file is the revised file for that repo. If you want to use it, download the
repo, replace main.c, and run make flash. This will both make the file and download to the trinket
(assuming you have your trinket set up for SPI programming access (I have a Sparkfun pocket programmer
that I use, and you can manually connect the pins on the programmer header to the appropriate pins
on the Trinket Pro.)
