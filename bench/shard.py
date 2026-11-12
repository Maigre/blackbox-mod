#!/usr/bin/env python3
"""shard.py - fork-only (bench/, never in a PR): run one slice of a long test suite, its cases where they are.

A suite here is a script of top-level statements. Its section headers (a comment line starting '# ===' or '# ---')
cut it into parts; a suite without headers is cut between any two top-level statements. Shard I of N runs a contiguous
run of parts, loud, and, quietly (its output dropped, the suite's failure counter put back after it), every statement
of the other parts that the run reads: the assignment that reaches each name it loads, directly or through the
functions and classes it calls, and every statement in between that may change that object (a subscript or attribute
store, a method call, a function that does either). The slice and what it pulls in are worked out from the source
(ast) at every run, so the suite is never edited for it and an edited suite reshards itself. In every shard: the
imports, defs and classes, the preamble before the first header (loud in shard 1 only), and the verdict (the trailing
statements that read the failure counter: "N failed", the exit status).

  shard.py SUITE I/N               run shard I of N (1-based), from the repo root, as `python3 SUITE` would
  shard.py SUITE --plan N [-v]     print the N slices: their lines and sections, what each pulls in, est. CPU seconds
  shard.py SUITE --profile         run the whole suite statement by statement and record each statement's CPU seconds
                                   in bench/shards/SUITE.tsv (the planner's weights; keyed by a hash of the statement's
                                   text, so an edit elsewhere in the file keeps them)
  shard.py SUITE --prove N [DIR]   run the suite whole (python3 SUITE) and as its N shards, side by side; proven when
                                   the shards' output, concatenated in order, is the whole run's line for line (the
                                   verdict lines aside), so their check counts add up, and each exit status says
                                   whether its own lines hold a FAIL; logs in DIR (default out/shard-prove);
                                   --whole-log LOG takes a finished `python3 SUITE` run of the same text instead of
                                   running it (its exit status read from its lines); --compare runs nothing and
                                   compares the logs and .rc files already in DIR

The planner minimises the costliest shard, a shard's cost being the CPU seconds of everything it runs (the profile's;
a statement the profile does not hold costs nothing, and without a profile a line stands for a second). With a
profile, a statement over 2 % of the suite's seconds stands alone, so a slice may start beside it inside a section.
"""
import ast
import bisect
import builtins
import hashlib
import io
import os
import re
import subprocess
import sys
import time

HEAD = re.compile(r"^# ?(={3,}|-{3,})")
PURE = {  # methods that only read their object: a call of one changes nothing (any other call on a global may)
    "get", "keys", "values", "items", "copy", "count", "index", "find", "rfind", "startswith", "endswith", "format",
    "join", "split", "rsplit", "strip", "lstrip", "rstrip", "lower", "upper", "replace", "encode", "decode", "hex",
    "tolist", "astype", "sum", "mean", "max", "min", "argmax", "argmin", "nonzero", "round", "bit_length", "to_bytes",
    "r8", "r16", "r32", "mem_read", "reg_read", "splitlines", "isdigit", "zfill", "ljust", "rjust", "std", "ptp",
    "flatten", "ravel", "reshape", "view", "issubset", "issuperset", "union", "intersection", "difference",
}
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.ListComp, ast.SetComp, ast.DictComp,
          ast.GeneratorExp)
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
HERE = os.path.dirname(os.path.abspath(__file__))
PLANNER = open(os.path.abspath(__file__)).read()                  # a cached plan is this planner's


def base_name(node):
    """X for X, X.a, X[i], X.a[i].b ..."""
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def params(node):
    a = node.args
    return {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} | {x.arg for x in (a.vararg, a.kwarg) if x}


def own(node):
    """the nodes evaluated in node's own scope, and the scopes nested in it"""
    nodes, nested = [], []

    def add(n):
        if isinstance(n, SCOPES):
            nested.append(n)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                outer = getattr(n, "decorator_list", []) + n.args.defaults + [d for d in n.args.kw_defaults if d]
            elif isinstance(n, ast.ClassDef):
                outer = n.decorator_list + n.bases + [k.value for k in n.keywords]
            else:
                outer = [n.generators[0].iter]
            for x in outer:
                add(x)
            return
        nodes.append(n)
        for c in ast.iter_child_nodes(n):
            add(c)

    if isinstance(node, ast.Lambda):
        add(node.body)
    elif isinstance(node, DEFS):
        for st in node.body:
            add(st)
    else:
        for i, g in enumerate(node.generators):
            if i:
                add(g.iter)
            add(g.target)
            for c in g.ifs:
                add(c)
        for x in ((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)):
            add(x)
    return nodes, nested


