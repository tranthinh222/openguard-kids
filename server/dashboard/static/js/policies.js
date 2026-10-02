import { apiRequest, apiWrite } from "./api.js";
import { setButtonBusy, showToast } from "./common.js";
import { startLiveRefresh } from "./live-refresh.js";

const DAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
let policyState = null;

function cloneValue(value) {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function emptyState(message) {
  const col = document.createElement("div");
  col.className = "col-12";
  const empty = document.createElement("div");
  empty.className = "empty-state card border-0 shadow-sm";
  const icon = document.createElement("i");
  icon.className = "bi bi-shield-check";
  const text = document.createElement("p");
  text.textContent = message;
  const link = document.createElement("a");
  link.href = "/children/new";
  link.className = "btn btn-primary";
  link.textContent = "Thêm trẻ";
  empty.append(icon, text, link);
  col.append(empty);
  return col;
}

function policyCard({ child, policy }) {
  const column = document.createElement("div");
  column.className = "col-12 col-lg-6";
  const card = document.createElement("article");
  card.className = "card border-0 shadow-sm h-100 policy-overview-card";
  const body = document.createElement("div");
  body.className = "card-body p-4";

  const top = document.createElement("div");
  top.className = "d-flex justify-content-between align-items-start gap-3 mb-3";
  const text = document.createElement("div");
  const title = document.createElement("h2");
  title.className = "h5 mb-1";
  title.textContent = child.display_name;
  const devices = document.createElement("p");
  devices.className = "small text-secondary mb-0";
  devices.textContent = `${child.online_count}/${child.device_count} thiết bị online`;
  text.append(title, devices);
  const version = document.createElement("span");
  version.className = "badge text-bg-light border";
  version.textContent = `Phiên bản v${policy.version}`;
  top.append(text, version);

  const screen = policy.payload?.screen_time || {};
  const stats = document.createElement("div");
  stats.className = "policy-summary-grid mb-3";
  const values = [
    ["Ngày thường", `${screen.weekday_minutes ?? 90} phút`],
    ["Cuối tuần", `${screen.weekend_minutes ?? 120} phút`],
    [
      "Idle timeout",
      `${Math.round((screen.idle_timeout_sec ?? 300) / 60)} phút`,
    ],
    ["Ân hạn", `${screen.grace_period_sec ?? 60} giây`],
  ];
  values.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "policy-summary-item";
    const labelEl = document.createElement("span");
    labelEl.className = "small text-secondary";
    labelEl.textContent = label;
    const valueEl = document.createElement("strong");
    valueEl.textContent = value;
    item.append(labelEl, valueEl);
    stats.append(item);
  });

  const actions = document.createElement("div");
  actions.className = "d-flex flex-wrap gap-2";
  const manage = document.createElement("a");
  manage.className = "btn btn-primary";
  manage.href = `/policies/${encodeURIComponent(child.id)}`;
  manage.innerHTML = '<i class="bi bi-sliders me-2"></i>Chỉnh chính sách';
  const profile = document.createElement("a");
  profile.className = "btn btn-outline-secondary";
  profile.href = `/children/${encodeURIComponent(child.id)}`;
  profile.textContent = "Xem hồ sơ";
  actions.append(manage, profile);

  body.append(top, stats, actions);
  card.append(body);
  column.append(card);
  return column;
}

function renderPolicyOverviewError(error) {
  const grid = document.getElementById("policies-grid");
  grid.replaceChildren();
  const col = document.createElement("div");
  col.className = "col-12";
  const alert = document.createElement("div");
  alert.className = "alert alert-danger mb-0";
  const title = document.createElement("strong");
  title.textContent = "Không tải được chính sách.";
  const detail = document.createElement("div");
  detail.className = "small mt-1";
  detail.textContent =
    error?.message || "Vui lòng kiểm tra Server API rồi tải lại trang.";
  alert.append(title, detail);
  col.append(alert);
  grid.append(col);
}

function renderPolicyOverview(items) {
  const grid = document.getElementById("policies-grid");
  grid.replaceChildren();
  if (items.length === 0) {
    grid.append(emptyState("Chưa có trẻ để cấu hình chính sách."));
    return;
  }
  items.forEach((item) => grid.append(policyCard(item)));
}

async function loadPolicyOverview(signal) {
  const children = await apiRequest("/api/v1/children", {
    signal,
    cache: "no-store",
  });
  return Promise.all(
    children.map(async (child) => ({
      child,
      policy: await apiRequest(
        `/api/v1/children/${encodeURIComponent(child.id)}/policy`,
        { signal, cache: "no-store" },
      ),
    })),
  );
}

