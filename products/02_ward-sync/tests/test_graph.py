"""ward-sync end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from ward import agents
from ward.app import runtime


class TestWardSync(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "encounter": "enc_8814",
        "events": [
            {"id": "evt_2231", "seq": 1, "kind": "ordered", "drug": "ceftriaxone"},
            {"id": "evt_2288", "seq": 2, "kind": "discontinued", "drug": "ceftriaxone"},
            {"id": "evt_2301", "seq": 3, "kind": "ordered", "drug": "co-amoxiclav"},
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"events": []}
    early_exit_result = "escalated"