def passed_on(call, pmut):
    """the names whose objects a call hands to a parameter its def may change (pmut: def name -> (its positional
    parameters, the ones it may change))"""
    f = call.func
    if not isinstance(f, ast.Name) or f.id not in pmut:
        return set()
    names, mut = pmut[f.id]
    out = set()
    for i, a in enumerate(call.args):
        if isinstance(a, ast.Starred):
            break
        if i < len(names) and names[i] in mut and isinstance(a, (ast.Name, ast.Attribute, ast.Subscript)):
            out.add(base_name(a))
    for kw in call.keywords:
        if kw.arg in mut and isinstance(kw.value, (ast.Name, ast.Attribute, ast.Subscript)):
            out.add(base_name(kw.value))
    return out - {None}


def param_mutations(body):
    """def name -> (its positional parameters, the parameters whose objects it may change: a subscript or attribute
    store, a method call not in PURE, through a local alias (y = p, y = p.a), or handed on to a def that does);
    a class: its __init__'s, self left out"""
    info = {}
    for s in body:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = s
        elif isinstance(s, ast.ClassDef):
            fn = next((x for x in s.body if isinstance(x, ast.FunctionDef) and x.name == "__init__"), None)
            if fn is None:
                continue
        else:
            continue
        a = fn.args
        names = [x.arg for x in a.posonlyargs + a.args]
        if isinstance(s, ast.ClassDef):
            names = names[1:]
        info[s.name] = (names, names + [x.arg for x in a.kwonlyargs], fn)
    pmut = {nm: (names, set()) for nm, (names, _, _) in info.items()}
    changed = True
    while changed:
        changed = False
        for nm, (names, allp, fn) in info.items():
            alias = {x: x for x in allp}
            for _ in range(3):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Name, ast.Attribute, ast.Subscript)):
                        b = base_name(n.value)
                        for t in n.targets:
                            if isinstance(t, ast.Name) and b in alias and t.id not in alias:
                                alias[t.id] = alias[b]
            mut = pmut[nm][1]
            before = len(mut)
            for n in ast.walk(fn):
                hit = set()
                if isinstance(n, (ast.Subscript, ast.Attribute)) and isinstance(n.ctx, (ast.Store, ast.Del)):
                    hit.add(base_name(n))
                elif isinstance(n, ast.Call):
                    if isinstance(n.func, ast.Attribute) and n.func.attr not in PURE:
                        hit.add(base_name(n.func.value))
                    hit |= passed_on(n, pmut)
                mut |= {alias[b] for b in hit if b in alias}
            changed |= len(mut) != before
    return pmut


def scope_facts(node, outer, modules, pmut):
    """a def, class, lambda or comprehension: (the global names its code reads, the global names it may bind or
    change), its nested scopes included. `outer`: the names local to the function scopes around it."""
    nodes, nested = own(node)
    locs = params(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) else set()
    decl = {g for n in nodes if isinstance(n, ast.Global) for g in n.names}
    for n in nodes:
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            locs.add(n.id)
        elif isinstance(n, ast.alias):
            locs.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            locs.add(n.name)
        elif isinstance(n, ast.Nonlocal):
            locs |= set(n.names)
    locs |= {n.name for n in nested if isinstance(n, DEFS)}
    locs -= decl

    def glob(x):
        return x not in modules and (x in decl or (x not in locs and x not in outer))
    reads, changes = set(), set()
    for n in nodes:
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, ast.Load) and glob(n.id):
                reads.add(n.id)
            elif n.id in decl:
                changes.add(n.id)
        elif isinstance(n, (ast.Subscript, ast.Attribute)) and isinstance(n.ctx, (ast.Store, ast.Del)):
            b = base_name(n)
            if b and glob(b):
                changes.add(b)
        elif isinstance(n, ast.Call):
            if isinstance(n.func, ast.Attribute) and n.func.attr not in PURE:
                b = base_name(n.func.value)
                if b and glob(b):
                    changes.add(b)
            changes |= {b for b in passed_on(n, pmut) if glob(b)}
    inner = outer if isinstance(node, ast.ClassDef) else outer | locs
    for ch in nested:
        r, c = scope_facts(ch, inner, modules, pmut)
        reads |= r
        changes |= c
    return reads, changes


