"""agri-desk agents: report parsing, surveillance linking, advisory writing.

Three quarters of this file does not call a model. The triage step, the early
exit and the commit are rules; the model writes the summary and the draft, and
:mod:`agentplatform.gate` removes anything it wrote that no tool supports.
"""

from __future__ import annotations

from agentplatform.authority import Level, Table

from .domain import Isolate, collapse_clonal, distinct_variants, emerging
from .sources import default_sources as _real_sources
from .sources import isolates as _corpus_isolates


def authority() -> Table:
    """Who may write what. Default-deny — see agentplatform.authority."""
    return (
        Table()
        .grant("report-parser", "report.*", Level.WRITE)
        .grant("surveillance-linker", "link.*", Level.WRITE)
        .grant("surveillance-linker", "variant.call", Level.NEVER)
        .grant("advisory-writer", "advisory.draft", Level.WRITE)
        .grant("price-reporter", "price.*", Level.WRITE)
    )


def triage(state: dict) -> dict:
    """Collapse clonal duplicates before counting anything.

    Reads the real GenBank corpus unless the caller supplied isolates directly,
    which is what the unit tests do to pin specific behaviour.
    """
    if state.get("isolates"):
        isolates = [
            Isolate(i["id"], i["sequence"], i["site"], i["day"]) for i in state["isolates"]
        ]
    else:
        isolates = _corpus_isolates(state.get("corpus"))
    rising = emerging(isolates, state.get("since_day", 0), state.get("min_sites", 2))
    return {
        "clusters": len(collapse_clonal(isolates)),
        "naive_count": distinct_variants(isolates, collapse=False),
        "emerging": rising,
        "summary_subject": rising,
    }


def early_exit(state: dict) -> bool:
    """Nothing is emerging once duplicates stop counting as separate observations."""
    return not state.get("emerging")


def on_exit(state: dict) -> dict:
    return {"no_emergence": True, "reason": "no variant seen at enough sites since the window"}


def commit(state: dict) -> dict:
    return {"advisory.draft": state.get("draft", ""), "issued": False}


def default_sources() -> dict:
    """Real branches over the real corpus. See :mod:`agridesk.sources`."""
    return _real_sources()
