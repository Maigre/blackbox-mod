"""The scarce things inside this tree: no two modules on one of them (bench/resources.py, hub blackbox#t-056).

What is checked, on the tree this runs in (read statically: no build needed for parts 1-2 and 4):
1. the reading itself: every parameter id, store entry, block offset and allocation evaluated, every patch table
   imported, every tagged store's cap found at its sites. An id the reader could not evaluate is a FAIL, since a
   clash could hide behind it.
2. the rules: one parameter per id and one id per xml name; SDRAM parts that do not overlap (unless one is declared
   inside the other, or their #if builds exclude each other) and stay inside the block, master_block() parts inside
   the core; backup-SRAM ranges of two modules apart; no stock byte patched by two modules unless the later one's
   stock bytes are the earlier one's new bytes (a chain patch.py accepts) or a module's TAKES names the site; no
   `resources: wants` site patched by another module; each tagged store's stock entries + ours within its cap.
3. against the compiled code, when the image is built (check.sh builds it first): each registration hook and each
   store-defaults hook run under Unicorn with the stock registrars / store_add stubbed, and the ids they really
   register or add compared with what part 1 read from the sources.
4. mutants, in a temporary copy of src/, patches/ and check.sh: one per rule (a registered id taken again, directly
   and through a helper that takes the id as a parameter, an xml name taken again, an SDRAM part on another, a
   backup-SRAM word on another module's and a `shares` tag that allows it, a call site patched twice and a TAKES that
   allows it, a wanted site, a store pushed past its cap); each must fail the rule it targets, or pass it when allowed.
NOT checked: that the tags' stock facts are right (stock's own store entries, the cap sites: notes/resources.md says
how they were counted), sizes the sources do not state (a part with no budget gets the room up to the next part).
"""
import os
import re
import shutil
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import resources as R  # noqa: E402

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if not cond else ""))
    fails += not cond


stock = R.stock_image(ROOT)
man = R.scan(ROOT, ".", False, stock)

# ---- 1. the reading
check(f"{len(man['params'])} parameter registrations read, {len(man['forwarded'])} forwarding stock's own; "
      f"registrars {man['stock_api']['register']}", len(man["params"]) > 0 and man["stock_api"]["register"])
check(f"{len(man['store_adds'])} store entries read in {len(man['store_chains'])} chains behind the hooked stock store_add",
      len(man["store_adds"]) > 0 and man["store_chains"])
check(f"nothing the reader could not evaluate", not man["warnings"], man["warnings"])
check(f"{len(man['patches'])} patches read from {len({p['module'] for p in man['patches']})} patch modules, none failed",
      man["patches"] and not man["patch_errors"], man["patch_errors"])
sd = man["sdram"]
check(f"the SDRAM block: {R.h(sd['block'])} (core {R.h(sd['core'])}), {len(sd['parts'])} parts through "
      f"{sorted(sd['accessors'])}", sd["block"] and sd["parts"] and "master_block" in sd["accessors"])
check(f"{len(man['bkpsram'])} backup-SRAM ranges read", len(man["bkpsram"]) > 0)
check(f"{len(man['stores'])} tagged stores, each cap found at its sites: " +
      ", ".join(f"{s['name']} {s['stock']}+{s['added']}/{s['cap']}" for s in man["stores"]),
      man["stores"] and all(s["cap"] is not None and s["stock"] is not None for s in man["stores"]))

# ---- 2. the rules
bad = R.check_tree(man)
explain = {"param-id": "one parameter per id, every id below the registry's 500",
           "xml-name": "one id per xml name",
           "sdram": "SDRAM parts apart, inside the block; master_block() parts inside the core",
           "bkpsram": "backup-SRAM ranges of two modules apart",
           "site": "no stock byte patched by two modules (chains and TAKES aside)",
           "wants": "no planned hook site patched by another module",
           "store": "each tagged store within its cap",
           "bank1": "the cave within bank 1 (as last built)"}
for rule, text in explain.items():
    got = [t for r, t in bad if r == rule]
    check(f"{rule}: {text}", not got, got)
check("no rule outside the list above fired", not [r for r, _ in bad if r not in explain], bad)