class Walk:
    """one top-level statement, in evaluation order (roughly): the global names it reads before binding them, the
    names it binds, the names it binds for sure (a plain assignment at its top), the names whose objects it may change
    (a subscript or attribute store, a method call), the names it calls methods on"""

    def __init__(self, modules, pmut):
        self.modules, self.pmut = modules, pmut
        self.uses, self.binds, self.strong, self.mutates, self.methods = set(), set(), set(), set(), set()

    def nested(self, n, bound):
        r, c = scope_facts(n, set(), self.modules, self.pmut)
        self.uses |= r - bound
        self.mutates |= c - bound

    def expr(self, n, bound):
        if n is None:
            return
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, ast.Load) and n.id not in bound:
                self.uses.add(n.id)
            return
        if isinstance(n, SCOPES):               # a lambda or a comprehension: its parts evaluated here, then its body
            if isinstance(n, ast.Lambda):
                for d in n.args.defaults + [d for d in n.args.kw_defaults if d]:
                    self.expr(d, bound)
            else:
                self.expr(n.generators[0].iter, bound)
            self.nested(n, bound)
            return
        if isinstance(n, ast.NamedExpr):
            self.expr(n.value, bound)
            self.binds.add(n.target.id)
            bound.add(n.target.id)
            return
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            b = base_name(n.func.value)
            if b and b not in self.modules and b not in bound:
                self.methods.add(b)
                if n.func.attr not in PURE:
                    self.mutates.add(b)
        if isinstance(n, ast.Call):             # f(x) where f may change its parameter: a change to x
            self.mutates |= {b for b in passed_on(n, self.pmut) if b not in self.modules and b not in bound}
        for c in ast.iter_child_nodes(n):
            self.expr(c, bound)

    def store(self, t, bound, strong):
        if isinstance(t, ast.Name):
            self.binds.add(t.id)
            if strong:
                self.strong.add(t.id)
            bound.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                self.store(e, bound, strong)
        elif isinstance(t, ast.Starred):
            self.store(t.value, bound, strong)
        else:                                   # X[i] = / X.a = : reads X, changes it
            self.expr(t, bound)
            b = base_name(t)
            if b and b not in bound:
                self.mutates.add(b)

    def body(self, stmts, bound):
        for b in stmts:
            self.stmt(b, bound, False)

    def stmt(self, s, bound, top):
        if isinstance(s, ast.Assign):
            self.expr(s.value, bound)
            for t in s.targets:
                self.store(t, bound, top)
        elif isinstance(s, ast.AnnAssign):
            self.expr(s.value, bound)
            if s.value is not None:
                self.store(s.target, bound, top)
        elif isinstance(s, ast.AugAssign):
            self.expr(s.value, bound)
            if isinstance(s.target, ast.Name):
                if s.target.id not in bound:
                    self.uses.add(s.target.id)
                self.binds.add(s.target.id)
            else:
                self.store(s.target, bound, False)
        elif isinstance(s, ast.Delete):
            for t in s.targets:
                if isinstance(t, ast.Name):
                    self.binds.add(t.id)
                else:
                    self.store(t, bound, False)
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            self.expr(s.iter, bound)
            inner = set(bound)
            self.store(s.target, inner, False)
            self.body(s.body + s.orelse, inner)
        elif isinstance(s, ast.While):
            self.expr(s.test, bound)
            self.body(s.body + s.orelse, set(bound))
        elif isinstance(s, ast.If):
            self.expr(s.test, bound)
            self.body(s.body, set(bound))
            self.body(s.orelse, set(bound))
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            inner = set(bound)
            for it in s.items:
                self.expr(it.context_expr, inner)
                if it.optional_vars is not None:
                    self.store(it.optional_vars, inner, False)
            self.body(s.body, inner)
        elif isinstance(s, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            self.body(s.body, set(bound))
            for h in s.handlers:
                hb = set(bound)
                self.expr(h.type, bound)
                if h.name:
                    hb.add(h.name)
                    self.binds.add(h.name)
                self.body(h.body, hb)
            self.body(s.orelse, set(bound))
            self.body(s.finalbody, set(bound))
        elif isinstance(s, DEFS):
            for d in s.decorator_list:
                self.expr(d, bound)
            if isinstance(s, ast.ClassDef):
                for b in s.bases + [k.value for k in s.keywords]:
                    self.expr(b, bound)
            else:
                for d in s.args.defaults + [d for d in s.args.kw_defaults if d]:
                    self.expr(d, bound)
            if not top:                         # a def inside a loop or an if: count its body as run here
                self.nested(s, bound)
            self.binds.add(s.name)
            if top:
                self.strong.add(s.name)
            bound.add(s.name)
        elif isinstance(s, (ast.Import, ast.ImportFrom)):
            for a in s.names:
                nm = (a.asname or a.name).split(".")[0]
                self.binds.add(nm)
                if top:
                    self.strong.add(nm)
                bound.add(nm)
        elif isinstance(s, (ast.Global, ast.Nonlocal)):
            pass
        else:                                   # Expr, Return, Raise, Assert, Pass, Break, Continue ...
            for c in ast.iter_child_nodes(s):
                if isinstance(c, ast.expr):
                    self.expr(c, bound)


class Suite:
    def __init__(self, path):
        self.path = path
        self.src = open(path).read()
        self.lines = self.src.splitlines()
        self.body = ast.parse(self.src, path).body
        n = len(self.body)
        self.heads = [i + 1 for i, l in enumerate(self.lines) if HEAD.match(l)]
        self.first = [min([s.lineno] + [d.lineno for d in getattr(s, "decorator_list", [])]) for s in self.body]
        self.text = ["\n".join(self.lines[self.first[k] - 1:self.body[k].end_lineno]) for k in range(n)]
        # the part of a statement: how many headers stand before its first line (0: the preamble)
        self.part = [bisect.bisect_left(self.heads, f) for f in self.first]
        if self.heads:
            self.cuts = [k for k in range(1, n) if self.part[k] != self.part[k - 1] and self.part[k] > 0]
            self.start = next((k for k in range(n) if self.part[k] > 0), n)
        else:
            self.cuts, self.start = list(range(1, n)), 0
        self.preamble = set(range(self.start)) if self.heads else set()
        self.modules = {(a.asname or a.name).split(".")[0] for s in self.body if isinstance(s, ast.Import)
                        for a in s.names}
        self.always = {k for k, s in enumerate(self.body) if isinstance(s, DEFS + (ast.Import, ast.ImportFrom))}
        self.analyse()

    def analyse(self):
        body, n = self.body, len(self.body)
        self.pmut = param_mutations(body)
        self.fn = {k: scope_facts(s, set(), self.modules, self.pmut) for k, s in enumerate(body) if isinstance(s, DEFS)}
        self.defs = {}
        for k in sorted(self.fn):
            self.defs.setdefault(body[k].name, []).append(k)
        self.multi = sorted(x for x, ks in self.defs.items() if len(ks) > 1)
        ws = []
        for s in body:
            w = Walk(self.modules, self.pmut)
            w.stmt(s, set(), True)
            ws.append(w)
        # the failure counter: what a top-level `check` declares global and assigns; the verdict: the trailing
        # statements that read it and bind nothing else
        self.counters = set()
        for k, s in enumerate(body):
            if isinstance(s, ast.FunctionDef) and s.name == "check":
                self.counters |= {g for x in ast.walk(s) if isinstance(x, ast.Global) for g in x.names}
        self.counters = self.counters or {"fails"}
        self.epilogue = set()
        for k in range(n - 1, -1, -1):
            if ws[k].uses & self.counters and not (ws[k].binds | ws[k].mutates) - self.counters:
                self.epilogue.add(k)
            else:
                break
        # aliases: Y = X / X.a / X[i]: a change to the object under either name is a change under the other
        self.alias = {}
        for s in body:
            if not isinstance(s, ast.Assign):
                continue
            pairs = []
            for t in s.targets:
                if isinstance(t, ast.Name):
                    pairs.append((t.id, s.value))
                elif isinstance(t, (ast.Tuple, ast.List)) and isinstance(s.value, (ast.Tuple, ast.List)) \
                        and len(t.elts) == len(s.value.elts):
                    pairs += [(a.id, b) for a, b in zip(t.elts, s.value.elts) if isinstance(a, ast.Name)]
            for y, v in pairs:
                b = base_name(v) if isinstance(v, (ast.Name, ast.Attribute, ast.Subscript)) else None
                if b and b != y and b not in self.modules:
                    self.alias.setdefault(y, set()).add(b)
                    self.alias.setdefault(b, set()).add(y)
        self._trans = {}
        self.need, self.chg, self.strong, self.objreads, self.methods = [], [], [], [], []
        for k, w in enumerate(ws):
            refs = {x for x in w.uses if x in self.defs}
            r, c = self.trans(refs, k)
            mut = w.mutates | c
            for x in list(mut):
                mut |= self.alias.get(x, set())
            self.need.append((w.uses | r) - self.counters)
            self.chg.append((w.binds | mut) - self.counters)
            self.strong.append(w.strong)
            self.objreads.append(r - self.counters)
            self.methods.append(w.methods)
        self.by_name = {}
        for k in range(n):
            for x in self.chg[k]:
                self.by_name.setdefault(x, []).append(k)

    def def_at(self, name, k):
        """the def or class statement that binds `name` last before statement k"""
        ks = self.defs.get(name)
        if not ks:
            return None
        i = bisect.bisect_left(ks, k)
        return ks[i - 1] if i else None

    def trans(self, names, k):
        """the globals read and changed by calling (or handing on) these names at statement k, every def they reach"""
        sig = tuple(self.def_at(x, k) for x in self.multi)
        reads, changes = set(), set()
        for nm in names:
            d = self.def_at(nm, k)
            if d is None:
                continue
            key = (d, sig)
            if key not in self._trans:
                rs, cs, seen, todo = set(), set(), set(), [d]
                while todo:
                    x = todo.pop()
                    if x in seen:
                        continue
                    seen.add(x)
                    r, c = self.fn[x]
                    rs |= r
                    cs |= c
                    todo += [y for y in (self.def_at(z, k) for z in r if z in self.defs) if y is not None]
                self._trans[key] = (rs, cs)
            r, c = self._trans[key]
            reads |= r
            changes |= c
        return reads, changes

    def closure(self, loud):
        """every statement a run of `loud` (a set of statement indices) needs"""
        last = max(loud) if loud else -1
        keep = set(loud) | self.epilogue | {k for k in self.always | self.preamble if k <= last}
        todo, done = sorted(keep), set()
        while todo:
            p = todo.pop()
            if p in done:
                continue
            done.add(p)
            names, seen = set(self.need[p]), set()
            while names:
                x = names.pop()
                if x in seen:
                    continue
                seen.add(x)
                ks = self.by_name.get(x, ())
                i = bisect.bisect_left(ks, p) - 1
                while i >= 0:
                    q = ks[i]
                    if q not in keep:
                        keep.add(q)
                        todo.append(q)
                    if x in self.methods[p] and x not in self.defs:
                        names |= self.objreads[q]   # its methods, run here, read what its maker's defs read
                    if x in self.strong[q]:
                        break
                    i -= 1
        return keep

    def units(self, cost):
        """the runs of statements a shard is made of: the parts, and inside a part a statement that costs more than
        2 % of the suite stands alone, so the planner can cut around it"""
        cuts = {c for c in self.cuts if c > self.start}
        tot = sum(cost)
        for k in range(self.start, len(self.body)):
            if self.profiled and cost[k] > 0.02 * tot:
                cuts |= {k, k + 1}
        b = [self.start] + sorted(c for c in cuts if self.start < c < len(self.body)) + [len(self.body)]
        return [(b[i], b[i + 1]) for i in range(len(b) - 1) if b[i] < b[i + 1]]

    def slices(self, n):
        """n contiguous runs of units, the costliest as cheap as can be (exact, over the units):
        [(first index, end index, est. CPU s)]. Cached in out/shard-plans/ against the suite's and the profile's text."""
        cost = self.costs()
        tag = hashlib.sha1((PLANNER + self.src + repr(cost) + f"/{n}").encode()).hexdigest()[:16]
        cache = os.path.join("out", "shard-plans", f"{os.path.basename(self.path)}.{n}.{tag}")
        try:
            return [tuple(float(x) if "." in x else int(x) for x in l.split()) for l in open(cache)]
        except (OSError, ValueError):
            pass
        units = self.units(cost)
        n = max(1, min(n, len(units)))
        memo = {}

        def scost(a, b):
            if (a, b) not in memo:
                memo[(a, b)] = sum(cost[k] for k in self.closure(set(range(units[a][0], units[b - 1][1]))))
            return memo[(a, b)]
        best_ = {}

        def best(a, m):                         # units a.. as m shards: (the costliest, the cuts)
            if (a, m) not in best_:
                if m == 1:
                    best_[(a, m)] = (scost(a, len(units)), ())
                else:
                    out = (float("inf"), ())
                    for b in range(a + 1, len(units) - m + 2):
                        c = scost(a, b)
                        if c >= out[0]:
                            break
                        r, cuts = best(b, m - 1)
                        if max(c, r) < out[0]:
                            out = (max(c, r), (b,) + cuts)
                    best_[(a, m)] = out
            return best_[(a, m)]
        bounds = (0,) + best(0, n)[1] + (len(units),)
        plan = [(units[bounds[i]][0], units[bounds[i + 1] - 1][1], scost(bounds[i], bounds[i + 1]))
                for i in range(len(bounds) - 1)]
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache + f".{os.getpid()}", "w") as f:
                f.write("".join(f"{a} {b} {c:.3f}\n" for a, b, c in plan))
            os.replace(cache + f".{os.getpid()}", cache)
        except OSError:
            pass
        return plan

    def key(self, k):
        return hashlib.sha1(self.text[k].encode()).hexdigest()[:12]

    def profile_path(self):
        return os.path.join(HERE, "shards", os.path.basename(self.path) + ".tsv")

    def costs(self):
        known = {}
        try:
            for line in open(self.profile_path()):
                if line.strip() and not line.startswith("#"):
                    h, c = line.split("\t")[:2]
                    known[h] = float(c)
        except OSError:
            pass
        self.profiled = bool(known)
        if not known:
            return [float(self.body[k].end_lineno - self.first[k] + 1) for k in range(len(self.body))]
        return [known.get(self.key(k), 0.0) for k in range(len(self.body))]

    def where(self, lo, hi):
        return f"lines {self.first[lo]}-{self.body[hi - 1].end_lineno}"


