#!/usr/bin/env python3
"""What each module of a blackbox-mod tree takes of the scarce things, and where two trees collide (hub blackbox#t-056).

  python3 bench/resources.py scan [TREE] [--build] [--md FILE] [--json FILE]
  python3 bench/resources.py report OURS THEIRS [--base REF] [--build] [--md FILE] [--json FILE]
  python3 bench/resources.py check [TREE]          the in-tree rules test_resources.py runs, as a list

TREE, OURS, THEIRS, REF: a folder (a checkout, a worktree) or a git ref of the repository this script lives in
(`upstream/main`, `maigre`, a sha), which is unpacked with `git archive` into a temporary folder. Both trees are only
read: `--build` builds a copy of each in a temporary folder, never in the tree.

Exit status: 0 clean, 1 a collision or a problem, 2 something not read (an id, a pointer, a patch table): a clash
can hide there, so the console line counts it and an unread tree never reads as clean.

What is read, and from where (notes/resources.md has the long form):
- parameter ids: every call to a binding of the stock registrars (a macro of src/*.c bound to a stock address and
  named *regist*), directly, through a helper or a function-like macro, its id evaluated from the file's #defines,
  enums, loops and const arrays; the xml name says which parameter it is. Where ids are read: the calls of a
  binding named *setting* (fw_setting).
- stock functions called: every macro binding one with FN() / B2_FN(); the report flags one whose first bytes the
  other tree patches.
- store entries: every call to a binding named *store_add*, in the functions reached from the stock call sites the
  patch tables hook in place of a stock store_add; the stores, their caps and stock's own count come from
  `resources: store` tags (patches/duck.py, patches/comp.py) because nothing else states them.
- the boot-time SDRAM block: master.c's allocation (a binding named *perm_alloc*), its accessors (master_block,
  master_tail, prism_mem), and every `p + NAME` / `&p[NAME]` in src/ whose pointer p is traced to an accessor (an
  assignment, the callers of a parameter, an out-parameter, a macro); a part's size is its STEM_BYTES, else the
  smallest sizeof(struct) budget a _Static_assert gives it, else the room up to the next part.
- backup SRAM: pointer casts whose operand evaluates (macros included) into 0x38800000..0x38800fff, and the
  _Static_asserts that bound them.
- patch RAM (the 172-byte gap 0x2405FF54..0x2405FFFF above the heap, src/solo.c): read the same way, and `.S` `.equ`
  words. A word nothing in src/ states (bench/b2split.py's dispatcher vector) comes from a `resources: ram at=..
  size=..` tag; a share in a source this fork does not edit (JOEBOX's) from bench/resources.tags.
- patched stock bytes: each patches/*.py module is imported with a stand-in symbol table (no build needed), so every
  (site, stock bytes, new bytes) is known; a BL's target is read back as its symbol name. Page slots and caps are
  data patches like any other.
- planned hooks no patch table states yet: `resources: wants site=... callee=... by=...` tags.
- with a build: bank-1 bytes per object (out/cave.map) and the bank-2 size.
"""
import argparse
import ast
import atexit
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_SHA256 = "281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d"
FLASH = 0x08040000                    # where the stock image starts
FAKE_BASE, FAKE_SPAN = 0x08800000, 0x00800000   # stand-in symbol addresses: past bank 2, inside a BL's reach
BKP_LO, BKP_HI = 0x38800000, 0x38801000
PATCH_LO, PATCH_HI = 0x2405FF54, 0x24060000       # patch RAM: the heap's end to the MPU regions (src/solo.c)


def h(v):
    return f"0x{v:x}" if isinstance(v, int) else str(v)


# --------------------------------------------------------------------------------------------------------- trees

_tmp = []


def _cleanup():
    for d in _tmp:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup)


