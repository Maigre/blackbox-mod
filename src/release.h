/*
 * A PUBLIC build: `RELEASE=1 ./build.sh`. Two things differ from the builds that go on the test unit:
 *   - the version reads as the release's name, not the letter of a test build;
 *   - the raw USB peek / poke (usbdev.c) is left out. It reads and writes any address in the machine, bank 1's flash
 *     controls included, which is how a unit can be killed for good; it is a development tool and nothing more.
 * The name of the first release under this scheme (2026-10-13): JOEBOX 1. Eight characters is the most a
 * knob-page header shows before it wraps (cpu.c), so the name and its number have to fit in that.
 */
#ifndef RELEASE_H
#define RELEASE_H

#define RELEASE_NAME "37.4.1"   /* Thomas's fork: 37.<feature step>.<build>; fork-only, never in a feature branch */
#define DEV_NAME     "37.4.1d"  /* a dev build of the same: USB peek / poke compiled in (see usbdev.c) */
_Static_assert(sizeof RELEASE_NAME - 1 <= 8, "a release name is eight characters at most: longer wraps on a knob page");
_Static_assert(sizeof DEV_NAME - 1 <= 8, "a dev name is eight characters at most: longer wraps on a knob page");

#endif
