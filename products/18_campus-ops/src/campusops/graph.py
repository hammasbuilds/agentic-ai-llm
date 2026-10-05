"""The campus-ops pipeline, built from the shared blueprint.

Seven nodes, the same seven every product has. What differs is the judgement in
:mod:`campusops.agents`, not the shape.
"""

from __future__ import annotations

from agentplatform.blueprint import standard_graph
from agentplatform.graphs import Graph
from agentplatform.llm import Model

from . import agents


def build(model: Model, sources: dict | None = None) -> Graph:
    return standard_graph(agents, model, sources)
