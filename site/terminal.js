/* ============================================================
   Trading Decision Terminal — 公共脚本
   刻意不依赖任何外部库：仪表盘和曲线都是手写 SVG，
   因为部署环境访问外部 CDN 不稳定，少一个外部依赖少一个故障点。
   ============================================================ */

const DATA_BASE = "./data";

/* ---------- 数据读取 ---------- */

const _problems = [];

function reportProblem(where, detail) {
  _problems.push(`${where}：${detail}`);
  const el = document.getElementById("diag");
  if (!el) return;
  el.hidden = false;
  el.textContent = "部分内容未能加载（其余不受影响）\n" + _problems.join("\n");
}

async function loadJson(name, fallback = null) {
  try {
    const res = await fetch(`${DATA_BASE}/${name}?t=${Date.now()}`, { cache: "no-store" });
    if (res.status === 404) return fallback;           // 文件还没生成，属正常
    if (!res.ok) { reportProblem(name, `HTTP ${res.status}`); return fallback; }
    return await res.json();
  } catch (e) {
    reportProblem(name, e.message || String(e));
    return fallback;
  }
}

/* 每块内容独立渲染，一块失败不影响其他块 */
function panel(name, fn) {
  try { fn(); } catch (e) { reportProblem(name, e.message || String(e)); }
}

/* ---------- 格式化 ---------- */

const fmt = {
  pct(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return (v * 100).toFixed(digits) + "%";
  },
  signedPct(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const s = (v * 100).toFixed(digits) + "%";
    return v > 0 ? "+" + s : s;
  },
  num(v, digits = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return Number(v).toFixed(digits);
  },
  price(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return Number(v).toFixed(2);
  },
  /* A股约定：涨=红(up)，跌=绿(down) */
  dirClass(v) {
    if (v === null || v === undefined || Number.isNaN(v) || v === 0) return "flat";
    return v > 0 ? "up" : "down";
  },
  code(c) {
    return String(c || "").toUpperCase();
  },
};

function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- 顶部导航与时间戳 ---------- */

const NAV = [
  { href: "index.html",     label: "市场雷达" },
  { href: "sectors.html",   label: "板块与选股" },
  { href: "signals.html",   label: "建仓候选" },
  { href: "alert.html",     label: "启动前预警" },
  { href: "holdings.html",  label: "持仓监控" },
  { href: "positions.html", label: "持仓录入" },
];

function buildChrome(currentFile) {
  const tabs = document.getElementById("tabs");
  if (tabs) {
    tabs.innerHTML = NAV.map(n =>
      `<a href="./${n.href}"${n.href === currentFile ? ' aria-current="page"' : ""}>${n.label}</a>`
    ).join("");
  }
}

async function stampLastRun() {
  const el = document.getElementById("stamp");
  if (!el) return;
  const lastRun = await loadJson("last_run.json");
  el.textContent = lastRun && lastRun.run_at ? `数据更新于 ${lastRun.run_at}` : "尚无运行记录";
}

/* ---------- 空状态 ---------- */

function emptyState(title, hint) {
  return `<div class="empty"><strong>${esc(title)}</strong>${esc(hint || "")}</div>`;
}

/* ---------- 仪表盘（半圆表盘，纯 SVG 手绘） ---------- */

