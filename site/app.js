// 仪表盘公共逻辑：从本站同源的 data/*.json 读取阿里云函数写入 GitHub 的结果。
// 这些 json 是 Cloudflare Pages 直接从仓库 site/data/ 目录静态托管的，不需要额外的 API。

const DATA_BASE = "./data";

async function fetchJson(name, fallback = null) {
  try {
    const res = await fetch(`${DATA_BASE}/${name}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return await res.json();
  } catch (e) {
    console.warn(`读取 ${name} 失败`, e);
    return fallback;
  }
}

function modeClass(mode) {
  if (!mode) return "";
  if (mode.includes("进攻")) return "mode-attack";
  if (mode.includes("正常")) return "mode-normal";
  if (mode.includes("谨慎")) return "mode-caution";
  return "mode-defense";
}

function actionBadgeClass(action) {
  if (!action) return "badge-hold";
  if (action.includes("买入") || action.includes("加仓")) return "badge-add";
  if (action.includes("清仓") || action.includes("减仓")) return "badge-reduce";
  return "badge-hold";
}

function setUpdatedTime(text) {
  const el = document.getElementById("updated-time");
  if (el) el.textContent = text ? `最后更新: ${text}` : "";
}
