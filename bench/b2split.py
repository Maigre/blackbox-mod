#!/usr/bin/env python3
"""b2split: move whole modules (src/<m>.c) from bank 1 to bank 2 by tool, with no edit to their source. A spike
(hub task blackbox#t-057); what it measured is in notes/spikes/b2split.md.

    python3 bench/b2split.py chop chopmode [--decl bench/splits/chopshop.py] [--stubs all|reached] [--run ./check.sh]
    python3 bench/b2split.py --verify            after python3 patch.py <the full set>: bank 2 decoded, stubs live / blank
    python3 bench/b2split.py --absent test_x.py  a suite with bank 2 blank in every emulator it makes

runs ./build.sh as it is, with a stand-in for arm-none-eabi-gcc on the PATH that (1) records how each moved module is
compiled and (2) takes over the final link (the one given -T out/cave.ld). At that link it:

  1. compiles each module again, with -ffunction-sections -fdata-sections -fno-ipa-ra, the build's own flags otherwise;
  2. reads the patch sets (patches/*.py, evaluated against stand-in symbols) to learn every stock site that reaches a
     module symbol and the stock callee or vtable word it replaced;
  3. splits each module in two copies of that one object:
       bank 2  every function, renamed <name>__b2, with what it reaches (static helpers, strings, tables);
       bank 1  what must stay: functions declared KEEP, data that stock or the cave reads (a name table a patch points
               stock at), and what those reach; its calls into moved functions land on the stubs;
  4. generates one bank-1 stub per entry (16 bytes: a mov, a b.w, a pair word) and a shared dispatcher (a second one
     that also saves d0-d7 for entries taking float arguments, read from their definition): bank 2 live -> the body;
     otherwise the fallback (the stock callee the patch replaced, the old vtable word, a declared value, or a
     hand-written function);
  5. answers bank 2's calls back into the cave through veneers in bank 2 that jump through a table whose address the
     dispatcher writes into one word of patch RAM (B2S_VEC) before every body: bank 2 holds neither a branch nor a
     data pointer into the cave (test_bank2.py), and its bytes do not depend on where the cave's code lands;
  6. writes out/b2split/cave.ld from out/cave.ld and links; build.sh then finishes as usual (bank 2 header, sum,
     b2_expect_sum, BBEXTRA.BIN).

A declaration file (python) may set: MODULES, KEEP (names kept whole in bank 1), FALLBACK {name: spec}, FALLBACK_SRC
(hand-written fallback C files), STUBS ("all" or "reached"). Fallback specs: "stock" (the patch's callee), "none"
(void: just return), "ret:<int>", "str:<text>" (return a pointer to that text, in bank 1), "c:<function>" (in a
FALLBACK_SRC file), "addr:<hex>" (a stock function).

Writes out/b2split/report.json (what went where, bytes) and prints a summary. Fork-only (bench/).
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "b2split")
X = os.path.join(OUT, "x")          # objects placed section by section by the generated linker script
B1 = os.path.join(OUT, "b1")        # bank-1 objects that go in through the cave's own wildcard
CAVE_LO, CAVE_HI, STOCK_LO, B2_LO = 0x080F1E78, 0x08100000, 0x08040000, 0x08100000
VEC_RAM = 0x2405FF5C                # patch RAM: one of the 12 unclaimed bytes 0x2405FF54..0x2405FF5F (notes x2)
SENT_LO, SENT_STEP = 0x080F2000, 0x20


# ---------------------------------------------------------------------------------------------------- ELF (32-bit LE)
class Elf:
    """Just enough of a relocatable ELF: sections, symbols, REL relocations."""

    def __init__(self, path):
        self.path = path
        d = self.d = open(path, "rb").read()
        assert d[:4] == b"\x7fELF" and d[4] == 1 and d[5] == 1, f"{path}: not ELF32 LE"
        shoff, = struct.unpack_from("<I", d, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", d, 0x2E)
        self.sh = []
        for i in range(shnum):
            name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from("<10I", d, shoff + i * shentsize)
            self.sh.append(dict(i=i, name_off=name, type=typ, flags=flags, off=off, size=size, link=link, info=info,
                                align=align, entsize=entsize))
        stro = self.sh[shstrndx]["off"]
        for s in self.sh:
            s["name"] = self._str(stro, s["name_off"])
        self.syms = []
        for s in self.sh:
            if s["type"] == 2:      # SHT_SYMTAB
                so = self.sh[s["link"]]["off"]
                for k in range(s["size"] // 16):
                    nm, val, size, info, other, shndx = struct.unpack_from("<IIIBBH", d, s["off"] + 16 * k)
                    self.syms.append(dict(name=self._str(so, nm), value=val, size=size, bind=info >> 4, type=info & 15,
                                          shndx=shndx))
        self.rels = {}              # target section index -> [(offset, type, sym index)]
        for s in self.sh:
            if s["type"] == 9:      # SHT_REL
                lst = self.rels.setdefault(s["info"], [])
                for k in range(s["size"] // 8):
                    off, info = struct.unpack_from("<II", d, s["off"] + 8 * k)
                    lst.append((off, info & 0xFF, info >> 8))
            elif s["type"] == 4:
                raise SystemExit(f"{path}: RELA sections are not handled")

    def _str(self, base, off):
        e = self.d.index(b"\0", base + off)
        return self.d[base + off:e].decode()

    def globals_defined(self):
        return {s["name"]: s for s in self.syms if s["bind"] in (1, 2) and s["shndx"] not in (0, 0xFFF1, 0xFFF2) and s["name"]}

    def undefined(self):
        return {s["name"] for s in self.syms if s["shndx"] == 0 and s["name"]}


# ------------------------------------------------------------------------------------------------- the patch sets
def decode_branch(b, at):
    """(target, kind) if the 4 bytes b at address at are a Thumb-2 BL or B.W, else None."""
    if len(b) < 4:
        return None
    h1, h2 = struct.unpack_from("<HH", b, 0)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xD000) not in (0xD000, 0x9000):
        return None
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s:
        off -= 1 << 25
    return at + 4 + off, ("bl" if h2 & 0x4000 else "b.w")


def patch_sites():
    """Evaluate every patch set against stand-in symbols. Returns {name: [site]} where a site is a dict with the
    address, its kind (bl, b.w, word) and what stock had there (callee, or the old word)."""
    sys.path.insert(0, os.path.join(ROOT, "patches"))
    import thumb
    names, addr_of = {}, {}

    class Sent(dict):
        def __missing__(self, k):
            a = SENT_LO + SENT_STEP * len(addr_of)
            assert a < CAVE_HI
            addr_of[k] = a
            names[a] = k
            self[k] = a
            return a

    real = thumb.symbols
    thumb.symbols = lambda elf: Sent()
    sites = {}
    try:
        for f in sorted(os.listdir(os.path.join(ROOT, "patches"))):
            if not f.endswith(".py") or f in ("thumb.py",):
                continue
            mod = f[:-3]
            sys.modules.pop(mod, None)
            try:
                m = __import__(mod)
            except Exception as exc:          # cave.py reads out/cave.bin: no symbol of a module there
                print(f"b2split: patches/{f} not evaluated ({type(exc).__name__}: {exc})")
                continue
            for at, old, new in getattr(m, "PATCHES", []):
                for k in range(0, len(new) - 3, 2):
                    br = decode_branch(new[k:k + 4], at + k)
                    if br and br[0] in names:
                        ob = decode_branch(old[k:k + 4], at + k) if len(old) >= k + 4 else None
                        callee = ob[0] if ob and STOCK_LO <= ob[0] < CAVE_LO else None
                        sites.setdefault(names[br[0]], []).append(dict(set=mod, at=at + k, kind=br[1], stock=callee))
                if len(new) == 4 and len(old) == 4:
                    v, o = struct.unpack("<I", new)[0], struct.unpack("<I", old)[0]
                    if (v & ~1) in names:
                        sites.setdefault(names[v & ~1], []).append(dict(set=mod, at=at, kind="word", old=o, thumb=v & 1))
    finally:
        thumb.symbols = real
    return sites


# ------------------------------------------------------------------------------------------------- helpers
def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"b2split: failed: {' '.join(cmd)}")
    return r.stdout


def return_type(src, name):
    """The return type of name's definition in src (a regex on the source: good enough for this tree's style)."""
    text = open(src).read()
    m = re.search(r"^([A-Za-z_][\w \t\*]*?)\b" + re.escape(name) + r"\s*\(([^;{]*)\)\s*\{", text, re.M)
    return m.group(1).strip() if m else None


def load_decl(path):
    d = {}
    if path:
        exec(compile(open(path).read(), path, "exec"), d)
    return d


# ------------------------------------------------------------------------------------------------- the split
def split(cfg, link_argv, real_gcc):
    mods = cfg["modules"]
    decl = load_decl(cfg.get("decl"))
    keep = set(decl.get("KEEP", [])) | set(cfg.get("keep", []))
    fb_decl = dict(decl.get("FALLBACK", {}))
    fb_decl.update(cfg.get("fallback", {}))
    stub_mode = cfg.get("stubs") or decl.get("STUBS", "all")
    fb_srcs = [os.path.join(ROOT, p) for p in decl.get("FALLBACK_SRC", [])]
    for d in (X, B1):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    report = dict(modules=mods, keep=sorted(keep), stubs_mode=stub_mode, vec_ram=hex(VEC_RAM), notes=[])

    # -- 1. compile each module again, section per function
    fs, flags = {}, None
    for m in mods:
        cmdf = os.path.join(OUT, "cmd", f"{m}.c.cmd")
        argv = open(cmdf).read().split("\n")[:-1]
        o = argv.index("-o")
        argv[o + 1] = os.path.join(X, f"{m}.fs.o")
        argv = [real_gcc] + argv + ["-ffunction-sections", "-fdata-sections", "-fno-ipa-ra"]
        run(argv, cwd=ROOT)
        fs[m] = Elf(os.path.join(X, f"{m}.fs.o"))
        flags = flags or [a for a in argv[1:] if a.startswith(("-mcpu", "-mthumb", "-mfloat-abi", "-mfpu", "-D", "-O", "-f"))
                          and a not in ("-ffunction-sections", "-fdata-sections")]
        for s in fs[m].sh:
            if s["name"].startswith((".data", ".bss")) and s["size"]:
                raise SystemExit(f"b2split: {m}.c has writable data ({s['name']}, {s['size']} B): the cave discards it; "
                                 "a module keeps its state at fixed addresses")
        if any(s["shndx"] == 0xFFF2 for s in fs[m].syms):
            raise SystemExit(f"b2split: {m}.c has COMMON symbols")

    # -- 2. who defines what, in the rest of the link
    ld_text = open(os.path.join(ROOT, "out", "cave.ld")).read()
    b2block = re.search(r"\.bank2\s*:\s*\{(.*?)\}\s*>\s*BANK2", ld_text, re.S)
    b2_objs = set(re.findall(r"(\S+\.o)\(", b2block.group(1)))
    moved_objs = {f"out/obj/{m}.o" for m in mods}
    others = [a for a in link_argv if a.endswith(".o") and a not in moved_objs]
    defined_in, cave_refs, b2obj_refs = {}, {}, {}
    for o in others:
        e = Elf(os.path.join(ROOT, o))
        for n, s in e.globals_defined().items():
            defined_in[n] = (o, s)
        for n in e.undefined():
            (b2obj_refs if o in b2_objs else cave_refs).setdefault(n, []).append(o)
    msym = {}                          # module global name -> (module, symbol)
    for m in mods:
        for n, s in fs[m].globals_defined().items():
            if n in msym:
                raise SystemExit(f"b2split: {n} defined in two modules")
            msym[n] = (m, s)
    for n in b2obj_refs:
        if n in msym:
            raise SystemExit(f"b2split: bank-2 object(s) {b2obj_refs[n]} call {n}: not handled (would need a rename)")

    sites = patch_sites()
    is_func = lambda n: msym[n][1]["type"] == 2

    # -- 3. roots. Data that stock (a patch) or the cave reads stays in bank 1; so does every name in KEEP.
    for n in keep:
        if n not in msym:
            raise SystemExit(f"b2split: KEEP names {n}, which no module defines")
    b1_roots = set(keep)
    for n in msym:
        if not is_func(n) and (n in sites or n in cave_refs):
            b1_roots.add(n)
            report["notes"].append(f"{n}: data read by {'stock (patch)' if n in sites else 'the cave'}: kept in bank 1")
    moved = {n for n in msym if is_func(n) and n not in keep}

    # -- 4. section closures over the relocation graph (per module, across modules through global names)
    def closure(roots, into_moved):
        """roots: global names. into_moved: follow edges into moved functions (bank 2) or stop there (bank 1).
        Returns ({module: set(section index)}, names reached that stop, external names reached)."""
        want = {m: set() for m in mods}
        stops, ext = set(), set()
        todo = []
        for n in roots:
            m, s = msym[n]
            todo.append((m, s["shndx"]))
        while todo:
            m, sec = todo.pop()
            if sec in want[m]:
                continue
            want[m].add(sec)
            e = fs[m]
            for off, typ, si in e.rels.get(sec, []):
                sym = e.syms[si]
                if sym["bind"] == 0 and sym["shndx"] not in (0, 0xFFF1):   # local: a section or a static
                    todo.append((m, sym["shndx"]))
                    continue
                n = sym["name"]
                if n in msym:
                    if not into_moved and n in moved:
                        stops.add(n)
                        continue
                    mm, ss = msym[n]
                    todo.append((mm, ss["shndx"]))
                else:
                    ext.add(n)
        return want, stops, ext

    b2_want, _, b2_ext = closure(moved, True)
    b1_want, b1_stops, b1_ext = closure(b1_roots, False)

    # -- 5. what bank 2 reaches outside the modules: bank-2 objects direct, cave functions through veneers
    veneers = []
    for n in sorted(b2_ext):
        if n not in defined_in:
            raise SystemExit(f"b2split: the moved code needs {n}, which nothing in the link defines")
        o, s = defined_in[n]
        if o in b2_objs:
            continue
        if s["type"] != 2:
            raise SystemExit(f"b2split: the moved code reads cave DATA {n} ({o}): bank 2 may hold no pointer into "
                             "the cave; needs a hand")
        veneers.append(n)

    # -- 6. the entries: what bank 1 (cave, stock through a patch, kept code) reaches among the moved functions
    reached = {}
    for n in moved:
        why = []
        if n in cave_refs:
            why.append("cave: " + ",".join(sorted(os.path.basename(o) for o in cave_refs[n])))
        if n in sites:
            why.append("stock: " + ",".join(f"{x['kind']}@{x['at']:#x}" for x in sites[n]))
        if n in b1_stops:
            why.append("kept code")
        if why:
            reached[n] = why
    entries = sorted(moved) if stub_mode == "all" else sorted(reached)

    def fallback_of(n):
        src = os.path.join(ROOT, "src", f"{msym[n][0]}.c")
        rt = return_type(src, n)
        if n in fb_decl:
            spec = fb_decl[n]
            if spec == "stock":
                pass
            else:
                return spec, "declared"
        ss = sites.get(n, [])
        stock = set()
        for x in ss:
            if x["kind"] == "word":
                if not (x["old"] & 1 and STOCK_LO <= x["old"] < CAVE_LO):
                    raise SystemExit(f"b2split: {n}: the word at {x['at']:#x} held {x['old']:#x}, not a stock "
                                     "function: needs a declared fallback")
                stock.add(x["old"] & ~1)
            elif x["stock"] is None:
                raise SystemExit(f"b2split: {n}: the patch at {x['at']:#x} replaced bytes that were no call: needs a "
                                 "declared fallback")
            else:
                stock.add(x["stock"])
        if len(stock) > 1:
            raise SystemExit(f"b2split: {n}: its sites replaced different stock callees {sorted(map(hex, stock))}: "
                             "needs a declared fallback")
        if stock:
            if n in cave_refs:
                report["notes"].append(f"{n}: the stock fallback also serves its cave callers {cave_refs[n]}")
            return f"addr:{stock.pop():#x}", "stock callee"
        if rt == "void":
            return "none", "void"
        if n in reached:
            raise SystemExit(f"b2split: {n} returns {rt!r} and is reached from bank 1 ({'; '.join(reached[n])}) with "
                             "no stock callee: declare its fallback (FALLBACK)")
        return "ret:0", f"default (returns {rt}, no bank-1 caller)"

    fallbacks = {n: fallback_of(n) for n in entries}
    for n in fb_decl:
        if n not in fallbacks and n in msym and n not in keep:
            report["notes"].append(f"{n}: a fallback is declared, but no stub was needed")

    # -- 7. the two copies of each module object
    def objcopy(src, dst, args):
        run(["arm-none-eabi-objcopy"] + args + [src, dst])

    placed_b2, placed_b1 = [], []
    for m in mods:
        e = fs[m]
        ren = []
        for n in e.globals_defined():
            ren += ["--redefine-sym", f"{n}={n}__b2"]
        for n in e.undefined():
            if n in msym:
                ren += ["--redefine-sym", f"{n}={n}__b2"]
            elif n in veneers:
                ren += ["--redefine-sym", f"{n}={n}__b2v"]
        b2o = os.path.join(X, f"{m}.b2.o")
        objcopy(e.path, b2o, ren)
        secs = [e.sh[i]["name"] for i in sorted(b2_want[m]) if e.sh[i]["size"]]
        if secs:
            placed_b2.append((os.path.relpath(b2o, ROOT), secs, sum(e.sh[i]["size"] for i in b2_want[m])))
        if b1_want[m]:
            b1o = os.path.join(X, f"{m}.b1.o")
            weak = []
            for n in e.globals_defined():
                if n in moved:
                    weak += ["--weaken-symbol", n]      # the stub's strong definition wins for kept code's calls
            objcopy(e.path, b1o, weak)
            secs = [e.sh[i]["name"] for i in sorted(b1_want[m]) if e.sh[i]["size"]]
            placed_b1.append((os.path.relpath(b1o, ROOT), secs, sum(e.sh[i]["size"] for i in b1_want[m])))

    # -- 8. stubs, dispatcher and vector table (bank 1); veneers (bank 2); declared fallbacks
    def fp_args(n):
        """Does n take float / double arguments (s0-s15 must then survive b2_live)? From its definition."""
        src = open(os.path.join(ROOT, "src", f"{msym[n][0]}.c")).read()
        m = re.search(r"^[A-Za-z_][\w \t\*]*?\b" + re.escape(n) + r"\s*\(([^;{]*)\)\s*\{", src, re.M)
        if m is None:
            raise SystemExit(f"b2split: {n}: no definition found in src/{msym[n][0]}.c to read its arguments from")
        if "..." in m.group(1):
            raise SystemExit(f"b2split: {n} is variadic: not handled")
        return bool(re.search(r"\b(float|double)\b(?!\s*\*)", m.group(1)))

    fp = {n: fp_args(n) for n in entries}

    def dispatcher(name, save_fp):
        o = 80 if save_fp else 16            # where the saved ip (the index) sits
        return ['    .section .text.' + name + ',"ax",%progbits', f'    .global {name}', f'    .type {name}, %function',
                '    .thumb_func',
                '@ ip = the entry\'s index; r0-r3' + (', s0-s15' if save_fp else '') +
                ' and the stack are the caller\'s arguments, lr its return',
                f'{name}:',
                '    push {r0-r3, ip, lr}'] + (['    vpush {d0-d7}'] if save_fp else []) + [
                f'    ldr r0, =0x{VEC_RAM:08x}           @ B2S_VEC: bank 2\'s veneers jump through this table',
                '    ldr r1, =b2s_vec',
                '    str r1, [r0]',
                '    bl b2_live',
                f'    ldr r1, [sp, #{o}]',
                '    ldr r2, =b2s_pairs',
                '    add.w r2, r2, r1, lsl #3',
                '    cmp r0, #0',
                '    ite ne',
                '    ldrne r2, [r2]                  @ live: the body in bank 2',
                '    ldreq r2, [r2, #4]              @ not: the fallback',
                f'    str r2, [sp, #{o}]'] + (['    vpop {d0-d7}'] if save_fp else []) + [
                '    pop {r0-r3, ip, lr}',
                '    bx ip',
                '    .ltorg', '']

    asm = ['    .syntax unified', '    .thumb', '@ generated by bench/b2split.py: bank-1 stubs into bank 2', '']
    if not all(fp.values()):
        asm += dispatcher("b2s_dispatch", False)
    if any(fp.values()):
        asm += dispatcher("b2s_dispatch_fp", True)
    rets = {}
    for k, n in enumerate(entries):
        d = "b2s_dispatch_fp" if fp[n] else "b2s_dispatch"
        asm += [f'    .section .text.b2s.{n},"ax",%progbits', f'    .global {n}', f'    .type {n}, %function',
                '    .thumb_func', f'{n}:', f'    mov.w ip, #{k}', f'    b.w {d}', f'    .size {n}, . - {n}', '']
    asm += ['    .section .rodata.b2s_pairs,"a",%progbits', '    .balign 4', '    .global b2s_pairs', 'b2s_pairs:']
    fb_objs_needed = False
    for n in entries:
        spec, _ = fallbacks[n]
        if spec.startswith("addr:"):
            tgt = f"0x{int(spec[5:], 16) | 1:08x}"
        elif spec == "none":
            tgt = "b2s_none"
            rets["none"] = ["b2s_none:", "    bx lr"]
        elif spec.startswith("ret:"):
            v = int(spec[4:], 0)
            tgt = f"b2s_ret_{v & 0xFFFFFFFF:x}"
            rets[tgt] = [f"{tgt}:", f"    ldr r0, ={v & 0xFFFFFFFF:#x}", "    bx lr", "    .ltorg"]
        elif spec.startswith("str:"):
            tgt = f"b2s_str_{n}"
            txt = spec[4:].replace("\\", "\\\\").replace('"', '\\"')
            rets[tgt] = [f"{tgt}:", f"    ldr r0, =.Ls_{n}", "    bx lr", "    .ltorg",
                         '    .section .rodata.b2s_str,"a",%progbits', f'.Ls_{n}: .asciz "{txt}"',
                         '    .section .text.b2s_ret,"ax",%progbits']
        elif spec.startswith("c:"):
            tgt = spec[2:]
            fb_objs_needed = True
        else:
            raise SystemExit(f"b2split: {n}: unknown fallback spec {spec!r}")
        asm.append(f'    .word {n}__b2, {tgt}      @ {n}')
    asm += ['    .section .rodata.b2s_vec,"a",%progbits', '    .balign 4', '    .global b2s_vec', 'b2s_vec:']
    asm += [f'    .word {n}' for n in veneers] or ['    .word 0']
    asm += ['', '    .section .text.b2s_ret,"ax",%progbits']
    for t, body in rets.items():
        asm += ['    .thumb_func', '    .type ' + body[0][:-1] + ', %function'] + body
    open(os.path.join(B1, "stubs.S"), "w").write("\n".join(asm) + "\n")
    cpu = [a for a in flags if a.startswith(("-mcpu", "-mthumb", "-mfloat-abi", "-mfpu"))]
    run([real_gcc] + cpu + ["-c", "-o", os.path.join(B1, "stubs.o"), os.path.join(B1, "stubs.S")])
    vasm = ['    .syntax unified', '    .thumb', '@ generated by bench/b2split.py: bank 2 -> cave, through B2S_VEC',
            '    .section .text.b2v,"ax",%progbits']
    for k, n in enumerate(veneers):
        vasm += ['    .thumb_func', f'    .global {n}__b2v', f'    .type {n}__b2v, %function', f'{n}__b2v:',
                 '    ldr.w ip, .Lvec', '    ldr.w ip, [ip]', f'    ldr.w ip, [ip, #{4 * k}]', '    bx ip']
        # (not ldr.w pc: its second half, 0xF00k, reads as half a BL to test_bank2's two-byte scan)
    vasm += ['    .balign 4', f'.Lvec: .word 0x{VEC_RAM:08x}']
    open(os.path.join(X, "veneers.S"), "w").write("\n".join(vasm) + "\n")
    run([real_gcc] + cpu + ["-c", "-o", os.path.join(X, "veneers.o"), os.path.join(X, "veneers.S")])
    if veneers:
        placed_b2.append((os.path.relpath(os.path.join(X, "veneers.o"), ROOT), [".text.b2v"], 14 * len(veneers) + 6))
    fb_objs = []
    if fb_objs_needed or fb_srcs:
        for src in fb_srcs:
            o = os.path.join(B1, os.path.basename(src)[:-2] + ".o")
            run([real_gcc] + flags + ["-Isrc", "-c", "-o", o, src], cwd=ROOT)
            fb_objs.append(os.path.relpath(o, ROOT))

    # -- 9. the linker script
    b2_lines = " ".join(f"{o}({' '.join(secs)})" for o, secs, _ in placed_b2)
    b1_lines = " ".join(f"{o}({' '.join(secs)})" for o, secs, _ in placed_b1)
    blk = b2block.group(0)
    assert blk.count("}") == 1, "out/cave.ld: the .bank2 block is not what b2split expects"
    ld = ld_text.replace(blk, blk.replace("}", " " + b2_lines + " }"))
    cave_pat = "*(.text .text.* .rodata .rodata.*)"
    assert ld.count(cave_pat) == 1, "out/cave.ld: the cave's wildcard is not where b2split expects it"
    ld = ld.replace(cave_pat, f"{b1_lines}\n    EXCLUDE_FILE(*b2split/x/*) {cave_pat}")
    ld = re.sub(r"(/DISCARD/\s*:\s*\{)", r"\1 *b2split/x/*(*) ", ld)
    open(os.path.join(OUT, "cave.ld"), "w").write(ld)

    # -- 10. link
    argv = []
    for a in link_argv:
        if a == "out/cave.ld":
            argv.append(os.path.relpath(os.path.join(OUT, "cave.ld"), ROOT))
        elif a in moved_objs:
            continue
        else:
            argv.append(a)
    objs = [o for o, _, _ in placed_b1] + [o for o, _, _ in placed_b2] + [os.path.relpath(os.path.join(B1, "stubs.o"), ROOT)] + fb_objs
    argv += list(dict.fromkeys(objs))
    r = subprocess.run([real_gcc] + argv, cwd=ROOT)
    if r.returncode:
        return r.returncode

    # -- 11. the report
    st = Elf(os.path.join(B1, "stubs.o"))
    stub_bytes = {s["name"]: s["size"] for s in st.sh if s["name"].startswith((".text.b2s", ".rodata.b2s"))}
    fb_bytes = 0
    for o in fb_objs:
        fe = Elf(os.path.join(ROOT, o))
        fb_bytes += sum(s["size"] for s in fe.sh if s["name"].startswith((".text", ".rodata")))
    report.update(
        fp_entries=sorted(n for n in entries if fp[n]), moved=sorted(moved), reached={n: reached[n] for n in sorted(reached)}, entries=entries,
        fallbacks={n: fallbacks[n] for n in entries}, veneers=veneers,
        bank1_kept=[dict(obj=o, sections=s, bytes=b) for o, s, b in placed_b1],
        bank2=[dict(obj=o, sections=s, bytes=b) for o, s, b in placed_b2],
        bytes=dict(kept=sum(b for _, _, b in placed_b1),
                   stubs=sum(v for k, v in stub_bytes.items() if k.startswith(".text.b2s.")),
                   pairs=stub_bytes.get(".rodata.b2s_pairs", 0), vec=stub_bytes.get(".rodata.b2s_vec", 0),
                   dispatcher=stub_bytes.get(".text.b2s_dispatch", 0) + stub_bytes.get(".text.b2s_dispatch_fp", 0),
                   declared_returns=stub_bytes.get(".text.b2s_ret", 0) + stub_bytes.get(".rodata.b2s_str", 0),
                   hand_fallbacks=fb_bytes,
                   bank2=sum(b for _, _, b in placed_b2)),
        sites={n: sites[n] for n in sorted(sites) if n in msym})
    json.dump(report, open(os.path.join(OUT, "report.json"), "w"), indent=1, default=str)
    return 0


# ------------------------------------------------------------------------------------------------- verify
IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"


def blank_bank2(e):
    """What a unit with no payload has: bank 2 erased (0xFF), and the verdict not taken yet."""
    e.uc.mem_write(B2_LO, b"\xff" * 0x20000)
    e.meter_up()


def verify():
    """After `python3 patch.py <full set>`: (1) no instruction in bank 2 branches out of it, decoded per function
    symbol (test_bank2.py's scan steps two bytes at a time and can read the second half of a 32-bit instruction as half
    a BL); no literal in bank 2 points into the cave; (2) every stub reaches its body with bank 2 live, and its
    fallback without one bank-2 instruction with bank 2 blank; every veneer lands on its cave function."""
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
    from unicorn import UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0
    from emu import Emu
    r = json.load(open(os.path.join(OUT, "report.json")))
    fails = []

    def check(label, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"  [{detail}]"))
        ok or fails.append(label)

    # (1) bank 2, function by function
    nm = run(["arm-none-eabi-nm", "-S", "-n", "out/cave.elf"]).splitlines()
    b2 = open("out/bank2.bin", "rb").read()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    out_br, cave_lit, funcs = [], [], 0
    for line in nm:
        p = line.split()
        if len(p) != 4 or p[2] not in "Tt":
            continue
        a, size, name = int(p[0], 16) & ~1, int(p[1], 16), p[3]
        if not B2_LO <= a < B2_LO + len(b2) or name.startswith("splash_"):
            continue
        funcs += 1
        code = b2[a - B2_LO:a - B2_LO + size]
        for ins in md.disasm(code, a):
            if ins.mnemonic in ("bl", "blx", "b", "b.w") and ins.op_str.startswith("#"):
                t = int(ins.op_str[1:], 16)
                if 0x08000000 <= t < 0x08200000 and not B2_LO <= t < B2_LO + len(b2):   # (outside the flash:
                    out_br.append                                                         # inline data, as test_bank2)((name, hex(ins.address), hex(t)))
            if ins.mnemonic.startswith("ldr") and "[pc" in ins.op_str:
                imm = re.search(r"#(-?0x[0-9a-f]+|-?\d+)\]", ins.op_str)
                la = ((ins.address + 4) & ~3) + (int(imm.group(1), 0) if imm else 0)
                if B2_LO <= la < B2_LO + len(b2) - 3:
                    v = struct.unpack_from("<I", b2, la - B2_LO)[0]
                    if CAVE_LO <= (v & ~1) < CAVE_HI:
                        cave_lit.append((name, hex(la), hex(v)))
    check(f"bank 2, {funcs} functions decoded one by one: no branch leaves bank 2", not out_br, out_br[:8])
    check("... and no literal they load points into the cave", not cave_lit, cave_lit[:8])

    # (2) the stubs, live and blank
    for blank in (False, True):
        for n in r["entries"]:
            e = Emu(IMAGE, "out/cave.elf")
            e.uc.mem_map(0x38800000, 0x1000)
            e.uc.mem_map(0x58024000, 0x1000)
            if blank:
                blank_bank2(e)
            spec = r["fallbacks"][n][0]
            seen = {"body": 0, "fb": 0, "b2": 0}
            e.uc.hook_add(UC_HOOK_CODE, lambda *_: seen.__setitem__("b2", seen["b2"] + 1), begin=B2_LO, end=B2_LO + 0xE0000)
            body = e.sym[n + "__b2"] & ~1
            if not blank:
                e.stub(body, lambda: seen.__setitem__("body", 1), value=0x5A5A)
            if spec.startswith("addr:"):
                e.stub(int(spec[5:], 16), lambda: seen.__setitem__("fb", 1), value=0x6B6B)
            elif spec.startswith("c:"):
                e.stub(e.sym[spec[2:]] & ~1, lambda: seen.__setitem__("fb", 1), value=0x6B6B)
            e.call(n, 0x24070000, 0x24070100, 0, 0, count=20_000_000)
            r0 = e.uc.reg_read(UC_ARM_REG_R0)
            if not blank:
                check(f"live  {n}: the body in bank 2, and B2S_VEC set", seen["body"] == 1 and seen["fb"] == 0
                      and e.r32(VEC_RAM) & 0xFFFFFFFF == e.sym["b2s_vec"], seen)
            else:
                if spec.startswith(("addr:", "c:")):
                    ok = seen["fb"] == 1
                elif spec.startswith("ret:"):
                    ok = r0 == int(spec[4:], 0) & 0xFFFFFFFF
                elif spec.startswith("str:"):
                    ok = e.cstr(r0) == spec[4:]
                else:
                    ok = True
                check(f"blank {n}: {spec}, no instruction run in bank 2", ok and seen["b2"] == 0, (seen, hex(r0)))
    e = Emu(IMAGE, "out/cave.elf")
    e.uc.mem_map(0x38800000, 0x1000)
    e.uc.mem_map(0x58024000, 0x1000)
    e.w32(VEC_RAM, e.sym["b2s_vec"])
    for n in r["veneers"]:
        got = []
        e.stub(e.sym[n] & ~1, lambda n=n: got.append(n), value=0)
        e.call(n + "__b2v", 1, 2, 3, 4)
        check(f"veneer {n}__b2v lands on {n} in the cave", got == [n], got)
    print(f"\n{len(fails)} failure(s)")
    return 1 if fails else 0


def absent(suite):
    """Run a suite with bank 2 blank in every emulator it makes: what a unit with no payload does."""
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import runpy
    import emu
    init = emu.Emu.__init__

    def init_blank(self, *a, **k):
        init(self, *a, **k)
        blank_bank2(self)
    emu.Emu.__init__ = init_blank
    sys.argv = [suite]
    runpy.run_path(suite, run_name="__main__")


# ------------------------------------------------------------------------------------------------- driver
def real_gcc_path():
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, "arm-none-eabi-gcc")
        if os.path.abspath(d) != os.path.join(OUT, "bin") and os.access(p, os.X_OK):
            return p
    raise SystemExit("b2split: no arm-none-eabi-gcc on the PATH")


SHIM = """#!/bin/sh
# generated by bench/b2split.py: stands in for arm-none-eabi-gcc during ./build.sh
for a in "$@"; do
  [ "$a" = out/cave.ld ] && exec "$B2SPLIT_PY" "$B2SPLIT_TOOL" --link "$@"