# ---- 3. against the compiled code
IMG = os.path.join(ROOT, "out", "+".join(man["patch_sets"]), "BLACKBOX.bin")
ELF = os.path.join(ROOT, "out", "cave.elf")
if os.path.isfile(IMG) and os.path.isfile(ELF) and man["patch_sets"]:
    sys.path.insert(0, ROOT)
    from emu import STACK, Emu  # noqa: E402

    e = Emu(IMG, ELF)
    e.uc.mem_map(0x38800000, 0x1000)                 # backup SRAM
    e.uc.mem_map(0x58024000, 0x1000)                 # RCC / PWR: bkp_enable
    TABLE, NAMES, TEXT, STORE, SENT = 0x24060000, 0x24061000, 0x24062000, 0x24063000, 0x3FF
    e.uc.mem_write(TEXT, b"x\0")
    e.uc.mem_write(NAMES, struct.pack("<16I", *[TEXT] * 16))
    got = []
    for a in man["stock_api"]["register"] + man["stock_api"]["store_add"]:
        e.stub(int(a, 16), lambda: got.append(e.arg(1)))
    for kind, chains, want in (("registration", man["register_chains"], "ids"), ("store", man["store_chains"], "entries")):
        for c in chains:
            got.clear()
            for k, v in enumerate((4, TEXT, TEXT, TEXT)):
                e.w32(STACK + 4 * k, v)
            # the hook stands in for one stock call: the stock id it would forward is replaced by a sentinel
            regs = (TABLE, SENT, TEXT, NAMES) if kind == "registration" else (STORE, SENT, 0)
            try:
                e.call(c["entry"], *regs, count=5_000_000)
                ran = True
            except Exception as x:              # noqa: BLE001 - a run that faults is reported, not raised
                ran, got[:] = False, [repr(x)]
            dyn = sorted(set(i for i in got if isinstance(i, int)) - {SENT})
            static = sorted(c[want]) if kind == "registration" else sorted({x["id"] for x in c["entries"]})
            check(f"{kind} hook {c['entry']} (site {', '.join(R.h(s) for s in c['sites'])}) run: {len(dyn)} ids, "
                  f"the same as read from the sources", ran and dyn == static,
                  {"ran": ran, "only run": [R.h(i) for i in sorted(set(dyn) - set(static))],
                   "only read": [R.h(i) for i in sorted(set(static) - set(dyn))]})
else:
    print(f"PASS the compiled-code comparison is skipped: no {os.path.relpath(IMG, ROOT)} (check.sh builds it)")


