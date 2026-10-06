"""fleet-desk end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from fleetdesk import agents
from fleetdesk.app import runtime


class TestFleetDesk(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "depot": "d",
        "stops": ["a", "b"],
        "solver_route": ["d", "a", "b", "d"],
        "challenger_route": ["d", "b", "a", "d"],
        "matrix": {
            "d->a": 1000,
            "a->d": 1000,
            "d->b": 2000,
            "b->d": 2000,
            "a->b": 1200,
            "b->a": 1200,
        },
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {
        "depot": "d",
        "stops": ["a", "b"],
        "solver_route": ["d", "a", "d"],
        "challenger_route": ["d", "a", "b", "d"],
        "matrix": {"d->a": 1000, "a->d": 1000},
    }
    early_exit_result = "rejected_route"