done
for a in "$@"; do
  case " $B2SPLIT_SRCS " in *" $a "*) printf '%s\\n' "$@" > "out/b2split/cmd/$(basename "$a").cmd";; esac
done
exec "$B2SPLIT_REAL_GCC" "$@"
"""


def summary():
    r = json.load(open(os.path.join(OUT, "report.json")))
    sz = run(["arm-none-eabi-size", "-A", os.path.join(ROOT, "out", "cave.elf")])
    cave = int(re.search(r"^\.cave\s+(\d+)", sz, re.M).group(1))
    bank2 = int(re.search(r"^\.bank2\s+(\d+)", sz, re.M).group(1))
    b = r["bytes"]
    print(f"b2split {' '.join(r['modules'])}: .cave {cave} B ({0xE188 - cave} free), .bank2 {bank2} B")
    print(f"  bank 1 kept {b['kept']} B, stubs {len(r['entries'])} x 8 = {b['stubs']} B + pairs {b['pairs']} B, "
          f"dispatcher {b['dispatcher']} B, vector table {b['vec']} B ({len(r['veneers'])} cave callees), declared "
          f"returns {b['declared_returns']} B, hand fallbacks {b['hand_fallbacks']} B; bank 2 {b['bank2']} B")
    for n in r["entries"]:
        spec, why = r["fallbacks"][n]
        print(f"  stub {n:24s} -> {n}__b2 | {spec} ({why}){'  [' + '; '.join(r['reached'][n]) + ']' if n in r['reached'] else ''}")
    if r.get("fp_entries"):
        print(f"  float arguments (s0-s15 saved round b2_live): {', '.join(r['fp_entries'])}")
    for n in r["notes"]:
        print("  note: " + n)
    r["cave"], r["bank2_total"] = cave, bank2
    json.dump(r, open(os.path.join(OUT, "report.json"), "w"), indent=1, default=str)


def main():
    a = sys.argv[1:]
    if a and a[0] == "--link":
        cfg = json.load(open(os.path.join(OUT, "config.json")))
        sys.exit(split(cfg, a[1:], os.environ["B2SPLIT_REAL_GCC"]))
    if a and a[0] == "--verify":
        sys.exit(verify())
    if a and a[0] == "--absent":
        absent(a[1])
        return
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    cfg = dict(modules=[], keep=[], fallback={}, stubs=None, decl=None)
    cmd = ["./build.sh"]
    i = 0
    while i < len(a):
        if a[i] == "--run":                # e.g. --run ./check.sh: anything that calls ./build.sh, split the same way
            cmd = a[i + 1:]
            break
        if a[i] == "--decl":
            cfg["decl"] = a[i + 1]; i += 2
        elif a[i] == "--stubs":
            cfg["stubs"] = a[i + 1]; i += 2
        elif a[i] == "--keep":
            cfg["keep"] += a[i + 1].split(","); i += 2
        elif a[i] == "--fallback":
            n, spec = a[i + 1].split("=", 1); cfg["fallback"][n] = spec; i += 2
        else:
            cfg["modules"].append(a[i]); i += 1
    if cfg["decl"] and not cfg["modules"]:
        cfg["modules"] = load_decl(cfg["decl"]).get("MODULES", [])
    for m in cfg["modules"]:
        if not os.path.exists(os.path.join(ROOT, "src", f"{m}.c")):
            raise SystemExit(f"b2split: no src/{m}.c")
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "bin"))
    os.makedirs(os.path.join(OUT, "cmd"))
    json.dump(cfg, open(os.path.join(OUT, "config.json"), "w"))
    shim = os.path.join(OUT, "bin", "arm-none-eabi-gcc")
    open(shim, "w").write(SHIM)
    os.chmod(shim, 0o755)
    env = dict(os.environ, B2SPLIT_REAL_GCC=real_gcc_path(), B2SPLIT_PY=sys.executable,
               B2SPLIT_TOOL=os.path.abspath(__file__), B2SPLIT_SRCS=" ".join(f"src/{m}.c" for m in cfg["modules"]),
               PATH=os.path.join(OUT, "bin") + os.pathsep + os.environ["PATH"])
    r = subprocess.run(cmd, cwd=ROOT, env=env)
    if os.path.exists(os.path.join(OUT, "report.json")):
        summary()
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
