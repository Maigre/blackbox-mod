#!/bin/sh
# Compile the firmware-free DSP cores for the host: host/libdsp.dylib, driven from Python (host/dsp.py) to render audio.
# clang on the Mac; any C compiler elsewhere (CC=gcc ./build.sh). The file keeps its .dylib name: dlopen does not care.
set -e
cd "$(dirname "$0")"
${CC:-$(command -v clang || command -v cc)} -O2 -shared -fPIC -Wno-unknown-pragmas -Wno-ignored-pragmas -o libdsp.dylib $(ls ../src/smash.c ../src/confetti.c ../src/prism.c ../src/rev4.c ../src/s950.c 2>/dev/null)
# Charles Vestal's TAPESCAM as published, the reference test_tapescam.py holds the firmware port against
${CC:-$(command -v clang || command -v cc)} -O2 -shared -fPIC -w -o libtsref.dylib tapescam_ref/ref.c
# ChopShop's attack scan + placement (chop_dsp.c, chop.c) for host/chop_check.py
${CC:-$(command -v clang || command -v cc)} -O2 -shared -fPIC -DSTR_HOST -Wno-unknown-pragmas -Wno-ignored-pragmas -Wno-incompatible-library-redeclaration -o libchop.dylib chop_host.c ../src/chop_dsp.c ../src/chop.c
