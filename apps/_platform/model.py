"""Async Ollama client, cached in Redis, with bounded concurrency.

Two things this does that a plain `httpx.post` does not.

**It keeps the GPU busy.** One request at a time leaves the card at about 9% utilisation:
it spends nearly all of its time waiting for the next HTTP round trip rather than decoding.
Eight in flight takes it to ~98%. That was measured on this machine and it roughly halves
every run in this repo, so the default is a bounded pool rather than a loop.

**It shares a cache across apps.** Several of these apps ask the model literally the same
questions - the first-attempt prompt in Repair-or-Rewrite is identical to the one in Size
Curve. Keyed on `(model, prompt, temperature, seed)` in Redis, the second app pays nothing,
which is what makes clicking through ten tools on one GPU tolerable.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Sequence

import httpx

from . import cache

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("MODEL", "qwen2.5-coder:14b")
CONCURRENCY = int(os.environ.get("GEN_CONCURRENCY", "8"))
#: How long to wait on the reachability probe. A page render asks this question
#: and nothing else about the model, so it must be cheap to answer.
PROBE_TIMEOUT = float(os.environ.get("OLLAMA_PROBE_TIMEOUT", "5.0"))


async def generate(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    seed: int | None = None,
    num_predict: int = 512,
    timeout: float = 240.0,
    use_cache: bool = True,
) -> str | None:
    """One completion. None only if the model could not be reached."""
    if use_cache:
        hit = await cache.get_generation(model, prompt, temperature, seed, num_predict)
        if hit is not None:
            return hit

    options: dict = {"temperature": temperature, "num_predict": num_predict}
    if seed is not None:
        options["seed"] = seed
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{OLLAMA}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "options": options},
            )
            r.raise_for_status()
            text = r.json().get("response", "")
    except (httpx.HTTPError, ValueError):
        return None

    if use_cache:
        await cache.put_generation(model, prompt, temperature, seed, text, num_predict)
    return text


async def generate_many(
    prompts: list[str],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    seeds: list[int | None] | None = None,
    num_predict: int = 512,
    concurrency: int = CONCURRENCY,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[str | None]:
    """Many completions, in prompt order, `concurrency` in flight."""
    seeds = seeds or [None] * len(prompts)
    sem = asyncio.Semaphore(concurrency)
    done = 0
    lock = asyncio.Lock()

    async def one(i: int) -> str | None:
        nonlocal done
        async with sem:
            out = await generate(
                prompts[i],
                model=model,
                temperature=temperature,
                seed=seeds[i],
                num_predict=num_predict,
            )
        async with lock:
            done += 1
            current = done
        if on_progress and (current % 5 == 0 or current == len(prompts)):
            await on_progress(current, len(prompts))
        return out

    return list(await asyncio.gather(*(one(i) for i in range(len(prompts)))))


async def embed(texts: list[str], model: str = "nomic-embed-text") -> list[list[float]] | None:
    """Batched embeddings. The per-item endpoint is ~100x slower when a 14B holds VRAM."""
    out: list[list[float]] = []
    try:
        async with httpx.AsyncClient(timeout=240) as client:
            for i in range(0, len(texts), 256):
                r = await client.post(
                    f"{OLLAMA}/api/embed",
                    json={"model": model, "input": texts[i : i + 256], "keep_alive": "30m"},
                )
                r.raise_for_status()
                out.extend(r.json()["embeddings"])
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return out


class ModelUnreachable(RuntimeError):
    """Some generations never happened.

    A generation that did not happen is not a wrong answer, and the difference is the
    whole product: every app here publishes a rate over model output, and an empty
    string scored as a failed attempt moves that rate without moving anything real.
    With the model down from the start, five of the six runners used to return a
    finished, all-zero measurement with status `done`; with it dying part-way, one app
    reported a 3B model beating a 14B by 25 points from a run where seven eighths of
    the calls never reached a model.
    """


def require_all(raws: Sequence[str | None], *, what: str = "generation") -> list[str]:
    """Every completion, or refuse. Never a blank standing in for one."""
    lost = sum(1 for raw in raws if raw is None)
    if lost:
        raise ModelUnreachable(
            f"{lost} of {len(raws)} {what}s never reached the model. No rate is "
            "published from a partial run: a lost generation is not a wrong answer."
        )
    return [raw for raw in raws if raw is not None]


def require(raw: str | None, *, what: str = "generation") -> str:
    """One completion, or refuse."""
    return require_all([raw], what=what)[0]


#: How long a failed reachability check is believed. `cache` and `bus` both have one of
#: these; `model` did not, so `health()` - which every page handler calls - paid the
#: full connect timeout on every render of every app. Two of three dependencies had the
#: pattern and the third was the one on the hot path.
DOWN_FOR = float(os.environ.get("OLLAMA_RETRY_AFTER", "5.0"))
_down_until = 0.0

#: How long a *successful* tag listing is believed. The down-memory above fixed the
#: machine with no Ollama; on a machine with one, `tags()` still made an HTTP round trip
#: on every call. `health()` is called by every page handler, so every render of every
#: app paid it - 0.29s measured here, against a server on localhost. `_tags` already
#: held the answer and nothing read it: the cache was written and never wired up, which
#: is why the cost was invisible.
#:
#: Short, because pulling a model has to show up without a restart. A pull takes minutes
#: and this is seconds, so the badge is behind by at most one page refresh.
TAGS_TTL = float(os.environ.get("OLLAMA_TAGS_TTL", "5.0"))
_tags: tuple[str, ...] = ()
_tags_until = 0.0


async def tags() -> tuple[str, ...]:
    """Every model tag the server holds, as `name:tag`."""
    global _down_until, _tags, _tags_until
    now = time.monotonic()
    if now < _down_until:
        return ()
    if now < _tags_until:
        return _tags
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            r = await client.get(f"{OLLAMA}/api/tags")
            r.raise_for_status()
            names = tuple(m["name"] for m in r.json().get("models", []) if m.get("name"))
    except (httpx.HTTPError, ValueError, KeyError):
        _down_until = time.monotonic() + DOWN_FOR
        # Kept consistent with `_down_until` rather than left behind. This does not
        # close the stale window - the TTL check above runs before any probe, so inside
        # it a dead server is still reported as up, and `TAGS_TTL` is the only thing
        # that bounds that. `test_a_server_that_went_away_is_still_reported_up_for_as
        # _long_as_the_ttl` pins the window at five seconds for exactly that reason.
        _tags, _tags_until = (), 0.0
        return ()
    _down_until = 0.0
    _tags = names
    _tags_until = time.monotonic() + TAGS_TTL
    return names


def forget_tags() -> None:
    """Drop the cached listing. For tests, and for a caller that just pulled."""
    global _tags, _tags_until, _down_until
    _tags, _tags_until, _down_until = (), 0.0, 0.0


async def available(model: str = DEFAULT_MODEL) -> bool:
    """Whether THIS model is there, not whether something of its family is.

    `"qwen2.5-coder:14b".split(":")[0] in r.text` was true for
    `qwen2.5-coder:does-not-exist`, so an app comparing a 3B against a 14B showed a
    green badge and an enabled Run button for a size the server does not hold - and
    then published the comparison with one arm entirely fabricated.
    """
    held = await tags()
    if not held:
        return False
    if ":" in model:
        return model in held or f"{model}:latest" in held
    return any(name.split(":")[0] == model for name in held)