def tmpdir(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    _tmp.append(d)
    return d


def open_tree(arg, repo=ROOT):
    """(path, label): a folder as it is, or a ref unpacked from the repository with git archive."""
    if os.path.isdir(arg):
        p = os.path.abspath(arg)
        sha = subprocess.run(["git", "-C", p, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", p, "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                               text=True).stdout.strip()
        return p, f"{arg} ({sha}{', modified' if dirty else ''})" if sha else arg
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--short", f"{arg}^{{commit}}"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"resources.py: {arg!r} is neither a folder nor a ref of {repo}")
    d = tmpdir("bbres-")
    arch = subprocess.Popen(["git", "-C", repo, "archive", arg], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", d], stdin=arch.stdout, check=True)
    arch.wait()
    return d, f"{arg} ({r.stdout.strip()})"


def stock_image(*trees):
    for p in [os.path.join(t, "firmware", "BLACKBOX-3.1.9.bin") for t in trees] + [
            os.path.join(ROOT, "firmware", "BLACKBOX-3.1.9.bin"), os.environ.get("BB_STOCK", ""),
            "/srv/dev/firmware/BLACKBOX-3.1.9.bin"]:
        if p and os.path.isfile(p):
            data = open(p, "rb").read()
            if hashlib.sha256(data).hexdigest() == STOCK_SHA256:
                return data
    return None


# ------------------------------------------------------------------------------------------------------ C reader

_LEX = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case", "_Static_assert", "defined",
             "__asm__", "asm", "static_assert"}


def lex(text):
    """(code, blank, comments): comments blanked out (lines kept); in blank the strings' insides too."""
    code, blank, comments, pos = [], [], [], 0
    for m in _LEX.finditer(text):
        code.append(text[pos:m.start()])
        blank.append(text[pos:m.start()])
        s = m.group()
        if s[0] == "/":
            comments.append((text.count("\n", 0, m.start()) + 1, s))
            sp = re.sub(r"[^\n]", " ", s)
            code.append(sp)
            blank.append(sp)
        else:
            code.append(s)
            blank.append(s[0] + " " * (len(s) - 2) + s[-1])
        pos = m.end()
    code.append(text[pos:])
    blank.append(text[pos:])
    return "".join(code), "".join(blank), comments


def match_close(s, i):
    """s[i] is ( [ or {: the index of its partner (strings already blanked)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[s[i]]]
    j = i + 1
    while j < len(s) and stack:
        c = s[j]
        if c in pairs:
            stack.append(pairs[c])
        elif c in ")]}":
            if c == stack[-1]:
                stack.pop()
        j += 1
    return j - 1


def split_top(code, blank, a, b, sep=","):
    """split code[a:b] at depth-0 separators (found in blank)"""
    out, depth, start = [], 0, a
    for j in range(a, b):
        c = blank[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == sep and depth == 0:
            out.append(code[start:j].strip())
            start = j + 1
    out.append(code[start:b].strip())
    return out


class Func:
    def __init__(self, name, a, b, params, line):
        self.name, self.a, self.b, self.params, self.line = name, a, b, params, line


class CFile:
    """One source file: its macros, enums, const arrays, functions and preprocessor conditions."""

    def __init__(self, tree, rel):
        self.tree, self.rel = tree, rel
        self.raw = open(os.path.join(tree.path, rel), encoding="utf-8", errors="replace").read()
        code, blank, self.comments = lex(self.raw)
        self.code_pp = code                   # comments out, preprocessor lines kept (macro bodies)
        self.macros, self.fmacros, self.includes, self.exclusive, self.fparams = {}, {}, [], [], {}
        lines_c, lines_b = code.split("\n"), blank.split("\n")
        self.conds = []                       # per line (0-based): the #if conditions it sits under
        stack, dead = [], 0
        i = 0
        while i < len(lines_c):
            line = lines_c[i]
            st = line.strip()
            self.conds.append(tuple(c for c in stack if c))
            if st.startswith("#"):
                full, k = st, i
                while full.endswith("\\") and k + 1 < len(lines_c):
                    k += 1
                    full = full[:-1] + " " + lines_c[k].strip()
                    self.conds.append(tuple(c for c in stack if c))
                d = re.match(r"#\s*(\w+)\s*(.*)", full)
                kw, rest = (d.group(1), d.group(2).strip()) if d else ("", "")
                if kw in ("if", "ifdef", "ifndef"):
                    if dead or (kw == "if" and rest in ("0",)):
                        dead += 1
                        stack.append("")
                    else:
                        stack.append(rest if kw == "ifdef" else "!" + rest if kw == "ifndef" else rest)
                elif kw == "elif":
                    if stack:
                        stack[-1] = "elif " + rest
                elif kw == "else":
                    if dead and stack and stack[-1] == "":
                        dead -= 1
                        stack[-1] = "!0"
                    elif stack:
                        stack[-1] = ("!" + stack[-1]) if not stack[-1].startswith("!") else stack[-1][1:]
                elif kw == "endif":
                    if stack:
                        if stack[-1] == "" and dead:
                            dead -= 1
                        stack.pop()
                elif kw == "define" and not dead:
                    m = re.match(r"(\w+)(\([^)]*\))?\s*(.*)", rest)
                    if m:
                        (self.fmacros if m.group(2) else self.macros).setdefault(
                            m.group(1), (m.group(3).strip(), i + 1, tuple(c for c in stack if c)))
                        if m.group(2):
                            self.fparams.setdefault(m.group(1), [x.strip() for x in m.group(2)[1:-1].split(",")])
                elif kw == "include" and not dead:
                    m = re.match(r'"([^"]+)"', rest)
                    if m:
                        self.includes.append(m.group(1))
                elif kw == "error" and not dead:
                    # an #error under two flags: the builds exclude each other (CPU_PROF and SLICE_DIAG)
                    pos_flags = [c for c in stack if re.fullmatch(r"\w+", c or "")]
                    self.exclusive += [frozenset((a, b)) for a in pos_flags for b in pos_flags if a < b]
                for j in range(i, k + 1):
                    lines_c[j] = " " * len(lines_c[j])
                    lines_b[j] = " " * len(lines_b[j])
                i = k + 1
                continue
            if dead:
                lines_c[i] = " " * len(line)
                lines_b[i] = " " * len(lines_b[i])
            i += 1
        self.code, self.blank = "\n".join(lines_c), "\n".join(lines_b)
        self.enums = {}
        for m in re.finditer(r"\benum\b[^{;()]*\{", self.blank):
            e = match_close(self.blank, m.end() - 1)
            v = 0
            for item in split_top(self.code, self.blank, m.end(), e):
                mm = re.match(r"(\w+)\s*(?:=\s*(.+))?$", item.strip(), re.S)
                if not mm:
                    continue
                if mm.group(2):
                    try:
                        v = self.eval(mm.group(2), {})
                    except Unresolved:
                        continue
                self.enums[mm.group(1)] = v
                v += 1
        self.funcs = self._functions()
        self.arrays = []                      # (pos, name, nested list of element strings)
        for m in re.finditer(r"\b(\w+)\s*((?:\[[^\]\n]*\]\s*)+)=\s*\{", self.blank):
            e = match_close(self.blank, m.end() - 1)
            self.arrays.append((m.start(), m.group(1), self._init_list(m.end() - 1, e)))

    def line(self, pos):
        return self.code.count("\n", 0, pos) + 1

    def cond(self, pos):
        n = self.line(pos) - 1
        return self.conds[n] if n < len(self.conds) else ()

    def _init_list(self, a, b):
        out = []
        for part, (s, e) in self._split_spans(a + 1, b):
            if self.blank[s:e].lstrip().startswith("{"):
                o = s + self.blank[s:e].index("{")
                out.append(self._init_list(o, match_close(self.blank, o)))
            else:
                out.append(part)
        return out

    def _split_spans(self, a, b):
        out, depth, start = [], 0, a
        for j in range(a, b + 1):
            c = self.blank[j] if j < b else ","
            if j < b and c in "([{":
                depth += 1
            elif j < b and c in ")]}":
                depth -= 1
            elif c == "," and depth == 0:
                if self.code[start:j].strip():
                    out.append((self.code[start:j].strip(), (start, j)))
                start = j + 1
        return out

    def _functions(self):
        funcs, depth, i, s = [], [], 0, self.blank
        transparent = 0
        while i < len(s):
            c = s[i]
            if c == "{":
                if not depth:
                    k = i - 1
                    while k >= 0 and s[k] not in ";{}":
                        k -= 1
                    head = s[k + 1:i].strip()
                    if re.search(r'extern\s+"\s*"$', head) or head.endswith('extern "C"'):
                        transparent += 1
                        i += 1
                        continue
                    if head.endswith(")") and "=" not in head.split("(")[0]:
                        o = len(head) - 1
                        dep = 0
                        while o >= 0:
                            if head[o] == ")":
                                dep += 1
                            elif head[o] == "(":
                                dep -= 1
                                if dep == 0:
                                    break
                            o -= 1
                        nm = re.search(r"(\w+)\s*$", head[:o])
                        if nm and nm.group(1) not in _KEYWORDS:
                            e = match_close(s, i)
                            params = []
                            for p in head[o + 1:-1].split(","):
                                pm = re.search(r"(\w+)\s*(?:\[[^\]]*\])?\s*\)?\s*(?:\([^)]*\))?\s*$", p.strip())
                                if pm and pm.group(1) not in ("void",):
                                    params.append(pm.group(1))
                            funcs.append(Func(nm.group(1), i, e, params, self.line(i)))
                            i = e + 1
                            continue
                depth.append(i)
                i = match_close(s, i) + 1
                depth.pop()
                continue
            if c == "}" and transparent:
                transparent -= 1
            i += 1
        return funcs

    def func_at(self, pos):
        for f in self.funcs:
            if f.a <= pos <= f.b:
                return f
        return None

    # ---- names visible here: own + included headers (recursively)
    def visible(self, attr, seen=None):
        seen = seen or set()
        if self.rel in seen:
            return {}
        seen.add(self.rel)
        out = {}
        for inc in self.includes:
            f = self.tree.header(self.rel, inc)
            if f:
                out.update(f.visible(attr, seen))
        out.update(getattr(self, attr))
        return out

    def macro_map(self):
        if not hasattr(self, "_mm"):
            self._mm = self.visible("macros")
            self._en = self.visible("enums")
        return self._mm

    def array(self, name, pos):
        best = None
        fn = self.func_at(pos) if pos is not None else None
        for p, n, v in self.arrays:
            if n != name:
                continue
            if fn and fn.a <= p <= fn.b:
                return v
            if not self.func_at(p):
                best = v
        return best

    # ---- expressions
    def eval(self, expr, env, pos=None, depth=0):
        return CEval(self, env, pos).value(expr, depth)

    def string(self, expr, env, pos=None):
        expr = expr.strip()
        lits = re.findall(r'"((?:\\.|[^"\\])*)"', expr)
        if lits and re.fullmatch(r'(\s*"(?:\\.|[^"\\])*"\s*)+', expr):
            return "".join(lits)
        m = re.fullmatch(r"(\w+)((?:\s*\[[^\]]+\])+)", expr)
        if m:
            arr = self.array(m.group(1), pos)
            for idx in re.findall(r"\[([^\]]+)\]", m.group(2)):
                if not isinstance(arr, list):
                    return None
                try:
                    arr = arr[CEval(self, env, pos).value(idx)]
                except (Unresolved, IndexError):
                    return None
            return self.string(arr, env, pos) if isinstance(arr, str) else None
        mm = self.macro_map().get(expr)
        if mm:
            return self.string(mm[0], env, pos)
        return None


class Unresolved(Exception):
    pass


_SUFFIX = re.compile(r"\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]+\b")
_TYPE = r"(?:u?int(?:8|16|32|64)_t|int|unsigned|long|short|char|size_t|signed|uintptr_t)"
_CAST = re.compile(r"\(\s*(?:(?:const|volatile)\s+)*" + _TYPE + r"(?:\s+" + _TYPE + r")*\s*\)")


class CEval(ast.NodeVisitor):
    def __init__(self, f, env, pos):
        self.f, self.env, self.pos = f, env, pos

    def value(self, expr, depth=0):
        if depth > 20:
            raise Unresolved("macro depth")
        self.depth = depth
        s = _CAST.sub(" ", _SUFFIX.sub(r"\1", expr.strip())).strip()
        s = s.replace("&&", " and ").replace("||", " or ")
        s = re.sub(r"!(?!=)", " not ", s)
        try:
            tree = ast.parse(s, mode="eval")
        except SyntaxError:
            raise Unresolved(expr)
        return self.visit(tree.body)

    def visit_Constant(self, n):
        if isinstance(n.value, int):
            return n.value
        raise Unresolved(repr(n.value))

    def visit_Name(self, n):
        if n.id in self.env:
            return self.env[n.id]
        mm = self.f.macro_map()
        if n.id in mm:
            return CEval(self.f, self.env, self.pos).value(mm[0] if False else mm[n.id][0], self.depth + 1)
        if n.id in self.f._en:
            return self.f._en[n.id]
        raise Unresolved(n.id)

    def visit_BinOp(self, n):
        a, b = self.visit(n.left), self.visit(n.right)
        ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b,
               ast.Div: lambda: int(a / b), ast.FloorDiv: lambda: a // b, ast.Mod: lambda: a % b,
               ast.LShift: lambda: a << b, ast.RShift: lambda: a >> b, ast.BitOr: lambda: a | b,
               ast.BitAnd: lambda: a & b, ast.BitXor: lambda: a ^ b}
        if type(n.op) not in ops:
            raise Unresolved("op")
        return ops[type(n.op)]()

    def visit_UnaryOp(self, n):
        v = self.visit(n.operand)
        if isinstance(n.op, ast.USub):
            return -v
        if isinstance(n.op, ast.UAdd):
            return v
        if isinstance(n.op, ast.Invert):
            return ~v & 0xFFFFFFFF
        if isinstance(n.op, ast.Not):
            return int(not v)
        raise Unresolved("unary")

    def visit_Subscript(self, n):
        idx = []
        node = n
        while isinstance(node, ast.Subscript):
            idx.insert(0, self.visit(node.slice))
            node = node.value
        if not isinstance(node, ast.Name):
            raise Unresolved("subscript")
        arr = self.f.array(node.id, self.pos)
        for i in idx:
            if not isinstance(arr, list) or i >= len(arr):
                raise Unresolved(node.id)
            arr = arr[i]
        if isinstance(arr, list):
            raise Unresolved(node.id)
        return CEval(self.f, self.env, self.pos).value(arr, self.depth + 1)

    def visit_Index(self, n):            # Python < 3.9
        return self.visit(n.value)

    def generic_visit(self, n):
        raise Unresolved(type(n).__name__)


def probe(f, exprs):
    """values the compiler gives for C expressions in file f's context (sizeof included), or {} without a
    toolchain or when the file does not compile on its own here; the tree is only read"""
    gcc = shutil.which("arm-none-eabi-g++" if f.rel.endswith(".cpp") else "arm-none-eabi-gcc")
    if not gcc or not exprs:
        return {}
    dig, seen, todo = hashlib.sha1(), set(), [f]
    while todo:                                          # the file and every header it pulls in, by content
        g = todo.pop()
        if g.rel in seen:
            continue
        seen.add(g.rel)
        dig.update(g.rel.encode() + g.raw.encode())
        todo += [x for x in (f.tree.header(g.rel, i) for i in g.includes) if x]
    key = (f.rel, dig.hexdigest(), tuple(sorted(exprs)))
    if key in _probed:
        return _probed[key]
    _probed[key] = out = _probe(f, gcc, sorted(exprs))
    return out


_probed = {}


def _probe(f, gcc, exprs):
    d = tmpdir("bbres-probe-")
    src = os.path.join(d, os.path.basename(f.rel))
    exprs = list(exprs)
    body = ", ".join(f"(unsigned)({e})" for e in exprs)
    open(src, "w").write(f.raw + f'\n{"extern \"C\" " if f.rel.endswith(".cpp") else ""}const unsigned __bbres_probe[] = {{{body}}};\n')
    obj, out = os.path.join(d, "p.o"), os.path.join(d, "p.bin")
    sdir = os.path.join(f.tree.path, os.path.dirname(f.rel))
    flags = ["-mcpu=cortex-m7", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv5-d16", "-Os", "-ffreestanding", "-nostdlib",
             "-fdata-sections", "-w", "-DB2_ID=0", "-DB2LOAD_WRITE=1", "-iquote", sdir, "-I", sdir,
             "-isystem", os.path.join(sdir, "munchi", "sys")]
    r = subprocess.run([gcc] + flags + ["-c", "-o", obj, src], capture_output=True, text=True)
    if r.returncode:
        return {}
    r = subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".rodata.__bbres_probe", obj, out],
                       capture_output=True)
    if r.returncode or not os.path.isfile(out):
        return {}
    raw = open(out, "rb").read()
    return {e: int.from_bytes(raw[4 * i:4 * i + 4], "little") for i, e in enumerate(exprs) if 4 * i + 4 <= len(raw)}


class Tree:
    def __init__(self, path, label):
        self.path, self.label = path, label
        self.files = {}
        src = os.path.join(path, "src")
        for fn in sorted(os.listdir(src)) if os.path.isdir(src) else []:
            if fn.endswith((".c", ".cpp", ".h", ".inc")):
                self.files["src/" + fn] = CFile(self, "src/" + fn)

    def header(self, frm, inc):
        rel = os.path.normpath(os.path.join(os.path.dirname(frm), inc))
        if rel not in self.files and os.path.isfile(os.path.join(self.path, rel)) and rel.startswith("src/") \
                and rel.count("/") == 1:
            self.files[rel] = CFile(self, rel)
        return self.files.get(rel)

    def sources(self):
        return [f for r, f in self.files.items() if r.endswith((".c", ".cpp"))]


def module_of(rel):
    b = os.path.basename(rel)
    b = re.sub(r"\.(c|cpp|h|S|py|inc)$", "", b)
    return re.sub(r"_(thunk|b2|dsp|room|coef|img|stock_names|palettes)$", "", b)


# ------------------------------------------------------------------------------------------------- loops and calls

def loops_at(f, fn, pos):
    """[(var, [values])] of the for-loops around pos inside fn, outermost first"""
    out = []
    for m in re.finditer(r"\bfor\s*\(", f.blank[fn.a:fn.b]):
        o = fn.a + m.end() - 1
        c = match_close(f.blank, o)
        parts = split_top(f.code, f.blank, o + 1, c, ";")
        if len(parts) != 3:
            continue
        j = c + 1
        while j < fn.b and f.blank[j].isspace():
            j += 1
        end = match_close(f.blank, j) if f.blank[j] == "{" else _stmt_end(f, j, fn.b)
        if not (j <= pos <= end):
            continue
        im = re.match(r"(?:[\w\s\*]*?\s)?(\w+)\s*=\s*(.+)$", parts[0], re.S)
        # the bound: `i < N`, or one `&&` conjunct of that form (`site == 1 && i < N`: at most those values)
        conj = [c.strip() for c in parts[1].split("&&")] if "||" not in parts[1] else [parts[1]]
        cm = next((x for x in (re.match(r"(\w+)\s*(<=|<|!=)\s*(.+)$", c, re.S) for c in conj)
                   if x and im and x.group(1) == im.group(1)), None)
        if not im or not cm or im.group(1) != cm.group(1) or not re.fullmatch(r"\w+\s*\+\+|\+\+\s*\w+|\w+\s*\+=\s*1", parts[2]):
            out.append((im.group(1) if im else "?", None))
            continue
        try:
            a = f.eval(im.group(2), {}, pos)
            b = f.eval(cm.group(3), {}, pos) + (1 if cm.group(2) == "<=" else 0)
            out.append((im.group(1), list(range(a, b))))
        except Unresolved:
            out.append((im.group(1), None))
    return out


def _stmt_end(f, j, limit):
    m = re.match(r"(for|while|if)\s*\(", f.blank[j:])
    if m:
        c = match_close(f.blank, j + m.end() - 1)
        k = c + 1
        while k < limit and f.blank[k].isspace():
            k += 1
        return match_close(f.blank, k) if f.blank[k] == "{" else _stmt_end(f, k, limit)
    depth = 0
    for k in range(j, limit):
        c = f.blank[k]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return k
    return limit


def envs(loops):
    combos = [{}]
    for var, vals in loops:
        if vals is None:
            return None
        combos = [dict(c, **{var: v}) for c in combos for v in vals]
    return combos


def calls(f, names):
    """(name, fn, pos, args) for every call of one of names inside a function of f"""
    if not names:
        return
    rx = re.compile(r"\b(" + "|".join(map(re.escape, sorted(names))) + r")\s*\(")
    for fn in f.funcs:
        for m in rx.finditer(f.blank, fn.a, fn.b):
            o = m.end() - 1
            c = match_close(f.blank, o)
            yield m.group(1), fn, m.start(), split_top(f.code, f.blank, o + 1, c)


# ------------------------------------------------------------------------------------------------------ patches

_LOADER = r'''
import importlib, json, os, re, sys, zlib
sys.dont_write_bytecode = True
tree, fakeroot, real = sys.argv[1], sys.argv[2], sys.argv[3]
real = set(json.loads(real)) if real != "-" else None
FAKE_BASE, FAKE_SPAN = %d, %d
class Syms(dict):
    rev = {}
    def __missing__(self, k):
        a = FAKE_BASE + (zlib.crc32(k.encode()) %% (FAKE_SPAN // 8)) * 8
        while a in Syms.rev and Syms.rev[a] != k:
            a += 8
        Syms.rev[a] = k
        self[k] = a
        return a
    def __contains__(self, k):
        return k in real if real is not None else True
pdir = os.path.join(tree, "patches")
sys.path.insert(0, pdir)
import thumb
fake = Syms()
thumb.symbols = lambda elf: fake
thumb.ROOT = fakeroot
mods, errors = {}, {}
for fn in sorted(os.listdir(pdir)):
    if not fn.endswith(".py") or fn == "thumb.py":
        continue
    name = fn[:-3]
    try:
        m = importlib.import_module(name)
    except BaseException as e:
        errors[name] = repr(e)[:300]
        continue
    if isinstance(getattr(m, "PATCHES", None), (list, tuple)):
        mods[name] = m
holders = {}
for name, m in mods.items():
    for t in m.PATCHES:
        holders.setdefault(id(t), []).append(name)
imports = {}
for name in mods:
    src = open(os.path.join(pdir, name + ".py")).read()
    imports[name] = set(re.findall(r"^\s*from\s+(\w+)\s+import", src, re.M)) | set(re.findall(r"^\s*import\s+(\w+)", src, re.M))
out = []
for name, m in mods.items():
    for t in m.PATCHES:
        hs = holders[id(t)]
        owner = [x for x in hs if not (imports[x] & (set(hs) - {x}))] or hs
        if owner[0] != name:
            continue
        addr, old, new = t
        pos = {x: next(k for k, u in enumerate(mods[x].PATCHES) if u is t) for x in hs}
        out.append(dict(module=name, sets=hs, pos=pos, addr=addr, old=bytes(old).hex(), new=bytes(new).hex()))
takes = {}
for name, m in mods.items():
    t = getattr(m, "TAKES", None)
    if t is None:
        continue
    if isinstance(t, dict):
        t = list(t.keys())
    takes[name] = [x if isinstance(x, int) else x[0] for x in t]
print(json.dumps(dict(patches=out, errors=errors, takes=takes, fake={str(a): n for a, n in Syms.rev.items()})))
''' % (FAKE_BASE, FAKE_SPAN)


def load_patches(tree):
    fakeroot = tmpdir("bbres-root-")
    os.makedirs(os.path.join(fakeroot, "out"))
    open(os.path.join(fakeroot, "out", "cave.bin"), "wb").close()
    real = "-"
    elf = os.path.join(tree, "out", "cave.elf")
    if os.path.isfile(elf) and shutil.which("arm-none-eabi-nm"):
        nm = subprocess.run(["arm-none-eabi-nm", elf], capture_output=True, text=True).stdout
        real = json.dumps([l.split()[2] for l in nm.splitlines() if len(l.split()) == 3])
    loader = os.path.join(fakeroot, "load_patches.py")
    open(loader, "w").write(_LOADER)
    r = subprocess.run([sys.executable, "-I", loader, tree, fakeroot, real], capture_output=True, text=True,
                       cwd=fakeroot)
    if r.returncode:
        raise SystemExit(f"resources.py: reading {tree}/patches failed:\n{r.stderr[-2000:]}")
    d = json.loads(r.stdout)
    d["fake"] = {int(a): n for a, n in d["fake"].items()}
    d["real_symbols"] = real != "-"
    return d


def decode_bl(b, at):
    """target of a Thumb-2 BL / B.W at `at` in bytes b (4 long), or None"""
    if len(b) < 4:
        return None
    h1, h2 = b[0] | b[1] << 8, b[2] | b[3] << 8
    if h1 & 0xF800 != 0xF000 or h2 & 0xD000 not in (0xD000, 0x9000):
        return None
    s = (h1 >> 10) & 1
    j1, j2 = (h2 >> 13) & 1, (h2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s:
        off -= 1 << 25
    return ("bl" if h2 & 0xD000 == 0xD000 else "b.w"), at + 4 + off


def tokens(p, fake):
    """per byte address: what the patch writes there, symbol names in place of stand-in addresses"""
    new, at = bytes.fromhex(p["new"]), p["addr"]
    tok = {at + i: ("byte", new[i]) for i in range(len(new))}
    i = 0
    while i + 4 <= len(new):
        d = decode_bl(new[i:i + 4], at + i)
        w = int.from_bytes(new[i:i + 4], "little") & ~1
        name = None
        if d and FAKE_BASE <= d[1] < FAKE_BASE + FAKE_SPAN + 0x1000:
            name = (d[0], sym_name(d[1], fake))
        elif FAKE_BASE <= w < FAKE_BASE + FAKE_SPAN + 0x1000 and i % 2 == 0:
            name = ("word", sym_name(w, fake))
        if name:
            for k in range(4):
                tok[at + i + k] = name
            i += 4
        else:
            i += 2
    return tok


def sym_name(a, fake):
    if a in fake:
        return fake[a]
    below = [x for x in fake if x <= a < x + 0x100]
    return f"{fake[max(below)]}+{a - max(below):#x}" if below else h(a)


def describe(p, fake):
    """(kind, stock callee, new target) of one patch"""
    old, new, at = bytes.fromhex(p["old"]), bytes.fromhex(p["new"]), p["addr"]
    do, dn = decode_bl(old, at), decode_bl(new, at)
    if len(old) == 4 and do and dn:
        tgt = sym_name(dn[1], fake) if FAKE_BASE <= dn[1] < FAKE_BASE + FAKE_SPAN + 0x1000 else h(dn[1])
        return "call", do[1], tgt
    if dn and len(new) <= 8:
        tgt = sym_name(dn[1], fake) if FAKE_BASE <= dn[1] < FAKE_BASE + FAKE_SPAN + 0x1000 else h(dn[1])
        return "call", None, tgt
    if len(new) == 4:
        w = int.from_bytes(new, "little") & ~1
        if FAKE_BASE <= w < FAKE_BASE + FAKE_SPAN + 0x1000:
            return "pointer", int.from_bytes(old, "little"), sym_name(w, fake)
    return "data", None, None


def data_words(p):
    """u16 view of a data patch, only the changed words: [(addr, old, new)]"""
    old, new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
    out = []
    for i in range(0, len(new) - 1, 2):
        o, n = old[i] | old[i + 1] << 8, new[i] | new[i + 1] << 8
        if o != n:
            out.append((p["addr"] + i, o, n))
    return out


# ---------------------------------------------------------------------------------------------------------- tags

_TAG = re.compile(r"resources:\s*(store|wants|shares|ram)\b([^\n*]*)")
# beside src/ and patches/: the build's own tool (D-047: its stubs write a patch-RAM word), and the tags for sources
# this fork does not edit
TAG_FILES = ("bench/b2split.py", "bench/resources.tags")


def read_tags(tree_path):
    """`resources: store <name> sites=.. cap=.. stock=N`, `resources: wants site=.. callee=.. by=..`, `resources:
    shares at=.. with=a,b` and `resources: ram at=.. size=..` tags in src/, patches/ and TAG_FILES"""
    tags = []
    rels = [f"{d}/{fn}" for d in ("src", "patches") if os.path.isdir(os.path.join(tree_path, d))
            for fn in sorted(os.listdir(os.path.join(tree_path, d)))] + list(TAG_FILES)
    for rel in rels:
        p = os.path.join(tree_path, rel)
        if not os.path.isfile(p) or not rel.endswith((".c", ".h", ".cpp", ".S", ".py", ".tags")):
            continue
        for n, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            for m in _TAG.finditer(line):
                words = m.group(2).split()
                t = {"kind": m.group(1), "file": rel, "line": n}
                if m.group(1) == "store" and words and "=" not in words[0]:
                    t["name"] = words.pop(0)
                for w in words:
                    if "=" in w:
                        k, v = w.split("=", 1)
                        vals = [int(x, 0) for x in v.split(",") if re.fullmatch(r"(0x)?[0-9a-fA-F]+", x)]
                        t[k] = vals if k in ("sites", "cap") else (vals[0] if vals and k in ("stock", "site", "callee", "at", "size")
                                                                   else v.split(",") if k == "with" else v)
                tags.append(t)
    return tags


# ------------------------------------------------------------------------------------------------------- build

def build_info(tree_path, do_build):
    """bank-1 / bank-2 bytes per object from out/cave.map: of a fresh build in a copy (--build), else of what is
    in the tree's out/ (it may be stale), else None"""
    where = tree_path
    note = "the tree's out/ as last built (may be stale)"
    if do_build:
        where = tmpdir("bbres-build-")
        for item in os.listdir(tree_path):
            if item in ("out", ".git", "firmware", ".venv"):
                continue
            s = os.path.join(tree_path, item)
            if os.path.isdir(s):
                shutil.copytree(s, os.path.join(where, item), symlinks=True)
            else:
                shutil.copy2(s, os.path.join(where, item))
        r = subprocess.run(["sh", "./build.sh"], cwd=where, capture_output=True, text=True)
        log = (r.stdout + r.stderr)[-3000:]
        over = re.search(r"region [`']?CAVE'? overflowed by (\d+) bytes", log)
        if r.returncode and not os.path.isfile(os.path.join(where, "out", "cave.map")):
            return {"built": False, "note": "build failed", "log": log,
                    "cave_overflow": int(over.group(1)) if over else None}
        note = "built in a temporary copy"
        if r.returncode:
            note += f" (build.sh exit {r.returncode}: {'CAVE overflowed by ' + over.group(1) + ' B' if over else log[-300:]})"
    mp = os.path.join(where, "out", "cave.map")
    if not os.path.isfile(mp):
        return None
    lines = open(mp, encoding="utf-8", errors="replace").read().split("\n")
    sections, cur, objs, pending, spans = {}, None, {}, None, {}
    for line in lines:
        m = re.match(r"^(\.\w+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)", line)
        if m:
            cur = m.group(1)
            sections[cur] = int(m.group(3), 16)
            spans[cur] = (int(m.group(2), 16), [])
            continue
        if re.match(r"^\S", line):
            cur = None if not line.startswith(" ") else cur
            continue
        if cur not in (".cave", ".bank2", ".b2head"):
            continue
        m = re.match(r"^ (\.\S+|\*fill\*|COMMON)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)(?:\s+(\S+))?", line)
        if not m and pending:
            m2 = re.match(r"^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+)", line)
            if m2:
                m = (pending, m2.group(1), m2.group(2), m2.group(3))
            pending = None
        elif not m:
            m1 = re.match(r"^ (\.\S+)\s*$", line)
            pending = m1.group(1) if m1 else None
            continue
        if not isinstance(m, tuple):
            m = m.groups()
        name, at, size, obj = m
        size = int(size, 16)
        if not size:
            continue
        spans[cur][1].append((int(at, 16), size, os.path.basename(obj) if obj else "(fill)"))
    # what each input section really occupies: up to the next one's address. A merged string section
    # (.rodata.str1.1) is listed at full size under every object, but all the strings sit in the first one and the
    # others start where the next section does (0 B): summing the listed sizes overcounts by 2.5..3.5 KB
    for sec, (start, ents) in spans.items():
        if sec not in (".cave", ".bank2", ".b2head"):
            continue
        end = start + sections[sec]
        for i, (at, size, obj) in enumerate(ents):
            nxt = ents[i + 1][0] if i + 1 < len(ents) else end
            real = min(size, max(0, nxt - at)) if nxt >= at else size
            bank = "bank1" if sec == ".cave" else "bank2"
            objs.setdefault(obj, {"bank1": 0, "bank2": 0})[bank] += real
    ld = os.path.join(where, "out", "cave.ld")
    ld = ld if os.path.isfile(ld) else os.path.join(where, "src", "cave.ld.in")
    cave_len = None
    if os.path.isfile(ld):
        m = re.search(r"CAVE\s*\(\w+\)\s*:\s*ORIGIN\s*=\s*0x[0-9a-fA-F]+\s*,\s*LENGTH\s*=\s*(0x[0-9a-fA-F]+|\d+)",
                      open(ld).read())
        cave_len = int(m.group(1), 0) if m else None
    b2 = os.path.join(where, "out", "bank2.bin")
    return {"built": True, "note": note, "cave_length": cave_len, "cave_used": sections.get(".cave"),
            "bank2_bytes": os.path.getsize(b2) if os.path.isfile(b2) else
            (sections.get(".bank2", 0) + sections.get(".b2head", 0)), "objects": objs}


# --------------------------------------------------------------------------------------------------------- scan

def scan(path, label, do_build=False, stock=None):
    t = Tree(path, label)
    warn = []
    man = {"tree": label, "path": path, "warnings": warn}

    # ---- bindings: macros naming a stock address, by role
    bind = {}                                     # (file, name) -> addr
    roles = {"register": set(), "store_add": set(), "perm_alloc": set(), "setting": set()}
    binds = []                                    # every stock function a macro binds with FN() / B2_FN()
    for f in t.files.values():
        for name, (body, _l, _c) in f.macros.items():
            m = re.search(r"\b(0x0?8[0-9a-fA-F]{6})\b", body)
            if m and "(" in body:
                a = int(m.group(1), 16) & ~1
                bind[(f.rel, name)] = a
                for role, rx in (("register", r"regist"), ("store_add", r"store_add"), ("perm_alloc", r"perm_alloc"),
                                 ("setting", r"setting")):
                    if re.search(rx, name, re.I):
                        roles[role].add(a)
                if re.search(r"\bB?2?_?FN\s*\(\s*" + m.group(1), body):
                    binds.append({"addr": a, "name": name, "file": f.rel, "line": _l, "module": module_of(f.rel)})
    man["binds"] = sorted(binds, key=lambda b: (b["addr"], b["file"]))
    man["stock_api"] = {k: sorted(h(a) for a in v) for k, v in roles.items()}
    man["stock_api_names"] = {h(a): sorted({n for (_r, n), b in bind.items() if b == a})
                              for v in roles.values() for a in v}

    def names_for(f, role):
        return {n for n, (b, _l, _c) in f.macro_map().items()
                if (f.rel, n) in bind and bind[(f.rel, n)] in roles[role]} | \
               {n for (r, n), a in bind.items() if a in roles[role] and n in f.macro_map()}

    # ---- the patch tables first: the functions they name are hooks, whose id arguments are stock's own
    pt = load_patches(path)
    hook_names = set(pt["fake"].values())

    def from_callers(fn, args_of_interest, depth=0):
        """a helper's parameters as its callers pass them: [(caller file, caller fn, pos, env, {param: expr})]"""
        out = []
        for g in t.sources():
            for _n, cfn, cpos, cargs in calls(g, {fn.name}):
                exprs = {p: cargs[fn.params.index(p)] for p in args_of_interest
                         if p in fn.params and fn.params.index(p) < len(cargs)}
                combos = envs(loops_at(g, cfn, cpos))
                if combos is None:
                    warn.append(f"{g.rel}:{g.line(cpos)}: a loop around {fn.name}(…) could not be read")
                    continue
                for env in combos:
                    out.append((g, cfn, cpos, env, exprs))
        return out

    def wrapped(f, names):
        """calls of a function-like macro of f whose body calls one of names, the macro expanded: (name, fn, pos, args)"""
        wraps = {w: (f.visible("fparams").get(w), body) for w, (body, _l, _c) in f.visible("fmacros").items()
                 if re.search(r"\b(" + "|".join(map(re.escape, names)) + r")\s*\(", body)} if names else {}
        for w, (ps, body) in wraps.items():
            for _n, fn, pos, args in calls(f, {w}):
                text = body
                for p_, a_ in zip(ps or [], args):
                    text = re.sub(r"\b" + re.escape(p_) + r"\b", lambda _m, a_=a_: a_, text)
                code, blank, _c = lex(text)
                for m in re.finditer(r"\b(" + "|".join(map(re.escape, names)) + r")\s*\(", blank):
                    o = m.end() - 1
                    yield m.group(1), fn, pos, split_top(code, blank, o + 1, match_close(blank, o))

    def taken_as_value(f, names):
        """a binding used other than by a call (a function-pointer variable): calls through it are not read"""
        for m in re.finditer(r"\b(" + "|".join(map(re.escape, names)) + r")\b(?!\s*\()", f.blank) if names else ():
            warn.append(f"{f.rel}:{f.line(m.start())}: {m.group(1)} is taken as a value: calls through it are not read")

    # ---- parameter registrations and store adds
    params, adds, forwarded = [], [], []
    for f in t.sources():
        regs, sadd = names_for(f, "register"), names_for(f, "store_add")
        taken_as_value(f, regs | sadd)
        for name, fn, pos, args in list(calls(f, regs | sadd)) + list(wrapped(f, regs | sadd)):
            if len(args) < 2:
                continue
            idx, line = args[1], f.line(pos)
            kind = "list" if "list" in name else "num" if "num" in name else "?"
            li = 2 if kind == "list" else 3
            sites = []                                  # (file evaluating, fn, pos, env, id expr, xml expr, label expr)
            if re.fullmatch(r"\w+", idx) and idx in fn.params:
                if fn.name in hook_names:               # a hook forwarding the stock call it stands in for
                    forwarded.append({"file": f.rel, "func": fn.name, "line": line, "call": name})
                    continue
                # a helper of ours taking the id as a parameter: its callers say which ids
                want = [idx] + [a for a in (args[-1], args[li] if len(args) > li else "") if a in fn.params]
                callers = from_callers(fn, want)
                if not callers:
                    warn.append(f"{f.rel}:{line}: {fn.name} registers its parameter `{idx}` and nothing calls it")
                for g, cfn, cpos, env, ex in callers:
                    sites.append((g, cfn, cpos, env, ex.get(idx), (g, ex[args[-1]]) if args[-1] in ex else (f, args[-1]),
                                  (g, ex[args[li]]) if len(args) > li and args[li] in ex else (f, args[li] if len(args) > li else None),
                                  fn.name))
            else:
                combos = envs(loops_at(f, fn, pos))
                if combos is None:
                    warn.append(f"{f.rel}:{line}: a loop around {name}(…, {idx}) could not be read")
                    continue
                sites = [(f, fn, pos, env, idx, (f, args[-1]), (f, args[li] if len(args) > li else None), None)
                         for env in combos]
            for g, cfn, cpos, env, e, (xf, xe), (lf, le), via in sites:
                try:
                    v = g.eval(e, env, cpos)
                except Unresolved as x:
                    warn.append(f"{g.rel}:{g.line(cpos)}: id `{e}` of {name} not read ({x})")
                    continue
                rec = {"id": v, "file": g.rel, "module": module_of(g.rel), "func": cfn.name, "line": g.line(cpos),
                       "cond": list(g.cond(cpos)), "id_name": e.strip() if re.fullmatch(r"\s*[A-Za-z_]\w*\s*", e or "") else None}
                if via:
                    rec["via"] = via
                if name in sadd:
                    adds.append(rec)
                else:
                    rec["kind"] = kind
                    rec["xml"] = xf.string(xe, env if xf is g else {}, cpos if xf is g else pos)
                    rec["label"] = lf.string(le, env if lf is g else {}, cpos if lf is g else pos) if le else None
                    params.append(rec)
    # ---- uses: the ids read through a binding named *setting* (fw_setting, fw_setting_set: (store, id))
    uses, uses_unread = [], []
    for f in t.sources():
        for name, fn, pos, args in calls(f, names_for(f, "setting")):
            if len(args) < 2:
                continue
            e = args[1]
            if re.fullmatch(r"\w+", e) and e in fn.params:
                todo = [(g, cfn, cpos, env, ex[e]) for g, cfn, cpos, env, ex in from_callers(fn, [e]) if e in ex]
            else:
                combos = envs(loops_at(f, fn, pos))
                todo = [(f, fn, pos, env, e) for env in combos] if combos is not None else []
            if not todo:
                uses_unread.append(f"{f.rel}:{f.line(pos)}: {name}(…, {e})")
            for g, cfn, cpos, env, ex in todo:
                try:
                    v = g.eval(ex, env, cpos)
                except Unresolved:
                    uses_unread.append(f"{g.rel}:{g.line(cpos)}: {name}(…, {ex})")
                    continue
                uses.append({"id": v, "file": g.rel, "module": module_of(g.rel), "func": cfn.name, "line": g.line(cpos),
                             "call": name, "id_name": ex.strip() if re.fullmatch(r"\s*[A-Za-z_]\w*\s*", ex) else None})
    man["uses"] = sorted({(u["id"], u["file"], u["line"]): u for u in uses}.values(), key=lambda u: (u["id"], u["file"], u["line"]))
    man["uses_unread"] = sorted(set(uses_unread))
    man["exclusive_flags"] = sorted({tuple(sorted(x)) for f in t.files.values() for x in f.exclusive})
    man["params"] = sorted(params, key=lambda r: (r["id"], r["file"]))
    man["forwarded"] = forwarded
    man["store_adds"] = sorted(adds, key=lambda r: (r["file"], r["line"], r["id"]))

    # ---- call graph (by name; static functions of the same name in two files both count)
    funcs = {}
    for f in t.sources():
        for fn in f.funcs:
            funcs.setdefault(fn.name, []).append((f, fn))
    graph = {}
    word = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
    for name, defs in funcs.items():
        out = set()
        for f, fn in defs:
            out |= {m.group(1) for m in word.finditer(f.blank, fn.a, fn.b) if m.group(1) in funcs}
        graph[name] = out

    def reach(start):
        seen, todo = set(), [start]
        while todo:
            n = todo.pop()
            if n in seen or n not in funcs:
                continue
            seen.add(n)
            todo += graph.get(n, ())
        return seen

    # ---- patches (loaded above)
    fake = pt["fake"]
    setlist = []
    chk = os.path.join(path, "check.sh")
    if os.path.isfile(chk):
        m = re.search(r"patch\.py\s+([\w ]+)", open(chk).read())
        setlist = m.group(1).split() if m else []
    applied = set(setlist)
    patches = []
    for p in pt["patches"]:
        if not bytes.fromhex(p["old"]) and p["addr"] >= 0x080F1E78:
            continue                                         # the cave itself, appended
        kind, callee, target = describe(p, fake)
        p.update(kind=kind, callee=callee, target=target, end=p["addr"] + len(bytes.fromhex(p["new"])),
                 applied=bool(not applied or set(p["sets"]) & applied))
        p["order"] = min(((setlist.index(x), p["pos"][x]) for x in p["sets"] if x in setlist), default=(99, p["pos"][p["module"]]))
        if kind == "data":
            p["words"] = data_words(p)
        patches.append(p)
    man["patches"] = sorted(patches, key=lambda p: p["addr"])
    man["patch_errors"] = pt["errors"]
    man["takes"] = pt["takes"]
    man["patch_sets"] = setlist
    man["patch_symbols"] = "the tree's out/cave.elf (for `in sym`)" if pt["real_symbols"] else "stand-ins (no build)"
    for name, e in pt["errors"].items():
        warn.append(f"patches/{name}.py could not be read: {e}")
    if os.path.isfile(os.path.join(path, "patch.py")) and "TAKES" in open(os.path.join(path, "patch.py")).read():
        man["patch_py_takes"] = True

    # ---- stores: the chains behind every hooked stock store_add, then the tagged stores
    chains = {}
    for p in patches:
        if p["kind"] == "call" and p["callee"] in roles["store_add"] and p["applied"]:
            chains.setdefault(p["target"], []).append(p["addr"])
    chain_out = []
    for fname, sites in sorted(chains.items()):
        r = reach(fname)
        ent = sorted({(a["id"], a["func"]) for a in adds if a["func"] in r})
        chain_out.append({"entry": fname, "sites": sites, "functions": sorted(r),
                          "entries": [{"id": i, "func": fn} for i, fn in ent]})
    man["store_chains"] = chain_out
    # the same for the registrations: which ids each hooked stock registration call leads to
    regc = {}
    for p in patches:
        if p["kind"] == "call" and p["callee"] in roles["register"] and p["applied"]:
            regc.setdefault(p["target"], []).append(p["addr"])
    man["register_chains"] = []
    for fname, sites in sorted(regc.items()):
        r = reach(fname)
        man["register_chains"].append({"entry": fname, "sites": sites, "functions": sorted(r),
                                       "ids": sorted({q["id"] for q in params if q["func"] in r})})
    man["tags"] = read_tags(path)
    man["stores"] = stores_of(man, man["tags"], stock)
    tagged = {a for tg in man["tags"] if tg["kind"] == "store" for a in tg.get("sites", [])}
    man["untagged_store_sites"] = [{"site": a, "entry": c["entry"], "entries": len(c["entries"])}
                                   for c in chain_out for a in c["sites"] if a not in tagged]

    # ---- SDRAM: the boot-time block
    man["sdram"] = sdram(t, warn, roles)

    # ---- backup SRAM, patch RAM
    man["bkpsram"] = ram_ranges(t, path, warn, man["tags"], BKP_LO, BKP_HI, "backup SRAM")
    man["patchram"] = ram_ranges(t, path, warn, man["tags"], PATCH_LO, PATCH_HI, "patch RAM")

    # ---- build
    man["build"] = build_info(path, do_build)
    man["_fake"] = {str(a): n for a, n in fake.items()}
    man["warnings"] = list(dict.fromkeys(warn))           # one line per place, not one per loop value
    return man


def cap_at(man, addr, stock):
    """the cap a `movs rN, #imm8` at addr holds in this tree: the patched byte, else stock's"""
    for p in man["patches"]:
        if p["applied"] and p["addr"] <= addr < p["end"]:
            b = bytes.fromhex(p["new"])[addr - p["addr"]:addr - p["addr"] + 2]
            return (b[0], p["module"]) if len(b) == 2 and b[1] & 0xF8 == 0x20 else (None, p["module"])
    if stock:
        b = stock[addr - FLASH:addr - FLASH + 2]
        return (b[0], "stock") if b[1] & 0xF8 == 0x20 else (None, "stock")
    return None, "stock (no image)"


def stores_of(man, tags, stock):
    """each tagged store: the entries this tree adds (from the chains at its sites), stock's own count, the cap"""
    out = []
    for tg in tags:
        if tg["kind"] != "store":
            continue
        ent, fns = set(), set()
        for c in man["store_chains"]:
            if set(c["sites"]) & set(tg.get("sites", [])):
                ent |= {(e["id"], e["func"]) for e in c["entries"]}
                fns.add(c["entry"])
        caps = [(h(a),) + cap_at(man, a, stock) for a in tg.get("cap", [])]
        vals = {c[1] for c in caps if c[1] is not None}
        out.append({"name": tg.get("name", "?"), "tag": f"{tg['file']}:{tg['line']}", "sites": [h(s) for s in tg.get("sites", [])],
                    "entry_functions": sorted(fns), "entries": [{"id": i, "func": f} for i, f in sorted(ent)],
                    "added": len(ent), "stock": tg.get("stock"), "caps": caps,
                    "cap": min(vals) if vals else None, "caps_agree": len(vals) <= 1})
    return out


def _strip(e):
    """an expression with its casts and outer parentheses taken off"""
    e = e.strip()
    while True:
        n = re.sub(r"^\(\s*(?:(?:const|volatile|struct|unsigned|signed)\s+)*\w+\s*(?:(?:const|volatile)\s*)*\**\s*\)\s*", "", e)
        if n.startswith("(") and match_close(n, 0) == len(n) - 1:
            n = n[1:-1].strip()
        if n == e:
            return e
        e = n


class BlockTracer:
    """where a pointer inside a function comes from: the accessors (master_block, master_tail, prism_mem, ...) it may
    hold, or "other" when it is traced to something else (stock's pointer, the raw allocation); empty = not traced"""

    def __init__(self, t, acc):
        self.t, self.acc, self.cache = t, acc, {}
        self.defs, self.static = {}, set()
        for f in t.sources():
            for fn in f.funcs:
                self.defs.setdefault(fn.name, []).append((f, fn))
                k = fn.a - 1
                while k >= 0 and f.blank[k] not in ";}":
                    k -= 1
                if re.search(r"\bstatic\b", f.blank[k + 1:fn.a]):
                    self.static.add((f.rel, fn.name))   # its callers are in its own file only
        self.acc_call = re.compile(r"\b(" + "|".join(map(re.escape, acc)) + r")\s*\(\s*\)") if acc else None
        self.sites = {}                       # name -> [(file, function, index of its "(")]: every call, one pass
        call_rx = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
        for f in t.sources():
            for fn in f.funcs:
                for m in call_rx.finditer(f.blank, fn.a, fn.b):
                    if m.group(1) in self.defs:
                        self.sites.setdefault(m.group(1), []).append((f, fn, m.end() - 1))
        self.statics = {}                     # per file: names assigned from an accessor anywhere in it
        for f in t.sources():
            d = self.statics.setdefault(f.rel, {})
            for m in (self.acc_call.finditer(f.blank) if self.acc_call else ()):
                k = m.start() - 1
                while k >= 0 and f.blank[k] not in ";{}":
                    k -= 1
                am = re.search(r"\b(\w+)\s*=(?!=)[^=]*$", f.blank[k + 1:m.start()])
                if am:
                    d.setdefault(am.group(1), set()).add(m.group(1))

    def _rhs(self, f, i, limit):
        """the expression starting at i: up to a ; or a , or ) at depth 0"""
        depth, j = 0, i
        while j < limit:
            c = f.blank[j]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c in ";," and depth == 0:
                break
            j += 1
        return f.code[i:j]

    def classify(self, f, fn, expr, depth):
        e = _strip(expr)
        if self.acc_call:
            got = {m.group(1) for m in self.acc_call.finditer(e)}
            if got:
                return got
        tern = re.match(r"(.+?)\?(.+):(.+)$", e, re.S)
        if tern:
            return self.classify(f, fn, tern.group(2), depth) | self.classify(f, fn, tern.group(3), depth)
        if re.fullmatch(r"[A-Za-z_]\w*", e):
            return self.trace(f, fn, e, depth + 1)
        return {"other"}

    def trace(self, f, fn, ident, depth=0):
        key = (f.rel, fn.name, fn.a, ident)
        if key in self.cache:
            return self.cache[key]
        if depth > 8:
            return set()
        self.cache[key] = set()                               # a cycle reads as not traced
        got = set()
        # assigned here: `ident = expr` (a declaration's initialiser too, `uint8_t *ident = expr`; not `*ident = expr`,
        # which stores through it)
        for m in re.compile(r"(?<![\w.>])" + re.escape(ident) + r"\s*=(?!=)").finditer(f.blank, fn.a, fn.b):
            before = f.blank[fn.a:m.start()].rstrip()
            if before.endswith("*") and not re.search(r"[\w)]\s*\**$", before):
                continue
            got |= self.classify(f, fn, self._rhs(f, m.end(), fn.b), depth)
        # handed back through an out-parameter: g(..., &ident, ...) with `*param = expr` in g
        for m in re.finditer(r"\b(\w+)\s*\(", f.blank[fn.a:fn.b]):
            o = fn.a + m.end() - 1
            args = split_top(f.code, f.blank, o + 1, match_close(f.blank, o))
            for k, a in enumerate(args):
                if re.fullmatch(r"&\s*" + re.escape(ident), a.strip()):
                    for g, gfn in self.callee(f, m.group(1)):
                        if k < len(gfn.params):
                            p = gfn.params[k]
                            for mm in re.finditer(r"\*\s*" + re.escape(p) + r"\s*=(?!=)", g.blank[gfn.a:gfn.b]):
                                got |= self.classify(g, gfn, self._rhs(g, gfn.a + mm.end(), gfn.b), depth)
        # a parameter: what its callers pass
        if ident in fn.params:
            k = fn.params.index(ident)
            for g, cfn, o in self.sites.get(fn.name, []):
                if (f.rel, fn.name) in self.static and g is not f:
                    continue
                cargs = split_top(g.code, g.blank, o + 1, match_close(g.blank, o))
                if k < len(cargs):
                    got |= self.classify(g, cfn, cargs[k], depth)
        # a macro standing for an address or an accessor call
        body = f.macro_map().get(ident)
        if not got and body:
            got = self.classify(f, fn, body[0], depth) if not re.fullmatch(r"\s*", body[0]) else {"other"}
        if not got:
            got = set(self.statics.get(f.rel, {}).get(ident, ()))
        self.cache[key] = got
        return got

    def callee(self, f, name):
        """the definitions a call of name in file f reaches: its own file's static one, else the global ones"""
        own = [(g, gfn) for g, gfn in self.defs.get(name, []) if g is f]
        return own or [(g, gfn) for g, gfn in self.defs.get(name, []) if (g.rel, name) not in self.static]


def sdram(t, warn, roles):
    master = t.files.get("src/master.c")
    res = {"block": None, "core": None, "parts": [], "allocations": []}
    if not master:
        return res
    # every boot-time allocation (master.c's block, and any other module's own)
    for f in t.sources():
        names = {n for n, (b, _l, _c) in f.macro_map().items() if re.search(r"\b0x0?8[0-9a-fA-F]{6}\b", b)
                 and int(re.search(r"\b(0x0?8[0-9a-fA-F]{6})\b", b).group(1), 16) & ~1 in roles["perm_alloc"]}
        for name, fn, pos, args in calls(f, names):
            e = args[0]
            sizes, how = [], "read"
            tern = re.match(r"(.+?)\?(.+):(.+)$", e, re.S)
            for part in ([tern.group(2), tern.group(3)] if tern else [e]):
                try:
                    sizes.append(f.eval(part, {}, pos))
                except Unresolved as x:
                    v = probe(f, [part.strip()]).get(part.strip())
                    if v is None:
                        warn.append(f"{f.rel}:{f.line(pos)}: allocation size `{part.strip()}` not read ({x}; no compiler probe)")
                    else:
                        sizes.append(v)
                        how = "compiler"
            res["allocations"].append({"file": f.rel, "func": fn.name, "line": f.line(pos), "expr": " ".join(e.split()),
                                       "sizes": sizes, "how": how})
    blk = [a for a in res["allocations"] if a["file"] == "src/master.c" and a["func"] == "master_alloc"]
    if blk and blk[0]["sizes"]:
        res["block"], res["core"] = max(blk[0]["sizes"]), min(blk[0]["sizes"])

    # accessors: master.c's functions handing out a pointer into the block, and where that pointer starts
    acc = {}

    def acc_off(name, depth=0):
        if name in acc or depth > 5:
            return acc.get(name)
        fn = next((x for x in master.funcs if x.name == name), None)
        if not fn:
            return None
        body = master.code[fn.a:fn.b]
        m = re.search(r"\breturn\b([^;]*);", body)
        if not m:
            return None
        e = m.group(1)
        tern = re.match(r"(.+?)\?(.+):(.+)$", e, re.S)
        then = tern.group(2) if tern else e
        pm = re.search(r"\b\w+\s*\+\s*([A-Z_][A-Z0-9_]*|0x[0-9a-fA-F]+u?)", then)
        if pm:
            v = master.eval(pm.group(1), {})
        else:
            cm = re.search(r"\b(\w+)\s*\(\s*\)", then)
            v = acc_off(cm.group(1), depth + 1) if cm and cm.group(1) in {x.name for x in master.funcs} else 0
        acc[name] = v
        return v

    for name in ("master_block", "master_tail") + tuple(x.name for x in master.funcs if x.name.endswith("_mem")):
        try:
            acc_off(name)
        except Unresolved as x:
            warn.append(f"src/master.c: accessor {name}'s offset not read ({x})")
    acc = {k: v for k, v in acc.items() if v is not None}
    res["accessors"] = {k: v for k, v in acc.items()}
    parts = {}

    def add_part(name, f, off, acc_name, pos, expr):
        key = name
        if key in parts:
            if parts[key]["offset"] != off:
                warn.append(f"SDRAM part {name}: {parts[key]['file']} says {h(parts[key]['offset'])}, {f.rel} says {h(off)}")
            parts[key]["files"] = sorted(set(parts[key]["files"]) | {f.rel})
            return
        parts[key] = {"name": name, "file": f.rel, "files": [f.rel], "module": module_of(f.rel), "offset": off,
                      "accessor": acc_name, "expr": expr, "cond": list(f.cond(pos)), "pos": pos, "_f": f}

    # the parts master.c hands out by accessor: <stem>_mem -> STEM
    for name, off in acc.items():
        if name.endswith("_mem"):
            stem = name[:-4].upper()
            add_part(stem, master, off, name, next(x for x in master.funcs if x.name == name).a, f"{name}()")

    # where a pointer comes from, traced through the code (comments play no part): assigned from an accessor, passed
    # down as an argument (a bank-2 function's `uint8_t *mem`), handed back through a `uint8_t **` out-parameter,
    # or a file's static assigned from an accessor in another function
    tracer = BlockTracer(t, acc)
    offset_rx = re.compile(r"(?<![\w.>])([A-Za-z_]\w*)(\s*\(\s*\))?\s*\+\s*([A-Z][A-Z0-9_]*|0[xX][0-9a-fA-F]+[uUlL]*)(?![\w(])"
                           r"|&\s*([A-Za-z_]\w*)\s*\[\s*([A-Z][A-Z0-9_]*|0[xX][0-9a-fA-F]+[uUlL]*)\s*\]")
    for f in t.sources():
        mm = f.macro_map()
        for fn in f.funcs:
            for m in offset_rx.finditer(f.blank, fn.a, fn.b):
                base, call, off = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), None, m.group(5))
                named = off[0].isalpha()
                if named and (off not in mm and off not in f._en or f.rel == "src/master.c" and off.endswith("_BYTES")):
                    continue
                if call:
                    got = {base} if base in acc else set()
                    if not got:
                        continue                                # another function's result, not the block
                else:
                    got = tracer.trace(f, fn, base)
                if any(a.endswith("_mem") for a in got):
                    continue                    # inside a module's own part (prism.c's layout of PRISM): its own business
                blocks = sorted(a for a in got if a in acc)
                if not blocks:
                    if not got and named and re.search(r"_(OFFSET|AT|OFF)$", off):
                        warn.append(f"{f.rel}:{f.line(m.start())}: `{base} + {off}` in {fn.name}: where `{base}` points "
                                    f"was not traced (no caller, no accessor), so this block offset is not read")
                    continue
                if not named:
                    warn.append(f"{f.rel}:{f.line(m.start())}: `{base} + {off}` in {fn.name}: a block offset written as a "
                                f"literal, not read as a part (name it, as the other parts are)")
                    continue
                try:
                    rel = f.eval(off, {}, m.start())
                except Unresolved as x:
                    warn.append(f"{f.rel}:{f.line(m.start())}: block offset {off} not read ({x})")
                    continue
                for a in blocks:
                    add_part(off, f, acc[a] + rel, a, m.start(),
                             " ".join(mm[off][0].split()) if off in mm else f"enum {off} = {h(rel)}")
    # sizes
    plist = sorted(parts.values(), key=lambda p: (p["offset"], p["name"]))
    for p in plist:
        f, name = p["_f"], p["name"]
        mm = f.macro_map()
        stem = re.sub(r"_(OFFSET|AT)$", "", name)
        cands = []
        if stem + "_BYTES" in mm and stem + "_BYTES" != name:
            try:
                cands.append((f.eval(stem + "_BYTES", {}), stem + "_BYTES"))
            except Unresolved:
                pass
        # the struct cast at its use, and the _Static_asserts that bound that struct
        st = set()
        for fl in [p["_f"]] + [t.files[r] for r in p["files"] if r in t.files]:
            for m in re.finditer(r"\(\s*(?:volatile\s+|const\s+)*struct\s+(\w+)\s*\*\s*\)\s*\(?\s*(?:&\s*)?\w+(?:\s*\(\s*\))?"
                                 r"\s*(?:\+|\[)\s*" + name + r"\b", fl.blank):
                st.add((fl, m.group(1)))
        for fl, sname in st:
            for g in [fl] + [t.header(fl.rel, i) for i in fl.includes if t.header(fl.rel, i)]:
                for m in re.finditer(r"_Static_assert\s*\(", g.blank):
                    c = match_close(g.blank, m.end() - 1)
                    cond = split_top(g.code, g.blank, m.end(), c)[0]
                    m1 = re.fullmatch(r"\s*sizeof\s*\(\s*struct\s+" + sname + r"\s*\)\s*<=\s*(.+)", cond, re.S)
                    m2 = re.fullmatch(r"\s*(.+?)\s*\+\s*sizeof\s*\(\s*struct\s+" + sname + r"\s*\)\s*<=\s*(.+)", cond, re.S)
                    try:
                        if m1 and "&&" not in m1.group(1):
                            cands.append((g.eval(m1.group(1), {}), f"assert in {g.rel}"))
                        elif m2:
                            cands.append((g.eval(m2.group(2), {}) - g.eval(m2.group(1), {}), f"assert in {g.rel}"))
                    except Unresolved:
                        pass
        if cands:
            p["size"], p["size_from"] = min(cands)
        # what the part really uses: sizeof its struct, from the compiler when there is one
        for fl, sname in st:
            v = probe(fl, [f"sizeof(struct {sname})"]).get(f"sizeof(struct {sname})")
            if v:
                p["used"] = max(p.get("used", 0), v)
                p["struct"] = sname
        p["nested_in"] = None
        body = mm.get(name, ("",))[0]
        for q in plist:
            if q is not p and re.search(r"\b" + q["name"] + r"\b", body):
                p["nested_in"] = q["name"]
    for i, p in enumerate(plist):
        if "size" in p:
            continue
        nxt = [q["offset"] for q in plist if q["offset"] > p["offset"]]
        end = min(nxt) if nxt else res["block"]
        if end is not None:
            p["size"], p["size_from"] = end - p["offset"], "room up to the next part"
        else:
            p["size"], p["size_from"] = 0, "unknown"
    for p in plist:
        p.pop("_f")
        p.pop("pos")
    res["parts"] = plist
    # master.c's own bound, when it states one (_Static_assert(... == N) on the block's macros)
    for m in re.finditer(r"_Static_assert\s*\(", master.blank):
        c = match_close(master.blank, m.end() - 1)
        cond = split_top(master.code, master.blank, m.end(), c)[0]
        mm = re.fullmatch(r"\s*(.+?)\s*(==|<=)\s*(0x[0-9a-fA-F]+u?|\d+)\s*", cond)
        if mm and "BYTES" in mm.group(1):
            try:
                if master.eval(mm.group(1), {}) == res["block"]:
                    res["bound"] = {"value": master.eval(mm.group(3), {}), "assert": " ".join(cond.split()),
                                    "line": master.line(m.start())}
            except Unresolved:
                pass
    return res


