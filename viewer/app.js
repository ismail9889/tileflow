'use strict';

// build_demo.py embeds independently captured traces for every selected size.
const TRACES = /*__INSERT_TRACES__*/null;

if (!TRACES || Object.keys(TRACES).length === 0) {
  throw new Error('Generate this viewer with: python tools/build_demo.py [--rtl]');
}

const sizes = Object.keys(TRACES).map(Number).sort((a, b) => a - b);
let trace;
let n;
let frames;
let cumulative;
let idleFrame;
const $ = (id) => document.getElementById(id);
const setText = (id, value) => { $(id).textContent = value; };

let cycle = 0;
let timer = null;

function chip(value, kind) {
  const dim = value === null ? ' dim' : '';
  return `<span class="chip ${kind}${dim}">${value === null ? '–' : value}</span>`;
}

function matrixHTML(matrix) {
  const entries = matrix.flat().map((value, index) =>
    `<div class="matrix-number" data-index="${index}">${value}</div>`
  ).join('');
  return `<div class="matrix-grid" style="grid-template-columns:repeat(${n},1fr)">${entries}</div>`;
}

// At recorded edge t, PE(i,j) consumes A[i,k] and B[k,j], k=t-i-j.
// Use positions, not values: repeated values and zeros must highlight the
// correct matrix entries. Several entries can be active in parallel.
function highlightActiveInputs(frame) {
  const aIndices = new Set();
  const bIndices = new Set();
  if (cycle > 0) {
    const t = cycle - 1;
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const cell = frame.cells[i][j];
        if (!cell.active) continue;
        const k = t - i - j;
        if (k < 0 || k >= n ||
            cell.a !== trace.a[i][k] || cell.b !== trace.b[k][j]) {
          throw new Error(`Operand/source mismatch at cycle ${cycle}, PE[${i},${j}]`);
        }
        aIndices.add(i * n + k);
        bIndices.add(k * n + j);
      }
    }
  }
  for (const [container, indices] of [['matrixA', aIndices], ['matrixB', bIndices]]) {
    for (const entry of $(container).querySelectorAll('.matrix-number')) {
      entry.classList.toggle('in-use', indices.has(Number(entry.dataset.index)));
    }
  }
}

function horizontalLink(value) {
  const idle = value === null ? ' link-idle' : '';
  return `<span class="link link-h${idle}" aria-label="A moves right">` +
    `<span class="link-value">${value === null ? '→' : value}</span></span>`;
}

function verticalLink(value) {
  const idle = value === null ? ' link-idle' : '';
  return `<span class="link link-v${idle}" aria-label="B moves down">` +
    `<span class="link-value">${value === null ? '↓' : value}</span></span>`;
}

function renderCell(frame, row, column) {
  const cell = frame.cells[row][column];
  const zero = cell.active && (cell.a === 0 || cell.b === 0);
  const state = cell.gated ? 'gated' : cell.active ? (zero ? 'zero-op' : 'active')
    : (cell.a !== null || cell.b !== null ? 'pending' : '');

  // Link labels are the operands arriving at the destination on this edge.
  const right = column + 1 < n ? frame.cells[row][column + 1].a : null;
  const down = row + 1 < n ? frame.cells[row + 1][column].b : null;
  const horizontal = column + 1 < n ? horizontalLink(right) : '';
  const vertical = row + 1 < n ? verticalLink(down) : '';
  const calculation = cell.gated ? 'Zero product · MAC isolated'
    : cell.active ? `${cell.a} × ${cell.b} = ${cell.product}` : '— idle —';

  return `
    <div class="tile ${state}">
      <div class="pe-id">PE [${row},${column}]</div>
      <div class="operand-line">${chip(cell.a, 'a')}${chip(cell.b, 'b')}</div>
      <div class="calc">${calculation}</div>
      <div class="acc">ACC <strong>${cell.acc}</strong></div>
      ${horizontal}${vertical}
    </div>`;
}

