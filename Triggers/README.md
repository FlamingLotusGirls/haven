# Haven Triggers

## Introduction
Haven introduces a system of event passing between distributed services, intended to allow
user actions (such as a button push, a slider value change, or a motion) to be distributed 
to various services that cause changes to the sculpture (such as poof a flame, make a sound,
change the lights). These events are called TriggerEvents, and the system as a whole is 
called the Trigger System

## Trigger System - Core Architecture
There are three main parts of the Trigger System:
- DeviceTriggerManager. These objects are responsible for detecting the events that cause
TriggerEvents, and sending those events to the central switchboard, the Trigger Gateway. 
A DeviceTriggerManager is usually instatiated on some embedded device, such as an ESP32. See the ESP32
DeviceTrigger library in this directory.
- Triggers. An abstract representation of the physical object that will cause the TriggerEvent. 
Triggers come in three types - ButtonTrigger (think on/off switch), DiscreteTrigger (think knob
with distinct settings), ContinuousTrigger (think slider), and OneShotTrigger (think motion detector).
A DeviceTriggerManager will manage one or more Triggers.
- Trigger Gateway. This is a service that receives information about Triggers and TriggerEvents, 
and publishes that information to other services. Each DeviceTriggerManager will register its 
Triggers with the TriggerGateway, and will send TriggerEvent data to the gateway when an event
is detected. Services that wish to use TriggerEvents can query the Trigger Gateway for available
Triggers, and can register to receive TriggerEvents from the Gateway.
- Sculpture Services. These are service that use the TriggerEvents to do something on the sculpture.
Key services include the Flame Server, the Sound Server, and Chromatik (the lighting server),
although Chromatik may be configured to handle fire and sound as well as lighting.

## System Details

### Triggers
These are at the heart of the system - those objects (buttons, switches, sliders, etc) that generate
the events that make things happen on the sculpture. A Trigger is an abstract representation of the physical object, and is represented by a data structure which has
- a name
- a type (On/Off, Discrete, Continuous, OneShot)
- a valid range (for Discrete and Continous triggers)

#### Library Function - Trigger Creation
To create a trigger using the DeviceTrigger Library, call DeviceTriggerManager::CreateXXXTrigger()
Triggers cannot be instantiated on their own; they are always managed by a DeviceTriggerManager.

#### Library Function - Send Trigger Event
To send an event associated with a trigger, make one of two calls
Trigger::SendTriggerEvent() - This will send a trigger event to the trigger gateway. The value
of the trigger event is the current value of the trigger.
XXXTrigger::CheckForEventAndSend(newInputValue) - This function will check to see if the new input
value causes an update of the current value of the trigger, and will only send a trigger event if
the current value changes. (The current value may stay the same due to debouncing or other error
filtering). This function is only available on Button, Discrete, and Continous Triggers - OneShot
triggers do not have values).

### DeviceTriggerManager
The DeviceTriggerManager channels information between the actual triggers and the Trigger Gateway. As part of its construction parameters, it is given the ip address and port of the Trigger Gateway.

#### Library Function - Registration with the Trigger Gateway
Once all of the Triggers have been created, you should call DeviceTriggerManager::RegisterDevice().
This will send an HTTP POST to the TriggerGateway, containing information about the device and
its associated Triggers.
We recommend that you repeat this call every few seconds or the Trigger Gateway will mark the device
and its triggers as offline. This does not affect the functionality of the service (trigger events
will still go through), but it may confuse people who are troubleshooting.

#### Library Functionality - Sending Trigger Events
Although a Trigger Event is initialized by a specific Trigger, the actual sending is done through
the DeviceTriggerManager. It makes the HTTP POST to the Trigger Gateway. This is done in a way 
that does not block the main thread, however, POSTs are serialized, and it is possible that a
trigger event may get discarded (couldn't be serviced fast enough, or the queue of pending events
was already full.)

### Example
See TestESP32 for an example of setting up triggers and communicating with the Trigger Gateway.

## Trigger Gateway
The Trigger Gateway receives Trigger information from the various DeviceTriggerManagers, and forwards that information to services that have registered with it. At present, no filtering
is done in the Gateway - if a service registers to receive TriggerEvents, it will receive *all*
TriggerEvents. (The interactivity in our system is limited, at least by computer standards. There
are at most a few dozen devices that can generate trigger events, and they are not being interacted
with the vast majority of the time.)

### Service Registration
To register to receive triggers, a service POSTs to the REST endpoint /api/register. The POST data
must include the name of the service (arbitrary string), and a port to receive trigger event data.
POST data *may* include a protocol for receiving trigger data - options include 
* TCP_SOCKET - creates a persistent socket to the service
* TCP_CONNECT - opens a new socket every time a new TriggerEvent is received
* OSC - sends UDP packet in OSC format (this is one of Chromatik's native inputs). The address 
pattern is /trigger/<triggerName>

### UI
The Trigger Gateway maintains a webpage accessible via standard request to http://<hostaddr>:<port>
By default, the Trigger Gateway runs on port 5002

## Sculpture Services
Individual services must register with the Trigger Gateway and listen for Trigger Events, but are free to use Triggers in any way that they want. Currently, the Flame Server is set up to use the 
Trigger Gateway

### Example - Flame Server
The Flame Server defines fire control sequences, and maps triggers to those sequences. Both the definition and the mapping can be controlled by the user via webpage. By default, the Flame Server 
runs on port 5001.

## TODOS/OUTSTANDING QUESTIONS
- Servers:
    - * There's a question of concurrency here - whether two triggers coming in at the same time
will create a problem on the outgoing socket. Need to check that.
    - * Check end to end when flame server starts before trigger server
    - * Test port changes for webservers
    - Trigger gateway. Allow registration for specific events, filter on the gateway. 
      Registration for a specific event is of the form:
        - Trigger Name + range 
           POST /listen_trigger {name:triggerName, value: [set of values], or value: {max: , min: }}
    - * Trigger gateway. What happens if multiple triggers have the same name? (Seems unfortunate but legitimate, actually. Check concurrency in this situation.)
- Expansion Boards
    - Having this run on the expansion board in the box
    - Getting box expansion boards made (with wifi? with ethernet? I don't have a kicad with ethernet yet)
  (do not use ethernet for this round. Extra connection which I do not want to deal with.)
- Misc
    - ? Can we use different colors in the webpage
    - ? pretty print std_sequences.json, because having it all on one line is unreadable
    - Raspberry Pi the services
- Mode service
    - * Test mode service
    - * Test mode service integration with flame server
    - Create mode box? Or something that can change the mode (and maybe show the current mode)?
- Esp32:
    - ? multi wifi
    - ? Ping/listener?
    - ? Don't sleep if not registered!
    - * Put library stuff into library files
    - * Async http requests
    - * ESP32 sleep mode. Let's see if I can get this thing working with a battery




