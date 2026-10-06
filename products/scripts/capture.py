"""Run every product for real and capture what it actually produces.

Nothing here is invented: each README's Input/Output section is written from
this file's output, which is a real intake -> drain -> approve cycle plus the
early-exit path.
"""

import ast
import importlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scripts" / "runs.json"

PRODUCTS = sorted(d for d in ROOT.iterdir() if d.is_dir() and d.name[0].isdigit())

# 01 predates the shared template and names its early-exit test differently.
EXIT_TEST = {
    "01_revenue-desk": "test_an_opt_out_leaves_the_graph_before_anything_is_drafted",
}
DEFAULT_EXIT_TEST = "test_the_early_exit_costs_no_generation"


class _ModuleSpec:
    """A product whose test is written out at module level, which is `01` alone.

    The other nineteen declare the same four things as attributes of a
    `StandardProductTests` subclass, and `_spec` returns the subclass itself. This
    wrapper lets the loop below read either through one interface.
    """

    def __init__(self, module):
        self._m = module

    def payload(self, **extra) -> dict:
        return self._m.payload(**extra)

    def script(self, for_payload: dict) -> dict:
        maker = getattr(self._m, "script", None)
        return maker(for_payload) if maker else self._m.SCRIPT

    def sources(self, **kw):
        return self._m.sources(**kw)

    def runtime(self, *a, **kw):
        return self._m.runtime(*a, **kw)


def _spec(module):
    """The product's conformance subclass, or a wrapper over its module.

    Nineteen products' `test_graph.py` used to hold a module-level `payload`,
    `script` and `sources`, nineteen times over, and this file read them by name.
    They now subclass `agentplatform.conformance.StandardProductTests` and declare
    only what differs, so the four things are class attributes - and the early-exit
    payload no longer has to be recovered by parsing the test that asserts it.
    """
    from agentplatform.conformance import StandardProductTests

    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, StandardProductTests)
            and value is not StandardProductTests
        ):
            return value
    return _ModuleSpec(module)


def _exit_payload(product_name: str, module, spec) -> dict:
    """The override that makes the graph finish without generating anything.

    Declared outright by a conformance subclass. For `01`, which spells its run out
    by hand, it is still read out of the test that asserts it - restating it here
    would let this file drift away from what is actually checked.
    """
    declared = getattr(spec, "early_exit_payload", None)
    if declared:
        return dict(declared)
    name = EXIT_TEST.get(product_name, DEFAULT_EXIT_TEST)
    return _exit_kwargs(module, name)


