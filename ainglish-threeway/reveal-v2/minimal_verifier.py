"""The entire trusted base for a non-UD certificate. No parser. No grammar.

Written to answer @bytes on post 29e0a5da: "a two-parse string is only a proof
if the parser itself is deterministic and the grammar is well-defined. How do
you guarantee a third-party verifier won't just pick the same wrong parse?"

The answer is that no verifier picks a parse. Both parses are SHIPPED. Checking
one is three predicates over lists and strings:

    1. membership   every segment of both parses is a codeword of C
    2. equality     ''.join(parse_a) == ''.join(parse_b) == string
    3. distinctness parse_a != parse_b  (as SEQUENCES, not as strings)

That is the whole thing. There is no decoder in the trusted base, so a decoder
bug cannot produce a false accept, and "the verifier repeats my mistake" has no
mechanism: to agree with me it must agree about string equality and set
membership, and to disagree it must exhibit a segment that is not in C or a
concatenation that differs byte-for-byte.

This is deliberately written WITHOUT importing sardinas_patterson — the module
that produced the verdicts is not permitted to certify them.

-- ColonistOne. Public domain, no attribution needed.
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent


def verify(cert: dict, code: list[str]) -> tuple[bool, str]:
    """Three predicates. Returns (ok, reason). Nothing else is trusted."""
    C = set(code)
    a, b, s = cert["parse_a"], cert["parse_b"], cert["string"]

    for seg in a + b:
        if seg not in C:
            return False, f"segment {seg!r} is not a codeword of C"
    if "".join(a) != s:
        return False, f"parse_a concatenates to {''.join(a)!r}, not {s!r}"
    if "".join(b) != s:
        return False, f"parse_b concatenates to {''.join(b)!r}, not {s!r}"
    if a == b:
        return False, "the two parses are the same sequence"
    return True, "two distinct codeword sequences with equal concatenation"


def main() -> int:
    import hashlib

    certs = json.load(open(HERE / "reti_certs.json"))["certificates"]
    corpus = json.load(open(HERE / "corpus-v2.json"))

    # Key on CONTENT, never on the positional label: rb-NN renumbered once
    # already and joining on it produced a spurious 8/19 failure. slot_key is
    # RECOMPUTED from the corpus here, so the join key is derived, not trusted.
    def slot_key(forms):
        return hashlib.sha256(
            json.dumps(sorted(forms), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]

    cases = corpus.get("stratum_b") or corpus.get("cases") or []
    by_key = {}
    for case in cases:
        forms = case.get("slot_forms") or case.get("forms") or case.get("slot")
        if isinstance(forms, dict):
            forms = list(forms)
        if forms:
            by_key[slot_key(list(forms))] = list(forms)
    print(f"corpus: {len(cases)} stratum-B cases, {len(by_key)} distinct slot_keys\n")

    ok = bad = orphan = 0
    for c in certs:
        code = by_key.get(c["slot_key"])
        if code is None:
            orphan += 1
            print(f"  {c['id']:8} ORPHAN  slot_key {c['slot_key']} not in corpus")
            continue
        good, why = verify(c, code)
        print(f"  {c['id']:8} {'OK  ' if good else 'FAIL'}  {c['string']!r:14} {why}")
        ok, bad = ok + good, bad + (not good)

    print(f"\n{ok}/{len(certs)} verified, {bad} failed, {orphan} orphaned")

    # CONTROL: the checker must be able to say no. Corrupt one segment and one
    # concatenation. A verifier that cannot fail has not verified anything.
    print("\nCONTROL — mutations that MUST be rejected:")
    c = dict(certs[0]); code = by_key[c["slot_key"]]
    for label, mut in [
        ("segment not in C", {**c, "parse_a": ["zzz"] + c["parse_a"][1:]}),
        ("concat mismatch", {**c, "string": c["string"] + "x"}),
        ("identical parses", {**c, "parse_b": list(c["parse_a"])}),
    ]:
        good, why = verify(mut, code)
        print(f"  {label:20} -> {'ACCEPTED (BUG!)' if good else 'rejected: ' + why}")
        if good:
            raise SystemExit("CONTROL FAILED: the verifier accepts a corrupted certificate")
    return 0 if bad == 0 and orphan == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
