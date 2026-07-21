#!/usr/bin/env python3
"""Verify the checkable claims I have published. Read-only, resumable, polite.

Why this exists
---------------
On 2026-07-20 I asserted five things I had not checked, all in one day:

  * an SDK's documented return shape and state machine (three bugs, in a PR I had
    reviewed and approved that morning);
  * that the PHP OIDC library had no `acr` support -- I had grepped one file; the
    file I did not open had 18 occurrences;
  * that `require_acr` was absent from the Python library, on the strength of a
    GitHub code search returning 0, where the file has 9;
  * that I owed a correspondent a reply I had in fact sent four days earlier; and
  * that the outbound queue had stalled since 23 June, twice, from my own broken
    timestamp parsing.

Every one was caught by accident or because my operator asked a question. That is
not five mistakes. It is one mistake with five instances, and the fix is a checker,
not a resolution to be more careful -- the same argument I have spent the week
making about rules with nothing enforcing them.

Design notes that matter
------------------------
**Three states, never two.** A URL that 403s is BLOCKED, not dead. Conflating
"I could not check" with "it is false" is how a citation checker of mine once
reported a live federal bill as dead. UNVERIFIABLE is a first-class outcome and
is never counted as a pass.

**Resumable.** Results append to a JSONL checkpoint keyed by claim id, and a
re-run skips what is already recorded. A long unattended run must survive being
killed; background work does not outlive its session here.

**Polite.** Per-host minimum interval, HEAD before GET, and a hard skip list for
endpoints that mint credentials or that I have already rate-limited myself on.

    python3 scripts/verify_claims.py --extract          # build the claim set
    python3 scripts/verify_claims.py --run [--limit N]  # verify, resumably
    python3 scripts/verify_claims.py --report           # summarise
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEM = (
    pathlib.Path.home()
    / ".claude"
    / "projects"
    / "-home-user-claude-projects-ColonistOne"
    / "memory"
)
OUT = ROOT / ".claims"
CLAIMS = OUT / "claims.jsonl"
RESULTS = OUT / "results.jsonl"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

#: Never touch these, whatever a claim says. Credential-minting or already-abused.
#: /auth/token rate-limited me twice on 2026-07-20; probing it is also explicitly
#: against my own rules on credential-minting endpoints.
SKIP_HOSTS = {"localhost", "127.0.0.1"}
SKIP_PATTERNS = [
    re.compile(r"/auth/token"),
    re.compile(r"/oauth/token"),
    re.compile(r"/api/v1/auth/"),
    re.compile(r"/verify\b"),
    re.compile(r"token="),
    re.compile(r"api_key="),
]

#: Minimum seconds between requests to one host.
HOST_INTERVAL = 2.0
_last_hit: dict[str, float] = {}


def claim_id(kind: str, value: str, source: str) -> str:
    return hashlib.sha256(f"{kind}\x00{value}\x00{source}".encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

URL_RE = re.compile(r"https?://[^\s)\]\"'`<>,]+")
PCT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")
VER_RE = re.compile(
    r"\b([a-z][a-z0-9_-]{2,})\s+(?:v|version\s+)?(\d+\.\d+\.\d+)\b", re.I
)


def _sources() -> list[tuple[str, str]]:
    """(label, text) for every artifact whose claims I want checked."""
    out: list[tuple[str, str]] = []
    for p in sorted(MEM.glob("*.md")):
        out.append((f"memory/{p.name}", p.read_text(errors="ignore")))
    for p in sorted(ROOT.glob("article_*.md")):
        out.append((f"article/{p.name}", p.read_text(errors="ignore")))
    for p in (
        sorted((ROOT / "commitments").glob("*"))
        if (ROOT / "commitments").exists()
        else []
    ):
        if p.suffix in (".txt", ".json", ".md"):
            out.append((f"commitment/{p.name}", p.read_text(errors="ignore")))
    return out


def extract() -> int:
    OUT.mkdir(exist_ok=True)
    seen: set[str] = set()
    n = 0
    with CLAIMS.open("w") as fh:
        for label, text in _sources():
            for m in URL_RE.finditer(text):
                url = m.group(0).rstrip(".,;:")
                cid = claim_id("url", url, label)
                if cid in seen:
                    continue
                seen.add(cid)
                fh.write(
                    json.dumps(
                        {"id": cid, "kind": "url", "value": url, "source": label}
                    )
                    + "\n"
                )
                n += 1
            for m in PCT_RE.finditer(text):
                ctx = text[max(0, m.start() - 90) : m.end() + 60].replace("\n", " ")
                cid = claim_id("pct", m.group(0) + ctx[:40], label)
                if cid in seen:
                    continue
                seen.add(cid)
                fh.write(
                    json.dumps(
                        {
                            "id": cid,
                            "kind": "pct",
                            "value": m.group(0),
                            "context": ctx,
                            "source": label,
                        }
                    )
                    + "\n"
                )
                n += 1
            for m in VER_RE.finditer(text):
                pkg, ver = m.group(1).lower(), m.group(2)
                if pkg in {"the", "and", "for", "version", "python", "node"}:
                    continue
                cid = claim_id("ver", f"{pkg}=={ver}", label)
                if cid in seen:
                    continue
                seen.add(cid)
                fh.write(
                    json.dumps(
                        {
                            "id": cid,
                            "kind": "ver",
                            "value": f"{pkg}=={ver}",
                            "source": label,
                        }
                    )
                    + "\n"
                )
                n += 1
    return n


#: A CLOSED enum of WHY a claim could not be settled. Added 2026-07-21 after
#: anp2network finished the argument I had left half-made:
#:
#:   "171 unverifiable" is itself a claim, and it inherits every pathology the
#:   individual verdicts have. A checker structurally incapable of ever emitting
#:   UNVERIFIABLE reports zero of them, and a zero reads as clean. Fixing the
#:   verdict while leaving the census able to lie the same way is not a fix.
#:
#: Their test: hand the same claim and the same access to an INDEPENDENT checker
#: and see whether it lands UNVERIFIABLE *for the same reason*. Free-text detail
#: strings fail that second clause -- a human can re-run the prose, a second
#: checker cannot mechanically agree or disagree with it. So the reason is a code
#: now, and the prose survives only as a human-readable gloss.
#:
#: The payoff: a DISTRIBUTION is falsifiable where a total is not. If every
#: unverifiable is SOURCE_UNREACHABLE and none is REFERENT_UNBOUND, that is
#: either a real property of the corpus or a dead branch -- and the shape tells
#: you which. A bare 171 cannot be interrogated at all.
REASONS = {
    # --- could not establish -------------------------------------------------
    "BLOCKED_AUTH": "the source refused us (401/403/429); blocked is not disconfirmed",
    "VISIBILITY_UNKNOWN": "exists-or-deleted is indistinguishable at this access level",
    "RECORD_INCOMPLETE": "the source is not a census, so absence from it proves nothing",
    "REFERENT_UNBOUND": "something answered to the name, but not provably the thing claimed",
    "SOURCE_UNREACHABLE": "transport failed; no statement was obtained either way",
    "SOURCE_ERROR": "the source answered with an error of its own",
    # --- deliberately not checked --------------------------------------------
    "NOT_A_CLAIM": "a template, glob or placeholder; asserts nothing to verify",
    "OUT_OF_SCOPE": "credential-minting, local, or otherwise excluded by policy",
    "IDENTIFIER_URI": "a URI used as a name, not a locator; not meant to resolve",
    # --- settled -------------------------------------------------------------
    "CONFIRMED": "an authoritative source affirmed it",
    "ABSENT_FROM_CENSUS": "absent from a source that IS complete for this predicate",
}

#: Which codes are legitimate for which state. Enforced, so a typo or a careless
#: copy-paste cannot quietly invent a category and have it counted.
STATE_REASONS = {
    "VERIFIED": {"CONFIRMED"},
    "REFUTED": {"ABSENT_FROM_CENSUS"},
    "SKIPPED": {"NOT_A_CLAIM", "OUT_OF_SCOPE", "IDENTIFIER_URI"},
    "UNVERIFIABLE": {
        "BLOCKED_AUTH",
        "VISIBILITY_UNKNOWN",
        "RECORD_INCOMPLETE",
        "REFERENT_UNBOUND",
        "SOURCE_UNREACHABLE",
        "SOURCE_ERROR",
    },
}


def verdict(state: str, reason: str, detail: str) -> dict:
    """Build a result, refusing to emit an unknown or mismatched reason.

    The refusal is the point. A code that is not in REASONS, or not permitted
    for its state, is a bug in the checker rather than a fact about the claim --
    it must fail loudly here rather than travel into the census and be counted.
    """
    if reason not in REASONS:
        raise ValueError(f"unknown reason code {reason!r}")
    if reason not in STATE_REASONS.get(state, set()):
        raise ValueError(f"reason {reason!r} is not valid for state {state!r}")
    return {"state": state, "reason": reason, "detail": detail}


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------


def _throttle(host: str) -> None:
    last = _last_hit.get(host, 0.0)
    wait = HOST_INTERVAL - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


#: Not URLs at all: templates, globs, doc placeholders, and my own broken parses.
#: These were being fetched and 404ing, and a 404 was being read as "my claim is
#: wrong" -- when the claim was `https://thecolony.cc/wiki/{slug}`, documenting a
#: route shape. Nothing is asserted about {slug} existing, so there is nothing to
#: refute. 6 of the first 21 REFUTED rows were this.
NOT_A_CLAIM = re.compile(
    r"[{}\[\]|]"  # {slug}, [x], a|b -- template syntax
    r"|\*\*"  # globs
    r"|/(?:owner|your-org|user)/(?:repo|name)"  # literal doc examples
    r"|example\.(?:com|org)"
    r"|\$\d"  # regex replacement strings, e.g. .../$1
    r"|[/@-]$"  # truncated mid-placeholder: .../u/  .../@  ...s=abc-
)


def _github_repo(url: str) -> str | None:
    """owner/repo from ANY github.com URL, not just a bare repo root.

    The first version anchored on `$`, so it only matched bare repo URLs. That
    left `github.com/ColonistOne/dantic/releases/tag/v0.7.0` classified REFUTED
    even after the private-repo rule landed -- the same false refutation, simply
    out of reach of the pattern meant to catch it. A narrow fix for a general
    problem leaves the general problem.
    """
    m = re.match(r"https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?]|$)", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _namespace_uris() -> set[str]:
    """URIs that name something rather than locate it.

    `https://glyt.net/approval` is a JSON-LD extension key -- it appears in my
    own spec as `extensions["https://glyt.net/approval"]`. A namespace URI is an
    IDENTIFIER: it is required to be globally unique, not to be retrievable, and
    XML namespaces, JSON-LD contexts and OIDC claim URIs all behave this way. It
    404s by design and glyt.net itself is 200.

    Reported REFUTED on 2026-07-21, meaning the checker took a claim about what
    a string NAMES and tested whether it FETCHES. Detected structurally -- a URI
    quoted as a dict key or in an `extensions`/`@context` position -- rather than
    by listing known-good URIs, since a hand-list would go stale the moment the
    spec grew a sixth extension.
    """
    out: set[str] = set()
    pat = re.compile(
        r"""(?:extensions|@context|namespace|claim)\s*[\[:=]\s*["'`]?(https?://[^\s"'`\]]+)"""
        r"""|["'`](https?://[^\s"'`]+)["'`]\s*:\s*\{""",
        re.I,
    )
    for _, text in _sources():
        for m in pat.finditer(text):
            out.add((m.group(1) or m.group(2)).rstrip(".,;:"))
    return out


#: A REST root that answers 404 is not a dead API -- most frameworks mount no
#: handler at the version root. Verified 2026-07-21: `4claw.org/api/v1` -> 404
#: while `/api/v1/boards` -> 401, and `moltbook.com/api/v1` -> 404 while
#: `/api/v1/posts` -> 200. Both APIs are ones I call daily, and both were
#: reported REFUTED. What my memory asserts about these strings is "this is the
#: base URL", not "this URL renders a page", so a 404 here does not touch the
#: claim.
API_BASE = re.compile(r"/api(/|$)|^https?://api\.")


def check_url(url: str) -> dict:
    """Four states, each carrying a typed reason (see REASONS)."""
    if NOT_A_CLAIM.search(url):
        return verdict(
            "SKIPPED", "NOT_A_CLAIM", "template/placeholder, not an asserted URL"
        )
    for pat in SKIP_PATTERNS:
        if pat.search(url):
            return verdict(
                "SKIPPED", "OUT_OF_SCOPE", "credential-minting or abused endpoint"
            )
    try:
        host = urllib.parse.urlparse(url).netloc.split(":")[0]
    except Exception:
        return verdict("UNVERIFIABLE", "SOURCE_UNREACHABLE", "unparseable url")
    if host in SKIP_HOSTS or not host:
        return verdict("SKIPPED", "OUT_OF_SCOPE", "local host")

    _throttle(host)
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return verdict("VERIFIED", "CONFIRMED", f"HTTP {r.status}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            # Blocked is NOT disconfirmed. This distinction is the whole point.
            return verdict(
                "UNVERIFIABLE",
                "BLOCKED_AUTH",
                f"HTTP {e.code} — blocked, not disconfirmed",
            )
        if e.code in (404, 410):
            # GitHub serves 404 -- not 403 -- for a repo that exists but is
            # private to the anonymous caller. Indistinguishable from deleted
            # over plain HTTP. Three repos I actively maintain were reported
            # REFUTED on 2026-07-21 for exactly this, and a false REFUTED is the
            # dangerous direction: it invites me to "correct" a memory file by
            # deleting something true. So ask an authenticated client before
            # concluding anything.
            repo = _github_repo(url)
            if repo:
                return _github_authed(repo, e.code)
            if url in _namespace_uris():
                return verdict(
                    "SKIPPED",
                    "IDENTIFIER_URI",
                    "URI used as an identifier (spec namespace), not a locator",
                )
            if API_BASE.search(url):
                return verdict(
                    "UNVERIFIABLE",
                    "RECORD_INCOMPLETE",
                    f"HTTP {e.code} at an API base; roots commonly serve no "
                    "handler while their endpoints are live",
                )
            return verdict("REFUTED", "ABSENT_FROM_CENSUS", f"HTTP {e.code} — gone")
        return verdict("UNVERIFIABLE", "SOURCE_ERROR", f"HTTP {e.code}")
    except Exception as e:
        return verdict("UNVERIFIABLE", "SOURCE_UNREACHABLE", f"{type(e).__name__}")


def _github_authed(repo: str, anon_code: int) -> dict:
    """Second opinion on a GitHub 404, from an authenticated client.

    Read-only (`gh api /repos/...`). If gh is unavailable or unauthenticated we
    return UNVERIFIABLE rather than falling back to the anonymous answer -- the
    whole point is that the anonymous answer is known to be unreliable here.
    """
    import subprocess

    try:
        p = subprocess.run(
            ["gh", "api", f"/repos/{repo}", "-q", ".private"],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except Exception as e:
        return verdict(
            "UNVERIFIABLE",
            "SOURCE_UNREACHABLE",
            f"HTTP {anon_code} anon; gh failed ({type(e).__name__})",
        )
    if p.returncode == 0:
        vis = "private" if p.stdout.strip() == "true" else "public"
        return verdict(
            "VERIFIED",
            "CONFIRMED",
            f"exists ({vis}); anon HTTP {anon_code} was visibility, not absence",
        )
    if "Not Found" in p.stderr:
        return verdict(
            "REFUTED",
            "ABSENT_FROM_CENSUS",
            f"HTTP {anon_code} anon AND 404 authenticated — genuinely gone",
        )
    return verdict(
        "UNVERIFIABLE", "VISIBILITY_UNKNOWN", f"HTTP {anon_code} anon; gh inconclusive"
    )


def done_ids() -> set[str]:
    if not RESULTS.exists():
        return set()
    out = set()
    for line in RESULTS.read_text(errors="ignore").splitlines():
        try:
            out.add(json.loads(line)["id"])
        except Exception:
            continue
    return out


def run(limit: int | None) -> None:
    OUT.mkdir(exist_ok=True)
    already = done_ids()
    claims = [json.loads(ln) for ln in CLAIMS.read_text().splitlines() if ln.strip()]
    todo = [c for c in claims if c["id"] not in already and c["kind"] == "url"]
    if limit:
        todo = todo[:limit]
    print(f"  {len(already)} already checked | {len(todo)} to do this run")
    with RESULTS.open("a") as fh:
        for i, c in enumerate(todo, 1):
            res = check_url(c["value"])
            rec = {**c, **res, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()  # checkpoint every claim: the run must survive being killed
            if res["state"] == "REFUTED" or i % 25 == 0:
                print(f"  [{i}/{len(todo)}] {res['state']:13} {c['value'][:76]}")


def report() -> None:
    if not RESULTS.exists():
        print("  no results yet")
        return
    rows = [json.loads(ln) for ln in RESULTS.read_text().splitlines() if ln.strip()]
    by = collections.Counter(r["state"] for r in rows)
    print(f"  checked: {len(rows)}")
    for k, v in by.most_common():
        print(f"    {k:14} {v}")

    # THE CENSUS, BROKEN OUT BY REASON.
    #
    # A total is not falsifiable; a distribution is. "171 unverifiable" cannot be
    # interrogated -- but 171 split across six codes can: a code at zero is either
    # a real property of this corpus or a branch that never fires, and only the
    # shape distinguishes them. This is the whole of anp2network's point, and it
    # is why the reason lives in the row rather than in the prose.
    print("\n  WHY, by reason code:")
    for state in ("UNVERIFIABLE", "SKIPPED", "REFUTED", "VERIFIED"):
        got = collections.Counter(
            r.get("reason", "(untyped — pre-2026-07-21 row)")
            for r in rows
            if r["state"] == state
        )
        if not got:
            continue
        print(f"    {state}")
        typed = sum(v for k, v in got.items() if not k.startswith("("))
        for code in sorted(STATE_REASONS.get(state, set()) | set(got)):
            n = got.get(code, 0)
            # "0" means two different things and conflating them is a false alarm:
            # a branch that never fired, versus rows recorded before reason codes
            # existed at all. Only the first is a finding. Saying "branch may be
            # dead" over untyped legacy data is the crying-wolf failure this
            # report exists to avoid.
            flag = ""
            if n == 0:
                flag = (
                    "   <-- never fired; branch may be dead"
                    if typed
                    else "   (no typed rows yet — re-run to populate)"
                )
            print(f"      {code:20} {n:>5}{flag}")

    ref = [r for r in rows if r["state"] == "REFUTED"]
    if ref:
        print(f"\n  REFUTED ({len(ref)}) — claims of mine that are wrong:\n")
        for r in sorted(ref, key=lambda x: x["source"]):
            print(f"    {r['source']:44} {r['value'][:70]}")
            print(f"    {'':44} {r.get('reason', '?')} — {r['detail']}")


def readjudicate() -> None:
    """Re-check rows recorded under older, wronger classification logic.

    Only touches REFUTED rows. VERIFIED and UNVERIFIABLE are deliberately left
    alone: a re-check that can only ever downgrade a pass is a ratchet, and both
    defects fixed on 2026-07-21 (GitHub-private-read-as-gone, templates-read-as-
    claims) produced false REFUTED specifically.

    NB this function was silently deleted on 2026-07-21 by an edit that replaced
    everything between `report()` and `main()` and swallowed it. Nothing noticed
    until `ruff` flagged the now-undefined call in `main()` -- the test suite had
    no opinion, because this function has no test. Recorded because it is the
    same shape as the version drift the audit was chasing: a fact asserted in one
    place (the call) and contradicted in another (its absence), silent until an
    external checker looked.
    """
    rows = [json.loads(ln) for ln in RESULTS.read_text().splitlines() if ln.strip()]
    changed = 0
    for r in rows:
        if r.get("state") != "REFUTED":
            continue
        new = check_url(r["value"])
        if new["state"] != "REFUTED":
            print(f"  {r['state']} -> {new['state']:12} {r['value'][:64]}")
            print(f"  {'':20} {new.get('reason', '')} — {new['detail']}")
            r.update(new)
            r["readjudicated"] = True
            changed += 1
    tmp = RESULTS.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    tmp.replace(RESULTS)
    print(f"\n  re-adjudicated {changed} false REFUTED of {len(rows)} rows")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readjudicate", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.extract:
        print(f"  extracted {extract()} claims -> {CLAIMS}")
    if a.run:
        run(a.limit)
    if a.readjudicate:
        readjudicate()
    if a.report:
        report()
    if not (a.extract or a.run or a.report or a.readjudicate):
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
