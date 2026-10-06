"""hermes-home end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from hermes import agents
from hermes.app import runtime


class TestHermesHome(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "specialist": "booking-agent",
        "message": "find a hotel",
        "constraints": [
            {"id": "c1", "predicate": "diet", "value": "vegan", "hard": True},
            {"id": "c2", "predicate": "seat", "value": "window", "hard": False},
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {
        "constraints": [{"id": "c1", "predicate": "diet", "value": "vegan", "hard": True}],
        "drop_hard": True,
    }
    early_exit_result = "handoff_refused"
