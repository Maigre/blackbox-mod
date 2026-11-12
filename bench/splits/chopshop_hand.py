# ChopShop as bench/splits/chopshop.py, but chop_set moves too, with a hand-written fallback (the hand split's shape:
# blackbox#t-052 kept the popup highlights and header_mode whole and wrote chop_set's fallback).
exec(open("bench/splits/chopshop.py").read())
KEEP = [n for n in KEEP if n != "chop_set"]
FALLBACK = dict(FALLBACK, chop_set="c:chop_set_off")
FALLBACK_SRC = ["bench/splits/chopshop_fallback.c"]
