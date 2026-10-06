"""The model interface, a fake that cannot reach a real one, and two wrappers.

``Recorded`` raises on any prompt it was not given, so a test cannot quietly
start calling ollama — which is what keeps this whole package runnable while a
model is still downloading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import keys
from .admission import Controller


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Model(Protocol):
    tag: str

    def generate(self, prompt: str, *, max_tokens: int = 512) -> Completion: ...


class UnscriptedPromptError(LookupError):
    """A test asked the fake model something it was not told how to answer."""


class AdmissionRejectedError(RuntimeError):
    """Admission control refused before the GPU was touched."""


@dataclass
class Recorded:
    """A deterministic stand-in for a model.

    Every prompt must be scripted. An unscripted prompt raises rather than
    returning something plausible, because a plausible answer from a fake is
    exactly how a test stops testing anything.
    """

    script: dict
    tag: str = "recorded"
    calls: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def generate(self, prompt: str, *, max_tokens: int = 512) -> Completion:
        if prompt not in self.script:
            raise UnscriptedPromptError(
                f"no scripted answer for {prompt[:60]!r}; add one rather than "
                "letting the test reach a real model"
            )
        self.calls.append(prompt)
        text = self.script[prompt]
        return Completion(
            text=text,
            model=self.tag,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(text.split()),
        )


@dataclass
class Cached:
    """Exact-match completion cache in front of any model."""

    inner: Model
    cache: object  # ports.Cache

    @property
    def tag(self) -> str:
        return self.inner.tag

    def generate(self, prompt: str, *, max_tokens: int = 512) -> Completion:
        key = keys.llmcache(self.inner.tag, prompt)
        hit = self.cache.get(key.name)
        if hit is not None:
            return Completion(text=hit, model=self.inner.tag, cached=True)
        completion = self.inner.generate(prompt, max_tokens=max_tokens)
        self.cache.set(key.name, completion.text, key.ttl_seconds)
        return completion


@dataclass
class Budgeted:
    """Admission control in front of any model.

    The check happens before the call, so a tenant over budget costs nothing
    rather than costing a generation that is then discarded.
    """

    inner: Model
    controller: Controller
    tenant: str = "default"

    @property
    def tag(self) -> str:
        return self.inner.tag

    def generate(self, prompt: str, *, max_tokens: int = 512) -> Completion:
        estimate = len(prompt.split()) + max_tokens
        decision = self.controller.admit(self.tenant, estimate)
        if not decision.admitted:
            raise AdmissionRejectedError(decision.reason)
        try:
            completion = self.inner.generate(prompt, max_tokens=max_tokens)
        except BaseException:
            # The call cost something unknown. The estimate stays charged, booked as
            # an estimate rather than as measured usage.
            self.controller.release(decision.reservation, None)
            raise
        # Settled against what the call really cost. `release` used to free the slot
        # and leave the worst-case estimate charged for good: a 19-word prompt
        # answered in four tokens stood at 515, which is 129 times its cost, and a
        # cache hit - which reaches no model at all - stood at the same.
        self.controller.release(decision.reservation, completion.total_tokens)
        return completion


@dataclass
class Ollama:
    """The real adapter. Imports httpx lazily and is never used in a test.

    Kept deliberately thin: everything interesting about running a model on one
    card lives in :mod:`agentplatform.admission`, not here.
    """

    tag: str
    host: str = ""
    timeout: float = 120.0

    def generate(self, prompt: str, *, max_tokens: int = 512) -> Completion:
        import httpx  # noqa: PLC0415 — deliberately lazy, see the docstring

        from .models import OLLAMA_HOST

        response = httpx.post(
            f"{self.host or OLLAMA_HOST}/api/generate",
            json={
                "model": self.tag,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        return Completion(
            text=body.get("response", ""),
            model=self.tag,
            prompt_tokens=body.get("prompt_eval_count", 0),
            completion_tokens=body.get("eval_count", 0),
        )
