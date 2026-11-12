# ChopShop (src/chop.c + src/chopmode.c) for bench/b2split.py: what the tool cannot know by itself.
MODULES = ["chop", "chopmode"]

# Kept whole in bank 1: they must act with bank 2 absent or before it is checked.
KEEP = [
    "chop_register",      # the app's param table, built while the app is: b2_live() is 0 until the first audio block
    "chop_defaults",      # the pad store's P_CHOP entry, same moment; a project's flag must load and save without bank 2
    "chop_invariant",     # clipsel's mode reset: the flag only ever lives on a Slicer, bank 2 or not
    "chop_header_mode",   # a WAV header read at a project's load (boot): a ChopShop pad must stay a Slicer
    "chop_set",           # the Mode list has 7 entries whatever bank 2 does (a data patch): positions map here
    "chop_show_wave",     # ... and the two popup highlights map back
    "chop_show_pad",
]

# Entries reached from bank 1 that return a value and replace no stock call: what they answer without bank 2.
FALLBACK = {
    "chop_roll_text": "str:[:.:]",   # clipsel's knob text for the Roll row (which only a live chop_pages adds)
    "chop_retempo": "ret:0",         # 0 = no detection to reuse: chop_set then asks chop_request, which does nothing
}
