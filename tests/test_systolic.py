"""Cycle-accurate cocotb checks against the independent Python model.

The RTL trace records observed operand taps, MAC pulses, and accumulators.
Operand validity is inferred from the deterministic input schedule.
"""
import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from sim.model import gemm, trace_gemm, viewer_workloads

ROOT = Path(__file__).resolve().parents[1]
W = 8
ACC_W = 32


def pack_signed(values, width):
    mask = (1 << width) - 1
    return sum((v & mask) << (i * width) for i, v in enumerate(values))


def unpack_signed(bits, count, width):
    mask = (1 << width) - 1
    sign = 1 << (width - 1)
    values = []
    for i in range(count):
        value = (bits >> (i * width)) & mask
        values.append(value - (1 << width) if value & sign else value)
    return values


async def clear_array(dut):
    dut.a_edge.value = 0
    dut.b_edge.value = 0
    dut.a_valid_edge.value = 0
    dut.b_valid_edge.value = 0
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.clear.value = 0


async def run_one(dut, a, b, capture=False, profile=None, zero_percent=0, zero_gate=False):
    n = len(a)
    expected_trace = trace_gemm(a, b, width=W, acc_width=ACC_W)
    recorded = []
    prev_mul_a = prev_mul_b = 0
    cumulative_flips = 0
    await clear_array(dut)
    for t in range(3 * n - 2):
        a_edge = [a[i][t - i] if i <= t < i + n else 0 for i in range(n)]
        b_edge = [b[t - j][j] if j <= t < j + n else 0 for j in range(n)]
        av = [int(i <= t < i + n) for i in range(n)]
        bv = [int(j <= t < j + n) for j in range(n)]
        dut.a_edge.value = pack_signed(a_edge, W)
        dut.b_edge.value = pack_signed(b_edge, W)
        dut.a_valid_edge.value = pack_signed(av, 1)
        dut.b_valid_edge.value = pack_signed(bv, 1)
        # Sample combinational multiplier inputs just BEFORE the active edge.
        # This is a sampled bit-transition metric, not internal-gate activity.
        await Timer(1, unit='ns')
        mul_a_bits = int(dut.mul_a_taps_flat.value)
        mul_b_bits = int(dut.mul_b_taps_flat.value)
        bit_flips = (mul_a_bits ^ prev_mul_a).bit_count() + (mul_b_bits ^ prev_mul_b).bit_count()
        prev_mul_a, prev_mul_b = mul_a_bits, mul_b_bits
        cumulative_flips += bit_flips
        oracle = expected_trace['cycles'][t]
        observed_a = unpack_signed(mul_a_bits, n * n, W)
        observed_b = unpack_signed(mul_b_bits, n * n, W)
        for i in range(n):
            for j in range(n):
                lane = i*n+j
                ref = oracle['cells'][i][j]
                zero_op = ref['active'] and ref['product'] == 0
                if zero_gate:
                    exp_a = ref['a'] if ref['active'] and not zero_op else 0
                    exp_b = ref['b'] if ref['active'] and not zero_op else 0
                    assert (observed_a[lane], observed_b[lane]) == (exp_a, exp_b), (
                        n, t, lane, 'operand isolation')
                elif ref['active']:
                    assert (observed_a[lane], observed_b[lane]) == (ref['a'], ref['b']), (
                        n, t, lane, 'unmodified multiplier inputs')
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")

        pulses = int(dut.mac_pulses.value)
        gated_pulses = int(dut.gated_pulses.value)
        expected_gated = sum(cell['active'] and cell['product'] == 0
                             for row in oracle['cells'] for cell in row) if zero_gate else 0
        assert gated_pulses.bit_count() == expected_gated, (n, t, 'gated pulses')
        accum = unpack_signed(int(dut.c_flat.value), n * n, ACC_W)
        taps_a = unpack_signed(int(dut.a_taps_flat.value), n * n, W)
        taps_b = unpack_signed(int(dut.b_taps_flat.value), n * n, W)
        c = [accum[i * n:(i + 1) * n] for i in range(n)]
        assert c == oracle["c"], f"N={n} cycle={t}: accumulator mismatch"
        assert pulses.bit_count() == oracle["active_count"], (n, t, "activity")
        cells = []
        for i in range(n):
            row = []
            for j in range(n):
                lane = i * n + j
                ref = oracle["cells"][i][j]
                active = bool((pulses >> lane) & 1)
                assert active == ref["active"], (n, t, i, j, "MAC pulse")
                gated = bool((gated_pulses >> lane) & 1)
                assert gated == (zero_gate and active and ref['product'] == 0), (
                    n, t, i, j, 'gated pulse')
                avalue = taps_a[lane] if ref["a"] is not None else None
                bvalue = taps_b[lane] if ref["b"] is not None else None
                assert avalue == ref["a"], (n, t, i, j, "A tap")
                assert bvalue == ref["b"], (n, t, i, j, "B tap")
                row.append({"a": avalue, "b": bvalue, "active": active,
                            "gated": gated,
                            "product": avalue * bvalue if active else None,
                            "acc": accum[lane]})
            cells.append(row)
        if capture:
            recorded.append({"t": t, "a_edge": oracle["a_edge"],
                             "b_edge": oracle["b_edge"], "cells": cells,
                             "active_count": pulses.bit_count(),
                             "gated_count": gated_pulses.bit_count(),
                             "operand_bit_flips": bit_flips, "c": c})
        await FallingEdge(dut.clk)

    result = unpack_signed(int(dut.c_flat.value), n * n, ACC_W)
    result = [result[i * n:(i + 1) * n] for i in range(n)]
    expected = gemm(a, b)
    assert result == expected, f"N={n}: {result} != {expected}"
    if capture:
        trace = {**expected_trace, "cycles": recorded}
        trace["meta"].update({"workload": profile, "target_zero_percent": zero_percent,
                              "zero_gate": zero_gate, "operand_bit_flips": cumulative_flips,
                              "switching_method": "RTL-observed pre-edge multiplier-input bit transitions"})
        trace["meta"]["trace_source"] = (
            "RTL-observed taps, MAC activity and accumulators via Verilator + cocotb; "
            "validity inferred from input schedule; products derived from taps"
        )
        return trace


