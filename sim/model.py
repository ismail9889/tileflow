"""Pure-Python, cycle-level reference and trace generator (NOT RTL execution).

The reference model follows the same registered-hop timing as rtl/pe.sv.
A[i,k] enters row i at t=i+k; B[k,j] enters column j at t=j+k.
At PE(i,j), matching operands meet at t=i+j+k.
"""
from __future__ import annotations

import random


def gemm(a, b):
    n = len(a)
    if not n or len(b) != n or any(len(row) != n for row in a + b):
        raise ValueError("The baseline accepts two equally sized square matrices")
    return [[sum(a[i][k] * b[k][j] for k in range(n)) for j in range(n)] for i in range(n)]


def trace_gemm(a, b, *, width=8, acc_width=32):
    n = len(a)
    if n < 1 or len(b) != n or any(len(row) != n for row in a + b):
        raise ValueError("The baseline accepts two equally sized square matrices")
    if acc_width < 2 * width:
        raise ValueError("Accumulator width must be >= 2 * operand width")
    lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
    if any(not (lo <= value <= hi) for row in a + b for value in row):
        raise ValueError("Operand is outside signed input range")
    a_q = [[0] * n for _ in range(n)]
    b_q = [[0] * n for _ in range(n)]
    va_q = [[False] * n for _ in range(n)]
    vb_q = [[False] * n for _ in range(n)]
    c = [[0] * n for _ in range(n)]
    cycles = []
    total_mac = 0
    for t in range(3 * n - 2):
        a_edge = [a[i][t-i] if i <= t < i+n else None for i in range(n)]
        b_edge = [b[t-j][j] if j <= t < j+n else None for j in range(n)]
        next_a, next_b, next_va, next_vb = [], [], [], []
        cells = []
        for i in range(n):
            row_a, row_b, row_va, row_vb = [], [], [], []
            row_cells = []
            for j in range(n):
                aval = a_edge[i] if j == 0 else (a_q[i][j-1] if va_q[i][j-1] else None)
                bval = b_edge[j] if i == 0 else (b_q[i-1][j] if vb_q[i-1][j] else None)
                va, vb = aval is not None, bval is not None
                active = va and vb
                product = aval * bval if active else None
                if active:
                    # Two's-complement wrap matches fixed-width RTL accumulation.
                    mask = (1 << acc_width) - 1
                    updated = (c[i][j] + product) & mask
                    if updated >= (1 << (acc_width - 1)):
                        updated -= (1 << acc_width)
                    c[i][j] = updated
                    total_mac += 1
                row_a.append(aval if va else 0)
                row_b.append(bval if vb else 0)
                row_va.append(va)
                row_vb.append(vb)
                row_cells.append({"a": aval, "b": bval, "active": active,
                                  "product": product, "acc": c[i][j]})
            next_a.append(row_a); next_b.append(row_b)
            next_va.append(row_va); next_vb.append(row_vb)
            cells.append(row_cells)
        a_q, b_q, va_q, vb_q = next_a, next_b, next_va, next_vb
        cycles.append({"t": t, "a_edge": a_edge, "b_edge": b_edge,
                       "cells": cells,
                       "active_count": sum(cell["active"] for row in cells for cell in row),
                       "c": [row[:] for row in c]})
    actual = c
    expected = gemm(a, b)
    # Match fixed-width output if a tiny accumulator is intentionally supplied.
    def wrap(x):
        x &= (1 << acc_width) - 1
        return x - (1 << acc_width) if x >= 1 << (acc_width-1) else x
    expected = [[wrap(x) for x in row] for row in expected]
    if actual != expected:
        raise AssertionError("Cycle-level reference model failed its own GEMM oracle")
    zero_inputs = sum(value == 0 for matrix in (a, b) for row in matrix for value in row)
    zero_products = sum(
        cell["active"] and cell["product"] == 0
        for frame in cycles for row in frame["cells"] for cell in row
    )
    return {"meta": {"n": n, "width": width, "acc_width": acc_width,
                     "input_zero_percent": 100 * zero_inputs / (2 * n * n),
                     "zero_product_macs": zero_products,
                     "cycles": len(cycles), "total_mac": total_mac,
                     "array_mac_utilization": total_mac / (n*n*len(cycles)),
                     "trace_source": "Python reference model (RTL trace pending simulator)"},
            "a": a, "b": b, "expected": expected, "cycles": cycles}


