import random
import unittest
from sim.model import trace_gemm, gemm, demo_matrices, viewer_workloads, annotate_datapath


class TestCycleModel(unittest.TestCase):
    def test_examples_and_randomized(self):
        rng = random.Random(20261106)
        for n in (1, 2, 3, 4, 8):
            for _ in range(40):
                a = [[rng.randint(-7, 7) for _ in range(n)] for _ in range(n)]
                b = [[rng.randint(-7, 7) for _ in range(n)] for _ in range(n)]
                t = trace_gemm(a, b)
                self.assertEqual(t["cycles"][-1]["c"], gemm(a, b))
                self.assertEqual(t["meta"]["total_mac"], n**3)
                self.assertEqual(t["meta"]["cycles"], 3*n-2)
                self.assertEqual(sum(c["active_count"] for c in t["cycles"]), n**3)

    def test_zero_and_extreme_signed(self):
        for n in (2, 4):
            a = [[-128 if (i+j) % 2 else 127 for j in range(n)] for i in range(n)]
            b = [[0 if (i+j) % 3 else -128 for j in range(n)] for i in range(n)]
            self.assertEqual(trace_gemm(a, b)["cycles"][-1]["c"], gemm(a, b))

    def test_demo_matrix_sizes(self):
        for n in (2, 3, 4, 8):
            a, b = demo_matrices(n)
            self.assertEqual(len(a), n)
            self.assertEqual(len(b), n)
            self.assertEqual(trace_gemm(a, b)["cycles"][-1]["c"], gemm(a, b))

    def test_viewer_sparse_inputs(self):
        for n in (2, 3, 4, 8):
            cases = viewer_workloads(n)
            self.assertEqual(set(cases), {"dense", "sparse25", "sparse50", "sparse75"})
            dense_a, dense_b, _ = cases["dense"]
            previous_zero_count = -1
            for label, (a, b, target) in cases.items():
                # Sparse workloads must be masked variants of the same base pair.
                for base, modified in ((dense_a, a), (dense_b, b)):
                    for base_row, modified_row in zip(base, modified):
                        for original, value in zip(base_row, modified_row):
                            self.assertIn(value, (0, original))
                zero_count = sum(x == 0 for matrix in (a, b) for row in matrix for x in row)
                self.assertGreater(zero_count, previous_zero_count)
                previous_zero_count = zero_count
                self.assertLessEqual(abs(zero_count - 2 * n * n * target / 100), 0.5)
                trace = trace_gemm(a, b)
                self.assertEqual(trace["cycles"][-1]["c"], gemm(a, b))
                self.assertEqual(trace["meta"]["cycles"], 3 * n - 2)
                self.assertEqual(trace["meta"]["total_mac"], n**3)
                zero_mac = sum(
                    cell["active"] and cell["product"] == 0
                    for frame in trace["cycles"]
                    for row in frame["cells"] for cell in row
                )
                self.assertEqual(trace["meta"]["zero_product_macs"], zero_mac)
                if label == "dense":
                    self.assertEqual(zero_mac, 0)

    def test_operand_isolation_prediction(self):
        for n in (2, 3, 4, 8):
            a, b, _ = viewer_workloads(n)['sparse50']
            conventional = annotate_datapath(trace_gemm(a, b), zero_gate=False)
            gated = annotate_datapath(trace_gemm(a, b), zero_gate=True)
            self.assertEqual(conventional['expected'], gated['expected'])
            self.assertEqual(conventional['cycles'][-1]['c'], gated['cycles'][-1]['c'])
            self.assertEqual(len(conventional['cycles']), len(gated['cycles']))
            self.assertEqual(sum(frame['gated_count'] for frame in gated['cycles']),
                             gated['meta']['zero_product_macs'])
            self.assertEqual(sum(frame['gated_count'] for frame in conventional['cycles']), 0)
            self.assertLessEqual(gated['meta']['operand_bit_flips'],
                                 conventional['meta']['operand_bit_flips'])

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            trace_gemm([[256]], [[1]])
        with self.assertRaises(ValueError):
            trace_gemm([[1, 2]], [[1, 2]])


if __name__ == "__main__":
    unittest.main()
