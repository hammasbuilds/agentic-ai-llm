"""Freeze the survey the README's Results table quotes.

Not a test. Run it when the published figures change on purpose:

    REPOS_ROOT=/path/to/your/checkouts python tests/freeze_survey.py

Why a fixture at all. The live checks in `test_real_repos.py` keep a band, because
the folder they read is live and committing to any checkout in it moves the counts.
But the bands written for the published 1.64% were `0.010 < share < 0.030` — 67% wider
than the figure on one side — so they passed for 2.74% as happily as for 1.64%, and an
independent review pointed out that nothing anywhere checked the published numbers at
all. `grep -rn "1.64" tests/` found no match.

The frozen survey is the other half: the exact figures, with a test reading them back
out of the prose. The band says the tool still behaves; the fixture says the README
still describes what it did.

It drifts fast, which is the point. The first freeze differed from the README by 21
candidate claims within hours of the README being written, because the surveyed folder
includes this repository and I had spent the day editing its prose.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from driftwatch.domain import MECHANICAL, Claim, verify
from driftwatch.repos import ROOT, scan

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "survey.json"


def main() -> int:
    repos = scan()
    if len(repos) < 10:
        print(f"only {len(repos)} checkouts under {ROOT}; set REPOS_ROOT")
        return 1

    claims = [Claim(c) for r in repos for c in r.claims]
    mechanical = [c for c in claims if c.kind == MECHANICAL]
    verdicts = [
        (r.name, verify(c, r.facts))
        for r in repos
        for c in map(Claim, r.claims)
        if c.kind == MECHANICAL
    ]
    checked = [(n, v) for n, v in verdicts if v.checked]
    false = [(n, v) for n, v in checked if v.holds is False]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "measured": date.today().isoformat(),
                "note": (
                    "The survey the README's Results table quotes, frozen. The live "
                    "checks keep a band because the folder changes; these are the "
                    "exact figures published. Regenerate with tests/freeze_survey.py "
                    "when they change on purpose."
                ),
                "repositories": len(repos),
                "candidate_claims": len(claims),
                "mechanical": len(mechanical),
                "checked": len(checked),
                "false": len(false),
                "false_findings": [
                    {"repo": name, "detail": v.detail, "claim": v.claim.text[:120]}
                    for name, v in false
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(HERE.parent)}")
    print(
        f"  {len(repos)} repositories, {len(claims):,} claims, {len(mechanical)} "
        f"mechanical, {len(checked)} checked, {len(false)} false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
