// Atlas Richie Sentinel Dashboard v2 — 前端 JS
// (各页面的具体逻辑在对应模板的 {% block scripts %} 中)
// 这里只放全局工具函数.

(function () {
  "use strict";

  // 通用 admin 操作: 弹 token prompt + fetch + 弹结果
  window.adminAction = async function adminAction(path, method = "POST") {
    const token = window.prompt("Admin token:");
    if (!token) return;
    const resp = await fetch(path, {
      method: method,
      headers: { "Authorization": "Bearer " + token },
    });
    let data;
    try {
      data = await resp.json();
    } catch (e) {
      data = { error: "non-JSON response", status: resp.status };
    }
    if (!resp.ok) {
      alert("Error: " + (data.error || resp.statusText));
    } else {
      alert(JSON.stringify(data, null, 2));
    }
    return data;
  };

  // ISO 时间格式化 (audit log 用)
  window.formatTime = function (ns) {
    if (!ns) return "";
    return new Date(ns / 1e6).toISOString();
  };
})();