_PTR_CAST = re.compile(r"\(\s*(?:(?:volatile|const)\s+)*(struct\s+\w+|u?int(?:8|16|32|64)_t|float|unsigned|int|char)"
                       r"\s*(?:(?:volatile|const)\s+)*\*\s*\)")
_OPERAND = re.compile(r"\s*([A-Za-z_]\w*|0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*)")


def _cast_operand(s, i):
    """the operand of a cast ending at s[i]: a parenthesised group or one token, as (text, end)"""
    j = i
    while j < len(s) and s[j] in " \t":
        j += 1
    if j < len(s) and s[j] == "(":
        e = match_close(s, j)
        return s[j:e + 1], e + 1
    m = _OPERAND.match(s, i)
    return (m.group(1), m.end()) if m else (None, i)


def ram_value(f, expr, lo, hi):
    """expr's value when it is an address in [lo, hi) (macros and enums of f evaluated), else None"""
    try:
        v = f.eval(expr, {})
    except (Unresolved, RecursionError, ValueError, TypeError, ZeroDivisionError):
        return None
    return v if lo <= v < hi else None


def _lit_in(text, lo, hi):
    """text holds a hex literal in [lo, hi)"""
    return any(lo <= int(x, 16) < hi for x in re.findall(r"\b0[xX]([0-9a-fA-F]+)", text))