def execute(suite, keep, loud, mark=None):
    """run the kept statements in file order as `python3 SUITE` would; one not loud prints nothing and leaves the
    failure counter as it found it"""
    sys.path[0] = os.path.dirname(os.path.abspath(suite.path))
    sys.argv = [suite.path]
    ns = {"__name__": "__main__", "__file__": os.path.abspath(suite.path), "__builtins__": builtins}
    out, err, null = sys.stdout, sys.stderr, io.StringIO()
    for k in sorted(keep):
        code = compile(ast.Module(body=[suite.body[k]], type_ignores=[]), suite.path, "exec")
        if k == min(suite.epilogue, default=None) and mark:
            print(mark, flush=True)
        if k in loud:
            exec(code, ns)
            continue
        saved = {c: ns[c] for c in suite.counters if c in ns}
        sys.stdout = sys.stderr = null
        try:
            exec(code, ns)
        finally:
            sys.stdout, sys.stderr = out, err
            null.seek(0)
            null.truncate()
            ns.update(saved)


def shard(path, i, n):
    s = Suite(path)
    lo, hi, c = s.slices(n)[i - 1]
    own_ = set(range(lo, hi))
    loud = own_ | s.epilogue | (s.preamble if i == 1 else set())
    keep = s.closure(own_) | loud
    print(f"     shard {i}/{n}: {s.where(lo, hi)}, {len(keep - loud - s.always - s.preamble)} statements of the other "
          f"parts run quietly, est. {c:.0f} s", flush=True)
    execute(s, keep, loud, f"     shard {i}/{n}: its verdict")


