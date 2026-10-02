import { apiRequest, apiWrite, formatDateTime } from "./api.js";
import { startLiveRefresh } from "./live-refresh.js";
import { setButtonBusy, statusBadge, showToast } from "./common.js";

let enrollmentInterval;

function formatUsage(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours} giờ ${minutes} phút`;
  return `${minutes} phút`;
}

function commandMessage(type, status) {
  const queued = status === "pending";
  if (type === "ADD_TIME")
    return queued ? "Đã xếp hàng lệnh thêm 15 phút." : "Đã gửi thêm 15 phút.";
  if (type === "LOCK_NOW")
    return queued
      ? "Đã xếp hàng lệnh khóa thiết bị."
      : "Đã gửi lệnh khóa thiết bị.";
  return queued
    ? "Đã xếp hàng lệnh cho phép sử dụng lại."
    : "Đã gửi lệnh cho phép sử dụng lại.";
}

async function sendCommand(deviceId, type, minutes = undefined, button = null) {
  if (button) setButtonBusy(button, true, "Đang gửi...");
  try {
    const payload = { type };
    if (minutes !== undefined) payload.minutes = minutes;
    const command = await apiWrite(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/commands`,
      "POST",
      payload,
    );
    showToast(commandMessage(type, command.status));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button) setButtonBusy(button, false);
  }
}

function renderDevices(devices) {
  const container = document.getElementById("child-devices");
  container.replaceChildren();
  if (devices.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const icon = document.createElement("i");
    icon.className = "bi bi-laptop";
    const text = document.createElement("p");
    text.textContent = "Chưa có thiết bị nào được ghép đôi cho hồ sơ này.";
    empty.append(icon, text);
    container.append(empty);
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "table-responsive";
  const table = document.createElement("table");
  table.className = "table align-middle mb-0";
  table.innerHTML =
    '<thead><tr><th>Tên</th><th>Trạng thái</th><th>Heartbeat cuối</th><th>Chính sách trên agent</th><th>Đã dùng</th><th class="text-end">Thao tác</th></tr></thead>';
  const tbody = document.createElement("tbody");

  devices.forEach((device) => {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.className = "fw-medium";
    name.textContent = device.device_name;
    const status = document.createElement("td");
    status.append(statusBadge(device.online));
    const heartbeat = document.createElement("td");
    heartbeat.textContent = formatDateTime(device.last_seen_at);
    const policy = document.createElement("td");
    policy.textContent = `v${device.current_policy_version}`;
    const usage = document.createElement("td");
    usage.textContent = formatUsage(device.quota_used_sec);

    const actionsCell = document.createElement("td");
    actionsCell.className = "text-end";
    const actions = document.createElement("div");
    actions.className =
      "device-action-group d-inline-flex flex-wrap justify-content-end gap-1";

    const lockButton = document.createElement("button");
    lockButton.type = "button";
    lockButton.className = "btn btn-sm btn-outline-danger";
    lockButton.innerHTML = '<i class="bi bi-lock me-1"></i>Khóa';
    lockButton.addEventListener("click", () =>
      sendCommand(device.id, "LOCK_NOW", undefined, lockButton),
    );

    const unlockButton = document.createElement("button");
    unlockButton.type = "button";
    unlockButton.className = "btn btn-sm btn-outline-secondary";
    unlockButton.innerHTML = '<i class="bi bi-unlock me-1"></i>Cho phép';
    unlockButton.addEventListener("click", () =>
      sendCommand(device.id, "UNLOCK", undefined, unlockButton),
    );

    const addButton = document.createElement("button");
    addButton.type = "button";
    addButton.className = "btn btn-sm btn-outline-primary";
    addButton.innerHTML = '<i class="bi bi-plus-circle me-1"></i>15 phút';
    addButton.addEventListener("click", () =>
      sendCommand(device.id, "ADD_TIME", 15, addButton),
    );

    actions.append(lockButton, unlockButton, addButton);
    actionsCell.append(actions);
    tr.append(name, status, heartbeat, policy, usage, actionsCell);
    tbody.append(tr);
  });

  table.append(tbody);
  wrapper.append(table);
  container.append(wrapper);
}

async function copyEnrollmentCode(code) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(code);
    return;
  }
  const previousFocus = document.activeElement;
  const field = document.createElement("textarea");
  field.value = code;
  field.readOnly = true;
  field.className = "clipboard-fallback";
  document.body.append(field);
  try {
    field.select();
    field.setSelectionRange(0, code.length);
    if (!document.execCommand("copy")) throw new Error("Clipboard unavailable");
  } finally {
    field.remove();
    previousFocus?.focus({ preventScroll: true });
  }
}

