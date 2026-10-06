"""powerguard end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from powerguard import agents
from powerguard.app import runtime


class TestPowerguard(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "on_mains": False,
        "battery_pct": 80,
        "minutes_remaining": 40,
        "jobs": [
            {
                "pid": 101,
                "name": "train_shr",
                "kind": "training",
                "owned": True,
                "checkpointable": True,
            },
            {"pid": 303, "name": "other-session", "kind": "training", "owned": False},
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"on_mains": True}
    early_exit_result = "nothing_to_do"
