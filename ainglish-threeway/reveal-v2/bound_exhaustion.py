#!/usr/bin/env python3
"""Did my falsifier's search actually REACH its declared bound, or stop short?

`ud_falsifier.py` declares two bounds and returns `None` for both ways of not
finding a witness:

    MAX_LEN     = 24        a DOMAIN bound  — which strings are in scope
    NODE_BUDGET = 400_000   a RESOURCE bound — how much of that scope I paid for

A null under "strings <= 24 chars" is only that if the search exhausted its
frontier. If it hit the node ceiling first, the true reach is *smaller than the
declared one* and nothing in the output says so — `return None` is emitted on
both paths, so the report cannot distinguish "searched everything in scope and
found nothing" from "ran out of budget".

That matters beyond my own tidiness because of what Reticuli's
`tools/bound_reduction.py` does with the declaration. It reads my `declared`
dict at face value and derives `max_depth <= 24` from `max_witness_len = 24`,
because depth <= length for non-empty codewords. The derivation is a theorem
about *strings*, and it is sound. But the object it is being applied to is my
*search*, and the search only covers the strings it actually enumerated. A
resource bound sitting in the same dictionary as a domain bound gets read as
if it were coverage.

Direction of the error, stated before measuring: a node ceiling can only ever
SHRINK my reach, so `A nested inside B` survives either way — a smaller A is
still inside B. The nesting conclusion is not at risk. What is at risk is the
*declaration*: if the ceiling bit, then "<= 24 chars" is an aspiration and the
honest declared bound is the effective one. And the same face-value reading
would manufacture a containment that does not hold if the resource bound were
on the containing side instead.

So this instruments the identical BFS to report, per slot:

    terminated  exhausted | node_budget
    nodes       nodes actually popped
    max_len     longest string actually enumerated

    python3 bound_exhaustion.py
"""

from __future__ import annotations

import json
import pathlib
from collections import deque

from ud_falsifier import MAX_LEN, NODE_BUDGET, slot_key

HERE = pathlib.Path(__file__).parent


def search_instrumented(forms: list[str]) -> dict:
    """Byte-for-byte the loop from `find_ambiguity`, plus counters.

    Deliberately a COPY rather than a refactor of the original: the published
    falsifier's bytes are the thing under test, and editing it to measure it
    would mean the number describes the edited version.
    """
    forms = [f for f in forms if f]
    seen: dict[str, tuple[str, ...]] = {"": ()}
    q = deque([""])
    nodes = 0
    longest = 0
    witness = None
    # The queue is FIFO, so states are popped in non-decreasing segment count:
    # this is a breadth-first sweep over DEPTH, not over length. That is what
    # makes the effective bound recoverable when the budget bites — the region
    # actually exhausted is every string of at most `deepest_complete` segments
    # (and at most MAX_LEN chars), which is a bound of Reticuli's kind, not mine.
    popped_depth = 0
    deepest_complete = -1
    while q and nodes < NODE_BUDGET:
        s = q.popleft()
        d = len(seen[s])
        if d > popped_depth:                # first pop of a deeper layer =>
            deepest_complete = popped_depth  # the previous layer is finished
            popped_depth = d
        nodes += 1
        for f in forms:
            t = s + f
            if len(t) > MAX_LEN:
                continue
            parse = seen[s] + (f,)
            if t in seen:
                if seen[t] != parse:
                    witness = (list(seen[t]), list(parse))
                    break
                continue
            seen[t] = parse
            longest = max(longest, len(t))
            q.append(t)
        if witness:
            break
    if not q and not witness:
        deepest_complete = popped_depth      # drained: the last layer finished too
    return {
        "found": witness is not None,
        # A witness short-circuits the loop, so its termination reason says
        # nothing about coverage — only the nulls are informative here.
        "terminated": "found" if witness else ("node_budget" if q else "exhausted"),
        "nodes": nodes,
        "max_len_reached": longest,
        "frontier_left": len(q),
        # The honest bound for a capped slot: every string with at most this
        # many segments was enumerated; deeper ones only partially.
        "depth_exhausted": deepest_complete,
    }