// Cycle 0 is the cleared, pre-injection state; recorded edges begin at Cycle 1.
function makeIdleFrame(size) {
  return {
    a_edge: Array(size).fill(null),
    b_edge: Array(size).fill(null),
    active_count: 0,
    cells: Array.from({ length: size }, () =>
      Array.from({ length: size }, () =>
        ({ a: null, b: null, active: false, gated: false, product: null, acc: 0 })
      )
    ),
    c: Array.from({ length: size }, () => Array(size).fill(0)),
  };
}

function render() {
  const frame = cycle === 0 ? idleFrame : frames[cycle - 1];
  $('scrub').value = String(cycle);
  setText('clock', `Cycle ${cycle} / ${frames.length}`);
  setText('active', String(frame.active_count));
  setText('cumulative', String(cycle ? cumulative[cycle - 1] : 0));
  setText('util', `${Math.round(100 * frame.active_count / (n * n))}%`);
  setText('overall', cycle
    ? `${(100 * cumulative[cycle - 1] / (cycle * n * n)).toFixed(1)}%`
    : '0.0%');
  renderComparison();
  highlightActiveInputs(frame);

  const topInputs = frame.b_edge.map((value) =>
    `<div class="input-b">${chip(value, 'b')}<div class="down-arrow">↓</div></div>`
  ).join('');
  const top = `
    <div class="top-inputs" style="grid-template-columns:34px repeat(${n},minmax(0,1fr))">
      <div></div>${topInputs}
    </div>`;

  const rows = frame.cells.map((cells, row) => {
    const input = `<div class="left-input">${chip(frame.a_edge[row], 'a')}` +
      '<span class="right-arrow">→</span></div>';
    return `
      <div class="array-row" style="grid-template-columns:34px repeat(${n},minmax(0,1fr))">
        ${input}${cells.map((_, column) => renderCell(frame, row, column)).join('')}
      </div>`;
  }).join('');

  $('array').style.minWidth = `${Math.max(480, n * (n >= 8 ? 116 : 156) + 34)}px`;
  $('array').classList.toggle('dense', n >= 8);
  $('array').innerHTML = top + rows;

  $('output').classList.toggle('dense', n >= 8);
  $('output').innerHTML = frame.c.map((row) =>
    `<div class="output-row">${row.map((value) =>
      `<span class="entry ${cycle === frames.length ? 'done' : ''}">${value}</span>`
    ).join('')}</div>`
  ).join('');

  const finished = cycle === frames.length;
  setText('status', cycle === 0
    ? 'Cycle 0: cleared, pre-injection state. No compute clock has elapsed.'
    : finished
      ? 'Complete. Outputs match the reference. Zero gating changes activity, not execution cycles.'
      : 'Green: nonzero MAC. Purple: conventional zero product. Gray: multiplier isolated.');
  $('prev').disabled = cycle === 0;
  $('next').disabled = finished;
}

function pause() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
  setText('toggle', '▶ Play');
}

function step(delta) {
  cycle = Math.max(0, Math.min(frames.length, cycle + delta));
  render();
  if (cycle === frames.length) pause();
}

function play() {
  if (timer !== null) {
    pause();
    return;
  }
  if (cycle === frames.length) cycle = 0;
  render();
  setText('toggle', 'Ⅱ Pause');
  timer = setInterval(() => step(1), Number($('speed').value));
}

function selectedProfile() {
  const mode = $('workload').value;
  return mode === 'dense' ? 'dense' : `${mode}${$('density').value}`;
}

