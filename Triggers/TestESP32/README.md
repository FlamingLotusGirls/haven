# Trigger POC for ESP32

This is sample code for creating triggers on an ESP32. It is largely straight forward,
but *does* make use of LittleFS for configuration file storage.

In order to use LittleFS you will need to install the extension in the Arduino IDE.
See https://randomnerdtutorials.com/arduino-ide-2-install-esp32-littlefs/. This involves
downloading a .vsix file and putting it in the plugins directory of your ArduinoIDE
directory.

Once that's done, you can upload any files in the data directory of your project by
using the command palette (ctrl-shift-p, or cmd-shift-p on Mac) and choosing 'Upload
to LittleFS'. *Any* serial connections must be closed (close the Serial monitor windows!)
or the plugin will be unable to download.

## Other Annoyances
The code is meant for the ESP32s3, but it will run on an ESP32c3 if you have those around.
However, the two ESPs have different ways of sleeping, so if you're running on the c3,
comment out #define SLEEP_ON_IDLE
