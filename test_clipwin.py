"""Clip Window: Slip, Region and Loop Len (src/clipwin.c, clipwin_thunk.S, patches/clipwin.py; notes/re/README.md
sections 2, 3) under Unicorn.

Real firmware runs for: the whole class-B pad block method (0x08068c64) block after block - process, voice start, the
recompute (FUN_08064a94 with H3 in it, called at the wraps through H3'), segment start (FUN_08065550 with H1 and H3 in
it, FUN_08065290 with H1'), render, fades, the segment reader with JOEBOX's
clip_read_b and clipwin_read in it, filter.c's clip_read and clip_read_ring, the stock clip reader and its kernel - then
the engine's own clock advance (0x080696d8), in the control tick's order; the pad constructor and the real param-set
for every setting (Pad Mode, Launch, Loop, Beat Count, Quant, Sync, Pitch, slice markers, a live Sync change, Launch
Trigger relaunches, Toggle stops, the transport stopped and its start message 0x57) and where Loop Len forces Sync from
clipwin_tick, which duck_block hands the engine; the cell's class-H object (its constructor,
linked at pad + 8, its block method after the pad's, its param-set storing Loop Start / End / Mode from the same
queue); clipwin_tick reading the app's pad stores
through the stock settings lookup, once a block where duck_block calls it; filter.c's machine readers (every machine
mode, SP 45 included) at and near the seam; the stock pad-parameter registrar (FUN_0808c158) with master_register /
clipwin_register in it, the stock pad-store builder (FUN_08093f20) with the defaults chain in it, master_alloc; the
stock knob binder (FUN_080a7ee0), set-value, the turn (FUN_080b0d54) and list-widget (FUN_080b9a3c) paths with
clipwin_format / clipwin_turn in them, the stock ring push and speed, stepper and snprintf; both thunks entered as their
sites enter them; the Waveform screen's setup (FUN_080a54a0: its bind block, FUN_080a53a2 and the refresh, with
clipwin_bind / clipwin_zoom / clipwin_wave in them), the view's two handlers (the knob event, the param-changed refresh,
the forward to the app with JOEBOX's slice_forward in it, the zoom message), the waveform's slice-marker and zoom setters,
and the app's SetCellParam (FUN_0809fa50) for what the forward sends; the Clip Window's maths in bank 2 (clipwin_b2.c,
every hook's since D-018), and a bank 2 whose header is gone from the start (every hook then stock's). Every scenario
also runs on this image with the clipwin hooks taken out at run time (or only Region's), and the Slip 0 ones on the
stock 3.1.9 image, for the comparisons; a Region scenario also runs on the stock image with a file as long as its
region.
Stubbed: the allocator, the log print, for the Waveform screen the app's copy of the pad's store into the view, the file
name, icons, buttons and the mode list, SetCellParam's posts to the engine and the UI (recorded), the sample source (length, rate, ready, the prefetch hint - recorded, with the
read it was made in - and the mono / stereo fetch, which serve a ramp: frame q holds (q + 1) * 2^-20, the right channel
its negative, or 1.0 for the gain runs; in the reader unit two sines, the file or the file turned circular), the knob's
text widget, redraw and post to the app (recorded).
Reference: the research harness's stock measurements (notes/re/a2: launch on the bar at 288 000 with +0x140 = 11 520
and msg 0x1d, a launch 300 samples late at once with +0x140 = 11 532, steps at (int)(j x fps), Sync None restarting
every len - 257 samples) and its model's assertions (a2/r2/k_slip.py, k_live.py, droplaunch.py, armed.py): every
sounding sample plays (stock frame + slip_f) mod len, the summed gain is stock's - a launch waiting for its bar when
Slip changes included; for a region (a2/r2/k_region.py, k_seam.py), stock playing a file as long as the region
(every sample at rs + (its frame + slip_f) mod vlen, the same gain away from the wraps; every recompute field), a
change heard from the next wrap on (the one after when made in the last Sync step; the next on its own grid when it
moves the wrap grid, against stock's live Beat Count change, which doubles) with no silence added, and no zero-gain
sample nor doubling at a seamless wrap, a clip of one step included; for Loop Len (a2/r2/k_looplen.py), the model's
numbers (the in-point from the sounding segment's phase, a forced Sync re-gridding the playing segment, the launch held
until it has sounded), the review's cases with absolute frames (a 44.1 kHz file whose re-indexed step runs ahead of its
position, Off and on within a step, a stop and relaunch, Sync None) and every segment starting on (int)((float)w x
fps) for the window's step w, then playing on, the gain of the run without it where Sync is not forced, no zero-gain
sample added where it is; for
the reader, the stock reader on the file turned circular; for a machine-mode pad, filter.c's
own clip_read on the file turned circular (at the seam, on the last blocks before it, near the start: bit for bit) and
test_clip.py's drop-sample model off the seam; for the seam hint, notes/re/a2's provider (a hint covers the block of
its position and the next two: 16 384 frames sure); for the Waveform knobs, stock's own Loop Start / End knobs in Sample
mode at the same zoom (the same posts, steps, ranges and positions, turn after turn), the bare Slip knob (the same values
with every turn sent to the app and refreshed), and the screen with the three hooks taken out in every other mode.
NOT checked: duck_block and the control tick around clipwin_tick (only its place in duck_block, from the image); a
negative value through preset save / load; how the waveform draws the bracket (only the widget's fields and dirty flag
are checked: its draw gates the bracket on +0x239 alone, notes/re/a3), the zoom a pinch leaves pending until the
waveform's tick applies it and posts 0xe5 (the message is sent here), the dead travel at the top of a type-0xd knob on
the hardware (stock's, open question 16); SD streaming at
the seam (the source is in RAM: the hints are checked - H1's, and H2's one at rs per crossing segment - not whether the
unit's cache still holds the hinted blocks when the read gets there: the miss counter 0x24013930, on the unit); Fidelity
machine modes inside the whole process (the reader alone is); the playhead on the waveform (left stock); relaunches at
the other recompute sites beyond the retriggers (a pad relaunched while it plays keeps its region: not run); Loop Len
with Pitch (rate != 1 is run once, a 44.1 kHz file), with a region change or a Beat Count change while it is engaged,
and a Trigger / Gate relaunch while it is engaged; whether a preset load stops a pad (Loop Len's in-point resets on a
stopped pad); the app's
loader and Pad Mode change feeding the class-H object (posted here as the app posts them, x3); the knob's counts per
revolution on the hardware (the acceleration's K); how it sounds; CPU on the chip.
"""
import re
import struct
import subprocess
import sys

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R8, UC_ARM_REG_R11, UC_ARM_REG_S0,
                               UC_ARM_REG_SP, UC_ARM_REG_LR)

from emu import BASE, RET, STACK, Emu

IMAGE = "out/solo+slice+duck+chord+cond+filter+cpu+od+comp+seqfix+fx2+munchi+master+fault+cave/BLACKBOX.bin"
STOCK = "firmware/BLACKBOX-3.1.9.bin"
e = Emu(IMAGE, "out/cave.elf")
img, stock = open(IMAGE, "rb").read(), open(STOCK, "rb").read()
S = e.sym

P_SLIP, P_REGION, P_LOOPLEN, P_SYNC = 0x1C9, 0x1C8, 0x1CA, 0x94
AUTO, FILE, LOOP = 0, 1, 2                           # Region's list
APP = 0x24020088
APP_PADS = APP + 0x1840
GUI_MS = 0x2402EEE0
PMEM, PCHECK, KEY = 0x38800F70, 0x38800F74, 0x5052534D
BLOCK = 0xC0000000                                   # master.c's boot-time SDRAM block, here
BANK = BLOCK + 0x56800 + 0x2D100                     # clipwin.c's cw_bank in it
B_SLIP, B_PAD, B_VALID, B_LATCH, B_H1, B_HINTED = 8, 0x48, 0x88, 0x98, 0x498, 0x4A8
B_WRAP, B_REGION, B_GOOD, B_ORIGIN, B_LL, B_FORCED, B_SF = 0x4BE, 0x4C0, 0x540, 0x5C0, 0x600, 0x610, 0x620
B_ZERO_AT, B_ZERO_DIR, B_KNOB_COUNTS, B_KNOB_SPEED = 0x4B8, 0x4BC, 0x720, 0x722   # the Slip knob's (clipwin_turn)
B_SIZE = 0x724                                       # sizeof(struct cw_bank)
CW_MAGIC = 0x43574E35
HEAP = 0xC1000000
ARR = 0x24072000                                     # the stores' entry arrays, 0x100 a pad
N = 128
RAMP = 2.0 ** -20
CTOR, PSET, BLOCKM, ADVANCE = 0x080640D0, 0x08067648, 0x08068C64, 0x080696D8
H_CTOR, RECOMPUTE = 0x08055450, 0x08064A94
PREFETCH, SRC_LEN, FETCH, FETCH2 = 0x0806375C, 0x080636F0, 0x08063634, 0x08063608
SITE_H1, SITE_H1P, SITE_READ, SITE_MIX_L, SITE_MIX_R = 0x0806578C, 0x0806541A, 0x08066622, 0x080666E2, 0x080666FA
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


def info(text):
    print("     " + text)


def maps(m):
    """what the class-B code and the cave touch beyond emu.py's map: ITCM/DTCM/SRAM, backup SRAM + RCC, WWDG, SDRAM"""
    for a, n in ((0x00000000, 0x10000), (0x20000000, 0x80000), (0x30000000, 0x48000), (0x38000000, 0x10000),
                 (0x38800000, 0x1000), (0x58024000, 0x1000), (0x50003000, 0x1000), (0xC0000000, 0x1800000)):
        m.uc.mem_map(a, n)


def sdram(m, on=True):
    m.w32(PMEM, BLOCK if on else 0)
    m.w32(PCHECK, (BLOCK ^ KEY) if on else 0)


def store(m, q, vals):
    """the app's settings store of pad q (row q // 4, col q % 4): {id: value}. The Slip row's value is the content's
    shift, + = ahead (D-016: clockwise on the knob, like a CDJ jog), the number every check below reasons in."""
    return store_raw(m, q, vals)


