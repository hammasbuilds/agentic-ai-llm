"""Generate real per-platform variants with the local model, once.

one-desk's claim is about what an adapter actually produces. Measuring that
needs adapter output, so this produces some: real source texts, a real local
instruct model, the four prompts the product would use.

Writes `products/data/adapter_runs.json`. The test suite reads the cache and
never calls a model.

    python scripts/run_adapter.py            # 12 sources, whatever model is installed
    python scripts/run_adapter.py 20         # more sources
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "adapter_runs.json"
AMI = DATA / "ami_manual.zip"

sys.path.insert(0, str(ROOT / "03_one-desk" / "src"))
sys.path.insert(0, str(ROOT / "platform" / "src"))

from onedesk.adapter import PLATFORMS, PROMPTS  # noqa: E402


def sources(limit: int) -> list[str]:
    """Real content to adapt: AMI abstractive meeting summaries.

    Real prose about a real thing, long enough to have content words and short
    enough to be a plausible source post.
    """
    if not AMI.exists():
        raise SystemExit(f"{AMI} is missing; run scripts/fetch_data.sh")
    out: list[str] = []
    with zipfile.ZipFile(AMI) as zf:
        for name in sorted(zf.namelist()):
            if not name.startswith("abstractive/") or not name.endswith(".xml"):
                continue
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError:
                continue
            text = " ".join((n.text or "").strip() for n in root.iter("sentence")).strip()
            if not text:
                text = " ".join((n.text or "").strip() for n in root.iter("sent")).strip()
            words = text.split()
            if 60 <= len(words) <= 220:
                out.append(" ".join(words))
            if len(out) >= limit:
                break
    return out


def installed() -> list[str]:
    listed = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False).stdout
    return [ln.split()[0] for ln in listed.splitlines()[1:] if ln.strip()]


def generate(model: str, prompt: str, timeout: float = 600.0) -> str:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 220, "temperature": 0.7, "seed": 11},
        }
    ).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read()).get("response", "").strip()


def main(limit: int = 12) -> int:
    from agentplatform import models

    have = installed()
    try:
        chosen = models.resolve(models.GENERAL, have)
    except models.NoModelForRoleError as exc:
        print(exc)
        return 1
    print(f"using {chosen.note}")

    texts = sources(limit)
    print(f"{len(texts)} source texts")

    runs = []
    for i, source in enumerate(texts, 1):
        variants = {}
        for platform in PLATFORMS:
            try:
                variants[platform] = generate(chosen.tag, PROMPTS[platform].format(source=source))
            except Exception as exc:  # noqa: BLE001
                print(f"  {i}/{len(texts)} {platform}: FAILED {type(exc).__name__}")
                break
        if len(variants) == len(PLATFORMS):
            runs.append({"source": source, "variants": variants, "model": chosen.tag})
            print(f"  {i}/{len(texts)} ok")

    OUT.write_text(json.dumps({"runs": runs}, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT} - {len(runs)} runs x {len(PLATFORMS)} variants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 12))
