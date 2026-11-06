"""Build one offline trace viewer for multiple array dimensions.

    python tools/run_rtl.py --sizes 2 3 4 8
    python tools/build_demo.py --rtl
    python tools/build_demo.py  # reference-model traces only
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.model import trace_gemm, viewer_workloads, annotate_datapath

STYLE_TAG = '<link rel="stylesheet" href="style.css">'
SCRIPT_TAG = '<script src="app.js"></script>'
TRACE_MARKER = '/*__INSERT_TRACES__*/null'
REFERENCE_STAMP = 'REFERENCE-MODEL TRACE · NOT RTL MEASURED'
RTL_STAMP = 'RTL-OBSERVED TRACES · VERILATOR + COCOTB'


def check_trace(trace, n, profile, target_zero_percent):
    """Reject absent or mismatched traces instead of silently using model data."""
    if trace['meta']['n'] != n:
        raise ValueError(f'Trace array dimension does not match {n}')
    if len(trace['cycles']) != 3 * n - 2:
        raise ValueError(f'Incomplete cycle trace for N={n}')
    if len(trace['a']) != n or len(trace['b']) != n:
        raise ValueError(f'Invalid operand dimensions for N={n}')
    if trace['cycles'][-1]['c'] != trace['expected']:
        raise ValueError(f'Final matrix does not match expected output for N={n}')
    if trace['meta'].get('workload') != profile:
        raise ValueError(f'Wrong workload profile for N={n}: {profile}')
    if trace['meta'].get('target_zero_percent') != target_zero_percent:
        raise ValueError(f'Wrong zero-density target for N={n}: {profile}')
    if trace['meta'].get('zero_gate') is not profile.startswith('gated'):
        raise ValueError(f'Wrong hardware gating mode for N={n}: {profile}')
    if any('operand_bit_flips' not in frame or 'gated_count' not in frame
           for frame in trace['cycles']):
        raise ValueError(f'Missing switching counters for N={n}: {profile}')
    if sum(frame['operand_bit_flips'] for frame in trace['cycles']) != trace['meta']['operand_bit_flips']:
        raise ValueError(f'Inconsistent sampled input transitions for N={n}: {profile}')
    a, b = trace['a'], trace['b']
    if any(len(row) != n for row in a + b):
        raise ValueError(f'Invalid matrix shape for N={n}: {profile}')
    zero_pct = 100 * sum(x == 0 for matrix in (a, b) for row in matrix for x in row) / (2 * n * n)
    if abs(trace['meta']['input_zero_percent'] - zero_pct) > 1e-7:
        raise ValueError(f'Input zero-density mismatch for N={n}: {profile}')


def build_html(traces, *, rtl):
    viewer = ROOT / 'viewer'
    template = (viewer / 'index.html').read_text(encoding='utf-8')
    css = (viewer / 'style.css').read_text(encoding='utf-8')
    js = (viewer / 'app.js').read_text(encoding='utf-8')
    if template.count(STYLE_TAG) != 1 or template.count(SCRIPT_TAG) != 1:
        raise ValueError('Viewer HTML is missing a unique source marker')
    if js.count(TRACE_MARKER) != 1:
        raise ValueError('Viewer JavaScript is missing the trace marker')
    # Escape HTML-sensitive sequences inside serialized strings in the script.
    embedded = json.dumps(traces, separators=(',', ':')).replace('<', '\\u003c')
    js = js.replace(TRACE_MARKER, embedded)
    template = template.replace(STYLE_TAG, f'<style>\n{css}</style>')
    template = template.replace(SCRIPT_TAG, f'<script>\n{js}</script>')
    if rtl:
        template = template.replace(REFERENCE_STAMP, RTL_STAMP)
    return template


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', action='store_true', help='Use captured Verilator/cocotb traces')
    parser.add_argument('--publish', action='store_true',
                        help='Also write verified RTL demo to docs/index.html for GitHub Pages')
    parser.add_argument('--sizes', nargs='+', type=int, default=[2, 3, 4, 8],
                        help='array sizes to include (default: 2 3 4 8)')
    args = parser.parse_args()
    if args.publish and not args.rtl:
        parser.error('--publish requires --rtl (never publish a model preview as RTL)')
    sizes = list(dict.fromkeys(args.sizes))
    if any(n < 1 for n in sizes):
        parser.error('Array sizes must be positive integers')
    artifacts = ROOT / 'artifacts'
    artifacts.mkdir(exist_ok=True)

    traces = {}
    for n in sizes:
        profiles = {}
        workload_cases = viewer_workloads(n)
        for profile in (*workload_cases, 'gated25', 'gated50', 'gated75'):
            original = profile.replace('gated', 'sparse')
            a, b, target = workload_cases[original]
            gate = profile.startswith('gated')
            if args.rtl:
                source = artifacts / f'rtl_trace_n{n}_{profile}.json'
                if not source.exists():
                    parser.error(f'Missing {source.relative_to(ROOT)}; run '
                                 f'python tools/run_rtl.py --sizes {" ".join(map(str, sizes))}')
                trace = json.loads(source.read_text(encoding='utf-8'))
                if not trace['meta']['trace_source'].startswith('RTL-observed'):
                    parser.error(f'{source.name} is not an RTL-captured trace')
                if trace['a'] != a or trace['b'] != b:
                    parser.error(f'{source.name} uses unexpected inputs; rerun RTL tests')
            else:
                trace = annotate_datapath(trace_gemm(a, b), zero_gate=gate)
                trace['meta'].update(workload=profile, target_zero_percent=target)
            check_trace(trace, n, profile, target)
            profiles[profile] = trace
        for pct in (25, 50, 75):
            sparse = profiles[f'sparse{pct}']
            gated = profiles[f'gated{pct}']
            if (sparse['a'], sparse['b'], sparse['expected']) != (gated['a'], gated['b'], gated['expected']):
                raise ValueError(f'Mismatched sparse/gated operands at N={n}, density={pct}')
        traces[str(n)] = profiles

    output = artifacts / ('rtl_demo.html' if args.rtl else 'demo.html')
    html = build_html(traces, rtl=args.rtl)
    output.write_text(html, encoding='utf-8')
    if args.publish:
        published = ROOT / 'docs' / 'index.html'
        published.write_text(html, encoding='utf-8')
        print('Updated GitHub Pages demo:', published.relative_to(ROOT))
    print('Generated:', output.relative_to(ROOT))
    print('Included arrays:', ', '.join(f'{n}x{n}' for n in sizes))
    print('Trace source:', 'Verilator + cocotb' if args.rtl else 'Python reference model')


if __name__ == '__main__':
    main()
