"""one-desk end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from onedesk import agents
from onedesk.app import runtime


class TestOneDesk(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "idea": "idea_0412",
        "baseline": "One model on one card serves every agent in the system",
        "variants": {"li": "One model on one card serves every agent we run"},
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"brand_veto": "names a client without permission"}
    early_exit_result = "vetoed"
