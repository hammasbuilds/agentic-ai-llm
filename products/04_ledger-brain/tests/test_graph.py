"""ledger-brain end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from ledger import agents
from ledger.app import runtime


class TestLedgerBrain(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "payments": [{"id": "p1", "amount": 12000}],
        "invoices": [{"id": "i1", "amount": 12000}, {"id": "i2", "amount": 9900}],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {
        "payments": [{"id": "p1", "amount": 12000}],
        "invoices": [{"id": "i1", "amount": 12000}, {"id": "i2", "amount": 12000}],
    }
    early_exit_result = "refused"
