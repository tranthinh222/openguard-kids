const LABELS = {
  education: "Giáo dục", entertainment: "Giải trí", social: "Mạng xã hội",
  games: "Trò chơi", age_inappropriate: "Không phù hợp lứa tuổi", unknown: "Chưa phân loại",
};

function appRow(rule = {}) {
  const row = document.createElement("div");
  row.className = "row g-2 align-items-center mb-2 app-rule";
  for (const [key, placeholder, size] of [["name", "game.exe", "col-md-3"], ["sha256", "SHA-256 (không bắt buộc)", "col-md-5"]]) {
    const cell = document.createElement("div"); cell.className = size;
    const input = document.createElement("input");
    input.className = "form-control"; input.dataset.field = key;
    input.placeholder = placeholder; input.setAttribute("aria-label", placeholder);
    input.value = rule[key] || ""; input.maxLength = key === "name" ? 124 : 64;
    cell.append(input); row.append(cell);
  }
  const cell = document.createElement("div"); cell.className = "col-md-4 d-flex gap-2";
  const action = document.createElement("select"); action.className = "form-select";
  action.dataset.field = "action"; action.setAttribute("aria-label", "Quy tắc ứng dụng");
  for (const [value, label] of [["allow", "Cho phép"], ["block", "Chặn"], ["default", "Mặc định (bỏ luật)"]]) {
    action.add(new Option(label, value));
  }
  action.value = rule.action || "block";
  const remove = document.createElement("button"); remove.type = "button";
  remove.className = "btn btn-outline-danger"; remove.textContent = "Xóa";
  remove.addEventListener("click", () => row.remove());
  cell.append(action, remove); row.append(cell);
  return row;
}

export function fillContentRules(payload) {
  const apps = document.getElementById("app-rules"); apps.replaceChildren();
  (payload.apps || []).forEach(rule => apps.append(appRow(rule)));
  const domains = Array.isArray(payload.domains) ? {} : (payload.domains || {});
  document.getElementById("domain-allow").value = (domains.allow || []).join("\n");
  document.getElementById("domain-block").value = (domains.block || []).join("\n");
  document.getElementById("safe-search").checked = domains.safe_search ?? true;
  const categories = document.getElementById("domain-categories"); categories.replaceChildren();
  const blocked = domains.blocked_categories || ["social", "games", "age_inappropriate"];
  for (const [value, label] of Object.entries(LABELS)) {
    const wrapper = document.createElement("label"); wrapper.className = "form-check form-check-inline";
    const input = document.createElement("input"); input.type = "checkbox";
    input.className = "form-check-input"; input.value = value; input.checked = blocked.includes(value);
    wrapper.append(input, document.createTextNode(label)); categories.append(wrapper);
  }
}

export function initContentRules() {
  document.getElementById("add-app-rule").addEventListener("click", () => document.getElementById("app-rules").append(appRow()));
  document.getElementById("save-content-policy").addEventListener("click", () => document.getElementById("save-policy-button").click());
}

export function readContentRules() {
  const apps = [...document.querySelectorAll(".app-rule")].map(row => {
    const read = name => row.querySelector(`[data-field="${name}"]`).value.trim();
    return { name: read("name"), sha256: read("sha256") || null, action: read("action") };
  }).filter(rule => rule.action !== "default");
  const lines = id => document.getElementById(id).value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  return { apps, domains: {
    allow: lines("domain-allow"), block: lines("domain-block"),
    blocked_categories: [...document.querySelectorAll("#domain-categories input:checked")].map(input => input.value),
    safe_search: document.getElementById("safe-search").checked,
  }};
}
