#!/usr/bin/env python3
"""A bounded, method-independent falsifier for the 21 UD claims.

The reveal splits into a class settled by certificate (19 non-UD, checkable by
a stranger) and a class settled by three-way convergence (21 UD). Convergence
is the weaker evidence, and it is weaker in a specific way: all three ports
implement Sardinas--Patterson, so a shared misreading of the 1953 construction
would agree with itself three times and look like a result.

So this does not implement SP. It searches directly for the object SP is a
proxy for: a string with two distinct decompositions into slot forms. BFS over
concatenation states, bounded by string length and a node budget. It cannot
PROVE unique decodability -- a bounded search that finds nothing is a null, and
saying so is the point. It can only refute, which is exactly the direction the
convergence claim is exposed in.

THE CONTROL IS THE WHOLE ARGUMENT. The same search runs over the 19 non-UD
slots, where an ambiguous string is known to exist. If it fails to find those,
a null on the 21 means the search is broken, not that the claims hold.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import deque

HERE = pathlib.Path(__file__).parent
MAX_LEN = 24
NODE_BUDGET = 400_000


def slot_key(forms: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(forms), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def find_ambiguity(forms: list[str]) -> tuple[list[str], list[str]] | None:
    """BFS over built strings; the first string reachable by two different
    parses is a witness. Returns the two parses, or None within the bound."""
    forms = [f for f in forms if f]
    seen: dict[str, tuple[str, ...]] = {"": ()}
    q = deque([""])
    nodes = 0
    while q and nodes < NODE_BUDGET:
        s = q.popleft()
        nodes += 1
        for f in forms:
            t = s + f
            if len(t) > MAX_LEN:
                continue
            parse = seen[s] + (f,)
            if t in seen:
                if seen[t] != parse:
                    return list(seen[t]), list(parse)
                continue
            seen[t] = parse
            q.append(t)
    return None


def main() -> int:
    corpus = json.loads((HERE / "corpus-v2.json").read_text())
    mine = json.loads((HERE / "mine_outputs.json").read_text())
    result = json.loads((HERE / "diff_result.json").read_text())

    forms_by_key = {}
    for case in corpus.get("stratum_b") or corpus.get("cases") or []:
        f = case.get("slot_forms") or case.get("forms") or case.get("slot")
        if isinstance(f, dict):
            f = list(f)
        if f:
            forms_by_key[slot_key(list(f))] = list(f)

    ud, non_ud = [], []
    for r in mine:
        if not str(r["stratum"]).startswith("stratum_b"):
            continue
        (ud if r["uniquely_decodable"] else non_ud).append(r["slot_key"])

    print(f"bound: strings <= {MAX_LEN} chars, <= {NODE_BUDGET} BFS nodes per slot\n")

    print(f"== CONTROL: the {len(non_ud)} non-UD slots — the search MUST find these ==")
    ctl_found = 0
    for k in sorted(non_ud):
        w = find_ambiguity(forms_by_key[k])
        ctl_found += w is not None
        if w is None:
            print(f"  MISS  {k}  forms={forms_by_key[k]}")
    print(f"  {ctl_found}/{len(non_ud)} ambiguities found by an SP-free search")
    if ctl_found != len(non_ud):
        print("\n  ⇒ the search cannot find known ambiguity. A null on the UD side "
              "would measure the search, not the claim. STOPPING.")
        return 2

    print(f"\n== the {len(ud)} UD slots — an ambiguity here REFUTES the convergence ==")
    refuted = []
    for k in sorted(ud):
        w = find_ambiguity(forms_by_key[k])
        if w is not None:
            refuted.append((k, w))
            print(f"  REFUTED {k}: {w[0]} vs {w[1]}  forms={forms_by_key[k]}")
    print(f"  {len(ud) - len(refuted)}/{len(ud)} survive; {len(refuted)} refuted")

    print("\n== RESULT ==")
    if refuted:
        print(f"  {len(refuted)} of the 21 convergence-settled claims are REFUTED by an "
              "independent search. Three ports agreed on a wrong answer.")
    else:
        print(f"  A bounded SP-free search finds no ambiguity in any of the {len(ud)} UD "
              f"slots, with the same search finding all {ctl_found}/{len(non_ud)} known ones.")
        print("  This is a NULL, not a proof: absence of a witness under a bound is not")
        print("  unique decodability. It is a fourth check that does not share the ports'")
        print("  method, which is the only thing convergence was missing.")

    result["ud_falsifier"] = {
        "max_len": MAX_LEN,
        "node_budget": NODE_BUDGET,
        "control_non_ud_found": ctl_found,
        "control_non_ud_total": len(non_ud),
        "ud_checked": len(ud),
        "ud_refuted": len(refuted),
    }
    (HERE / "diff_result.json").write_text(json.dumps(result, indent=1))
    return 1 if refuted else 0


if __name__ == "__main__":
    raise SystemExit(main())
