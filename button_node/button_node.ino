const int BUTTON_PIN = 23;
const int INDICATOR_LED_PIN = 2;

void setup()
{
  Serial.begin(9600);
  pinMode(INDICATOR_LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT);
}

void loop()
{
  int buttonStatus = digitalRead(BUTTON_PIN);
  if (buttonStatus == HIGH)
  {
    digitalWrite(INDICATOR_LED_PIN, HIGH);
  }
  else
  {
    digitalWrite(INDICATOR_LED_PIN, LOW);
  }
}