def ram_ranges(t, path, warn, tags, lo, hi, what):
    """the ranges of [lo, hi) (backup SRAM, patch RAM) each file uses: pointer casts of an address there (a literal,
    a macro, a base + offset: the operand is evaluated with the file's macros), bounded by _Static_asserts; `.S`
    words; `resources: ram at=.. size=..` tags"""
    uses = []
    for f in list(t.files.values()):
        if f.rel.endswith(".inc"):
            continue
        bkp_names = {n for n, (body, _l, _c) in f.macro_map().items() if _lit_in(body, lo, hi)
                     and ram_value(f, n, lo, hi) is not None}
        lines = f.code_pp.split("\n")
        for m in _PTR_CAST.finditer(f.code_pp):
            ty = " ".join(m.group(1).split())
            op, _e = _cast_operand(f.code_pp, m.end())
            if not op:
                continue
            a = ram_value(f, op, lo, hi)
            line = f.line(m.start())
            dm = re.match(r"\s*#\s*define\s+(\w+)", lines[line - 1]) if line - 1 < len(lines) else None
            if a is None:
                hit = set(re.findall(r"[A-Za-z_]\w*", op)) & bkp_names
                if hit or _lit_in(op, lo, hi):
                    warn.append(f"{f.rel}:{line}: a pointer cast on {what}, `({ty} *){' '.join(op.split())}`, not read")
                continue
            size = {"uint8_t": 1, "int8_t": 1, "char": 1, "uint16_t": 2, "int16_t": 2, "uint64_t": 8, "int64_t": 8}.get(ty, 4) \
                if not ty.startswith("struct") else None
            uses.append({"file": f.rel, "addr": a, "type": ty, "size": size, "from": "cast", "line": line,
                         "cond": list(f.cond(m.start())), "name": dm.group(1) if dm else None})
        for m in re.finditer(r"_Static_assert\s*\(", f.blank):
            c = match_close(f.blank, m.end() - 1)
            cond = split_top(f.code, f.blank, m.end(), c)[0]
            mm = re.fullmatch(r"\s*\(?(?:\(\s*uint32_t\s*\))?\s*\(?\s*(0[xX][0-9a-fA-F]+u?|[A-Za-z_]\w*)\s*\+\s*(.+?)\)?\s*<=\s*(.+?)\s*",
                              cond, re.S)
            if not mm or ram_value(f, mm.group(1), lo, hi) is None:
                continue
            a = ram_value(f, mm.group(1), lo, hi)
            try:
                end = a + f.eval(mm.group(2), {})           # a size the file states: the range is that long
            except Unresolved:
                try:
                    end = f.eval(mm.group(3), {})           # sizeof(...): the bound is the budget
                except Unresolved:
                    continue
            sm = re.search(r"sizeof\s*\(\s*(struct\s+\w+)\s*\)", mm.group(2))
            uses.append({"file": f.rel, "addr": a, "end": end, "from": "assert", "type": sm.group(1) if sm else None,
                         "line": f.line(m.start()), "cond": list(f.cond(m.start()))})
    s_dir = os.path.join(path, "src")
    for fn in sorted(os.listdir(s_dir)) if os.path.isdir(s_dir) else []:
        if fn.endswith(".S"):
            code, _b, _c = lex(open(os.path.join(s_dir, fn), errors="replace").read().replace("@", "//"))
            for m in re.finditer(r"=\s*(0[xX][0-9a-fA-F]+)|\.word\s+(0[xX][0-9a-fA-F]+)|\.equ\s+\w+\s*,\s*(0[xX][0-9a-fA-F]+)",
                                 code):
                a = int(m.group(1) or m.group(2) or m.group(3), 16)
                if lo <= a < hi:
                    uses.append({"file": "src/" + fn, "addr": a, "size": 4, "from": "asm",
                                 "line": code.count("\n", 0, m.start()) + 1, "cond": []})
    for tg in tags:                                     # a word no source states: its tag
        if tg["kind"] == "ram" and lo <= tg.get("at", -1) < hi:
            uses.append({"file": tg["file"], "addr": tg["at"], "size": tg.get("size") or 4, "from": "tag",
                         "line": tg["line"], "cond": []})
    # one range per (file, start): an assert's end wins, else the cast's size, else the room to the next start
    rng = {}
    for u in uses:
        k = (u["file"], u["addr"])
        r = rng.setdefault(k, {"file": u["file"], "module": module_of(u["file"]), "start": u["addr"], "end": None,
                               "from": None, "line": u["line"], "cond": u["cond"], "types": [], "names": []})
        if u.get("type", "") and u["type"].startswith("struct") and u["type"] not in r["types"]:
            r["types"].append(" ".join(u["type"].split()))
        if u.get("name") and u["name"] not in r["names"]:
            r["names"].append(u["name"])                # the macro that names it: the same thing in another file
        if u.get("end") is not None and (r["from"] != "assert" or u["end"] < r["end"]):
            r["end"], r["from"] = u["end"], "assert"
        elif u.get("size") and r["from"] not in ("assert",) and (r["end"] is None or u["addr"] + u["size"] > r["end"]):
            r["end"], r["from"] = u["addr"] + u["size"], u["from"]
    # a struct cast with no assert: its size from the compiler, when there is one
    need = {}
    for u in uses:
        r = rng[(u["file"], u["addr"])]
        if r["end"] is None and u.get("type", "").startswith("struct") and u["file"] in t.files:
            need.setdefault(u["file"], {})[u["addr"]] = u["type"]
    for fr, want in need.items():
        got = probe(t.files[fr], {f"sizeof({ty})" for ty in want.values()})
        for a, ty in want.items():
            if got.get(f"sizeof({ty})"):
                rng[(fr, a)]["end"], rng[(fr, a)]["from"] = a + got[f"sizeof({ty})"], f"sizeof({ty}) by the compiler"
    starts = sorted({r["start"] for r in rng.values()})
    for r in rng.values():
        if r["end"] is None:
            nxt = [s for s in starts if s > r["start"]]
            r["end"], r["from"] = (min(nxt) if nxt else hi), "room up to the next start"
    return sorted(rng.values(), key=lambda r: (r["start"], r["file"]))