def plan(path, n, verbose):
    t0 = time.process_time()
    s = Suite(path)
    cost = s.costs()
    sl = s.slices(n)
    print(f"{path}: {len(s.body)} statements, {len(s.heads)} headers, {sum(cost):.1f} s CPU in all; profile "
          f"{'found' if os.path.exists(s.profile_path()) else 'missing (a line stands for a second)'}; "
          f"planned in {time.process_time() - t0:.1f} s")
    for i, (lo, hi, c) in enumerate(sl, 1):
        loud = set(range(lo, hi))
        pulled = sorted(s.closure(loud) - loud - s.always - s.epilogue - s.preamble)
        pc = sum(cost[k] for k in pulled)
        print(f"  {i}/{n}: {s.where(lo, hi)} ({hi - lo} statements), est. {c:.1f} s, of which {pc:.1f} s in "
              f"{len(pulled)} statements of the other parts")
        top = s.body[lo - 1].end_lineno if lo else 0
        for h in s.heads:
            if top < h <= s.body[hi - 1].end_lineno and s.lines[h - 1].startswith("# ==="):
                print(f"      {s.lines[h - 1].lstrip('# =')[:100]}")
        if verbose:
            for k in pulled:
                print(f"      pulled {s.first[k]}: {cost[k]:.2f} s  {s.text[k].splitlines()[0][:90]}")