def _exit_kwargs(module, name: str) -> dict:
    """Pull the early-exit payload out of the product's own test, by parsing it.

    Read from the test rather than restated here, so this file cannot drift
    away from what is actually asserted.
    """
    tree = ast.parse(inspect.getsource(getattr(module, name)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "payload"):
            continue
        if node.keywords and node.keywords[0].arg is None:  # payload(**{...})
            return _value(node.keywords[0].value, module)
        if node.keywords:  # payload(reply="...")
            return {k.arg: _value(k.value, module) for k in node.keywords}
    raise LookupError(f"no early-exit payload found in {name}")


def _value(node, module):
    """literal_eval where possible; otherwise evaluate in the test's own namespace.

    One product's early-exit payload is a list comprehension, which is not a
    literal. Evaluating it against the module it came from is exact, and the
    source is ours.
    """
    try:
        return ast.literal_eval(node)
    except ValueError:
        return eval(  # noqa: S307 - our own generated test source
            compile(ast.Expression(node), "<test>", "eval"), vars(module)
        )


EXIT_FLAGS = (
    "escalated",
    "vetoed",
    "refused",
    "nothing_to_do",
    "no_incident",
    "refused_to_score",
    "blocked",
    "handoff_refused",
    "cleared",
    "not_reportable",
    "no_path",
    "cannot_assess",
    "held_at_floor",
    "rejected_route",
    "not_publishable",
    "no_emergence",
    "no_drift",
    "suppressed",
)


def capture(product: Path) -> dict:
    paths = [str(product / "src"), str(ROOT / "platform" / "src"), str(product / "tests")]
    for p in paths:
        sys.path.insert(0, p)
    for mod in list(sys.modules):
        if mod.startswith(("test_graph", "agentplatform")) or mod in _pkgs:
            del sys.modules[mod]

    try:
        tg = importlib.import_module("test_graph")
        app = importlib.import_module(tg.runtime.__module__)
        from agentplatform.llm import Recorded

        spec = _spec(tg)

        payload = spec.payload()
        model = Recorded(spec.script(payload))
        rt = spec.runtime(model, spec.sources())

        rt.submit("run_1", "e1", payload)
        lag = rt.bus.lag(rt.topics.tasks, rt.group)
        rt.drain()
        paused = dict(rt.run_row("run_1"))
        # `rt.checkpoint(run_id)`, not `rt._checkpoints[run_id]`. The private dict was
        # replaced by a store-backed checkpoint and the public accessor added for
        # exactly this, and this file was not updated - so the generator behind every
        # product's Input/Output section raised AttributeError on all twenty, and
        # nothing imports it or runs it in CI.
        gated = dict(rt.checkpoint("run_1").state)
        done = dict(rt.approve("run_1"))

        exit_model = Recorded(spec.script(payload))
        exit_rt = spec.runtime(exit_model, spec.sources())
        exit_rt.submit("run_2", "e2", spec.payload(**_exit_payload(product.name, tg, spec)))
        exit_rt.drain()
        exited = dict(exit_rt.run_row("run_2"))

        return {
            "domain": app.DOMAIN,
            "topics": list(rt.topics.all()),
            "lag_after_intake": lag,
            "input_keys": sorted(k for k in payload if not k.startswith("_")),
            "paused": {
                "status": paused["status"],
                "awaiting": paused.get("awaiting"),
                "visited": paused["visited"],
                "llm_calls": paused["llm_calls"],
            },
            "gate": {
                "kept": gated.get("kept_claims", []),
                "dropped": [d[0] for d in gated.get("dropped_claims", [])],
                "drop_rate": gated.get("drop_rate"),
            },
            "done": {
                "status": done["status"],
                "visited": done["visited"],
                "llm_calls": done["llm_calls"],
                "result_keys": sorted(done["result"]),
            },
            "early_exit": {
                "status": exited["status"],
                "visited": exited["visited"],
                "llm_calls": exited["llm_calls"],
                "flags": {k: v for k, v in exited["result"].items() if k in EXIT_FLAGS},
            },
        }
    finally:
        for p in paths:
            sys.path.remove(p)


_pkgs = {
    "revenue",
    "ward",
    "onedesk",
    "ledger",
    "comms",
    "oncall",
    "hiredesk",
    "biddesk",
    "hermes",
    "kycfloor",
    "watchtower",
    "powerguard",
    "swarmlab",
    "graphclinic",
    "claimsfloor",
    "shelfops",
    "fleetdesk",
    "campusops",
    "agridesk",
    "driftwatch",
}
_pkgs |= {f"{p}.{sub}" for p in _pkgs for sub in ("app", "graph", "agents", "domain")}


def main() -> None:
    runs, failed = {}, 0
    for product in PRODUCTS:
        try:
            runs[product.name] = capture(product)
            r = runs[product.name]
            print(
                f"  {product.name:18} paused@{r['paused']['awaiting']} "
                f"{r['paused']['llm_calls']} calls, exit {r['early_exit']['llm_calls']} calls"
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  {product.name:18} FAILED {type(exc).__name__}: {exc}")
            runs[product.name] = {"error": f"{type(exc).__name__}: {exc}"}
    if failed:
        # The committed file is what all twenty READMEs are checked against, so a
        # partial run must not replace it. It did: `python scripts/capture.py` printed
        # "0/20 captured" having already overwritten runs.json with twenty error stubs
        # - the README's own instruction destroying the artefact the README says every
        # figure came from.
        print(f"\n{failed} of {len(PRODUCTS)} failed; {OUT.name} left as it was")
        raise SystemExit(1)

    # `newline="\n"`, because `write_text` translates on Windows and the committed file
    # is LF. Without it a run that changes nothing rewrites all 1,701 lines, so the
    # diff that is supposed to show whether a figure moved shows the whole file instead.
    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(runs, indent=2))
    print(f"\n{len(PRODUCTS) - failed}/{len(PRODUCTS)} captured -> {OUT}")


if __name__ == "__main__":
    main()
