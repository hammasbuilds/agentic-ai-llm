"""The six behaviours every product built on `standard_graph` must have.

Nineteen products shipped a `tests/test_graph.py` holding the same six tests with the
same six names, differing only in the payload they submit, one key to look for in the
early-exit result, and the package the imports come from. Around 2,400 lines in all,
of which maybe 200 said anything about a particular product.

That is not only repetition. Two things follow from it that this module is here to fix:

  * a correction to the shared scaffolding had to be applied nineteen times, and the
    one that was not applied looked exactly like the eighteen that were;
  * the counts read as 114 tests of six behaviours. The coverage is six behaviours
    over nineteen payloads, and consolidating does not reduce it - each subclass still
    contributes six, run against its own product's graph.

What stays per-product is the judgement: the payload a real caller sends, the shape
that lets the graph exit early, and the name that result carries. Those are the only
things that ever differed, and they stay written out in each product's own test file
where a reader can see them.

`01_revenue-desk` deliberately does not use this. It is the worked example the
products README points at - "every graph shape appears in it exactly once" - and
reading the whole run spelled out in one file is the point of it.
"""

from __future__ import annotations

from . import api, blueprint
from .authority import Level
from .llm import Recorded

#: The two strings the recorded model returns. Fixed, because no assertion here is
#: about their content: what matters is how many generations a run spends and whether
#: resuming spends more.
SUMMARY = "A short factual summary."
DRAFT = "The drafted output."


class StandardProductTests:
    """Subclass once per product, set four attributes, get the six tests.

    ::

        class TestWardSync(StandardProductTests):
            agents = agents
            runtime = staticmethod(runtime)
            base_payload = {...}
            early_exit_payload = {"events": []}
            early_exit_result = "escalated"

    `runtime` must be wrapped in `staticmethod`, or Python binds it as a method and
    passes the class in as the model.
    """

    #: The product's `agents` module - `triage`, `authority` and the rest.
    agents = None
    #: The product's `app.runtime` factory, wrapped in `staticmethod`.
    runtime = None
    #: What a caller sends. Written out per product, because it is the one part of
    #: this that says what the product is for.
    base_payload: dict = {}
    #: The override that makes the graph finish without generating anything.
    early_exit_payload: dict = {}
    #: The key the early-exit result sets to True.
    early_exit_result: str = ""

    # -- the fixtures the six tests share ----------------------------------------

    @classmethod
    def payload(cls, **extra) -> dict:
        base = dict(cls.base_payload)
        base.update(extra)
        return base

    @classmethod
    def script(cls, for_payload: dict) -> dict:
        """Exactly the prompts this run will produce, and no others.

        Derived from the payload rather than pasted, because `Recorded` raises on an
        unscripted prompt - which is what stops a test quietly reaching a real model.
        Triage runs before the fan-out, so the subject is the same whether or not a
        branch dies.
        """
        subject = cls.agents.triage(for_payload).get("summary_subject")
        return {
            f"summarise:{subject}|failed:[]": SUMMARY,
            f"summarise:{subject}|failed:['beta']": SUMMARY,
            f"compose:{SUMMARY}": DRAFT,
        }

    @staticmethod
    def sources(fail_beta: bool = False):
        def beta(state):
            if fail_beta:
                raise TimeoutError("source down")
            return ["src_b22"]

        return {"alpha": lambda s: ["src_a41"], "beta": beta}

    @classmethod
    def _rt(cls, *, fail_beta: bool = False, for_payload: dict | None = None):
        model = Recorded(cls.script(for_payload if for_payload is not None else cls.payload()))
        return model, cls.runtime(model, cls.sources(fail_beta=fail_beta))

    # -- the six ------------------------------------------------------------------

    def test_the_product_runs_end_to_end(self):
        # Imported here, not at module scope: this file lives in the platform's
        # runtime package, and a runtime module that cannot be imported without
        # pytest installed is a dependency the published wheel does not declare.
        import pytest

        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        model, rt = self._rt()
        client = TestClient(api.create_app(rt))

        accepted = client.post(
            "/intake", json={"run_id": "r1", "entity": "e1", "payload": self.payload()}
        )
        assert accepted.status_code == 202
        assert model.calls == []  # the queue accepted it; the GPU has not been touched

        assert rt.drain() == 1
        paused = client.get("/runs/r1").json()
        assert paused["status"] == api.AWAITING_APPROVAL
        assert paused["awaiting"] == blueprint.APPROVE
        assert paused["llm_calls"] == 2  # already spent, and reported before resuming

        done = client.post("/approvals/r1/approve").json()
        assert done["status"] == api.DONE
        assert done["llm_calls"] == 2  # resuming added none

    def test_nothing_is_regenerated_across_the_approval(self):
        model, rt = self._rt()
        rt.submit("r1", "e1", self.payload())
        rt.drain()
        before = list(model.calls)
        rt.approve("r1")
        assert model.calls == before

    def test_the_early_exit_costs_no_generation(self):
        assert self.early_exit_payload, "a product that cannot exit early must say so"
        model, rt = self._rt()
        rt.submit("r1", "e1", self.payload(**self.early_exit_payload))
        rt.drain()
        row = rt.run_row("r1")
        assert row["status"] == api.DONE
        assert row["result"][self.early_exit_result] is True
        assert model.calls == []
        assert row["llm_calls"] == 0

    def test_a_failed_gather_branch_is_disclosed_to_synthesis(self):
        model, rt = self._rt(fail_beta=True)
        rt.submit("r1", "e1", self.payload())
        rt.drain()
        assert any("failed:['beta']" in c for c in model.calls)

    def test_an_unreceipted_claim_never_reaches_the_approver(self):
        _, rt = self._rt()
        rt.submit("r1", "e1", self.payload())
        rt.drain()
        state = rt.checkpoint("r1").state
        assert state["kept_claims"] == ["Backed by a real receipt."]
        assert state["dropped_claims"][0][0] == "Asserted with nothing behind it."
        # One of two dropped, with `claims_checked` as the denominator that says so.
        assert state["claims_checked"] == 2
        # `drop_rate` is None, and that is the finding. This asserted 0.5 - a rate over
        # `claims`, a key this run supplied in its own payload. Half of what the CALLER
        # sent was unreceipted; nothing here measures what the model wrote, and the
        # gate says so instead of publishing a figure that reads as if it did.
        assert state["drop_rate"] is None
        assert state["claims_source"] == "payload"

    def test_the_authority_table_is_default_deny(self):
        assert self.agents.authority().level_for("nobody", "anything") is Level.NEVER