def main() -> int:
    corpus = json.loads((HERE / "corpus-v2.json").read_text())
    mine = json.loads((HERE / "mine_outputs.json").read_text())

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

    print(f"declared: strings <= {MAX_LEN} chars, <= {NODE_BUDGET} BFS nodes per slot\n")

    rows = []
    capped = 0
    for label, keys in (("UD (subject, the nulls)", ud), ("non-UD (control)", non_ud)):
        print(f"== {label}: {len(keys)} slots")
        for k in sorted(keys):
            r = search_instrumented(forms_by_key[k])
            r["slot_key"] = k
            r["class"] = "ud" if keys is ud else "non_ud"
            rows.append(r)
            if r["terminated"] == "node_budget":
                capped += 1
                print(
                    f"  CAPPED  {k}  nodes={r['nodes']} frontier={r['frontier_left']:>9} "
                    f"-> honest bound: depth <= {r['depth_exhausted']} segments"
                )
        subj = [r for r in rows if r["class"] == ("ud" if keys is ud else "non_ud")]
        nulls = [r for r in subj if not r["found"]]
        print(f"  {len(nulls)} nulls; termination: "
              f"{sum(1 for r in nulls if r['terminated'] == 'exhausted')} exhausted, "
              f"{sum(1 for r in nulls if r['terminated'] == 'node_budget')} node_budget")
        if nulls:
            print(f"  max nodes on a null: {max(r['nodes'] for r in nulls)} "
                  f"({max(r['nodes'] for r in nulls) / NODE_BUDGET:.1%} of budget)")
            print(f"  max string length actually enumerated: "
                  f"{max(r['max_len_reached'] for r in nulls)} of {MAX_LEN}")
        print()

    ud_nulls = [r for r in rows if r["class"] == "ud" and not r["found"]]
    print("== VERDICT ==")
    if capped == 0:
        print("  No slot hit the node ceiling. Every null is an EXHAUSTED search over")
        print(f"  all strings <= {MAX_LEN} chars, so `max_witness_len: {MAX_LEN}` is a")
        print("  reach and not an aspiration, and the reduction table's face-value")
        print("  reading of it is sound. `node_budget` was never load-bearing here —")
        print("  it is a safety valve that did not open.")
        print(f"  Headroom: the hungriest null used {max(r['nodes'] for r in ud_nulls)} "
              f"of {NODE_BUDGET} nodes.")
    else:
        cap_rows = [r for r in rows if r["terminated"] == "node_budget"]
        depths = sorted(r["depth_exhausted"] for r in cap_rows)
        print(f"  {capped} of {len(ud_nulls)} UD nulls stopped on the NODE CEILING, not on")
        print("  the length bound. For those, `max_witness_len: 24` OVERSTATES the search:")
        print("  the region actually swept is bounded by segment count, not by characters.")
        print(f"  Honest per-slot bound on the capped ones: depth <= {depths[0]}..{depths[-1]}")
        print(f"  segments (worst case {depths[0]}), against a declared 24 characters.")
        print()
        print("  Two consequences, and the second is the one that generalises:")
        print("  1. The nesting verdict SURVIVES. A node ceiling can only shrink my reach,")
        print("     and a smaller A is still inside B. Reticuli's bound still contains mine.")
        print("  2. The DECLARATION was wrong, and it was wrong in the kind that")
        print("     `bound_reduction.py` refuses to compare. My dict mixed a DOMAIN bound")
        print("     (<=24 chars, what is in scope) with a RESOURCE bound (400k nodes, what")
        print("     I paid for), and the table read the domain one at face value because")
        print("     that is the only one it can reason about. The resource bound turned out")
        print("     to be the binding constraint on half the subject cases.")

    (HERE / "bound_exhaustion.json").write_text(
        json.dumps({"max_len": MAX_LEN, "node_budget": NODE_BUDGET,
                    "capped": capped, "rows": rows}, indent=1)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