# ---- 4. mutants
def copy_tree():
    d = tempfile.mkdtemp(prefix="bbres-mut-")
    for item in ("src", "patches"):
        shutil.copytree(os.path.join(ROOT, item), os.path.join(d, item), symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    if os.path.isfile(os.path.join(ROOT, "check.sh")):
        shutil.copy2(os.path.join(ROOT, "check.sh"), os.path.join(d, "check.sh"))
    return d


def mutant(name, edit, rule, expect=True):
    """rule = None: the reader must say it could not read the mutant (a warning), not stay silent"""
    d = copy_tree()
    try:
        edit(d)
        m = R.scan(d, name, False, stock)
        if rule is None:
            check(f"mutant: {name} -> not read, and said so", bool(m["warnings"]), m["warnings"])
            return
        hits = [t for r, t in R.check_tree(m) if r == rule]
        check(f"mutant: {name} -> the {rule} rule " + ("fires" if expect else "stays silent"),
              bool(hits) == expect and not m["warnings"], hits or m["warnings"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def report_mutant(name, edit_ours, edit_theirs, kind, expect=True):
    """two copies of this tree, each edited: the two-tree report must (or must not) give a row of this kind"""
    a, b = copy_tree(), copy_tree()
    try:
        edit_ours(a)
        edit_theirs(b)
        mo, mt = R.scan(a, "ours", False, stock), R.scan(b, "theirs", False, stock)
        rep = R.report(mo, mt, None, stock)
        hits = [c for c in rep["collisions"] if c["kind"] == kind]
        unread = rep["unread"]["ours"] + rep["unread"]["theirs"]
        check(f"report mutant: {name} -> " + (f"a {kind} row" if expect else f"no {kind} row"),
              bool(hits) == expect and not unread, hits or unread or [c["kind"] for c in rep["collisions"]])
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def put(d, rel, text, mode="w"):
    with open(os.path.join(d, rel), mode) as f:
        f.write(text)


REG = {int(a, 16): n for a, n in man["stock_api_names"].items()}
LIST_AT = next(a for a, ns in REG.items() if any("list" in n for n in ns) and R.h(a) in man["stock_api"]["register"])
ADD_AT = int(man["stock_api"]["store_add"][0], 16)
HEAD = ("#include <stdint.h>\n#define FN(addr) ((addr) | 1u)\n"
        "typedef void (*register_list_fn)(void *t, int p, const char *l, const char *const *n, int c, const char *x);\n"
        f"#define fw_register_list ((register_list_fn)FN({R.h(LIST_AT)}))\n"
        "typedef void (*store_add_fn)(void *store, int param, int value);\n"
        f"#define fw_store_add ((store_add_fn)FN({R.h(ADD_AT)}))\n"
        "uint8_t *master_block(void);\n")
taken = {p["id"] for p in man["params"]}
free_id = next(i for i in range(0x100, 0x1F4) if i not in taken)
p0 = man["params"][0]
mutant(f"id {R.h(p0['id'])} registered again for another parameter",
       lambda d: put(d, "src/zz_mutant.c", HEAD + f'void zz_register(void *t) {{ fw_register_list(t, {R.h(p0["id"])}, "Zz:", 0, 0, "zzmutant"); }}\n'),
       "param-id")
mutant(f"... the same through a helper that takes the id and the xml name as parameters",
       lambda d: put(d, "src/zz_mutant.c", HEAD + 'static void zz_reg(void *t, int id, const char *x) { fw_register_list(t, id, "Zz:", 0, 0, x); }\n'
                     f'void zz_register(void *t) {{ for (int k = 0; k < 2; k++) zz_reg(t, {R.h(p0["id"] - 1)} + k, "zzmutant"); }}\n'),
       "param-id")
mutant(f"xml name {p0['xml']!r} on the free id {R.h(free_id)}",
       lambda d: put(d, "src/zz_mutant.c", HEAD + f'void zz_register(void *t) {{ fw_register_list(t, {R.h(free_id)}, "Zz:", 0, 0, "{p0["xml"]}"); }}\n'),
       "xml-name")
blk = next(p for p in sd["parts"] if p["accessor"] == "master_block" and not p["nested_in"])
mutant(f"a 0x100-byte part on {blk['name']} ({R.h(blk['offset'])})",
       lambda d: put(d, "src/zz_mutant.c", HEAD + f"#define ZZ_OFFSET {R.h(blk['offset'] - sd['accessors']['master_block'])}u\n"
                     "struct zz { uint32_t w[64]; };\n_Static_assert(sizeof(struct zz) <= 0x100, \"zz\");\n"
                     "void zz_poke(void) { uint8_t *mem = master_block(); struct zz *z = (struct zz *)(mem + ZZ_OFFSET); z->w[0] = 0; }\n"),
       "sdram")
ZZ = f"#define ZZ_OFFSET {R.h(blk['offset'] - sd['accessors']['master_block'])}u\nstruct zz {{ uint32_t w[64]; }};\n"
for form, body in (
        ("passed down as a parameter (the bank-2 form), the caller handing master_block()",
         ZZ + "static void zz_dsp(uint8_t *mem) { ((struct zz *)(mem + ZZ_OFFSET))->w[0] = 0; }\n"
              "void zz_poke(void) { zz_dsp(master_block()); }\n"),
        ("handed back through a uint8_t ** out-parameter",
         ZZ + "static void zz_get(uint8_t **m) { *m = master_block(); }\n"
              "void zz_poke(void) { uint8_t *mem; zz_get(&mem); ((struct zz *)(mem + ZZ_OFFSET))->w[0] = 0; }\n"),
        ("written master_block() + offset", ZZ + "void zz_poke(void) { ((struct zz *)(master_block() + ZZ_OFFSET))->w[0] = 0; }\n"),
        ("written &mem[offset], the offset an enum",
         f"enum {{ ZZ_OFFSET = {R.h(blk['offset'] - sd['accessors']['master_block'])} }};\n"
         "void zz_poke(void) { uint8_t *mem = master_block(); *(uint32_t *)&mem[ZZ_OFFSET] = 0; }\n")):
    mutant(f"... the same part {form}", lambda d, b=body: put(d, "src/zz_mutant.c", HEAD + b), "sdram")
mutant("... a block-like offset on a pointer parameter nothing passes",
       lambda d: put(d, "src/zz_mutant.c", HEAD + ZZ + "void zz_poke(uint8_t *mem) { ((struct zz *)(mem + ZZ_OFFSET))->w[0] = 0; }\n"), None)
mutant("... the part's offset written as a literal on master_block()'s pointer",
       lambda d: put(d, "src/zz_mutant.c", HEAD + "void zz_poke(void) { uint8_t *mem = master_block(); "
                     f"*(uint32_t *)(mem + {R.h(blk['offset'] - sd['accessors']['master_block'] + 0x10)}u) = 0; }}\n"), None)
bk = man["bkpsram"][0]
mutant(f"a backup-SRAM word on {bk['file']}'s {R.h(bk['start'])}",
       lambda d: put(d, "src/zz_mutant.c", HEAD + f"#define ZZ_WORD (*(volatile uint32_t *){R.h(bk['start'])}u)\n"
                     "void zz_poke(void) { ZZ_WORD = 0; }\n"),
       "bkpsram")
mutant(f"... the same, a `resources: shares` tag naming both modules",
       lambda d: put(d, "src/zz_mutant.c", HEAD + f"#define ZZ_WORD (*(volatile uint32_t *){R.h(bk['start'])}u)\n"
                     f"/* resources: shares at={R.h(bk['start'])} with=zz_mutant,{bk['module']} */\n"
                     "void zz_poke(void) { ZZ_WORD = 0; }\n"),
       "bkpsram", expect=False)
sr = next(r for r in man["bkpsram"] if r["types"] and r["end"] - r["start"] >= 8)
BKP = (f"#define ZZ_BKP {R.h(R.BKP_LO)}u\n"
       f"#define ZZ_W (*(volatile uint32_t *)(ZZ_BKP + {R.h(sr['start'] + 4 - R.BKP_LO)}u))\n")
mutant(f"a backup-SRAM word inside {sr['file']}'s {sr['types'][0]}, written as a base macro + offset",
       lambda d: put(d, "src/zz_mutant.c", HEAD + BKP + "void zz_poke(void) { ZZ_W = 0; }\n"), "bkpsram")
mutant(f"... the same base macro + a variable offset",
       lambda d: put(d, "src/zz_mutant.c", HEAD + "#define ZZ_BKP 0x38800000u\n"
                     "void zz_poke(int i) { *(volatile uint32_t *)(ZZ_BKP + 4u * i) = 0; }\n"), None)
# a free gap of the reader's map, behind a range whose size is known: both trees claim it
rs = sorted(man["bkpsram"], key=lambda r: r["start"])
gap = next(R.h((x["end"] + 0xf) & ~0xf) for x, y in zip(rs, rs[1:]) if x["from"] != "cast" and y["start"] - ((x["end"] + 0xf) & ~0xf) >= 0x40)


def claim(fname, struct, macro, member):
    return lambda d: put(d, f"src/{fname}.c", HEAD + f"struct {struct} {{ {member}[16]; }};\n"
                         f"#define {macro} ((volatile struct {struct} *){gap}u)\n"
                         f"_Static_assert({gap}u + sizeof(struct {struct}) <= {gap}u + 0x40u, \"{struct}\");\n"
                         f"void {fname}_poke(void) {{ {macro}->w[0] = 0; }}\n")


report_mutant(f"each tree's own module on the free backup SRAM at {gap}, one range in both",
              claim("zz_ours", "zza", "ZZA", "uint32_t w"), claim("zz_theirs", "zzb", "ZZB", "float w"), "bkpsram")
report_mutant(f"... the same structure in another file on the other side (code moved)",
              claim("zz_ours", "zza", "ZZA", "uint32_t w"), claim("zz_moved", "zza", "ZZA", "uint32_t w"), "bkpsram",
              expect=False)
call = next(p for p in man["patches"] if p["applied"] and p["kind"] == "call" and p["callee"])


def site_mutant(takes):
    def edit(d):
        put(d, "patches/zz_mutant.py", "import os\nfrom thumb import ROOT, bl, symbols\n"
            "sym = symbols(os.path.join(ROOT, 'out', 'cave.elf'))\n"
            f"PATCHES = [({R.h(call['addr'])}, bl({R.h(call['addr'])}, {R.h(call['callee'])}), bl({R.h(call['addr'])}, sym['zz_hook']))]\n"
            + (f"TAKES = [{R.h(call['addr'])}]\n" if takes else ""))
        s = open(os.path.join(d, "check.sh")).read()
        put(d, "check.sh", re.sub(r"(patch\.py\s+[\w ]*?)(\s+cave\b|\s*$)", r"\1 zz_mutant\2", s, count=1, flags=re.M))
    return edit


mutant(f"site {R.h(call['addr'])} ({call['module']}.py) patched again by another module", site_mutant(False), "site")
mutant(f"... the same, the other module's TAKES naming the site", site_mutant(True), "site", expect=False)
mutant(f"a planned hook on {R.h(call['addr'])}",
       lambda d: put(d, "src/zz_mutant.c", HEAD + f"/* resources: wants site={R.h(call['addr'])} callee={R.h(call['callee'])} by=zz */\n"),
       "wants")
st = next((s for s in man["stores"] if s["entry_functions"] and s["cap"] is not None and s["stock"] is not None), None)
room = st["cap"] - st["stock"] - st["added"] + 1 if st else 0


def store_mutant(d):
    fn = st["entry_functions"][0]
    for f in sorted(os.listdir(os.path.join(d, "src"))):
        if not f.endswith((".c", ".cpp")):
            continue
        p = os.path.join(d, "src", f)
        s = open(p).read()
        m = re.search(r"\b" + fn + r"\s*\(\s*[\w\s\*]*?(\w+)\s*[,)][^{;]*\{", s)
        if m:
            s = s[:m.end()] + f" zz_more({m.group(1)});" + s[m.end():]
            open(p, "w").write("void zz_more(void *store);\n" + s)
            break
    free = [i for i in range(0x100, 0x1F4) if i not in taken][:room]
    put(d, "src/zz_mutant.c", HEAD + "void zz_more(void *store) {\n" +
        "".join(f"    fw_store_add(store, {R.h(i)}, 0);\n" for i in free) + "}\n")


if st:
    mutant(f"{room} more entries in the {st['name']} store ({st['stock']} + {st['added']} of {st['cap']})", store_mutant, "store")
else:
    check("mutant: a store pushed past its cap (needs a tagged store)", False)
# another stock bl store_add near a tagged one, hooked: no tag names its site, so no cap would count its entries
tagged = {a for tg in man["tags"] if tg["kind"] == "store" for a in tg.get("sites", [])}
patched = {a for p in man["patches"] for a in range(p["addr"], p["end"])}
near = sorted(tagged)[0] if tagged else None
other = next((a for a in range(near - 0x200, near + 0x200, 2) if a not in tagged and a not in patched and
              (R.decode_bl(stock[a - R.FLASH:a - R.FLASH + 4], a) or (None, None)) == ("bl", ADD_AT)), None) \
    if near and stock else None


def untagged_mutant(d):
    put(d, "patches/zz_mutant.py", "import os\nfrom thumb import ROOT, bl, symbols\n"
        "sym = symbols(os.path.join(ROOT, 'out', 'cave.elf'))\n"
        f"PATCHES = [({R.h(other)}, bl({R.h(other)}, {R.h(ADD_AT)}), bl({R.h(other)}, sym['zz_defaults']))]\n")
    s = open(os.path.join(d, "check.sh")).read()
    put(d, "check.sh", re.sub(r"(patch\.py\s+[\w ]*?)(\s+cave\b|\s*$)", r"\1 zz_mutant\2", s, count=1, flags=re.M))
    put(d, "src/zz_mutant.c", HEAD + "void zz_defaults(void *store) {\n" +
        "".join(f"    fw_store_add(store, {R.h(i)}, 0);\n" for i in [i for i in range(0x100, 0x1F4) if i not in taken][:3]) + "}\n")


if other:
    mutant(f"the stock store_add at {R.h(other)} (beside the tagged {R.h(near)}) hooked, its site in no tag", untagged_mutant, "store")
else:
    check("mutant: an untagged stock store_add hooked (needs the stock image and a tagged store)", False)

print(f"{fails} failed")
sys.exit(1 if fails else 0)
