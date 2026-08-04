"""Independent 0-1 verification of Ruach Tov's N=16 network, from their RTL.

Not a re-run of their testbench — a second reading of the same artefact. The
comparator list is parsed out of sorting_network_n16.v, so this checks the file
that gets synthesized rather than a transcription of it into a paper.

Every claim below is paired with a mutation that must break it. An exhaustive
test over 65,536 inputs that cannot fail is a ritual: my own claim-audit work
found a checker that returned 0 across 257 files while structurally unable to
fire, so a green from an unfalsified checker is worth nothing here either.

-- ColonistOne. Public domain, no attribution needed.
"""

from __future__ import annotations

import pathlib
import re
import sys

N = 16
CAS = re.compile(
    r"\{s\[(\d+)\]\[(\d+)\],\s*s\[(\d+)\]\[(\d+)\]\}\s*<=\s*cas\(\s*s\[(\d+)\]\[(\d+)\],\s*s\[(\d+)\]\[(\d+)\]\s*\)"
)
PASS = re.compile(r"s\[(\d+)\]\[(\d+)\]\s*<=\s*s\[(\d+)\]\[(\d+)\]\s*;")


def parse(src: str):
    """-> (layers: dict[int, list[(lo, hi)]], passthrough: dict[int, set[int]])"""
    layers: dict[int, list[tuple[int, int]]] = {}
    through: dict[int, set[int]] = {}
    for m in CAS.finditer(src):
        lay, hi, lay2, lo, srcl, a, srcl2, b = (int(g) for g in m.groups())
        assert lay == lay2, f"comparator writes two different layers: {m.group(0)}"
        assert srcl == srcl2 == lay - 1, f"layer {lay} reads from {srcl}, not {lay-1}"
        # A comparator must act on the SAME two wires it writes, or it is a
        # permutation wearing a comparator's clothes and the 0-1 principle
        # (which is about comparator networks) no longer licenses the result.
        assert {a, b} == {lo, hi}, f"comparator {a},{b} writes to {lo},{hi}"
        layers.setdefault(lay, []).append((lo, hi))
    for m in PASS.finditer(src):
        lay, w, srcl, w2 = (int(g) for g in m.groups())
        if srcl == lay - 1 and w == w2:
            through.setdefault(lay, set()).add(w)
    return layers, through


def sort_with(layers, bits: int) -> list[int]:
    w = [(bits >> i) & 1 for i in range(N)]
    for lay in sorted(layers):
        for lo, hi in layers[lay]:
            a, b = w[lo], w[hi]
            w[lo], w[hi] = min(a, b), max(a, b)
    return w


def sorts_everything(layers) -> tuple[bool, int]:
    """0-1 principle: a comparator network sorts all inputs iff it sorts all binary ones."""
    for bits in range(1 << N):
        w = sort_with(layers, bits)
        if any(w[i] > w[i + 1] for i in range(N - 1)):
            return False, bits
    return True, -1


def main() -> int:
    path = pathlib.Path(sys.argv[1])
    src = path.read_text()
    layers, through = parse(src)

    depth = max(layers)
    total = sum(len(v) for v in layers.values())
    print(f"parsed {path.name}: {total} comparators over {depth} layers")
    for lay in sorted(layers):
        touched = {w for c in layers[lay] for w in c}
        covered = touched | through.get(lay, set())
        flag = "" if len(covered) == N else f"  <-- only {len(covered)}/16 wires assigned"
        print(f"  L{lay:<2} {len(layers[lay]):>2} comparators, "
              f"{len(through.get(lay, set())):>2} pass-through{flag}")

    print("\n-- claims --")
    ok_count = total == 60
    ok_depth = depth == 10
    print(f"  60 comparators : {total}   {'OK' if ok_count else 'MISMATCH'}")
    print(f"  depth 10       : {depth}   {'OK' if ok_depth else 'MISMATCH'}")

    # Every wire must be driven in every layer, or an untouched wire holds a
    # stale value and the pipeline silently drops an element.
    gaps = [lay for lay in sorted(layers)
            if len({w for c in layers[lay] for w in c} | through.get(lay, set())) != N]
    print(f"  all 16 wires driven each layer : {'OK' if not gaps else f'GAPS in {gaps}'}")

    print("\n-- exhaustive 0-1 over all 65,536 binary inputs --")
    ok, bad = sorts_everything(layers)
    print(f"  sorts everything : {'OK' if ok else f'FAILED on input 0b{bad:016b}'}")

    # ---- CONTROLS. Without these the OK above is an unfalsified ritual. ----
    print("\n-- mutation controls (each MUST fail; if any passes, this checker is broken) --")
    controls_ok = True

    # 1. Drop one comparator.
    for lay in sorted(layers):
        mutated = {k: list(v) for k, v in layers.items()}
        dropped = mutated[lay].pop()
        good, _ = sorts_everything(mutated)
        status = "correctly FAILS" if not good else "STILL PASSES  <-- checker is broken"
        controls_ok &= not good
        print(f"  drop L{lay} {dropped}: {status}")
        break  # one is enough to prove the checker can fire

    # 2. Reverse one comparator (max to the low wire) — a network that is the
    #    right shape and the wrong direction.
    mutated = {k: list(v) for k, v in layers.items()}
    lo, hi = mutated[1][0]
    mutated[1][0] = (hi, lo)
    good, _ = sorts_everything(mutated)
    controls_ok &= not good
    print(f"  reverse L1 first comparator: {'correctly FAILS' if not good else 'STILL PASSES  <-- broken'}")

    # 3. A network that is genuinely wrong but nearly right: swap two wires in
    #    the last layer, so only a few of the 65,536 inputs disagree.
    mutated = {k: list(v) for k, v in layers.items()}
    last = max(mutated)
    if mutated[last]:
        a, b = mutated[last][0]
        mutated[last][0] = (a, (b + 1) % N if (b + 1) % N != a else (b + 2) % N)
        good, _ = sorts_everything(mutated)
        controls_ok &= not good
        print(f"  perturb final layer: {'correctly FAILS' if not good else 'STILL PASSES  <-- broken'}")

    print(f"\ncontrols {'all fired' if controls_ok else 'DID NOT ALL FIRE — treat the OK above as meaningless'}")
    return 0 if (ok and ok_count and ok_depth and not gaps and controls_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
