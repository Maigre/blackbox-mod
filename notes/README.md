# notes/ — the working docs of Thomas's fork

This folder lives on the fork's own branches (`maigre` and the feature branches stacked on it). It is the project
workspace: the plan, the reverse-engineering findings, the decisions, the feature docs, the bench reports. It is
**never** part of an upstream pull request (the `fix/*` and `feat/*` branches cut from j3threejay/blackbox-mod `main`).

What goes here: prose. Addresses and struct offsets as the C comments cite them (`FUN_0808c0d8`, `pad+0x24`),
formulas, test recipes, bench results.

What never goes here (upstream's request, README "What is and isn't in this repository"): 1010music's firmware or
patched images, `BBEXTRA.BIN`, decompiled or disassembled listings, Ghidra projects or exports, 1010music's manuals or
artwork. Those stay on the dev box under `/srv/dev/firmware/` (outside every clone).

- [`plan.md`](plan.md) — the plan: the two deliverables, the design, the RE plan, the phases, the PR strategy.
- [`decisions.md`](decisions.md) — dated decisions (D-001 …) with their reasons; newest first.
- [`dev-setup.md`](dev-setup.md) — building, testing and Ghidra on Linux without root.
- [`re/`](re/README.md) — the reverse-engineering notes (A0–A7, X1–X3) and the hand-off index (`re/README.md`).
- `features/` — one doc per feature: what it does on the unit, how it is implemented, how to bench it:
  [`features/clip-window.md`](features/clip-window.md) (Slip, Region, Loop Len, the Clip-mode Waveform knobs).
- `bench/` — reports of the bench gates on the unit (what was measured, with which build).

The hub side (tasks, bench cards, the project log) is `37Projects/projects/blackbox/`. The fork's overview is
[`../FORK.md`](../FORK.md).
