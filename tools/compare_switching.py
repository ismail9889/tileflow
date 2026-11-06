"""Validate and compare sampled multiplier-input switching from RTL traces.

Requires BOTH conventional sparse and zero-gated RTL traces for every size
and zero-density setting. Refuses incomplete, model-only, or mismatched runs.

    python tools/run_rtl.py --sizes 2 3 4 8
    python tools/compare_switching.py --sizes 2 3 4 8

The counts cover sampled pre-clock-edge multiplier-input transitions ONLY.
They are not gate-level switching, dynamic power, energy, or throughput.
"""

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_rtl_trace(path, n, gate):
    if not path.is_file():
        raise ValueError(f"Missing RTL trace: {path}. Run tools/run_rtl.py first.")
    trace = json.loads(path.read_text(encoding="utf-8"))
    meta = trace.get("meta", {})
    if int(meta.get("n", -1)) != n:
        raise ValueError(f"Array dimension mismatch in {path}")
    if meta.get("zero_gate") is not bool(gate):
        raise ValueError(f"ZERO_GATE flag mismatch in {path}")
    if "RTL-observed" not in str(meta.get("trace_source", "")):
        raise ValueError(f"Not an RTL-observed trace: {path}")
    if "RTL-observed" not in str(meta.get("switching_method", "")):
        raise ValueError(f"Switching was not measured from RTL taps: {path}")
    cycles = trace.get("cycles", [])
    if len(cycles) != 3*n-2 or meta.get("cycles") != 3*n-2:
        raise ValueError(f"Wrong or incomplete cycle count in {path}")
    if cycles[-1].get("c") != trace.get("expected"):
        raise ValueError(f"Last cycle does not match matrix product in {path}")
    transition_total = 0
    for index, frame in enumerate(cycles):
        if frame.get("t") != index:
            raise ValueError(f"Nonsequential cycle indices in {path}")
        flips = frame.get("operand_bit_flips")
        if type(flips) is not int or flips < 0:
            raise ValueError(f"Missing/invalid transitions at cycle {index} in {path}")
        transition_total += flips
    if transition_total != meta.get("operand_bit_flips"):
        raise ValueError(f"Transition sum mismatch in {path}")
    return trace


def compare_pair(n, pct, artifacts):
    names = [f"rtl_trace_n{n}_{tag}{pct}.json" for tag in ("sparse", "gated")]
    sparse = load_rtl_trace(artifacts / names[0], n, gate=False)
    gated = load_rtl_trace(artifacts / names[1], n, gate=True)
    for name in ("a", "b", "expected"):
        if sparse[name] != gated[name]:
            raise ValueError(f"Different {name} for sparse and gated N={n}, density={pct}%")
    if sparse["meta"].get("target_zero_percent") != pct or gated["meta"].get("target_zero_percent") != pct:
        raise ValueError(f"Wrong zero-density configuration for N={n}, {pct}%")
    if sparse["meta"].get("input_zero_percent") != gated["meta"].get("input_zero_percent"):
        raise ValueError(f"Different realized zero density for N={n}, {pct}%")
    zero_products = 0
    isolated = 0
    scheduled = 0
    for cycle, (s, g) in enumerate(zip(sparse["cycles"], gated["cycles"])):
        if s["c"] != g["c"] or s["active_count"] != g["active_count"]:
            raise ValueError(f"Different outputs/schedule at N={n}, {pct}%, cycle={cycle}")
        for row_s, row_g in zip(s["cells"], g["cells"]):
            for cs, cg in zip(row_s, row_g):
                for field in ("a", "b", "active", "product", "acc"):
                    if cs[field] != cg[field]:
                        raise ValueError(f"Different PE values at N={n}, {pct}%, cycle={cycle}")
                z = bool(cs["active"] and cs["product"] == 0)
                zero_products += z
                scheduled += bool(cs["active"])
                isolated += bool(cg.get("gated", False))
                if cs.get("gated", False) or bool(cg.get("gated", False)) != z:
                    raise ValueError(f"Gating mismatch at N={n}, {pct}%, cycle={cycle}")
        if g.get("gated_count") != sum(bool(c["gated"]) for r in g["cells"] for c in r):
            raise ValueError(f"gated_count mismatch at N={n}, {pct}%, cycle={cycle}")
    if scheduled != n**3 or zero_products != isolated:
        raise ValueError(f"Incorrect operation totals N={n}, {pct}%")
    baseline = sparse["meta"]["operand_bit_flips"]
    optimized = gated["meta"]["operand_bit_flips"]
    return {
        "n": n, "target_zero_percent": pct,
        "actual_zero_percent": round(sparse["meta"]["input_zero_percent"], 2),
        "compute_cycles": 3*n-2, "scheduled_macs": scheduled,
        "zero_products": zero_products, "isolated_zero_slots": isolated,
        "sparse_input_transitions": baseline,
        "gated_input_transitions": optimized,
        "transition_reduction_percent": (
            round(100 * (baseline - optimized) / baseline, 2) if baseline else "N/A"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[2, 3, 4, 8])
    parser.add_argument("--zero-percent", type=int, nargs="+", default=[25, 50, 75])
    args = parser.parse_args()
    if any(n < 1 for n in args.sizes):
        parser.error("Array sizes must be positive")
    if any(p not in (25, 50, 75) for p in args.zero_percent):
        parser.error("Currently available trace densities: 25, 50, 75")
    artifacts = ROOT / "artifacts"
    try:
        rows = [compare_pair(n, pct, artifacts)
                for n in dict.fromkeys(args.sizes)
                for pct in dict.fromkeys(args.zero_percent)]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        parser.exit(1, f"Cannot compare traces: {error}\n")
    output_dir = ROOT / "build" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "switching_comparison.csv"
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print("N   Target zeros    Sparse flips    Gated flips   Reduction")
    for row in rows:
        print(f"{row['n']:<3} {row['target_zero_percent']:>8}%  "
              f"{row['sparse_input_transitions']:>13}  "
              f"{row['gated_input_transitions']:>12}  "
              f"{str(row['transition_reduction_percent']):>8}%")
    print(f"\nValidated identical matrices, MAC schedules, outputs and isolation: {len(rows)} comparisons")
    print(f"CSV: {output}")
    print("These are sampled multiplier-input transitions, not power or energy.")


if __name__ == "__main__":
    main()
