"""Reproducible generic-cell comparison for conventional and zero-gated RTL.

Run from the repository (or elsewhere):
    python tools/measure_synth.py --sizes 2 3 4 8

Yosys 0.52 / synth -noabc produces technology-independent cells. These are
NOT mapped area, delay, clock frequency, energy, or physical power estimates.
Raw logs and generic_cells.csv are written under build/reports/ (git-ignored).
"""

import argparse
import csv
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CELL_RE = re.compile(r"^\s+(\S+)\s+(\d+)\s*$", re.MULTILINE)


def synthesize(n, gate, reports):
    # chparam followed by -auto-top is deliberate: parameterized elaboration
    # renames the top module in Yosys 0.52.
    commands = (
        "read_verilog -sv rtl/pe.sv rtl/systolic_array.sv; "
        f"chparam -set N {n} -set ZERO_GATE {gate} systolic_array; "
        "hierarchy -check -auto-top; "
        "synth -auto-top -flatten -noabc; stat"
    )
    result = subprocess.run(
        ["yosys", "-Q", "-p", commands], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    log = reports / f"generic_n{n}_gate{gate}.log"
    log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Yosys failed for N={n}, ZERO_GATE={gate}: {log}")

    # The final 'stat' comes after synth's internal statistics. Parse only
    # the last final-module block to avoid double counting intermediary runs.
    blocks = re.findall(r"(?m)^=== .*? ===\s*\n(.*?)(?=^=== |^Warnings:|\Z)",
                        result.stdout, flags=re.MULTILINE | re.DOTALL)
    if not blocks:
        raise RuntimeError(f"Could not locate the final stats block in {log}")
    block = blocks[-1]
    m = re.search(r"Number of cells:\s*(\d+)", block)
    if not m:
        raise RuntimeError(f"No cell total in final stats block: {log}")
    cells = {name: int(count) for name, count in CELL_RE.findall(block)
             if name.startswith("$_") or name == "$scopeinfo"}
    total = int(m.group(1))
    metadata = cells.get("$scopeinfo", 0)
    functional = total - metadata
    if sum(cells.values()) != total:
        raise RuntimeError(f"Unexpected Yosys cell types/counts in {log}")
    sequential = sum(count for kind, count in cells.items()
                     if kind.startswith(("$_DFF", "$_SDFF")))
    return {
        "n": n, "zero_gate": gate,
        "generic_cells": functional,
        "sequential_cells": sequential,
        "combinational_cells": functional - sequential,
        "metadata_cells": metadata,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[2, 3, 4, 8])
    args = parser.parse_args()
    if any(n < 1 for n in args.sizes):
        parser.error("Array sizes must be positive")

    reports = ROOT / "build" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for n in dict.fromkeys(args.sizes):
            for gate in (0, 1):
                print(f"Synthesizing {n}x{n}, ZERO_GATE={gate}...", flush=True)
                rows.append(synthesize(n, gate, reports))
    except FileNotFoundError:
        parser.exit(1, "Yosys not found. Install yosys in Ubuntu first.\n")
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")

    output = reports / "generic_cells.csv"
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nN    Conventional    Zero-gated     Delta      Overhead")
    for n in dict.fromkeys(args.sizes):
        base, gated = [r for r in rows if r["n"] == n]
        delta = gated["generic_cells"] - base["generic_cells"]
        overhead = 100 * delta / base["generic_cells"]
        print(f"{n:<4} {base['generic_cells']:>12} {gated['generic_cells']:>13} "
              f"{delta:>+9} {overhead:>+11.2f}%")
    print(f"\nRaw logs and CSV: {output.parent}")
    print("Generic cell counts are not mapped silicon area, timing, or power.")


if __name__ == "__main__":
    main()