def demo_matrices(n):
    """Small, deterministic operands for the trace viewer (not a benchmark)."""
    if n < 1:
        raise ValueError("Array dimension must be positive")
    a4 = [[2, -1, 3, 0], [1, 4, -2, 2],
          [-3, 1, 2, 1], [2, 0, -1, 3]]
    b4 = [[1, 2, 0, -1], [3, -2, 2, 1],
          [-1, 4, 1, 2], [2, 1, -3, 1]]
    if n <= 4:
        return ([row[:n] for row in a4[:n]],
                [row[:n] for row in b4[:n]])
    a = [[(2 * i + 3 * j + 1) % 9 - 4 for j in range(n)] for i in range(n)]
    b = [[(3 * i - 2 * j + 4) % 11 - 5 for j in range(n)] for i in range(n)]
    return a, b


def viewer_workloads(n):
    """Fixed, reproducible dense and sparse examples for the trace viewer.

    Zero density is counted across A and B combined. Sparse matrices retain
    the dense values at unmasked positions; their dimensions never change.
    """
    base_a, base_b = demo_matrices(n)
    # The earlier demonstration matrices had occasional zeros. Make the
    # dense example strictly nonzero so the contrast is unambiguous.
    dense_a = [[value if value else 1 for value in row] for row in base_a]
    dense_b = [[value if value else -1 for value in row] for row in base_b]
    cases = {"dense": (dense_a, dense_b, 0)}
    for pct in (25, 50, 75):
        a = [row[:] for row in dense_a]
        b = [row[:] for row in dense_b]
        count = round(2 * n * n * pct / 100)
        rng = random.Random(6143 + n)
        positions_a = list(range(n * n))
        positions_b = list(range(n * n))
        rng.shuffle(positions_a)
        rng.shuffle(positions_b)
        for index in positions_a[: (count + 1) // 2]:
            a[index // n][index % n] = 0
        for index in positions_b[: count // 2]:
            b[index // n][index % n] = 0
        cases[f"sparse{pct}"] = (a, b, pct)
    return cases


def annotate_datapath(trace, *, zero_gate=False):
    """Annotate a *model* trace with sampled multiplier-input transitions.

    These counts are model predictions, not RTL observations or power estimates.
    """
    width = trace['meta']['width']
    mask = (1 << width) - 1
    n = trace['meta']['n']
    previous_a = [0] * (n * n)
    previous_b = [0] * (n * n)
    total_flips = 0
    for frame in trace['cycles']:
        flips = 0
        gated = 0
        for i, row in enumerate(frame['cells']):
            for j, cell in enumerate(row):
                lane = i * n + j
                zero_slot = cell['active'] and cell['product'] == 0
                cell['gated'] = bool(zero_gate and zero_slot)
                if cell['gated']:
                    gated += 1
                a = 0 if cell['a'] is None else cell['a']
                b = 0 if cell['b'] is None else cell['b']
                if zero_gate and (not cell['active'] or zero_slot):
                    a = b = 0
                a &= mask
                b &= mask
                flips += (previous_a[lane] ^ a).bit_count()
                flips += (previous_b[lane] ^ b).bit_count()
                previous_a[lane], previous_b[lane] = a, b
        frame['gated_count'] = gated
        frame['operand_bit_flips'] = flips
        total_flips += flips
    trace['meta']['zero_gate'] = bool(zero_gate)
    trace['meta']['operand_bit_flips'] = total_flips
    trace['meta']['switching_method'] = 'reference-model pre-edge multiplier-input bit transitions'
    return trace
