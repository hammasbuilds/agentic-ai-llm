"""agri-desk end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from agridesk import agents
from agridesk.app import runtime


class TestAgriDesk(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "since_day": 15,
        "isolates": [
            {"id": "i1", "sequence": "TTTT", "site": "multan", "day": 20},
            {"id": "i2", "sequence": "TTTT", "site": "sahiwal", "day": 21},
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {
        "since_day": 5,
        "isolates": [
            {"id": f"i{n}", "sequence": "ACGT", "site": "multan", "day": 10 + n}
            for n in range(9)
        ],
    }
    early_exit_result = "no_emergence"
