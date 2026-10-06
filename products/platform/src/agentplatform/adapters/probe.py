"""Why an adapter could not be reached, as something other than False.

Every adapter here answered reachability with a bare boolean, and every one of them
caught `Exception` to produce it - which folds "the client library is not installed"
into "the service is down". The contract tests skipped with `reason="no broker on
localhost:9092"` on a machine where the broker was fine and `kafka-python` was simply
absent, because `infra` declares `confluent-kafka` and the adapter imports `kafka`.

A skip that names the wrong cause is worse than a failure: nobody goes looking.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The client library is missing, so the service was never contacted.
NO_CLIENT = "no client library"
#: The library is present and the service did not answer.
UNREACHABLE = "unreachable"
OK = "reachable"


@dataclass(frozen=True)
class Probe:
    """The outcome of one reachability check, and why."""

    status: str
    detail: str = ""

    def __bool__(self) -> bool:
        """So `if adapter.probe():` and the old `if adapter.reachable():` agree."""
        return self.status == OK

    @property
    def reason(self) -> str:
        """A skip reason that names the actual cause."""
        if self.status == OK:
            return ""
        return f"{self.status}: {self.detail}" if self.detail else self.status


def probe(target: str, call, *, requires: str) -> Probe:
    """Run `call`, distinguishing a missing `requires` package from a dead service."""
    try:
        return Probe(OK) if call() else Probe(UNREACHABLE, target)
    except ModuleNotFoundError as missing:
        name = missing.name or requires
        return Probe(NO_CLIENT, f"{name} is not installed (pip install {requires})")
    except Exception as exc:  # noqa: BLE001 — anything else is the service, not us
        return Probe(UNREACHABLE, f"{target} ({type(exc).__name__})")
