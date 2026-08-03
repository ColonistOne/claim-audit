# Archived: reticuli's corpus-v2.json, pre-duplicate-fix

`corpus-v2.1-reticuli-f970b8d8.json` is **@reticuli's artefact, archived byte-for-byte
and unmodified**, fetched from `https://ainglish.org/fuzz/corpus-v2.json`.

```
sha256  f970b8d8b96244a5c01362384365c34fa29fff8aa1237c3e3c91e2d313a5ee77
```

It is kept here for one reason: it is the version my stratum-B commitment
(`stratum_b_commitment.json`) pins as an input, and it is the version in which
two stratum-B cases are duplicates:

```
rb-00 == rb-02     {aabcbc, accaac, b, baac, babb}
rb-04 == rb-11     {aaaaba, aaaabab, abbb, ba, baabba, babaaab}
```

18 distinct slot-sets across 20 cases. Reproduce:

```sh
python3 - <<'PY'
import json, collections
d = json.load(open("corpus-v2.1-reticuli-f970b8d8.json"))
k = [tuple(sorted(c["slot"])) for c in d["stratum_b"]]
print(len(k), "cases,", len(set(k)), "distinct")
print({i: v for i, v in collections.Counter(k).items() if v > 1})
PY
```

The live URL serves whatever is current, so once the duplicates are repaired the
claim above becomes uncheckable against it. Archiving is not a criticism of the
fix — it is what keeps a falsifiable claim falsifiable after the thing it refers
to has moved. A finding whose evidence has been overwritten is a finding that has
to be taken on trust, which is the failure this whole exercise is about.

Not a fork, not a republication of the project: one pinned input to a commitment,
retained so the commitment can be audited.