def profile(path):
    s = Suite(path)
    sys.path[0] = os.path.dirname(os.path.abspath(path))
    sys.argv = [path]
    ns = {"__name__": "__main__", "__file__": path, "__builtins__": builtins}
    rows, t_all = [], time.process_time()
    try:
        for k, st in enumerate(s.body):
            if k in s.epilogue:
                continue
            code = compile(ast.Module(body=[st], type_ignores=[]), path, "exec")
            t0 = time.process_time()
            exec(code, ns)
            rows.append((k, time.process_time() - t0))
    finally:
        os.makedirs(os.path.dirname(s.profile_path()), exist_ok=True)
        with open(s.profile_path(), "w") as f:
            f.write(f"# {os.path.basename(path)}: CPU seconds of each top-level statement (bench/shard.py --profile, "
                    f"{os.uname().nodename}, {time.strftime('%Y-%m-%d')}, load {os.getloadavg()[0]:.1f} at the end); "
                    f"under 0.05 s left out. The planner's weights: only their ratios matter\n")
            f.write("# key\tcpu\tline\tfirst words\n")
            for k, c in rows:
                if c >= 0.05:
                    f.write(f"{s.key(k)}\t{c:.2f}\t{s.first[k]}\t{s.text[k].splitlines()[0][:60]}\n")
        print(f"     profile: {time.process_time() - t_all:.1f} s CPU, {len(rows)} statements -> {s.profile_path()}",
              file=sys.stderr)
    print(f"{ns.get('fails', '?')} failed")


