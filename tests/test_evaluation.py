"""Unit tests for report parsing and trace consistency (no simulator needed)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from compare_switching import compare_pair  # noqa: E402
from measure_synth import synthesize  # noqa: E402


class AnalysisTests(unittest.TestCase):
    @staticmethod
    def write_trace_pair(folder):
        a = [[1, 0], [0, 1]]
        b = [[1, 0], [0, 1]]
        expected = [[1, 0], [0, 1]]
        # A tiny hand-built trace fixture tests report validation ONLY.
        # It does not assert that the RTL produces these signals.
        for tag, gate, flips in (("sparse", False, 20), ("gated", True, 10)):
            c = [[0, 0], [0, 0]]
            cycles = []
            for t in range(4):
                cells = []
                for i in range(2):
                    row = []
                    for j in range(2):
                        k = t - i - j
                        active = 0 <= k < 2
                        av = a[i][k] if active else None
                        bv = b[k][j] if active else None
                        product = av * bv if active else None
                        if active:
                            c[i][j] += product
                        row.append({"a": av, "b": bv, "active": active,
                                    "product": product, "acc": c[i][j],
                                    "gated": bool(gate and active and product == 0)})
                    cells.append(row)
                cycles.append({
                    "t": t, "c": [row[:] for row in c], "cells": cells,
                    "active_count": sum(x["active"] for r in cells for x in r),
                    "gated_count": sum(x["gated"] for r in cells for x in r),
                    "operand_bit_flips": flips if t == 0 else 0,
                })
            data = {
                "a": a, "b": b, "expected": expected, "cycles": cycles,
                "meta": {"n": 2, "cycles": 4, "zero_gate": gate,
                         "target_zero_percent": 50, "input_zero_percent": 50,
                         "trace_source": "RTL-observed fixture, not a simulator run",
                         "switching_method": "RTL-observed fixture, not a simulator run",
                         "operand_bit_flips": flips},
            }
            (folder / f"rtl_trace_n2_{tag}50.json").write_text(
                json.dumps(data), encoding="utf-8")

    def test_pair_comparison_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.write_trace_pair(folder)
            result = compare_pair(2, 50, folder)
            self.assertEqual(result["compute_cycles"], 4)
            self.assertEqual(result["scheduled_macs"], 8)
            self.assertEqual(result["zero_products"], result["isolated_zero_slots"])
            self.assertEqual(result["transition_reduction_percent"], 50.0)

    def test_missing_trace_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Missing RTL trace"):
                compare_pair(2, 50, Path(tmp))

    def test_mismatched_matrices_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.write_trace_pair(folder)
            path = folder / "rtl_trace_n2_gated50.json"
            trace = json.loads(path.read_text())
            trace["a"][0][0] = 3
            path.write_text(json.dumps(trace))
            with self.assertRaisesRegex(ValueError, "Different a"):
                compare_pair(2, 50, folder)

    def test_generic_cell_stat_parser(self):
        output = """=== paramod\\systolic_array ===

   Number of cells: 18
     $_AND_     8
     $_DFF_PN0_ 4
     $_XOR_     5
     $scopeinfo 1

Warnings: 0 unique messages
"""
        class Result:
            returncode = 0
            stdout = output
            stderr = ""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("measure_synth.subprocess.run", return_value=Result()):
                counts = synthesize(2, 0, Path(tmp))
            self.assertEqual(counts["generic_cells"], 17)
            self.assertEqual(counts["sequential_cells"], 4)


if __name__ == "__main__":
    unittest.main()