# ------------------------------------------------------------------------------------------------- in-tree rules

def exclusive(c1, c2, pairs=()):
    """two #if conditions that cannot hold in one build: X against !X, or two flags an #error keeps apart"""
    s1, s2 = set(c1), set(c2)
    if any("!" + x in s2 for x in s1) or any("!" + x in s1 for x in s2):
        return True
    return any(frozenset((x, y)) in pairs for x in s1 for y in s2)


def ordered(man):
    return sorted((p for p in man["patches"] if p["applied"]), key=lambda p: tuple(p["order"]))


def overlaps(man):
    """(earlier, later, chained) for every two modules' patches on the same stock bytes, in patch.py's order;
    chained = the later one's stock bytes are what the earlier one wrote there"""
    img, out = {}, {}
    for p in ordered(man):
        old, new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        for i in range(len(new)):
            a = p["addr"] + i
            if a in img and img[a][1]["module"] != p["module"]:
                q = img[a][1]
                k = (id(q), id(p))
                ok = i < len(old) and old[i] == img[a][0]
                out[k] = (q, p, out.get(k, (q, p, True))[2] and ok)
            img[a] = (new[i], p)
    return list(out.values())


def final_image(man, fake):
    """per stock byte address: (what the patched image holds there, the patch that wrote it last)"""
    img = {}
    for p in ordered(man):
        for a, tk in tokens(p, fake).items():
            img[a] = (tk, p)
    return img