async def exercise_reset_and_clear(dut, n):
    """Check that partial sums and in-flight operands are discarded."""
    for asynchronous in (False, True):
        await clear_array(dut)
        dut.a_edge.value = pack_signed([1] * n, W)
        dut.b_edge.value = pack_signed([1] * n, W)
        dut.a_valid_edge.value = (1 << n) - 1
        dut.b_valid_edge.value = (1 << n) - 1
        for _ in range(n + 1):
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
        assert int(dut.c_flat.value) != 0, "test failed to form partial sums"

        if asynchronous:
            dut.rst_n.value = 0
            await Timer(1, unit="ns")
        else:
            dut.clear.value = 1
            await RisingEdge(dut.clk)
            await Timer(1, unit="ns")

        assert int(dut.c_flat.value) == 0, "partial sums survived reset/clear"
        assert int(dut.mac_pulses.value) == 0, "MAC pulse survived reset/clear"
        assert int(dut.gated_pulses.value) == 0, "gated pulse survived reset/clear"
        assert int(dut.a_taps_flat.value) == 0, "A operands survived reset/clear"
        assert int(dut.b_taps_flat.value) == 0, "B operands survived reset/clear"
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1
        dut.clear.value = 0
    # A fresh job after reset exercises recovery (tested by the caller).


@cocotb.test()
async def signed_dense_and_zero_matrices(dut):
    n = int(os.environ.get("TILEFLOW_N", "4"))
    zero_gate = bool(int(os.environ.get('TILEFLOW_ZERO_GATE', '0')))
    dut.rst_n.value = 0
    dut.clear.value = 0
    dut.a_edge.value = 0
    dut.b_edge.value = 0
    dut.a_valid_edge.value = 0
    dut.b_valid_edge.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    rng = random.Random(20261106 + n)
    zero = [[0] * n for _ in range(n)]
    identity = [[int(i == j) for j in range(n)] for i in range(n)]
    extreme = [[(-128 if (i + j) % 2 else 127) for j in range(n)] for i in range(n)]
    cases = [(zero, zero), (identity, extreme), (extreme, identity)]
    cases += [([[rng.randint(-128, 127) for _ in range(n)] for _ in range(n)],
               [[rng.randint(-128, 127) for _ in range(n)] for _ in range(n)])
              for _ in range(20)]
    for a, b in cases:
        await run_one(dut, a, b, zero_gate=zero_gate)

    await exercise_reset_and_clear(dut, n)
    # Record genuine RTL traces for both hardware configurations.
    for profile, (a, b, pct) in viewer_workloads(n).items():
        if zero_gate and profile == 'dense':
            continue
        if not zero_gate and profile.startswith('gated'):
            continue
        output_profile = profile.replace('sparse', 'gated') if zero_gate else profile
        trace = await run_one(dut, a, b, capture=True,
                              profile=output_profile, zero_percent=pct,
                              zero_gate=zero_gate)
        output = ROOT / "artifacts" / f"rtl_trace_n{n}_{output_profile}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        dut._log.info("RTL trace written: %s", output)
