"""comms-desk end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from comms import agents
from comms.app import runtime


class TestCommsDesk(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "commitments": [
            {
                "id": "c1",
                "speaker": "ayesha",
                "source": "meeting",
                "text": "I will send the revised pricing sheet to the client before Friday",
            },
            {
                "id": "c2",
                "speaker": "ayesha",
                "source": "email",
                "text": "Sending the revised pricing sheet over to the client by Friday",
            },
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"commitments": []}
    early_exit_result = "nothing_to_do"