def store_raw(m, q, vals):
    """the app's settings store of pad q, values as the app keeps them"""
    rows = sorted(vals.items())
    at = ARR + q * 0x100
    m.uc.mem_write(at, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
    s = APP_PADS + (q // 4) * 0xF0 + (q % 4) * 0x30
    m.w32(s + 4, at)
    m.uc.mem_write(s + 10, struct.pack("<H", len(rows)))


def slips(m, d):
    for q in range(16):
        store(m, q, {0x4: 500, P_SLIP: d.get(q, 0)})


def u32(m, a):
    return m.r32(a) & 0xFFFFFFFF


def bank_slip(m, q):
    return m.r32(BANK + B_SLIP + 4 * q)


def bank_valid(m, q):
    return m.r8(BANK + B_VALID + q)


L_SIZE = 16                                          # struct cw_latch: rs, vlen, delta, len


def latch(m, q, k):
    """(rs, vlen, delta)"""
    return struct.unpack("<3i", m.uc.mem_read(BANK + B_LATCH + (q * 4 + k) * L_SIZE, 12))


def made_for(m, q, k):
    """the file length a latch was made for"""
    return m.r32(BANK + B_LATCH + (q * 4 + k) * L_SIZE + 12)


def slip_f(slip, length, clip):
    return (slip * length // clip) % length


# ====================================================================================================== 1. the image
def branch(at, data=img):
    """target of the 4-byte bl / b.w at `at`, and which one it is"""
    h1, h2 = struct.unpack_from("<HH", data, at - BASE)
    s = (h1 >> 10) & 1
    i1, i2 = 1 - (((h2 >> 13) & 1) ^ s), 1 - (((h2 >> 11) & 1) ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    off -= (1 << 25) if s else 0
    kind = "bl" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0xD000 else "b.w" if h1 >> 11 == 0b11110 and h2 & 0xD000 == 0x9000 else "?"
    return kind, at + 4 + off


cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def code(name, n):
    a = S[name]
    return [(i.address, i.mnemonic, i.op_str) for i in cs.disasm(img[a - BASE:a - BASE + n], a)]


sites = {"H1 (segment start, FUN_08065550)": (0x0806578C, PREFETCH, "clipwin_seg_start_b"),
         "H1' (slice segment start, FUN_08065290)": (0x0806541A, PREFETCH, "clipwin_slice_start_b"),
         "H3 (the recompute's first length: Beat Count Auto, frames per step)": (0x08064B2C, SRC_LEN, "clipwin_len_recompute_b"),
         "H3 (the recompute's second length: the file tempo; a clip of one step timed by the clip)": (0x08064C5A, SRC_LEN, "clipwin_len_steps_b"),
         "H3 (FUN_08065550's length > 0 check)": (0x0806561E, SRC_LEN, "clipwin_len_b"),
         "H3 (the last step's end)": (0x08065690, SRC_LEN, "clipwin_len_end_b"),
         "H3' (the synced wrap's recompute)": (0x08066FAC, RECOMPUTE, "clipwin_wrap_b"),
         "H3' (the unsynced wrap's recompute)": (0x08066E9E, RECOMPUTE, "clipwin_wrap_free_b"),
         "F (set-value text, FUN_080b0728)": (0x080B0746, 0x080B0528, "clipwin_format"),
         "F (type-1 turn text)": (0x080B0E18, 0x080B0528, "clipwin_format"),
         "K (type-1 turn stepper)": (0x080B0DDE, 0x080B0B74, "clipwin_turn"),
         "W (the Waveform's Clip bind block, its last unbind: BR)": (0x080A582A, 0x080A7EE0, "clipwin_bind"),
         "W (FUN_080a53a2: the position knobs at every bind and zoom change)": (0x080A53B0, 0x080A52C4, "clipwin_zoom"),
         "W (the Waveform refresh's Clip case: the slice markers)": (0x080A5B0E, 0x080C6E8C, "clipwin_wave")}
for what, (at, was, now) in sites.items():
    check(f"{what} at {at:#010x}: stock 'bl {was:#010x}' is now 'bl {now}'",
          branch(at, stock) == ("bl", was) and branch(at) == ("bl", S[now]), (branch(at, stock), branch(at)))
check("H2: the segment reader's call at 0x08066622 is still JOEBOX's 'bl clip_read_b' (stock: bl 0x080662e4)",
      branch(0x08066622, stock) == ("bl", 0x080662E4) and branch(0x08066622) == ("bl", S["clip_read_b"]))
c = code("clip_read_b", 8)
check("clip_read_b: 'add.w r1, fp, #0x14c' then 'b.w clipwin_read' (was b.w clip_read)",
      [x[1] for x in c] == ["add.w", "b.w"] and c[0][2] == "r1, fp, #0x14c" and branch(c[1][0]) == ("b.w", S["clipwin_read"]), c)
for thunk, slot, target in (("clipwin_seg_start_b", "#0x20", "clipwin_seg_start"), ("clipwin_slice_start_b", "#4", "clipwin_slice_start")):
    c = code(thunk, 8)
    check(f"{thunk}: r2 = the slot at [sp, {slot}], r3 = r4 (the pad), then b.w {target}",
          [(x[1], x[2]) for x in c[:2]] == [("ldr", f"r2, [sp, {slot}]"), ("mov", "r3, r4")] and branch(c[2][0]) == ("b.w", S[target]), c)
for thunk, site in (("clipwin_len_recompute_b", 1), ("clipwin_len_b", 0), ("clipwin_len_end_b", 2)):
    c = code(thunk, 8)
    check(f"{thunk}: r1 = r4 (the pad), r2 = site {site}, then b.w clipwin_len (r0, the source, as the caller set it)",
          [(x[1], x[2]) for x in c[:2]] == [("mov", "r1, r4"), ("movs", f"r2, #{site}")] and branch(c[2][0]) == ("b.w", S["clipwin_len"]), c)
c = code("clipwin_len_steps_b", 10)
check("clipwin_len_steps_b: r1 = r4 (the pad), r2 = site 3, r3 = r9 (the clip in output samples at 0x08064c5a), then b.w "
      "clipwin_len", [(x[1], x[2]) for x in c[:3]] == [("mov", "r1, r4"), ("movs", "r2, #3"), ("mov", "r3, sb")]
      and branch(c[3][0]) == ("b.w", S["clipwin_len"]), c)
c = code("clipwin_wrap_b", 6)
c2 = code("clipwin_wrap_free_b", 6)
check("clipwin_wrap_b: r2 = sp + 0x58 (the render's tick of the next pass), clipwin_wrap_free_b: r2 = 0; then b.w clipwin_wrap "
      "(r0, r1 as the caller set them)", [(x[1], x[2]) for x in c[:1]] == [("add", "r2, sp, #0x58")] and branch(c[1][0]) == ("b.w", S["clipwin_wrap"])
      and [(x[1], x[2]) for x in c2[:1]] == [("movs", "r2, #0")] and branch(c2[1][0]) == ("b.w", S["clipwin_wrap"]), (c, c2))
# the stock facts the two thunks rely on: r9 at 0x08064c5a is the clip in output samples ([sp + 0x20], FUN_08070420's
# output, loaded at 0x08064bac on every path, the Beat Count one through 0x08064e58), and the render's tick of the next
# pass is at [sp + 0x58] when it calls the recompute at the synced wrap (stored at 0x08064f2e/32, snapped at 0x08066f92/6)
words = lambda a, n: struct.unpack_from(f"<{n}H", stock, a - BASE)
check("stock: 'ldr.w r9, [sp, #0x20]' at 0x08064bac (after FUN_08070420 at 0x08064b9e and 0x08064e54, whose output is "
      "[sp + 0x20]); nothing between it and 0x08064c5a writes r9 or [sp + 0x20]; the synced wrap stores the tick at "
      "[sp + 0x58] (0x08066f2e, 0x08066f92, 0x08066f96) and calls the recompute with sp unchanged",
      [(i.mnemonic, i.op_str) for i in cs.disasm(stock[0x08064BAC - BASE:0x08064BB0 - BASE], 0x08064BAC)] == [("ldr.w", "sb, [sp, #0x20]")]
      and not any((not i.mnemonic.startswith(("str", "vstr", "cmp")) and i.op_str.split(",")[0].strip("{ ") == "sb") or "sb" in i.op_str and
                  i.mnemonic.startswith("pop") or i.mnemonic.startswith(("str", "vstr")) and "[sp, #0x20]" in i.op_str
                  for i in cs.disasm(stock[0x08064BB0 - BASE:0x08064C5A - BASE], 0x08064BB0))
      and sum(1 for _ in cs.disasm(stock[0x08064BB0 - BASE:0x08064C5A - BASE], 0x08064BB0)) > 50
      and [(i.mnemonic, i.op_str) for i in cs.disasm(stock[0x08066F2E - BASE:0x08066F36 - BASE], 0x08066F2E)] == [("str.w", "r8, [sp, #0x58]"), ("str.w", "sb, [sp, #0x5c]")]
      and [(i.mnemonic, i.op_str) for i in cs.disasm(stock[0x08066F92 - BASE:0x08066F9A - BASE], 0x08066F92)] == [("strd", "r0, r3, [sp, #0x58]"), ("strd", "r4, r2, [sp, #0x58]")]
      and not any(i.mnemonic in ("push", "pop", "sub", "add") and "sp" in i.op_str.split(",")[0] for i in cs.disasm(stock[0x08066F9A - BASE:0x08066FAC - BASE], 0x08066F9A)))
sizes = {l.split()[3]: int(l.split()[1], 16) for l in subprocess.run(["arm-none-eabi-nm", "-S", "out/cave.elf"], capture_output=True,
                                                                    text=True, check=True).stdout.splitlines() if len(l.split()) == 4}
duck = code("duck_block", sizes["duck_block"])
order = [int(x[2].lstrip("#"), 16) for x in duck if x[1] == "bl"]
tail = img[S["duck_block"] - BASE:S["duck_block"] - BASE + sizes["duck_block"]]
at_tick = [i for i, x in enumerate(duck) if x[1] == "bl" and int(x[2].lstrip("#"), 16) == S["clipwin_tick"]] or [1]
r4_writes = [x for x in duck[:at_tick[0]] if x[2].split(",")[0].strip() == "r4" and not x[1].startswith(("str", "cmp", "tst"))]
check("duck_block: lfo_tick, insert_tick, then clipwin_tick (once a block, before the pads) with r0 = the engine (duck_block's "
      "own r0, kept in r4: 'mov r4, r0' is the only write to r4 before it), then the tail call into the engine's control tick (0x08053164)",
      order[-3:] == [S["lfo_tick"], S["insert_tick"], S["clipwin_tick"]] and order.count(S["clipwin_tick"]) == 1
      and struct.pack("<I", 0x08053165) in tail and duck[at_tick[0] - 1][1:] == ("mov", "r0, r4")
      and [x[1:] for x in r4_writes] == [("mov", "r4, r0")], ([hex(t) for t in order], duck[at_tick[0] - 1], r4_writes))
for page in (0x080EF990, 0x080EF288):
    got = struct.unpack_from("<36H", img, page - BASE)
    check(f"Clip Pos page at {page:#010x}: Loop Mode, Beat Count, Quant Size, Sync, Region (0x1c8), Slip (0x1c9), Loop Len "
          "(0x1ca), then 29 empty slots", got == (0x8D, 0xD2, 0x47, 0x94, P_REGION, P_SLIP, P_LOOPLEN) + (0,) * 29
          and struct.unpack_from("<36H", stock, page - BASE) == (0x8D, 0xD2, 0x47, 0x94) + (0,) * 32, [hex(x) for x in got[:8]])
touched = {"FUN_08065550": (0x08065550, 936, [0x0806561E, 0x08065690, 0x0806578C]), "FUN_08065290": (0x08065290, 688, [0x0806541A]),
           "FUN_08064a94 (recompute)": (0x08064A94, 0x3C8, [0x08064B2C, 0x08064C5A]),
           "FUN_080667b8 (render; filter.py's filter_voice_b at 0x080669d6)": (0x080667B8, 0x860, [0x080669D6, 0x08066E9E, 0x08066FAC]),
           "FUN_08066454": (0x08066454, 856, [0x08066622]), "FUN_080662e4 (stock clip reader)": (0x080662E4, 368, []),
           "FUN_080b0728": (0x080B0728, 36, [0x080B0746]), "FUN_080b0d54": (0x080B0D54, 772, [0x080B0DDE, 0x080B0E18]),
           "FUN_080a54a0 (the Waveform setup; slice.py's four Slicer hooks in it too)":
               (0x080A54A0, 0x6F0, [0x080A582A, 0x080A5B0E, 0x080A58E6, 0x080A58F2, 0x080A58FE, 0x080A5B64]),
           "FUN_080a53a2": (0x080A53A2, 0x16, [0x080A53B0]),
           "the Clip Pos page": (0x080EF990, 72, [0x080EF998, 0x080EF99A, 0x080EF99C]),
           "its class-0x4c copy": (0x080EF288, 72, [0x080EF290, 0x080EF292, 0x080EF294])}
for name, (start, size, at) in touched.items():
    allowed = {a + i for a in at for i in range(4 if a < 0x080EF000 else 2)}
    diff = {start + i for i in range(size) if img[start - BASE + i] != stock[start - BASE + i]}
    check(f"{name}: no stock byte changes outside the hook sites ({', '.join(hex(a) for a in at) or 'none'})",
          diff <= allowed and (not at or diff), sorted(hex(a) for a in diff - allowed))

# ---- master_alloc: the bank is cleared at every boot and fits the block
maps(e)
allocs = []
e.stub(0x0806AA80, lambda: allocs.append(("line", e.arg(0), e.arg(1))))
e.stub(0x0804436C, lambda: allocs.append(("perm", e.arg(0))), value=BLOCK)
e.w32(BANK, CW_MAGIC)
e.call("master_alloc", 0x24076000, 192000)
e.meter_up()
check(f"master_alloc: one 0x84100-byte block, cw_bank's 0x800 bytes at its end (+0x83900; it uses {B_SIZE:#x}), its magic "
      "cleared each boot",
      allocs[-1] == ("perm", 0x84100) and BANK + 0x800 == BLOCK + 0x84100 and u32(e, BANK) == 0, (allocs, hex(u32(e, BANK))))
del e.stubs[0x0806AA80], e.stubs[0x0804436C]

# ====================================================================================================== 2. registration
regs = []


lists = {}


def registrar(m, table):
    """the stock pad-parameter registrar run whole; every registration recorded at the one writer (FUN_0808c0a8), and
    each list's entry names at the list registrar (FUN_0808c0d8: r3 names, [sp] count) into `lists`"""
    out = []

    def names():
        sp = m.uc.reg_read(UC_ARM_REG_SP)
        lists[m.arg(1)] = [m.cstr(u32(m, m.arg(3) + 4 * i)) for i in range(m.r32(sp))]
    m.uc.hook_add(UC_HOOK_CODE, lambda *a: names(), begin=0x0808C0D8, end=0x0808C0D8)

    def write():
        a = m.arg(1)
        pid, typ = m.r16(a), m.r8(a + 2)
        lab, lo, hi, xml = u32(m, a + 4), m.r32(a + 0x10), m.r32(a + 0x14), u32(m, a + 0x18)
        out.append((pid, typ, m.cstr(lab) if lab else None, lo, hi, m.cstr(xml) if xml else None))
    m.uc.hook_add(UC_HOOK_CODE, lambda *a: write(), begin=0x0808C0A8, end=0x0808C0A8)
    m.stub(0x0804436C, value=table)
    m.call(0x0808C158, 0, count=20_000_000)
    del m.stubs[0x0804436C]
    return out


TABLE = 0x24040000
regs = registrar(e, TABLE)
st_m = Emu(STOCK, "out/cave.elf")
maps(st_m)
stock_regs = registrar(st_m, TABLE)
ours = [r for r in regs if r[0] == P_SLIP]
check("the patched registrar registers 0x1c9 once: 'Slip:', type 1 (int), -3840 .. 3840, saved as 'clipslip'",
      ours == [(P_SLIP, 1, "Slip:", -3840, 3840, "clipslip")], ours)
region_reg = [r for r in regs if r[0] == P_REGION]
list_type = {r[1] for r in regs if r[0] == 0xF1}                # Fidelity, a stock-registrar list (filter.c)
check(f"... and 0x1c8 once, before it: 'Region:', a list (type {region_reg[0][1] if region_reg else None}, as Fidelity's) of "
      f"{lists.get(P_REGION)}, saved as 'clipregion'", len(region_reg) == 1 and region_reg[0][2] == "Region:"
      and region_reg[0][5] == "clipregion" and {region_reg[0][1]} == list_type and lists.get(P_REGION) == ["Auto", "File", "Loop"]
      and regs.index(region_reg[0]) < regs.index(ours[0]), (region_reg, list_type, lists.get(P_REGION)))
ll_reg = [r for r in regs if r[0] == P_LOOPLEN]
LL_NAMES = ["Off", "1/16", "1/8", "1/4", "1/2", "1 bar", "2 bars", "4 bars"]
check(f"... and 0x1ca once, after Slip: 'Loop Len:', a list of {lists.get(P_LOOPLEN)} (stock's own strings), saved as "
      "'cliplooplen'", len(ll_reg) == 1 and ll_reg[0][2] == "Loop Len:" and ll_reg[0][5] == "cliplooplen"
      and {ll_reg[0][1]} == list_type and lists.get(P_LOOPLEN) == LL_NAMES and regs.index(ll_reg[0]) > regs.index(ours[0]),
      (ll_reg, lists.get(P_LOOPLEN)))
check("the labels fit the screen (<= 9 characters)", ours and len(ours[0][2]) <= 9 and region_reg and len(region_reg[0][2]) <= 9
      and ll_reg and len(ll_reg[0][2]) <= 9)
check("stock registers nothing in 0x1c8 .. 0x1cf; the patched image only 0x1c8, 0x1c9 and 0x1ca there",
      not [r for r in stock_regs if 0x1C8 <= r[0] <= 0x1CF] and sorted(r[0] for r in regs if 0x1C8 <= r[0] <= 0x1CF) == [P_REGION, P_SLIP, P_LOOPLEN],
      [hex(r[0]) for r in regs if 0x1C8 <= r[0] <= 0x1CF])
xmls = [r[5] for r in regs if r[5]]
dups = sorted({x for x in xmls if xmls.count(x) > 1})
stock_xmls = [r[5] for r in stock_regs if r[5]]
check("'clipslip', 'clipregion' and 'cliplooplen' are unique among every registered xml name (and new to the image)",
      all(xmls.count(x) == 1 and x not in stock_xmls and x.encode() not in stock for x in ("clipslip", "clipregion", "cliplooplen")))
if dups:
    info(f"xml names registered more than once (stock's own: {sorted({x for x in stock_xmls if stock_xmls.count(x) > 1})}): {dups}")
check(f"the patched registrar still registers stock's {len(stock_regs)} ids under their stock xml names (JOEBOX relabels a few)",
      {(r[0], r[5]) for r in stock_regs} <= {(r[0], r[5]) for r in regs}, sorted({(r[0], r[5]) for r in stock_regs} - {(r[0], r[5]) for r in regs}))

# ---- the type-3 (pad) store built by the stock builder, with lfo_defaults -> insert_defaults -> clipwin_defaults in it
PSTORE, TYPE, PARR = 0x24073000, 0x24073100, 0x24074000
e.uc.mem_write(PSTORE, bytes(0x20))
e.uc.mem_write(TYPE, b"\x03")
e.stub(0x0804436C, lambda: e.uc.mem_write(PARR, bytes(e.arg(0))), value=PARR)
e.call(0x08093F20, PSTORE, TYPE)
del e.stubs[0x0804436C]
count, cap = e.r16(PSTORE + 10), e.r16(PSTORE + 12)
entries = [struct.unpack_from("<HHi", bytes(e.uc.mem_read(PARR + 8 * i, 8))) for i in range(count)]
ids = [x[0] for x in entries]
check(f"a new pad's store (FUN_08093f20, type 3) holds Region 0 (Auto), Slip 0 and Loop Len 0 (Off) once each ({count} of "
      f"{cap} entries used)", all(ids.count(p_) == 1 and entries[ids.index(p_)][2] == 0 for p_ in (P_REGION, P_SLIP, P_LOOPLEN))
      and cap == 96 and count < cap,
      (count, cap, ids[-4:]))

# ====================================================================================================== the poll (unit)
sdram(e)
e.uc.mem_write(BANK, bytes(0x800))
values = {0: 960, 1: -30, 2: 7, 3: 3839, 4: -3840, 5: 5000, 6: -9999, 9: 1}
for q in range(16):
    store(e, q, {0x4: 500} if q == 7 else {0x4: 500, P_SLIP: values.get(q, 0)})
e.call("clipwin_tick", 0)
check(f"clipwin_tick with a fresh block: the bank is set up (magic '{CW_MAGIC.to_bytes(4, 'big').decode()}') and one pad "
      "polled per call",
      u32(e, BANK) == CW_MAGIC and e.r32(BANK + 4) == 1 and bank_slip(e, 0) == 960 and bank_slip(e, 1) == 0,
      (hex(u32(e, BANK)), e.r32(BANK + 4), bank_slip(e, 0), bank_slip(e, 1)))
# a bank left by another layout (SDRAM keeps its contents through a reset; master_alloc clears only the magic): the
# first call clears all of cw_bank, and nothing past it
e.uc.mem_write(BANK, b"\xa5" * 0x800)
e.w32(BANK, CW_MAGIC - 1)
e.call("clipwin_tick", 0)
got = bytes(e.uc.mem_read(BANK, 0x800))
check(f"a stale bank (the magic of another layout, every other byte 0xa5): the first call zeroes all {B_SIZE:#x} bytes of "
      f"cw_bank but what that poll wrote (magic, scan 1, pad 1's Slip 960), and leaves the rest of its 0x800 alone",
      u32(e, BANK) == CW_MAGIC and e.r32(BANK + 4) == 1 and bank_slip(e, 0) == 960
      and got[8 + 4:B_SIZE] == bytes(B_SIZE - 12) and got[B_SIZE:] == b"\xa5" * (0x800 - B_SIZE),
      (hex(u32(e, BANK)), e.r32(BANK + 4), bank_slip(e, 0), [hex(i) for i in range(12, B_SIZE) if got[i]][:4]))
for _ in range(15):
    e.call("clipwin_tick", 0)
want = [max(-3840, min(3840, values.get(q, 0))) for q in range(16)]
check("sixteen calls read all sixteen pads' stores (row * 0xf0 + col * 0x30), clamped to +-3840; a store without the id reads 0",
      [bank_slip(e, q) for q in range(16)] == want, [bank_slip(e, q) for q in range(16)])

# the guarded drop on a cached pad
UPAD = 0x24060000


def upad(q, cls=0x4C):
    e.uc.mem_write(UPAD, bytes(0xC00))
    e.uc.mem_write(UPAD + 4, bytes([cls]))
    e.w32(UPAD + 0x18, (q // 4) << 8 | q % 4)
    for k, (act, done, delay, first) in enumerate(((1, 0, 500, 0), (1, 0, 500, 1), (1, 0, 0, 0), (0, 0, 500, 0))):
        b = UPAD + 0x30 + k * 0x70
        e.uc.mem_write(b, bytes([act, done]))
        e.w32(b + 0x20, delay)
        e.uc.mem_write(b + 0x3C, bytes([first]))
    e.w32(BANK + B_PAD + 4 * q, UPAD)


def done():
    return [e.r8(UPAD + 0x31 + k * 0x70) for k in range(4)]


def tick_until(q):
    for _ in range(16):
        e.call("clipwin_tick", 0)
        if (e.r32(BANK + 4) - 1) & 15 == q:
            return


upad(9)
store(e, 9, {0x4: 500, P_SLIP: 480})
tick_until(9)
check("a Slip change drops the pad's pending segment (active, not done, delay > 0) and nothing else: not a pending "
      "launch (+0x3c set), not the sounding one (delay 0), not an inactive slot", done() == [1, 0, 0, 0] and bank_slip(e, 9) == 480, done())
upad(9)
tick_until(9)
check("the same value polled again: no drop", done() == [0, 0, 0, 0], done())
for what, cls, cell_q in (("a cached object that is not a class-B pad", 0x48, 9), ("a cached pad whose cell moved", 0x4C, 10)):
    upad(9, cls)
    e.w32(UPAD + 0x18, (cell_q // 4) << 8 | cell_q % 4)
    store(e, 9, {0x4: 500, P_SLIP: -480 if cell_q == 9 else 300})
    tick_until(9)
    check(f"{what}: the new value is taken, nothing is dropped", done() == [0, 0, 0, 0] and bank_slip(e, 9) in (-480, 300), done())
sdram(e, False)
e.uc.mem_write(BANK, bytes(16))
e.call("clipwin_tick", 0)
check("no SDRAM block (master_alloc did not run): clipwin_tick writes nothing", bytes(e.uc.mem_read(BANK, 16)) == bytes(16))


# ====================================================================================================== the rig
POS, SID, AT, FET = 2, 6, 7, 12          # a read row: block, slot, POSition (virtual), n, rate, frac, Segment ID, the
#                                         sample it sounds AT; then return, used, frac, buffer, its FETches, clip_read ran


def no_bank2(m, entered):
    """bank 2's header wiped on emulator m before its first b2_live() (which caches the verdict for the boot), and every
    entry into a bank-2 cw_* function appended to `entered`"""
    m.uc.mem_write(0x08100000, bytes(16))
    for fn in CW_FUNCS:
        m.uc.hook_add(UC_HOOK_CODE, lambda *a, fn=fn: entered.append(fn), begin=S[fn] & ~1, end=S[fn] & ~1)


CW_FUNCS = sorted(n for n in S if n.startswith("cw_") and 0x08100000 <= S[n] < 0x08200000)


class Rig:
    """The class-B pad process block by block (notes/re/a2's Rig, with a1's Rig2 input-bank buffers), on an Emu.

    One pad, one engine; pre_block runs where duck_block would (clipwin_tick), then the block method, then the clock
    advance. Logs: reads at the segment reader's call (block, slot, virtual position, n, rate, frac, then the result:
    return, used, frac, buffer, the fetches made inside it, whether filter.c's clip_read ran), fetches, prefetches,
    every segment start (H1 and H1'), each segment's mixed samples, the summed output, the messages to the app.
    h: the cell's class-H object too (real ctor, linked at pad + 8 as the graph builder links it; its block method runs
    after the pad's and reads the same queue, so loop points posted there land in it, notes/re/x3). bypass: every
    clipwin hook taken out at run time; region_off: only Region's (H3, H3'), which leaves v1 (Slip). bank2=False: bank
    2's header wiped before anything runs, so the first b2_live() (the first poll, or the first recompute) says no and
    keeps saying it, as on a unit without this build's BBEXTRA.BIN; every entry into a cw_* function is counted in
    b2_entered."""

    def __init__(self, frames=96000, src_rate=48000, bpm=120.0, stereo=False, cell=0, image=IMAGE, block=True,
                 bypass=False, dc=False, h=False, region_off=False, bank2=True):
        self.m = m = Emu(image, "out/cave.elf")
        uc = self.uc = m.uc
        maps(m)
        self.b2_entered = []
        if not bank2:
            no_bank2(m, self.b2_entered)
        self.patched = image == IMAGE
        self.heap = HEAP
        self.len, self.src_rate, self.stereo, self.dc = frames, src_rate, stereo, dc
        self.q = (cell >> 8 & 3) * 4 + (cell & 3)
        sdram(m, block)
        m.stubs[0x0804436C] = lambda: m.ret(self.alloc(m.arg(0)))
        m.stub(0x08043DE4, value=0)
        self.src = self.alloc(0x40)
        m.w32(self.src + 0x24, 0x1234)
        uc.mem_write(self.src + 0x1C, bytes([int(stereo)]))
        m.stubs[SRC_LEN] = lambda: m.ret(self.len)
        m.stubs[0x0806377C] = lambda: m.ret(self.src_rate)
        m.stub(0x0806371C, value=1)
        self.prefetches, self.fetches, self.hints, self.reading = [], [], [], None
        m.stub(PREFETCH, self._prefetch, value=0)
        m.stub(FETCH, self._fetch_mono, value=0)
        m.stub(FETCH2, self._fetch_stereo, value=0)
        self.engine = eng = self.alloc(0x30000, 0x100)
        self.ctx = ctx = eng + 0x128E0
        m.w32(ctx, eng)
        uc.mem_write(eng + 0x18, struct.pack("<f", bpm))
        uc.mem_write(eng + 0x38, b"\x01")
        self._buffers()
        self.pad = pad = self.alloc(3000)
        m.call(CTOR, pad)
        m.w32(pad + 0x24, self.src)
        m.w32(pad + 0x18, cell)
        uc.mem_write(pad + 0xB79, b"\x01")
        self.h = None
        if h:
            self.h = H = self.alloc(0x5C4)
            m.call(H_CTOR, H)
            m.w32(H + 0x18, cell)
            shared = self.alloc(0x10)                         # engine + 0x2c74: {key map, source entries}
            m.w32(shared + 4, self.alloc(0x7500))
            m.w32(H + 0x20, shared)
            m.w32(pad + 8, H)
        self.queue = ctx + {0x400: 4, 0x401: 0x608}.get(cell, ((cell >> 8 & 0xFF) + ((cell & 0xFF) + (cell >> 16) * 4) * 4 + 2) * 0x604 + 4)
        self.block, self._S0 = 0, 0
        self.posted, self.reads, self.mix, self.out, self.made = [], [], [], [], []
        self.pre_block = None
        self.sid, self.nsid, self.cur, self.in_clip_read = {}, 0, None, False
        for a, fn in ((SITE_H1, self._on_h1), (SITE_H1P, self._on_h1p), (SITE_READ, self._on_read),
                      (SITE_READ + 4, self._on_read_ret), (SITE_MIX_L, lambda: self._on_mix(0)),
                      (SITE_MIX_R, lambda: self._on_mix(1))):
            uc.hook_add(UC_HOOK_CODE, lambda u, a_, s_, d_, fn=fn: fn(), begin=a, end=a)
        if self.patched:
            uc.hook_add(UC_HOOK_CODE, lambda *a: setattr(self, "in_clip_read", True), begin=S["clip_read"], end=S["clip_read"])
        go = lambda target: (lambda: uc.reg_write(UC_ARM_REG_PC, target | 1))
        if bypass and self.patched:
            m.stubs[S["clipwin_seg_start_b"]] = go(PREFETCH)
            m.stubs[S["clipwin_slice_start_b"]] = go(PREFETCH)
            m.stubs[S["clipwin_read"]] = go(S["clip_read"])
            m.stub(S["clipwin_tick"])
        if (bypass or region_off) and self.patched:
            for t in ("clipwin_len_recompute_b", "clipwin_len_steps_b", "clipwin_len_b", "clipwin_len_end_b"):
                m.stubs[S[t]] = go(SRC_LEN)
            for t in ("clipwin_wrap_b", "clipwin_wrap_free_b"):
                m.stubs[S[t]] = go(RECOMPUTE)

    def alloc(self, n, align=8):
        a = (self.heap + align - 1) & ~(align - 1)
        self.heap = a + n
        self.uc.mem_write(a, bytes(n))
        return a

    def _prefetch(self):
        pos = struct.unpack("<i", struct.pack("<I", self.m.arg(1)))[0]
        self.prefetches.append((self.block, pos))
        if self.reading is not None:                          # a hint made inside a segment read (H2): whose read
            self.hints.append((self.block, pos, self.reading))

    def _data(self, pos, n, right=False):
        q = np.arange(pos, pos + n, dtype=np.int64)
        v = np.ones(n) if self.dc else (q + 1) * RAMP * (-1.0 if right else 1.0)
        return np.where((q >= 0) & (q < self.len), v, 0.0).astype(np.float32).tobytes()

    def _fetch_mono(self):
        m = self.m
        dst, n, pos = m.arg(1), m.arg(2), struct.unpack("<i", struct.pack("<I", m.arg(3)))[0]
        self.fetches.append((self.block, pos, n))
        self.uc.mem_write(dst, self._data(pos, n))

    def _fetch_stereo(self):
        m = self.m
        n, pos = m.arg(3), m.r32(self.uc.reg_read(UC_ARM_REG_SP))
        self.fetches.append((self.block, pos, n))
        self.uc.mem_write(m.arg(1), self._data(pos, n))
        self.uc.mem_write(m.arg(2), self._data(pos, n, True))

    def _buffers(self):
        def mk(addr, cap=N):
            l, r = self.alloc(cap * 4), self.alloc(cap * 4)
            self.uc.mem_write(addr, struct.pack("<IIIIBBxx", cap, 0, l, r, 1, 0))
            return l
        for k in range(3):
            mk(self.ctx + 0x151FC + k * 0x14)
        self.buses = [(self.ctx + 0x150E4 + k * 0x14, mk(self.ctx + 0x150E4 + k * 0x14)) for k in range(16)]
        for k, cap in enumerate((N, 0x400, N, N)):         # Rig2: the input bank (the reader's scratch is #1)
            mk(self.ctx + 0x1583C + k * 0x14, cap)

    def i64(self, a):
        return struct.unpack("<q", self.uc.mem_read(a, 8))[0]

    @property
    def S(self):
        return self.i64(self.engine)

    def goto(self, at):
        e_ = self.engine
        self.uc.mem_write(e_ + 8, bytes(16))
        self.uc.mem_write(e_, struct.pack("<q", at - N))
        self.m.call(ADVANCE, e_, N)

    def set_bpm(self, bpm):
        """a tempo change as a re-anchored tempo state looks: origin = (ticks now, samples now)"""
        self.uc.mem_write(self.engine + 8, struct.pack("<qq", self.i64(self.engine + 0x30), self.S))
        self.uc.mem_write(self.engine + 0x18, struct.pack("<f", bpm))

    def post(self, mtype, offset=0, w8=0, wc=0, w10=0, w14=0):
        n = self.m.r32(self.queue + 0x600)
        self.uc.mem_write(self.queue + 0x18 * n, struct.pack("<BxxxIIIII", mtype, offset, w8, wc, w10 & 0xFFFFFFFF, w14))
        self.m.w32(self.queue + 0x600, n + 1)

    def cell(self):
        return u32(self.m, self.pad + 0x18)

    def note_on(self, note=60, vel=100):
        self.post(2, 0, 0, note, vel)

    def param(self, pid, value):
        self.post(0x39, 0, self.cell(), pid, value)

    def params(self, beats=4, quant=3, sync=3, loop=1, launch=2, mode=1):
        for pid, v in ((0x8B, mode), (0x93, launch), (0x8D, loop), (0xD2, beats), (0x47, quant), (0x94, sync)):
            msg = self.alloc(0x18)
            self.uc.mem_write(msg, struct.pack("<BxxxIIII", 0x39, 0, self.cell(), pid, v & 0xFFFFFFFF))
            self.m.call(PSET, self.pad, self.engine, msg, self.ctx)

    def markers(self, frames):
        self.post(0x3C, 0, self.cell(), 0, 1000)
        for f in frames:
            self.post(0x3C, 0, self.cell(), f, 1)

    def _new(self, k, how, step, start, stock_pos, launch=0):
        self.nsid += 1
        self.sid[k] = self.nsid
        ours = self.patched and self.q < 16
        p = self.pad
        self.made.append(dict(sid=self.nsid, k=k, how=how, step=step, start=start, block=self.block, stock_pos=stock_pos, launch=launch,
                              valid_before=(bank_valid(self.m, self.q) >> k) & 1 if self.patched else 0,
                              h1_before=(self.m.r8(BANK + B_H1 + self.q) >> k) & 1 if ours else 0,
                              prefetch_at=len(self.prefetches),
                              # what H1 has to go on: the pad's steps (final here) and the bank's Loop Len
                              tps=self.i64(p + 0x208), n=u32(self.m, p + 0x210),
                              fps=struct.unpack("<f", bytes(self.uc.mem_read(p + 0x1FC, 4)))[0],
                              ll=self.m.r8(BANK + B_LL + self.q) if ours else 0,
                              origin=self.m.r32(BANK + B_ORIGIN + 4 * self.q) if ours else 0))

    def _on_h1(self):
        uc, m = self.uc, self.m
        k = m.r32(uc.reg_read(UC_ARM_REG_SP) + 0x20)
        self._new(k, "H1", uc.reg_read(UC_ARM_REG_R5), self.i64(self.pad + 0x38 + k * 0x70), uc.reg_read(UC_ARM_REG_R1),
                  uc.reg_read(UC_ARM_REG_R8))

    def _on_h1p(self):
        uc, m = self.uc, self.m
        k = m.r32(uc.reg_read(UC_ARM_REG_SP) + 4)
        self._new(k, "H1'", None, None, uc.reg_read(UC_ARM_REG_R1))

    def _on_read(self):
        uc, m = self.uc, self.m
        k = (uc.reg_read(UC_ARM_REG_R4) - self.pad - 0x30) // 0x70
        sp = uc.reg_read(UC_ARM_REG_SP)
        n = m.r32(sp)
        pos = uc.reg_read(UC_ARM_REG_R2) | uc.reg_read(UC_ARM_REG_R3) << 32
        self.cur = (k, n)
        self._ptrs = [u32(m, sp + o) for o in (4, 8, 0x14)]
        self._f0 = len(self.fetches)
        self.in_clip_read = False
        self.reads.append([self.block, k, pos, n, uc.reg_read(UC_ARM_REG_S0), u32(m, self._ptrs[1]), self.sid.get(k),
                           self._S0 + N - n])
        self.reading = self.sid.get(k)

    def _on_read_ret(self):
        m = self.m
        self.reading = None
        self.reads[-1] += [self.uc.reg_read(UC_ARM_REG_R0)] + [u32(m, p) for p in self._ptrs] + \
            [tuple(self.fetches[self._f0:]), self.in_clip_read]

    def _on_mix(self, ch):
        if self.cur is None:
            return
        uc = self.uc
        k, n = self.cur
        if ch == 1 or not self.stereo:
            self.cur = None
        cnt = uc.reg_read(UC_ARM_REG_R1)
        v = np.frombuffer(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0), 4 * cnt)), np.float32).copy()
        self.mix.append((self._S0 + (N - n), self.sid.get(k), ch, v))

    def step_block(self):
        m, uc = self.m, self.uc
        self._S0 = self.S
        if self.pre_block:
            self.pre_block(self)
        z = bytes(N * 4)
        for a, buf in self.buses:
            m.w32(a + 4, 0)
            uc.mem_write(a + 0x10, b"\x01")
            uc.mem_write(buf, z)
        m.call(BLOCKM, self.pad, self.ctx, count=20_000_000)
        acc = np.zeros(N, np.float32)
        for a, buf in self.buses:
            acc += np.frombuffer(bytes(uc.mem_read(buf, N * 4)), np.float32)
        self.out.append(acc)
        q = self.ctx + 0x15238                                # the app queue: log, then drained
        for i in range(m.r32(q + 0x600)):
            b = bytes(uc.mem_read(q + 0x18 * i, 0x18))
            self.posted.append((self.block, b[0], struct.unpack("<5I", b[4:])))
        m.w32(q + 0x600, 0)
        m.w32(self.queue + 0x600, 0)                          # the engine drains the pad queues (FUN_0805f3b8)
        m.call(ADVANCE, self.engine, N)                       # then the clock advance, as at 0x080531e0
        self.block += 1

    def run(self, blocks):
        for _ in range(blocks):
            self.step_block()
        return self

    def seg(self, k):
        b = self.pad + 0x30 + k * 0x70
        return dict(active=self.m.r8(b), done=self.m.r8(b + 1), delay=self.m.r32(b + 0x20), first=self.m.r8(b + 0x3C),
                    step=u32(self.m, b + 0x34))

    def layer(self, L=0):
        b = self.pad + 0x260 + L * 0x410
        return dict(active=self.m.r8(b), launch_tick=self.i64(b + 0x140), armed=self.m.r8(b + 0x148))

    def seam_reads(self):
        return [r for r in self.reads if not r[-1]]


def poll(r):
    r.m.call("clipwin_tick", r.engine, count=20_000_000)


def starts(r):
    """each segment that sounded: (its first sample, step, stock start frame), in order"""
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    return sorted((first[m_["sid"]], m_["step"], m_["start"]) for m_ in r.made if m_["sid"] in first)


def scenario(frames=96000, beats=4, quant=3, sync=3, at=287000, blocks=900, slip=0, others=None, pre=None, setup=None,
             note=60, launch=2, loop=1, region=None, points=None, vals=None, **kw):
    """A Clip pad (Launch Toggle, Loop On) with Slip `slip` (and Region `region`, if given) in its store, the app's other
    pads per `others`; the poll has seen the stores before the note (as on the unit, where the app writes its store
    before it posts). points = (Loop Start, Loop End, Loop Mode): posted to the cell's queue a block before the rest,
    so its class-H object (h, implied) holds them, as the app's posts leave it. vals: more of the pad's store ({id: value},
    e.g. Sync and Loop Len), from the start."""
    if points is not None:
        kw["h"] = True
    r = Rig(frames=frames, **kw)
    d = dict(others or {})
    d[r.q] = slip
    slips(r.m, d)
    if region is not None or vals:
        store(r.m, r.q, {0x4: 500, P_SLIP: slip, **({} if region is None else {P_REGION: region}), **(vals or {})})
    if r.patched:
        for _ in range(16):
            poll(r)

    def pb(rr):
        if rr.patched:
            poll(rr)
        if pre:
            pre(rr)
    r.pre_block = pb
    r.params(beats=beats, quant=quant, sync=sync, launch=launch, loop=loop)
    if r.h:
        r.goto(at - N)
        if points is not None:
            for pid, v in zip((0x91, 0x92, 0x8E), points):
                r.param(pid, v)
        r.step_block()
    if setup:
        setup(r)
    r.goto(at)
    r.note_on(note)
    return r.run(blocks)


def same(a, b, silent=False):
    """everything the two runs did, bit for bit: reads (and their results and fetches), prefetches, mixed output, posts"""
    strip = lambda rs: [x[:SID] + x[AT:-1] for x in rs]            # the segment numbering and clip_read flag aside
    d = dict(reads=strip(a.reads) == strip(b.reads), fetches=a.fetches == b.fetches, prefetches=a.prefetches == b.prefetches,
             out=len(a.out) == len(b.out) and all(np.array_equal(x.view(np.uint32), y.view(np.uint32)) for x, y in zip(a.out, b.out)),
             posted=a.posted == b.posted)
    return all(d.values()) and (silent or len(a.reads) > 0), d


def decode(rd, rr, ch=0):
    """a gain run (source 1.0) and a ramp run of the same scenario -> per sample: summed gain, sounding segments, and
    when one segment sounds, which one and the source frame it plays"""
    a = [x for x in rd.mix if x[2] == ch]
    b = [x for x in rr.mix if x[2] == ch]
    assert len(a) == len(b) and all(x[0] == y[0] and x[1] == y[1] and len(x[3]) == len(y[3]) for x, y in zip(a, b))
    s = np.concatenate([x[0] + np.arange(len(x[3])) for x in a])
    sid = np.concatenate([np.full(len(x[3]), x[1] or 0) for x in a])
    g = np.concatenate([x[3] for x in a]).astype(np.float64)
    v = np.concatenate([y[3] for y in b]).astype(np.float64)
    base = int(s.min())
    idx = s - base
    live = np.abs(g) > 1e-7
    cnt = np.bincount(idx, weights=live.astype(float))
    single = live & (cnt[idx] == 1)
    frame, who = np.full(len(cnt), np.nan), np.zeros(len(cnt), np.int64)
    frame[idx[single]] = (-1.0 if ch else 1.0) * v[single] / g[single] / RAMP - 1
    who[idx[single]] = sid[single]
    return dict(base=base, gain=np.bincount(idx, weights=g), cnt=cnt, frame=frame, sid=who, rig=rr)


def audio(**kw):
    return decode(scenario(dc=True, **kw), scenario(**kw))


def window(ref, cw):
    lo, hi = max(ref["base"], cw["base"]), min(ref["base"] + len(ref["gain"]), cw["base"] + len(cw["gain"]))
    cut = lambda d, key: d[key][lo - d["base"]:hi - d["base"]]
    return lo, {k: (cut(ref, k), cut(cw, k)) for k in ("frame", "gain", "sid")}


def shifted(ref, cw, sf, length, edge=0, since=None):
    """samples where one segment sounds in both runs: max |cw frame - (stock frame + slip_f) mod len| (circular), the
    count of samples off by more than 0.05 frame, and of samples whose summed gain differs. `edge` > 0 leaves out the
    samples within that many frames of the file's ends in either run (the kernel's support: there stock interpolates
    into the silence after the file, the Clip Window into the file's start). `since`: only the samples from there on."""
    lo, w = window(ref, cw)
    fs, fc = w["frame"]
    gs, gc = w["gain"]
    span = lo + np.arange(len(gs)) >= (since if since is not None else lo)
    ok = ~np.isnan(fs) & ~np.isnan(fc) & span
    want = np.mod(fs + sf, length)
    near = lambda f: (f < edge) | (f > length - 1 - edge)
    if edge:
        ok &= ~near(fs) & ~near(want)
    err = np.abs(fc - want)
    err = np.minimum(err, length - err)[ok]
    gdiff = (np.abs(gs - gc) > 1e-6) & span
    if edge:
        gdiff &= ~(near(np.nan_to_num(fs, nan=length / 2)) | near(np.nan_to_num(fc, nan=length / 2)))
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > 0.05).sum()), int(gdiff.sum())


def wraps(d, length):
    """how often the frame played by one segment jumps from the file's end back to its start"""
    f, sid = d["frame"], d["sid"]
    i = np.where(~np.isnan(f[:-1]) & ~np.isnan(f[1:]) & (sid[:-1] == sid[1:]) & (sid[:-1] > 0))[0]
    return int((f[i + 1] - f[i] < -length / 2).sum())


# ====================================================================================================== 3. off = stock
off_cases = [("the matched file (96 000 frames, 4 beats), Quant 1 bar, Sync 1/4", dict(frames=96000, at=287000, cell=0x102)),
             ("a fast file (88 615 frames, fps 22 153.75)", dict(frames=88615, at=287000, cell=0x0)),
             ("88 615 frames, the note 300 samples after the bar", dict(frames=88615, at=288300, cell=0x303)),
             ("Sync None", dict(frames=96000, at=287000, sync=6, cell=0x201))]
for name, sc in off_cases:
    q = (sc["cell"] >> 8) * 4 + (sc["cell"] & 3)
    others = {p: 960 for p in range(16) if p != q}
    cw = scenario(slip=0, others=others, **sc)
    by = scenario(slip=0, others=others, bypass=True, **sc)
    st = scenario(slip=0, image=STOCK, **sc)
    ok1, d1 = same(cw, by)
    ok2, d2 = same(cw, st)
    check(f"Slip 0, {name} (pad {q + 1}; every other pad's Slip 960): each read (position, n, rate, frac, used, buffer, "
          "fetches), prefetch, mixed sample and message identical to the hooks taken out", ok1, d1)
    check("  ...and to the stock 3.1.9 image", ok2, d2)
    check("  ...no latch made, the poll did run", bank_valid(cw.m, q) == 0 and u32(cw.m, BANK) == CW_MAGIC and bank_slip(cw.m, (q + 1) % 16) == 960)
    st_ = starts(cw)
    if "matched" in name:
        check("  stock as measured (notes/re/a2): launch on the bar at 288 000 (+0x140 = 11 520, msg 0x1d), steps at "
              "312 000 / 336 000 / 360 000 on frames 24 000 j, the wrap at 384 000 back to frame 0",
              cw.layer()["launch_tick"] == 11520 and [b for b, t, _ in cw.posted if t == 0x1D] and
              st_[:5] == [(288000, 0, 0), (312000, 1, 24000), (336000, 2, 48000), (360000, 3, 72000), (384000, 0, 0)],
              (cw.layer(), st_[:5]))
    if "fast" in name:
        check("  stock as measured: steps start on (int)(j x 22153.75) = 0, 22 153, 44 307, 66 461, on the same grid",
              st_[:4] == [(288000, 0, 0), (312000, 1, 22153), (336000, 2, 44307), (360000, 3, 66461)], st_[:4])
    if "300" in name:
        check("  stock as measured: a launch 300 samples late starts at once on frame 0 (+0x140 = 11 532), step 1 still "
              "on the grid (312 000)", cw.layer()["launch_tick"] == 11532 and st_[:2] == [(288300, 0, 0), (312000, 1, 22153)],
              (cw.layer(), st_[:2]))
    if "None" in name:
        check("  stock as measured: Sync None, one segment for the whole file, restarted every len - 257 samples",
              st_[:2] == [(288000, 0, 0), (288000 + 96000 - 257, 0, 0)], st_[:3])

# ====================================================================================================== 4. Slip
slip_cases = [("matched 96 000, launch on the bar", dict(frames=96000, at=287000, blocks=900), (0, 960, -30, 7, 3839)),
              ("fast 88 615, launch on the bar", dict(frames=88615, at=287000, blocks=900), (0, 960, -30, 7, 3839)),
              ("fast 88 615, launch 300 samples late", dict(frames=88615, at=288300, blocks=900), (960, -30, 3839)),
              ("16 beats (384 000), Quant 1 beat < Sync 1 bar, note at tick 8 000", dict(frames=384000, beats=16, quant=5, sync=1, at=200000, blocks=1000), (960, -30, 3839)),
              ("fast 88 615, default Sync 1/16", dict(frames=88615, sync=5, at=287000, blocks=900), (960, 7, 3839))]
for name, sc, values in slip_cases:
    sc = dict(sc, cell=0x102)
    ref = audio(**sc)
    clip = sc.get("beats", 4) * 960
    for slip in values:
        cw = audio(slip=slip, **sc)
        sf = slip_f(slip, sc["frames"], clip)
        n, err, bad, gd = shifted(ref, cw, sf, sc["frames"])
        r = cw["rig"]
        h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
        pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
        lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
        check(f"{name}, Slip {slip} (slip_f {sf}): every sounding sample plays (stock frame + slip_f) mod len "
              f"({n} samples, max error {err:.4f} frame), summed gain = stock's at every sample",
              n > 80000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))
        if slip:
            wr = wraps(cw, sc["frames"])
            check(f"  H1 latched every segment start ({len(h1)}): slot k from the caller's frame, (0, len, slip_f), and "
                  f"prefetched where it will read; the content wraps inside a segment {wr} time(s), {len(r.seam_reads())} "
                  "block(s) read by clipwin_read's own fetch (across the file end, or within 3 frames of its start)",
                  h1 and pf == [max(0, (m_["start"] + sf) % sc["frames"] - 8) for m_ in h1] and lat and
                  all(x == (0, sc["frames"], sf) for x in lat) and len(r.seam_reads()) >= min(wr, 1),
                  (pf[:4], [m_["start"] for m_ in h1][:4], lat, len(r.seam_reads())))

# more of what stock does around a slipped pad: it keeps doing it, every sample still stock + slip_f
for name, sc, slip in (("a retrigger (Launch Trigger, Quant 1 beat, a second note in step 1): two voices' segments",
                        dict(launch=0, quant=5, pre=lambda rr: rr.note_on() if rr.block == 200 else None), 960),
                       ("a live Sync change (1/4 -> 1/2 in step 1): stock re-grids the playing segment, re-makes the pending one",
                        dict(pre=lambda rr: rr.param(0x94, 2) if rr.block == 265 else None), -30),
                       ("a tempo change (120 -> 126 BPM in step 1)", dict(pre=lambda rr: rr.set_bpm(126.0) if rr.block == 265 else None), 7)):
    sc = dict(sc, cell=0x102, frames=88615)
    ref, cw = audio(**sc), audio(slip=slip, **sc)
    sf = slip_f(slip, 88615, 3840)
    n, err, bad, gd = shifted(ref, cw, sf, 88615)
    launches = sum(1 for m_ in cw["rig"].made if m_["launch"])
    check(f"{name}, Slip {slip}: every sounding sample plays stock + slip_f ({n} samples, max {err:.4f} frame), summed "
          f"gain = stock's ({launches} launch(es))", n > 50000 and err <= 0.02 and bad == 0 and gd == 0
          and launches == (2 if "retrigger" in name else 1), (n, err, bad, gd, launches))
# clip = ticks per step x steps, not Beat Count x 960, where the steps do not divide the clip
r = scenario(frames=1392000, beats=29, sync=1, slip=3840, cell=0x102, blocks=40)
tps, n_ = r.i64(r.pad + 0x208), u32(r.m, r.pad + 0x210)
got = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
check(f"Beat Count 29, Sync 1 bar: {n_} steps of {tps} ticks ({tps * n_}, not 27 840); slip_f = floor(3840 x len / {tps * n_})"
      f" = {slip_f(3840, 1392000, tps * n_)} (README 2.4: the product, as the model)",
      (tps, n_) == (3977, 7) and got and all(x == (0, 1392000, slip_f(3840, 1392000, 27839)) for x in got)
      and slip_f(3840, 1392000, 27839) != slip_f(3840, 1392000, 27840), (tps, n_, got))

# the cave writes nothing in the block but its own bank: every write from clipwin.o's code (its static helpers and
# bank included: the link map gives the object's .text) and clipwin_b2.o's (the latch and the rest of the maths, in
# bank 2), a launch on the seam (Slip 3839) and a live change
w = []
r = Rig(cell=0x102)
cw_code = [(int(l.split()[1], 16), int(l.split()[1], 16) + int(l.split()[2], 16)) for l in open("out/cave.map")
           if l.split()[:1] and l.split()[0].startswith(".text") and l.rstrip().endswith(("out/obj/clipwin.o", "out/obj/clipwin_b2.o"))
           and len(l.split()) == 4]
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u, acc, addr, size_, v, d: w.append((addr, size_)) if any(
    a <= u.reg_read(UC_ARM_REG_PC) < b for a, b in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
slips(r.m, {6: 3839})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), store(rr.m, 6, {0x4: 500, P_SLIP: -30}) if rr.block == 150 else None)
r.params()
r.goto(287000)
r.note_on()
r.run(300)
hit = {name: any(lo <= a - BANK < hi for a, s in w) for name, lo, hi in (("valid", B_VALID, B_LATCH), ("latch", B_LATCH, B_H1),
                                                                         ("h1", B_H1, B_HINTED), ("hinted", B_HINTED, B_SIZE))}
check(f"in a Slip run, every write clipwin.c makes into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (of the 0x800 "
      f"reserved; valid, latch, h1 and hinted written: {hit})", cw_code and w and all(hit.values())
      and all(BANK <= a and a + s <= BANK + B_SIZE for a, s in w), (cw_code, sorted({hex(a) for a, s in w if not BANK <= a < BANK + B_SIZE})[:4]))

# H2's seam hint (README 2.6): once a segment reads within 16 384 frames of the region end (the hint's sure reach,
# notes/re/a2), clipwin_read hints rs once for that slot; H1 clears the bit at the next latch
for name, sc, exact in (("96 000 frames, Slip 7, Sync 1/4 (the seam mid-step)", dict(frames=96000, slip=7, blocks=1600), True),
                        ("88 615 frames, Slip 960, Sync 1/4 (a step crosses mid-step, the next starts on the seam)",
                         dict(frames=88615, slip=960, blocks=1400), True),
                        ("88 615 frames, Slip 960, Sync 1/16 (steps shorter than the reach)", dict(frames=88615, slip=960, sync=5, blocks=1400), False)):
    r = scenario(cell=0x102, **sc)
    ln, sf = sc["frames"], slip_f(sc["slip"], sc["frames"], 3840)
    near = {x[SID] for x in r.reads if ln - (x[POS] + sf) % ln <= 16384}          # the rule, from each read's real position
    cross = {}
    for x in r.seam_reads():
        cross.setdefault(x[SID], x[0])
    sids = [s for _, _, s in r.hints]
    lead = sorted(max((b - hb for hb, _, _ in r.hints if 0 <= b - hb <= 300), default=-1) for b in cross.values())
    check(f"seam hint, {name}: {len(r.hints)} hint(s) from clipwin_read, all at rs = 0, one per segment, from exactly the "
          f"segments that read within 16 384 frames of the end ({len(near)}){', which are the crossing ones' if exact else ''} "
          f"({len(cross)} crossing in {len(r.made)} segments); every seam read hinted {lead} blocks ahead (>= 100); no other "
          "prefetch than H1's", r.hints and all(p == 0 for _, p, _ in r.hints) and len(set(sids)) == len(sids)
          and set(sids) == near and set(cross) <= near and (not exact or set(cross) == near) and len(cross) >= 2
          and min(lead) >= 100 and len(r.prefetches) == len(r.made) + len(r.hints),
          (r.hints[:6], sorted(near), cross, lead, len(r.prefetches), len(r.made)))
r = scenario(frames=96000, slip=-30, cell=0x102, blocks=40)
seam = [x[0] for x in r.seam_reads()][:1]
info(f"observed: a launch whose slipped content starts near the end (Slip -30: frame 95 250) is hinted at rs only at its "
     f"first read (block {r.hints[0][0] if r.hints else None}; H1's own prefetch at {r.prefetches[0][1]}), "
     f"{seam[0] - r.hints[0][0] if seam and r.hints else None} block(s) before its seam read (block {seam[:1]})")

# ====================================================================================================== 5. live change
for frames in (96000, 88615):
    ref = audio(frames=frames, cell=0x102)
    for slip in (480, -7):
        seen = {}

        def change(rr, slip=slip):
            if rr.block == 265:                               # sample 320 920, inside step 1 (312 000 .. 336 000)
                store(rr.m, 6, {0x4: 500, P_SLIP: slip})
            if "at" not in seen and bank_slip(rr.m, 6) == slip:
                seen["at"] = rr.block
        cw = audio(frames=frames, cell=0x102, pre=change)
        r = cw["rig"]
        sf = slip_f(slip, frames, 3840)
        at = seen.get("at", -1)
        lo, w = window(ref, cw)
        fs, fc = w["frame"]
        gs, gc = w["gain"]
        sid = w["sid"][1]
        newer = np.array([r.made[s - 1]["block"] >= at if s else False for s in sid])
        both = ~np.isnan(fs) & ~np.isnan(fc)
        old, new = both & ~newer, both & newer
        e_old = float(np.abs(fc[old] - fs[old]).max()) if old.any() else 9e9
        e_new = np.abs(fc[new] - np.mod(fs[new] + sf, frames))
        e_new = float(np.minimum(e_new, frames - e_new).max()) if new.any() else 9e9
        first_new = min((x[AT] for x in r.reads if x[SID] and r.made[x[SID] - 1]["block"] >= at), default=-1)
        alone = int(np.argmax(new)) + lo
        remade = [(m_["k"], m_["step"], m_["block"]) for m_ in r.made if m_["step"] == 2][:2]
        bdy = (336000 - 287000) // N
        check(f"live {frames} frames, Slip 0 -> {slip} in step 1 (polled at block {at}, {at - 265} block(s) after the store "
              f"changed): the pending step 2 is dropped and re-made in that block, same slot",
              0 <= at - 265 < 16 and len(remade) == 2 and remade[1][2] == at and remade[0][0] == remade[1][0], remade)
        check(f"  everything up to the step boundary (336 000) identical to stock; the sounding segment keeps playing stock "
              f"frames (max {e_old:.4f}); the re-made step starts on the boundary ({first_new}, through stock's crossfade: "
              f"alone from {alone}) and every sample of it plays stock + slip_f (max {e_new:.4f}); summed gain = stock's at "
              "every sample (no added silence)",
              all(np.array_equal(x, y) for x, y in zip(ref["rig"].out[:bdy], r.out[:bdy])) and e_old == 0 and e_new <= 0.02
              and first_new == 336000 and not (np.abs(gs - gc) > 1e-6).any(),
              (e_old, e_new, first_new, int((np.abs(gs - gc) > 1e-6).sum())))

# The row's sign (Thomas, D-016): + = AHEAD, - = behind (a CDJ jog). -480 (-0.480 on screen, half a beat behind) must
# play every sample 12 000 samples (half a beat at 120 BPM) after stock plays it: content = stock - 12 000.
ref = audio(frames=96000, cell=0x102)


def user_late(rr):
    if rr.block == 0:
        store_raw(rr.m, 6, {0x4: 500, P_SLIP: -480})


cw = audio(frames=96000, cell=0x102, pre=user_late)
n, err, bad, gd = shifted(ref, cw, slip_f(-480, 96000, 3840), 96000)
check(f"the row's sign: Slip -0.480 (counter-clockwise, behind) plays every sample half a beat LATER than stock - content "
      f"= stock frame - 12 000 ({n} samples, max {err:.4f} frame), and the bank holds -480",
      n > 25000 and err <= 0.02 and bad == 0 and gd == 0 and bank_slip(cw["rig"].m, 6) == -480, (n, err, bad, gd))

# Sync None: no pending segment to drop - the new Slip waits for the restart (README section 4, open question 8)
seen = {}


def change_none(rr):
    if rr.block == 300:
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if "at" not in seen and bank_slip(rr.m, 6) == 960:
        seen["at"] = rr.block


r = scenario(frames=96000, sync=6, cell=0x102, pre=change_none, blocks=900)
first = {}
for x in r.reads:
    first.setdefault(x[SID], x)
remade = [m_ for m_ in r.made if m_["block"] == seen.get("at")]
restart = first.get(remade[0]["sid"]) if len(remade) == 1 else None
check("Sync None, Slip 0 -> 960 while playing (README section 4, question 8): the playing segment plays on stock; the "
      "pending restart is re-made when the poll sees it, and that restart (len - 257 samples on) plays slipped",
      restart and first[1][FET][0][1] == 0 and restart[AT] == 288000 + 96000 - 257 and restart[FET][0][1] == 24000,
      ([(m_["block"], m_["start"]) for m_ in r.made], seen, [(x[AT], x[FET][:1]) for x in first.values()]))

# the pending launch (droplaunch, armed): never dropped (that would sound it at once, off its bar); the poll latches it
# again in place, so it plays the new Slip from its first read, on its bar
seen = {}


def change_pending(rr):
    if rr.block == 20:                                        # between the note (193 000) and its bar (288 000)
        seen["segs"] = [rr.seg(k) for k in range(4)]
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if "at" not in seen and bank_slip(rr.m, 6) == 960:       # the poll ran just before, in this block
        seen["at"] = rr.block
        seen["pending"] = [rr.seg(k) for k in range(4)]
        seen["latch"] = [latch(rr.m, 6, k) if bank_valid(rr.m, 6) >> k & 1 else None for k in range(4)]


r = scenario(frames=96000, at=193000, blocks=960, cell=0x102, pre=change_pending)
launch = [m_ for m_ in r.made if m_["step"] == 0][:2]
k0 = launch[0]["k"] if launch else 0
p0 = seen["pending"][k0] if "pending" in seen and launch else dict(active=0, done=0, delay=0, first=0)
check("pending launch: when the poll sees the change, the launch segment is waiting (delay > 0, +0x3c set) and is "
      "not dropped (no step-0 segment made again); only the step after it is re-made",
      p0["active"] and not p0["done"] and p0["delay"] > 0 and p0["first"] and len(launch) == 1
      and [m_["block"] for m_ in r.made if m_["step"] == 1][:2] == [0, seen.get("at")], (p0, [(m_["step"], m_["block"]) for m_ in r.made]))
check("  ...so it still launches on its bar: first read at 288 000, layer +0x140 = 11 520, msg 0x1d posted",
      r.reads[0][AT] == 288000 and r.layer()["launch_tick"] == 11520 and [b for b, t, _ in r.posted if t == 0x1D][:1] == [742],
      (r.reads[0][AT], r.layer(), [b for b, t, _ in r.posted if t == 0x1D][:2]))
step1 = [x for x in r.reads if r.made[x[SID] - 1]["step"] == 1]
check(f"  the poll latches the waiting launch again in place (slot {k0}: (0, 96 000, 24 000), prefetched at 23 992 in that "
      "block): it plays slipped from its first read (first fetch 24 000 = slip_f), the next step too (24 000 + 24 000)",
      seen.get("latch", [None] * 4)[k0] == (0, 96000, 24000) and (seen.get("at"), 23992) in r.prefetches
      and r.reads[0][FET][0][1] == 24000 and step1 and step1[0][FET][0][1] == 48000,
      (seen.get("latch"), [p for p in r.prefetches if p[0] == seen.get("at")], r.reads[0][FET][:1], step1[0][FET][:1] if step1 else None))
ref = audio(frames=96000, at=193000, blocks=960, cell=0x102)
cw = decode(scenario(dc=True, frames=96000, at=193000, blocks=960, cell=0x102, pre=change_pending), r)
n, err, bad, gd = shifted(ref, cw, 24000, 96000)
check(f"  every sounding sample, the launch step's first included, plays (stock frame + slip_f) mod len ({n} samples, max "
      f"{err:.4f} frame), summed gain = stock's", n > 25000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))