def check_tree(man):
    """what one tree must never hold: [(rule, text)]"""
    bad = []
    takes = {a for v in man["takes"].values() for a in v}
    pairs = {frozenset(x) for x in man.get("exclusive_flags", [])}
    # parameter ids: one parameter per id, one id per xml name
    by_id = {}
    for p in man["params"]:
        by_id.setdefault(p["id"], []).append(p)
    for i, ps in sorted(by_id.items()):
        ident = {p["xml"] or f"{p['file']}:{p['func']}" for p in ps}
        if len(ident) > 1 and not all(exclusive(a["cond"], b["cond"], pairs) for a in ps for b in ps if a is not b and a["xml"] != b["xml"]):
            bad.append(("param-id", f"id {h(i)} registered for {len(ident)} parameters: " +
                        ", ".join(f"{p['xml'] or '?'} ({p['file']}:{p['line']})" for p in ps)))
        if i >= 500:
            bad.append(("param-id", f"id {h(i)} ({ps[0]['file']}:{ps[0]['line']}) is past the registry's 500 slots"))
    by_xml = {}
    for p in man["params"]:
        if p["xml"]:
            by_xml.setdefault(p["xml"], set()).add(p["id"])
    for x, ids in sorted(by_xml.items()):
        if len(ids) > 1:
            bad.append(("xml-name", f"xml name {x!r} on {len(ids)} ids: {', '.join(h(i) for i in sorted(ids))}"))
    # a module's copy of its own id under another name (as clipwin_b2.c's B2_P_SLIP for clipwin.c's P_SLIP was) that no
    # longer holds the registered value: the read lands on whatever parameter has that id now
    for u in man.get("uses", []):
        for p in man["params"]:
            n, m = u.get("id_name"), p.get("id_name")
            if n and m and p["module"] == u["module"] and (n == m or n.endswith("_" + m)) and p["id"] != u["id"]:
                now = ", ".join(sorted({q["xml"] or "?" for q in by_id.get(u["id"], [])})) or "no parameter of this tree"
                bad.append(("param-use", f"{u['file']}:{u['line']} reads {n} = {h(u['id'])} through {u['call']}, but "
                                         f"{p['file']}:{p['line']} registers {m} at {h(p['id'])}; {h(u['id'])} is {now}"))
    # SDRAM parts: no two claims overlap unless one is declared inside the other or the builds exclude each other
    parts = man["sdram"]["parts"]
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if a["offset"] < b["offset"] + b["size"] and b["offset"] < a["offset"] + a["size"] and a["size"] and b["size"]:
                if a["nested_in"] == b["name"] or b["nested_in"] == a["name"] or exclusive(a["cond"], b["cond"], pairs):
                    continue
                bad.append(("sdram", f"{a['name']} ({a['file']}) [{h(a['offset'])}, {h(a['offset'] + a['size'])}) and "
                                     f"{b['name']} ({b['file']}) [{h(b['offset'])}, {h(b['offset'] + b['size'])}) overlap"))
        blk = man["sdram"]["block"]
        if blk is not None and a["offset"] + a["size"] > blk:
            bad.append(("sdram", f"{a['name']} ({a['file']}) ends at {h(a['offset'] + a['size'])}, past the block's {h(blk)}"))
        core = man["sdram"]["core"]
        if core is not None and core != blk and a["accessor"] == "master_block" and a["offset"] + a["size"] > core:
            bad.append(("sdram", f"{a['name']} ({a['file']}) is reached through master_block() but ends at "
                                 f"{h(a['offset'] + a['size'])}, past the core's {h(core)} (the tail is absent on a unit without the payload)"))
    # backup SRAM, patch RAM: ranges of two modules never overlap, unless a `resources: shares at=.. with=a,b` tag
    # says they take turns there (one compressor runs at a time) or one reads what the other writes; none ends past
    # its memory
    def declared(a, b):
        return any(tg["kind"] == "shares" and {a["module"], b["module"]} <= set(tg.get("with", []))
                   and max(a["start"], b["start"]) <= tg.get("at", -1) < min(a["end"], b["end"]) for tg in man["tags"])

    for rule, top, what in (("bkpsram", BKP_HI, "backup SRAM"), ("patchram", PATCH_HI, "patch RAM")):
        rs = man.get(rule, [])
        for i, a in enumerate(rs):
            if a["end"] > top:
                bad.append((rule, f"{a['file']} [{h(a['start'])}, {h(a['end'])}) ({a['from']}) ends past {what}'s {h(top)}"))
            for b in rs[i + 1:]:
                if declared(a, b):
                    continue
                if a["module"] != b["module"] and a["start"] < b["end"] and b["start"] < a["end"] and not exclusive(a["cond"], b["cond"], pairs):
                    if (a["start"], a["end"]) == (b["start"], b["end"]) and set(a["types"]) & set(b["types"]):
                        continue                                # one structure, named in two files
                    bad.append((rule, f"{a['file']} [{h(a['start'])}, {h(a['end'])}) ({a['from']}) and {b['file']} "
                                      f"[{h(b['start'])}, {h(b['end'])}) ({b['from']}) overlap"))
    # stock bytes: one module per byte, unless it declares it takes the site, or its stock bytes are the other
    # module's new ones (a chain patch.py accepts: master.py on comp.py's Tools page)
    ap = [p for p in man["patches"] if p["applied"]]
    for a, b, chained in overlaps(man):
        if chained:
            continue
        span = range(max(a["addr"], b["addr"]), min(a["end"], b["end"]))
        if any(x in man["takes"].get(b["module"], []) or x in man["takes"].get(a["module"], []) for x in span):
            continue
        bad.append(("site", f"{h(span[0])}: patched by {a['module']}.py ({a['target'] or a['new']}) and "
                            f"{b['module']}.py ({b['target'] or b['new']})"))
    for tg in man["tags"]:
        if tg["kind"] == "wants":
            for p in ap:
                if p["addr"] <= tg.get("site", -1) < p["end"] and tg.get("site") not in takes:
                    bad.append(("wants", f"{h(tg['site'])} is wanted by {tg.get('by', '?')} ({tg['file']}:{tg['line']}) "
                                         f"and patched by {p['module']} -> {p['target']}"))
    # stores: stock's entries + ours within the cap; a hooked stock store_add no tag names fills a store nobody counts
    for u in man.get("untagged_store_sites", []):
        bad.append(("store", f"the stock store_add at {h(u['site'])} is hooked by {u['entry']} ({u['entries']} entries) and "
                             f"no `resources: store` tag names that site: no store's cap counts them"))
    for s in man["stores"]:
        if not s["caps_agree"]:
            bad.append(("store", f"{s['name']} store: its cap sites disagree: {s['caps']}"))
        if s["cap"] is not None and s["stock"] is not None and s["stock"] + s["added"] > s["cap"]:
            bad.append(("store", f"{s['name']} store: stock's {s['stock']} + {s['added']} added = "
                                 f"{s['stock'] + s['added']} > cap {s['cap']}"))
    # bank 1
    b = man.get("build")
    if b and b.get("built") and b.get("cave_length") and b.get("cave_used") and b["cave_used"] > b["cave_length"]:
        bad.append(("bank1", f"the cave holds {b['cave_used']} B of {b['cave_length']}"))
    return bad


# ------------------------------------------------------------------------------------------------ two-tree report

