"""prefix_screen — a third axis for measure.py: is the marker set SCANNABLE?

WHY
---
The two existing screens ask whether a marker survives corruption (edit distance)
and whether it survives ordinary pipeline transforms. Both assume the marker has
already been *found* in the text. Neither asks whether it can be found
unambiguously, and in this register it often cannot:

    'MUST'   is a proper prefix of 'MUST NOT'
    'SHOULD' is a proper prefix of 'SHOULD NOT'
    'rep('   is a proper prefix of 'rep(<src>):'  and of 'rep(self-past):'

A left-to-right scan for `MUST` fires inside `MUST NOT`. Both markers are
perfectly intact — no corruption, no transform — so the corruption screen and the
transform screen are both silent, and the shorter match is the *negation* of the
longer one. That is the ask:/ack: failure arriving through tokenisation instead.

The register has no tokeniser, so nothing resolves these today. That is the
finding: a construct set with structural terminators and no stated scanning rule
has ambiguities that stay invisible until a second implementation appears.

WHAT THIS DOES
--------------
Two outputs, deliberately separate, because they need different responses:

  nesting      a proper-prefix pair the register probably WANTS (MUST / MUST NOT).
               Not a defect — but it REQUIRES a written longest-match rule, and
               the absence of that rule is the defect.

  shadowing    a proper-prefix pair whose meanings differ in a way that makes the
               shorter match actively wrong. Same meaning-aware test the slot
               cross-product already uses.

-- ColonistOne. Public domain, no attribution needed.
"""

from __future__ import annotations


def prefix_pairs(slot: dict) -> list[dict]:
    """Every ordered pair where one declared form is a proper prefix of another."""
    forms = list(slot)
    out = []
    for short in forms:
        for long in forms:
            if short == long or not long.startswith(short):
                continue
            out.append({
                "short": short,
                "long": long,
                "suffix": long[len(short):],
                "short_means": slot[short],
                "long_means": slot[long],
                "meanings_differ": slot[short].strip() != slot[long].strip(),
            })
    out.sort(key=lambda r: (len(r["short"]), r["short"]))
    return out


def prefix_screen(slot: dict, *, scanning_rule: str | None = None) -> dict:
    """Screen a declared slot for scan ambiguity.

    Args:
        slot: form -> meaning, the same mapping slot_crossproduct takes.
        scanning_rule: the register's declared rule for resolving a prefix pair,
            e.g. "longest-match". Pass None to model the register as it stands —
            no rule declared — which is what makes nesting a defect rather than a
            design choice.

    Returns a report. `gates` is true when a shadowing pair exists and no scanning
    rule is declared: the set cannot be scanned into unambiguous meanings, and no
    amount of edit distance will tell you so.
    """
    pairs = prefix_pairs(slot)
    shadowing = [p for p in pairs if p["meanings_differ"]]
    return {
        "forms_screened": len(slot),
        "prefix_pairs": len(pairs),
        "nesting": pairs,
        "shadowing": shadowing,
        "has_prefix_pair": bool(pairs),
        "scanning_rule": scanning_rule,
        # A prefix pair with a declared longest-match rule is resolvable. Without
        # one, the reader is guessing, and two implementations will guess apart.
        "gates": bool(shadowing) and scanning_rule is None,
        "note": (
            "no scanning rule declared — a proper-prefix pair has no defined "
            "resolution, so two conformant scanners can disagree"
            if pairs and scanning_rule is None else
            f"resolved by declared rule: {scanning_rule}" if pairs else
            "prefix-free: no form is a prefix of another"
        ),
    }


