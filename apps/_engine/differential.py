"""Prove a surviving mutant is a different program, by finding an input that separates it.

Mutation survival alone overstates a test suite's weakness, because some mutations are
equivalent to the original and no suite could ever catch them. The usual response is to
acknowledge the problem and move on. This looks for a witness instead: an input on which
the reference solution and the mutant return different values.

A survivor with a witness is a *provably* wrong program that MBPP marked correct. A
survivor without one is either equivalent or simply not separated by the inputs tried -
the distinction is undecidable in general, so those are reported as unproven rather than
counted either way.

Candidate inputs come from the asserts themselves. MBPP's asserts contain literal
arguments, and perturbing those literals - a number off by one, an emptied list, a
flipped sign - stays inside the type the function expects, which matters because a
function that raises TypeError on both sides has not been separated by anything.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 10.0


@dataclass(frozen=True)
class Witness:
    found: bool
    args: str = ""
    ref: str = ""
    mut: str = ""
    reason: str = ""
    #: Inputs the probe actually evaluated and ran on both programs. Zero means this
    #: mutant was never separated because it was never tried - which is not evidence
    #: that it is equivalent, and used to be reported the same way.
    cases_run: int = 0
    candidates: int = 0


def call_args(test: str) -> list[ast.expr] | None:
    """The literal argument expressions from `assert f(a, b) == c`."""
    try:
        tree = ast.parse(test.strip())
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return list(node.args)
    return None


def _perturb(node: ast.expr) -> list[ast.expr]:
    """Nearby values of the same type."""
    out: list[ast.expr] = []
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            out.append(ast.Constant(not v))
        elif isinstance(v, int):
            out += [
                ast.Constant(v + 1),
                ast.Constant(v - 1),
                ast.Constant(0),
                ast.Constant(1),
                ast.Constant(2),
                ast.Constant(-v),
            ]
        elif isinstance(v, float):
            out += [ast.Constant(v + 1.0), ast.Constant(0.0), ast.Constant(-v)]
        elif isinstance(v, str):
            out += [
                ast.Constant(v + v[:1]),
                ast.Constant(v[:-1]),
                ast.Constant(""),
                ast.Constant(v.upper()),
                ast.Constant(v * 2),
            ]
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        elts = list(node.elts)
        cls = type(node)
        if elts:
            out.append(cls(elts=elts[:-1], ctx=ast.Load()))
            out.append(cls(elts=elts + [elts[-1]], ctx=ast.Load()))
            out.append(cls(elts=list(reversed(elts)), ctx=ast.Load()))
            for i, e in enumerate(elts[:3]):
                for p in _perturb(e)[:2]:
                    new = list(elts)
                    new[i] = p
                    out.append(cls(elts=new, ctx=ast.Load()))
        out.append(cls(elts=[], ctx=ast.Load()))
    return out


def candidate_calls(tests: tuple[str, ...], cap: int = 60) -> list[str]:
    """Argument tuples to try, as source strings, starting with the originals."""
    out: list[str] = []
    seen: set[str] = set()
    for t in tests:
        args = call_args(t)
        if args is None:
            continue
        base = ", ".join(_src(a) for a in args)
        if base not in seen:
            seen.add(base)
            out.append(base)
        for i, a in enumerate(args):
            for p in _perturb(a):
                new = list(args)
                new[i] = p
                try:
                    s = ", ".join(_src(x) for x in new)
                except (ValueError, AttributeError):
                    continue
                if s not in seen:
                    seen.add(s)
                    out.append(s)
                if len(out) >= cap:
                    return out
    return out


def _src(node: ast.expr) -> str:
    ast.fix_missing_locations(node)
    return ast.unparse(node)


_PROBE = """\
import copy, json, sys
{setup}
_NS_REF = {{}}
_NS_MUT = {{}}
exec({ref!r}, _NS_REF)
exec({mut!r}, _NS_MUT)
f_ref = _NS_REF[{fn!r}]
f_mut = _NS_MUT[{fn!r}]

def _call(f, args):
    # A fresh copy per call. Both programs were handed the SAME object, so a function
    # that mutates its argument gave the mutant pre-mutated input - and the prober then
    # reported a separating input between a program and itself. Measured over the first
    # 150 MBPP problems: 2 of 66 "proven wrong" survivors were artefacts of this, and
    # the `mut` value shown in the witness table was not what the mutant produces.
    try:
        return ("ok", repr(f(*copy.deepcopy(args))))
    except Exception as e:
        return ("exc", type(e).__name__)

CASES = {cases!r}
_ran = 0
for src in CASES:
    try:
        args = eval("(" + src + ",)")
    except Exception:
        continue
    _ran += 1
    a = _call(f_ref, args)
    b = _call(f_mut, args)
    # Two different exception types still separate the programs, but two identical
    # ones do not - and "both raise TypeError" is what a badly typed input produces,
    # which would be a witness to nothing.
    if a != b:
        print(json.dumps({{"args": src, "ref": str(a), "mut": str(b)}}))
        break
# Always last, so the caller can tell "ran forty inputs and none separated them" from
# "every candidate failed to eval and nothing was ever run". Those are the same verdict
# and not the same evidence.
print(json.dumps({{"ran": _ran, "candidates": len(CASES)}}))
"""


def find_witness(
    reference: str, mutant: str, fn: str, tests: tuple[str, ...], setup: str = ""
) -> Witness:
    cases = candidate_calls(tests)
    if not cases:
        return Witness(False, reason="no parsable call in asserts")
    src = _PROBE.format(setup=setup, ref=reference, mut=mutant, fn=fn, cases=cases)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "probe.py"
        with f.open("w", encoding="utf-8", newline="") as handle:
            handle.write(src)
        try:
            r = subprocess.run(
                [sys.executable, str(f)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return Witness(False, reason="timeout")
        except OSError as exc:
            return Witness(False, reason=f"spawn failed: {exc}")
    lines = (r.stdout or "").strip().splitlines()
    if not lines:
        # The probe did not even reach its summary: the reference or the mutant failed
        # to exec, or the process died.
        return Witness(False, reason=f"probe produced nothing (exit {r.returncode})")
    try:
        summary = json.loads(lines[-1])
        ran, candidates = int(summary["ran"]), int(summary["candidates"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return Witness(False, reason="unparsable probe output")

    for raw in lines[:-1]:
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "args" in d:
            return Witness(
                True,
                args=d["args"],
                ref=d["ref"],
                mut=d["mut"],
                cases_run=ran,
                candidates=candidates,
            )

    reason = (
        f"no input was runnable ({candidates} candidate(s), none evaluated)"
        if ran == 0
        else f"no separating input found in {ran} of {candidates} candidate(s)"
    )
    return Witness(False, reason=reason, cases_run=ran, candidates=candidates)


# `find_many` was here: a ThreadPoolExecutor wrapper over `find_witness` that nothing
# called. The witness hunt runs untrusted code under a timeout, and app 02 drives it
# through `run_in_executor` with its own progress reporting, so a second parallel
# wrapper was a way for the two to disagree about how many workers are safe.
