"""Which agent may write which field. Default-deny.

An agent that *can* write to the system of record will eventually write
something wrong. Which agent may write which field is enforced here and in the
schema, never in a system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Level(Enum):
    WRITE = "write"
    PROPOSE = "propose"
    NEVER = "never"


class NotAuthorisedError(PermissionError):
    """The agent has no authority over this field."""


@dataclass
class Applied:
    """The outcome of one agent trying to change a record."""

    written: dict[str, object] = field(default_factory=dict)
    proposed: dict[str, object] = field(default_factory=dict)
    refused: dict[str, object] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.written or self.proposed)


class Table:
    """The write-authority table for one product.

    Anything not granted is ``NEVER``. A new field added to the schema is
    therefore closed by default rather than open, which is the only direction
    that is safe to get wrong.
    """

    def __init__(self) -> None:
        self._grants: dict[tuple[str, str], Level] = {}

    def grant(self, agent: str, fields: str | tuple[str, ...], level: Level) -> Table:
        names = (fields,) if isinstance(fields, str) else tuple(fields)
        for name in names:
            self._grants[(agent, name)] = level
        return self

    def level_for(self, agent: str, field_name: str) -> Level:
        exact = self._grants.get((agent, field_name))
        if exact is not None:
            return exact
        # "deal.*" grants everything under deal - the children, not the parent. The
        # prefix of a dotless name is itself, so a grant on "patch.*" used to answer a
        # question about bare "patch": "may draft a patch" authorised writing the patch.
        if "." not in field_name:
            return Level.NEVER
        prefix = field_name.split(".", 1)[0]
        return self._grants.get((agent, f"{prefix}.*"), Level.NEVER)

    def check(self, agent: str, field_name: str) -> Level:
        level = self.level_for(agent, field_name)
        if level is Level.NEVER:
            raise NotAuthorisedError(f"{agent} may never write {field_name}")
        return level

    def apply(self, agent: str, changes: dict[str, object]) -> Applied:
        """Split a proposed change set by what this agent is allowed to do."""
        out = Applied()
        for name, value in changes.items():
            level = self.level_for(agent, name)
            if level is Level.WRITE:
                out.written[name] = value
            elif level is Level.PROPOSE:
                out.proposed[name] = value
            else:
                out.refused[name] = value
        return out