function renderEnrollment(code, expiresAt) {
  clearInterval(enrollmentInterval);
  const panel = document.getElementById("enrollment-panel");
  panel.replaceChildren();
  panel.className = "mt-3";
  const expiry = new Date(expiresAt).getTime();

  const box = document.createElement("div");
  box.className = "enrollment-code-panel";
  const label = document.createElement("div");
  label.className = "small text-secondary mb-1";
  label.textContent = "Mã ghép đôi";
  const codeEl = document.createElement("div");
  codeEl.className = "enrollment-code";
  codeEl.textContent = code;
  const codeRow = document.createElement("div");
  codeRow.className = "enrollment-code-row";
  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "btn btn-outline-primary enrollment-copy";
  copyButton.setAttribute("aria-label", "Sao chép mã ghép đôi");
  copyButton.title = "Sao chép mã ghép đôi";
  copyButton.innerHTML = '<i class="bi bi-copy" aria-hidden="true"></i>';
  copyButton.addEventListener("click", async () => {
    copyButton.disabled = true;
    try {
      await copyEnrollmentCode(code);
      showToast(
        "Đã sao chép mã ghép đôi. Bạn có thể dán mã trên thiết bị của trẻ.",
      );
    } catch {
      showToast(
        "Không thể sao chép tự động. Bạn có thể chọn mã và sao chép thủ công.",
        true,
      );
    } finally {
      copyButton.disabled = Date.now() >= expiry;
    }
  });
  codeRow.append(codeEl, copyButton);

  const countdown = document.createElement("div");
  countdown.className = "small mt-2";
  countdown.textContent = "Hết hạn sau ";
  const timer = document.createElement("strong");
  countdown.append(timer);
  box.append(label, codeRow, countdown);
  panel.append(box);

  const tick = () => {
    const remaining = expiry - Date.now();
    if (remaining <= 0) {
      timer.textContent = "00:00";
      box.classList.add("opacity-50");
      copyButton.disabled = true;
      copyButton.title = "Mã ghép đôi đã hết hạn";
      clearInterval(enrollmentInterval);
      return;
    }
    const total = Math.ceil(remaining / 1000);
    timer.textContent = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  };
  enrollmentInterval = setInterval(tick, 1000);
  tick();
}

function renderEnrollmentResult(state) {
  clearInterval(enrollmentInterval);
  const panel = document.getElementById("enrollment-panel");
  panel.replaceChildren();
  panel.className = "mt-3";
  const notice = document.createElement("div");
  notice.className = `enrollment-result alert ${state === "used" ? "alert-success" : "alert-warning"} mb-0`;
  notice.setAttribute("role", "status");
  const title = document.createElement("strong");
  title.textContent =
    state === "used" ? "Ghép đôi thành công!" : "Mã ghép đôi đã hết hạn.";
  const description = document.createElement("p");
  description.className = "small mt-2 mb-0";
  description.textContent =
    state === "used"
      ? "Thiết bị đã được liên kết với trẻ. Bạn có thể tạo mã mới để ghép thêm thiết bị."
      : "Hãy tạo mã mới để tiếp tục ghép thiết bị.";
  notice.append(title, description);
  panel.append(notice);
}

export async function initChildDetailPage() {
  const childId = document.body.dataset.childId;
  const encodedId = encodeURIComponent(childId);
  let activeEnrollmentId = null;
  let previousDevices;

  const [child, policy] = await Promise.all([
    apiRequest(`/api/v1/children/${encodedId}`),
    apiRequest(`/api/v1/children/${encodedId}/policy`),
  ]);

  document.getElementById("child-name").textContent = child.display_name;
  document.getElementById("policy-version").textContent = `v${policy.version}`;
  document.title = `${child.display_name} · OpenGuard Kids`;

  startLiveRefresh(
    async (signal) => {
      const enrollmentId = activeEnrollmentId;
      const options = { signal, cache: "no-store" };
      const [devices, enrollment] = await Promise.all([
        apiRequest(`/api/v1/children/${encodedId}/devices`, options),
        enrollmentId
          ? apiRequest(
              `/api/v1/children/${encodedId}/enrollment/${encodeURIComponent(enrollmentId)}`,
              options,
            )
          : Promise.resolve(null),
      ]);
      return { devices, enrollment };
    },
    ({ devices, enrollment }) => {
      const snapshot = JSON.stringify(devices);
      if (snapshot !== previousDevices) {
        renderDevices(devices);
        previousDevices = snapshot;
      }
      if (
        enrollment?.enrollment_id === activeEnrollmentId &&
        ["used", "expired"].includes(enrollment.status)
      ) {
        activeEnrollmentId = null;
        renderEnrollmentResult(enrollment.status);
      }
    },
  );

  const button = document.getElementById("create-enrollment-button");
  button.addEventListener("click", async () => {
    setButtonBusy(button, true, "Đang tạo mã...");
    try {
      const enrollment = await apiWrite(
        `/api/v1/children/${encodedId}/enrollment`,
        "POST",
      );
      activeEnrollmentId = enrollment.enrollment_id;
      renderEnrollment(enrollment.code, enrollment.expires_at);
    } catch (error) {
      activeEnrollmentId = null;
      clearInterval(enrollmentInterval);
      const panel = document.getElementById("enrollment-panel");
      panel.textContent = error.message;
      panel.className = "mt-3 alert alert-danger";
    } finally {
      setButtonBusy(button, false);
    }
  });
}
