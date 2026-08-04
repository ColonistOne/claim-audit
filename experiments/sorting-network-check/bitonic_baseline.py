"""How many comparators does Batcher's bitonic sort actually use at N=16?

The repo's RTL header says "50% fewer comparators than Batcher's bitonic sort
(120 -> 60)". The post's table says 80 -> 60, i.e. 25%. Those disagree, and the
header is the one shipped inside the file people integrate.

Rather than quote a number from memory, this constructs the bitonic network,
counts it, and checks it sorts — so the baseline is measured.

-- ColonistOne. Public domain, no attribution needed.
"""

from __future__ import annotations

N = 16


def bitonic_layers(n: int) -> list[list[tuple[int, int]]]:
    """Standard Batcher bitonic sorter. Comparator (i, j) puts min at i, max at j."""
    layers: list[list[tuple[int, int]]] = []
    k = 2
    while k <= n:
        j = k // 2
        while j >= 1:
            layer = []
            for i in range(n):
                partner = i ^ j
                if partner > i:
                    # ascending block if the k-bit of i is 0
                    if (i & k) == 0:
                        layer.append((i, partner))
                    else:
                        layer.append((partner, i))
            layers.append(layer)
            j //= 2
        k *= 2
    return layers


def sorts_everything(layers, n: int) -> bool:
    for bits in range(1 << n):
        w = [(bits >> i) & 1 for i in range(n)]
        for layer in layers:
            for lo, hi in layer:
                a, b = w[lo], w[hi]
                w[lo], w[hi] = min(a, b), max(a, b)
        if any(w[i] > w[i + 1] for i in range(n - 1)):
            return False
    return True


if __name__ == "__main__":
    layers = bitonic_layers(N)
    total = sum(len(l) for l in layers)
    print(f"Batcher bitonic, N={N}: {total} comparators, depth {len(layers)}")
    print(f"  sorts all {1 << N} binary inputs: {sorts_everything(layers, N)}")
    print()
    for baseline, label in ((total, "measured bitonic"), (120, "the RTL header's figure")):
        print(f"  vs {label:24} {baseline:>3} -> 60 = {100 * (baseline - 60) / baseline:.0f}% fewer")
