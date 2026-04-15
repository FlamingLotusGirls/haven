# haven
Code to support flame control for the Haven project.
Based on the same technology we've used with many of our recent fire sculptures -
Raspberry pi driving an RS485 line out to the flame control boxes. The flame control
boxes speak our '!' protocol - ie, !BBVI. (Here BB is the board value in asci-encoded
hex, V is the valve number, and I is 0 or 1, for on or off.)

The addition here is an auxiliary board directly connected to our flame control board,
intercepting physical button presses and turning them into sequences. This allows us to
have more local control of the flame effects without having to rendevous through the
RPI. (Control is limited to the valves on that particular box. There's still no way for
the boxes to talk to each other.)
