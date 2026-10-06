"""shelf-ops end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from shelfops import agents
from shelfops.app import runtime


class TestShelfOps(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "base": 10000,
        "floor": 1000,
        "cost": 6000,
        "fee_pct": 12.0,
        "proposals": [
            {"agent": "repricer", "kind": "reprice", "discount_pct": 10.0},
            {"agent": "promotions", "kind": "promotion", "discount_pct": 15.0},
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {
        "base": 10000,
        "floor": 9500,
        "cost": 6000,
        "fee_pct": 12.0,
        "proposals": [{"agent": "clearance", "kind": "clearance", "discount_pct": 90.0}],
    }
    early_exit_result = "held_at_floor"
