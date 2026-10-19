# Upstream issue draft — a pad's Input under Resample (for Thomas to send, 2026-10-19)

To Justin (j3threejay/blackbox-mod), as an issue. **Thomas edits and sends it**; nothing here is posted by a session.
Found at Gate 3b part 2 (`notes/bench/2026-10-19-gate3b-part2.md`, F-m), on 37.4.0d; the code involved is JOEBOX's,
unchanged in the fork. Not yet reproduced on a plain JOEBOX 1 rc4 image: say so, or run it first.

---

**Title:** Live input on a pad + record source Resample = a feedback loop (howl, then all audio silent)

Hi Justin,

On my Mk1 (JOEBOX 1 rc4 + my fork's Clip Window, which doesn't touch the input path), a pad's **Input** row reads
whatever the **record source** is set to. With the record source on **Resample**:

1. Set a pad's Input to In 1+2, Output Out 1, and play it: a full-level tone right away, which stays when the cable is
   unplugged and goes away when the pad's Output is Out 2.
2. With the Phaser insert on that pad, the loop runs away: Out 1 becomes exact digital zero on **every** pad (the
   metronome on Out 2 still plays), and stays so after stopping the pad, changing the delay / reverb types or turning
   the insert Off. Setting the pad's Input Off brings the audio back at once. No fault, the audio task at full rate.

What I see over USB (a dev build with a memory peek): the bus `add_input` reads (the engine pointer + 0x128E0 +
0x1583C, `0x2405F154` here, channels `0x20004400` / `0x20004600` in DTCM) is stock's recording input. Under Resample
it holds Out 1's mix (exactly 0.0 with every pad stopped, rms 0.30 with pads playing); under In 1+2, the inputs. So
a pad with Input on and Output Out 1 under Resample hears itself one block later. In the silent state those two
channels and three other block buffers were all `0x7FC00000` (NaN), which clears as soon as the Input is Off.

Suggestions, your call: ignore a pad's Input while the record source is Resample (or read the converter's own
buffer instead of the recording input), and/or a line in the README. A NaN guard on a pad's buffer would also keep
one runaway pad from silencing everything.

Thanks,
Thomas
