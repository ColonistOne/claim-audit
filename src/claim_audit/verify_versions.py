#!/usr/bin/env python3
"""Verify version claims against the registry or repo that actually publishes them.

Why this is not just "GET pypi.org/pypi/{name}/json"
----------------------------------------------------
The extractor behind these claims matches `<word> <semver>`, so it cannot tell a
package name from the English word before a number. Of 195 extracted claims,
`was`, `published`, `since`, `into`, `against` and `tag` are all in the top 20
"packages". Feeding those to PyPI returns 404, and a naive checker would report
six REFUTED claims that were never claims.

The subtler trap is the opposite one. `langford`, `dantic` and `smolag` are my
dogfood agents; they are versioned in PRIVATE GitHub repos and were never meant
to be on PyPI. A 404 from PyPI says nothing whatsoever about whether
"langford 0.7.0" is true. Reporting it REFUTED would be the same mistake that,
on 2026-07-21, had this audit declare three live repos deleted -- and a false
REFUTED is the dangerous direction, because it invites me to "correct" a memory
file by deleting something true.

Resolution is NOT ordered first-match-wins. That design was tried and refuted a
true claim: `colony-oidc 0.4.0` was reported false because PyPI runs 0.3.0 ->
0.5.0, when the version is real -- tagged and GitHub-released, just never
published to PyPI. A registry list is complete for "was this published HERE",
and the claim never said "here". Checking the formalisation rather than the
claim, which is the failure this whole audit exists to find.

So every source is consulted, and each may confirm, refute, or ABSTAIN:

    PyPI / npm     confirm or refute -- publishing is the only route in, so
                   absence from the release list is genuine evidence
    GitHub tags    confirm ONLY -- tags are discretionary; ColonistOne/langford
                   has 4 tags against a codebase at 0.18.0
    unbound name   abstain -- see below

A verdict then follows three rules:

  * any source confirming  -> VERIFIED
  * refutation requires a BOUND REFERENT (a name in OWNED) and at least one
    source that positively establishes absence
  * a source's own abstention is binding and is never overruled by aggregation

Referent binding is the load-bearing part. "php 8.2.31" and "mariadb 10.6.27"
are true of the software on my server, and are ALSO names of unrelated PyPI
packages, so a naive lookup refutes a true claim from the wrong universe. And
STOPWORDS can never be sufficient: PyPI is large enough that `drove`, `her`,
`past`, `said` and `chosen` are all real packages. Any list of English I write
loses to the namespace, so an unbound name is simply not refutable.

Everything that is not VERIFIED or REFUTED is an admission that I could not
check -- which is a result, not a failure to produce one.

    python3 scripts/verify_versions.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLAIMS = ROOT / ".claims" / "claims.jsonl"
RESULTS = ROOT / ".claims" / "versions.jsonl"

#: Words the extractor mistook for package names. Not a blocklist of bad
#: packages -- a list of English. Anything here is reported NOT-A-CLAIM, which
#: is scored separately from every verification state so it can never pad a
#: pass rate.
STOPWORDS = {
    "was",
    "tag",
    "published",
    "into",
    "against",
    "since",
    "and",
    "the",
    "for",
    "with",
    "from",
    "than",
    "then",
    "now",
    "via",
    "per",
    "see",
    "run",
    "use",
    "spec",
    "sdk",
    "plugin",
    "version",
    "release",
    "released",
    "bump",
    "bumped",
    "cut",
    "ship",
    "shipped",
    "add",
    "added",
    "fix",
    "fixed",
    "merged",
    "live",
    "not",
    "but",
    "all",
    "new",
    "old",
    "our",
    "its",
    "has",
    "had",
    "are",
    "one",
}

UA = {"User-Agent": "colonist-one-claim-audit/1.0"}


def _get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"__http__": e.code}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def check_pypi(name: str, version: str) -> dict | None:
    """None means 'not a PyPI package' -- distinct from 'version not found'."""
    d = _get_json(f"https://pypi.org/pypi/{name}/json")
    if d is None or d.get("__http__"):
        return None
    releases = set(d.get("releases", {}))
    if version in releases:
        return {
            "state": "VERIFIED",
            "where": "pypi",
            "detail": f"{name} {version} on PyPI",
        }
    latest = d.get("info", {}).get("version", "?")
    return {
        "state": "REFUTED",
        "where": "pypi",
        "detail": f"{name} exists on PyPI but has no {version} (latest {latest})",
    }


def check_npm(name: str, version: str) -> dict | None:
    for cand in (name, f"@thecolony/{name}"):
        d = _get_json(f"https://registry.npmjs.org/{cand.replace('/', '%2F')}")
        if d is None or d.get("__http__"):
            continue
        if version in set(d.get("versions", {})):
            return {
                "state": "VERIFIED",
                "where": "npm",
                "detail": f"{cand} {version} on npm",
            }
        latest = d.get("dist-tags", {}).get("latest", "?")
        return {
            "state": "REFUTED",
            "where": "npm",
            "detail": f"{cand} exists on npm but has no {version} (latest {latest})",
        }
    return None


def check_github_tags(name: str, version: str) -> dict | None:
    """Authenticated, so private repos resolve. Read-only."""
    for owner in ("ColonistOne", "TheColonyAI", "TheColonyCC", "Cogproof"):
        try:
            p = subprocess.run(
                [
                    "gh",
                    "api",
                    f"/repos/{owner}/{name}/tags",
                    "--paginate",
                    "-q",
                    ".[].name",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if p.returncode != 0:
            continue
        tags = {t.strip().lstrip("v") for t in p.stdout.splitlines() if t.strip()}
        if version in tags:
            return {
                "state": "VERIFIED",
                "where": "github",
                "detail": f"{owner}/{name} tagged v{version}",
            }
        # A GIT TAG CAN CONFIRM BUT NEVER REFUTE, and this is not a nicety.
        #
        # ColonistOne/langford carries 4 tags -- v0.4.0, v0.5.0, v0.11.0,
        # v0.12.0 -- while its pyproject says 0.18.0. Fourteen or so versions
        # were simply never tagged. An earlier build of this checker read the
        # missing v0.7.0 tag as "langford 0.7.0 is a false claim", which is
        # inferring absence from a record that was never complete.
        #
        # This is the distinction that matters for the whole audit: PyPI and npm
        # release lists are COMPLETE BY CONSTRUCTION -- publishing is the only
        # way a version comes to exist there, so absence there is real evidence.
        # Tags are discretionary annotations a human or a script may skip. Same
        # HTTP 200, entirely different epistemic weight, and only the registry
        # earns the right to refute.
        return {
            "state": "UNVERIFIABLE",
            "where": "github",
            "detail": (
                f"{owner}/{name} exists with {len(tags)} tag(s), none {version}; "
                "tags are not a complete release record, so this is unknown, not false"
            ),
        }
    return None


#: Artifacts whose namespace I can actually BIND. A version claim is only
#: refutable when I know which artifact it is about, and for these I do: they are
#: mine, I publish them, and I can enumerate every place a version could live.
#:
#: This list is short on purpose. Coverage bought by guessing is worse than no
#: coverage, because it produces confident refutations of true statements.
OWNED = {
    "colony-sdk",
    "colony-chat",
    "colony-memory",
    "colony-oidc",
    "colony-skill",
    "langchain-colony",
    "crewai-colony",
    "openai-agents-colony",
    "pydantic-ai-colony",
    "smolagents-colony",
    "progenly",
    "oauth2-colony",
    "colony-login-bundle",
    "colony-sdk-js",
    "colony-sdk-go",
    "colony-sdk-python",
    "colony-agent-supervisor",
    "langford",
    "dantic",
    "smolag",
    "eliza-gemma",
    "cogproof",
    "witness-independence",
    "cadence",
    "attestation-envelope-spec",
}


def check_version(name: str, version: str) -> dict:
    """Resolve a version claim against EVERY source, then judge.

    Three corrections are baked in, each from a false REFUTED this produced on
    2026-07-21 against my own memory:

    1. STOPWORDS cannot scale. PyPI has hundreds of thousands of names, so
       `drove`, `her`, `past`, `said`, `stays`, `chosen` and `single` are all
       real packages. Any list of English I write will keep losing to the
       namespace. So an unbound name is never refutable, list or no list.

    2. NAME COLLISION ACROSS NAMESPACES. "php 8.2.31" and "mariadb 10.6.27" are
       true statements about the software on my server. There are also PyPI
       packages called `php` ("Handle some of the strange standards in PHP
       projects") and `mariadb` (a Python connector). Same string, different
       referent, and the checker refuted a true claim by looking it up in the
       wrong universe.

    3. FIRST-MATCH-WINS HID THE REST. `colony-oidc 0.4.0` was reported REFUTED
       because PyPI goes 0.3.0 -> 0.5.0. The version is real: tagged AND
       GitHub-released, just never published to PyPI. A registry's list is
       complete for "was this published HERE", which is not the question the
       claim asked. Checking the formalisation instead of the claim -- the same
       gap this whole audit exists to find.

    So: gather from all sources, confirm on any hit, and refute only when the
    referent is bound AND every readable source agrees the version is absent.
    """
    if name.lower() in STOPWORDS:
        return {
            "state": "NOT-A-CLAIM",
            "where": "-",
            "detail": "extractor caught the preceding English word, not a package",
        }

    evidence, sources = [], []
    for fn, tag in (
        (check_pypi, "pypi"),
        (check_npm, "npm"),
        (check_github_tags, "github"),
    ):
        got = fn(name, version)
        if got is None:
            continue
        sources.append(tag)
        evidence.append(got)
        if got["state"] == "VERIFIED":
            return {**got, "detail": got["detail"] + f" (checked {', '.join(sources)})"}

    if name.lower() not in OWNED:
        # Unbound referent. Something answered to the name, but I cannot show it
        # is the thing the claim was about, so I am not entitled to a verdict.
        seen = ", ".join(sources) if sources else "nothing"
        return {
            "state": "UNVERIFIABLE",
            "where": "-",
            "detail": (
                f"'{name}' is not an artifact I publish; {seen} answered to the name "
                "but the referent is unbound, so absence proves nothing"
            ),
        }

    # A SOURCE'S OWN ABSTENTION IS BINDING. check_github_tags returns
    # UNVERIFIABLE, not REFUTED, because a sparse tag list cannot establish
    # absence. An earlier version of this function collected that verdict and
    # then overruled it -- counting the source as "answered" and refuting on the
    # aggregate -- which re-broke `langford 0.7.0` immediately after the tag rule
    # was written to protect it. Only a source that positively claims the version
    # is missing gets a vote here.
    refuting = [e for e in evidence if e["state"] == "REFUTED"]
    if not refuting:
        abstained = ", ".join(sources) if sources else "nothing"
        return {
            "state": "UNVERIFIABLE",
            "where": "-",
            "detail": f"owned artifact; {abstained} answered but no source can establish absence",
        }

    where = "+".join(e["where"] for e in refuting)
    return {
        "state": "REFUTED",
        "where": where,
        "detail": f"{name}: {version} absent from {where}, which keeps a complete release record",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    rows = [json.loads(ln) for ln in CLAIMS.read_text().splitlines() if ln.strip()]
    vers = [r for r in rows if r["kind"] == "ver"]
    done = set()
    if RESULTS.exists():
        done = {
            json.loads(ln)["id"]
            for ln in RESULTS.read_text().splitlines()
            if ln.strip()
        }
    todo = [r for r in vers if r["id"] not in done][: a.limit]
    print(f"  {len(done)} done | {len(todo)} to check")

    with RESULTS.open("a") as fh:
        for i, c in enumerate(todo, 1):
            name, version = c["value"].split("==", 1)
            res = check_version(name, version)
            fh.write(json.dumps({**c, **res}) + "\n")
            fh.flush()
            if res["state"] == "REFUTED" or i % 25 == 0:
                print(
                    f"  [{i}/{len(todo)}] {res['state']:13} {c['value']:34} {res['detail'][:60]}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
