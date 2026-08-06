#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
cd "$root"
mkdir -p build tests
gcc -std=gnu17 -O2 -Wall -Wextra -Wpedantic -fPIC -c vendor/asap-8.0.0/asap.c -o build/asap.o
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -fPIC -shared sap.cc build/asap.o -o sap.so -laudcore -laudtag
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic test_asap.cpp build/asap.o -o test_asap