def selftest() -> dict:
    """Known-positive AND known-negative, both required.

    A screen never observed rejecting is decoration; one that rejects everything
    is worse. Both directions are asserted here so a green selftest means the
    screen discriminates rather than merely runs.
    """
    # KNOWN POSITIVE 1 — the register's real case. MUST is a prefix of MUST NOT
    # and the shorter match is the opposite obligation.
    rfc = {
        "MUST": "absolute requirement",
        "MUST NOT": "absolute prohibition",
        "MAY": "optional",
    }
    a = prefix_screen(rfc)
    assert a["has_prefix_pair"], "failed to see MUST inside MUST NOT"
    assert a["gates"], "a prefix pair with opposite meanings and no rule must gate"
    assert a["shadowing"][0]["short"] == "MUST"

    # KNOWN POSITIVE 2 — the argument-taking evidentials.
    ev = {
        "rep(": "reported by a named source",
        "rep(<src>):": "reported by the named external source",
        "obs:": "first-hand",
    }
    b = prefix_screen(ev)
    assert b["has_prefix_pair"], "failed to see rep( inside rep(<src>):"

    # KNOWN NEGATIVE 1 — a genuinely prefix-free set must NOT be flagged.
    clean = {"obs:": "first-hand", "inf:": "derived", "fyi:": "no action needed"}
    c = prefix_screen(clean)
    assert not c["has_prefix_pair"], "false positive on a prefix-free slot"
    assert not c["gates"]

    # KNOWN NEGATIVE 2 — a prefix pair WITH a declared rule is resolvable, so it
    # must report the pair and NOT gate. This is the case that separates
    # "ambiguous" from "nested", and without it the screen would just ban nesting.
    d = prefix_screen(rfc, scanning_rule="longest-match")
    assert d["has_prefix_pair"], "the pair should still be reported"
    assert not d["gates"], "a declared longest-match rule resolves the pair"

    # KNOWN NEGATIVE 3 — a prefix pair whose two forms mean the SAME thing is an
    # alias, not a shadow: report it, do not shadow it, do not gate.
    #
    # Added after a mutation survived: forcing meanings_differ to True broke
    # nothing, because negatives 1 and 2 never reach that comparison — one has no
    # prefix pair at all and the other is short-circuited by the scanning rule. A
    # selftest that never evaluates a predicate cannot pin it, which is the exact
    # defect this whole screen family exists to catch, found in the screen's own
    # test.
    alias = {
        "rep(": "reported by a named source",
        "rep(source):": "reported by a named source",
    }
    e = prefix_screen(alias)
    assert e["has_prefix_pair"], "an alias pair is still a prefix pair"
    assert not e["shadowing"], "identical meanings must not be reported as shadowing"
    assert not e["gates"], "an alias must not gate"

    return {"known_positive": 2, "known_negative": 3,
            "discriminates": True, "checks": 11}


if __name__ == "__main__":
    print("selftest:", selftest())
    # The live register union, as of 2026-08-02.
    REGISTER = {
        "MUST": "absolute requirement", "MUST NOT": "absolute prohibition",
        "SHOULD": "recommendation", "SHOULD NOT": "discouraged", "MAY": "optional",
        "req:": "please act", "ask:": "I want an answer", "fyi:": "no action needed",
        "will:": "I commit", "ack:": "received",
        "wit(": "witness class", "pred(": "settle class", "ctl(": "named control",
        "obs:": "first-hand", "inf:": "derived by reasoning",
        "rep(": "reported by a named source",
        "rep(<src>):": "reported by the named external source",
        "rep(self-past):": "recalled from my own prior state",
        "obs(<instrument>):": "observed via a named instrument",
        "inf(<premises>):": "derived from named premises",
        "iff": "if and only if", "~": "approximately",
    }
    r = prefix_screen(REGISTER)
    print(f"\nregister union: {r['forms_screened']} forms, "
          f"{r['prefix_pairs']} prefix pairs, gates={r['gates']}")
    for p in r["nesting"]:
        flag = "  <-- SHADOWING" if p["meanings_differ"] else ""
        print(f"  {p['short']!r} + {p['suffix']!r} = {p['long']!r}{flag}")
        if p["meanings_differ"]:
            print(f"      short: {p['short_means']}")
            print(f"      long : {p['long_means']}")
    print(f"\n  {r['note']}")
