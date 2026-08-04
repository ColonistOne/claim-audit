#!/usr/bin/env python3
"""Controls for diff_v2.py. An all-green checker is a suspect until each of its
checks has been shown to fail for the reason it exists.

Every mutation below is a defect the reveal could plausibly have carried. The
diff must go RED on each. A mutation that stays green means that check is
decoration, and I would have published its pass as evidence.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
FILES = ["corpus-v2.json", "mine_outputs.json", "reti_outputs.json", "reti_certs.json"]


def run(tmp: pathlib.Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(tmp / "diff_v2.py")], capture_output=True, text=True
    )
    return r.returncode, r.stdout + r.stderr


def mutate(label: str, fn, expect_hits: list[str]) -> bool:
    """Apply fn to a scratch copy, run the diff, require it to fail LOUDLY and
    for the named check(s) to be among the failures."""
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        for f in FILES + ["diff_v2.py"]:
            shutil.copy(HERE / f, tmp / f)
        fn(tmp)
        code, out = run(tmp)
        # The hash gate fires first and aborts, which is itself correct
        # behaviour -- but it would mask every downstream check. So mutations
        # that are meant to exercise a downstream check re-pin the hash.
        hit = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
        ok = code != 0 and any(
            any(e in h for e in expect_hits) for h in hit
        )
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
        for h in hit[:3]:
            print(f"          -> {h}")
        if not hit:
            print(f"          -> STAYED GREEN (exit {code}) — this check is decoration")
        return ok


def repin(tmp: pathlib.Path, name: str) -> None:
    """Recompute the commitment for a mutated file, so the hash gate does not
    abort before the check under test can run. Legitimate here and ONLY here:
    in the real diff a hash mismatch must abort."""
    import hashlib
    import importlib.util

    spec = importlib.util.spec_from_file_location("_d", HERE / "diff_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # import-safe: main() is under __main__ guard

    got = hashlib.sha256((tmp / name).read_bytes()).hexdigest()
    src = (tmp / "diff_v2.py").read_text()
    (tmp / "diff_v2.py").write_text(src.replace(mod.PINNED[name], got))


def edit(tmp: pathlib.Path, name: str, fn) -> None:
    o = json.loads((tmp / name).read_text())
    fn(o)
    (tmp / name).write_text(json.dumps(o))
    repin(tmp, name)


results = []
print("controls for diff_v2 — each mutation MUST turn the diff red\n")

# 1. The hash gate itself. No re-pin: a byte changed after commitment must abort.
results.append(
    mutate(
        "a single byte changed in their outputs aborts on the commitment",
        lambda t: (t / "reti_outputs.json").write_bytes(
            (t / "reti_outputs.json").read_bytes().replace(b'"seed": 20260803', b'"seed": 20260804')
        ),
        ["reti_outputs.json"],
    )
)

# 2. A real port disagreement on the load-bearing (UD) side.
results.append(
    mutate(
        "one flipped UD verdict in their php port is caught as a disagreement",
        lambda t: edit(
            t,
            "reti_outputs.json",
            lambda o: o["stratum_b"][0]["php"]["crossproduct"].update(
                {"uniquely_decodable": not o["stratum_b"][0]["php"]["crossproduct"]["uniquely_decodable"]}
            ),
        ),
        ["three-way verdict disagreements"],
    )
)

# 3. A certificate that does not actually certify — the exact failure the
#    concatenation check exists for. Counting 19 would not have seen this.
results.append(
    mutate(
        "a certificate whose parses no longer concatenate to its string",
        lambda t: edit(
            t, "reti_certs.json", lambda o: o["certificates"][0].update({"string": "zzz"})
        ),
        ["certificates verify by concatenation"],
    )
)

# 4. A certificate using a token that is not a declared form of the slot —
#    a parse that verifies arithmetically but not against the corpus.
results.append(
    mutate(
        "a certificate parse using a token absent from the corpus slot forms",
        lambda t: edit(
            t,
            "reti_certs.json",
            lambda o: o["certificates"][0].update(
                {
                    "string": "qq",
                    "parse_a": ["qq"],
                    "parse_b": ["q", "q"],
                }
            ),
        ),
        ["certificates verify by concatenation"],
    )
)

# 5. Certificate coverage: a non-UD claim shipped with no witness at all.
results.append(
    mutate(
        "a non-UD claim with its certificate removed",
        lambda t: edit(t, "reti_certs.json", lambda o: o["certificates"].pop(0)),
        ["certificate set is EXACTLY my non-UD set"],
    )
)

# 6. The join key. Renumbering must NOT move the result — but a genuinely
#    missing slot must. This is the defect that made 15 phantom disagreements.
results.append(
    mutate(
        "a stratum-B row whose slot_key is absent from my half",
        lambda t: edit(
            t, "reti_outputs.json", lambda o: o["stratum_b"][0].update({"slot_key": "dead" * 4})
        ),
        ["slot_keys join"],
    )
)

# 7. Natural-corpus disagreement — the 200 rounds must not be a rubber stamp.
results.append(
    mutate(
        "one flipped UD verdict in the natural corpus",
        lambda t: edit(
            t,
            "reti_outputs.json",
            lambda o: o["natural"][0]["php"]["crossproduct"].update({"uniquely_decodable": False}),
        ),
        ["natural UD disagreements"],
    )
)

# 8. The prefix-pair detector, which is a different field from the verdict.
#    v1's whole finding was that coverage is per-FIELD, not per-run.
results.append(
    mutate(
        "an altered prefix_pairs count on a natural round",
        lambda t: edit(
            t,
            "reti_outputs.json",
            lambda o: o["natural"][0]["php"]["crossproduct"].update(
                {"prefix_pairs": [{"prefix": "x", "of": "xy", "meanings_differ": True}]}
            ),
        ),
        ["prefix-pair count disagreements"],
    )
)

# 9. POSITIVE CONTROL. "Reject everything" would pass all eight mutations
#    above. The unmutated inputs must still come out green, or the mutations
#    prove nothing about the checks and only that the script can fail.
with tempfile.TemporaryDirectory() as d:
    tmp = pathlib.Path(d)
    for f in FILES + ["diff_v2.py"]:
        shutil.copy(HERE / f, tmp / f)
    code, out = run(tmp)
    ok = code == 0 and "all checks green" in out
    print(f"  {'ok  ' if ok else 'FAIL'}  POSITIVE CONTROL: unmutated inputs still pass (exit {code})")
    results.append(ok)

print(f"\n{sum(results)}/{len(results)} controls behaved as required")
raise SystemExit(0 if all(results) else 1)
