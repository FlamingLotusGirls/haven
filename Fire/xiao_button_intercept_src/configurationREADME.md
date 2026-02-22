# Configuration Documentation

## Channel Naming - channels.json
Each board contains eight physical channels, which control up to 8 flame effect solenoids.
In the field, it's common for solenoids to be swapped between different channels, so it
is helpful to have an abstraction that allow you to reference solenoids by name rather than by 
channel index.

The format of the channels.json file is a list of tuples, with each tuple mapping a channel 
index to a solenoid name. Not all channel indexes must be mapped - we may not use them all.

Example:
[{1,"Cockatoo1"}, {2,"Cockatoo4"}, {3, "CockatooChick1"}]


## Pattern Naming - patterns.json
A input button can be configured to run a pattern across one or more channels. The base component of
a pattern is a sequnce - a series of on/off commands coupled with timing information. A pattern is defined as a list of poofer sequences, where a poofer sequence is a triple containing the name of a pattern, the name of the solenoid to run it on, and a delay (in ms) before the pattern starts. As an example:
Example
Sequence:  {"poof", {true, 500}, {false, 200}, {false, -1}}
Pattern: {"BirdChase", ["Cockatoo1", 0, "poof"], ["Cockatoo4", 500, "poof"]}
Pattern Mapping: {0, "BirdChase}  // Button 0 triggers BirdChase

The patterns.json file contains a list of sequences, a list of patterns created from those sequences, and a list of pattern mappings