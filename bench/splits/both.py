# ChopShop (tool only, bench/splits/chopshop.py) and note repeat (bench/splits/repeat.py) in one build: the full check.
_c, _r = {}, {}
exec(open("bench/splits/chopshop.py").read(), _c)
exec(open("bench/splits/repeat.py").read(), _r)
MODULES = _c["MODULES"] + _r["MODULES"]
KEEP = _c["KEEP"]
FALLBACK = dict(_c["FALLBACK"], **_r["FALLBACK"])