function renderSchedule(slots) {
  const grid = document.getElementById("schedule-grid");
  grid.replaceChildren();
  const corner = document.createElement("div");
  corner.className = "schedule-corner";
  grid.append(corner);

  DAYS.forEach((day) => {
    const heading = document.createElement("div");
    heading.className = "schedule-day";
    heading.textContent = day;
    grid.append(heading);
  });

  for (let halfHour = 0; halfHour < 48; halfHour += 1) {
    const hour = String(Math.floor(halfHour / 2)).padStart(2, "0");
    const minute = halfHour % 2 === 0 ? "00" : "30";
    const time = document.createElement("div");
    time.className = "schedule-time";
    time.textContent = `${hour}:${minute}`;
    grid.append(time);

    for (let day = 0; day < 7; day += 1) {
      const index = day * 48 + halfHour;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `schedule-slot ${slots[index] ? "allowed" : "blocked"}`;
      button.dataset.index = String(index);
      button.title = `${DAYS[day]} ${hour}:${minute}`;
      button.setAttribute("aria-pressed", String(slots[index]));
      button.addEventListener("click", () => {
        slots[index] = !slots[index];
        button.classList.toggle("allowed", slots[index]);
        button.classList.toggle("blocked", !slots[index]);
        button.setAttribute("aria-pressed", String(slots[index]));
      });
      grid.append(button);
    }
  }
}

function fillPolicy(policy) {
  policyState = cloneValue(policy);
  const screenTime = policyState.payload?.screen_time || {};
  if (!policyState.payload) policyState.payload = {};
  if (
    !Array.isArray(policyState.payload.weekly_schedule) ||
    policyState.payload.weekly_schedule.length !== 336
  ) {
    policyState.payload.weekly_schedule = Array(336).fill(true);
  }

  document.getElementById("weekday-minutes").value =
    screenTime.weekday_minutes ?? 90;
  document.getElementById("weekend-minutes").value =
    screenTime.weekend_minutes ?? 120;
  document.getElementById("idle-timeout").value =
    screenTime.idle_timeout_sec ?? 300;
  document.getElementById("grace-period").value =
    screenTime.grace_period_sec ?? 60;
  document.getElementById("policy-version").textContent = `v${policy.version}`;
  renderSchedule(policyState.payload.weekly_schedule);
}

function readNumber(id, min, max, label) {
  const value = Number(document.getElementById(id).value);
  if (!Number.isFinite(value) || value < min || value > max) {
    throw new Error(`${label} phải nằm trong khoảng ${min}–${max}.`);
  }
  return Math.round(value);
}

function policyFromForm() {
  if (!policyState) throw new Error("Policy chưa được tải.");
  const currentScreenTime = policyState.payload.screen_time || {};
  return {
    payload: {
      screen_time: {
        weekday_minutes: readNumber(
          "weekday-minutes",
          1,
          1440,
          "Giới hạn ngày thường",
        ),
        weekend_minutes: readNumber(
          "weekend-minutes",
          1,
          1440,
          "Giới hạn cuối tuần",
        ),
        idle_timeout_sec: readNumber("idle-timeout", 60, 3600, "Idle timeout"),
        grace_period_sec: readNumber(
          "grace-period",
          0,
          300,
          "Thời gian ân hạn",
        ),
        warning_minutes: Array.isArray(currentScreenTime.warning_minutes)
          ? currentScreenTime.warning_minutes
          : [10, 5, 1],
      },
      weekly_schedule: policyState.payload.weekly_schedule,
      apps: Array.isArray(policyState.payload.apps)
        ? policyState.payload.apps
        : [],
      domains: Array.isArray(policyState.payload.domains)
        ? policyState.payload.domains
        : [],
    },
  };
}

export function initPoliciesPage() {
  return startLiveRefresh(loadPolicyOverview, renderPolicyOverview, {
    onError: renderPolicyOverviewError,
  });
}

export async function initPolicyDetailPage() {
  const childId = document.body.dataset.childId;
  const encodedId = encodeURIComponent(childId);
  const [child, policy] = await Promise.all([
    apiRequest(`/api/v1/children/${encodedId}`),
    apiRequest(`/api/v1/children/${encodedId}/policy`),
  ]);

  document.getElementById("policy-child-name").textContent = child.display_name;
  document.title = `${child.display_name} · Chính sách · OpenGuard Kids`;
  fillPolicy(policy);

  const save = document.getElementById("save-policy-button");
  save.addEventListener("click", async () => {
    setButtonBusy(save, true, "Đang lưu...");
    try {
      const updated = await apiWrite(
        `/api/v1/children/${encodedId}/policy`,
        "PUT",
        policyFromForm(),
      );
      fillPolicy(updated);
      showToast(`Đã lưu chính sách phiên bản v${updated.version}.`);
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setButtonBusy(save, false);
    }
  });

  document.getElementById("schedule-all").addEventListener("click", () => {
    policyState.payload.weekly_schedule = Array(336).fill(true);
    renderSchedule(policyState.payload.weekly_schedule);
  });
  document.getElementById("schedule-none").addEventListener("click", () => {
    policyState.payload.weekly_schedule = Array(336).fill(false);
    renderSchedule(policyState.payload.weekly_schedule);
  });
}
