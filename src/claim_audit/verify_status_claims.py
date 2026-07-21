#!/usr/bin/env python3
"""Find memory files that contradict themselves about status. Local, fast, no network.

Why
---
On 2026-07-20 my ATL ballot memory said, in its own `description` field, "CAST
APPROVE 2026-07-18 (receipt d08f5fd4)" -- and, 40 lines later in the body, "HAVE
NOT CAST. Cast is gated on pinning the enforcement status". Both written by me,
in one file, about one ballot. I only noticed because I queried the API instead
of trusting either.

That is the dangerous shape for a memory system: a file loaded into context every
session, quoted back confidently, disagreeing with itself. Whichever half gets
read first wins, and there is no signal that the other half exists.

This does not try to understand the text. It looks for pairs of OPPOSED status
markers co-occurring in one file, which is narrow enough to be precise and was
exactly sufficient to catch the real case. Every hit is a prompt to go and check
the artifact -- never an automatic edit.

    python3 scripts/verify_status_claims.py
"""

from __future__ import annotations

import pathlib
import re

MEM = (
    pathlib.Path.home()
    / ".claude"
    / "projects"
    / "-home-user-claude-projects-ColonistOne"
    / "memory"
)

#: (label, done-pattern, not-done-pattern). Deliberately conservative: these fire
#: on assertive status language, not on prose that merely discusses a state.
#: (label, done-pattern, not-done-pattern).
#:
#: EVERY done-pattern carries a negative lookbehind excluding a preceding negation.
#: Without it `\bCAST\b` also matches inside "HAVE NOT CAST", so a file whose body
#: said "HAVE NOT CAST" scored as BOTH done and not-done, and the contradiction test
#: -- which requires done XOR not-done -- could never fire. The checker returned a
#: confident 0 against the exact historical file it was written to catch. Found on
#: 2026-07-21 by replaying that file through it instead of trusting the zero.
_NEG = r"(?<!not )(?<!NOT )(?<!never )(?<!NEVER )(?<!un)"

OPPOSED = [
    (
        "cast/not-cast",
        re.compile(_NEG + r"\b(?:CAST|✅ *CAST)\b", re.I),
        re.compile(r"\b(?:HAVE NOT CAST|NOT (?:YET )?CAST|⛔ *HAVE NOT)\b", re.I),
    ),
    (
        "merged/awaiting-merge",
        re.compile(_NEG + r"\bMERGED\b", re.I),
        re.compile(
            r"\b(?:awaiting (?:Jack'?s )?merge|not merged|open,? not merged|unmerged)\b",
            re.I,
        ),
    ),
    (
        "resolved/open",
        re.compile(_NEG + r"\b(?:RESOLVED|CLOSED|DISCHARGED|✅ *DONE)\b", re.I),
        re.compile(
            r"\b(?:still open|remains open|unresolved|OPEN /|⏳|🔴 *(?:open|pending))\b",
            re.I,
        ),
    ),
    (
        "published/unpublished",
        re.compile(_NEG + r"\b(?:PUBLISHED|LIVE on (?:PyPI|npm)|RELEASED)\b", re.I),
        re.compile(
            r"\b(?:NOT yet published|unpublished|awaiting release|not released)\b", re.I
        ),
    ),
    (
        "fixed/still-broken",
        re.compile(_NEG + r"\b(?:FIXED|✅ *fixed)\b", re.I),
        re.compile(r"\b(?:still (?:broken|failing|red)|NOT fixed|unfixed)\b", re.I),
    ),
    (
        "voted/not-voted",
        re.compile(
            _NEG
            + r"\b(?:my (?:approve|reject|vote) stands|already voted|VOTED (?:APPROVE|REJECT)|vote cast)\b",
            re.I,
        ),
        re.compile(
            r"(?:my_vote\s*[:=]\s*None|\bnot (?:yet )?voted\b|\bdo not auto-cast\b|\bNOT reviewed\b)",
            re.I,
        ),
    ),
]

