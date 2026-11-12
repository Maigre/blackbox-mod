# ChopShop (src/chop.c + src/chopmode.c) for bench/b2split.py: what the tool cannot know by itself.
MODULES = ["chop", "chopmode"]

# Kept whole in bank 1: they must act with bank 2 absent or before it is checked.
KEEP = [
    "chop_register",      # the app's param table, built while the app is: b2_live() is 0 until the first audio block
    "chop_defaults",      # the pad store's P_CHOP entry, same moment; a project's flag must load and save without bank 2
    "chop_invariant",     # clipsel's mode reset: the flag only ever lives on a Slicer, bank 2 or not
    "chop_header_mode",   # a WAV header read at a project's load (boot): a ChopShop pad must stay a Slicer (the mode
                          # is stored: stock's fallback would give the pad the file's mode)
    "chop_set",           # the Mode list has 7 entries whatever bank 2 does (a data patch): positions map here
    "chop_show_wave",     # ... and the two popup highlights map back
    "chop_show_pad",
]
# Moved on purpose, though the same header read calls it: chop_header_post (its closing post, stock site 0x0809def2).
# Before the meter's first block its stub runs stock's post only, where JOEBOX 2 also runs chop_forget and re-chops a
# ChopShop pad that has a Chop type. Keeping it alone changes nothing: both are moved, so no-op stubs in that window
# too. `--keep chop_header_post,chop_forget` (+128 B) brings the forget back (the chop state sits behind the stretch
# bank's scratch, which a boot does not clear); the re-chop would take chop_request and what it reaches. Whether a
# boot's project load falls in that window is the unit's to say (notes/spikes/b2split.md, "The boot window").

# Entries reached from bank 1 that return a value and replace no stock call: what they answer without bank 2.
FALLBACK = {
    "chop_roll_text": "str:[:.:]",   # clipsel's knob text for the Roll row (which only a live chop_pages adds)
    "chop_retempo": "ret:0",         # 0 = no detection to reuse: chop_set then asks chop_request, which does nothing
}
