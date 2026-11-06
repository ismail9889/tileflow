"""Build and test the signed systolic array with Verilator and cocotb.

    python tools/run_rtl.py                 # N=2,3,4,8; saves viewer traces
    python tools/run_rtl.py --sizes 4       # verify only the 4x4 array
"""
import argparse
from pathlib import Path
import sys

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[2, 3, 4, 8],
                        help="array dimensions to verify (default: 2 3 4 8)")
    args = parser.parse_args()
    if any(n < 1 for n in args.sizes):
        parser.error("every array dimension must be positive")

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    runner = get_runner("verilator")
    for n in dict.fromkeys(args.sizes):
        for gate in (0, 1):
            build_dir = ROOT / 'build' / f'verilator_n{n}_g{gate}' 
            print(f'\nVerifying {n}x{n}, zero-gating={bool(gate)}', flush=True)
            runner.build(
            sources=[ROOT / "rtl/pe.sv", ROOT / "rtl/systolic_array.sv"],
            hdl_toplevel="systolic_array",
            parameters={"N": n, "W": 8, "ACC_W": 32, "ZERO_GATE": f"1'b{gate}"},
            build_dir=build_dir,
            always=True,
            )
            runner.test(
            hdl_toplevel="systolic_array", test_module="test_systolic",
            build_dir=build_dir,
            extra_env={"PYTHONPATH": f"{ROOT}:{ROOT / 'tests'}",
                       "TILEFLOW_N": str(n), "TILEFLOW_ZERO_GATE": str(gate)},
            )
    print("\nAll requested array dimensions passed.")


if __name__ == "__main__":
    main()
