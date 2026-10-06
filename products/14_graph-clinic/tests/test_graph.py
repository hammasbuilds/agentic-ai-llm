"""graph-clinic end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from graphclinic import agents
from graphclinic.app import runtime


class TestGraphClinic(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "start": "pneumonia",
        "end": "penicillin_allergy",
        "edges": [
            {
                "src": "pneumonia",
                "rel": "treated_with",
                "dst": "ceftriaxone",
                "source": "doc_1",
            },
            {
                "src": "ceftriaxone",
                "rel": "contraindicated_in",
                "dst": "penicillin_allergy",
                "source": "doc_2",
            },
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"start": "pneumonia", "end": "diabetes", "edges": []}
    early_exit_result = "no_path"