def report(ours, theirs, base=None, stock=None):
    col = []                                                # collisions

    def add(kind, what, o, t, detail=""):
        col.append({"kind": kind, "what": what, "ours": o, "theirs": t, "detail": detail})

    # ---- parameter ids
    def idmap(m):
        d = {}
        for p in m["params"]:
            d.setdefault(p["id"], []).append(p)
        return d
    io, it = idmap(ours), idmap(theirs)

    def used(m, i):
        us = [u for u in m.get("uses", []) if u["id"] == i]
        return ", ".join(f"{u['file']}:{u['line']}" + (f" ({u['id_name']})" if u["id_name"] else "") for u in us)

    for i in sorted(set(io) & set(it)):
        xo = {p["xml"] or f"{p['file']}:{p['func']}" for p in io[i]}
        xt = {p["xml"] or f"{p['file']}:{p['func']}" for p in it[i]}
        # a row when the two sides do not hold the same parameters there: none in common, or one side adds another
        if xo != xt and len(xo | xt) > 1:
            uo, ut = used(ours, i), used(theirs, i)
            add("param-id", f"id {h(i)}",
                "; ".join(f"{p['xml']} ({p['label']}) {p['file']}:{p['line']} {p['func']}" for p in io[i]),
                "; ".join(f"{p['xml']} ({p['label']}) {p['file']}:{p['line']} {p['func']}" for p in it[i]),
                ("" if not xo & xt else f"both hold {', '.join(sorted(xo & xt))}, and one side adds another")
                + (f"{'; ' if xo & xt else ''}read here at: ours {uo or '-'}; theirs {ut or '-'} (they move with the id)"
                   if uo or ut else ""))
    for side, m, other, oid in (("ours", ours, theirs, it), ("theirs", theirs, ours, io)):
        mine = idmap(m)
        for u in m.get("uses", []):
            if u["id"] in oid and u["id"] not in mine:
                o = f"{u['file']}:{u['line']} {u['func']} reads {h(u['id'])}" + (f" ({u['id_name']})" if u["id_name"] else "") \
                    + " (registered by no module here: stock's)"
                t_ = "; ".join(f"{p['xml']} {p['file']}:{p['line']}" for p in oid[u["id"]])
                add("param-use", f"id {h(u['id'])}", o if side == "ours" else t_, t_ if side == "ours" else o,
                    "one side reads an id the other registers for its own parameter")
    xo = {}
    for p in ours["params"]:
        if p["xml"]:
            xo.setdefault(p["xml"], set()).add(p["id"])
    for p in theirs["params"]:
        if p["xml"] and p["xml"] in xo and p["id"] not in xo[p["xml"]]:
            add("xml-name", f"xml {p['xml']!r}", ", ".join(h(i) for i in sorted(xo[p["xml"]])), f"{h(p['id'])} {p['file']}:{p['line']}",
                "one parameter on two ids: a preset saved by one side loads into the other's id")

    # ---- patched stock bytes
    fo = {int(a): n for a, n in ours["_fake"].items()}
    ft = {int(a): n for a, n in theirs["_fake"].items()}
    po = [p for p in ours["patches"] if p["applied"]]
    ptt = [p for p in theirs["patches"] if p["applied"]]
    img_o, img_t = final_image(ours, fo), final_image(theirs, ft)
    pairs = {}
    for a in sorted(set(img_o) & set(img_t)):
        (to, p), (tt, q) = img_o[a], img_t[a]
        e = pairs.setdefault((id(p), id(q)), {"p": p, "q": q, "ov": [], "diff": []})
        e["ov"].append(a)
        if to != tt:
            e["diff"].append(a)
    for e in pairs.values():
        p, q, ov, diff = e["p"], e["q"], e["ov"], e["diff"]
        if diff and (p["kind"] == "call" or q["kind"] == "call"):
            add("site", f"call site {h(p['addr'] if p['kind'] == 'call' else q['addr'])}",
                f"{p['module']}.py: bl {h(p['callee']) if p['callee'] else '?'} -> {p['target']}",
                f"{q['module']}.py: bl {h(q['callee']) if q['callee'] else '?'} -> {q['target']}",
                "a BL takes one target: a chain or a choice")
        elif diff:
            wo = [w for w in data_words(p) if w[0] in diff or w[0] + 1 in diff]
            wt = [w for w in data_words(q) if w[0] in diff or w[0] + 1 in diff]
            add("data", f"stock bytes {h(min(diff))}..{h(max(diff) + 1)}",
                f"{p['module']}.py @{h(p['addr'])}: " + (", ".join(f"{h(a)}: {h(o)}->{h(n)}" for a, o, n in wo) or p["new"]),
                f"{q['module']}.py @{h(q['addr'])}: " + (", ".join(f"{h(a)}: {h(o)}->{h(n)}" for a, o, n in wt) or q["new"]),
                "two tables write different values into the same stock bytes (a page slot, a constant)")
        elif p["module"] != q["module"]:
            add("site-module", f"stock bytes {h(ov[0])}", f"{p['module']}.py", f"{q['module']}.py",
                "the same bytes from two modules: patch.py refuses the second in a merged tree")
    # a stock function one side calls (FN() / B2_FN()) whose first bytes the other side patches: in the merged image
    # that call lands in the other side's hook (their slice.py's trampoline on 0x08064A94 -> sel_setup, which our
    # clipwin.c calls as fw_recompute)
    for side, m, mimg, oimg in (("ours", ours, img_o, img_t), ("theirs", theirs, img_t, img_o)):
        seen = set()
        for b in m.get("binds", []):
            hit = [a for a in range(b["addr"], b["addr"] + 4) if a in oimg and (a not in mimg or mimg[a][0] != oimg[a][0])]
            if not hit or (b["addr"], b["module"]) in seen:
                continue
            seen.add((b["addr"], b["module"]))
            q = oimg[hit[0]][1]
            mine = f"{b['file']}:{b['line']} {b['name']} calls stock {h(b['addr'])}"
            theirs_ = f"{q['module']}.py patches {h(q['addr'])}: " + (f"-> {q['target']}" if q["target"] else q["new"])
            add("binds", f"stock function {h(b['addr'])}", mine if side == "ours" else theirs_,
                theirs_ if side == "ours" else mine, "a call into stock that the other side's patch turns into its hook")
    for side, mine, other, oname in (("ours", ours, ptt, "theirs"), ("theirs", theirs, po, "ours")):
        for tg in mine["tags"]:
            if tg["kind"] != "wants":
                continue
            for p in other:
                if p["addr"] <= tg.get("site", -1) < p["end"]:
                    o = f"wanted by {tg.get('by', '?')} ({tg['file']}:{tg['line']}): bl {h(tg.get('callee'))}" \
                        if tg.get("callee") else f"wanted by {tg.get('by', '?')} ({tg['file']}:{tg['line']})"
                    t = f"{p['module']}.py: bl {h(p['callee']) if p['callee'] else '?'} -> {p['target']}"
                    add("wants", f"call site {h(tg['site'])}", o if side == "ours" else t, t if side == "ours" else o,
                        "a planned hook (a `resources: wants` tag) on a site the other tree already patches")

    # ---- stores
    stores = []
    names = {s["name"] for s in ours["stores"]} | {s["name"] for s in theirs["stores"]}
    tags = {t_["name"]: t_ for t_ in theirs["tags"] + ours["tags"] if t_["kind"] == "store"}
    for n in sorted(names):
        so = next((s for s in ours["stores"] if s["name"] == n), None)
        st = next((s for s in theirs["stores"] if s["name"] == n), None)
        if st is None:
            st = stores_of(theirs, [tags[n]], stock)[0]
        if so is None:
            so = stores_of(ours, [tags[n]], stock)[0]
        eo = {(e["id"], e["func"]) for e in so["entries"]}
        et = {(e["id"], e["func"]) for e in st["entries"]}
        stock = so["stock"] if so["stock"] is not None else st["stock"]
        caps = {c for c in (so["cap"], st["cap"]) if c is not None}
        merged = len(eo | et)
        row = {"name": n, "stock": stock, "ours": len(eo), "theirs": len(et), "both": len(eo & et), "merged": merged,
               "cap_ours": so["cap"], "cap_theirs": st["cap"], "only_ours": sorted(eo - et), "only_theirs": sorted(et - eo)}
        stores.append(row)
        if stock is not None and caps and stock + merged > min(caps):
            add("store", f"{n} store", f"{stock} + {len(eo)} = {stock + len(eo)} of {so['cap']}",
                f"{stock} + {len(et)} = {stock + len(et)} of {st['cap']}",
                f"merged: stock {stock} + {merged} = {stock + merged} > cap {min(caps)} "
                f"(only ours: {', '.join(h(i) for i, _ in sorted(eo - et))}; only theirs: {', '.join(h(i) for i, _ in sorted(et - eo))})")

    # a hooked store_add neither tree's tags name: its entries are in no store above, so the sums are short
    tagged = {a for tg in ours["tags"] + theirs["tags"] if tg["kind"] == "store" for a in tg.get("sites", [])}
    untagged = {side: [f"the stock store_add at {h(c['site'])} is hooked by {c['entry']} ({c['entries']} entries) and no "
                       f"`resources: store` tag of either tree names it: no store sum above counts them"
                       for c in m.get("untagged_store_sites", []) if c["site"] not in tagged]
                for side, m in (("ours", ours), ("theirs", theirs))}

    # ---- SDRAM
    sd = sdram_report(ours["sdram"], theirs["sdram"], add)

    # ---- backup SRAM: two ranges that overlap are one thing when they share a module, a struct type or the macro
    # that names them (code moved between files: master.c's GLBUF is vhs.c's upstream); a pair the other tree
    # already holds side by side is that tree's own (its check judges it); anything else collides, equal ranges too
    def ident(r):
        return {("module", r["module"])} | {("type", x) for x in r["types"]} | {("name", x) for x in r.get("names", [])}

    def holds(m, r, near, kind):
        """m has a range that is r's thing and overlaps near"""
        return any(ident(x) & ident(r) and x["start"] < near["end"] and near["start"] < x["end"] for x in m.get(kind, []))

    def shared(a, b):
        return any(tg["kind"] == "shares" and {a["module"], b["module"]} <= set(tg.get("with", []))
                   and max(a["start"], b["start"]) <= tg.get("at", -1) < min(a["end"], b["end"])
                   for tg in ours["tags"] + theirs["tags"])

    def said(r):
        x = r["types"] + r.get("names", [])
        return f"{r['file']} [{h(r['start'])}, {h(r['end'])}) ({r['from']}{'; ' + ', '.join(x) if x else ''})"

    for kind, what in (("bkpsram", "backup SRAM"), ("patchram", "patch RAM")):
        for a in ours.get(kind, []):
            for b in theirs.get(kind, []):
                if not (a["start"] < b["end"] and b["start"] < a["end"]) or ident(a) & ident(b) or shared(a, b):
                    continue
                if holds(theirs, a, b, kind) or holds(ours, b, a, kind):
                    continue
                add(kind, f"{what} {h(max(a['start'], b['start']))}", said(a), said(b),
                    f"two modules on the same {what} bytes")

    # ---- bank 1
    bk = bank_report(ours.get("build"), theirs.get("build"), base, add)
    return {"ours": ours["tree"], "theirs": theirs["tree"], "base": base["tree"] if base else None,
            "collisions": col, "stores": stores, "sdram": sd, "bank": bk,
            "unread": {"ours": ours["warnings"] + untagged["ours"], "theirs": theirs["warnings"] + untagged["theirs"]}}


def sdram_report(o, t, add):
    po = {p["name"]: p for p in o["parts"]}
    pt = {p["name"]: p for p in t["parts"]}

    def tile(parts, block, p):
        nxt = [q["offset"] for q in parts.values() if q["offset"] > p["offset"]]
        return (min(nxt) if nxt else block) - p["offset"]

    out = {"ours": {"block": o["block"], "core": o["core"], "bound": o.get("bound")},
           "theirs": {"block": t["block"], "core": t["core"], "bound": t.get("bound")},
           "moved": [], "new_theirs": [], "new_ours": []}
    for n in sorted(set(po) & set(pt)):
        if po[n]["offset"] != pt[n]["offset"]:
            out["moved"].append({"name": n, "file": po[n]["file"], "ours": po[n]["offset"], "theirs": pt[n]["offset"]})

    def extra(mine, other, mblock, oblock, key):
        """other's parts that are not mine: where they ride in my layout (the slack behind the paired part before
        them), or what they add to my block"""
        total, core_add = 0, 0
        for n, p in sorted(other.items(), key=lambda x: x[1]["offset"]):
            if n in mine:
                continue
            if p.get("nested_in") and p["nested_in"] in other and p["nested_in"] not in mine:
                continue                                  # rides inside another new part
            prev = [q for q in other.values() if q["name"] in mine and q["offset"] <= p["offset"]]
            anchor = max(prev, key=lambda q: q["offset"]) if prev else None
            rec = {"name": n, "file": p["file"], "offset": p["offset"], "size": p["size"], "size_from": p["size_from"],
                   "accessor": p["accessor"]}
            lands = [q["name"] for q in mine.values() if q["offset"] < p["offset"] + p["size"] and p["offset"] < q["offset"] + q["size"]]
            rec["lands_on"] = lands
            rec["past_block"] = mblock is not None and p["offset"] + p["size"] > mblock
            if anchor:
                rel = p["offset"] - anchor["offset"]
                room = tile(mine, mblock, mine[anchor["name"]])
                rec["anchor"] = anchor["name"]
                rec["fits_in_slack"] = rel + p["size"] <= room
                rec["anchor_accessor"] = mine[anchor["name"]]["accessor"]
            else:
                rec["fits_in_slack"] = False
            if not rec["fits_in_slack"]:
                total += p["size"]
                if p["accessor"] == "master_block":
                    core_add += p["size"]
            out[key].append(rec)
        for n in sorted(set(mine) & set(other)):
            # a part both have: what the other side's version really uses (sizeof, else its claim) against the room
            # this layout gives it
            grow = other[n].get("used", other[n]["size"]) - tile(mine, mblock, mine[n])
            if grow > 0:
                total += grow
                out.setdefault(key + "_grown", []).append({"name": n, "by": grow})
        return total, core_add

    eo, co = extra(po, pt, o["block"], t["block"], "new_theirs")
    et, ct = extra(pt, po, t["block"], o["block"], "new_ours")
    out["merged_on_ours"] = (o["block"] or 0) + eo
    out["merged_on_theirs"] = (t["block"] or 0) + et
    out["core_on_ours"] = (o["core"] or 0) + co if o["core"] != o["block"] else None
    for r in out["new_theirs"]:
        if r["lands_on"] or r["past_block"]:
            add("sdram", f"their {r['name']} [{h(r['offset'])}, {h(r['offset'] + r['size'])})",
                (", ".join(r["lands_on"]) or "-") + (" ; past our block's end " + h(o["block"]) if r["past_block"] else ""),
                f"{r['file']} ({r['size_from']})",
                "their offset taken as is lands on these parts of our layout")
    for r in out["new_ours"]:
        if r["lands_on"] or r["past_block"]:
            add("sdram", f"our {r['name']} [{h(r['offset'])}, {h(r['offset'] + r['size'])})", f"{r['file']} ({r['size_from']})",
                (", ".join(r["lands_on"]) or "-") + (" ; past their block's end " + h(t["block"]) if r["past_block"] else ""),
                "our offset taken as is lands on these parts of their layout")
    if out["moved"]:
        add("sdram", f"{len(out['moved'])} parts at different offsets",
            ", ".join(f"{m['name']} {h(m['ours'])}" for m in out["moved"]),
            ", ".join(f"{m['name']} {h(m['theirs'])}" for m in out["moved"]),
            "the two layouts differ: a merge keeps one master.c and re-bases the other side's modules")
    # boot-time allocations other than the block that only one side makes (stretch.c's own area)
    key = lambda a: (a["file"], a["func"])                          # noqa: E731
    ko, kt = {key(a) for a in o["allocations"]}, {key(a) for a in t["allocations"]}
    out["allocations_theirs_only"] = [a for a in t["allocations"] if key(a) not in ko]
    out["allocations_ours_only"] = [a for a in o["allocations"] if key(a) not in kt]
    also = "; ".join(f"their {a['file']}:{a['line']} {a['func']} takes its own {'/'.join(h(x) for x in a['sizes']) or '?'} at boot"
                     for a in out["allocations_theirs_only"])
    lim = (o.get("bound") or {}).get("value", o["block"])
    if o["block"] and out["merged_on_ours"] > lim:
        add("sdram", "block size", f"{h(o['block'])}" + (f" (master.c:{o['bound']['line']}: {o['bound']['assert']})" if o.get("bound") else ""),
            h(t["block"]), f"merged needs {h(out['merged_on_ours'])} on our layout, {h(out['merged_on_theirs'])} on theirs"
            + (f"; our core {h(o['core'])} -> {h(out['core_on_ours'])}" if out["core_on_ours"] else "") + (f"; {also}" if also else ""))
    return out


