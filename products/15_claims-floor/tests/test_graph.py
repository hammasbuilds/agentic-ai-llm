"""claims-floor end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from claimsfloor import agents
from claimsfloor.app import runtime


class TestClaimsFloor(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "loss_date": "2025-06-01",
        "peril": "flood",
        "versions": [
            {
                "id": "v1",
                "from": "2024-01-01",
                "to": "2025-12-31",
                "perils": ["fire", "flood", "theft"],
            },
            {
                "id": "v2",
                "from": "2026-01-01",
                "perils": ["fire", "theft"],
                "exclusions": ["flood"],
            },
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {
        "loss_date": "2023-05-01",
        "peril": "fire",
        "versions": [
            {"id": "v1", "from": "2024-01-01", "to": "2025-12-31", "perils": ["fire"]}
        ],
    }
    early_exit_result = "cannot_assess"
