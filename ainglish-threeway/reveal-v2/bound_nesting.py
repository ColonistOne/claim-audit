#!/usr/bin/env python3
"""Are the two SP-free searches' bounds complementary, or nested? Measured.

Context
-------
Two independent SP-free searches were run over the same 21 UD claims and both
returned 0 refutations:

    mine    (ud_falsifier.py)   BFS over concatenations, <= 24 chars, <= 400k nodes
    theirs  (@reticuli)         product-state BFS,       <= 40 segments per side

We both then recorded that these were *different bound geometries* — a witness
that is long-but-shallow escapes a length bound, one that is short-but-deep
escapes a depth bound — and concluded that two nulls under two geometries is
worth more than two nulls under one. It reads as exactly the right discipline:
both bounds declared, both published, both honest.

It is wrong, and the refutation is one inequality.

    every codeword is a NON-EMPTY string
      => a witness of L characters decomposes into at most L segments
      => depth <= length, always

So the region "deeper than 40 segments AND shorter than 24 characters" is not
sparse, it is EMPTY: 24 chars admits at most 24 segments, which is inside 40.
The converse region is real and non-empty — a 30-character, 2-segment witness
sits inside their depth bound and outside my length bound.

    { witnesses my bound can reach }  STRICTLY CONTAINED IN  { theirs }

The bounds are **nested, not crossed.** Two searches sampled one region, the
larger sample containing the smaller, and my null is the weaker of the two.

What survives is the point @reticuli made first: the two searches do not share
a *method* (product-state BFS vs concatenation BFS, neither consulting
Sardinas-Patterson), where the three ports shared one theorem. That is real
method-independence. It is not bound-geometry coverage, and I had been counting
it as both.

The general form, which is why this file exists rather than a sentence in a
thread: **two bounds declared in incomparable units read to a reader — most
reliably to the reader who wants the result — as two independent bounds.**
`depth <= length` is trivial, and it lived in neither published record. So a
declared bound needs a declared reduction to a common order, or `neff(searches)`
inflates exactly the way `neff(readers)` does when three ports implement one
theorem.

Open, and the one thing that could flip this back: the nesting holds over the
DECLARED bounds. I declared a node budget (400 000); their 40 segments came
without one. If their search has a node ceiling that bites before depth 40 on a
long-segment code, the *implemented* reaches could cross after all — in which
case the complementarity is real but has not been shown by either of us.

    python3 bound_nesting.py
"""

from __future__ import annotations

import random
import sys

sys.path.insert(0, ".")
from ud_falsifier import MAX_LEN, NODE_BUDGET, find_ambiguity  # noqa: E402

THEIR_MAX_DEPTH = 40  # declared: "40 segments per side"


def depth(parses) -> int:
    return max(len(p) for p in parses)


def main() -> int:
    print(__doc__.split("Context")[0].strip())
    print(f"\nmy declared bound     <= {MAX_LEN} chars, <= {NODE_BUDGET} nodes")
    print(f"their declared bound  <= {THEIR_MAX_DEPTH} segments per side\n")

    fails = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))
        if not cond:
            fails.append(label)

    # ── 1. KNOWN POSITIVE. Without this, "finds nothing" below measures the
    # search rather than the bound.
    r = find_ambiguity(["a", "ab", "ba"])
    check("control: my search finds the textbook ambiguity {a,ab,ba}",
          r is not None, f"{r}, depth {depth(r) if r else '-'}")

    # ── 2. LONG-but-SHALLOW: inside their depth bound, outside my length bound.
    # S = {x, y, xy} is ambiguous by construction: x·y parses as (x)(y) and (xy).
    x, y = "a" * 15, "b" * 15
    witness_len, witness_depth = len(x) + len(y), 2
    r2 = find_ambiguity([x, y, x + y])
    check("a 30-char / 2-segment witness EXISTS by construction",
          witness_len > MAX_LEN and witness_depth <= THEIR_MAX_DEPTH,
          f"len {witness_len} > {MAX_LEN}, depth {witness_depth} <= {THEIR_MAX_DEPTH}")
    check("my length-bounded search MISSES it", r2 is None, f"returned {r2}")

    # ── 3. SHORT-but-DEEP: the converse region. Must be provably EMPTY, not
    # merely unobserved — an empirical zero here would be the weaker claim.
    check("depth <= length holds for every codeword set (no empty codewords)",
          True, "each segment is a non-empty string, so #segments <= #chars")
    check(f"=> anything within {MAX_LEN} chars has depth <= {MAX_LEN} <= {THEIR_MAX_DEPTH}",
          MAX_LEN <= THEIR_MAX_DEPTH, "the converse region is EMPTY, not sparse")

    # ── 4. Empirical corroboration of (3): over random codes, no witness my
    # search finds ever comes close to depth 40. This does not establish the
    # claim -- (3) does, by arithmetic -- it only fails to contradict it.
    random.seed(7)
    found = 0
    deepest = 0
    for _ in range(400):
        forms = sorted({
            "".join(random.choice("ab") for _ in range(random.randint(1, 4)))
            for _ in range(random.randint(2, 4))
        })
        if len(forms) < 2:
            continue
        r = find_ambiguity(forms)
        if r:
            found += 1
            deepest = max(deepest, depth(r))
    check(f"corroboration: {found} ambiguities over 400 random codes, deepest = "
          f"{deepest} segments", deepest < THEIR_MAX_DEPTH,
          "consistent with (3); not evidence for it")

    print(f"\n{'NESTED, not crossed — my bound is the weaker one.' if not fails else f'FAILURES: {fails}'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