def bank_report(bo, bt, base, add):
    if not (bo and bt and bo.get("built") and bt.get("built")):
        return {"note": "build both trees (--build) for the bank-1 estimate"}
    bb = base.get("build") if base else None
    objs = sorted(set(bo["objects"]) | set(bt["objects"]) | (set(bb["objects"]) if bb and bb.get("built") else set()))
    rows, m1, m2, hi1, shaky = [], 0, 0, 0, []
    for ob in objs:
        o = bo["objects"].get(ob, {"bank1": 0, "bank2": 0})
        t = bt["objects"].get(ob, {"bank1": 0, "bank2": 0})
        if bb and bb.get("built"):
            b = bb["objects"].get(ob, {"bank1": 0, "bank2": 0})
            e1 = max(0, o["bank1"] + t["bank1"] - b["bank1"])
            e2 = max(0, o["bank2"] + t["bank2"] - b["bank2"])
            # both sides shrank it from the base: perhaps the same move made twice (Munchi's engine to bank 2), which a
            # merge holds once; the sum then undercounts, so the high end takes the larger side
            both_down = all(b["bank1"] - x >= max(256, b["bank1"] // 10) for x in (o["bank1"], t["bank1"])) \
                and e1 < max(o["bank1"], t["bank1"])
        else:
            b, e1, e2, both_down = None, max(o["bank1"], t["bank1"]), max(o["bank2"], t["bank2"]), False
        m1 += e1
        m2 += e2
        hi1 += max(o["bank1"], t["bank1"]) if both_down else e1
        if both_down:
            shaky.append(ob)
        rows.append({"object": ob, "ours": o["bank1"], "theirs": t["bank1"], "base": b["bank1"] if b else None,
                     "merged": e1, "both_shrank": both_down, "ours_b2": o["bank2"], "theirs_b2": t["bank2"], "merged_b2": e2})
    cap = bo.get("cave_length") or bt.get("cave_length")
    res = {"method": "ours + theirs - base, per object" if bb and bb.get("built") else "the larger side, per object",
           "objects": rows, "merged_bank1": m1, "merged_bank1_high": hi1, "both_shrank": shaky, "merged_bank2": m2,
           "cave_length": cap, "ours_bank1": bo.get("cave_used"), "theirs_bank1": bt.get("cave_used")}
    if cap and max(m1, hi1) > cap:
        span = (f"{m1}..{hi1}" if hi1 != m1 else f"{m1}")
        over = (f"{m1 - cap:+}..{hi1 - cap:+}" if hi1 != m1 else f"{m1 - cap:+}")
        add("bank1", "flash bank 1 (the cave)", f"{bo.get('cave_used')} B", f"{bt.get('cave_used')} B",
            f"merged estimate {span} B of {cap} B, {over} B against it"
            + (": the low end fits, the high end does not" if m1 <= cap < hi1 else "") + f" ({res['method']}"
            + (f"; both sides shrank {', '.join(shaky)}: the high end counts the larger side" if shaky else "") + ")")
    return res


# ------------------------------------------------------------------------------------------------------ output

def md_scan(man):
    L = [f"# Resources of {man['tree']}", ""]
    mods = {}
    for p in man["params"]:
        mods.setdefault(p["module"], {}).setdefault("ids", []).append(p)
    store_of = {}
    for s in man["stores"]:
        for e in s["entries"]:
            store_of.setdefault(e["func"], set()).add(s["name"])
    for a in man["store_adds"]:
        mods.setdefault(a["module"], {}).setdefault("adds", []).append(a)
    for p in man["patches"]:
        mods.setdefault(p["module"], {}).setdefault("patches", []).append(p)
    for p in man["sdram"]["parts"]:
        mods.setdefault(p["module"], {}).setdefault("sdram", []).append(p)
    for r in man["bkpsram"]:
        mods.setdefault(r["module"], {}).setdefault("bkp", []).append(r)
    for r in man.get("patchram", []):
        mods.setdefault(r["module"], {}).setdefault("pram", []).append(r)
    objs = (man.get("build") or {}).get("objects") or {}
    for ob, v in objs.items():
        mods.setdefault(module_of(ob.replace(".o", ".c")), {}).setdefault("objs", []).append((ob, v))
    sd = man["sdram"]
    L += [f"SDRAM block {h(sd['block'])}" + (f" (core {h(sd['core'])})" if sd["core"] != sd["block"] else "") +
          (f", master.c:{sd['bound']['line']} pins it: `{sd['bound']['assert']}`" if sd.get("bound") else ""), ""]
    if sd["allocations"]:
        L += ["Boot-time allocations: " + "; ".join(f"{a['file']}:{a['line']} {a['func']}({a['expr']}) = "
                                                     f"{'/'.join(h(s) for s in a['sizes'])}" for a in sd["allocations"]), ""]
    for s in man["stores"]:
        L += [f"Store **{s['name']}** ({s['tag']}): stock {s['stock']} + {s['added']} added = "
              f"{(s['stock'] or 0) + s['added']} of cap {s['cap']} (cap sites: " +
              ", ".join(f"{a} = {v} by {who}" for a, v, who in s["caps"]) + ")", ""]
    b = man.get("build")
    if b and b.get("built"):
        L += [f"Bank 1: {b['cave_used']} of {b['cave_length']} B; bank 2: {b['bank2_bytes']} B ({b['note']})", ""]
    for mname in sorted(mods):
        d = mods[mname]
        L += [f"## {mname}", ""]
        for p in d.get("ids", []):
            L.append(f"- id {h(p['id'])} {p['kind']} {p['label']!s} xml {p['xml']!s} ({p['file']}:{p['line']} {p['func']})")
        by_fn = {}
        for a in d.get("adds", []):
            by_fn.setdefault(a["func"], []).append(a["id"])
        for fn, ids in by_fn.items():
            where = ", ".join(sorted(store_of.get(fn, []))) or "no tagged store reaches it"
            L.append(f"- store entries from {fn} ({where}): {len(ids)}: " + ", ".join(h(i) for i in ids))
        for p in d.get("sdram", []):
            L.append(f"- SDRAM {p['name']} [{h(p['offset'])}, {h(p['offset'] + p['size'])}) via {p['accessor']}() "
                     f"({p['size_from']}; {p['file']})")
        for r in d.get("bkp", []):
            L.append(f"- backup SRAM [{h(r['start'])}, {h(r['end'])}) ({r['from']}; {r['file']}:{r['line']})")
        for r in d.get("pram", []):
            L.append(f"- patch RAM [{h(r['start'])}, {h(r['end'])}) ({r['from']}; {r['file']}:{r['line']})")
        for p in d.get("patches", []):
            na = "" if p["applied"] else " (in no applied set)"
            if p["kind"] == "call":
                L.append(f"- site {h(p['addr'])}: bl {h(p['callee']) if p['callee'] else '?'} -> {p['target']}{na}")
            elif p["kind"] == "pointer":
                L.append(f"- word {h(p['addr'])}: {h(p['callee'])} -> &{p['target']}{na}")
            else:
                ws = p.get("words") or []
                L.append(f"- data {h(p['addr'])}..{h(p['end'])}: " + (", ".join(f"{h(a)} {h(o)}->{h(n)}" for a, o, n in ws[:12])
                                                                       + (" …" if len(ws) > 12 else "") or "(no change)") + na)
        for t_ in man["takes"].get(mname, []):
            L.append(f"- takes {h(t_)} (TAKES)")
        for tg in man["tags"]:
            if tg["kind"] == "wants" and module_of(tg["file"]) == mname:
                L.append(f"- wants {h(tg.get('site'))} (bl {h(tg.get('callee'))}) for {tg.get('by')} ({tg['file']}:{tg['line']})")
        for ob, v in d.get("objs", []):
            L.append(f"- {ob}: bank 1 {v['bank1']} B, bank 2 {v['bank2']} B")
        L.append("")
    L += ["## Store chains (what each hooked stock store_add leads to)", ""]
    for c in man["store_chains"]:
        L.append(f"- {c['entry']} (sites {', '.join(h(s) for s in c['sites'])}): {len(c['entries'])} entries: "
                 + ", ".join(f"{h(e['id'])}" for e in c["entries"]))
    if man["warnings"]:
        L += ["", "## Not read", ""] + [f"- {w}" for w in man["warnings"]]
    return "\n".join(L) + "\n"


def md_report(r):
    L = [f"# Collisions: {r['ours']} (ours) against {r['theirs']} (theirs)", ""]
    if r.get("base"):
        L += [f"Merge base for the bank-1 estimate: {r['base']}", ""]
    for side in ("ours", "theirs"):
        if r["unread"][side]:
            L += [f"**{len(r['unread'][side])} items not read in {side}** (listed at the end): a clash can hide there.", ""]
    kinds = {}
    for c in r["collisions"]:
        kinds.setdefault(c["kind"], []).append(c)
    L += ["| kind | collisions |", "|---|---|"] + [f"| {k} | {len(v)} |" for k, v in kinds.items()] + [""]
    for k, v in kinds.items():
        L += [f"## {k}", "", "| what | ours | theirs | note |", "|---|---|---|---|"]
        for c in v:
            L.append(f"| {c['what']} | {c['ours']} | {c['theirs']} | {c['detail']} |".replace("\n", " "))
        L.append("")
    sd = r["sdram"]
    L += ["## SDRAM block", "",
          f"Ours {h(sd['ours']['block'])} (core {h(sd['ours']['core'])}), theirs {h(sd['theirs']['block'])}; merged "
          f"{h(sd['merged_on_ours'])} on our layout, {h(sd['merged_on_theirs'])} on theirs"
          + (f"; our core would grow to {h(sd['core_on_ours'])}" if sd.get("core_on_ours")
             and sd["core_on_ours"] != sd["ours"]["core"] else "") + ".", ""]
    for side in ("theirs", "ours"):
        for a in sd.get(f"allocations_{side}_only", []):
            L += [f"Only {side}: {a['file']}:{a['line']} {a['func']}({a['expr']}) = {'/'.join(h(x) for x in a['sizes']) or '?'} "
                  f"at boot, outside the block.", ""]
    if sd["new_theirs"]:
        L += ["Their parts that ours has not:", "", "| part | file | at | size | rides in our | lands on, as is |", "|---|---|---|---|---|---|"]
        for p in sd["new_theirs"]:
            L.append(f"| {p['name']} | {p['file']} | {h(p['offset'])} | {h(p['size'])} ({p['size_from']}) | "
                     f"{(p.get('anchor') + ' slack') if p.get('fits_in_slack') else 'new room'} | {', '.join(p['lands_on']) or '-'}"
                     f"{' (past our end)' if p['past_block'] else ''} |")
        L.append("")
    if sd["new_ours"]:
        L += ["Our parts that theirs has not: " + ", ".join(f"{p['name']} ({p['file']}, {h(p['size'])})" for p in sd["new_ours"]), ""]
    L += ["## Stores", "", "| store | stock | ours | theirs | both | merged | caps (ours/theirs) |", "|---|---|---|---|---|---|---|"]
    for s in r["stores"]:
        L.append(f"| {s['name']} | {s['stock']} | {s['ours']} | {s['theirs']} | {s['both']} | "
                 f"{(s['stock'] or 0) + s['merged']} | {s['cap_ours']}/{s['cap_theirs']} |")
    L.append("")
    b = r["bank"]
    if "objects" in b:
        L += ["## Flash", "", f"Bank 1: ours {b['ours_bank1']} B, theirs {b['theirs_bank1']} B, merged estimate "
              f"{b['merged_bank1']}" + (f"..{b['merged_bank1_high']}" if b["merged_bank1_high"] != b["merged_bank1"] else "")
              + f" B of {b['cave_length']} B ({b['method']}" + (f"; the high end counts the larger side of {', '.join(b['both_shrank'])}, "
                                                                 "which both sides shrank" if b["both_shrank"] else "")
              + f"). Bank 2 merged estimate {b['merged_bank2']} B.", "",
              "| object | ours | theirs | base | merged |", "|---|---|---|---|---|"]
        for o in b["objects"]:
            if o["ours"] or o["theirs"]:
                L.append(f"| {o['object']} | {o['ours']} | {o['theirs']} | {o['base'] if o['base'] is not None else ''} | {o['merged']} |")
        L.append("")
    else:
        L += ["## Flash", "", b["note"], ""]
    for side in ("ours", "theirs"):
        if r["unread"][side]:
            L += [f"## Not read in {side}", ""] + [f"- {w}" for w in r["unread"][side]] + [""]
    return "\n".join(L)


def _clean(man):
    m = {k: v for k, v in man.items() if not k.startswith("_")}
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("tree", nargs="?", default=ROOT)
    c = sub.add_parser("check")
    c.add_argument("tree", nargs="?", default=ROOT)
    r = sub.add_parser("report")
    r.add_argument("ours")
    r.add_argument("theirs")
    r.add_argument("--base", help="merge base (ref or folder): the bank-1 estimate becomes ours + theirs - base")
    for x in (s, c, r):
        x.add_argument("--build", action="store_true", help="build a copy of each tree (bank-1 bytes per object)")
        x.add_argument("--md")
        x.add_argument("--json")
    a = ap.parse_args(argv)
    # exit status: 0 clean, 1 a problem or a collision, 2 something the reader could not read (whatever else it
    # found): a clash can hide behind an unread id or patch table, so an unread tree never reads as clean
    if a.cmd in ("scan", "check"):
        p, label = open_tree(a.tree)
        man = scan(p, label, a.build, stock_image(p))
        if a.cmd == "check":
            bad = check_tree(man)
            for rule, text in bad:
                print(f"{rule}: {text}")
            for w in man["warnings"]:
                print(f"not read: {w}")
            print(f"{len(bad)} problems" + (f"; {len(man['warnings'])} not read" if man["warnings"] else ""))
            return 2 if man["warnings"] else 1 if bad else 0
        md = md_scan(man)
        if a.json:
            json.dump(_clean(man), open(a.json, "w"), indent=1, default=str)
        if a.md:
            open(a.md, "w").write(md)
        if not a.md and not a.json:
            sys.stdout.write(md)
        if man["warnings"]:
            print(f"resources.py: {len(man['warnings'])} not read in {label} (the 'Not read' list)", file=sys.stderr)
        return 2 if man["warnings"] else 0
    po, lo = open_tree(a.ours)
    pt_, lt = open_tree(a.theirs)
    stock = stock_image(po, pt_)
    mo = scan(po, lo, a.build, stock)
    mt = scan(pt_, lt, a.build, stock)
    mb = None
    if a.base:
        pb, lb = open_tree(a.base)
        mb = {"tree": lb, "build": build_info(pb, True)}
    rep = report(mo, mt, mb, stock)
    md = md_report(rep)
    if a.json:
        json.dump({"report": rep, "ours": _clean(mo), "theirs": _clean(mt)}, open(a.json, "w"), indent=1, default=str)
    if a.md:
        open(a.md, "w").write(md)
    if not a.md:
        sys.stdout.write(md)
    unread = {s: len(v) for s, v in rep["unread"].items() if v}
    line = f"{len(rep['collisions'])} collisions" + ("".join(f"; {n} not read in {s}" for s, n in unread.items())
                                                     + " (see 'Not read': a clash can hide there)" if unread else "")
    if a.md:
        print(line + f"; markdown {a.md}" + (f", JSON {a.json}" if a.json else ""))
    else:
        print(line, file=sys.stderr)
    return 2 if unread else 1 if rep["collisions"] else 0


if __name__ == "__main__":
    sys.exit(main())
