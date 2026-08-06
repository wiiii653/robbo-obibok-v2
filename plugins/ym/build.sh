#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd); cd "$root"
sources=(vendor/stsound/StSoundLibrary/digidrum.cpp vendor/stsound/StSoundLibrary/LZH/LzhLib.cpp vendor/stsound/StSoundLibrary/Ym2149Ex.cpp vendor/stsound/StSoundLibrary/Ymload.cpp vendor/stsound/StSoundLibrary/YmMusic.cpp vendor/stsound/StSoundLibrary/YmUserInterface.cpp)
flags=(-std=c++17 -O2 -Wall -Wextra -Wpedantic -Wno-unused-parameter -fPIC -Ivendor/stsound/StSoundLibrary)
g++ "${flags[@]}" -shared ym.cc "${sources[@]}" -o ym.so -laudcore -laudtag
g++ "${flags[@]}" test_stsound.cpp "${sources[@]}" -o test_stsound
