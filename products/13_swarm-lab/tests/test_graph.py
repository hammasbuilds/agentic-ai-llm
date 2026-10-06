"""swarm-lab end to end: intake, bus, worker, approval, commit.

No broker, no database, no model, no network.

The six tests are in `agentplatform.conformance`, shared by every product built on
`standard_graph` - nineteen copies of them used to be pasted into nineteen files, so
a correction to the scaffolding had to be made nineteen times. What belongs to this
product is below: the payload a caller sends, the shape that lets the graph finish
without generating anything, and the name that result carries.
"""

from agentplatform.conformance import StandardProductTests

from swarmlab import agents
from swarmlab.app import runtime


class TestSwarmLab(StandardProductTests):
    agents = agents
    runtime = staticmethod(runtime)

    base_payload = {
        "repeats": 3,
        "calls": [
            {"agent": "a1", "tool": "fetch", "args": {"url": "x"}, "seq": 1},
            {"agent": "a2", "tool": "fetch", "args": {"url": "x"}, "seq": 2},
        ],
        "writes": [
            {"agent": "a1", "entity": "d1", "field": "amount", "value": 100, "seq": 1},
            {"agent": "a2", "entity": "d1", "field": "amount", "value": 200, "seq": 2},
        ],
        "issued_receipts": ["src_a41", "src_b22"],
        "claims": [
            {"text": "Backed by a real receipt.", "receipts": ["src_a41"]},
            {"text": "Asserted with nothing behind it.", "receipts": []},
        ],
    }

    early_exit_payload = {"repeats": 1}
    early_exit_result = "not_reportable"