#: A file that explicitly narrates a change of state is not contradicting itself.
#: "SUPERSEDED", "CORRECTED", "was X, now Y" are the honest way to record history.
RECONCILED = re.compile(
    r"SUPERSEDED|STATUS CORRECTED|RECONCILED|\bwas wrong\b|CORRECTION|no longer accurate",
    re.I,
)


def frontmatter_and_body(text: str) -> tuple[str, str]:
    """Split a memory file into its YAML frontmatter and its body."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    return text[:end], text[end + 4 :]


def contradictions(files: list[pathlib.Path]) -> list[dict]:
    """The PRIMARY check, as data.

    Extracted from main() so tests can drive the real decision instead of
    restating it. The first test suite re-implemented this condition inline;
    mutating the rule here left the suite green, because nothing in the test
    ever called this code. A test that copies the logic it is testing only ever
    proves the copy agrees with itself.
    """
    found = []
    for p in files:
        text = p.read_text(errors="ignore")
        fm, body = frontmatter_and_body(text)
        if not fm or RECONCILED.search(text):
            continue
        for label, done_re, notdone_re in OPPOSED:
            fm_done, fm_not = bool(done_re.search(fm)), bool(notdone_re.search(fm))
            body_done, body_not = (
                bool(done_re.search(body)),
                bool(notdone_re.search(body)),
            )
            # ASYMMETRIC ON PURPOSE. The two sides are not equally reliable:
            # "HAVE NOT CAST" is unambiguously a status assertion, whereas the
            # positive side is a bare word that also occurs in ordinary prose.
            # The first version required `not body_done` on both sides, so the
            # sentence "Cast is gated on pinning the enforcement status" -- prose,
            # four words after the real "HAVE NOT CAST" -- set body_done and
            # vetoed the finding. The checker returned 0 on the exact file it was
            # written for. So the specific side gates, and the noisy side does not.
            if (fm_done and body_not) or (fm_not and body_done and not body_not):
                found.append(
                    {
                        "file": p.name,
                        "axis": label,
                        "fm": "done" if fm_done else "not-done",
                    }
                )
    return found


#: An identifier two statements can BOTH be about: uuid head, PR number, version.
#: Anchoring on a shared identifier is what makes intra-body detection precise.
#: Whole-body co-occurrence was tried first and was useless -- one file legitimately
#: describes many objects, so "contains both markers" is almost always two different
#: subjects. "Contains both markers ABOUT THE SAME ID" almost never is.
IDENT = re.compile(r"\b(?:[0-9a-f]{8}|#\d{1,5}|v?\d+\.\d+\.\d+)\b")


def intra_body_contradictions(files: list[pathlib.Path]) -> list[dict]:
    """Lines within ONE body that make opposed status claims about ONE identifier.

    The case this exists for, found 2026-07-21: my ATL ballot note carried

        "... `my_vote:None`) -- NOT reviewed/analysed. Do NOT auto-cast ..."
        "48f01d57 (v0.5.3) still open ... -- my reject stands"

    Both in the body, both about ballot 48f01d57, flatly contradictory, and the
    ballot closed within 24 hours. The frontmatter-vs-body check returned 0 and
    was RIGHT to -- the contradiction was body-vs-body and simply outside its
    scope. A correct zero from a check that cannot see the failure is still a
    zero somebody will read as clean, which is why the scope note printed under
    it was worth writing and why this function now exists.

    Neither line was checkable from inside the file. Only the API settled it --
    so a hit here is a prompt to go and ask the world, never an edit.
    """
    found = []
    for p in files:
        text = p.read_text(errors="ignore")
        if RECONCILED.search(text):
            continue
        _, body = frontmatter_and_body(text)
        # Sentence-ish units: a claim rarely straddles a line break in these notes.
        units = [ln for ln in body.split("\n") if ln.strip()]
        by_id: dict[str, list[str]] = {}
        for ln in units:
            for ident in set(IDENT.findall(ln)):
                by_id.setdefault(ident, []).append(ln)
        for ident, lns in by_id.items():
            if len(lns) < 2:
                continue
            for label, done_re, notdone_re in OPPOSED:
                says_done = [ln for ln in lns if done_re.search(ln)]
                says_not = [ln for ln in lns if notdone_re.search(ln)]
                # A single line asserting both is usually narration
                # ("was X, now Y"); two DIFFERENT lines disagreeing is the defect.
                pure_done = [ln for ln in says_done if ln not in says_not]
                pure_not = [ln for ln in says_not if ln not in says_done]
                if pure_done and pure_not:
                    found.append(
                        {
                            "file": p.name,
                            "axis": label,
                            "identifier": ident,
                            "done_line": pure_done[0].strip()[:120],
                            "notdone_line": pure_not[0].strip()[:120],
                        }
                    )
                    break
    return found


def main() -> int:
    files = sorted(MEM.glob("*.md"))

    # PRIMARY CHECK: does a file's own `description` contradict its body?
    #
    # This is the shape that actually cost me. The description is what lands in the
    # MEMORY.md index and gets quoted back; the body is what I read when I open the
    # file. When they disagree, whichever I hit first wins and nothing signals the
    # other exists. My ATL note said "CAST APPROVE" in its description and "HAVE NOT
    # CAST" forty lines down.
    #
    # Restricting to description-vs-body is what makes this precise. The earlier,
    # looser version flagged any file containing both markers anywhere, and most of
    # those were one file correctly describing two different objects -- PR #12 merged
    # and PR #5 not. Co-occurrence is not contradiction, and a checker that cries
    # wolf gets switched off.
    primary = contradictions(files)

    print("=" * 74)
    print("PRIMARY — frontmatter description contradicting its own body")
    print("=" * 74)
    print(
        f"  files with frontmatter scanned: {sum(1 for p in files if p.read_text(errors='ignore').startswith('---'))}"
    )
    print(f"  contradictions found          : {len(primary)}")
    for h in primary:
        print(
            f"    {h['file']}  [{h['axis']}] — description says {h['fm']}, body says the opposite"
        )
    if not primary:
        # Deliberately NOT "all clear". An earlier version printed "none. The ATL
        # case was the only instance of this shape" -- a confident claim about the
        # corpus, printed unconditionally, by a checker that at the time could not
        # fire at all. The zero was the bug and the message was covering for it.
        # State the scope, not a verdict.
        print(
            "    none matched. Scope: the 5 axes in OPPOSED, description-vs-body only."
        )
        print(
            "    A zero here means these patterns found nothing, NOT that memory is consistent."
        )

    intra = intra_body_contradictions(files)
    print()
    print("=" * 74)
    print("PRIMARY-B — one body contradicting itself about one identifier")
    print("=" * 74)
    print(f"  contradictions found          : {len(intra)}")
    for h in intra:
        print(f"    {h['file']}  [{h['axis']}]  id={h['identifier']}")
        print(f"      says done    : {h['done_line']}")
        print(f"      says not-done: {h['notdone_line']}")
    if not intra:
        print(
            "    none matched. Scope: the OPPOSED axes, between lines sharing an identifier."
        )

    # SECONDARY, reported but NOT counted as findings: opposed markers anywhere in
    # one file. Low precision by construction -- kept as a review prompt, with the
    # false-positive rate stated so nobody mistakes the count for a defect count.
    loose = 0
    for p in files:
        text = p.read_text(errors="ignore")
        if RECONCILED.search(text):
            continue
        for _, done_re, notdone_re in OPPOSED:
            if done_re.search(text) and notdone_re.search(text):
                loose += 1
                break
    print()
    print("=" * 74)
    print("SECONDARY — opposed markers co-occurring anywhere (LOW PRECISION)")
    print("=" * 74)
    print(f"  files: {loose}")
    print("  Not defects. Inspected by hand on 2026-07-21: the large majority are one")
    print("  file correctly describing two different objects. Reported as a review")
    print("  prompt only, and deliberately not summed into any headline number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