def armed(bypass):
    """a note while the transport is stopped, Slip 0 -> 960 while it is armed, then PLAY on the bar at 384 000"""
    r = Rig(cell=0x102, bypass=bypass)
    slips(r.m, {})
    for _ in range(16):
        poll(r)
    r.pre_block = poll
    r.params()
    r.goto(193000)
    r.uc.mem_write(r.engine + 0x38, b"\x00")                  # transport stopped
    r.note_on()
    r.run(10)
    before = [r.seg(k) for k in range(4)]
    store(r.m, 6, {0x4: 500, P_SLIP: 960})
    r.run(20)
    held = dict(segs=[r.seg(k) for k in range(4)], armed=r.layer()["armed"], slip=bank_slip(r.m, 6), reads=len(r.reads),
                latch=latch(r.m, 6, 0) if bank_valid(r.m, 6) & 1 else None, pf=[p for b, p in r.prefetches if b >= 10])
    r.goto(384000)                                             # PLAY: the transport runs, and its start message (0x57)
    r.uc.mem_write(r.engine + 0x38, b"\x01")
    r.post(0x57)
    r.run(300)
    return r, before, held


r, before, held = armed(False)
by = armed(True)[0]
check("armed while the transport is stopped (delay 1, +0x3c set, layer +0x148 = 1): a Slip change leaves the launch armed "
      "and untouched, and latches it again in place (slot 0: (0, 96 000, 24 000), prefetched at 23 992)",
      before[0]["first"] and before[0]["delay"] == 1 and held["segs"] == before and held["armed"] == 1 and held["slip"] == 960
      and not held["reads"] and held["latch"] == (0, 96000, 24000) and held["pf"] == [23992], (before[0], held))
timing = lambda rr: [x[:SID] + x[AT:FET] for x in rr.reads]          # every read but its fetches
step1 = [x for x in r.reads if r.made[x[SID] - 1]["step"] == 1]
check("  PLAY (msg 0x57) on the bar at 384 000: it sounds from 384 001 (stock's delay 1; +0x140 = 15 360, msg 0x1d), every "
      "read's timing and bookkeeping and every message as with the hooks out, and it plays slipped from its first read: "
      "first fetch 24 000 (slip_f; hooks out: 0), the next step 48 000",
      r.reads and by.reads and r.reads[0][AT] == by.reads[0][AT] == 384001 and r.layer()["launch_tick"] == by.layer()["launch_tick"] == 15360
      and [b for b, t, _ in r.posted if t == 0x1D][:1] == [30] and timing(r) == timing(by) and r.posted == by.posted
      and r.reads[0][FET][0][1] == 24000 and by.reads[0][FET][0][1] == 0 and step1 and step1[0][FET][0][1] == 48000,
      (r.reads[0][AT] if r.reads else None, r.layer(), by.layer(), timing(r) == timing(by), r.posted == by.posted,
       r.reads[0][FET][:1] if r.reads else None, step1[0][FET][:1] if step1 else None))

# ====================================================================================================== 5b. a new file
# A new file under a playing pad: a load from the pad's Load screen, the browser's pre-listen (FUN_080a1560 loads each
# highlighted file into the pad the browser was opened on too), a take landing in the pad. The chain, as notes/re/x3
# sections 3 and 4 trace it: the pad's asset closes (fw_src_len answers 0), the pad load's full re-post makes the pad
# recompute while the new slot is not open yet (0x90), the loader opens the new file (fw_src_len answers its length,
# the source serves its frames), the app's 0xE handler posts 0x90 and the pad recomputes against it.
SWAP, CLOSED = 265, 4                                         # sample 320 920, inside step 1 (312 000 .. 336 000)
T_SWAP, T_OPEN = 287000 + SWAP * N, 287000 + (SWAP + CLOSED) * N


def new_file(length):
    def pre(rr):
        if rr.block == SWAP:
            rr.len = 0
            rr.param(0x90, 0)
        if rr.block == SWAP + CLOSED:
            rr.len = length
        if rr.block == SWAP + CLOSED + 1:
            rr.param(0x90, length)
    return pre


