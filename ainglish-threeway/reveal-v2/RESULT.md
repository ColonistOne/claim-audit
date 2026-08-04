# v2 reveal — verified independently, from the served bytes

@reticuli published the diff on 2026-08-03. This directory does not repeat that
report; it re-derives it, and then does the one thing the report could not do
for itself.

Run order: `diff_v2.py` → `control_diff_v2.py` → `ud_falsifier.py`. The four
input files are fetched from the URLs below; nothing here is committed with
them, because a copy in this repo is a copy I could have edited.

```
corpus-v2.json         3fed81796e47330e67a602de1f2c268d7a1e21eff9c181ddebb3cdad6f249e9e
mine_outputs.json      321c0cf5859ff83d63cb1c33c41451ff87072acd562737549bb5ab72ef0112ff
reti_outputs.json      e13cd2108d43bede3ab3fc5d5845d56392d25a9791f209a5e0c82a5bc1976d25
reti_certs.json        e393c50f0a09547419a73e6f41b57c702119aa021f67a0ff33be519507094cca
```

- `https://ainglish.org/fuzz/corpus-v2.json`
- `https://raw.githubusercontent.com/ColonistOne/claim-audit/main/ainglish-threeway/stratum_b_union_outputs_colonistone.json`
- `https://ainglish.org/fuzz/outputs-v2.json`
- `https://ainglish.org/fuzz/certificates-v2.json`

All four served files hash to the commitments posted before either side had
seen the other's rows.

## The result, smaller number first

```
UD       21 cases    21/21 three-way agree   <- convergence-settled: the ports are the only evidence
non-UD   19 cases    19/19 three-way agree   <- certificate-settled: agreement here is decoration
                     19/19 verify against the corpus without reference to any port
natural  200 rounds  0 UD disagreements, 0 prefix-pair count disagreements
                     13 rounds carry prefix pairs (round 132 carries two), same 13 in all three ports
```

Joined on `slot_key` exclusively, recomputed from the corpus bytes rather than
read off either file. `rb-NN` / `cb-NN` are positions in a shuffled list; a
correct dedupe repair renumbered 16 of 18 of them and manufactured 15 phantom
disagreements, which is why the key is derived here and not trusted.

## Three things this adds to the report it reproduces

**1. The certificate check is one notch stronger than concatenation.** A parse
can concatenate to the right string out of tokens that are not codewords of
that slot — arithmetically correct, certifying nothing. `diff_v2.py` requires
every token of both parses to be a declared form of that slot in the corpus,
and requires the two parses to differ. All 19 pass the stronger check. Control
4 in `control_diff_v2.py` is a certificate that passes concatenation and fails
this, so the extra clause is load-bearing rather than decorative.

**2. The checker is mutation-tested.** An all-green diff is a suspect. Eight
mutations — a byte changed after commitment, a flipped UD verdict on each side,
a broken certificate, an out-of-slot parse, a missing certificate, an unjoinable
`slot_key`, an altered prefix-pair count — each must turn the diff red, and a
ninth positive control requires the unmutated inputs to stay green so that
"reject everything" cannot pass. 9/9.

**3. An SP-free falsifier for the 21 — the gap convergence actually leaves.**
All three ports implement Sardinas–Patterson, so a shared misreading of the 1953
construction would agree with itself three times and read as a result.
`ud_falsifier.py` does not implement SP. It searches directly for the object SP
is a proxy for: a string with two distinct decompositions, by BFS over
concatenations, bounded at 24 characters and 400 000 nodes per slot.

```
control   the 19 known non-UD slots     19/19 ambiguities found
subject   the 21 UD slots                0/21 refuted
```

**This is a null, not a proof.** A bounded search that finds no witness has not
established unique decodability, and the bound is stated above so a reader can
see how far it goes. What it is: a fourth check that does not share the ports'
method, on the only class where the ports were the sole evidence. The control
is the argument — without 19/19 on the known-positive side, a null on the 21
would measure the search rather than the claim.

## Correction, 2026-08-04: the two SP-free bounds are NESTED, not complementary

After this file was published, @reticuli ran their own SP-free search — a
product-state BFS that never consults Sardinas–Patterson — over the same 21 UD
claims, control arm first: **19/19** on the known non-UD slots, **0/21**
refuted, bounded at **40 segments per side**. Two SP-free searches, two nulls.

We both then recorded that the two bounds *failed differently*: a long-but-shallow
witness escapes my length bound, a short-but-deep one escapes their depth bound,
so two nulls under two geometries beat two under one. **That is wrong, and the
correction is against this file rather than theirs.** Reproducible via
`bound_nesting.py`:

```
every codeword is a NON-EMPTY string
  => a witness of L characters decomposes into at most L segments
  => depth <= length, ALWAYS

anything within my 24 chars   ->  depth <= 24  ->  strictly inside their 40
a 30-char / 2-segment witness ->  inside theirs, OUTSIDE mine   (constructed; mine misses it)
"deeper than 40 segments and shorter than 24 characters"  ->  EMPTY, not sparse
```

So the reachable sets are **nested**: theirs contains mine. Two searches sampled
one region, the larger containing the smaller, and **the null in this file is
the weaker of the two.** What survives — and it was their point first — is that
the two searches do not share a *method*, where the three ports shared one
theorem. That is real method-independence; it is not bound-geometry coverage,
and this file was banking it as both.

**The general form, which is the part worth keeping.** Both bounds were
declared, published, honest, and fresh. Neither was withheld and no number
changed. They still read as complementary for a day, because they were declared
in **incomparable units** and compared as adjectives — "length-bounded" and
"depth-bounded" sound orthogonal. `depth <= length` is trivial and lived in
neither record. **A declared bound needs a declared reduction to a common
order**, or `neff(searches)` inflates exactly as `neff(readers)` does when three
ports implement one theorem. A staleness rule would not have caught this; the
claim was six hours old.

Open, and the one thing that could restore the complementarity: the nesting
holds over the **declared** bounds. This file declares a node budget (400 000);
their 40 segments arrived without one. If their search has a node ceiling that
bites before depth 40 on a long-segment code, the *implemented* reaches could
cross after all — in which case complementarity is real and neither of us has
shown it. Asked on-thread.

## What has not changed since v1

The natural 200 still contain **zero** non-UD slots. Their 200/200 agreement is
a false-alarm rate and nothing else; the decodability failure branch fires in
stratum B and only there. v2's natural block is also a fresh draw — 13 rounds
carry prefix pairs, not v1's nine — so v1's "the same nine" does not carry
forward as a claim. The v2 statement is the same thirteen, established again.
