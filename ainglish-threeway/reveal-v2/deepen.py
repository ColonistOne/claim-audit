#!/usr/bin/env python3
"""Re-run the 10 budget-capped UD slots with a much larger node ceiling.

`bound_exhaustion.py` shows my published null was, on 10 of 21 subject slots,
a null under a RESOURCE ceiling rather than under the declared 24-character
domain. That immediately raises the only question that matters: was the ceiling
hiding a witness?

If any of the 10 refutes at a higher budget, my published `0/21 refuted` is
wrong and needs a public retraction. If none does, the null survives and the
declared bound simply needs correcting to what was achieved.

The control is the same one the original uses and it is not optional: the 19
known ambiguities must still be found, or a null here measures the search.
"""
import json, pathlib, time
from collections import deque
from ud_falsifier import MAX_LEN, slot_key

HERE = pathlib.Path(__file__).parent
BIG = 8_000_000

def find(forms, budget):
    forms = [f for f in forms if f]
    seen = {"": ()}
    q = deque([""]); nodes = 0
    while q and nodes < budget:
        s = q.popleft(); nodes += 1
        for f in forms:
            t = s + f
            if len(t) > MAX_LEN: continue
            parse = seen[s] + (f,)
            if t in seen:
                if seen[t] != parse: return (list(seen[t]), list(parse)), nodes, "found"
                continue
            seen[t] = parse; q.append(t)
    return None, nodes, ("node_budget" if q else "exhausted")

corpus = json.loads((HERE/"corpus-v2.json").read_text())
mine = json.loads((HERE/"mine_outputs.json").read_text())
forms_by_key = {}
for case in corpus.get("stratum_b") or corpus.get("cases") or []:
    f = case.get("slot_forms") or case.get("forms") or case.get("slot")
    if isinstance(f, dict): f = list(f)
    if f: forms_by_key[slot_key(list(f))] = list(f)
non_ud = [r["slot_key"] for r in mine if str(r["stratum"]).startswith("stratum_b") and not r["uniquely_decodable"]]
capped = [r["slot_key"] for r in json.loads((HERE/"bound_exhaustion.json").read_text())["rows"]
          if r["terminated"] == "node_budget"]

print(f"CONTROL: {len(non_ud)} known ambiguities at budget {BIG}")
ok = sum(1 for k in non_ud if find(forms_by_key[k], BIG)[0] is not None)
print(f"  {ok}/{len(non_ud)} found")
assert ok == len(non_ud), "control failed — a null below would measure the search"

print(f"\nSUBJECT: the {len(capped)} budget-capped UD slots at budget {BIG}")
out = []
for k in sorted(capped):
    t0 = time.time()
    w, nodes, term = find(forms_by_key[k], BIG)
    out.append({"slot_key": k, "refuted": w is not None, "nodes": nodes, "terminated": term})
    flag = "REFUTED" if w else ("exhausted" if term == "exhausted" else "still capped")
    print(f"  {k}  {flag:14} nodes={nodes:>9}  {time.time()-t0:.1f}s" + (f"  {w}" if w else ""))

ref = [r for r in out if r["refuted"]]
ex  = [r for r in out if r["terminated"] == "exhausted"]
print(f"\n{len(ref)} refuted, {len(ex)} now fully exhausted, {len(out)-len(ref)-len(ex)} still capped at {BIG}")
(HERE/"deepen.json").write_text(json.dumps({"budget": BIG, "rows": out}, indent=1))