strip = lambda x: x[:SID] + x[AT:-1]                         # a read row, segment numbering and clip_read flag aside
for name, length, values in (("a shorter file (50 000 frames)", 50000, (960, -480)),
                             ("a longer file (192 000 frames)", 192000, (960,)),
                             ("a file of the same length (96 000 frames)", 96000, (960,))):
    sc = dict(frames=96000, cell=0x102, blocks=900, pre=new_file(length))
    st_r = scenario(image=STOCK, **sc)
    st = decode(scenario(dc=True, image=STOCK, **sc), st_r)
    t = st["base"] + np.arange(len(st["gain"]))
    quiet = int(((t >= T_OPEN) & (np.abs(st["gain"]) < 1e-7)).sum())
    on = [x for x in st_r.reads if x[0] == SWAP + CLOSED and st_r.made[x[SID] - 1]["step"] == 1]
    at = T_SWAP - 312000 + 24000                              # step 1's position when the slot closes
    check(f"stock 3.1.9, Slip 0, {name} under the playing pad from {T_SWAP}: no restart - the sounding step 1 stands "
          f"still while the slot is closed (nothing read) and reads on from its position, {at}, in the new file; the "
          f"pending step 2 keeps its start on the old grid (48 000), step 3 starts on the new one ({3 * length // 4}); "
          f"{quiet} samples silent after the file opens (the reader reads nothing past len + 0xff)",
          starts(st_r)[:5] == [(288000, 0, 0), (312000, 1, 24000), (336000, 2, 48000), (360000, 3, 3 * length // 4), (384000, 0, 0)]
          and not [m_ for m_ in st_r.made if SWAP <= m_["block"] <= SWAP + CLOSED + 1]
          and len(on) == 1 and on[0][POS] == at and on[0][FET][:1] == ((SWAP + CLOSED, at, N),),
          (starts(st_r)[:6], [(m_["block"], m_["step"]) for m_ in st_r.made], on[:1]))
    ok, d = same(scenario(**sc), st_r)
    check("  Slip 0 on this image: every read, fetch, prefetch, mixed sample and message identical to stock through the "
          "file change", ok, d)
    for slip in values:
        rr = scenario(slip=slip, **sc)
        cw = decode(scenario(dc=True, slip=slip, **sc), rr)
        sf_old, sf_new = slip_f(slip, 96000, 3840), slip_f(slip, length, 3840)
        lo, w = window(st, cw)
        gs, gc = w["gain"]
        s = lo + np.arange(len(gs))
        extra = int(((s >= T_SWAP) & (np.abs(gc) < 1e-7) & (np.abs(gs) > 1e-7)).sum())
        past = lambda r_: {f for f in r_.fetches if f[0] >= SWAP + CLOSED and f[1] + f[2] > length}
        old = {m_["sid"] for m_ in rr.made if m_["block"] < SWAP}
        mine = [strip(x) for x in rr.reads if x[0] >= SWAP and x[SID] in old]
        theirs = [strip(x) for x in st_r.reads if x[0] >= SWAP and x[SID] in old]
        if length != 96000:
            check(f"  Slip {slip}: the segments latched for the old file (the sounding step 1 and the pending step 2) read "
                  f"as stock does from the file change on: {len(mine)} reads (position, n, rate, frac, used, buffer, "
                  f"fetches) identical to stock's (the old mapping, + {sf_old} folded at 96 000, belongs to the old file)",
                  len(mine) > 200 and mine == theirs, (len(mine), len(theirs), [(a, b) for a, b in zip(mine, theirs) if a != b][:2]))
            check(f"  ...so no silence stock does not have ({extra} samples silent where stock sounds), and no read past "
                  f"the new file's end that stock does not make ({len(past(rr))} fetches reaching past {length}, all stock's own)",
                  extra == 0 and past(rr) <= past(st_r), (extra, sorted(past(rr) - past(st_r))[:3]))
        else:
            n, err, bad, gd = shifted(st, cw, sf_old, 96000)
            check(f"  Slip {slip}: the file closes and one of the same length opens: the latches hold again (the same "
                  f"length, the same shift), every sounding sample before and after plays stock + slip_f ({n} samples, max "
                  f"{err:.4f} frame), summed gain = stock's, the closed blocks silent as stock's",
                  n > 80000 and err <= 0.02 and bad == 0 and gd == 0 and extra == 0, (n, err, bad, gd, extra))
        fresh = [m_ for m_ in rr.made if m_["block"] > SWAP + CLOSED + 1]
        t_new = min((x[AT] for x in rr.reads if fresh and x[SID] == fresh[0]["sid"]), default=-1)
        held = [(latch(rr.m, 6, k), made_for(rr.m, 6, k)) for k in range(4) if bank_valid(rr.m, 6) >> k & 1]
        n, err, bad, gd = shifted(st, cw, sf_new, length, since=t_new + 256)
        check(f"  the first segment made after the recompute (step {fresh[0]['step'] if fresh else None}, sounding from "
              f"{t_new}) and the ones after it latch the new file: (0, {length}, {sf_new}), made for {length}; from the end "
              f"of its crossfade with step 2 ({t_new + 256}) every sounding sample plays (stock frame + {sf_new}) mod "
              f"{length} ({n} samples, max {err:.4f} frame), summed gain = stock's",
              t_new == 360000 and held and all(x == ((0, length, sf_new), length) for x in held)
              and n > 20000 and err <= 0.02 and bad == 0 and gd == 0, (t_new, held, n, err, bad, gd))

# ====================================================================================================== 6. gating


def gate(name, slip_map, silent=False, **kw):
    a = scenario(others=slip_map, **kw)
    b = scenario(others=slip_map, bypass=True, **kw)
    ok, d = same(a, b, silent)
    return a, ok, d


def slicer_setup(ms):
    def setup(r):
        r.goto(287000 - N)
        r.markers(ms)
        r.step_block()
    return setup


all960 = {q: 960 for q in range(16)}
MK = (0, 20000, 50000, 70000)                                 # slice markers
for name, kw in (("a Slicer pad (no markers: its segments pass H1)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Slicer pad with markers, note 37 (segments through H1')", dict(setup=lambda r: (r.params(mode=2), slicer_setup(MK)(r)), note=37)),
                 ("a Clip pad, Sync = Slice, with markers (H1')", dict(sync=0, setup=slicer_setup(MK)))):
    a, ok, d = gate(name, all960, slip=960, cell=0x102, blocks=500, **kw)
    hits = {h: sum(1 for m_ in a.made if m_["how"] == h) for h in ("H1", "H1'")}
    check(f"{name}, Slip 960: plays exactly as with the hooks out, no latch ({hits})",
          ok and bank_valid(a.m, 6) == 0 and bank_slip(a.m, 6) == 960 and sum(hits.values()) > 0, d)

# Slip changed live on those pads: the poll still drops their pending segments (it does not know Slip is ignored there)


def changes(rr):
    if rr.block in (150, 260, 330, 420):
        store(rr.m, 6, {0x4: 500, P_SLIP: {150: 960, 260: -30, 330: 480, 420: 7}[rr.block]})


for name, kw in (("a Slicer pad (no markers)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Slicer pad with markers", dict(setup=lambda r: (r.params(mode=2), slicer_setup(MK)(r)), note=37)),
                 ("a Clip pad, Sync = Slice, with markers", dict(sync=0, setup=slicer_setup(MK)))):
    a = scenario(slip=0, cell=0x102, blocks=600, pre=changes, **kw)
    b = scenario(slip=0, cell=0x102, blocks=600, pre=changes, bypass=True, **kw)
    ok, d = same(a, b)
    remade = len(a.made) - len(b.made)
    check(f"{name}, Slip changed four times while it plays: every read, fetch, output sample and message as with the "
          f"hooks out ({remade} pending segment(s) dropped and re-made by stock, {len(a.prefetches) - len(b.prefetches)} "
          "extra prefetch hint(s))", d["reads"] and d["fetches"] and d["out"] and d["posted"] and bank_valid(a.m, 6) == 0, d)

# a slot H1 latched, reused by a slice segment (H1' clears it): live Sync -> Slice on a slipped pad


def to_slice(r):
    if r.block == 300:
        r.param(0x94, 0)


runs = [scenario(slip=960, cell=0x102, blocks=900, pre=to_slice, setup=slicer_setup(MK), bypass=b)
        for b in (False, True)]
sl = [[x[FET] for x in r_.reads if r_.made[x[SID] - 1]["how"] == "H1'"] for r_ in runs]
stale = [m_ for m_ in runs[0].made if m_["how"] == "H1'" and m_["valid_before"]]
check("Sync -> Slice while slipped: slice segments reuse slots H1 had latched (H1' clears them) and read the stock "
      "frames, exactly as with the hooks out", stale and sl[0] and sl[0] == sl[1], (len(stale), len(sl[0]), sl[0][:2], sl[1][:2]))
sounding = {x[SID] for x in runs[0].reads if x[0] == 300}
past = [(x[POS], x[FET][0][1] if x[FET] else None) for x in runs[0].reads if x[SID] in sounding and x[POS] >= 96000][:1]
past_by = [(x[POS], x[FET][0][1] if x[FET] else None) for x in runs[1].reads if x[POS] >= 96000][:1]
info("observed: the segment sounding at the switch keeps its latch and stock re-times it to run on past the file's end; "
     f"stock reads silence there {past_by}, the Clip Window the folded, slipped frames {past} (virtual, real)")

# a launch waiting for its bar on Sync = Slice (a slice segment, H1') is never latched again by the poll, even in a slot
# an earlier H1 segment used: Launch Trigger, Sync 1/4 (H1 caches the pad, every slot passes H1), a relaunch on the
# next bar, Sync -> Slice with markers live, another relaunch (now through H1'), then Slip 0 -> 960 before its bar
seen = {}


def slice_relaunch(rr):
    s = seen.setdefault(rr.hooks_out, {})
    if rr.block == 100:
        rr.note_on()                                          # relaunch on the bar at 384 000, through H1
    if rr.block == 800:
        rr.param(0x94, 0)                                     # Sync -> Slice
    if rr.block == 830:
        rr.note_on()                                          # relaunch on the bar at 480 000, through H1'
    if rr.block == 840:
        s["cached"] = u32(rr.m, BANK + B_PAD + 4 * 6) == rr.pad
        s["pending"] = [k for k in range(4) if rr.seg(k)["active"] and rr.seg(k)["delay"] > 0 and rr.seg(k)["first"]]
        store(rr.m, 6, {0x4: 500, P_SLIP: 960})
    if rr.block == 870:
        s["slip"], s["valid"] = bank_slip(rr.m, 6), bank_valid(rr.m, 6)


runs = []
for b_ in (False, True):
    def tag(r, b_=b_):
        r.hooks_out = b_
        slicer_setup(MK)(r)
    runs.append(scenario(slip=0, sync=3, launch=0, cell=0x102, at=287000, blocks=1600, pre=slice_relaunch, setup=tag, bypass=b_))
ok, d = same(*runs)
a, s = runs[0], seen.get(False, {})
rel = [m_ for m_ in a.made if m_["how"] == "H1'" and m_["block"] == 830 and m_["k"] in s.get("pending", [])]
check(f"Sync = Slice, a relaunch pending for its bar (slot {[m_['k'] for m_ in rel]}, made through H1' in a slot H1 had used: "
      f"h1 bit {[m_['h1_before'] for m_ in rel]} before), pad cached by H1 ({s.get('cached')}), Slip 0 -> 960 before the bar: "
      f"every read, fetch, output sample and message as with the hooks out (msg 0x1d at {[b for b, t, _ in a.posted if t == 0x1D]}), "
      f"no latch; only prefetch hints differ ({len(a.prefetches) - len(runs[1].prefetches)} extra: pending slice steps re-made)",
      d["reads"] and d["fetches"] and d["out"] and d["posted"] and len(rel) == 1 and rel[0]["h1_before"] == 1 and s.get("cached")
      and s.get("slip") == 960 and s.get("valid") == 0 and bank_valid(a.m, 6) == 0
      and [b for b, t, _ in a.posted if t == 0x1D][-1:] == [1508], (d, s, [(m_["how"], m_["block"], m_["k"], m_["h1_before"]) for m_ in a.made]))

a, ok, d = gate("0x401", all960, slip=960, blocks=400, cell=0x401)
check(f"cell 0x401 (the 17th class-B object, queue ctx + 0x608; pad 2's store under & 3), Slip 960 on every pad: "
      f"inactive - plays ({len(a.reads)} reads) as with the hooks out, no latch, not cached as any pad",
      ok and not any(bank_valid(a.m, q) for q in range(16)) and not any(u32(a.m, BANK + B_PAD + 4 * q) for q in range(16)),
      (d, len(a.reads)))
a, ok, d = gate("len 0", all960, silent=True, slip=960, blocks=400, frames=0)
check(f"fw_src_len 0 (not open), Slip 960: nothing plays, as with the hooks out ({len(a.reads)} reads), no latch",
      ok and not any(bank_valid(a.m, q) for q in range(16)), d)
a, ok, d = gate("len bad", all960, slip=960, blocks=400, frames=0x10000000)
check(f"fw_src_len 0x10000000 (the provider reported 0 frames), Slip 960: inactive - plays ({len(a.reads)} reads) as with "
      "the hooks out, no latch", ok and not any(bank_valid(a.m, q) for q in range(16)), d)
fill = bytes([0xA5]) * 0x1000
a = Rig(block=False, cell=0x102)
a.uc.mem_write(BANK - 0x800, fill)
slips(a.m, all960)
a.pre_block = poll
a.params()
a.goto(287000)
a.note_on()
a.run(400)
b = scenario(slip=960, others=all960, cell=0x102, blocks=400, bypass=True)
ok, d = same(a, b)
check("no SDRAM block, Slip 960: the poll and both hooks pass through - same as the hooks out, the memory where the "
      "bank would be untouched", ok and bytes(a.uc.mem_read(BANK - 0x800, 0x1000)) == fill, d)

# ====================================================================================================== 7. the reader (unit)
LENU = 50000
t = np.arange(LENU)
L_SIG = (0.4 * np.sin(2 * np.pi * 3000 * t / 48000) + 0.3 * np.sin(2 * np.pi * 9500 * t / 48000)).astype(np.float32)
R_SIG = (0.25 * np.sin(2 * np.pi * 5000 * t / 48000)).astype(np.float32)
RPAD, RSRC, SCR, OUT, VARS = 0x24060000, 0x24061000, 0x24062000, 0x24062100, 0x24062200
SCRD, SCRR, OUTD, OUTR = 0x24064000, 0x24065000, 0x24066000, 0x24067000   # 1024 floats each
VOICE = RPAD + 0x260 + 0x410
QU = 6


def sigs(length):
    """the test file's two channels, `length` frames (the first LENU are L_SIG / R_SIG)"""
    t_ = np.arange(length)
    return ((0.4 * np.sin(2 * np.pi * 3000 * t_ / 48000) + 0.3 * np.sin(2 * np.pi * 9500 * t_ / 48000)).astype(np.float32),
            (0.25 * np.sin(2 * np.pi * 5000 * t_ / 48000)).astype(np.float32))


def reader(image, rotate=None, length=LENU):
    """a machine with a RAM-served source: frame p of the file, or of the file turned by `rotate` (circular)"""
    m = Emu(image, "out/cave.elf")
    maps(m)
    m.fetches = []
    sig_l, sig_r = (L_SIG, R_SIG) if length == LENU else sigs(length)

    def frames_of(pos, n, sig):
        p = np.arange(pos, pos + n)
        if rotate is not None:
            return sig[np.mod(p + rotate, length)].tobytes()
        return np.where((p >= 0) & (p < length), sig[np.clip(p, 0, length - 1)], 0).astype(np.float32).tobytes()

    def fetch():
        pos = struct.unpack("<i", struct.pack("<I", m.arg(3)))[0]
        m.fetches.append((pos, m.arg(2)))
        m.uc.mem_write(m.arg(1), frames_of(pos, m.arg(2), sig_l))

    def fetch2():
        pos = m.r32(m.uc.reg_read(UC_ARM_REG_SP))
        m.fetches.append((pos, m.arg(3)))
        m.uc.mem_write(m.arg(1), frames_of(pos, m.arg(3), sig_l))
        m.uc.mem_write(m.arg(2), frames_of(pos, m.arg(3), sig_r))
    m.stub(FETCH, fetch)
    m.stub(FETCH2, fetch2)
    m.stub(SRC_LEN, value=length)
    m.uc.mem_write(RPAD, bytes(0xC00))
    m.uc.mem_write(RPAD + 4, b"\x4c")
    m.w32(RPAD + 0x24, RSRC)
    m.w32(RPAD + 0x18, (QU // 4) << 8 | QU % 4)
    sdram(m)
    m.uc.mem_write(BANK, bytes(0x800))
    m.w32(BANK, CW_MAGIC)
    return m


def set_latch(m, k, delta, valid=True, q=QU, length=LENU):
    """slot k latched as H1 latches it for a file of `length` frames: (0, length, delta), made for that length"""
    m.uc.mem_write(BANK + B_LATCH + (q * 4 + k) * L_SIZE, struct.pack("<4i", 0, length, delta, length))
    m.uc.mem_write(BANK + B_VALID + q, bytes([(1 << k) if valid else 0]))


def read(m, target, pos, frac, rate, stereo=False, n=64, k=1, frac_at=None):
    m.stub(0x08063790, value=int(stereo))
    for buf, dl, dr in ((SCR, SCRD, SCRR), (OUT, OUTD, OUTR)):
        m.uc.mem_write(buf, struct.pack("<IIIIBB", 1024, 1024, dl, dr if stereo else 0, 0, int(stereo)))
    for a in (OUTD, OUTR, SCRD, SCRR):
        m.uc.mem_write(a, bytes(4096))
    fp = frac_at if frac_at is not None else RPAD + 0x30 + k * 0x70 + 0x1C
    m.uc.mem_write(fp, struct.pack("<f", frac))
    m.uc.mem_write(VARS, struct.pack("<iI", -1, 0))
    m.uc.reg_write(UC_ARM_REG_S0, struct.unpack("<I", struct.pack("<f", rate))[0])
    for i, v in enumerate((n, VARS, fp, SCR, OUT, VARS + 4)):
        m.w32(STACK + 4 * i, v)
    m.fetches.clear()
    m.uc.reg_write(UC_ARM_REG_R11, VOICE)
    if target == 0x080662E4 or target == "clip_read":
        m.call(target, RPAD, VOICE + 0x14C, pos, 0, count=20_000_000)
    else:
        m.call(target, RPAD, 0, pos, 0, count=20_000_000)
    ok = m.uc.reg_read(UC_ARM_REG_R0)
    used, res = struct.unpack("<iI", m.uc.mem_read(VARS, 8))
    nfrac = struct.unpack("<f", m.uc.mem_read(fp, 4))[0]
    dl, dr = (OUTD, OUTR) if res == OUT else (SCRD, SCRR)
    left = np.frombuffer(bytes(m.uc.mem_read(dl, 4 * n)), np.float32).copy()
    right = np.frombuffer(bytes(m.uc.mem_read(dr, 4 * n)), np.float32).copy() if stereo else None
    return ok, used, nfrac, res, left, right, list(m.fetches)


def fidelity(m, v):
    store(m, QU, {0x4: 500, 0xDB: 0, 0xF1: v})


cw_m = reader(IMAGE)
for name, delta, pos, rate, frac, stereo, n, length in (
        ("rate 1, frac 0 (the straight copy)", 30000, 19970, 1.0, 0.0, False, 64, LENU),
        ("rate 0.7, frac 0.25 (the kernel)", 30000, 19980, 0.7, 0.25, False, 64, LENU),
        ("rate 2.3, frac 0.6", 12345, LENU - 12345 - 70, 2.3, 0.6, False, 64, LENU),
        ("rate 8, 128 frames (the fetch capped at the scratch's 1024)", 30000, 19990, 8.0, 0.3, False, 128, LENU),
        ("stereo, rate 1, frac 0", 30000, 19970, 1.0, 0.0, True, 64, LENU),
        ("stereo, rate 0.91875 (44.1 kHz), frac 0.4", 30000, 19985, 0.91875, 0.4, True, 64, LENU),
        ("rate 1, frac 0, real position 1 (no seam in stock's window: its reader at the real position)", 30001, 20000, 1.0, 0.0, False, 64, LENU),
        ("rate 0.8, real position 2 (the same)", 2, 0, 0.8, 0.1, False, 64, LENU),
        ("a 40-frame file, 64 frames read (round the file twice)", 13, 20, 1.0, 0.0, False, 64, 40),
        ("a 40-frame file, stereo, rate 1.7", 13, 30, 1.7, 0.2, True, 64, 40)):
    m = cw_m if length == LENU else reader(IMAGE, length=length)
    ref_m = reader(STOCK, rotate=delta, length=length)
    set_latch(m, 1, delta, length=length)
    fidelity(m, 0)
    got = read(m, "clip_read_b", pos, frac, rate, stereo, n=n)
    want = read(ref_m, 0x080662E4, pos, frac, rate, stereo, n=n)
    real = (pos + delta) % length
    count = n if rate == 1.0 and frac == 0.0 else min(int(np.float32(n) * np.float32(rate)) + 8, 1024)
    ring = got[6][0][0] == real and all(f[0] == 0 for f in got[6][1:]) and sum(f[1] for f in got[6]) == count
    check(f"{'seam' if real + count > length else 'mapped'} read, {name}: what the stock reader makes of the file turned circular (output, used, frac, buffer, "
          f"bit for bit); fetched {got[6]}", ring and got[0] == want[0] == 1 and got[1:4] == want[1:4]
          and np.array_equal(got[4].view(np.uint32), want[4].view(np.uint32))
          and (not stereo or np.array_equal(got[5].view(np.uint32), want[5].view(np.uint32))), (got[:4], want[:4], got[6], want[6]))

# off the seam: filter.c's machine modes read the mapped position (test_clip.py's model)
FIR26 = [0.00302, 0.24563, 0.5027, 0.24563, 0.00302]


def drop_model(P, rate, n, grid=26040):
    g, out = 48000 / grid, []
    for i in range(n):
        j = round(np.floor((P + i * rate) / g + 1 / 8192) * g)
        out.append(sum(FIR26[t] * float(L_SIG[(j - 2 + t) % LENU]) for t in range(5)))
    return np.array(out)


set_latch(cw_m, 1, 30000)
fidelity(cw_m, 2)
got = read(cw_m, "clip_read_b", 5000, 0.25, 0.5)
bad = np.where(np.abs(got[4] - drop_model(35000 + 1.25, 0.5, 64)) > 2e-4)[0]
fidelity(cw_m, 0)
norm = read(cw_m, "clip_read_b", 5000, 0.25, 0.5)
check("off the seam, Fidelity SP1200, rate 0.5: the drop-sample reader at the mapped position (35 000; test_clip.py's "
      f"model, {len(bad)} of 64 off), position bookkeeping as Fidelity Normal, one fetch from real - 3 {got[6]}",
      len(bad) <= 2 and got[1:3] == norm[1:3] and got[6] == [(34997, 40)], (bad[:4], got[1:3], norm[1:3], got[6]))

# a machine mode at or near the seam: filter.c's machine reader over the circular region (clip_read_ring), seam or not.
# The reference: filter.c's own clip_read at the real position on the file truly circular, bit for bit.
MODES = ((2, "SP1200"), (3, "SP-12"), (4, "S950"), (5, "MPC60"), (6, "SP Raw"), (7, "S950 Lo"), (8, "SP 45"))
circ_m = reader(IMAGE, rotate=0)


def same_read(got, want, stereo):
    return got[:4] == want[:4] and np.array_equal(got[4].view(np.uint32), want[4].view(np.uint32)) and (
        not stereo or np.array_equal(got[5].view(np.uint32), want[5].view(np.uint32)))


fidelity(cw_m, 2)
fidelity(circ_m, 2)
set_latch(cw_m, 1, 30000)
got = read(cw_m, "clip_read_b", 19980, 0.25, 0.5)
want = read(circ_m, "clip_read", 49980, 0.25, 0.5)
check(f"on the seam, Fidelity SP1200, rate 0.5 (real 49 980): filter.c's machine reader over the circular file, bit for "
      f"bit its clip_read on the file turned circular (output, used, frac, buffer); fetched {got[6]}, all inside the file",
      same_read(got, want, False) and got[6] == [(49977, 23), (0, 17)], (got[:4], want[:4], got[6], want[6]))
set_latch(cw_m, 1, 30001)
got = read(cw_m, "clip_read_b", 20000, 0.25, 0.5)
want = read(circ_m, "clip_read", 50001, 0.25, 0.5)
check("Fidelity SP1200 one frame into the file (real 1): the machine reader's back-step wraps to the file's end, bit for "
      "bit clip_read on the circular file one pass later (50 001: the 26 040 Hz grid repeats every 50 000 frames, 27 125 "
      f"steps); fetched {got[6]}", same_read(got, want, False) and got[6] == [(49998, 2), (0, 38)],
      (got[:4], want[:4], got[6], want[6]))

# F1: rate 1, frac 0 on the last blocks before the seam. Stock's straight copy needs n frames and has no seam there; a
# machine reads [real - 3, real + n + 5), across the end (gap 0..4) or onto it (5)
for v, name in MODES:
    fidelity(cw_m, v)
    fidelity(circ_m, v)
    bad, outside = [], []
    for stereo in (False, True):
        for gap in range(6):
            real = LENU - N - gap
            set_latch(cw_m, 1, 30000)
            got = read(cw_m, "clip_read_b", real - 30000, 0.0, 1.0, stereo, n=N)
            want = read(circ_m, "clip_read", real, 0.0, 1.0, stereo, n=N)
            outside += [f for f in got[6] if not 0 <= f[0] <= f[0] + f[1] <= LENU]
            if not (same_read(got, want, stereo) and got[6][0][0] == real - 3 and sum(c for _, c in got[6]) == N + 8):
                bad.append((stereo, gap, got[:4], want[:4], got[6]))
    check(f"F1, Fidelity {name}, rate 1, frac 0, real = len - 128 - 0..5, mono and stereo: the machine's 136 frames from "
          "real - 3 fetched inside [0, len) only (in two parts where they wrap), and bit for bit clip_read on the circular file",
          not bad and not outside, (bad[:2], outside[:4]))

# near the start (real 0..2): the back-step wraps to the end. The reference reads one pass later, on a 240 000-frame file
# (5 x 48 000: the grid of every machine but SP 45, 19 288.9 Hz, repeats over it)
LONG = 240000
long_m, long_ref = reader(IMAGE, length=LONG), reader(IMAGE, rotate=0, length=LONG)
for v, name in MODES[:6]:
    fidelity(long_m, v)
    fidelity(long_ref, v)
    bad = []
    for stereo in (False, True):
        for real, rate, frac in ((0, 1.0, 0.0), (1, 1.0, 0.0), (2, 1.0, 0.0), (1, 0.91875, 0.4), (2, 0.8, 0.1)):
            set_latch(long_m, 1, 1234, length=LONG)
            got = read(long_m, "clip_read_b", (real - 1234) % LONG, frac, rate, stereo, n=N)
            want = read(long_ref, "clip_read", real + LONG, frac, rate, stereo, n=N)
            if not (same_read(got, want, stereo) and got[6][0] == (LONG - 3 + real, 3 - real)
                    and all(0 <= p_ <= p_ + c_ <= LONG for p_, c_ in got[6])):
                bad.append((real, rate, stereo, got[:4], want[:4], got[6]))
    check(f"near the start, Fidelity {name}, real 0 / 1 / 2 at rates 1, 0.91875, 0.8, mono and stereo: the back-step's "
          "frames fetched from the file's end, nothing outside it, and bit for bit clip_read on the circular file one pass "
          "later", not bad, bad[:2])

# ABI-1: the filter object's rate (+0x60) is the reader's to write; a clocked machine (S950, S950 Lo) takes its DAC clock
# and its low-pass from it, and a rate that makes no sense as "no reader ran". A seam block must write it too.
for v, name in ((4, "S950"), (7, "S950 Lo")):
    fidelity(cw_m, v)
    fidelity(circ_m, v)
    rows = []
    for stereo in (False, True):
        for rate, frac, real in ((0.91875, 0.4, LENU - 20), (1.0, 0.0, LENU - 60), (1.498, 0.3, LENU - 60)):
            set_latch(cw_m, 1, 30000)
            cw_m.uc.mem_write(VOICE + 0x14C + 0x60, struct.pack("<f", 0.5))       # left by another rate
            got = read(cw_m, "clip_read_b", real - 30000, frac, rate, stereo, n=N)
            after = struct.unpack("<f", cw_m.uc.mem_read(VOICE + 0x14C + 0x60, 4))[0]
            want = read(circ_m, "clip_read", real, frac, rate, stereo, n=N)
            rows.append((rate, stereo, after, len(got[6]) == 2 and same_read(got, want, stereo)))
    check(f"ABI-1, Fidelity {name}: a stale rate at the filter object + 0x60 (0.5) is rewritten by a seam block (rates "
          "0.91875, 1, 1.498, mono and stereo, the fetch in two parts), and the block is clip_read's on the circular file",
          all(after == np.float32(rate) and ok_ for rate, _, after, ok_ in rows), rows)
fidelity(cw_m, 0)

# when the read is not ours to map
base_m = reader(IMAGE)
for name, prep, kw in (("the latch is not valid", lambda m: set_latch(m, 1, 30000, valid=False), {}),
                       ("the latch is for another slot", lambda m: set_latch(m, 2, 30000), {}),
                       ("&frac is not a segment's fraction", lambda m: set_latch(m, 1, 30000), dict(frac_at=RPAD + 0x30 + 0x70 + 0x20)),
                       ("&frac is past the fourth segment", lambda m: set_latch(m, 1, 30000), dict(frac_at=RPAD + 0x30 + 4 * 0x70 + 0x1C)),
                       ("the pad is cell 0x401", lambda m: (set_latch(m, 1, 30000), m.w32(RPAD + 0x18, 0x401)), {}),
                       ("the latch was made for a 96 000-frame file and the pad's file is now 50 000 frames (a load since "
                        "H1; the old mapping would read at 49 970)", lambda m: set_latch(m, 1, 30000, length=96000), {}),
                       ("no SDRAM block", lambda m: (set_latch(m, 1, 30000), sdram(m, False)), {})):
    m = reader(IMAGE)
    prep(m)
    got = read(m, "clip_read_b", 19970, 0.25, 0.7, **kw)
    want = read(base_m, "clip_read", 19970, 0.25, 0.7, **kw)
    check(f"{name}: filter.c's clip_read, unchanged", got[:4] == want[:4] and np.array_equal(got[4], want[4]) and got[6] == want[6],
          (got[:4], want[:4], got[6], want[6]))

# thunks entered as the patched sites enter them


def enter(m, thunk, r4, words):
    sp = STACK - 0x100
    for off, v in words.items():
        m.w32(sp + off, v)
    for reg, v in ((UC_ARM_REG_R0, RSRC), (UC_ARM_REG_R1, 1234), (UC_ARM_REG_R2, 0x33330000), (UC_ARM_REG_R3, 0x44440000),
                   (UC_ARM_REG_R4, r4)):
        m.uc.reg_write(reg, v)
    m.uc.reg_write(UC_ARM_REG_SP, sp)
    m.uc.reg_write(UC_ARM_REG_LR, RET | 1)
    m.uc.emu_start(S[thunk] | 1, RET, count=1_000_000)
    return m.uc.reg_read(UC_ARM_REG_PC) == RET and m.uc.reg_read(UC_ARM_REG_SP) == sp and m.uc.reg_read(UC_ARM_REG_R4) == r4


m = reader(IMAGE)
pf = []
m.stub(PREFETCH, lambda: pf.append((m.arg(0), m.arg(1))))
set_latch(m, 2, 777)
for at in (B_VALID, B_H1, B_HINTED):
    m.uc.mem_write(BANK + at + QU, b"\x0f")
bits = lambda: [m.r8(BANK + at + QU) for at in (B_VALID, B_H1, B_HINTED)]
ok = enter(m, "clipwin_slice_start_b", RPAD, {4: 2, 0x20: 1})
check("H1' thunk: the slot from [sp + 4], the pad from r4: that slot's latch and its 'made through H1' bit cleared, the "
      "others kept, the prefetch called with the caller's source and position", ok and bits() == [0x0B, 0x0B, 0x0F]
      and pf == [(RSRC, 1234)], ([hex(x) for x in bits()], pf))
m.uc.mem_write(RPAD + 0x29, b"\x01")
m.uc.mem_write(RPAD + 0x208, struct.pack("<qI", 960, 4))
m.uc.mem_write(RPAD + 0x30 + 3 * 0x70 + 8, struct.pack("<q", 37000))
m.w32(BANK + B_SLIP + 4 * QU, 960)
m.uc.mem_write(BANK + B_H1 + QU, b"\x03")                     # slot 3 last held a slice segment
pf.clear()
ok = enter(m, "clipwin_seg_start_b", RPAD, {4: 1, 0x20: 3})
check("H1 thunk: the slot from [sp + 0x20]: slot 3 latched (0, 50 000, 12 500) for the 50 000-frame file, marked made "
      "through H1, its seam hint re-armed (hinted bit cleared), prefetched at 37 000 + 12 500 - 8",
      ok and bits() == [0x0B, 0x0B, 0x07] and latch(m, QU, 3) == (0, LENU, 12500) and made_for(m, QU, 3) == LENU
      and pf == [(RSRC, 49492)] and u32(m, BANK + B_PAD + 4 * QU) == RPAD, ([hex(x) for x in bits()], latch(m, QU, 3), pf))

# ====================================================================================================== 8. rate, stereo


def rate_case(name, frames, src_rate, stereo, slip, pitch=None):
    pre = (lambda rr: rr.param(0x5C, pitch) if rr.block == 0 else None) if pitch else None
    sc = dict(frames=frames, src_rate=src_rate, stereo=stereo, cell=0x102, pre=pre)
    rd0, rr0 = scenario(dc=True, **sc), scenario(**sc)
    rd1, rr1 = scenario(dc=True, slip=slip, **sc), scenario(slip=slip, **sc)
    sf = slip_f(slip, frames, 3840)
    rate = struct.unpack("<f", struct.pack("<I", rr1.reads[3][4]))[0]
    for ch in ((0, 1) if stereo else (0,)):
        n, err, bad, gd = shifted(decode(rd0, rr0, ch), decode(rd1, rr1, ch), sf, frames, edge=3)
        check(f"{name}{', right' if ch else (', left' if stereo else '')} (rate {rate:.5f}), Slip {slip}: every sounding "
              f"sample plays stock + slip_f ({n} samples, max {err:.4f} frame; the 3 frames at each end of the file "
              "aside), summed gain = stock's", n > 90000 and err <= 0.02 and bad == 0 and gd == 0, (n, err, bad, gd))
    seam = rr1.seam_reads()
    check(f"  {len(seam)} seam block(s) read through clipwin_read's own fetch{' pair' if stereo else ''} and "
          f"{'the kernel' if rate != 1.0 else 'the straight copy'}", len(seam) >= 1 and all(len(x[FET]) == 2 for x in seam if x[FET][0][1] > 3))


rate_case("44.1 kHz file (88 200 frames)", 88200, 44100, False, 960)
rate_case("stereo 48 kHz", 96000, 48000, True, -30)
rate_case("stereo 44.1 kHz", 88200, 44100, True, 3839)
rate_case("Pitch +7 semitones", 96000, 48000, False, 960, pitch=7000)

# ====================================================================================================== 9. the knob
texts, posts = [], []
e.stub(0x080C3B98, lambda: texts.append((e.arg(0), e.cstr(e.arg(1)))))
e.stub(0x080B0480)
e.stub(0x080AED14, lambda: posts.append((e.r16(e.arg(1)), e.r32(e.arg(1) + 0xC), e.r32(e.arg(1) + 0x10))))
LIST = 0x24050000
KN = LIST + 0x120


def fresh():
    e.uc.mem_write(LIST, bytes(0xA000))
    e.w32(KN, 0x080F0C88)
    e.uc.mem_write(LIST + 0x404, b"\x01")


def vtext():
    return [x for a, x in texts if a == KN + 0x9C]


regs = registrar(e, TABLE)                             # a real table for the binder
for v, want in ((1240, "+1.280"), (-30, "-0.030"), (0, "+0.000"), (959, "+0.959"), (3840, "+4.000"), (-3840, "-4.000")):
    fresh()
    texts.clear()
    e.call(0x080A7EE0, P_SLIP, v, KN)
    check(f"Slip {v} on a knob bound by the stock binder: type {e.r8(KN + 0x31)}, range {e.r32(KN + 0x14C)}..{e.r32(KN + 0x150)}, "
          f"text {want!r} (beats.ticks)", vtext()[-1:] == [want] and e.r8(KN + 0x31) == 1
          and (e.r32(KN + 0x14C), e.r32(KN + 0x150)) == (-3840, 3840), (vtext(), e.r8(KN + 0x31)))
fresh()
e.w32(KN + 0x14, P_SLIP)
e.call(0x080B04C8, KN)
texts.clear()
e.call(0x080B0790, KN, 1240)
check("a reset knob that kept the stale id 0x1c9 (type 0) prints what stock prints there: ''", vtext() == [""], vtext())
fresh()
e.call(0x080A7EE0, P_SLIP, 1240, KN)
e.uc.mem_write(KN + 0x2D8, b"\x01")
texts.clear()
e.call("clipwin_format", KN)
ours_ = vtext()
texts.clear()
e.call(0x080B0528, KN)
check(f"a frozen knob (+0x2d8 set): clipwin_format leaves it to the stock formatter (text {ours_}, stock {vtext()})",
      ours_ == vtext() and "+1.280" not in ours_, (ours_, vtext()))
e.uc.mem_write(TABLE + P_SLIP * 0x1C + 2, b"\x09")         # registered as a type-9 row instead (P3 may)
fresh()
texts.clear()
e.call(0x080A7EE0, P_SLIP, 1240, KN)
check("the same row registered as type 9 (a list position): the value it stands for, '+1.280'",
      e.r8(KN + 0x31) == 9 and vtext()[-1:] == ["+1.280"], (e.r8(KN + 0x31), vtext()))
e.uc.mem_write(TABLE + P_SLIP * 0x1C + 2, b"\x01")


def turn(path, per_ms, events=40, sign=1, start=0, fresh_knob=True, t0=10_000, period=16, seq=None):
    """`events` turn events `period` ms apart at `per_ms` counts per ms; returns (value, counts sent, last time), and
    appends (time, value) after each event to `seq` if given. A fresh knob comes with its acceleration ring (8 x
    {counts, ms} at +0x294, write index at +0x2d4) as if it had been turning at that speed for 8 events already:
    fresh() zeroes the widget, and a ring of zeros would read as a slow turn. The bank's detent state (the last arrival
    on 0) is left as it is: a fresh knob is a new turn, not a new unit."""
    c, t = sign * int(per_ms * period), t0
    if fresh_knob:
        fresh()
        e.call(0x080A7EE0, P_SLIP, start, KN)
        posts.clear()
        texts.clear()
        for k in range(8):
            e.uc.mem_write(KN + 0x294 + 8 * k, struct.pack("<iI", c, t - period * (7 - k)))
        e.w32(KN + 0x2D4, 0)
    for _ in range(events):
        t += period
        e.w32(GUI_MS, t)
        if path == "list":
            e.call(0x080B9A3C, LIST, c)
        else:
            e.call(0x080B0D54, KN, c)
        if seq is not None:
            seq.append((t, e.r32(KN + 0x27C) + e.r32(KN + 0x288)))
    return e.r32(KN + 0x27C) + e.r32(KN + 0x288), c * events, t


# The knob, v2 (37.2.1; Thomas on 37.2.0d: "blocking at 0 is not great ... accelerator is too fast it seems"): by the
# stock accelerator's speed m (1 .. 6), slow = single ticks (40 counts a tick, twice that at speed 2), medium = one
# KNOB_STEP_MEDIUM a turn event onto its grid, fast (the top speeds) = one 1/64 (60 ticks) a turn event onto the 1/64
# grid; 0 is a detent: a turn that reaches it stops there, and passes ZERO_DETENT_MS after it ARRIVED. The numbers are
# read from src/clipwin_b2.c's #defines (the rule is bank 2's, cw_turn, since D-018), so that tuning one on the unit
# leaves these checks about the shape. The detent's state lives in cw_bank (SDRAM), as on the unit, so the block is
# there for these.
_knob_src = open("src/clipwin_b2.c").read()
KNOB_DEF = {n: int(re.search(rf"^#define {n}\s+(\d+)", _knob_src, re.M).group(1))
            for n in ("KNOB_MEDIUM", "KNOB_FAST", "KNOB_STEP_MEDIUM", "SLIP_GRID", "ZERO_DETENT_MS")}
MED_AT, FAST_AT, MED_STEP, GRID, DETENT = KNOB_DEF.values()
info(f"the knob's numbers (src/clipwin_b2.c): medium from speed {MED_AT}, fast from {FAST_AT}, a medium step {MED_STEP} "
     f"ticks, the 1/64 grid {GRID}, the detent {DETENT} ms")


def at_speed(m):
    """counts per ms that the stock accelerator reads as speed m: trunc(|sum of the last 8 counts| / their 7 periods)"""
    return (m + 0.5) * 7 / 8


def tier(m):
    return "slow" if m < MED_AT else "medium" if m < FAST_AT else "fast"


def slow_ticks(m, c, events):
    """slow: what the stock stepper (FUN_080b0b74, its step/3 hysteresis and all) makes of counts x 10 x m an event,
    from 0 on a fresh knob"""
    fresh()
    e.call(0x080A7EE0, P_SLIP, 0, KN)
    for _ in range(events):
        e.call(0x080B0B74, KN + 0x270, c * 10 * m)
    return e.r32(KN + 0x27C) + e.r32(KN + 0x288)


try:
    e.uc.mem_map(0xC0000000, 0x1800000)
except Exception:
    pass                                                    # already mapped
e.uc.mem_map(0x38800000, 0x1000) if not any(r[0] == 0x38800000 for r in e.uc.mem_regions()) else None
e.uc.mem_map(0x58024000, 0x1000) if not any(r[0] == 0x58024000 for r in e.uc.mem_regions()) else None
sdram(e)
e.w32(BANK, 0)                                              # bank() sets itself up on first use
TOP = 6                                                     # the top speed: a fast turn whatever KNOB_FAST says
for path in ("list", "turn"):
    name = "pad page list (FUN_080b9a3c)" if path == "list" else "waveform turn (FUN_080b0d54)"
    slow, counts, _ = turn(path, 0.7)
    med, mcounts, _ = turn(path, 2.5)
    check(f"{name}: slow, 1 tick per 40 counts ({counts} counts -> {slow}); speed 2, 2 ticks per 40 ({mcounts} -> {med})",
          slow == counts // 40 and med == 2 * mcounts // 40, (slow, counts, med, mcounts))
    # every speed, 7 events from 0: its tier's step; and what each event leaves in cw_bank for the bench
    got, want, seen = [], [], []
    for m_ in range(1, 7):
        v, cnt, _ = turn(path, at_speed(m_), events=7, sign=-1 if m_ & 1 and m_ >= MED_AT else 1)
        got.append(v)
        sgn = 1 if cnt > 0 else -1
        seen.append((struct.unpack("<h", bytes(e.uc.mem_read(BANK + B_KNOB_COUNTS, 2)))[0], e.r8(BANK + B_KNOB_SPEED),
                     cnt // 7))
        want.append(slow_ticks(m_, cnt // 7, 7) if m_ < MED_AT else 7 * sgn * (MED_STEP if m_ < FAST_AT else GRID))
    check(f"  speeds 1 .. 6 (odd ones from medium on down), 7 events from 0: "
          f"{', '.join(f'{m_} {tier(m_)} {g:+d}' for m_, g in enumerate(got, 1))} - slow = the stepper fed counts x 10 x "
          f"speed (single ticks), one {MED_STEP}-tick step a turn event from speed {MED_AT}, one 1/64 ({GRID}) from speed "
          f"{FAST_AT}", got == want, (got, want))
    check(f"  each event leaves its counts (i16) and the speed (u8) at cw_bank + {B_KNOB_COUNTS:#x} for bbusb.py knob "
          f"({[x[:2] for x in seen]})", all(x[0] == x[2] and x[1] == m_ for m_, x in enumerate(seen, 1)), seen)
    fast = [turn(path, s_, events=7)[0] for s_ in (3, 4, 6, 12)]
    check(f"  3 and 4 counts/ms (speeds 3 and 4: medium) give {7 * MED_STEP}, 6 and 12 (speed 6: fast) {7 * GRID}, for 7 "
          f"events from 0 ({fast}); 37.2.0d gave {7 * GRID} for all four",
          fast == [7 * MED_STEP] * 2 + [7 * GRID] * 2, fast)
    snaps = [turn(path, at_speed(MED_AT), events=3, start=25)[0],
             turn(path, at_speed(MED_AT), events=3, sign=-1, start=125)[0],
             turn(path, at_speed(TOP), events=3, start=25)[0],
             turn(path, at_speed(TOP), events=2, start=130)[0],
             turn(path, at_speed(TOP), events=2, sign=-1, start=-25)[0]]
    want = [25 // MED_STEP * MED_STEP + 3 * MED_STEP, -(-125 // MED_STEP) * MED_STEP - 3 * MED_STEP,
            25 // GRID * GRID + 3 * GRID, 130 // GRID * GRID + 2 * GRID, -(25 // GRID * GRID) - 2 * GRID]
    check(f"  off-grid values snap to the tier's grid first: medium up from +25 and down from +125, three events -> "
          f"{snaps[0]}, {snaps[1]}; fast up from +25, three -> {snaps[2]}; from the medium step +130, two -> {snaps[3]}; "
          f"down from -25, two -> {snaps[4]} (the 1/64 grid)",
          snaps == want and all(x % GRID == 0 for x in snaps[2:]), (snaps, want))
    v, _, _ = turn(path, 12, events=80)
    check("  fast up stops at +3840 (64 grid steps); the text follows, and the app is sent 0x1c9 = the value",
          v == 3840 and vtext()[-1:] == ["+4.000"] and posts and posts[-1] == (0x3D, 3840, P_SLIP), (v, vtext()[-1:], posts[-1:]))
    v, _, _ = turn(path, 12, events=80, sign=-1)
    check("  fast down stops at -3840 too", v == -3840 and vtext()[-1:] == ["-4.000"], (v, vtext()[-1:]))

    # the detent on 0: fast down from +300, an event every 16 ms
    sq = []
    turn(path, at_speed(TOP), events=20, sign=-1, start=300, t0=20_000, seq=sq)
    vals = [x for _, x in sq]
    t_arr = sq[4][0]
    held = [x for tt, x in sq[5:] if tt - t_arr < DETENT]
    after = [x for tt, x in sq[5:] if tt - t_arr >= DETENT]
    check(f"  fast down from +300 (16 ms events): {vals[:5]} - it stops on 0, holds there for {len(held)} events (those "
          f"under {DETENT} ms after the arrival), then goes past it at its speed ({after[:3]} ...; text {vtext()[-1:]})",
          vals[:5] == [240, 180, 120, 60, 0] and held == [0] * len(held) and len(held) == (DETENT - 1) // 16
          and after == [-GRID * (i + 1) for i in range(len(after))] and len(after) > 0
          and vtext()[-1:] == [f"-{len(after) * GRID // 960}.{len(after) * GRID % 960:03d}"], (vals, vtext()[-1:]))
    # the pause counts from the arrival, not from the last event: a steady stream every 20 ms passes (37.2.0d: a wall)
    sq = []
    turn(path, at_speed(TOP), events=30, sign=-1, start=300, t0=30_000, period=20, seq=sq)
    t_arr = next(tt for tt, x in sq if x == 0)
    first = next((tt for tt, x in sq if x < 0), None)
    want_first = t_arr + -(-DETENT // 20) * 20
    check(f"  a steady stream, an event every 20 ms: it passes 0 {None if first is None else first - t_arr} ms after it "
          f"arrived (the first event {DETENT} ms or more on; 37.2.0d held it there for as long as it went on), then one "
          f"1/64 an event ({[x for _, x in sq][-3:]})",
          first == want_first and sq[-1][1] == -GRID * ((sq[-1][0] - first) // 20 + 1), (first, want_first, sq))
    # a new turn the same way inside the pause is still in it; one after it, from rest, moves at once
    v, _, t = turn(path, at_speed(TOP), events=5, sign=-1, start=300, t0=40_000)       # arrives at 40 080
    v_in, _, _ = turn(path, at_speed(TOP), events=1, sign=-1, start=0, t0=t + DETENT - 30)
    v_rest, _, _ = turn(path, at_speed(TOP), events=1, sign=-1, start=0, t0=t + DETENT)
    check(f"  a turn that arrived on 0 ({v}), then a new one the same way {DETENT - 14} ms after the arrival: still on 0 "
          f"({v_in}); {DETENT + 16} ms after: off at once ({v_rest})", v == 0 and v_in == 0 and v_rest == -GRID,
          (v, v_in, v_rest))
    v_set = [turn(path, at_speed(m_), events=1, sign=s_, start=0, t0=50_000)[0] for m_, s_ in ((MED_AT, 1), (TOP, -1))]
    check(f"  a turn starting at 0 from rest: its first event moves, medium +{MED_STEP}, fast -{GRID} ({v_set})",
          v_set == [MED_STEP, -GRID], v_set)
    # the other way leaves 0 at once (at the speed the stock ring reads then: its sum of signed counts drops on a
    # reversal, so the first event back is a tier lower: fast -> medium, medium -> slow)
    v, _, t = turn(path, at_speed(TOP), events=5, sign=1, start=-200, t0=60_000)
    v_back, _, _ = turn(path, at_speed(TOP), events=1, sign=-1, fresh_knob=False, t0=t)
    spd = e.r8(BANK + B_KNOB_SPEED)
    v2, _, t = turn(path, at_speed(MED_AT), events=21, sign=1, start=-200, t0=70_000)
    v_mback, _, _ = turn(path, at_speed(MED_AT), events=1, sign=-1, fresh_knob=False, t0=t)
    mspd = e.r8(BANK + B_KNOB_SPEED)
    step_of = lambda m_: GRID if m_ >= FAST_AT else MED_STEP if m_ >= MED_AT else None
    check(f"  fast up from -200 holds 0 ({v}); turning the other way 16 ms later moves at once ({v_back}, speed {spd}); "
          f"medium the same ({v2}, then {v_mback}, speed {mspd})",
          v == 0 and v2 == 0 and v_back < 0 and v_mback < 0 and (step_of(spd) is None or v_back == -step_of(spd))
          and (step_of(mspd) is None or v_mback == -step_of(mspd)), (v, v_back, spd, v2, v_mback, mspd))
    # medium and slow arrive there too
    sq = []
    turn(path, at_speed(MED_AT), events=20, sign=-1, start=35, t0=80_000, seq=sq)
    vals = [x for _, x in sq]
    t_arr = sq[3][0]
    after = [x for tt, x in sq[4:] if tt - t_arr >= DETENT]
    check(f"  medium down from +35: {vals[:4]}, the detent, then on ({after[:3]} ...)",
          vals[:4] == [30, 20, 10, 0] and all(x == 0 for tt, x in sq[4:] if tt - t_arr < DETENT) and len(after) > 0
          and after == [-MED_STEP * (i + 1) for i in range(len(after))], vals)
    sq = []
    _, c_, _ = turn(path, 0.7, events=60, sign=-1, start=5, t0=90_000, seq=sq)
    vals = [x for _, x in sq]
    i_arr = vals.index(0) if 0 in vals else 0
    t_arr = sq[i_arr][0]
    check(f"  slow down from +5 ({c_} counts): single ticks down to 0 ({vals[i_arr - 2:i_arr + 1]}), held there for the "
          f"events under {DETENT} ms after the arrival, then single ticks on ({vals[-3:]})",
          0 in vals and all(0 <= a - b <= 1 for a, b in zip(vals, vals[1:])) and vals[-1] < 0
          and all(x == 0 for tt, x in sq[i_arr:] if tt - t_arr < DETENT), vals)

# other knobs: the same text, steps and posts as on the stock image
for m_ in (st_m,):
    m_.stub(0x080B0480)
st_texts, st_posts = [], []
st_m.stub(0x080C3B98, lambda: st_texts.append((st_m.arg(0), st_m.cstr(st_m.arg(1)))))
st_m.stub(0x080AED14, lambda: st_posts.append((st_m.r16(st_m.arg(1)), st_m.r32(st_m.arg(1) + 0xC), st_m.r32(st_m.arg(1) + 0x10))))
others = [r for r in stock_regs if r[1] in (1, 0xD, 9)][:6]


def knob_run(m, tx, ps, pid, v, counts):
    m.uc.mem_write(LIST, bytes(0xA000))
    m.w32(KN, 0x080F0C88)
    tx.clear()
    ps.clear()
    m.call(0x080A7EE0, pid, v, KN)
    t_ = 50_000
    for c in counts:
        t_ += 16
        m.w32(GUI_MS, t_)
        m.call(0x080B0D54, KN, c)
    return [x for a, x in tx if a == KN + 0x9C], list(ps), m.r32(KN + 0x34), m.r32(KN + 0x27C)


for pid, typ, lab, lo, hi, xml in others:
    v = lo + (hi - lo) // 3
    counts = [11] * 10 + [192] * 10 + [-40] * 5
    a_, b_ = knob_run(e, texts, posts, pid, v, counts), knob_run(st_m, st_texts, st_posts, pid, v, counts)
    check(f"another knob ({lab!r}, id {pid:#x}, type {typ}): bound and turned slow and fast, the same text, posts and "
          "position as on the stock image", a_ == b_, (a_[0][-2:], b_[0][-2:], a_[1][-1:], b_[1][-1:], a_[2:], b_[2:]))

# ====================================================================================================== 10. Region
# Region (README section 3): the clip plays the Sample-mode loop [Loop Start, Loop End) - the cell's class-H object keeps
# it in Clip mode too - as if it were the file: the clip's length (H3) is the region's, so Beat Count Auto, the steps and
# the last step's end follow it, every segment latches the region in H1 and reads it circularly in H2. A change while it
# plays waits for the next wrap (H3'). Seamless wrap: Loop On and not Trigger, the last step crossfades into step 0.


def region_bank(m, q):
    return struct.unpack("<2i", m.uc.mem_read(BANK + B_REGION + 8 * q, 8))


# ---- unit: the rule, the source and the gating, clipwin_len called as the thunks call it
u = Emu(IMAGE, "out/cave.elf")
maps(u)
sdram(u)
u.uc.mem_write(BANK, bytes(0x800))
UQ, UL, UH, USRC = 6, 0x24060000, 0x24061000, 0x24062000
ulen = [96000]
u.stub(SRC_LEN, lambda: u.ret(ulen[0]))
u.uc.mem_write(UL, bytes(0xC00))
u.uc.mem_write(UL + 4, b"\x4c")
u.w32(UL + 0x18, 0x102)
u.uc.mem_write(UL + 0x29, b"\x01")
u.uc.mem_write(UL + 0x1F4, bytes([1, 0, 0, 0, 3]))           # Loop On; Launch Toggle (+0x1f8 = 3)
u.uc.mem_write(UL + 0x220, struct.pack("<q", 960))           # Sync 1/4
u.uc.mem_write(UH, bytes(0x5C4))
u.uc.mem_write(UH + 4, b"\x48")
u.w32(UH + 0x18, 0x102)
u.w32(UL + 8, UH)


def h_loop(ls, le, mode):
    u.uc.mem_write(UH + 0xFC, struct.pack("<iii", ls, le, 0))
    u.w32(UH + 0x108, mode)


def len_at(site):
    u.call("clipwin_len", USRC, UL, site)
    return u.uc.reg_read(UC_ARM_REG_R0)


def ulen_call(site, layer=0):
    u.uc.mem_write(UL + 0x260, bytes([layer]))
    return len_at(site)


rule = [  # Region, Loop Mode, Loop Start, Loop End -> the region (rs, vlen), or None = the whole file
    (AUTO, 1, 24000, 72000, (24000, 48000), "a loop inside the file"),
    (AUTO, 2, 10000, 30000, (10000, 20000), "Bidirect counts as a loop"),
    (AUTO, 0, 24000, 72000, (24000, 48000), "Loop Mode None: the loop all the same (Gate 3 finding 7)"),
    (AUTO, 1, 0, 96000, None, "[0, len) with Loop Forward: what a load leaves (x3 t13)"),
    (AUTO, 1, 0, 95999, None, "[0, len - 1]: a whole-file smpl loop"),
    (AUTO, 1, 0, 95998, (0, 95998), "[0, len - 2]"),
    (AUTO, 1, 0, 72000, (0, 72000), "from the start"),
    (AUTO, 1, 24000, 96000, (24000, 72000), "to the end"),
    (AUTO, 1, 50000, 40000, None, "start after end"),
    (AUTO, 1, 24000, 24000, None, "start = end"),
    (AUTO, 1, 24000, 100000, None, "end past the file"),
    (AUTO, 1, -5, 72000, None, "negative start"),
    (AUTO, 1, 0, 0, None, "Loop End 0 (no file yet, or a store being rebuilt)"),
    (FILE, 1, 24000, 72000, None, "File, whatever the loop"),
    (LOOP, 0, 24000, 72000, (24000, 48000), "Loop, whatever Loop Mode says"),
    (LOOP, 0, 0, 95999, None, "Loop on [0, len - 1] (a whole-file smpl loop, dwEnd inclusive) is the file too"),
    (LOOP, 0, 0, 95998, (0, 95998), "Loop on [0, len - 2]"),
    (LOOP, 1, 0, 96000, None, "Loop on the whole file is the file"),
    (LOOP, 1, 50000, 40000, None, "Loop, start after end"),
    (7, 1, 24000, 72000, (24000, 48000), "a value past the list reads as Auto"),
]
bad = []
for reg, mode, ls, le, want, what in rule:
    store(u, UQ, {0x4: 500, P_REGION: reg})
    h_loop(ls, le, mode)
    u.uc.mem_write(BANK + B_REGION + 8 * UQ, struct.pack("<2i", 777, 777))
    got = ulen_call(1)
    r_ = region_bank(u, UQ)
    ok = (r_ == want and got == want[1]) if want else (r_[1] == 0 and got == 96000)
    if not ok:
        bad.append((what, got, r_, want))
check(f"the Auto rule and File / Loop over {len(rule)} loop-point cases (len 96 000; the class-H object's Loop Start +0xfc, "
      "Loop End +0x100, Loop Mode +0x108): Auto = Loop = any 0 <= start < end <= len but the whole file ([0, >= len - 1]), "
      "Loop Mode not asked; the recompute's length is the region's", not bad, bad)
store(u, UQ, {0x4: 500, P_REGION: AUTO})
h_loop(24000, 72000, 1)
rows = []
for n_, what in ((0, "not open"), (0x10000000, "the provider reported 0 frames")):
    ulen[0] = n_
    rows.append((ulen_call(1), region_bank(u, UQ)[1], ulen_call(0), ulen_call(2)))
ulen[0] = 96000
check(f"fw_src_len 0 / 0x10000000: no region, the length passed on as it is at every site ({rows})",
      rows == [(0, 0, 0, 0), (0x10000000, 0, 0x10000000, 0x10000000)], rows)
ulen_call(1)
rows = {}
for what, at, val, want in (("Clip", None, None, (48000, 48000, 1)),
                            ("Launch Trigger", 0x1F8, 1, (48000, 48000, 48000)),
                            ("Loop Off", 0x1F4, 0, (48000, 48000, 48000)),
                            ("a Slicer pad", 0x254, 1, (96000, 96000, 96000)),
                            ("Clip / Slicer mode off", 0x29, 0, (96000, 96000, 96000)),
                            ("Sync Slice with slice markers", 0x220, None, (96000, 96000, 96000)),
                            ("Sync Slice, no markers", 0x221, None, (48000, 48000, 1))):
    keep = bytes(u.uc.mem_read(UL, 0xC00))
    if at == 0x220:
        u.uc.mem_write(UL + 0x220, struct.pack("<q", 0xF0000))
        u.w32(UL + 0x250, 4)
    elif at == 0x221:
        u.uc.mem_write(UL + 0x220, struct.pack("<q", 0xF0000))
    elif at is not None:
        u.uc.mem_write(UL + at, bytes([val]))
    rows[what] = (ulen_call(0, 1), ulen_call(1, 1), ulen_call(2, 1))
    u.uc.mem_write(UL, keep)
check("the sites while it plays: the region's length at the recompute and the > 0 check, and at the last step's end 1 "
      "(seamless: end = 0) - but the region's end on a one-shot (Launch Trigger, or Loop Off); the whole file on a Slicer "
      f"pad, a pad not in Clip / Slicer mode, and Sync Slice with markers: {rows}",
      all(rows[w] == x for w, x in (("Clip", (48000, 48000, 1)), ("Launch Trigger", (48000, 48000, 48000)),
                                     ("Loop Off", (48000, 48000, 48000)), ("a Slicer pad", (96000,) * 3),
                                     ("Clip / Slicer mode off", (96000,) * 3), ("Sync Slice with slice markers", (96000,) * 3),
                                     ("Sync Slice, no markers", (48000, 48000, 1)))), rows)
# site 3 (0x08064c5a, the recompute's second length, r3 = the clip in output samples): a synced clip of one step has
# that step timed by the clip (+0x204), where stock times it by the length; nothing else changes it
def site3(n=1, synced=1, clip=24000, region=True):
    keep, kb = bytes(u.uc.mem_read(UL, 0xC00)), bytes(u.uc.mem_read(BANK + B_REGION + 8 * UQ, 8))
    u.uc.mem_write(UL + 0x1F5, bytes([synced]))
    u.w32(UL + 0x210, n)
    u.uc.mem_write(UL + 0x204, struct.pack("<f", 32000.0))
    u.uc.mem_write(UL + 0x260, b"\x01")
    if not region:
        u.w32(BANK + B_REGION + 8 * UQ + 4, 0)
    u.call("clipwin_len", USRC, UL, 3, clip)
    got = (u.uc.reg_read(UC_ARM_REG_R0), struct.unpack("<f", bytes(u.uc.mem_read(UL + 0x204, 4)))[0])
    u.uc.mem_write(UL, keep)
    u.uc.mem_write(BANK + B_REGION + 8 * UQ, kb)
    return got


rows = {what: site3(**kw) for what, kw in (("one step, synced", {}), ("two steps", dict(n=2)), ("Sync None", dict(synced=0)),
                                           ("a clip of 0 ticks", dict(clip=0)), ("no region", dict(region=False)))}
check(f"site 3: the region's length; a synced clip of one step gets +0x204 = the clip in output samples (24 000), not the "
      f"region's 32 000 - not with two steps, Sync None, a clip of 0 ticks or no region ({rows})",
      rows == {"one step, synced": (48000, 24000.0), "two steps": (48000, 32000.0), "Sync None": (48000, 32000.0),
               "a clip of 0 ticks": (48000, 32000.0), "no region": (96000, 32000.0)}, rows)
# when it is taken: a stopped pad at any recompute; a playing one only at its wrap's
h_loop(0, 32000, 1)
playing = (ulen_call(1, 1), region_bank(u, UQ))
for L in (1, 2):
    u.uc.mem_write(UL + 0x260, bytes(0x420))
    u.uc.mem_write(UL + 0x260 + (L - 1) * 0x410, b"\x01")
    playing += (len_at(1), region_bank(u, UQ))
u.uc.mem_write(UL + 0x260, bytes(0x420))
u.uc.mem_write(BANK + B_WRAP, bytes([UQ + 2]))               # another pad's wrap
u.uc.mem_write(UL + 0x260, b"\x01")
other = (len_at(1), region_bank(u, UQ))
u.uc.mem_write(BANK + B_WRAP, bytes([UQ + 1]))               # this pad's
wrapped = (len_at(1), region_bank(u, UQ))
u.uc.mem_write(BANK + B_WRAP, b"\x00")
stopped = (ulen_call(1, 0), region_bank(u, UQ))
h_loop(24000, 72000, 1)
ulen_call(1)
h_loop(0, 32000, 1)
others = (ulen_call(0, 1), ulen_call(2, 1), ulen_call(0, 0), region_bank(u, UQ))
check("taken at the recompute (site 1) only: while either layer plays, the region it plays is kept (new loop points wait), "
      f"another pad's wrap changes nothing, its own wrap takes them, and so does a stopped pad: {playing}, {other}, "
      f"{wrapped}, {stopped}; the other sites never take one: {others}",
      playing == (48000, (24000, 48000), 48000, (24000, 48000), 48000, (24000, 48000)) and other == (48000, (24000, 48000))
      and wrapped == (32000, (0, 32000)) and stopped == (32000, (0, 32000)) and others == (48000, 1, 48000, (24000, 48000)),
      (playing, other, wrapped, stopped, others))
rec = []
u.stub(RECOMPUTE, lambda: rec.append((u.arg(0), u.arg(1), u.r8(BANK + B_WRAP))))
u.call("clipwin_wrap", UL, 0x12345678, 0)
after = u.r8(BANK + B_WRAP)
u.w32(UL + 0x18, 0x401)
u.call("clipwin_wrap", UL, 0x12345678, 0)
u.w32(UL + 0x18, 0x102)
check(f"H3' (clipwin_wrap): the recompute with the caller's pad and clock, this pad marked as wrapping during it and only "
      f"then; cell 0x401 is no pad ({rec}, after {after})", rec == [(UL, 0x12345678, UQ + 1), (UL, 0x12345678, 0)] and after == 0, rec)
# ...and the wrap grid: the recompute stubbed as one that adopts (0, 32 000) when this pad wraps and leaves +0x230 =
# `grid`; t = the synced wrap's tick of the new pass (an i64 at the thunk's sp + 0x58), 0 for the unsynced wrap
TICK = 0x24063000


def wrap_grid(t, grid, new=(0, 32000), old=(24000, 48000)):
    rec.clear()
    u.uc.mem_write(BANK + B_REGION + 8 * UQ, struct.pack("<2i", *old))

    def fake():
        w_ = u.r8(BANK + B_WRAP)
        rec.append(w_)
        if w_ == UQ + 1 and new:
            u.uc.mem_write(BANK + B_REGION + 8 * UQ, struct.pack("<2i", *new))
        u.uc.mem_write(UL + 0x230, struct.pack("<q", grid))
    u.stub(RECOMPUTE, fake)
    if t is not None:
        u.uc.mem_write(TICK, struct.pack("<q", t))
    u.call("clipwin_wrap", UL, 0x12345678, TICK if t is not None else 0)
    return region_bank(u, UQ), tuple(rec)


rows = {what: wrap_grid(*a, **kw) for what, a, kw in (
    ("on the new grid", (3840 * 100, 3840), {}), ("off it", (3840 * 100 + 1920, 3840), {}),
    ("off it, region unchanged", (3840 * 100 + 1920, 3840), dict(new=None)),
    ("off it, only Loop Start moved", (3840 * 100 + 1920, 3840), dict(new=(0, 48000))),
    ("the unsynced wrap (no tick)", (None, 3840), {}), ("no grid (+0x230 = 0)", (3840 * 100 + 1920, 0), {}),
    ("a tick past 2^32", ((1 << 32) + 1920, 3840), {}))}
del u.stubs[RECOMPUTE]
check("H3' and the wrap grid: a new region whose pass would not start on its own wrap grid (+0x230 after the recompute) "
      "is put back and the recompute run again, as no wrap (the pass keeps the region it had); on the grid, without a tick "
      f"(unsynced), without a grid, with the region unchanged or a tick past 2^32, it is taken: {rows}",
      rows == {"on the new grid": ((0, 32000), (UQ + 1,)), "off it": ((24000, 48000), (UQ + 1, 0)),
               "off it, region unchanged": ((24000, 48000), (UQ + 1,)), "off it, only Loop Start moved": ((24000, 48000), (UQ + 1, 0)),
               "the unsynced wrap (no tick)": ((0, 32000), (UQ + 1,)), "no grid (+0x230 = 0)": ((0, 32000), (UQ + 1,)),
               "a tick past 2^32": ((0, 32000), (UQ + 1,))}, rows)
u.uc.mem_write(UL + 0x230, bytes(8))
# the source: the class-H object when the link holds, else the app's store (0x91, 0x92) with the last good pair; Loop
# Mode (0x8e) is not read (finding 7): the fourth pair, with Loop Mode None, is a region all the same
rows = []
for what, link in (("no class-H object (pad + 8 = 0)", 0), ("an object of another class", "class"), ("another cell's", "cell")):
    u.w32(UL + 8, UH if link else 0)
    if link == "class":
        u.uc.mem_write(UH + 4, b"\x43")
    if link == "cell":
        u.w32(UH + 0x18, 0x103)
    u.uc.mem_write(BANK + B_GOOD + 8 * UQ, bytes(8))
    seq = []
    for vals in ({0x8E: 1, 0x91: 10000, 0x92: 30000}, {0x8E: 1, 0x91: 40000, 0x92: 30000}, {0x8E: 1, 0x92: 30000},
                 {0x8E: 0, 0x91: 10000, 0x92: 30000}, {0x8E: 1, 0x91: 0, 0x92: 64000}):
        store(u, UQ, {**vals, 0x4: 500, P_REGION: AUTO})
        ulen_call(1)
        seq.append(region_bank(u, UQ))
    rows.append((what, seq))
    u.uc.mem_write(UH + 4, b"\x48")
    u.w32(UH + 0x18, 0x102)
u.w32(UL + 8, UH)
want = [(10000, 20000), (10000, 20000), (0, 30000), (10000, 20000), (0, 64000)]
check("no usable class-H link (none, another class, another cell): the loop from the app's store, through the settings "
      "lookup; a pair that makes no sense there (start after end; a start not stored yet, read 0) gives the last pair that "
      "did; Loop Mode None as on", all(seq == want for _, seq in rows),
      rows)
info("observed: a Loop Start the store does not hold yet reads 0 and makes a pair with Loop End: [0, 30 000) until it "
     "arrives (the fallback only; the class-H object has both from the same queue)")

# ---- the whole process
REG = (24000, 72000, 1)                                      # 2 beats of a 96 000-frame file, Loop Forward


def first_steps(r, k=6):
    return [(a, st_, fr) for a, st_, fr in starts(r)][:k]


def wraps_at(r, after=0):
    return [a for a, st_, _ in starts(r) if st_ == 0 and a > after]


def region_shift(ref, cw, rs, vlen, sf, wraps, guard=300, edge=0):
    """samples where one segment sounds in both runs, away from the wraps: max |cw frame - (rs + (ref frame + sf) mod
    vlen)| (circular), the count off by more than 0.05, and of samples whose summed gain differs. `edge` leaves out the
    samples within that many frames of either end, of the reference file or of the region (the kernel's support: stock
    interpolates into the silence after its file, the region into its own start, and a frame decoded from a ramp
    interpolated across the seam is a blend of both ends)"""
    lo, w = window(ref, cw)
    fs, fc = w["frame"]
    gs, gc = w["gain"]
    at = lo + np.arange(len(fs))
    away = np.ones(len(fs), bool)
    for x in wraps:
        away &= np.abs(at - x) > guard
    want = np.mod(fs + sf, vlen)
    if edge:
        for x in (np.nan_to_num(fs, nan=vlen / 2), np.nan_to_num(want, nan=vlen / 2)):
            away &= (x >= edge) & (x <= vlen - 1 - edge)
    ok = ~np.isnan(fs) & ~np.isnan(fc) & away
    want = rs + want
    err = np.abs(fc - want)
    err = np.minimum(err, vlen - err)[ok]
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > 0.05).sum()), int(((np.abs(gs - gc) > 1e-6) & away).sum())


def inside(d, rs, vlen, start, stop=None):
    """from sample `start` on: frames played by one segment outside [rs, rs + vlen), zero-gain samples, the peak gain"""
    a, b_ = start - d["base"], (stop - d["base"]) if stop else len(d["gain"]) - N
    f, g = d["frame"][a:b_], d["gain"][a:b_]
    out = ~np.isnan(f) & ((f < rs - 0.02) | (f > rs + vlen - 1 + 0.02))
    return int(out.sum()), int((np.abs(g) < 1e-7).sum()), float(g.max())


FIELDS = ((0x1FC, "<f"), (0x204, "<f"), (0x208, "<q"), (0x210, "<I"), (0x230, "<q"), (0x23C, "<I"), (0x258, "<f"), (0xBA8, "<q"))


def fields(r):
    return [struct.unpack(f_, bytes(r.uc.mem_read(r.pad + o, struct.calcsize(f_))))[0] for o, f_ in FIELDS]


# Region Loop plays only [ls, le), Slip on top; Beat Count Auto from the region's length. Reference: the stock image
# playing a 48 000-frame file - the region alone - with the same settings.
ref = audio(frames=48000, beats=0, image=STOCK, cell=0x102)
ref_r = ref["rig"]
for slip in (0, 480, -30, 7):
    cw = audio(frames=96000, beats=0, slip=slip, points=REG, cell=0x102)
    r = cw["rig"]
    sf = slip_f(slip, 48000, 1920)
    w_ = wraps_at(r, 288000)
    n, err, bad_, gd = region_shift(ref, cw, 24000, 48000, sf, w_)
    out, zeros, peak = inside(cw, 24000, 48000, 288000 + 300)
    lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
    h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
    pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
    check(f"Region Auto, Loop Forward [24 000, 72 000) of 96 000, Slip {slip} (slip_f {sf} over the region): away from the "
          f"wraps ({w_[:3]}...) every sounding sample plays 24 000 + (stock's frame of the region alone + slip_f) mod 48 000 "
          f"({n} samples, max error {err:.4f} frame), summed gain = stock's",
          n > 60000 and err <= 0.02 and bad_ == 0 and gd == 0 and len(w_) >= 2, (n, err, bad_, gd, w_))
    check(f"  nothing outside the region from the launch on ({out} samples), no zero-gain sample ({zeros}; stock's wraps "
          f"have a notch), peak gain {peak:.3f}; latched {lat[:1]} every segment, prefetched at 24 000 + the mapped start - 8"
          + (f"; {len(r.hints)} seam hint(s) at rs" if slip else ""),
          out == 0 and zeros == 0 and peak <= 1.0 + 1e-6 and lat and all(x == (24000, 48000, sf) for x in lat)
          and pf == [max(0, 24000 + (m_["start"] + sf) % 48000 - 8) for m_ in h1]
          and all(p == 24000 for _, p, _ in r.hints) and (not slip or r.hints), (out, zeros, peak, lat, pf[:4], r.hints[:3]))
    if slip == 0:
        check("  Beat Count Auto counts the region: frames per step, output samples per step, ticks per step, steps, wrap "
              f"grid, length, file tempo and the clip ticks told the app equal stock's for the 48 000-frame file ({fields(r)})",
              fields(r) == fields(ref_r) and fields(r)[2] * fields(r)[3] == 1920
              and [p[1:] for p in r.posted if p[1] == 0x8D][-1:] == [p[1:] for p in ref_r.posted if p[1] == 0x8D][-1:],
              (fields(r), fields(ref_r), [p for p in r.posted if p[1] == 0x8D], [p for p in ref_r.posted if p[1] == 0x8D]))

# Beat Count Auto over other region lengths: the recompute's fields are stock's for a file of the region's length
rows = []
for ls, le in ((0, 36000), (10000, 50000), (5000, 61000), (12345, 90000), (0, 95998)):
    a = scenario(frames=96000, beats=0, points=(ls, le, 1), cell=0x102, blocks=8)
    b = scenario(frames=le - ls, beats=0, image=STOCK, cell=0x102, blocks=8)
    rows.append((le - ls, fields(a)[2] * fields(a)[3], fields(a) == fields(b)))
check(f"Beat Count Auto with regions of 36 000, 40 000, 56 000, 77 655 and 95 998 frames: every recompute field as stock's for "
      f"that file ({[(v, c) for v, c, _ in rows]} (frames, clip ticks))", all(x for _, _, x in rows), rows)

# Auto keeps a freshly loaded pad on File (its loop points the whole file, whatever Loop Mode), and File is v1 bit for bit
for name, kw in (("Auto, [0, len) Loop Forward (what a load leaves)", dict(points=(0, 88615, 1))),
                 ("Auto, [0, len) Loop Mode None", dict(points=(0, 88615, 0))),
                 ("File, a Loop Forward loop [24 000, 72 000)", dict(points=REG, region=FILE))):
    for slip in (0, 960):
        a = scenario(frames=88615, slip=slip, cell=0x102, blocks=900, **kw)
        b = scenario(frames=88615, slip=slip, cell=0x102, blocks=900, points=(0, 0, 0))
        c = scenario(frames=88615, slip=slip, cell=0x102, blocks=900, region_off=True, **kw)
        ok1, d1 = same(a, b)
        ok2, d2 = same(a, c)
        check(f"{name}, Slip {slip}, 88 615 frames: every read, fetch, prefetch, output sample and message as with no loop "
              "(Loop Start, Loop End, Loop Mode all 0), and as with Region's hooks taken out (v1)", ok1 and ok2 and region_bank(a.m, 6)[1] == 0, (d1, d2))
a = scenario(frames=96000, cell=0x102, blocks=900, points=REG, region=FILE)
b = scenario(frames=96000, cell=0x102, blocks=900, points=REG, image=STOCK)
ok, d = same(a, b)
check("File with a loop, Slip 0: as the stock 3.1.9 image, bit for bit", ok, d)
a = audio(frames=96000, beats=0, points=(24000, 72000, 0), region=LOOP, cell=0x102)
n, err, bad_, gd = region_shift(ref, a, 24000, 48000, 0, wraps_at(a["rig"], 288000))
check(f"Loop with Loop Mode None: the region all the same ({n} samples as the region alone, max error {err:.4f})",
      n > 60000 and err <= 0.02 and bad_ == 0 and gd == 0, (n, err, bad_, gd))
# Gate 3 finding 7: a take whose loop points were moved on the Clip-mode Waveform has Sample mode's Loop Mode None (a row a
# Clip pad never shows), and Auto stayed on File. Auto plays them now, as Loop does
a = audio(frames=96000, beats=0, points=(24000, 72000, 0), region=AUTO, cell=0x102)
n, err, bad_, gd = region_shift(ref, a, 24000, 48000, 0, wraps_at(a["rig"], 288000))
check(f"Auto with Loop Mode None (finding 7): the region, as Loop plays it ({n} samples as the region alone, max error "
      f"{err:.4f}; region {region_bank(a['rig'].m, 6)})", n > 60000 and err <= 0.02 and bad_ == 0 and gd == 0
      and region_bank(a["rig"].m, 6) == (24000, 48000), (n, err, bad_, gd, region_bank(a["rig"].m, 6)))

# the seamless wrap, proven: regions shorter and longer than their (Auto) beats, against stock playing them as files
for ls, le, what in ((10000, 50000, "40 000 frames (1.67 beats, Auto 2: short, stock leaves a gap before each wrap)"),
                     (0, 56000, "56 000 frames (2.33 beats, Auto 2: long, stock's last step overlaps the next pass)"),
                     (24000, 72000, "48 000 frames (2 beats: stock's V-notch at the wrap)")):
    vlen = le - ls
    st_ = audio(frames=vlen, beats=0, image=STOCK, cell=0x102)
    cw = audio(frames=96000, beats=0, points=(ls, le, 1), cell=0x102)
    _, z0, p0 = inside(st_, 0, vlen, 288000 + 300)
    out, z1, p1 = inside(cw, ls, vlen, 288000 + 300)
    n, err, bad_, gd = region_shift(st_, cw, ls, vlen, 0, wraps_at(cw["rig"], 288000), guard=4400)
    wr = wraps(dict(frame=cw["frame"] - ls, sid=cw["sid"]), vlen)
    check(f"seamless, {what}: stock {z0} zero-gain samples and peak {p0:.3f}; the region {z1} and peak {p1:.3f}, nothing "
          f"outside it, the last step running on round the region's end ({wr} time(s) in one segment) into the next pass; "
          f"the steps away from the wraps as stock's ({n} samples)",
          z1 == 0 and p1 <= 1.0 + 1e-6 and out == 0 and (z0 > 0 or p0 > 1.0 + 1e-6) and n > 20000 and err <= 0.02
          and bad_ == 0, (z0, p0, z1, p1, out, wr, n, err, bad_))
for name, kw in (("Launch Trigger (a one-shot)", dict(launch=0)), ("Loop Off", dict(loop=0))):
    st_ = audio(frames=48000, beats=0, image=STOCK, cell=0x102, **kw)
    cw = audio(frames=96000, beats=0, points=REG, cell=0x102, **kw)
    n, err, bad_, gd = region_shift(st_, cw, 24000, 48000, 0, [])
    out, _, _ = inside(cw, 24000, 48000, 288000)
    last, last_st = np.nanmax(cw["frame"]), np.nanmax(st_["frame"])
    check(f"{name}: no seamless end - the pass plays the region once and stops on its end (last frame sounding {last:.0f}, "
          f"stock {last_st:.0f} of its 48 000), every sample and gain as stock's playing the region alone ({n} samples)",
          n > 40000 and err <= 0.02 and bad_ == 0 and gd == 0 and out == 0 and abs(last - last_st - 24000) < 0.02
          and last_st > 47990, (n, err, bad_, gd, out, last, last_st))

# a clip of one Sync step (Sync >= the clip, n = 1): stock times that step by the length (+0x204), so a file longer than
# its beats doubles at every wrap and a shorter one leaves a gap; the region's step is timed by the clip (H3 site 3)
for ls, le, what in ((24000, 56000, "32 000 frames (1.33 beats, Auto 1: long)"), (24000, 44000, "20 000 frames (0.83 beat, Auto 1: short)")):
    vlen = le - ls
    st_ = audio(frames=vlen, beats=0, image=STOCK, cell=0x102)
    cw = audio(frames=96000, beats=0, points=(ls, le, 1), cell=0x102)
    r = cw["rig"]
    _, z0, p0 = inside(st_, 0, vlen, 288000 + 300)
    out, z1, p1 = inside(cw, ls, vlen, 288000 + 300)
    w_ = wraps_at(r, 0)
    f_, fs_ = fields(r), fields(st_["rig"])
    n, err, bad_, gd = region_shift(st_, cw, ls, vlen, 0, w_)
    check(f"one step, {what}, Sync 1/4: ticks per step {f_[2]}, {f_[3]} step, +0x204 {f_[1]:.0f} (the clip; stock "
          f"{fs_[1]:.0f}, the length); stock {z0} zero-gain samples and peak {p0:.3f}, the region {z1} and peak {p1:.3f}, "
          f"nothing outside it, a pass every beat ({w_[:4]}), what both play alone as stock's ({n} samples)",
          f_[2:4] == [960, 1] and f_[1] == 24000.0 and fs_[1] == vlen and z1 == 0 and p1 <= 1.0 + 1e-6 and out == 0
          and (z0 > 0 or p0 > 1.0 + 1e-6) and w_[:4] == [288000, 312000, 336000, 360000] and n > 10000 and err <= 0.02 and bad_ == 0,
          (f_, fs_, z0, p0, z1, p1, out, w_[:4], n, err, bad_))

# a region under half a beat on Beat Count Auto is a clip of 0 ticks (stock rounds a file that short to 0 beats too):
# no clip to turn Slip into frames (slip_f 0), but every segment still reads the region, not the file's first frames
for launch, name in ((2, "Toggle"), (0, "Trigger")):
    st_ = audio(frames=9000, beats=0, sync=5, launch=launch, image=STOCK, cell=0x102, blocks=400)
    cw = audio(frames=96000, beats=0, sync=5, launch=launch, points=(30000, 39000, 1), slip=480, cell=0x102, blocks=400)
    r = cw["rig"]
    out, z, pk = inside(cw, 30000, 9000, 288000 + 300)
    _, zs, pks = inside(st_, 0, 9000, 288000 + 300)
    lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
    h1 = [m_ for m_ in r.made if m_["how"] == "H1"]
    pf = [r.prefetches[m_["prefetch_at"]][1] for m_ in h1]
    s_ = starts(r)
    fr = cw["frame"]
    lo_, hi_ = float(np.nanmin(fr)), float(np.nanmax(fr))
    ok = (fields(r)[2] == 0 and out == 0 and lo_ >= 30000 - 0.02 and hi_ <= 38999 + 0.02 and lat and all(x == (30000, 9000, 0) for x in lat)
          and pf == [max(0, 30000 + m_["start"] % 9000 - 8) for m_ in h1] and all(st == 0 and fr_ == 0 for _, st, fr_ in s_))
    if launch == 0:
        n, err, bad_, gd = region_shift(st_, cw, 30000, 9000, 0, [])
        check(f"a region of 9 000 frames (3/8 beat), Beat Count Auto, Sync 1/16, Slip 480, {name}: 0 ticks per step, every "
              f"segment latched (30 000, 9 000, slip_f 0), frames {lo_:.0f} .. {hi_:.0f}, nothing outside the region; one pass, "
              f"every sample and gain as stock's playing the 9 000 frames alone ({n} samples)",
              ok and len(s_) == 1 and n > 8000 and err <= 0.02 and bad_ == 0 and gd == 0, (lat, out, lo_, hi_, s_, n, err, bad_, gd))
    else:
        per = sorted({b_[0] - a_[0] for a_, b_ in zip(s_, s_[1:])})
        check(f"  ...{name}: the same, a pass every {per} samples (no grid: on its own length, as stock's 9 000-frame file "
              f"every {sorted({b_[0] - a_[0] for a_, b_ in zip(starts(st_['rig']), starts(st_['rig'])[1:])})}), "
              f"{z} zero-gain samples, peak {pk:.3f} (stock {pks:.3f}: a 0-beat clip restarts early, README Known issues)",
              ok and len(s_) >= 4 and per == [8875] and z == 0 and pk < 2.0, (lat, out, lo_, hi_, s_[:5], per, z, pk))

# a region change while the pad plays: heard at the next wrap, no added silence
for name, change in (("new loop points (Loop End 96 000 -> 48 000, Region Auto)", lambda rr: rr.param(0x92, 48000)),
                     ("Region File -> Auto over a loop it already had", lambda rr: store(rr.m, 6, {0x4: 500, P_REGION: AUTO}))):
    first = (0, 96000, 1) if "points" in name else (0, 48000, 1)
    reg0 = None if "points" in name else FILE
    kw = dict(frames=96000, beats=0, cell=0x102, points=first, region=reg0, blocks=1500)
    ref_ = audio(**kw)
    cw = audio(pre=lambda rr: change(rr) if rr.block == 265 else None, **kw)
    r, rr_ = cw["rig"], ref_["rig"]
    W = 288000 + 96000                                        # the first wrap after the change
    up_to = (W - 287000) // N - 1
    same_before = all(np.array_equal(x, y) for x, y in zip(rr_.out[:up_to], r.out[:up_to]))
    s_ = [(a, st_, fr) for a, st_, fr in starts(r) if a >= W][:5]
    out, _, peak = inside(cw, 0, 48000, W + 300)
    zr = set(np.where(np.abs(ref_["gain"]) < 1e-7)[0] + ref_["base"])
    zc = set(np.where(np.abs(cw["gain"]) < 1e-7)[0] + cw["base"])
    lim = cw["base"] + len(cw["gain"]) - N
    added = sorted(x for x in zc - zr if 321000 <= x < lim)
    check(f"live, {name}, inside step 1 of the first pass: every output sample identical to no change up to the wrap at "
          f"{W}; from it the new region (steps {s_}), nothing outside [0, 48 000), no zero-gain sample that the run without "
          f"the change does not have ({len(added)} added; it keeps stock's notch at {W} - that pass's last step was made "
          "before the change was taken)", same_before and s_[:3] == [(W, 0, 0), (W + 24000, 1, 24000), (W + 48000, 0, 0)]
          and out == 0 and not added and peak <= 1.0 + 1e-6, (same_before, s_, out, added[:5], peak))

# region -> region while it plays, Slip 480 (slip_f 12 000 over either): [24 000, 72 000) -> [6 000, 54 000), both 2 beats.
# Changed inside step 0 it is heard at the next wrap; inside the pass's last Sync step, at the one after: the next
# pass's step 0 is made, and the wrap's recompute run, when the last step starts sounding (README)
kw = dict(frames=96000, beats=0, cell=0x102, points=REG, blocks=1300, slip=480)
ref_ = audio(**kw)
zr = set(np.where(np.abs(ref_["gain"]) < 1e-7)[0] + ref_["base"])
for blk, W, when in ((100, 336000, "inside step 0"), (265, 384000, "inside step 1, the last Sync step")):
    cw = audio(pre=lambda rr, blk=blk: (rr.param(0x91, 6000), rr.param(0x92, 54000)) if rr.block == blk else None, **kw)
    r = cw["rig"]
    up_to = (W - 287000) // N - 1
    same_before = all(np.array_equal(x, y) for x, y in zip(ref_["rig"].out[:up_to], r.out[:up_to]))
    out, z, pk = inside(cw, 6000, 48000, W + 300)
    zc = set(np.where(np.abs(cw["gain"]) < 1e-7)[0] + cw["base"])
    added = sorted(x for x in zc - zr if 290000 <= x < cw["base"] + len(cw["gain"]) - N)
    lat = [latch(r.m, 6, k) for k in range(4) if bank_valid(r.m, 6) >> k & 1]
    s_ = [x for x in starts(r) if x[0] >= W][:3]
    check(f"live, region -> region, Slip 480, {when} (sample {287000 + blk * N}): every output sample as without the "
          f"change up to the wrap at {W}, from it the new region (steps {s_}; latched {lat[:1]}), nothing outside "
          f"[6 000, 54 000), no zero-gain sample added ({len(added)}), peak {pk:.3f}",
          same_before and s_ == [(W, 0, 0), (W + 24000, 1, 24000), (W + 48000, 0, 0)] and out == 0 and not added
          and pk <= 1.0 + 1e-6 and lat and all(x == (6000, 48000, 12000) for x in lat), (same_before, s_, out, added[:5], pk, lat))

# a change that makes the clip longer moves stock's wrap grid (+0x230 = min(Quant, clip)): a pass that does not start on
# it has its end snapped back into the past. Stock does that on a live Beat Count change (2 -> 4 beats, Quant 1 bar):
# two passes start at once over the last step (gain 2), then the bar. The region waits for a wrap on its grid (H3').
st_ = audio(frames=96000, beats=2, image=STOCK, cell=0x102, blocks=2400, pre=lambda rr: rr.param(0xD2, 4) if rr.block == 100 else None)
cw = audio(frames=192000, beats=0, points=REG, cell=0x102, blocks=2400, pre=lambda rr: rr.param(0x92, 120000) if rr.block == 100 else None)
ws, wc = wraps_at(st_["rig"], 0), wraps_at(cw["rig"], 0)
gs, gc = st_["gain"][:len(st_["gain"]) - N], cw["gain"][:len(cw["gain"]) - N]
out, z, pk = inside(cw, 24000, 96000, 384000 + 300)
check(f"live, 2 beats -> 4 inside step 0 (Loop End 72 000 -> 120 000, mid-bar wrap at 336 000): stock's Beat Count change "
      f"starts passes at {ws[:5]} ({int((gs > 1 + 1e-6).sum())} samples above gain 1, peak {gs.max():.2f}); the region keeps "
      f"its 2 beats to the bar and plays the 4 from it: {wc[:5]}, {int((gc > 1 + 1e-6).sum())} samples above 1, "
      f"{z} zero-gain, nothing outside [24 000, 120 000)",
      ws[2] < 480000 - 48000 and gs.max() > 1.9 and wc[:5] == [288000, 336000, 384000, 480000, 576000] and not (gc > 1 + 1e-6).any()
      and z == 0 and out == 0, (ws[:6], wc[:6], gs.max(), gc.max(), z, out))

# region -> File while it plays (Region Auto -> File), inside step 0: the file's 4 beats wait for the bar, from which it
# plays as the stock image plays the file (the region's last step, seamless, crossfades into it: no notch there)
kw = dict(frames=96000, beats=0, cell=0x102, points=REG, blocks=1700, region=AUTO)
ref_ = audio(**kw)
st_ = audio(frames=96000, beats=0, image=STOCK, cell=0x102, blocks=1700)
cw = audio(pre=lambda rr: store(rr.m, 6, {0x4: 500, P_REGION: FILE}) if rr.block == 100 else None, **kw)
r = cw["rig"]
up_to = (384000 - 287000) // N - 1
same_before = all(np.array_equal(x, y) for x, y in zip(ref_["rig"].out[:up_to], r.out[:up_to]))
s_ = [x for x in starts(r) if x[0] >= 336000][:7]
lo, w = window(st_, cw)
at = lo + np.arange(len(w["frame"][0]))
keep = at >= 384000 + 300
fs, fc = w["frame"][0][keep], w["frame"][1][keep]
both = ~np.isnan(fs) & ~np.isnan(fc)
gdiff = int((np.abs(w["gain"][0][keep] - w["gain"][1][keep]) > 1e-6).sum())
zc = sorted(x for x in np.where(np.abs(cw["gain"][:len(cw["gain"]) - N]) < 1e-7)[0] + cw["base"] if x > 290000)
zs = sorted(x for x in np.where(np.abs(st_["gain"][:len(st_["gain"]) - N]) < 1e-7)[0] + st_["base"] if x > 290000)
check(f"live, region -> File inside step 0: as without the change up to the bar at 384 000 (the region at 336 000 too), "
      f"then the file's 4 beats ({s_}); from there every sample and gain as the stock image's ({int(both.sum())} samples, "
      f"{gdiff} gains differ); zero-gain samples {zc} (stock {zs}: its notch at 384 000 is the region's crossfade here), "
      f"no latch, peak {cw['gain'].max():.3f}",
      same_before and s_ == [(336000, 0, 0), (360000, 1, 24000), (384000, 0, 0), (408000, 1, 24000), (432000, 2, 48000),
                             (456000, 3, 72000), (480000, 0, 0)] and both.sum() > 90000 and np.abs(fs[both] - fc[both]).max() <= 0.02
      and gdiff == 0 and zc == [x for x in zs if x > 384000 + 300] and zs and bank_valid(r.m, 6) == 0 and cw["gain"].max() <= 1.0 + 1e-6,
      (same_before, s_, int(both.sum()), gdiff, zc, zs))

# unsynced: Sync None, the restart takes it
cw = audio(frames=96000, beats=0, sync=6, cell=0x102, points=(0, 96000, 1), blocks=2000,
           pre=lambda rr: rr.param(0x92, 48000) if rr.block == 300 else None)
r = cw["rig"]
s_ = starts(r)
after = [(a, fr) for a, st_, fr in s_ if a > 288000 + 38400]
out, zeros, peak = inside(cw, 0, 48000, after[1][0] + 300 if len(after) > 1 else 0)
check(f"live, Sync None (the unsynced wrap, 0x08066e9e): the restart made after the change plays [0, 48 000) and the "
      f"next comes 48 000 samples on (seamless: no end, so not stock's len - 257) ({[a for a, _ in after[:4]]}); nothing "
      f"outside it from there, {zeros} zero-gain samples, peak {peak:.3f}",
      len(after) >= 3 and after[0][0] == 288000 + 96000 - 257 and after[1][0] - after[0][0] == 96000 - 257
      and after[2][0] - after[1][0] == 48000 and out == 0 and zeros == 0 and peak <= 1.0 + 1e-6, (s_[:5], out, zeros, peak))

# rate != 1 and stereo: a 44.1 kHz stereo file, the region one second of it (2 beats)
st_ = [scenario(dc=dc, frames=44100, src_rate=44100, stereo=True, beats=0, image=STOCK, cell=0x102) for dc in (True, False)]
cw_ = [scenario(dc=dc, frames=88200, src_rate=44100, stereo=True, beats=0, points=(22050, 66150, 1), slip=480, cell=0x102)
       for dc in (True, False)]
for ch in (0, 1):
    a, b = decode(*st_, ch), decode(*cw_, ch)
    sf = slip_f(480, 44100, 1920)
    w_ = wraps_at(cw_[1], 288000)
    n, err, bad_, gd = region_shift(a, b, 22050, 44100, sf, w_, edge=3)
    check(f"44.1 kHz stereo ({'right' if ch else 'left'}), region [22 050, 66 150) of 88 200, Slip 480: every sample away "
          f"from the wraps plays 22 050 + (stock's frame + slip_f) mod 44 100 ({n} samples, max {err:.4f}; the 3 frames at "
          "each end of stock's file aside), gain as stock's",
          n > 40000 and err <= 0.02 and bad_ == 0 and gd == 0, (n, err, bad_, gd))

# a new file under a pad playing a region (5b's chain, Beat Count Auto): the latch keeps the FILE's length, not the
# region's. The segments latched for the region read as stock reads, at their own positions in the new file; the next
# ones latch the new file: the region again when it fits there (a playing pad takes new loop points at its wrap), else
# the file. Slip on top, against the same run at Slip 0.
for length, slip in ((50000, 0), (50000, 960), (192000, 960)):
    sc = dict(frames=96000, beats=0, cell=0x102, blocks=900, points=REG, pre=new_file(length))
    rr = scenario(slip=slip, **sc)
    cw = decode(scenario(dc=True, slip=slip, **sc), rr)
    old = {m_["sid"] for m_ in rr.made if m_["block"] < SWAP}
    rows = [x for x in rr.reads if x[0] >= SWAP + CLOSED and x[SID] in old]
    moved = [x for x in rows if not x[FET] or x[FET][0][1] != x[POS]]
    past = [f for f in rr.fetches if f[0] >= SWAP + CLOSED and f[1] + f[2] > length + 0xFF]
    t = cw["base"] + np.arange(len(cw["gain"]))
    quiet = int(((t >= T_OPEN) & (np.abs(cw["gain"]) < 1e-7)).sum())
    rs, vlen = (24000, 48000) if length >= 72000 else (0, length)
    sf = slip_f(slip, vlen, 1920)
    held = [(latch(rr.m, 6, k), made_for(rr.m, 6, k)) for k in range(4) if bank_valid(rr.m, 6) >> k & 1]
    fresh = [m_ for m_ in rr.made if m_["block"] > SWAP + CLOSED + 1]
    t_new = min((x[AT] for x in rr.reads if fresh and x[SID] == fresh[0]["sid"]), default=-1)
    want_held = [((rs, vlen, sf), length)] * len(held) if (slip or rs) else []
    check(f"Region Loop [24 000, 72 000) of 96 000, Slip {slip}, a {length}-frame file under the playing pad from {T_SWAP}: "
          f"the segments latched for the region (made for 96 000) read as stock reads from the file opening on, at their "
          f"own positions in the new file ({len(rows)} reads, {len(moved)} mapped), nothing fetched past the new end + 0xff, "
          f"no silent sample ({quiet}); the segments made since latch {want_held[:1] or 'nothing (File, Slip 0: stock)'}"
          + (" (the region fits the new file)" if rs else " (the region does not fit: the file)"),
          len(rows) > 200 and not moved and not past and quiet == 0 and held == want_held and t_new == 360000,
          (len(rows), moved[:2], past[:2], quiet, held, t_new))
    if slip:
        ref0 = decode(scenario(dc=True, **sc), scenario(**sc))
        lo, w = window(ref0, cw)
        f0, fc = w["frame"]
        g0, gc = w["gain"]
        span = lo + np.arange(len(f0)) >= t_new + 256
        ok_ = ~np.isnan(f0) & ~np.isnan(fc) & span
        want = rs + np.mod(f0 - rs + sf, vlen)
        err = np.abs(fc - want)
        err = np.minimum(err, vlen - err)[ok_]
        gd = int(((np.abs(g0 - gc) > 1e-6) & span).sum())
        check(f"  from the end of the first new segment's crossfade ({t_new + 256}) every sounding sample plays "
              f"{rs} + (the Slip 0 run's frame - {rs} + {sf}) mod {vlen} ({int(ok_.sum())} samples, max "
              f"{float(err.max()) if len(err) else 9e9:.4f} frame), summed gain = the Slip 0 run's",
              ok_.sum() > 20000 and len(err) and err.max() <= 0.02 and gd == 0, (int(ok_.sum()), gd))

# gating: where a region does not apply, every hook passes through (as the hooks out), the loop points set
for name, kw in (("a Slicer pad (no markers)", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("a Clip pad, Sync = Slice, with markers (H1')", dict(sync=0, setup=slicer_setup(MK))),
                 ("no SDRAM block", dict(block=False)),
                 ("fw_src_len 0x10000000", dict(frames=0x10000000))):
    a = scenario(points=REG, region=LOOP, cell=0x102, blocks=500, **kw)
    b = scenario(points=REG, region=LOOP, cell=0x102, blocks=500, bypass=True, **kw)
    ok, d = same(a, b)
    check(f"Region Loop over [24 000, 72 000), {name}: plays as with the hooks out, no latch", ok and bank_valid(a.m, 6) == 0, d)
a = scenario(points=REG, region=LOOP, cell=0x102, blocks=400, frames=0)
b = scenario(points=REG, region=LOOP, cell=0x102, blocks=400, frames=0, bypass=True)
ok, d = same(a, b, True)
check(f"Region Loop, fw_src_len 0 (not open): nothing plays, as with the hooks out ({len(a.reads)} reads)", ok, d)
a = scenario(points=REG, region=LOOP, cell=0x401, blocks=400)
b = scenario(points=REG, region=LOOP, cell=0x401, blocks=400, bypass=True)
ok, d = same(a, b)
check("Region Loop on cell 0x401 (no pad): as with the hooks out, nothing in the bank",
      ok and not any(region_bank(a.m, q)[1] for q in range(16)), d)

# every write clipwin.c makes in a Region run lands in the bank
w = []
r = Rig(cell=0x102, h=True)
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u_, acc, addr, size_, v, d_: w.append((addr, size_)) if any(
    a_ <= u_.reg_read(UC_ARM_REG_PC) < b_ for a_, b_ in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
store(r.m, 6, {0x4: 500, P_SLIP: 7, P_REGION: AUTO})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), rr.param(0x92, 48000) if rr.block == 200 else None)
r.params(beats=0)
r.goto(287000 - N)
for pid, v in zip((0x91, 0x92, 0x8E), (24000, 72000, 1)):
    r.param(pid, v)
r.step_block()
r.goto(287000)
r.note_on()
r.run(700)
hit = {name: any(lo <= a_ - BANK < hi for a_, s_ in w) for name, lo, hi in (("wrap", B_WRAP, B_WRAP + 1), ("region", B_REGION, B_GOOD))}
check(f"in a Region run, every write clipwin.c makes into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (wrap and "
      f"region written: {hit})", w and all(hit.values()) and all(BANK <= a_ and a_ + s_ <= BANK + B_SIZE for a_, s_ in w)
      and region_bank(r.m, 6) == (24000, 24000), (sorted({hex(a_) for a_, s_ in w if not BANK <= a_ < BANK + B_SIZE})[:4], region_bank(r.m, 6)))

# ====================================================================================================== 11. Loop Len
# Loop Len (README section 3, notes/re/a2 k_looplen; D-004): only a window of W ticks loops, on the clock, where the music
# was when it was engaged. Each segment H1 makes plays the window's step that lines up with its own, w = (origin + ((j x
# tps - origin) mod W)) / tps, from (int)((float)w x fps) (+ slip_f): stock's own product. origin = the phase of the
# sounding segment that started last, rounded down to W. A W the steps do not divide forces the pad's Sync through the
# class-B param-set (0x94), given back on Off as the app's store has it; never while a launch waits for its bar.
# Reference: the research model's numbers (a2/r2/k_looplen.out: L1 origin 7 680, steps 3 and 0 replaying 192 000; L2
# origin 1 200, Sync 1/16 forced, the next segment at 324 000 and every one after playing 30 000, Sync 1/4 back and step
# 2 at 432 000 playing 48 000; L3 every later step replaying 48 000; L4 the engage held until the launch sounded, the
# launch on its bar with +0x140 = 11 520), the same run with Loop Len never on (same gains, sample for sample, where the
# Sync is not forced), and the formula above, evaluated per segment from what H1 saw.
def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def fl(w, fps):
    """stock's first frame of step w: vcvt.f32.u32, vmul.f32 by +0x1fc, vcvt.s32.f32 (truncation)"""
    return int(f32(float(w) * fps))


def want_first(m_, sf=0, vlen=None):
    """the frame segment m_ starts on, from what H1 saw: its step, the pad's steps, the bank's Loop Len and origin"""
    j, tps, n, o = m_["step"], m_["tps"], m_["n"], m_["origin"]
    W = 240 << (m_["ll"] - 1) if m_["ll"] else 0
    w = (o + (j * tps - o) % W) // tps if W and W < tps * n and not W % tps and not o % tps else j
    f = fl(w, m_["fps"]) + sf
    return f % vlen if vlen else f


def ll_pre(events, slip=0, sync=3, region=None, then=None):
    """pre_block: the pad's store as the app keeps it (Sync, Slip, Loop Len) with Loop Len set at the blocks in
    `events` {block: value}; the bank's Loop Len state after each block's poll in rr.llog"""
    def pre(rr):
        if not hasattr(rr, "llog"):
            rr.llog = []
        q = rr.q
        rr.llog.append((rr.block, rr.m.r8(BANK + B_LL + q), rr.m.r32(BANK + B_ORIGIN + 4 * q), rr.m.r8(BANK + B_FORCED + q),
                        rr.i64(rr.pad + 0x220)))
        if rr.block in events:
            store(rr.m, q, {0x4: 500, P_SLIP: slip, P_SYNC: sync, P_LOOPLEN: events[rr.block],
                            **({} if region is None else {P_REGION: region})})
        if then:
            then(rr)
    return pre


def taken(r, ll):
    """the first block whose poll took Loop Len `ll`, and the state then (block, ll, origin, forced, Sync ticks)"""
    for i, x in enumerate(r.llog):
        if x[1] == ll and (i == 0 or r.llog[i - 1][1] != ll):
            return x
    return None


def seg_firsts(d, after=0, rate=1.0):
    """each segment that sounded alone somewhere, from sample `after`: (its first sample, step, the frame it started on,
    read back from the first sample it sounds alone, at `rate` source frames a sample)"""
    r = d["rig"]
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    out = []
    for m_ in r.made:
        s0 = first.get(m_["sid"])
        idx = np.where(d["sid"] == m_["sid"])[0]
        if s0 is None or not len(idx) or s0 < after:
            continue
        out.append((s0, m_["step"], int(round(d["frame"][idx[0]] - (d["base"] + idx[0] - s0) * rate))))
    return sorted(out)


def follows(d, sf=0, rs=0, vlen=None, after=0, rate=1.0, off=0.0, tol=0.02):
    """every sample where one segment sounds (from `after`): plays rs + (want_first(its segment) + the samples since it
    started x rate) mod vlen, read back `off` frames on (the reader's own at rate != 1). Returns (samples, max error,
    samples off by more than `tol` frame)"""
    r = d["rig"]
    vlen = vlen or r.len
    first = {}
    for x in r.reads:
        first.setdefault(x[SID], x[AT])
    by = {m_["sid"]: m_ for m_ in r.made}
    f, sid, base = d["frame"], d["sid"], d["base"]
    at = base + np.arange(len(f))
    ok = ~np.isnan(f) & (sid > 0) & (at >= after)
    want = np.full(len(f), np.nan)
    for s_ in set(sid[ok].tolist()):
        m_ = by.get(s_)
        if m_ is None or m_["how"] != "H1" or s_ not in first:
            ok &= sid != s_
            continue
        sel = ok & (sid == s_)
        want[sel] = rs + np.mod(want_first(m_, sf, vlen) + (at[sel] - first[s_]) * rate + off, vlen)
    err = np.abs(f - want)[ok]
    err = np.minimum(err, vlen - err)
    return int(ok.sum()), float(err.max()) if len(err) else 9e9, int((err > tol).sum())


def zeros_after(d, start):
    g = d["gain"][:len(d["gain"]) - N]
    return {int(x) + d["base"] for x in np.where(np.abs(g) < 1e-7)[0] if x + d["base"] >= start}


def same_gain(a, b, start):
    lo, w = window(a, b)
    at = lo + np.arange(len(w["gain"][0]))
    keep = at >= start
    return int((np.abs(w["gain"][0][keep] - w["gain"][1][keep]) > 1e-6).sum())


# L1: Quant 1 beat < Sync 1 bar, a 16-beat 384 000-frame clip launched on beat 2 (tick 8 640): stock's phase is its step
# index, not ticks - launch. Engaged 1 bar inside step 2 (sounding frame ~195 520, phase ~7 821), Off two bars on.
eng = (387520 - 200000) // N
kw = dict(frames=384000, beats=16, quant=5, sync=1, at=200000, blocks=3900, vals={P_SYNC: 1})
ref_ = audio(pre=ll_pre({}, sync=1), **kw)
cw = audio(pre=ll_pre({eng: 5, eng + 1500: 0}, sync=1), **kw)
r = cw["rig"]
on, off = taken(r, 5), taken(r, 0) if taken(r, 5) else None
off = next((x for x in r.llog if on and x[0] > on[0] and x[1] == 0), None)
sg = seg_firsts(cw, 300000)
n_, err, bad_ = follows(cw)
zc, zr = zeros_after(cw, 200000), zeros_after(ref_, 200000)
check(f"Loop Len 1 bar engaged inside step 2 of a 16-beat clip launched on beat 2 (Quant 1 beat < Sync 1 bar; taken at "
      f"block {on and on[0]}, sample {on and 200000 + on[0] * N}): origin {on and on[2]} (a2/r2 k_looplen L1: 7 680; ticks - "
      f"launch would give 3 840), Sync left alone; steps 3 and 0 replay the bar that was playing, from 192 000 ({sg[:4]})",
      on and on[2] == 7680 and on[3] == 0 and on[4] == 3840 and sg[:3] == [(384000, 2, 192000), (480000, 3, 192000), (576000, 0, 192000)],
      (on, sg[:4]))
check(f"  Off two bars on (block {off and off[0]}): step 1 at 672 000 plays its own 96 000 again, in phase, as without Loop "
      f"Len ({sg[3:4]}); every sample plays its segment's step of the window from its first frame ({n_} samples, max error "
      f"{err:.4f}); summed gain = the run without Loop Len at every sample ({same_gain(ref_, cw, 200000)} differ), no zero-gain "
      f"sample added ({len(zc - zr)})", off and sg[3:4] == [(672000, 1, 96000)] and n_ > 300000
      and err <= 0.02 and bad_ == 0 and same_gain(ref_, cw, 200000) == 0 and not zc - zr, (off, sg[3:6], n_, err, bad_))

# L2: the matched 4-beat clip, Sync 1/4, Loop Len 1/16 engaged inside step 1 (frame ~33 000): W < a Sync step, so the
# pad's Sync is forced to 1/16 and stock re-grids the playing segment; Off one bar on gives Sync 1/4 back.
kw = dict(frames=96000, at=193000, blocks=2600, vals={P_SYNC: 3})
ref_ = audio(pre=ll_pre({}), **kw)
cw = audio(pre=ll_pre({1000: 1, 1750: 0}), **kw)
r = cw["rig"]
on = taken(r, 1)
off = next((x for x in r.llog if on and x[0] > on[0] and x[1] == 0), None)
sg = seg_firsts(cw, 318000)
during = [x for x in sg if x[0] < 418000]
n_, err, bad_ = follows(cw)
zc, zr = zeros_after(cw, 288300), zeros_after(ref_, 288300)
check(f"Loop Len 1/16 engaged inside step 1 with Sync 1/4 (taken at sample {on and 193000 + on[0] * N}): origin {on and on[2]} "
      f"(L2: 1 200), Sync forced to 1/16 (+0x220 {on and on[4]}, forced {on and on[3]}); the playing segment re-gridded, the "
      f"next at 324 000 and every one after it, a 1/16 apart, replaying frame 30 000 ({during[:3]} ... {len(during)} segments)",
      on and on[2] == 1200 and on[3] == 1 and on[4] == 240 and during and during[0][0] == 324000
      and all(x[2] == 30000 for x in during) and [x[0] for x in during] == list(range(324000, 324000 + 6000 * len(during), 6000))
      and len(during) >= 15, (on, during[:4], len(during)))
after = [x for x in sg if x[0] >= 418000][:4]
st_ = audio(frames=96000, at=193000, blocks=2600, image=STOCK, pre=lambda rr: rr.param(P_SYNC, 5) if on and rr.block == on[0]
            else rr.param(P_SYNC, 3) if off and rr.block == off[0] else None)
same_starts = [x[:2] for x in starts(r)] == [x[:2] for x in starts(st_["rig"])]
check(f"  the timing is stock's own Sync change: every segment start and the summed gain at every sample as the stock image "
      f"sent Sync 1/16 and 1/4 in those two blocks ({same_starts}, {same_gain(st_, cw, 288300)} samples differ)",
      on and off and same_starts and same_gain(st_, cw, 288300) == 0, (starts(r)[:12], starts(st_["rig"])[:12]))
check(f"  Off one bar on (block {off and off[0]}): Sync 1/4 given back (+0x220 {off and off[4]}, forced {off and off[3]}), the "
      f"next segment step 2 on the beat at 432 000 playing 48 000, in phase ({after}); every sample plays its segment's "
      f"step of the window ({n_} samples, max error {err:.4f}); no zero-gain sample added ({sorted(zc - zr)[:4]}), peak "
      f"{cw['gain'].max():.3f}", off and off[3] == 0 and off[4] == 960 and after[:3] == [(432000, 2, 48000), (456000, 3, 72000),
                                                                                 (480000, 0, 0)]
      and n_ > 150000 and err <= 0.02 and bad_ == 0 and not zc - zr and cw["gain"].max() <= 1.0 + 1e-6, (off, after, n_, err, bad_, sorted(zc - zr)[:5]))

# L3: a launch 300 samples late (+0x140 = 11 532), Loop Len 1/4 inside step 2: a one-beat stutter of the beat that was
# playing - every later step replays 48 000, the summed gain stock's sample for sample
kw = dict(frames=96000, at=288300, blocks=1800, vals={P_SYNC: 3})
ref_ = audio(pre=ll_pre({}), **kw)
cw = audio(pre=ll_pre({400: 3}), **kw)
r = cw["rig"]
on = taken(r, 3)
sg = seg_firsts(cw, 336000)
n_, err, bad_ = follows(cw)
check(f"Loop Len 1/4 inside step 2 of a launch 300 samples late (+0x140 {r.layer()['launch_tick']}): origin {on and on[2]} "
      f"(L3: 1 920), Sync 1/4 left alone; every step from 360 000 replays the beat at 48 000 ({sg[:6]}), every sample its "
      f"segment's ({n_} samples, max error {err:.4f}); summed gain = the run without Loop Len ({same_gain(ref_, cw, 288300)} differ)",
      r.layer()["launch_tick"] == 11532 and on and on[2] == 1920 and on[3] == 0 and sg[0] == (336000, 2, 48000)
      and [x[2] for x in sg[1:7]] == [48000] * 6 and [x[0] for x in sg[:7]] == list(range(336000, 336000 + 7 * 24000, 24000))
      and n_ > 100000 and err <= 0.02 and bad_ == 0 and same_gain(ref_, cw, 288300) == 0, (on, sg[:8], n_, err, bad_))

# L4: Loop Len set while the launch waits for its bar (the note at 193 000, the bar at 288 000): nothing until the launch
# has sounded - it keeps its bar, +0x140 and msg 0x1d - then taken from where it plays (origin 0), Sync forced to 1/16
kw = dict(frames=96000, at=193000, blocks=1300, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({20: 1}), **kw)
r = cw["rig"]
on = taken(r, 1)
sg = seg_firsts(cw, 0)
n_, err, bad_ = follows(cw)
check(f"Loop Len 1/16 set while the launch waits for its bar: not taken while it waits (taken at sample "
      f"{on and 193000 + on[0] * N}, after the launch at {sg[0][0] if sg else None}); the launch on its bar with +0x140 "
      f"{r.layer()['launch_tick']} and msg 0x1d; then origin {on and on[2]}, Sync 1/16 forced, every later segment replaying "
      f"frame 0 ({sg[1:5]}; {n_} samples follow their segment, max error {err:.4f})",
      on and 193000 + on[0] * N > 288000 and sg[0] == (288000, 0, 0) and r.layer()["launch_tick"] == 11520
      and [b_ for b_, t_, _ in r.posted if t_ == 0x1D] and on[2] == 0 and on[3] == 1 and on[4] == 240
      and all(x[2] == 0 for x in sg[2:]) and len(sg) >= 10 and n_ > 60000 and err <= 0.02 and bad_ == 0, (on, sg[:5], n_, err, bad_))

# changing it live keeps the in-point: 1/4 engaged inside step 2 (in-point 1 920 = frame 48 000), then 1/8 (Sync forced to
# 1/8), then 1/2 (the user's 1/4 divides the window again: given back): the window starts at 48 000 throughout, its
# out-point moves
kw = dict(frames=96000, at=287000, blocks=2200, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({400: 3, 900: 2, 1400: 4}), **kw)
r = cw["rig"]
t1, t2, t3 = taken(r, 3), taken(r, 2), taken(r, 4)
sg = seg_firsts(cw, 340000)
n_, err, bad_ = follows(cw)
s8 = [x for x in sg if t2 and t3 and 287000 + t2[0] * N + 12000 <= x[0] < 287000 + t3[0] * N]
s2 = [x for x in sg if t3 and x[0] >= 287000 + t3[0] * N + 12000]
check(f"Loop Len changed live 1/4 -> 1/8 -> 1/2: the in-point stays (origin {t1 and t1[2]}, {t2 and t2[2]}, {t3 and t3[2]}); at "
      f"1/8 Sync is forced to 1/8 (+0x220 {t2 and t2[4]}) and every step replays 48 000 ({s8[:3]}...); at 1/2 the user's "
      f"Sync 1/4 is given back (+0x220 {t3 and t3[4]}, forced {t3 and t3[3]}) and the window [48 000, 96 000) plays in 1/4 "
      f"steps, on the clock ({[x[2] for x in s2[:8]]}); every sample its segment's ({n_}, max {err:.4f})",
      t1 and t2 and t3 and t1[2] == t2[2] == t3[2] == 1920 and t2[4] == 480 and t2[3] == 1 and t3[4] == 960 and t3[3] == 0
      and s8 and all(x[2] == 48000 for x in s8) and len(s2) >= 4 and [x[0] % 24000 for x in s2] == [0] * len(s2)
      and all(x[2] == 48000 + 24000 * ((x[0] // 24000) % 2) for x in s2) and n_ > 150000 and err <= 0.02 and bad_ == 0,
      (t1, t2, t3, s8[:4], s2[:8], n_, err, bad_))

# a fast file (88 615 frames, fps 22 153.75 at Sync 1/4): each step of the window starts on stock's own float product
kw = dict(frames=88615, at=287000, blocks=1900, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({600: 4}), **kw)
r = cw["rig"]
on = taken(r, 4)
sg = seg_firsts(cw, 287000 + 600 * N + 2048 + 24000)
n_, err, bad_ = follows(cw)
w_ = [44307 if (x[0] // 24000) % 2 == 0 else 66461 for x in sg]
check(f"Loop Len 1/2 on 88 615 frames (taken in step 3, origin {on and on[2]}): the steps alternate (int)(2 x 22 153.75) = "
      f"44 307 and (int)(3 x 22 153.75) = 66 461 ({[x[2] for x in sg[:6]]}); every sample its segment's ({n_}, max {err:.4f})",
      on and on[2] == 1920 and len(sg) >= 5 and [x[2] for x in sg] == w_ and n_ > 100000 and err <= 0.02 and bad_ == 0,
      (on, sg[:8], n_, err, bad_))

# stacked: Region [24 000, 72 000) (Beat Count Auto: 2 beats), Slip 480 (slip_f 12 000), Loop Len 1/4 inside step 1 -
# the window is the region's beat 2, shifted by Slip within the region: every step plays 24 000 + (24 000 + 12 000) mod
# 48 000 on; gains as the same run without Loop Len (the seamless wrap included)
kw = dict(frames=96000, beats=0, cell=0x102, points=REG, slip=480, blocks=1500, vals={P_SYNC: 3})
ref_ = audio(pre=ll_pre({}, slip=480), **kw)
cw = audio(pre=ll_pre({300: 3}, slip=480), **kw)
r = cw["rig"]
on = taken(r, 3)
sg = seg_firsts(cw, 287000 + 300 * N + 2048 + 24000)
n_, err, bad_ = follows(cw, sf=12000, rs=24000, vlen=48000)
out, z, pk = inside(cw, 24000, 48000, 288300)
check(f"Loop Len 1/4 on Region [24 000, 72 000) with Slip 480 (taken at origin {on and on[2]}): every later step starts on "
      f"60 000 ({[x[2] for x in sg[:5]]}), every sample 24 000 + (its step's frame + 12 000) mod 48 000 ({n_}, max {err:.4f}); "
      f"nothing outside the region, summed gain = without Loop Len ({same_gain(ref_, cw, 288300)} differ), {z} zero-gain samples",
      on and on[2] == 960 and len(sg) >= 5 and all(x[2] == 60000 for x in sg) and n_ > 80000 and err <= 0.02 and bad_ == 0
      and out == 0 and z == 0 and same_gain(ref_, cw, 288300) == 0, (on, sg[:6], n_, err, bad_, out, z))

# where Loop Len does nothing: Quant None (no grid); Sync None (no clock phase: a1; forcing a Sync there would make
# stock's None-to-synced re-grid double a whole step at gain 2); a window of the whole clip or more (2 bars on 4 beats);
# a Slicer pad; Sync = Slice with markers - every read, fetch, sample and message as the same run without it, the pad's Sync
# untouched (the poll still drops the pending step when it takes the value, and stock makes it again: one more prefetch;
# on Sync = Slice with markers every segment starts in H1', so the poll never has the pad and never takes it)
for name, kw in (("Quant None", dict(quant=8)), ("Sync None", dict(sync=6)), ("2 bars on a 4-beat clip", dict(ll=6)),
                 ("a Slicer pad", dict(setup=lambda r: (r.params(mode=2), None)[1])),
                 ("Sync = Slice with markers", dict(sync=0, setup=slicer_setup(MK)))):
    ll = kw.pop("ll", 1)
    sync = kw.get("sync", 3)
    a = scenario(frames=96000, at=287000, blocks=700, vals={P_SYNC: sync}, pre=ll_pre({100: ll}, sync=sync), **kw)
    b = scenario(frames=96000, at=287000, blocks=700, vals={P_SYNC: sync}, pre=ll_pre({}, sync=sync), **kw)
    ok, d = same(a, b)
    check(f"Loop Len {'1/16' if ll == 1 else '2 bars'}, {name}: every read, fetch, sample and message as without it "
          f"({len(a.prefetches) - len(b.prefetches)} prefetch(es) more: the pending step made again), the pad's Sync "
          f"untouched (forced {a.m.r8(BANK + B_FORCED + a.q)}), no latch", d["reads"] and d["fetches"] and d["out"]
          and d["posted"] and a.m.r8(BANK + B_FORCED + a.q) == 0 and a.i64(a.pad + 0x220) == b.i64(b.pad + 0x220)
          and (taken(a, ll) or "markers" in name) and bank_valid(a.m, a.q) == 0, d)

# the app re-sends Sync (a turn of the Sync knob) while Loop Len holds it forced: the next poll forces it again
kw = dict(frames=96000, at=287000, blocks=1000, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({200: 1}, then=lambda rr: rr.param(P_SYNC, 3) if rr.block == 600 else None), **kw)
r = cw["rig"]
back = [x for x in r.llog if x[0] > 600 and x[4] == 960]
again = next((x for x in r.llog if x[0] > 600 and x[4] == 240), None)
n_, err, bad_ = follows(cw)
check(f"Sync re-sent as 1/4 while Loop Len 1/16 holds it at 1/16: forced again by the next poll ({len(back)} blocks on 1/4, "
      f"then {again}), every sample its segment's ({n_}, max {err:.4f})",
      again and 0 < len(back) <= 16 and again[3] == 1 and n_ > 80000 and err <= 0.02 and bad_ == 0, (back[:2], again, n_, err))

# a stopped pad: Loop Len set after a Toggle stop is taken at once (no music: the in-point is the clip's start) and its
# Sync forced while it is quiet; the next launch, on its bar, plays the first 1/16 over and over
kw = dict(frames=96000, at=287000, blocks=1960, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({900: 1}, then=lambda rr: rr.note_on() if rr.block in (300, 1000) else None), **kw)
r = cw["rig"]
on = taken(r, 1)
sg = seg_firsts(cw, 400000)
n_, err, bad_ = follows(cw)
quiet = cw["gain"][(on[0] * N + 287000 - cw["base"]) if on else 0:(480000 - cw["base"])] if on else np.ones(1)
check(f"Loop Len 1/16 set on a pad stopped by Toggle (taken at sample {on and 287000 + on[0] * N}, the pad silent from "
      f"there to the relaunch: {not np.abs(quiet).max() > 1e-7}): origin {on and on[2]}, Sync forced at once (+0x220 "
      f"{on and on[4]}); the relaunch on the bar at 480 000 and every 1/16 after it replay frame 0 ({sg[:4]}), every sample "
      f"its segment's ({n_}, max {err:.4f})", on and on[2] == 0 and on[3] == 1 and on[4] == 240 and not np.abs(quiet).max() > 1e-7
      and sg and sg[0] == (480000, 0, 0) and len(sg) >= 8 and all(x[2] == 0 for x in sg)
      and [x[0] for x in sg[:8]] == list(range(480000, 528000, 6000)) and n_ > 40000 and err <= 0.02 and bad_ == 0,
      (on, sg[:6], n_, err, bad_))

# the engage at rate != 1 (a 44.1 kHz file, rate 0.91875; notes/re/a1): the app sends Sync 1/2 late in step 1 of 1/4 and
# stock's re-index puts the playing segment on step 1 of 1/2 while it still plays frame 43 063 < (int)(1 x 44 100): its
# elapsed frames are negative. Loop Len 1/2 taken there (block 374, the clock at 1 875 ticks, in the first half) takes
# the first half (origin 0, signed; an unsigned difference gave 186 992 640, a frame 78 247 window); the re-indexed
# segment plays on to 384 000, then every step replays frame 0. Frames read back as the reader gives them at this rate:
# 1 frame on, +-0.1 (the run without Loop Len reads the same way)
def late_sync(rr):
    if rr.block == 370:
        rr.param(P_SYNC, 2)
        store(rr.m, rr.q, {0x4: 500, P_SLIP: 0, P_SYNC: 2})


kw = dict(frames=88200, src_rate=44100, at=287000, blocks=1300, vals={P_SYNC: 3}, cell=0x102)   # pad 6: polled at 374
RT = 44100 / 48000
ref_ = audio(pre=ll_pre({}, sync=2, then=late_sync), **kw)
cw = audio(pre=ll_pre({371: 4}, sync=2, then=late_sync), **kw)
r = cw["rig"]
on = taken(r, 4)
sg, sr = seg_firsts(cw, 300000, RT), seg_firsts(ref_, 300000, RT)
n_, err, bad_ = follows(cw, rate=RT, off=1.0, tol=0.12)
nr, er, br = follows(ref_, rate=RT, off=1.0, tol=0.12)
check(f"Loop Len 1/2 on a 44.1 kHz file, taken where stock's re-index has put the playing segment a step ahead of its "
      f"position (block {on and on[0]}): origin {on and on[2]} (the clock's half, 1 875 ticks: 0), Sync 1/2 left alone; the "
      f"re-indexed segment plays on, then every step replays frame 0 ({sg[:4]}; without Loop Len {sr[:4]}); every sample "
      f"its segment's ({n_}, max {err:.3f} with the reader's 1-frame offset, as without it: {er:.3f}); summed gain = the run "
      f"without Loop Len ({same_gain(ref_, cw, 288300)} differ)",
      on and on[0] == 374 and on[2] == 0 and on[3] == 0 and on[4] == 1920 and len(sg) >= 3 and sg[0] == sr[0]
      and [x[:2] for x in sg[1:3]] == [(384000, 0), (432000, 1)] and [x[2] for x in sg[1:]] == [1] * (len(sg) - 1)
      and sr[2][2] == 44101 and n_ > 150000 and bad_ == 0 and br == 0 and nr > 150000
      and same_gain(ref_, cw, 288300) == 0, (on, sg[:5], sr[:5], n_, err, bad_, er, br))

# Off, then on again within the same Sync step (the stutter gesture): after Off the sounding segment still plays the
# window (frames 26 000 .. 34 000 at 362 000 .. 370 000), so the new engage takes its in-point from that frame, not from
# stock's unlooped position (72 000 + ..., which would give 2 880): the same beat, 24 000, from 384 000 on. Then Off at
# 415 000 (step 1: the steps after it play their own, 48 000 at 432 000) and on again at 453 400, inside step 2, where
# the sounding segment plays its own step: the in-point is where stock plays (1 920), 48 000 from 456 000 on
kw = dict(frames=96000, at=287000, blocks=1700, vals={P_SYNC: 3}, cell=0x102)   # pad 6: polled at 214 + 16k
cw = audio(pre=ll_pre({200: 3, 600: 0, 618: 3, 1000: 0, 1300: 3}), **kw)
r = cw["rig"]
tr = [x[:4] for i, x in enumerate(r.llog) if i and x[1] != r.llog[i - 1][1]]
sg = seg_firsts(cw, 300000)
n_, err, bad_ = follows(cw)
fr = [cw["frame"][x - cw["base"]] for x in (362000, 366000, 370000)]
check(f"Loop Len 1/4 on, Off and on again inside one Sync step (taken at blocks {[x[0] for x in tr[:3]]}): the window "
      f"still sounding after Off ({fr}) gives the in-point again (origins {[x[2] for x in tr[:3]]}), and the steps from "
      f"384 000 replay 24 000; Off (block {tr[3][0] if len(tr) > 3 else None}) and on again inside step 2 (block "
      f"{tr[4][0] if len(tr) > 4 else None}): the in-point where stock plays (origin {tr[4][2] if len(tr) > 4 else None}) "
      f"({[x[::2] for x in sg if 384000 <= x[0] <= 480000]}); every sample its segment's ({n_}, max {err:.4f})",
      len(tr) == 5 and [x[1:3] for x in tr] == [(3, 960), (0, 960), (3, 960), (0, 960), (3, 1920)]
      and tr[1][0] < 627 < tr[2][0] < 640 and 1300 < tr[4][0] < 1320 and fr == [26000.0, 30000.0, 34000.0]
      and [x[::2] for x in sg if 384000 <= x[0] <= 480000] == [(384000, 24000), (408000, 24000), (432000, 48000),
                                                                (456000, 48000), (480000, 48000)]
      and n_ > 150000 and err <= 0.02 and bad_ == 0, (tr, sg[:16], fr, n_, err, bad_))

# a pad stopped while Loop Len is on (taken inside step 1: in-point 960), then the store written again with the same
# Loop Len (as a preset reload leaves it), then relaunched: a stopped pad starts the window over at the clip's start, as
# a launch after power-on does (origin 0 from the first poll that sees it stopped), so the relaunch on the bar at 480 000
# and every step after it replay frame 0
kw = dict(frames=96000, at=287000, blocks=1960, vals={P_SYNC: 3})
cw = audio(pre=ll_pre({200: 3, 850: 3}, then=lambda rr: rr.note_on() if rr.block in (700, 1000) else None), **kw)
r = cw["rig"]
on = taken(r, 3)
reset = next((x for x in r.llog if on and x[0] > on[0] and x[2] != on[2]), None)
sg = seg_firsts(cw, 300000)
n_, err, bad_ = follows(cw)
quiet = cw["gain"][384300 - cw["base"]:480000 - cw["base"]]
check(f"Loop Len 1/4 taken inside step 1 (origin {on and on[2]}), the pad stopped by Toggle (silent from 384 300: "
      f"{not np.abs(quiet).max() > 1e-7}), its store written again with the same value, then relaunched: the in-point "
      f"is the clip's start again once the pad is stopped ({reset}); the relaunch on the bar at 480 000 and every step "
      f"after it replay frame 0 ({[x for x in sg if x[0] >= 480000][:4]}; before the stop {[x[2] for x in sg if x[0] < 400000]}); "
      f"every sample its segment's ({n_}, max {err:.4f})",
      on and on[2] == 960 and reset and reset[2] == 0 and 287000 + reset[0] * N < 384000 + 16 * N + 2048
      and not np.abs(quiet).max() > 1e-7 and [x[2] for x in sg if x[0] < 400000] == [24000] * 4
      and [x[:3] for x in sg if x[0] >= 480000][:3] == [(480000, 0, 0), (504000, 1, 0), (528000, 2, 0)]
      and n_ > 100000 and err <= 0.02 and bad_ == 0, (on, reset, sg[:10], n_, err, bad_))

# a new file under a pad playing a window (5b's chain; Loop Len latches at Slip 0 too): the segments latched for the old
# file read as stock reads, at their own positions in the new file, and the next ones latch the new file, the window's
# step played from the new file's frames per step (the in-point is in ticks: it stays)
for length in (50000, 192000):
    cw = audio(pre=ll_pre({100: 3}, then=new_file(length)), frames=96000, at=287000, blocks=900, vals={P_SYNC: 3})
    r = cw["rig"]
    on = taken(r, 3)
    old = {m_["sid"] for m_ in r.made if m_["block"] < SWAP}
    rows = [x for x in r.reads if x[0] >= SWAP + CLOSED and x[SID] in old]
    moved = [x for x in rows if (x[FET][0][1] != x[POS] if x[FET] else x[POS] < length)]
    held = [made_for(r.m, r.q, k) for k in range(4) if bank_valid(r.m, r.q) >> k & 1]
    fresh = [m_ for m_ in r.made if m_["block"] > SWAP + CLOSED + 1]
    t_new = min((x[AT] for x in r.reads if fresh and x[SID] == fresh[0]["sid"]), default=-1)
    sg = seg_firsts(cw, t_new)
    n_, err, bad_ = follows(cw, after=t_new + 256, vlen=length)
    check(f"Loop Len 1/4 taken in step 0 (origin {on and on[2]}), a {length}-frame file under the playing pad from {T_SWAP}: the "
          f"segments latched for the old file read from the file opening on as stock reads, at their own positions in the new "
          f"file ({len(rows)} reads, {len(moved)} mapped; past its end nothing, as stock); the next ones latch the new "
          f"file (made for {sorted(set(held))}) and replay its frame 0 ({sg[:3]}), every sample its segment's step of the "
          f"window ({n_} samples, max {err:.4f})",
          on and on[2] == 0 and len(rows) > 200 and not moved and held and set(held) == {length}
          and t_new == 360000 and sg[:3] and all(x[2] == 0 for x in sg[:3]) and n_ > 20000 and err <= 0.02 and bad_ == 0,
          (on, len(rows), moved[:2], held, t_new, sg[:4], n_, err, bad_))

# every write clipwin.c (and its bank 2 part, clipwin_b2.c, where Loop Len's take is) makes in a Loop Len run (engaged
# with Sync forced, changed, Off with Sync given back) lands in the bank; the param-set it calls writes the pad, as a 0x39
# message would
w = []
r = Rig(cell=0x102)
r.uc.hook_add(UC_HOOK_MEM_WRITE, lambda u_, acc, addr, size_, v, d_: w.append((addr, size_)) if any(
    a_ <= u_.reg_read(UC_ARM_REG_PC) < b_ for a_, b_ in cw_code) else None, begin=BLOCK, end=BLOCK + 0x100000)
store(r.m, 6, {0x4: 500, P_SYNC: 3})
for _ in range(16):
    poll(r)
r.pre_block = lambda rr: (poll(rr), ll_pre({300: 1, 500: 3, 700: 0})(rr))
r.params()
r.goto(287000)
r.note_on()
r.run(900)
hit = {name: any(lo <= a_ - BANK < hi for a_, s_ in w) for name, lo, hi in (("origin", B_ORIGIN, B_LL), ("ll", B_LL, B_FORCED),
                                                                           ("forced", B_FORCED, B_SF), ("sf", B_SF, B_SIZE))}
check(f"in a Loop Len run, every write clipwin.c and clipwin_b2.c make into the SDRAM block lands in cw_bank's {B_SIZE:#x} bytes (origin, "
      f"Loop Len, forced and the latches' Slip part written: {hit}); Sync forced to 1/16, eased to 1/8 at 1/4 (the largest "
      f"that divides the in-point), given back on Off ({[x[4] for i, x in enumerate(r.llog) if i and x[4] != r.llog[i - 1][4]]})",
      w and all(hit.values()) and all(BANK <= a_ and a_ + s_ <= BANK + B_SIZE for a_, s_ in w)
      and [x[4] for i, x in enumerate(r.llog) if i and x[4] != r.llog[i - 1][4]] == [240, 480, 960] and r.i64(r.pad + 0x220) == 960,
      (sorted({hex(a_) for a_, s_ in w if not BANK <= a_ < BANK + B_SIZE})[:4], hit))

# a window that is not a whole number of the pad's steps although longer: Loop Len 1/2 on a 5-beat clip with Sync 1/2
# (n = 2, steps of 2 400 ticks), engaged inside step 1: forced to 1/4, the largest Sync that divides the window, its
# in-point and the clip. Stock plays this clip with a gap (its step 1 snaps to the 2 400 grid) and its re-grid to 1/4
# skips steps: the stock image sent Sync 1/4 in the same block does exactly the same, sample for sample
kw = dict(frames=120000, beats=5, at=287000, sync=2, blocks=1700, vals={P_SYNC: 2})
cw = audio(pre=ll_pre({600: 4}, sync=2), **kw)
r = cw["rig"]
on = taken(r, 4)
st_ = audio(frames=120000, beats=5, at=287000, sync=2, blocks=1700, image=STOCK,
            pre=lambda rr: rr.param(P_SYNC, 3) if on and rr.block == on[0] else None)
sg = seg_firsts(cw, 287000 + on[0] * N + 2048 if on else 0)
n_, err, bad_ = follows(cw)
same_starts = [x[:2] for x in starts(r)] == [x[:2] for x in starts(st_["rig"])]
check(f"Loop Len 1/2 on a 5-beat clip with Sync 1/2 (steps of {r.made[0]['tps']} ticks), taken inside step 1: Sync forced "
      f"to 1/4 (+0x220 {on and on[4]}), origin {on and on[2]}; the steps play the window's two beats, 48 000 and 72 000 "
      f"({sg[:5]}), every sample its segment's ({n_}, max {err:.4f}); starts and summed gain as the stock image sent Sync "
      f"1/4 in that block ({same_starts}, {same_gain(st_, cw, 288300)} samples differ)",
      r.made[0]["tps"] == 2400 and on and on[4] == 960 and on[3] == 1 and on[2] == 1920 and len(sg) >= 4
      and all(x[2] == 48000 + 24000 * (((x[1] * 960 - 1920) % 1920) // 960) for x in sg) and {x[2] for x in sg} == {48000, 72000}
      and n_ > 80000 and err <= 0.02 and bad_ == 0 and same_starts and same_gain(st_, cw, 288300) == 0, (on, sg[:8], n_, err, bad_))

# Every Clip Window hook's maths is in bank 2 (clipwin_b2.c, D-018): without this build's payload there (its header wiped
# before the first poll, so the first b2_live() says no for the whole run) every hook passes through to stock. L2's run,
# Loop Len 1/16 set and then Off: bit for bit the run where it is never set, the Sync never forced, and no bank-2
# function entered
kw = dict(frames=96000, at=193000, blocks=1900, vals={P_SYNC: 3})
nb = scenario(pre=ll_pre({1000: 1, 1750: 0}), bank2=False, **kw)
rf = scenario(pre=ll_pre({}), **kw)
ok_, d_ = same(rf, nb)
check(f"no bank 2 (its header wiped before the first poll): Loop Len 1/16 set and then Off plays as if it had never been "
      f"set, bit for bit ({d_}), never taken ({sorted({x[1] for x in nb.llog})}), Sync never forced "
      f"({sorted({x[4] for x in nb.llog})}), and no bank-2 function entered ({len(nb.b2_entered)} entries of "
      f"{len(CW_FUNCS)} functions)",
      ok_ and {x[1] for x in nb.llog} == {0} and {x[4] for x in nb.llog} == {960} and not nb.b2_entered and len(CW_FUNCS) >= 14,
      (d_, sorted(set(nb.b2_entered)), CW_FUNCS))
# ...and with all three set from the start (Slip +480, Region Loop over [24 000, 72 000) in the class-H object, Loop Len
# 1/4) and a live Slip change: every read, fetch, prefetch, mixed sample and message as with every clipwin hook taken out
kw = dict(frames=96000, cell=0x102, blocks=900, slip=480, points=(24000, 72000, 1), region=LOOP, vals={P_SYNC: 3, P_LOOPLEN: 3},
          pre=lambda rr: store(rr.m, rr.q, {0x4: 500, P_SLIP: -30, P_REGION: LOOP, P_SYNC: 3, P_LOOPLEN: 3}) if rr.block == 300 else None)
nb = scenario(bank2=False, **kw)
by = scenario(bypass=True, **kw)
wb = scenario(**kw)
ok_, d_ = same(nb, by)
differs = not same(wb, by)[0]
check(f"no bank 2, with Slip +480 (then -30), Region Loop [24 000, 72 000) and Loop Len 1/4 set: every Clip pad plays "
      f"stock, bit for bit the run with every clipwin hook taken out ({d_}), no bank-2 function entered "
      f"({len(nb.b2_entered)}), nothing latched (valid {bank_valid(nb.m, 6):#x}), no Sync forced ({nb.i64(nb.pad + 0x220)}); "
      f"with bank 2 the same run is not stock's ({differs}: latched {bank_valid(wb.m, 6):#x})",
      ok_ and not nb.b2_entered and bank_valid(nb.m, 6) == 0 and nb.i64(nb.pad + 0x220) == 960 and differs
      and bank_valid(wb.m, 6), (d_, sorted(set(nb.b2_entered)), differs))
# ...and Slip 0, Region File, Loop Len Off over a loop in the class-H object: the stock 3.1.9 image's run, bit for bit
a = scenario(frames=96000, cell=0x102, blocks=900, points=REG, region=FILE, bank2=False)
b = scenario(frames=96000, cell=0x102, blocks=900, points=REG, image=STOCK)
ok_, d_ = same(a, b)
check(f"no bank 2: Slip 0, Region File and Loop Len Off over a loop play as the stock 3.1.9 image, bit for bit ({d_})", ok_, d_)

# ====================================================================================================== 12. the Waveform knobs
# Clip mode on the Waveform screen (README section 3, notes/re/a3): stock unbinds all four knobs and never draws the loop
# bracket. Patched: TL = Loop Start (0x91), TR = Loop End (0x92), sample positions (type 0xd) one zoom pixel a step, ranged
# as stock ranges them in Sample mode; BL = Slip, BR = Loop Len; the white bracket when Region plays the loop. Real: the
# screen's setup FUN_080a54a0 (its bind block, FUN_080a53a2, the refresh), the binder FUN_080a7ee0, the knob widget (reset,
# label, type, range, value, list, the turn FUN_080b0d54, stepper, accelerator, formatter, clipwin_format / clipwin_turn
# in them), the view's two handlers (FUN_080a6d28: the knob event 0x32, the param-changed refresh 0x66; FUN_080a66dc: the
# forward of 0x3d / 0x3c with JOEBOX's slice_forward in it, the zoom message 0xe5), the waveform's slice-marker setter
# FUN_080c6e8c and its zoom set FUN_080c6f44, and the app's SetCellParam FUN_0809fa50 for what the forward sends. Stubbed:
# the app's copy of the pad's store into the view (FUN_0809a830: the store kept here), the file name, text widgets
# (recorded), icons, buttons and the mode list, the knob redraw, the view's post (recorded); SetCellParam's posts to the
# engine and the UI (recorded). The app posting 0x66 after it stored a value is done here, as the app does it.
SITES12 = {"clipwin_bind": (0x080A582A, 0x080A7EE0), "clipwin_zoom": (0x080A53B0, 0x080A52C4),
           "clipwin_wave": (0x080A5B0E, 0x080C6E8C)}
VIEW, VENT, VMSG = 0x24060000, 0x24070000, 0x24078000
KN12 = {"TL": 0x670, "BL": 0x950, "TR": 0xC30, "BR": 0xF10}
WV = VIEW + 0x38
CLIP12 = {0x8B: 1, 0xEA: 0, 0x8E: 1, 0x8F: 0, 0x90: 0, 0x91: 24000, 0x92: 72000, 0x8D: 1, 0x94: 3, 0x47: 3, 0xD2: 0,
          P_REGION: AUTO, P_SLIP: 480, P_LOOPLEN: 3}


class Screen:
    """the Waveform view of pad (1, 2) on an emulator of `image`; bypass = the three Waveform hooks put back to stock;
    bank2=False: bank 2's header wiped before anything runs (entries into cw_* counted in b2_entered); stock_knob = the
    knob's text and turn hooks (clipwin_format, clipwin_turn) put back to stock; compose: the knob's real redraw
    (FUN_080b0480, its "%s %s" line of name and value, recorded at the knob's + 0xf4 text), else stubbed"""

    def __init__(self, image=IMAGE, bypass=False, bank2=True, stock_knob=False, compose=False):
        m = self.m = Emu(image, "out/cave.elf")
        maps(m)
        self.b2_entered = []
        if not bank2:
            no_bank2(m, self.b2_entered)
        if stock_knob:
            for at in (0x080B0746, 0x080B0E18, 0x080B0DDE):
                m.uc.mem_write(at, stock[at - BASE:at - BASE + 4])
        registrar(m, TABLE)
        if bypass:
            for at, _ in SITES12.values():
                m.uc.mem_write(at, stock[at - BASE:at - BASE + 4])
        m.uc.mem_write(VIEW, bytes(0x5000))
        for o in KN12.values():
            m.w32(VIEW + o, 0x080F0C88)
        self.vals, self.texts, self.posts, self.binds = {}, [], [], []
        m.stub(0x0809A830, lambda: self.copy(self.vals))
        m.stub(0x0809AD74, lambda: m.uc.mem_write(m.arg(2), b"loop.wav\0"))
        if compose:                                          # the text set for real (the line reads the widgets back)
            m.uc.hook_add(UC_HOOK_CODE, lambda *a: self.texts.append((m.arg(0) - VIEW, m.cstr(m.arg(1)))),
                          begin=0x080C3B98, end=0x080C3B98)
        else:
            m.stub(0x080C3B98, lambda: self.texts.append((m.arg(0) - VIEW, m.cstr(m.arg(1)))))
        for a in (0x080A5480, 0x080A3DEC, 0x080C6078, 0x080C4DD6, 0x080C4DF0, 0x080A401C, 0x080BD398, 0x080BD74E,
                  0x080C6004, 0x080A5210) + (() if compose else (0x080B0480,)):
            m.stub(a)
        m.stub(0x080A331A, lambda: m.uc.mem_write(m.arg(0) + 0x30, bytes([m.arg(1) & 0xFF])))   # a knob's grey flag
        m.stub(0x080AED14, lambda: self.posts.append((m.r16(m.arg(1)), m.r32(m.arg(1) + 0xC), m.r32(m.arg(1) + 0x10))))
        m.uc.hook_add(UC_HOOK_CODE, lambda *a: self.binds.append((m.arg(0), m.arg(1), m.arg(2) - VIEW)),
                      begin=0x080A7EE0, end=0x080A7EE0)
        m.w32(VIEW + 0x2390, 192000)                         # the file's length
        m.w32(VIEW + 0x47C8 + 8, 400)                        # the marker stepper's counts per step
        m.uc.mem_write(VIEW + 0x29C, struct.pack("<H", 0x12))
        m.uc.mem_write(VIEW + 0x3740, b"\x01")               # turns go to the knobs (not the popup list)
        m.w32(GUI_MS, 10_000)
        sdram(m)                                             # the Slip knob's hold on 0 lives in cw_bank
        m.w32(BANK, 0)

    def copy(self, vals):
        rows = sorted(vals.items())
        self.m.uc.mem_write(VENT, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
        self.m.w32(VIEW + 0x2370 + 4, VENT)
        self.m.uc.mem_write(VIEW + 0x2370 + 10, struct.pack("<HH", len(rows), 96))

    def msg(self, handler, mid, a=0, b=0, pad=0x12):
        self.m.uc.mem_write(VMSG, struct.pack("<HHIHHiiI", mid, 0, 0x080CFBA4, pad, 0, a, b, 0))
        self.m.call(handler, VIEW, VMSG, count=50_000_000)

    def open(self, vals, was=0):
        """the screen set up for the pad, which was in mode `was` the last time the view looked"""
        self.vals = dict(vals)
        self.copy({**vals, 0x8B: was})
        self.binds.clear()
        self.texts.clear()
        self.m.call(0x080A54A0, VIEW, 0, count=50_000_000)

    def stored(self, **upd):
        """the app stored the pad's value(s) and posts 0x66: the view's refresh"""
        self.vals.update({int(k[1:], 16): v for k, v in upd.items()})
        self.msg(0x080A6D28, 0x66)

    def turn(self, k, counts, t=None):
        """one knob event (0x32: TL 0, BL 1, TR 2, BR 3) -> the knob's own post -> the view's forward; then the app
        stores what was forwarded and posts 0x66. Returns (the knob's posts, the forwards)"""
        if t is not None:
            self.m.w32(GUI_MS, t)
        self.posts.clear()
        self.msg(0x080A6D28, 0x32, k, counts)
        own, fwd = list(self.posts), []
        for p_ in own:
            self.posts.clear()
            self.m.uc.mem_write(VMSG, struct.pack("<HHIHHiiI", p_[0], 0, 0x080CFBA4, 0, 0, p_[1], p_[2], 0))
            self.m.call(0x080A66DC, VIEW, VMSG, count=50_000_000)
            fwd += self.posts
        for p_ in fwd:
            if p_[0] == 0x6E:
                self.vals[p_[1]] = p_[2]
        if fwd:
            self.msg(0x080A6D28, 0x66)
        return own, fwd

    def knob(self, name):
        k = VIEW + KN12[name]
        m = self.m
        return dict(id=m.r32(k + 0x14), type=m.r8(k + 0x31), lo=m.r32(k + 0x14C), hi=m.r32(k + 0x150), step=m.r32(k + 0x28C),
                    pending=m.r32(k + 0x290), idx=m.r32(k + 0x27C), start=m.r32(k + 0x288), n=m.r32(k + 0x280),
                    acc=m.r32(k + 0x270), grey=m.r8(k + 0x30))

    def shown(self, name):
        """the knob's value as the turn would post it: type 0xd the pending position, else idx x step + start; others
        idx + start"""
        k = self.knob(name)
        if k["type"] == 0xD:
            return k["pending"] if k["pending"] != 0x7FFFFFFE else min(max(k["idx"] * k["step"] + k["start"], k["lo"]), k["hi"])
        return k["idx"] + k["start"]

    def text(self, name, off=0x9C):
        t = [x for a, x in self.texts if a == KN12[name] + off]
        return t[-1] if t else None

    def wave(self):
        m = self.m
        return dict(on=m.r8(WV + 0x239), ls=m.r32(WV + 0x22C), le=m.r32(WV + 0x230), dirty=m.r8(WV + 0x32),
                    slices=m.r8(WV + 0x238), startlen=m.r8(WV + 0x23A))

    def state(self):
        return {n: self.knob(n) for n in KN12} | {"wave": self.wave()}


# ---- Clip: the setup binds the four knobs, the position pair stepped, ranged and valued in that order
sc = Screen()
sc.open(CLIP12)
b_ = sc.binds
st = sc.state()
check(f"Clip setup: stock's three unbinds (TL, TR, BL), then the hook at BR binds TL 0x91 = 24 000, TR 0x92 = 72 000, BL "
      f"Slip = 480, BR Loop Len = 3 through the stock binder with the store's values ({[(hex(i), v, hex(o)) for i, v, o in b_]})",
      b_ == [(0, 0, 0x670), (0, 0, 0xC30), (0, 0, 0x950), (0x91, 24000, 0x670), (0x92, 72000, 0xC30), (P_SLIP, 480, 0x950),
             (P_LOOPLEN, 3, 0xF10)], b_)
check(f"  names {[sc.text(n, 0x44) for n in ('TL', 'TR', 'BL', 'BR')]} (the binder's, from the table, then this screen's: "
      f"{[x for a, x in sc.texts if a in (0x670 + 0x44, 0xC30 + 0x44, 0x950 + 0x44, 0xF10 + 0x44)]}), texts "
      f"{[sc.text(n) for n in ('TL', 'TR', 'BL', 'BR')]} (Slip as beats.ticks, Loop Len its name)",
      [sc.text(n, 0x44) for n in ("TL", "TR", "BL", "BR")] == ["LpS", "LpE", "Slip", "LpLen"]
      and [sc.text(n) for n in ("TL", "TR", "BL", "BR")] == ["24000", "72000", "+0.480", "1/4"], sc.texts[-12:])

# ---- the knobs' lines fit (Gate 3 finding 2: "Loop Start", "Loop End", "Slip", "Loop Len" too long, the values hidden
# by the neighbour's name). A knob draws "name value" (FUN_080b0480, real here) in its + 0xf4 text: the box and the
# alignment from the knob's own set-rect FUN_080afeb2 (real) on the rects and styles the view's constructor FUN_080a5b90
# gives them (TL (0, 74, 157, 73) style 1, BL (0, 0, ...) 2, TR (158, 74, ...) 3, BR (158, 0, ...) 4, its text size
# 0x10), the width of a line from the text draw's own measure (FUN_0808ed28: length x the font's width x 2 at size 0x10,
# the font's width a u16 at 0x240000d4, its .data image at 0x080f1d80 + 0xd4)
CHAR_W = struct.unpack_from("<H", img, 0x080F1D80 + 0xD4 - BASE)[0] * 2
geom = {}
for name, (x, y, style) in {"TL": (0, 0x4A, 1), "BL": (0, 0, 2), "TR": (0x9E, 0x4A, 3), "BR": (0x9E, 0, 4)}.items():
    kn = 0x24068000
    e.uc.mem_write(kn, bytes(0x300))
    e.uc.mem_write(kn + 0x32, bytes([style]))
    e.uc.mem_write(kn + 0x98, b"\x10")
    e.uc.mem_write(0x24068400, struct.pack("<4i", x, y, 0x9D, 0x49))
    e.stub(0x080AEC44)
    e.call(0x080AFEB2, kn, 0x24068400)
    del e.stubs[0x080AEC44]
    geom[name] = (e.r32(kn + 0xF4 + 4), e.r32(kn + 0xF4 + 0xC), e.r8(kn + 0xF4 + 0x51))   # x, w, alignment (1 left, 3 right)


def extent(name, line):
    x, w, al = geom[name]
    n = len(line) * CHAR_W
    return (x, x + n) if al == 1 else (x + w - n, x + w)


def lines(scr):
    return {n: [x for a, x in scr.texts if a == KN12[n] + 0xF4][-1] for n in KN12}


def fits(ln):
    """each line inside its box, and the two of a row clear of each other"""
    ex = {n: extent(n, ln[n]) for n in ln}
    inside = all(geom[n][0] <= ex[n][0] and ex[n][1] <= geom[n][0] + geom[n][1] for n in ln)
    return inside and ex["TL"][1] <= ex["TR"][0] and ex["BL"][1] <= ex["BR"][0], ex


big = {**CLIP12, 0x91: 99999998, 0x92: 99999999, P_SLIP: -3840, P_LOOPLEN: 7}
mid = {**CLIP12, 0x91: 1000000, 0x92: 1234567}
for what, vals_, length in (("the setup's values", CLIP12, 192000),
                            ("positions of seven digits (a loop past 21 s of a 30 s file)", mid, 1440000),
                            ("the widest ones (positions of eight digits, Slip -4.000, Loop Len 4 bars)", big, 100000000)):
    scl = Screen(compose=True)
    scl.m.w32(VIEW + 0x2390, length)
    scl.open(vals_)
    ln = lines(scl)
    ok_, ex = fits(ln)
    check(f"  the four lines with {what}: {ln}; {CHAR_W} px a character, each inside its {geom['TL'][1]}-px box "
          f"(left from x {geom['TL'][0]}, right ending at {geom['TR'][0] + geom['TR'][1]}) and clear of its neighbour: {ex}",
          ok_ and geom["TL"][2] == 1 and geom["TR"][2] == 3 and geom["BL"][2] == 1 and geom["BR"][2] == 3
          and ln["TL"].startswith("LpS ") and ln["BR"].startswith("LpLen "), (ln, ex, geom))
old_names = {"TL": "Loop Start:", "TR": "Loop End:", "BL": "Slip:", "BR": "Loop Len:"}
old_ok, old_ex = fits({n: f"{old_names[n]} {v}" for n, v in (("TL", 24000), ("TR", 72000), ("BL", "+0.480"), ("BR", "1/4"))})
check(f"  ...where the table's names (the binder's, 37.2.x) did not fit even the setup's values: {old_ex}", not old_ok, old_ex)
tl, tr = st["TL"], st["TR"]
check(f"  TL Loop Start: type 0xd, a step of the setup's zoom (256 frames a pixel), 0 .. Loop End, at 24 000 (stock's binder "
      f"alone leaves 0 .. 1000 with 1 000 shown: {tl}); TR Loop End: 24 000 .. the length 192 000, at 72 000 ({tr})",
      (tl["type"], tl["step"], tl["lo"], tl["hi"], sc.shown("TL")) == (0xD, 256, 0, 72000, 24000)
      and (tr["type"], tr["step"], tr["lo"], tr["hi"], sc.shown("TR")) == (0xD, 256, 24000, 192000, 72000), (tl, tr))
check(f"  BL Slip type 1 at +480, BR Loop Len a list (type 5) at 1/4, none greyed ({st['BL']}, {st['BR']})",
      st["BL"]["type"] == 1 and sc.shown("BL") == 480 and st["BR"]["type"] == 5 and sc.shown("BR") == 3
      and not any(st[n]["grey"] for n in KN12), (st["BL"], st["BR"]))
w_ = st["wave"]
check(f"  the loop bracket drawn (Region Auto, Loop Mode on): [24 000, 72 000), shown, dirty; slice markers and the pink "
      f"start bracket off as stock leaves them ({w_})", w_ == dict(on=1, ls=24000, le=72000, dirty=1, slices=0, startlen=0), w_)

# stock (and the hooks bypassed): nothing bound, no bracket
for nm, scr in (("stock", Screen(STOCK)), ("hooks bypassed", Screen(bypass=True))):
    scr.open(CLIP12)
    s2 = scr.state()
    check(f"  on the {nm} image the same setup binds nothing (ids {[hex(s2[n]['id']) for n in KN12]}, types "
          f"{[s2[n]['type'] for n in KN12]}) and draws no bracket ({s2['wave']['on']})",
          all(s2[n]["id"] == 0 and s2[n]["type"] == 0 for n in KN12) and s2["wave"]["on"] == 0, s2)

# ---- turns through the view: the knob posts, the view forwards to the app, the app stores and posts 0x66, the view
# refreshes. TL and TR turn as stock's own Loop Start and Loop End knobs turn in Sample mode, where they are BL and BR:
# the same screen in Sample mode at the same zoom, the same turns - the same posts and knob states, turn after turn
sm = Screen()
sm.open({**CLIP12, 0x8B: 0}, was=1)
sm.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 256.0))
sm.msg(0x080A66DC, 0xE5)                                   # Sample mode fits the whole file: zoomed in to the Clip's 256
pos = lambda s_, n: {k: s_.knob(n)[k] for k in ("type", "lo", "hi", "step", "idx", "start", "pending")}
seq = [(0, -400), (0, 1200), (2, -400), (2, 2800), (0, -8000), (2, -400 * 3)]
clip_f, samp_f, alike, drawn = [], [], [], []
for i, (k, c) in enumerate(seq):
    sc.m.uc.mem_write(WV + 0x32, b"\x00")              # drawn: each turn moves the pair under a bracket that stays shown
    clip_f += sc.turn(k, c, t=20_000 + 100 * i)[1]
    samp_f += sm.turn({0: 1, 2: 3}[k], c, t=20_000 + 100 * i)[1]
    alike.append(pos(sc, "TL") == pos(sm, "BL") and pos(sc, "TR") == pos(sm, "BR"))
    w = sc.wave()
    drawn.append((w["on"], w["dirty"], (w["ls"], w["le"]) == (sc.vals[0x91], sc.vals[0x92])))
st = sc.state()
ls, le = sc.vals[0x91], sc.vals[0x92]
check(f"TL / TR turned slow and fast, down and up ({len(seq)} turns): the same posts as Sample mode's Loop Start / End knobs "
      f"({clip_f}), the same steps, ranges and positions after each turn ({alike}); one step down from 24 000 posts 23 552, "
      "the stepper cell below 24 000's, as stock's (the binder alone would post 999)",
      clip_f == samp_f and len(clip_f) == len(seq) and all(alike) and clip_f[0] == (0x6E, 0x91, 23552), (clip_f, samp_f, alike))
check(f"  each forwarded as 0x6e and stored; the refresh ranges each by the other (TL 0 .. {st['TL']['hi']}, TR "
      f"{st['TR']['lo']} .. {st['TR']['hi']}) and the bracket follows: [{st['wave']['ls']}, {st['wave']['le']}), shown "
      f"through every turn, each turn's new pair drawn and marked dirty (on, dirty, the stored pair: {drawn})",
      all(x[0] == 0x6E and x[1] in (0x91, 0x92) for x in clip_f) and (st["TL"]["lo"], st["TL"]["hi"]) == (0, le)
      and (st["TR"]["lo"], st["TR"]["hi"]) == (ls, 192000) and (st["wave"]["on"], st["wave"]["ls"], st["wave"]["le"]) == (1, ls, le)
      and drawn == [(1, 1, True)] * len(seq), (st["TL"], st["TR"], st["wave"], ls, le, drawn))
sc.m.uc.mem_write(WV + 0x32, b"\x00")
sc.stored()
check(f"a refresh that changes nothing leaves the waveform clean (dirty {sc.wave()['dirty']})", sc.wave()["dirty"] == 0)
own, fwd = sc.turn(3, -800, t=20_300)
check(f"BR Loop Len two list steps down: 1/16 (index 1), sent as a list change (0x3c) and forwarded as 0x6e 0x1ca "
      f"({own}, {fwd}); text {sc.text('BR')}", own == [(0x3C, 1, P_LOOPLEN)] and fwd == [(0x6E, P_LOOPLEN, 1)]
      and sc.text("BR") == "1/16" and sc.shown("BR") == 1, (own, fwd, sc.text("BR")))

# Slip on BL: the same knob as on the Pos page, every turn coming back as a refresh. A refresh re-values only a value the
# store holds differently: a set value parks the stepper mid-step, which on every turn would double the slow speed.
def slip_run(round_trip, per_ms, events, sign=1, start=0):
    s_ = Screen()
    s_.open({**CLIP12, P_SLIP: start})
    c, t = sign * int(per_ms * 16), 30_000
    k = VIEW + 0x950
    for i in range(8):
        s_.m.uc.mem_write(k + 0x294 + 8 * i, struct.pack("<iI", c, t - 16 * (7 - i)))
    s_.m.w32(k + 0x2D4, 0)
    vals_ = []
    for _ in range(events):
        t += 16
        if round_trip:
            s_.turn(1, c, t=t)
        else:
            s_.m.w32(GUI_MS, t)
            s_.m.call(0x080B0D54, k, c)
        vals_.append(s_.shown("BL"))
    return vals_, s_


rt, s_ = slip_run(True, 0.7, 40)
bare, _ = slip_run(False, 0.7, 40)
check(f"BL Slip, slow (0.7 counts/ms, 40 events): every turn forwarded and refreshed gives the bare knob's values, 1 tick "
      f"per 40 counts ({rt[-1]} vs {bare[-1]}; store {s_.vals[P_SLIP]}, text {s_.text('BL')})",
      rt == bare and rt[-1] == 40 * 11 // 40 and s_.vals[P_SLIP] == rt[-1] and s_.text("BL") == "+0.011", (rt[-5:], bare[-5:]))
rt, s_ = slip_run(True, 6, 20, sign=-1, start=300)
bare, _ = slip_run(False, 6, 20, sign=-1, start=300)
n_held = (DETENT - 1) // 16                                # the events under ZERO_DETENT_MS after the arrival
check(f"  fast down from +300 through the view: the 1/64 grid, the detent on 0 for {n_held} events, then past it "
      f"({rt[:6]} ... {rt[-3:]}), as the bare knob ({bare[:6]} ... {bare[-3:]})",
      rt == bare and rt[:5] == [240, 180, 120, 60, 0] and rt[5:5 + n_held] == [0] * n_held
      and rt[5 + n_held:] == [-GRID * (i + 1) for i in range(15 - n_held)] and s_.vals[P_SLIP] == rt[-1], (rt, bare))
s_.stored(_1c9=-1200)
check(f"  a Slip the store gets from elsewhere is shown at the next refresh ({s_.shown('BL')}, {s_.text('BL')})",
      s_.shown("BL") == -1200 and s_.text("BL") == "-1.240", (s_.shown("BL"), s_.text("BL")))

# what the forward sends, the app stores (SetCellParam FUN_0809fa50, real): a Clip pad's store takes all four
sp_posts = []
sc.m.stub(0x0804C59C, lambda: sp_posts.append(("engine", sc.m.arg(1), sc.m.arg(2), sc.m.arg(3))))
sc.m.stub(0x080B5758, lambda: sp_posts.append(("ui", sc.m.r16(sc.m.arg(1)), sc.m.r16(sc.m.arg(1) + 8))))
CLS = 0x24079000
sc.m.uc.mem_write(CLS, struct.pack("<HH", 0x2003, 0x4770))                 # movs r0, #3; bx lr: a pad store's class
sc.m.w32(CLS + 0x10, CLS | 1)
ST12, ENT12 = APP_PADS + 1 * 0xF0 + 2 * 0x30, 0x2407A000
rows = sorted(CLIP12.items())
sc.m.uc.mem_write(ENT12, b"".join(struct.pack("<HHi", i, 0, v) for i, v in rows))
sc.m.w32(ST12, CLS + 0x10)
sc.m.w32(ST12 + 4, ENT12)
sc.m.uc.mem_write(ST12 + 10, struct.pack("<HH", len(rows), 96))
CELL12 = 0x2407B000
sc.m.uc.mem_write(CELL12, struct.pack("<IHH", 0, 0x0012, 0))
got, sets12 = {}, ((0x91, 24576), (0x92, 71936), (P_SLIP, -60), (P_LOOPLEN, 1))
for pid, v in sets12:
    sp_posts.clear()
    sc.m.call(0x0809FA50, APP, CELL12, pid, v, 0, count=20_000_000)
    sc.m.call(0x08093E9C, ST12, pid)
    got[pid] = (sc.m.uc.reg_read(66), [x for x in sp_posts])
check(f"SetCellParam on the Clip pad's store (mode {CLIP12[0x8B]}) stores what the forward sends: Loop Start, Loop End, "
      f"Slip, Loop Len, and posts each to the engine and the UI ({ {hex(k): v[0] for k, v in got.items()} })",
      {k: v[0] & 0xFFFFFFFF for k, v in got.items()} == {0x91: 24576, 0x92: 71936, P_SLIP: (-60) & 0xFFFFFFFF, P_LOOPLEN: 1}
      and all(any(x[0] == "engine" for x in v[1]) and any(x[0] == "ui" for x in v[1]) for v in got.values()), got)
# ...and the engine's post is the {cell, id, value} the engine takes (the 0x39 message the Rig's Region and Loop Len runs
# start from): what ties a turn on this screen to what the pad plays
eng12 = {pid: [x[1:] for x in got[pid][1] if x[0] == "engine"] for pid, _ in sets12}
check(f"  each posted to the engine as cell 0x102 (row 1, col 2), the id and the value ({ {hex(k): v for k, v in eng12.items()} })",
      all(eng12[pid] == [(0x102, pid, v & 0xFFFFFFFF)] for pid, v in sets12), eng12)

# ---- the zoom: msg 0xe5 (no refresh follows it) re-steps the pair, keeping range and value, as Sample mode's
for s_ in (sc, sm):
    s_.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 16.0))
    s_.msg(0x080A66DC, 0xE5)
st = sc.state()
check(f"zoom to 16 frames a pixel (msg 0xe5): TL and TR step 16, same ranges and values ({st['TL']['step']}, "
      f"{st['TR']['step']}; {sc.shown('TL')}, {sc.shown('TR')}), as Sample mode's pair",
      (st["TL"]["step"], st["TR"]["step"], st["TL"]["hi"], st["TR"]["lo"], sc.shown("TL"), sc.shown("TR")) == (16, 16, le, ls, ls, le)
      and pos(sc, "TL") == pos(sm, "BL") and pos(sc, "TR") == pos(sm, "BR"), (st["TL"], st["TR"]))
f1, f2 = sc.turn(2, 400, t=40_000)[1], sm.turn(3, 400, t=40_000)[1]
check(f"  TR one step up then: {f1}, a pixel at that zoom, as Sample mode's ({f2})", f1 == f2 == [(0x6E, 0x92, le + 16)], (f1, f2))
sc.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 0.5))
sc.msg(0x080A66DC, 0xE5)
check(f"  a zoom under one frame a pixel (0.5) steps 1 frame ({sc.knob('TL')['step']}, {sc.knob('TR')['step']})",
      sc.knob("TL")["step"] == 1 and sc.knob("TR")["step"] == 1)

# ---- the bracket shows what Region plays (the engine's rule, is_loop), marked dirty only when it changes
br = Screen()
br.open(CLIP12)
cases = [("Region File", dict(_1c8=FILE), 0), ("Auto, Loop Mode None (finding 7)", dict(_1c8=AUTO, _8e=0), 1),
         ("Loop, Loop Mode None", dict(_1c8=LOOP), 1), ("Loop, the whole file [0, 192 000)", dict(_91=0, _92=192000), 0),
         ("Loop, [0, 191 999] (a whole-file smpl loop)", dict(_92=191999), 0), ("Loop, [1, 191 999)", dict(_91=1), 1),
         ("Loop, Loop End past the file", dict(_92=192001), 0), ("Loop, Loop Start = Loop End", dict(_91=50000, _92=50000), 0),
         ("Auto, Loop Mode on, [24 000, 72 000)", dict(_1c8=AUTO, _8e=1, _91=24000, _92=72000), 1),
         ("Loop End moved while Region plays the loop: [24 000, 96 000)", dict(_92=96000), 1),
         ("Slip changed: nothing moves", dict(_1c9=-30), 1)]
got_, ok_ = [], True
for name, upd, want in cases:
    before = br.wave()
    br.m.uc.mem_write(WV + 0x32, b"\x00")
    br.stored(**upd)
    w = br.wave()
    moved = w["on"] != before["on"] or (w["on"] and (w["ls"], w["le"]) != (before["ls"], before["le"]))
    got_.append((name, w["on"], w["dirty"]))
    ok_ &= w["on"] == want and w["dirty"] == moved and (not want or (w["ls"], w["le"]) == (br.vals[0x91], br.vals[0x92]))
check(f"the bracket at each refresh: shown exactly when Region plays the loop, at [Loop Start, Loop End), dirty only when "
      f"it changed, shown or moved ({[(n, o, d) for n, o, d in got_]})",
      ok_ and [o for _, o, _ in got_] == [w_ for _, _, w_ in cases] and got_[-2][1:] == (1, 1), got_)
MK = 0x2407C000
sl = Screen()
sl.m.uc.mem_write(MK, struct.pack("<3I", 0, 64000, 128000))
sl.m.w32(VIEW + 0x2398, MK)
sl.m.w32(VIEW + 0x2398 + 4, 3)
sl.m.w32(WV + 0x184, MK + 0x100)
sl.open(CLIP12)
w = sl.wave()
check(f"a Clip pad with slice markers: the bracket beside them, the markers still shown (FUN_080c6edc would hide them) ({w})",
      w["on"] == 1 and w["slices"] == 1 and (w["ls"], w["le"]) == (24000, 72000), w)

# ---- without bank 2 (D-018): the four rows are bound all the same (Loop Start and End are stock's own; Slip and Loop
# Len are kept, as stored, and do nothing), but no bracket shows where Region plays the loop, and the Slip knob is
# stock's: its text and every turn as with the knob's two hooks taken out (the turn's counts straight to the stepper)
nb2, kref = Screen(bank2=False), Screen(stock_knob=True)
runs = []
for scr in (nb2, kref):
    scr.open(CLIP12)
    seq = [scr.turn(1, c, t=40_000 + 16 * i) for i, c in enumerate((400, 400, 1200, -400, 2000, -4000, -40, 9000))]
    scr.stored(_1c9=-30)
    runs.append(({n: scr.knob(n) for n in KN12}, list(scr.texts), seq, list(scr.binds), scr.shown("BL")))
w_nb, w_ref = nb2.wave(), kref.wave()
check(f"no bank 2: the Waveform's Slip knob (BL) is stock's - its text ({nb2.text('BL')!r}, not beats.ticks), eight turns "
      f"(their posts and forwards, the value {runs[0][4]}) and every other knob, text and bind as with the knob's two hooks "
      f"taken out; the four rows bound ({[hex(runs[0][0][n]['id']) for n in KN12]})",
      runs[0] == runs[1] and nb2.text("BL") is not None and "." not in nb2.text("BL")
      and [runs[0][0][n]["id"] for n in KN12] == [0x91, 0x1C9, 0x92, 0x1CA],
      {i: (runs[0][i], runs[1][i]) for i in range(5) if runs[0][i] != runs[1][i]})
check(f"  ...no bracket where Region Auto plays [24 000, 72 000) with bank 2 (shown without it {w_nb['on']}, with it "
      f"{w_ref['on']}), and no bank-2 function entered ({len(nb2.b2_entered)})",
      w_nb["on"] == 0 and w_ref["on"] == 1 and not nb2.b2_entered, (w_nb, w_ref, sorted(set(nb2.b2_entered))))

# ---- the other modes: the screen exactly as with the three hooks taken out - Sample, Granular, Slicer, set up, zoomed,
# refreshed, and Sample after Clip (the Clip binding leaves nothing behind)
for name, steps in (("Sample", [0]), ("Granular", [3]), ("Slicer", [2]), ("Sample after Clip", [1, 0])):
    runs = []
    for scr in (Screen(), Screen(bypass=True)):
        scr.m.w32(WV + 0xC, 476)
        was = 0 if steps[0] else 1
        for mode in steps:
            scr.open({**CLIP12, 0x8B: mode}, was=was)
            was = mode
        scr.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 64.0))
        scr.msg(0x080A66DC, 0xE5)
        scr.stored(_91=30000)
        runs.append((scr.state(), list(scr.texts), list(scr.binds)))
    # after Clip, the knobs' steppers start where the Clip binding left them (stock's reset keeps a stepper), so Sample's
    # own values park them mid-step at the same index: the accumulator differs by half a step, nothing else
    strip = lambda st_: {k: ({kk: vv for kk, vv in v.items() if kk != "acc"} if k in KN12 and len(steps) > 1 else v) for k, v in st_.items()}
    acc = [(runs[0][0][n]["acc"], runs[1][0][n]["acc"], runs[0][0][n]["idx"]) for n in KN12]
    check(f"{name}: knobs, texts, binds and waveform flags as with the Waveform hooks taken out (TL {hex(runs[0][0]['TL']['id'])}, "
          f"bracket {runs[0][0]['wave']['on']})" + (f"; the steppers' accumulators parked mid-step at the same index ({acc})"
                                                     if len(steps) > 1 else ""),
          (strip(runs[0][0]), runs[0][1:]) == (strip(runs[1][0]), runs[1][1:])
          and (len(steps) == 1 or all(a // 400 == b // 400 == i for a, b, i in acc)),
          {k: (runs[0][0][k], runs[1][0][k]) for k in runs[0][0] if runs[0][0][k] != runs[1][0][k]})

# New Rec and New Multi bind nothing (stock's bind block has no branch for modes 4 and 5): after Clip the knobs keep
# these rows there, as on stock they keep Sample's after Sample. A zoom change there leaves them and the bracket alone.
for mode in (4, 5):
    nr = Screen()
    nr.open(CLIP12)
    nr.open({**CLIP12, 0x8B: mode}, was=1)
    nr.m.uc.mem_write(WV + 0x239, b"\x00")
    before = nr.state()
    nr.m.uc.mem_write(VIEW + 0x1A0, struct.pack("<f", 16.0))
    nr.msg(0x080A66DC, 0xE5)
    after = nr.state()
    check(f"{('New Rec', 'New Multi')[mode - 4]} after Clip: nothing rebound ({[hex(after[n]['id']) for n in KN12]}); a zoom change "
          f"there re-steps nothing (TL step {after['TL']['step']}) and draws no bracket ({after['wave']['on']})",
          before == after and after["TL"]["step"] == 256 and after["wave"]["on"] == 0, (before["TL"], after["TL"], after["wave"]))

print(f"{fails} failed")
sys.exit(1 if fails else 0)