function renderGauge(el, score) {
  const W = 320, H = 182, cx = 160, cy = 164, r = 128;
  const clamped = Math.max(0, Math.min(100, Number(score) || 0));

  // 半圆从 180°（左）扫到 0°（右）
  const polar = (pct) => {
    const a = Math.PI * (1 - pct / 100);
    return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
  };
  const arc = (from, to, cls, width) => {
    const [x1, y1] = polar(from), [x2, y2] = polar(to);
    const large = (to - from) > 50 ? 1 : 0;
    return `<path d="M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}"
      fill="none" stroke-linecap="butt" stroke-width="${width}" class="${cls}"/>`;
  };

  // 底轨按四个档位分段，颜色对应各档风险等级
  const segs = [
    { from: 0,  to: 40,  color: "var(--down)" },
    { from: 40, to: 60,  color: "var(--warn)" },
    { from: 60, to: 80,  color: "var(--accent)" },
    { from: 80, to: 100, color: "var(--up)" },
  ];

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="市场评分 ${clamped}">`;
  // 底轨（浅）
  segs.forEach(s => {
    svg += arc(s.from, s.to, "", 12).replace('class=""', `stroke="${s.color}" opacity="0.16"`);
  });
  // 已达成部分（实色）
  segs.forEach(s => {
    if (clamped <= s.from) return;
    const to = Math.min(clamped, s.to);
    svg += arc(s.from, to, "", 12).replace('class=""', `stroke="${s.color}" opacity="0.95"`);
  });
  // 阈值刻度 40/60/80
  [40, 60, 80].forEach(t => {
    const [x1, y1] = polar(t);
    const inner = r - 10, outer = r + 10;
    const a = Math.PI * (1 - t / 100);
    svg += `<line x1="${(cx + inner * Math.cos(a)).toFixed(2)}" y1="${(cy - inner * Math.sin(a)).toFixed(2)}"
      x2="${(cx + outer * Math.cos(a)).toFixed(2)}" y2="${(cy - outer * Math.sin(a)).toFixed(2)}"
      stroke="var(--line-strong)" stroke-width="1"/>`;
    svg += `<text x="${(cx + (outer + 9) * Math.cos(a)).toFixed(2)}" y="${(cy - (outer + 5) * Math.sin(a)).toFixed(2)}"
      text-anchor="middle" class="curve-tick">${t}</text>`;
  });
  // 指针
  const a = Math.PI * (1 - clamped / 100);
  svg += `<line x1="${cx}" y1="${cy}" x2="${(cx + (r - 22) * Math.cos(a)).toFixed(2)}"
    y2="${(cy - (r - 22) * Math.sin(a)).toFixed(2)}" stroke="var(--ink)" stroke-width="2.5" stroke-linecap="round"/>`;
  svg += `<circle cx="${cx}" cy="${cy}" r="5" fill="var(--ink)"/>`;
  svg += `</svg>`;
  el.innerHTML = svg;
}

/* ---------- 折线图（净值曲线，纯 SVG） ---------- */

function renderCurve(el, points, opts = {}) {
  if (!points || points.length < 2) {
    el.innerHTML = emptyState("暂无曲线数据", "累积若干笔已平仓记录后自动生成");
    return;
  }
  const W = 900, H = 240, padL = 56, padR = 16, padT = 16, padB = 30;
  const ys = points.map(p => p.y);
  let min = Math.min(...ys), max = Math.max(...ys);
  if (min === max) { min -= 1; max += 1; }
  const pad = (max - min) * 0.08;
  min -= pad; max += pad;

  const X = i => padL + (W - padL - padR) * (i / (points.length - 1));
  const Y = v => padT + (H - padT - padB) * (1 - (v - min) / (max - min));

  const line = points.map((p, i) => `${i ? "L" : "M"} ${X(i).toFixed(1)} ${Y(p.y).toFixed(1)}`).join(" ");
  const area = `${line} L ${X(points.length - 1).toFixed(1)} ${Y(min).toFixed(1)} L ${X(0).toFixed(1)} ${Y(min).toFixed(1)} Z`;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="curve" role="img" aria-label="${esc(opts.label || "曲线")}">`;
  // 横向网格 + 左侧刻度
  for (let i = 0; i <= 4; i++) {
    const v = min + (max - min) * (i / 4);
    const y = Y(v);
    svg += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" class="curve-axis"/>`;
    svg += `<text x="${padL - 8}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" class="curve-tick">${
      opts.yFormat ? opts.yFormat(v) : v.toFixed(0)}</text>`;
  }
  svg += `<path d="${area}" class="curve-area"/>`;
  svg += `<path d="${line}" class="curve-line"/>`;
  // 首尾日期
  [0, points.length - 1].forEach(i => {
    svg += `<text x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : "end"}" class="curve-tick">${
      esc(points[i].x)}</text>`;
  });
  svg += `</svg>`;
  el.innerHTML = svg;
}

/* ---------- 计量条 ---------- */

function meter(label, value, max, detail) {
  const ratio = max ? Math.max(0, Math.min(1, value / max)) : 0;
  return `<div class="meter">
    <div class="meter-row">
      <span class="meter-label">${esc(label)}</span>
      <span class="meter-value">${fmt.num(value, 1)} / ${max}</span>
    </div>
    <div class="meter-track"><div class="meter-fill" style="width:${(ratio * 100).toFixed(1)}%"></div></div>
    ${detail ? `<div class="meter-detail">${esc(detail)}</div>` : ""}
  </div>`;
}

/* 把 breakdown 里的 detail 对象压成一行可读文字 */
function detailLine(detail) {
  if (!detail || typeof detail !== "object") return "";
  return Object.entries(detail)
    .map(([k, v]) => `${k} ${typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) : v}`)
    .join(" · ");
}

/* 操作提示 -> 徽标样式（A股：加仓偏红，减仓偏绿） */
function actionBadge(action) {
  const a = String(action || "");
  let cls = "badge-hold";
  if (a.includes("加仓")) cls = "badge-add";
  else if (a.includes("清仓") || a.includes("减仓")) cls = "badge-cut";
  else if (a.includes("底仓")) cls = "badge-warn";
  return `<span class="badge ${cls}">${esc(a || "持有")}</span>`;
}