// Both workloads use the same base matrices. Sparse inputs mask selected
// elements but never change the fixed compute schedule.
function profileStats(profile) {
  const data = TRACES[String(n)][profile];
  if (!data) throw new Error(`Missing comparison trace: ${profile}`);

  // This is cumulative through the *displayed* clock, not a full-run total.
  let macs = 0;
  let zeros = 0;
  let active = 0;
  let isolated = 0;
  let flips = 0;
  for (let t = 0; t < cycle; t++) {
    const frame = data.cycles[t];
    active = frame.active_count;
    macs += active;
    isolated += frame.gated_count;
    flips += frame.operand_bit_flips;
    for (const row of frame.cells) {
      for (const cell of row) {
        if (cell.active && cell.product === 0) zeros++;
      }
    }
  }
  return { macs, active, zeros, nonzero: macs - zeros,
    isolated, flips, inputZeros: data.meta.input_zero_percent };
}

function renderComparison() {
  const dense = profileStats('dense');
  const sparse = profileStats(`sparse${$('density').value}`);
  const gated = profileStats(`gated${$('density').value}`);
  setText('comparisonCycle', `through cycle ${cycle} / ${frames.length}`);
  const row = (label, key) => `<tr><th scope="row">${label}</th>` +
    [dense, sparse, gated].map(stats => `<td>${stats[key]}</td>`).join('') + '</tr>';
  $('comparison').innerHTML = `
    <table class="compare-table">
      <thead><tr><th scope="col">Metric</th><th scope="col">Dense</th>` +
      `<th scope="col">Sparse</th><th scope="col">Zero-gated</th></tr></thead>
      <tbody>
        <tr><th scope="row">Cycles elapsed</th><td>${cycle}</td><td>${cycle}</td><td>${cycle}</td></tr>
        ${row('MACs this cycle', 'active')}
        ${row('Scheduled MACs', 'macs')}
        ${row('Zero products', 'zeros')}
        ${row('Zero-product slots isolated', 'isolated')}
        ${row('Multiplier-input bit transitions¹', 'flips')}
      </tbody>
    </table>`;
}

function selectConfiguration(preserveCycle = false) {
  pause();
  const size = $('size').value;
  const profile = selectedProfile();
  trace = TRACES[size][profile];
  if (!trace) throw new Error(`Missing ${profile} trace for ${size}×${size}`);
  n = trace.meta.n;
  frames = trace.cycles;
  idleFrame = makeIdleFrame(n);
  let macs = 0;
  cumulative = [];
  for (const frame of frames) {
    macs += frame.active_count;
    cumulative.push(macs);
  }
  $('densityControl').hidden = $('workload').value === 'dense';
  cycle = preserveCycle ? Math.min(cycle, frames.length) : 0;
  $('matrixA').innerHTML = matrixHTML(trace.a);
  $('matrixB').innerHTML = matrixHTML(trace.b);
  $('matrixA').parentElement.parentElement.classList.toggle('large', n >= 8);
  $('scrub').max = String(frames.length);
  $('scrub').value = String(cycle);
  render();
}

$('size').innerHTML = sizes.map((size) =>
  `<option value="${size}">${size} × ${size} (${size * size} PEs)</option>`
).join('');
$('size').value = String(sizes.includes(4) ? 4 : sizes[0]);
$('size').addEventListener('change', () => selectConfiguration(false));
$('workload').addEventListener('change', () => selectConfiguration(true));
$('density').addEventListener('change', () => selectConfiguration(true));

$('toggle').addEventListener('click', play);
$('prev').addEventListener('click', () => { pause(); step(-1); });
$('next').addEventListener('click', () => { pause(); step(1); });
$('reset').addEventListener('click', () => { pause(); cycle = 0; render(); });
$('speed').addEventListener('change', () => {
  if (timer !== null) { pause(); play(); }
});
$('scrub').addEventListener('input', (event) => {
  pause();
  cycle = Number(event.target.value);
  render();
});
document.addEventListener('keydown', (event) => {
  if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT') return;
  if (event.key === 'ArrowRight') { pause(); step(1); }
  if (event.key === 'ArrowLeft') { pause(); step(-1); }
  if (event.code === 'Space') { event.preventDefault(); play(); }
});

selectConfiguration(false);
