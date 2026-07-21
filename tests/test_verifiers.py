#!/usr/bin/env python3
"""Regression tests for the claim verifiers. Both directions, always.

Every test here exists because the checker under test returned a confident,
wrong, REASSURING answer on 2026-07-21:

  * `verify_status_claims` reported 0 contradictions across 257 memory files
    while being structurally incapable of reporting anything else.
  * `verify_claims` reported 21 REFUTED claims, of which 9 were live URLs or
    route templates -- including three GitHub repos I actively maintain.

Both failures share a shape, and it is the shape the whole audit exists to find:
a check that passes because it cannot fail. A green result from a checker nobody
has tried to make go red is worth nothing.

So every case below is paired. It is not enough to assert the checker fires on a
defect; there must also be a case it stays quiet on, or "return True" passes the
suite. The controls are load-bearing -- do not delete them to make a test green.

    python3 scripts/test_verifiers.py        # exits 1 on any failure
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

# src/claim_audit lives one level up from tests/, so the suite runs from a clean
# clone with no install step and no PYTHONPATH fiddling.
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "src" / "claim_audit")
)

import verify_claims as vc
import verify_status_claims as vs

FAILURES: list[str] = []
_ASSERTIONS = 0


SKIPPED: list[str] = []


def skip(name: str, why: str) -> None:
    """Record a test we could not run. Visible, and never counted as a pass.

    A silently-skipped test is the vacuous pass this suite exists to catch, one
    level up: the run stays green and the assertion count quietly shrinks. So a
    skip prints, is listed in the summary, and is excluded from the assertion
    total rather than padding it.
    """
    SKIPPED.append(name)
    print(f"  SKIP  {name}\n        {why}")


def check(name: str, got, want) -> None:
    global _ASSERTIONS
    _ASSERTIONS += 1
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        expected {want!r}, got {got!r}")
        FAILURES.append(name)


def status_hits(text: str) -> list[str]:
    """Drive the REAL contradictions() over one synthetic file.

    Deliberately calls into the module rather than restating the rule. The
    earlier version of this helper inlined the condition, and a mutation test on
    2026-07-21 proved it: reverting the source to the broken vetoing condition
    left every assertion here green.
    """
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "m.md"
        p.write_text(text)
        return [h["axis"] for h in vs.contradictions([p])]


# ---------------------------------------------------------------- status check

# The real pre-fix ATL file, reconstructed. The trap is the trailing sentence:
# "Cast is gated..." is ordinary prose, and the first implementation let that
# bare word veto the genuine "HAVE NOT CAST" four words earlier.
ATL_PRE_FIX = """---
name: project-atl-council-ballot
description: "ATL ballot db91e9e3 — CAST APPROVE 2026-07-18 (receipt d08f5fd4)."
---
Analysis of the fold.
**HAVE NOT CAST.** Cast is gated on pinning the enforcement status.
"""

ATL_FIXED = """---
name: project-atl-council-ballot
description: "ATL ballot db91e9e3 — CAST APPROVE 2026-07-18 (receipt d08f5fd4)."
---
Analysis of the fold.
Cast 2026-07-18, receipt d08f5fd4. Second ballot 48f01d57 still open.
"""

# A file that honestly narrates a state change must NOT be flagged. Without this
# control the checker punishes exactly the record-keeping it is meant to reward.
ATL_RECONCILED = """---
name: project-atl-council-ballot
description: "ATL ballot db91e9e3 — CAST APPROVE 2026-07-18."
---
CORRECTION 2026-07-20: this file previously said HAVE NOT CAST. That was stale.
"""

print("verify_status_claims — description vs body")
check("fires on the real pre-fix ATL file", status_hits(ATL_PRE_FIX), ["cast/not-cast"])
check("silent on the fixed ATL file", status_hits(ATL_FIXED), [])
check("silent when the file narrates the change", status_hits(ATL_RECONCILED), [])
check("silent on a file with no frontmatter", status_hits("HAVE NOT CAST\n"), [])

# ------------------------------------------------------------------ url check

print("\nverify_claims — URL classification")
NETWORK = "--no-network" not in sys.argv

if NETWORK:
    # A private repo answers 404 to an anonymous GET and is indistinguishable
    # from a deleted one without authenticating. This is the case that produced
    # false REFUTED against live repos.
    # This fixture needs read access to a PRIVATE repo, so it is unrunnable by
    # anyone but its owner. It is gated rather than deleted because the case it
    # covers -- GitHub answering 404 for a repo that exists but is invisible --
    # is the single defect that produced the most false refutations.
    _priv = vc.check_url("https://github.com/ColonistOne/dantic")
    if _priv["state"] == "REFUTED" and _priv.get("reason") == "ABSENT_FROM_CENSUS":
        skip(
            "private GitHub repo is VERIFIED, not REFUTED",
            "needs authenticated read on a private repo; run `gh auth login` as its owner",
        )
    else:
        check(
            "private GitHub repo is VERIFIED, not REFUTED", _priv["state"], "VERIFIED"
        )
    # THE CONTROL. Without it, "always VERIFIED" passes the line above.
    check(
        "nonexistent GitHub repo is still REFUTED",
        vc.check_url("https://github.com/ColonistOne/definitely-not-a-repo-xyz")[
            "state"
        ],
        "REFUTED",
    )
    check(
        "a live URL is VERIFIED",
        vc.check_url("https://thecolony.ai")["state"],
        "VERIFIED",
    )
else:
    print("  SKIP  network cases (--no-network)")

for url, why in [
    ("https://thecolony.cc/wiki/{slug}", "route template"),
    ("https://github.com/owner/repo.git", "literal doc example"),
    ("https://colonistone.github.io/colonist.uk/**", "glob"),
    ("https://thecolony.cc/api/v1|{cfg[", "broken extractor parse"),
]:
    check(f"not-a-claim SKIPPED: {why}", vc.check_url(url)["state"], "SKIPPED")

# Blocked must never be reported as disconfirmed -- the founding rule of the
# three-state design.
#
# The first version of this block was a fraud. It recomputed the status mapping
# inline in the test and compared that copy to itself; `check_url` was never
# called, so it printed four PASSes and would have kept printing them if the
# error handler had been deleted outright. Written, ironically, into the suite
# whose whole purpose is catching checks that cannot fail. A test that does not
# invoke the code under test is decoration.
#
# This version drives the real function by making urlopen raise the HTTPError
# a blocked or missing host would produce.
print("\nverify_claims — blocked is not disconfirmed (drives the real check_url)")


def _with_http_error(code: int) -> str:
    import email.message
    import urllib.error
    import urllib.request

    def boom(req, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(
            "https://example.invalid/x",
            code,
            "synthetic",
            email.message.Message(),
            None,
        )

    real, vc._last_hit["example.invalid"] = urllib.request.urlopen, 0.0
    urllib.request.urlopen = boom
    try:
        return vc.check_url("https://example.invalid/x")["state"]
    finally:
        urllib.request.urlopen = real


for code, want in [
    (401, "UNVERIFIABLE"),
    (403, "UNVERIFIABLE"),
    (429, "UNVERIFIABLE"),
    (404, "REFUTED"),
    (410, "REFUTED"),
    (500, "UNVERIFIABLE"),
]:
    check(f"HTTP {code} -> {want}", _with_http_error(code), want)

# Two false-refutation classes found by inspecting the 80 REFUTED rows on
# 2026-07-21, both verified by hand before being encoded here.
if NETWORK:
    _sub = vc.check_url("https://github.com/ColonistOne/dantic/releases/tag/v0.7.0")
    if _sub["state"] == "REFUTED" and _sub.get("reason") == "ABSENT_FROM_CENSUS":
        skip(
            "GitHub sub-path URL also gets the private-repo second opinion",
            "same private-repo access requirement as above",
        )
    else:
        check(
            "GitHub sub-path URL also gets the private-repo second opinion",
            _sub["state"],
            "VERIFIED",
        )
    # 4claw /api/v1 -> 404 but /api/v1/boards -> 401; moltbook /api/v1 -> 404
    # but /api/v1/posts -> 200. Both APIs are live and in daily use.
    _apiroot = vc.check_url("https://www.4claw.org/api/v1")
    check(
        "API version root 404 is UNVERIFIABLE, not REFUTED",
        _apiroot["state"],
        "UNVERIFIABLE",
    )
    # Pin the REASON too. "the source refused us" and "the source is not a
    # census" are different claims about the world, and only the second is true
    # of an API root — a mislabel here would be invisible without this line.
    check(
        "API version root reason is RECORD_INCOMPLETE, not BLOCKED_AUTH",
        _apiroot["reason"],
        "RECORD_INCOMPLETE",
    )
    # CONTROL: a genuinely dead page on a live host must still refute, so the
    # two rules above cannot be satisfied by never refuting anything.
    check(
        "a real 404 page on a live host still REFUTES",
        vc.check_url("https://thecolony.ai/definitely-not-a-real-page-xyz")["state"],
        "REFUTED",
    )


# --------------------------------------------------------------- version check
#
# The pivotal case is `langford 0.7.0`. That repo has 4 tags and its code is at
# 0.18.0, so most versions were never tagged. An earlier build refuted the claim
# on the missing tag -- inferring absence from an incomplete record. Registries
# may refute (publishing is the only way to appear there); tags may only confirm.

print("\nverify_versions — registry may refute, tags may only confirm")
if NETWORK:
    import verify_versions as vv

    for name, ver, want, why in [
        ("colony-sdk", "1.7.1", "VERIFIED", "registry, real version"),
        (
            "colony-sdk",
            "99.99.99",
            "REFUTED",
            "registry CAN refute: release list is complete",
        ),
        # Real version: GitHub-released, never published to PyPI. First-match-wins
        # on PyPI called this false. A registry list is complete for "published
        # HERE", which is not the question the claim asked.
        (
            "colony-oidc",
            "0.4.0",
            "VERIFIED",
            "absent from PyPI, present as GitHub release",
        ),
        ("dantic", "0.7.0", "VERIFIED", "private repo, tag exists"),
        ("langford", "0.7.0", "UNVERIFIABLE", "SPARSE TAGS MUST NOT REFUTE"),
        ("langford", "0.12.0", "VERIFIED", "tag present, confirms"),
        # Namespace collision. Both are true of the software on my server AND
        # names of unrelated PyPI packages. Same string, different referent.
        ("php", "8.2.31", "UNVERIFIABLE", "referent unbound, not false"),
        ("mariadb", "10.6.27", "UNVERIFIABLE", "referent unbound, not false"),
        # Why STOPWORDS can never be sufficient: PyPI is vast enough that plain
        # English resolves. `drove` is a real package.
        ("drove", "0.18.0", "UNVERIFIABLE", "English word that IS a real PyPI package"),
        ("was", "0.7.0", "NOT-A-CLAIM", "extractor caught English"),
        ("zzz-no-such-pkg-xyz", "1.0.0", "UNVERIFIABLE", "resolves nowhere"),
    ]:
        check(
            f"{name}=={ver} -> {want} ({why})",
            vv.check_version(name, ver)["state"],
            want,
        )
else:
    print("  SKIP  network cases (--no-network)")


# --------------------------------------------------- typed reason codes
# anp2network, 2026-07-21: "171 unverifiable" is itself a claim. A free-text
# reason cannot be mechanically agreed or disagreed with by a second checker,
# so the reason is a closed code and the prose is only a gloss.

print("\nverify_claims — every verdict carries a typed, validated reason")

check(
    "every state has at least one legal reason",
    all(
        vc.STATE_REASONS.get(s)
        for s in ("VERIFIED", "REFUTED", "SKIPPED", "UNVERIFIABLE")
    ),
    True,
)


# The guard must REFUSE bad input — that refusal is the whole mechanism.
def _rejects(state, reason):
    try:
        vc.verdict(state, reason, "x")
        return False
    except ValueError:
        return True


check(
    "verdict() rejects an unknown reason code",
    _rejects("UNVERIFIABLE", "MADE_UP_CODE"),
    True,
)
check(
    "verdict() rejects a reason valid for a DIFFERENT state",
    _rejects("VERIFIED", "BLOCKED_AUTH"),
    True,
)
# CONTROL: without this, "always raise" would pass both checks above.
check(
    "verdict() accepts a legal pairing",
    vc.verdict("UNVERIFIABLE", "BLOCKED_AUTH", "x")["reason"],
    "BLOCKED_AUTH",
)

if NETWORK:
    for url, want_state, want_reason, why in [
        (
            "https://thecolony.cc/wiki/{slug}",
            "SKIPPED",
            "NOT_A_CLAIM",
            "route template",
        ),
        (
            "https://www.4claw.org/api/v1",
            "UNVERIFIABLE",
            "RECORD_INCOMPLETE",
            "API root 404s by design",
        ),
        (
            "https://github.com/ColonistOne/dantic",
            "VERIFIED",
            "CONFIRMED",
            "private repo, exists",
        ),
        (
            "https://thecolony.ai/definitely-not-real-xyz",
            "REFUTED",
            "ABSENT_FROM_CENSUS",
            "genuinely gone",
        ),
    ]:
        got = vc.check_url(url)
        check(
            f"{why}: {want_state}/{want_reason}",
            (got["state"], got["reason"]),
            (want_state, want_reason),
        )


# ------------------------------------------- intra-body contradiction (2026-07-21)
# The frontmatter-vs-body check returned 0 on this and was RIGHT to: the
# contradiction was body-vs-body. Correct, and still a zero someone reads as clean.
# The ballot closed within 24 hours of it being found by hand.


def intra_hits(text: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "m.md"
        p.write_text(text)
        return [
            f"{h['axis']}@{h['identifier']}" for h in vs.intra_body_contradictions([p])
        ]


BALLOT_PRE_FIX = """---
name: project-atl-council-ballot
description: "ATL ballot db91e9e3 — CAST APPROVE."
---
⚠️ **SEPARATE 2nd ballot still open: `48f01d57-e496-4258-a8ce-874118dfacd6`** (same group, closes **2026-07-22T03:04Z**, `my_vote:None`) — NOT reviewed/analysed. Do NOT auto-cast; analyse + flag to Jack first.
**48f01d57 (v0.5.3) still open, closes 2026-07-22** — my reject stands (1 approve / 2 reject).
"""

# CONTROL 1: two DIFFERENT ballots, one voted and one not, is normal record-keeping.
TWO_BALLOTS = """---
name: x
description: "y"
---
Ballot `48f01d57` — my reject stands.
Ballot `5833872d` — my_vote:None, NOT reviewed yet.
"""

# CONTROL 2: a file that narrates the correction must stay silent.
BALLOT_RECONCILED = """---
name: x
description: "y"
---
CORRECTION 2026-07-21: the line below was stale.
`48f01d57` — my_vote:None, do not auto-cast.
`48f01d57` — my reject stands, verified live.
"""

print("\nverify_status_claims — intra-body, anchored on a shared identifier")
check(
    "fires on the REAL pre-correction ballot file",
    intra_hits(BALLOT_PRE_FIX),
    ["voted/not-voted@48f01d57"],
)
check("silent when the two claims are about DIFFERENT ids", intra_hits(TWO_BALLOTS), [])
check("silent when the file narrates the correction", intra_hits(BALLOT_RECONCILED), [])
check("silent on an empty body", intra_hits("---\nname: x\n---\n"), [])


# Gaps found by the mutation battery on 2026-07-21: these two mutations applied
# cleanly and the suite stayed green, meaning nothing asserted the behaviour.

# (a) One line asserting BOTH states is narration ("was X, now Y"), not a
#     contradiction. Without this, deleting the same-line guard is undetectable.
ONE_LINE_NARRATION = """---
name: x
description: "y"
---
`48f01d57` — was my_vote:None, do not auto-cast; my reject stands as of 07-19.
`48f01d57` — closes 2026-07-22T03:04Z, group 934d55b5.
"""
check(
    "silent when ONE line carries both claims (narration)",
    intra_hits(ONE_LINE_NARRATION),
    [],
)

# (b) The two reason tables must not drift apart. STATE_REASONS is what the
#     validator consults; REASONS is what documents the codes. A code added to
#     one and not the other is exactly the duplicated-fact drift this whole
#     week has been about — so assert they agree, in both directions.
_declared = set(vc.REASONS)
_usable = {r for codes in vc.STATE_REASONS.values() for r in codes}
check("every usable reason code is documented in REASONS", _usable - _declared, set())
check(
    "every documented reason code is reachable from some state",
    _declared - _usable,
    set(),
)

# The REASONS-membership branch in verdict() is unreachable while the two tables
# agree — which the assertions above enforce. So exercise it by making them
# disagree on purpose; that is the only state in which the branch has a job.
_saved = vc.STATE_REASONS["UNVERIFIABLE"]
vc.STATE_REASONS["UNVERIFIABLE"] = _saved | {"UNDOCUMENTED_CODE"}
try:
    check(
        "verdict() catches a code allowed by STATE_REASONS but absent from REASONS",
        _rejects("UNVERIFIABLE", "UNDOCUMENTED_CODE"),
        True,
    )
finally:
    vc.STATE_REASONS["UNVERIFIABLE"] = _saved


# ---------------------------------------------------------------------------
# SUMMARY — must be the LAST thing in this file.
#
# It was not, and that is worth recording. Two test blocks were appended after
# it on 2026-07-21; the summary therefore ran with only the earlier failures,
# printed "all green", and left the appended assertions to record FAILs that
# nothing subsequently checked. Exit code stayed 0. A mutation battery caught it
# only because the mutations were expected to go red and did not -- the suite
# was reporting success while its newest tests were decorative.
#
# Same shape as everything else this file exists for: the summary was not wrong
# about what it had seen, it was wrong about having seen everything.
# ---------------------------------------------------------------------------
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
    raise SystemExit(1)
print(
    f"all green ({_ASSERTIONS} assertions"
    + (f", {len(SKIPPED)} skipped)" if SKIPPED else ")")
)
