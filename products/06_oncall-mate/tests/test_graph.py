"""oncall-mate end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from oncall import agents
from oncall.app import runtime


class TestOncallMate(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "alerts": [
            {
                "id": "al_1",
                "service": "checkout",
                "template": "upstream timeout <*>ms",
                "at": 0,
            },
            {
                "id": "al_2",
                "service": "checkout",
                "template": "upstream timeout <*>ms",
                "at": 30,
            },
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"alerts": []}
    early_exit_result = "no_incident"
