# haven - BirdBath
Code supporting the bird bath
Please note that the bird bath control technology is based on
LightCurve, developed by Sam Cooler and Sequoia Alexander

## Beertaps control

The "beertaps" are two sets of three beer taps. The sliding liquid valve has been replaced
by custom designed and printed parts. The three parts in each beertap is a "plunger", which
moves with the handle back and forth through the body and throad. It has a small hole in the
"tongue" which fits around a linear potentiometer (Digikey 15mm). The linear potentiometer
is 20Kohm. It sits in a small holder, precisely made, with two groves - this is the "fader holder".
The final part is the "beer nut" which fits precisely around a 7/8 standard american beer
fitting (throat). There are two fusion files, because the "holder" and "beernut" fit together
precisely so are two components of one design.

The linear potentiometer has three wires: V+, GND, WIPER. V+ and GND are +3.3V. the Wiper is a value
between 0 and 3.3V depending on position. To test, you can check resistance: 20kohms, or a percentage
of that. In order to measure the location, an ADS1115 from Adafruit ( product number 1085 ) is used.
Due to concerns about run length and interferance, the ADS1115 is run in differential mode.
Therefore there are 8 wires from the birdbath where the ADS1115 is, and the keg with the taps.

For exmplicity, ethernet was chosen. One pair as V+ GND, then the other three pairs as WIPER and GND(return).

This requires 3 ADS1115. The Adafruit build allows 4 on an I2C by using the address pins.
A custom made box has two RJ45 (one to each keg) and I2C to the PI (connected the standard way).

The software component to measure the values is written with three processes, one for each
ADS1115. That's because of the nature of I2C, you can't have overlapping requests. The amount of time
the ADS1115 takes to read is 8ms. If we polled all 6, that would add up to unpleasant response.
But we can't overlap all of them. Therefore we have one Python process for each. It will read channel 1
and channel 2 in alternation, as fast as possible, then put a measurement on an IPC queue that will be
picked up by LightCurve.

The Adafruit ADS1115 python libraries are used.