def prove(path, n, out, whole_log=None, compare=False):
    """run (unless `compare`: the logs and exit files are in `out` already), then compare"""
    os.makedirs(out, exist_ok=True)
    py, base = sys.executable, os.path.basename(path)
    rc, secs = {}, {}
    if not compare:
        jobs = [] if whole_log else [("whole", [py, path])]
        jobs += [(f"{i}of{n}", [py, os.path.abspath(__file__), path, f"{i}/{n}"]) for i in range(1, n + 1)]
        procs = []
        for name, cmd in jobs:                  # stdout and stderr apart: the proof is on what the suite prints
            f = open(os.path.join(out, f"{base}.{name}.log"), "w")
            g = open(os.path.join(out, f"{base}.{name}.err"), "w")
            procs.append((name, subprocess.Popen(cmd, stdout=f, stderr=g), f, g, time.time()))
        for name, p, f, g, t0 in procs:
            rc[name] = p.wait()
            secs[name] = time.time() - t0
            f.close()
            g.close()
            with open(os.path.join(out, f"{base}.{name}.rc"), "w") as r:
                r.write(f"{rc[name]} {secs[name]:.1f}\n")
    else:
        for name in ["whole"] + [f"{i}of{n}" for i in range(1, n + 1)]:
            try:
                r, t = open(os.path.join(out, f"{base}.{name}.rc")).read().split()
                rc[name], secs[name] = int(r), float(t)
            except (OSError, ValueError):
                pass
    if whole_log:                               # a finished `python3 SUITE` run of this very text
        import shutil
        if os.path.abspath(whole_log) != os.path.abspath(os.path.join(out, f"{base}.whole.log")):
            shutil.copy(whole_log, os.path.join(out, f"{base}.whole.log"))
    if "whole" not in rc:                       # its exit status read from its lines
        ls_ = open(os.path.join(out, f"{base}.whole.log")).read().splitlines()
        rc["whole"] = 1 if any(l.startswith("FAIL ") for l in ls_) or not ls_ \
            or not ls_[-1].rstrip().endswith(("failed", "failure(s)")) else 0
        secs["whole"] = float("nan")

    def lines(name):                            # a shard's own lines: between its header and its verdict's mark
        ls = open(os.path.join(out, f"{base}.{name}.log")).read().splitlines()
        at = next((j for j, l in enumerate(ls) if l.startswith("     shard ") and l.endswith(": its verdict")), None)
        return [l for l in (ls[:at] if at is not None else ls) if not l.startswith("     shard ")], ls, \
            (len(ls) - at - 1 if at is not None else 0)
    parts = [lines(f"{i}of{n}") for i in range(1, n + 1)]
    tail = max(p[2] for p in parts)              # what the verdict prints, cut from the whole run's end the same way
    whole_all = open(os.path.join(out, f"{base}.whole.log")).read().splitlines()
    whole = whole_all[:len(whole_all) - tail] if tail else whole_all
    parts = [(b, ls) for b, ls, _ in parts]
    joined = [l for b, _ in parts for l in b]

    def count(ls):
        return sum(l.startswith("PASS ") for l in ls), sum(l.startswith("FAIL ") for l in ls)
    wc, sc = count(whole), [count(b) for b, _ in parts]
    print(f"whole: exit {rc['whole']}, {wc[0]} PASS + {wc[1]} FAIL = {sum(wc)} checks, {secs['whole']:.0f} s")
    for i, (c, (_, ls)) in enumerate(zip(sc, parts), 1):
        print(f"shard {i}/{n}: exit {rc[f'{i}of{n}']}, {c[0]} PASS + {c[1]} FAIL = {sum(c)} checks, "
              f"{secs[f'{i}of{n}']:.0f} s  ({ls[0].strip() if ls else 'no output'})")
    tot = (sum(c[0] for c in sc), sum(c[1] for c in sc))
    same = joined == whole
    print(f"shards: {tot[0]} PASS + {tot[1]} FAIL = {sum(tot)} checks; the shards' output, concatenated, is the "
          f"whole's line for line: {'yes' if same else 'NO'}")
    if not same:
        for j in range(max(len(joined), len(whole))):
            a = joined[j] if j < len(joined) else None
            b = whole[j] if j < len(whole) else None
            if a != b:
                print(f"  first difference, line {j + 1}:\n    shards: {a}\n    whole:  {b}")
                break
    ok = same and tot == wc and (rc["whole"] != 0) == (wc[1] > 0) \
        and all((rc[f"{i}of{n}"] != 0) == (sc[i - 1][1] > 0) for i in range(1, n + 1))
    print("PROVEN" if ok else "NOT PROVEN")
    return 0 if ok else 1


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    path = argv[1]
    if argv[2] == "--plan":
        plan(path, int(argv[3]), "-v" in argv)
    elif argv[2] == "--profile":
        profile(path)
    elif argv[2] == "--prove":
        rest = argv[4:]
        whole = rest[rest.index("--whole-log") + 1] if "--whole-log" in rest else None
        compare = "--compare" in rest
        rest = [a for a in rest if a not in ("--whole-log", whole, "--compare")]
        return prove(path, int(argv[3]), rest[0] if rest else "out/shard-prove", whole, compare)
    else:
        i, n = (int(x) for x in argv[2].split("/"))
        if not 1 <= i <= n:
            print(f"no shard {i} of {n}")
            return 2
        shard(path, i, n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
