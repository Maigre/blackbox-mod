# notes/ — the working docs of Thomas's fork

This folder lives on the `thomas` branch only. It is the project workspace: the plan, the
reverse-engineering findings, the workflows, the decisions. It is **never** part of a `feat/*`
branch or a pull request to upstream (j3threejay/blackbox-mod).

What goes here: prose. Addresses and struct offsets as the C comments cite them (`FUN_0808c0d8`,
`pad+0x24`), formulas, test recipes, bench results.

What never goes here (upstream's request, README "What is and isn't in this repository"):
1010music's firmware or patched images, `BBEXTRA.BIN`, decompiled or disassembled listings, Ghidra
projects or exports, 1010music's manuals or artwork. Those stay on dev37 under `/srv/dev/firmware/`.

- `plan.md` — the plan (two deliverables, design, RE plan, phases, PR strategy).
- `re/` — one file per RE step (A0 … A7), written as the findings come.
- `workflows.md` — the workflows as performed on the unit; becomes `LOOPER.md` at P5.
- `decisions.md` — dated decisions with their reasons.
- `features/` — one file per feature of the fork as built: what it does on the unit, the controls, how it is
  implemented, what is not done, how to bench it (`looper.md`: P4).

The hub side (tasks, bench cards, log) is `37Projects/projects/blackbox/`.
