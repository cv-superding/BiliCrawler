/* 全局前端工具：API 调用、提示、状态轮询 */
const App = (() => {
  const api = async (url, opts = {}) => {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  };

  const post = (url, body) =>
    api(url, { method: "POST", body: JSON.stringify(body || {}) });

  const del = (url) => api(url, { method: "DELETE" });

  let toastTimer = null;
  const toast = (msg) => {
    let el = document.querySelector(".toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  };

  const STATUS_TEXT = {
    pending: "排队中", running: "采集中", paused: "已暂停",
    completed: "已完成", failed: "失败", cancelled: "已取消",
  };
  const escapeHtml = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  return { api, post, del, toast, STATUS_TEXT, escapeHtml };
})();
