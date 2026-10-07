"""One way to read a product's test module, for the three scripts that read one.

`capture.py`, `smoke_serve.py` and `screenshots.py` each take a product's
`tests/test_graph.py` and drive its graph. Nineteen of the twenty products moved from
module-level `payload`/`script`/`sources`/`runtime` to a `StandardProductTests`
subclass, and `capture.py` grew the adapter for both shapes. The other two were not
touched, and kept calling `tg.payload()`:

    $ python scripts/smoke_serve.py
    1/20 products served over HTTP

with `AttributeError: module 'test_graph' has no attribute 'payload'` for products 02 to
20 — and it had already rewritten `scripts/served.json`, the artefact `products/README.md`
points at as the evidence for "All 20 also boot on a real ASGI server", from twenty good
rows to one row and nineteen error stubs.

That is the exact failure `tests/test_captured_runs.py` was written about for
`capture.py`: following the README destroyed the artefact the README says every figure
came from. The lesson was applied to the one script and not to the two beside it, because
the adapter lived inside the one script. It lives here now, and
`tests/test_product_scripts.py` runs all three.
"""

from __future__ import annotations


class _ModuleSpec:
    """A product whose test is written out at module level, which is `01` alone.

    The other nineteen declare the same four things as attributes of a
    `StandardProductTests` subclass, and `spec_for` returns the subclass itself. This
    wrapper lets a caller read either through one interface.
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

    @property
    def runtime(self):
        """The product's own `runtime` FUNCTION, not a wrapper around it.

        A property rather than a method, because callers read `runtime.__module__` to
        find the product's app module - and a wrapper method answers with THIS module,
        which made `capture.py` look for `DOMAIN` in `product_spec`. The subclass path
        holds the same function as a staticmethod, so both answer the same way.
        """
        return self._m.runtime


def spec_for(module):
    """The product's conformance subclass, or a wrapper over its module.

    Both expose `payload`, `script`, `sources` and `runtime`, so a caller never has to
    know which shape a product's test is written in - which is the whole point, and
    what the two scripts that did not use this got wrong.
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
