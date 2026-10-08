import { apiRequest, apiError } from "./api.js";
import { startLiveRefresh } from "./live-refresh.js";

const el = id => document.getElementById(id);
const duration = seconds => `${Math.floor(seconds / 3600)} giờ ${Math.floor(seconds % 3600 / 60)} phút ${seconds % 60} giây`;

function table(id, rows, metric) {
  const target = el(id); target.replaceChildren();
  if (!rows.length) { target.textContent = "Chưa có dữ liệu trong khoảng ngày này."; return; }
  const list = document.createElement("ul"); list.className = "list-group list-group-flush";
  rows.forEach(row => {
    const item = document.createElement("li"); item.className = "list-group-item d-flex justify-content-between gap-2 text-break";
    const name = document.createElement("span"); name.textContent = row.subject;
    const value = document.createElement("strong"); value.textContent = metric === "duration_sec" ? duration(row[metric]) : String(row[metric]);
    item.append(name, value); list.append(item);
  });
  target.append(list);
}

function render(data) {
  el("report-results").hidden = false;
  el("report-status").textContent = `Từ ${data.start} đến ${data.end} · UTC${data.timezone_offset_minutes >= 0 ? "+" : ""}${data.timezone_offset_minutes / 60}`;
  el("screen-total").textContent = data.has_screen_time_data ? duration(data.screen_time_sec) : "Chưa có dữ liệu";
  el("block-total").textContent = String(data.blocked_count);
  el("report-clock-note").textContent = data.untrusted_event_count ? `${data.untrusted_event_count} sự kiện dùng thời điểm server nhận do đồng hồ chưa tin cậy.` : "";
  const chart = el("daily-chart"); chart.replaceChildren();
  const max = Math.max(1, ...data.daily.map(day => day.screen_time_sec));
  for (const day of data.daily) {
    const row = document.createElement("div"); row.className = "mb-2";
    const label = document.createElement("div"); label.className = "small";
    label.textContent = `${day.date}: ${day.has_data ? duration(day.screen_time_sec) : "chưa đồng bộ"}`;
    const bar = document.createElement("div"); bar.className = "bg-primary rounded";
    bar.style.height = "12px"; bar.style.width = `${day.screen_time_sec / max * 100}%`;
    row.append(label, bar); chart.append(row);
  }
  table("top-apps", data.top_apps, "duration_sec");
  table("top-domains", data.top_domains, "count");
  table("top-blocks", data.blocks, "count");
}

export async function initReportsPage() {
  const children = await apiRequest("/api/v1/children");
  if (!children.length) {
    el("report-status").textContent = "Chưa có trẻ. Thêm hồ sơ trẻ để bắt đầu xem báo cáo.";
    el("report-load").disabled = true; return;
  }
  children.forEach(child => el("report-child").add(new Option(child.display_name, child.id)));
  const requested = new URLSearchParams(location.search).get("child_id");
  if (children.some(child => child.id === requested)) el("report-child").value = requested;
  const initial = await apiRequest(`/api/v1/children/${encodeURIComponent(el("report-child").value)}/reports/summary`);
  el("report-start").value = initial.start; el("report-end").value = initial.end;
  const today = initial.end;
  let stop, currentUrl;
  function load() {
    stop?.();
    el("report-results").hidden = true;
    el("report-export").disabled = true;
    el("report-status").textContent = "Đang tải...";
    const params = new URLSearchParams({start: el("report-start").value, end: el("report-end").value});
    currentUrl = `/api/v1/children/${encodeURIComponent(el("report-child").value)}/reports`;
    const url = `${currentUrl}/summary?${params}`;
    const exportUrl = `${currentUrl}/export.csv?${params}`;
    stop = startLiveRefresh(signal => apiRequest(url, {signal, cache: "no-store"}), data => {
      render(data); el("report-export").disabled = false; el("report-export").dataset.url = exportUrl;
    }, { intervalMs: 15000, onError: error => {
      // Existing data stays usable during a transient polling failure. The
      // shared refresh status shows stale state and clears itself on recovery.
      if (el("report-results").hidden) el("report-status").textContent = error.message;
    }});
  }
  el("report-range").addEventListener("change", () => {
    if (el("report-range").value === "custom") return;
    const start = new Date(`${today}T12:00:00Z`);
    start.setUTCDate(start.getUTCDate() - Number(el("report-range").value) + 1);
    el("report-start").value = start.toISOString().slice(0, 10); el("report-end").value = today;
    load();
  });
  for (const id of ["report-start", "report-end"]) el(id).addEventListener("change", () => {
    el("report-range").value = "custom"; load();
  });
  el("report-child").addEventListener("change", load);
  el("report-load").addEventListener("click", load);
  el("report-export").addEventListener("click", async () => {
    try {
      const response = await fetch(el("report-export").dataset.url, { credentials: "same-origin" });
      if (!response.ok) throw await apiError(response);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "openguard-report.csv";
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { el("report-status").textContent = error.message; }
  });
  load();
}
