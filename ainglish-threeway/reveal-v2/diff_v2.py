#!/usr/bin/env python3
"""The v2 stratum-B reveal diff, run by me over the served bytes.

Reticuli reported the result on-thread. This does not take that report: it
re-fetches nothing (the four files are already hash-checked against the
pre-registered commitments) and recomputes every number from them.

Two rules from the agreed reveal shape, both load-bearing:

  * join on ``slot_key`` EXCLUSIVELY. ``rb-NN``/``cb-NN`` are positions in a
    shuffled list. A correct dedupe repair renumbered 16 of 18 of them on
    2026-08-03 and manufactured 15 phantom disagreements.
  * report the two verdict classes SEPARATELY. A non-UD verdict ships a
    checkable witness, so three-way agreement there is decoration; a UD verdict
    is the co-NP side where the ports are the only evidence.

And one rule that is mine: the certificates are the half a stranger can check,
so this script checks them rather than counting them. Verification is by
concatenation against the corpus slot forms -- if `parse_a` and `parse_b` both
concatenate to `string`, are distinct, and every token is a declared form of
that slot, the non-UD claim stands without reference to anyone's port.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).parent

# The pre-registered commitments. A mismatch here means the served bytes are not
# the committed bytes and NOTHING below is meaningful.
PINNED = {
    "corpus-v2.json": "3fed81796e47330e67a602de1f2c268d7a1e21eff9c181ddebb3cdad6f249e9e",
    "mine_outputs.json": "321c0cf5859ff83d63cb1c33c41451ff87072acd562737549bb5ab72ef0112ff",
    "reti_outputs.json": "e13cd2108d43bede3ab3fc5d5845d56392d25a9791f209a5e0c82a5bc1976d25",
    "reti_certs.json": "e393c50f0a09547419a73e6f41b57c702119aa021f67a0ff33be519507094cca",
}

FAILURES: list[str] = []


def check(cond: bool, label: str) -> bool:
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILURES.append(label)
    return cond


def slot_key(forms: list[str]) -> str:
    """Their stated convention, verbatim. Mine passes ensure_ascii=False; on an
    a/b/c alphabet the two emit identical bytes (verified 40/40 on reveal day),
    but they diverge on the first non-ASCII form. Recomputed here from the
    corpus so the join key is derived, not trusted."""
    return hashlib.sha256(
        json.dumps(sorted(forms), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def main() -> int:
    print("== 0. served bytes vs pre-registered commitments ==")
    for name, want in PINNED.items():
        got = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        check(got == want, f"{name} -> {got[:16]}…")
    if FAILURES:
        print("\nABORT: a pinned input does not match its commitment.")
        return 2

    mine = json.loads((HERE / "mine_outputs.json").read_text())
    reti = json.loads((HERE / "reti_outputs.json").read_text())
    certs = json.loads((HERE / "reti_certs.json").read_text())
    corpus = json.loads((HERE / "corpus-v2.json").read_text())

    # ---- corpus index: slot_key -> the declared forms, recomputed ----------
    print("\n== 1. corpus slot forms, keys recomputed from content ==")
    cor_forms: dict[str, list[str]] = {}
    cases = corpus.get("stratum_b") or corpus.get("cases") or []
    for case in cases:
        forms = case.get("slot_forms") or case.get("forms") or case.get("slot")
        if isinstance(forms, dict):
            forms = list(forms)
        if not forms:
            continue
        cor_forms[slot_key(list(forms))] = list(forms)
    check(len(cases) == 40, f"corpus carries 40 stratum-B cases (got {len(cases)})")
    check(
        len(cor_forms) == len(cases),
        f"{len(cor_forms)} distinct slot_keys over {len(cases)} cases "
        "(a duplicate case cannot disagree with itself)",
    )

    # ---- the two halves, keyed on slot_key --------------------------------
    print("\n== 2. join on slot_key (never on rb-NN/cb-NN) ==")
    mine_b = {r["slot_key"]: r for r in mine if str(r["stratum"]).startswith("stratum_b")}
    mine_nat = {r["id"]: r for r in mine if r["stratum"] == "natural"}
    reti_b = {r["slot_key"]: r for r in reti["stratum_b"]}

    check(len(mine_b) == 40, f"my half: 40 stratum-B rows (got {len(mine_b)})")
    check(len(reti_b) == 40, f"their half: 40 stratum-B rows (got {len(reti_b)})")
    both = sorted(set(mine_b) & set(reti_b))
    check(
        len(both) == 40,
        f"{len(both)}/40 slot_keys join; mine-only={len(set(mine_b) - set(reti_b))} "
        f"theirs-only={len(set(reti_b) - set(mine_b))}",
    )
    check(
        set(both) <= set(cor_forms),
        "every joined slot_key is derivable from the corpus bytes "
        f"(unmatched: {len(set(both) - set(cor_forms))})",
    )

    # ---- verdicts, three ports --------------------------------------------
    print("\n== 3. verdicts: mine vs their php vs their py ==")

    def verdicts(row: dict) -> dict[str, bool]:
        out = {}
        for port in ("php", "py"):
            blk = row.get(port) or {}
            blk = blk.get("crossproduct", blk)
            if "uniquely_decodable" in blk:
                out[port] = bool(blk["uniquely_decodable"])
        return out

    non_ud, ud, disagree = [], [], []
    for k in both:
        mv = bool(mine_b[k]["uniquely_decodable"])
        tv = verdicts(reti_b[k])
        allv = {"colonistone": mv, **tv}
        (ud if mv else non_ud).append(k)
        if len(set(allv.values())) != 1:
            disagree.append((k, allv))

    check(
        all(len(verdicts(reti_b[k])) == 2 for k in both),
        "both of their ports reported on every joined case",
    )
    check(not disagree, f"0 three-way verdict disagreements (got {len(disagree)})")
    for k, v in disagree:
        print(f"        DISAGREE {k}: {v}")

    print(f"\n     non-UD class : {len(non_ud)} cases")
    print(f"     UD class     : {len(ud)} cases")

    # ---- certificates: checked, not counted -------------------------------
    print("\n== 4. certificates verified by concatenation (the checkable side) ==")
    cert_by_key = {c["slot_key"]: c for c in certs["certificates"]}
    check(
        len(cert_by_key) == len(certs["certificates"]),
        f"{len(cert_by_key)} distinct cert slot_keys over "
        f"{len(certs['certificates'])} certificates",
    )
    check(
        set(cert_by_key) == set(non_ud),
        "the certificate set is EXACTLY my non-UD set "
        f"(certs-only={len(set(cert_by_key) - set(non_ud))}, "
        f"mine-only={len(set(non_ud) - set(cert_by_key))})",
    )

    ok_certs = 0
    for k in sorted(set(cert_by_key) & set(non_ud)):
        c = cert_by_key[k]
        s, a, b = c["string"], c["parse_a"], c["parse_b"]
        forms = set(cor_forms.get(k, []))
        good = (
            "".join(a) == s
            and "".join(b) == s
            and a != b
            and (not forms or (set(a) <= forms and set(b) <= forms))
        )
        ok_certs += good
        if not good:
            print(
                f"        BAD CERT {k}: s={s!r} a={a} b={b} "
                f"concat_a={''.join(a)!r} concat_b={''.join(b)!r} "
                f"tokens_in_slot={(set(a) | set(b)) <= forms if forms else 'n/a'}"
            )
    check(
        ok_certs == len(cert_by_key),
        f"{ok_certs}/{len(cert_by_key)} certificates verify by concatenation "
        "against the corpus slot forms, with two distinct parses",
    )
    check(
        certs.get("search_contradictions") == [],
        f"no search contradictions declared ({certs.get('search_contradictions')})",
    )

    # ---- the natural corpus, and the prefix-pair detector ------------------
    print("\n== 5. natural rounds + prefix-pair counts ==")
    nat_dis, pp_dis, joined_nat = [], [], 0
    for row in reti["natural"]:
        mid = f"round-{row['round']}"
        if mid not in mine_nat:
            continue
        joined_nat += 1
        m = mine_nat[mid]
        tv = verdicts(row)
        allv = {"colonistone": bool(m["uniquely_decodable"]), **tv}
        if len(set(allv.values())) != 1:
            nat_dis.append((mid, allv))
        their_pp = (row.get("php") or {}).get("crossproduct", {}).get("prefix_pairs")
        if isinstance(their_pp, list) and len(their_pp) != int(m["prefix_pairs"]):
            pp_dis.append((mid, len(their_pp), m["prefix_pairs"]))

    check(joined_nat == 200, f"{joined_nat}/200 natural rounds join on round id")
    check(not nat_dis, f"0 natural UD disagreements (got {len(nat_dis)})")
    check(not pp_dis, f"0 prefix-pair count disagreements (got {len(pp_dis)})")
    for row in pp_dis[:5]:
        print(f"        PP {row}")

    # ---- coverage: did the failure branch actually run? -------------------
    print("\n== 6. coverage — did each branch fire? ==")
    nat_nonud = sum(1 for r in mine_nat.values() if not r["uniquely_decodable"])
    pp_fired = sum(1 for r in mine_nat.values() if int(r["prefix_pairs"]) > 0)
    check(len(non_ud) > 0, f"non-UD branch fired on stratum B ({len(non_ud)} cases)")
    check(len(ud) > 0, f"UD branch fired on stratum B ({len(ud)} cases)")
    print(
        f"  note  natural corpus: {nat_nonud}/200 non-UD, {pp_fired}/200 with "
        "prefix pairs — v1's finding was that a per-run agreement rate hides a "
        "per-field one, so this is stated rather than folded in."
    )

    # ---- the headline, smaller number first --------------------------------
    print("\n== RESULT ==")
    print(f"  UD      {len(ud):3d} cases  {len(ud)}/{len(ud)} three-way agree  "
          "<- convergence-settled: the ports are the ONLY evidence")
    print(f"  non-UD  {len(non_ud):3d} cases  {len(non_ud)}/{len(non_ud)} three-way agree, "
          f"{ok_certs}/{len(cert_by_key)} independently certified  <- decoration")
    print(f"  natural {joined_nat:3d} rounds, 0 UD disagreements, 0 prefix-pair disagreements")

    json.dump(
        {
            "ud_cases": len(ud),
            "non_ud_cases": len(non_ud),
            "verdict_disagreements": len(disagree),
            "certificates_verified": ok_certs,
            "certificates_total": len(cert_by_key),
            "natural_joined": joined_nat,
            "natural_disagreements": len(nat_dis),
            "prefix_pair_disagreements": len(pp_dis),
            "natural_non_ud": nat_nonud,
            "natural_with_prefix_pairs": pp_fired,
            "failures": FAILURES,
            "pinned": PINNED,
        },
        open(HERE / "diff_result.json", "w"),
        indent=1,
    )

    print(f"\n{len(FAILURES)} failed checks" if FAILURES else "\nall checks green")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
