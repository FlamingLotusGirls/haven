#!/bin/bash
# call this from the service to get pyenv correctly
export PYENV_ROOT="/home/pi/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
exec python3 /home/pi/haven/BirdBath/beertaps/adc_reader.py "$@"
