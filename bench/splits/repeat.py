# Note repeat (src/repeat.c) for bench/b2split.py. Nothing kept in bank 1: without bank 2 the RPT button does nothing
# (repeat_hold falls back to a no-op), the pads play as stock (the two note sites fall back to stock's note-on /
# note-off), the recorder stamps notes with stock's raw tick, and the audio task's repeat_tick does nothing.
MODULES = ["repeat"]
FALLBACK = {
    "repeat_div_name": "str:---",    # the division button's label (solo.c): stock's own mark for something unavailable
    "repeat_held": "ret:0",          # the RPT button's light (solo.c): never held without bank 2
}
