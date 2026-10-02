import { apiRequest, apiWrite, formatDateTime } from "./api.js";
import { setButtonBusy, showToast } from "./common.js";
import { startLiveRefresh } from "./live-refresh.js";

let allRequests = [];
let allChildren = [];

function statusMeta(status) {
  if (status === "approved")
    return ["Đã duyệt", "text-bg-success-subtle text-success-emphasis"];
  if (status === "rejected")
    return ["Đã từ chối", "text-bg-secondary-subtle text-secondary-emphasis"];
  return ["Đang chờ", "text-bg-warning-subtle text-warning-emphasis"];
}

function requestCard(item) {
  const card = document.createElement("article");
  card.className = "card border-0 shadow-sm request-overview-card";
  const body = document.createElement("div");
  body.className =
    "card-body p-4 d-flex flex-wrap justify-content-between align-items-center gap-3";

  const left = document.createElement("div");
  const header = document.createElement("div");
  header.className = "d-flex flex-wrap align-items-center gap-2 mb-1";
  const title = document.createElement("h2");
  title.className = "h6 mb-0";
  title.textContent = item.child_name;
  const [label, badgeClass] = statusMeta(item.status);
  const badge = document.createElement("span");
  badge.className = `badge ${badgeClass}`;
  badge.textContent = label;
  header.append(title, badge);

  const desc = document.createElement("div");
  desc.className = "mb-1";
  desc.textContent = `Xin thêm ${item.requested_minutes} phút`;
  const meta = document.createElement("div");
  meta.className = "small text-secondary";
  meta.textContent = formatDateTime(item.created_at);
  left.append(header, desc, meta);
  if (item.parent_response) {
    const response = document.createElement("div");
    response.className = "small mt-2";
    response.textContent = `Phản hồi: ${item.parent_response}`;
    left.append(response);
  }

  const actions = document.createElement("div");
  actions.className = "d-flex flex-wrap gap-2";
  const profile = document.createElement("a");
  profile.className = "btn btn-sm btn-outline-secondary";
  profile.href = `/children/${encodeURIComponent(item.child_id)}`;
  profile.textContent = "Xem hồ sơ";
  actions.append(profile);

  if (item.status === "pending") {
    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "btn btn-sm btn-primary";
    approve.textContent = "Duyệt";
    approve.addEventListener("click", async () => {
      setButtonBusy(approve, true, "Đang duyệt...");
      try {
        await apiWrite(
          `/api/v1/children/${encodeURIComponent(item.child_id)}/requests/${encodeURIComponent(item.id)}/approve`,
          "POST",
          {},
        );
        showToast(
          `Đã duyệt thêm ${item.requested_minutes} phút cho ${item.child_name}.`,
        );
      } catch (error) {
        showToast(error.message, true);
      } finally {
        setButtonBusy(approve, false);
      }
    });

    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = "btn btn-sm btn-outline-secondary";
    reject.textContent = "Từ chối";
    reject.addEventListener("click", async () => {
      setButtonBusy(reject, true, "Đang xử lý...");
      try {
        await apiWrite(
          `/api/v1/children/${encodeURIComponent(item.child_id)}/requests/${encodeURIComponent(item.id)}/reject`,
          "POST",
          {},
        );
        showToast(`Đã từ chối yêu cầu của ${item.child_name}.`);
      } catch (error) {
        showToast(error.message, true);
      } finally {
        setButtonBusy(reject, false);
      }
    });
    actions.prepend(approve, reject);
  }

  body.append(left, actions);
  card.append(body);
  return card;
}

function selectedChild() {
  return document.getElementById("request-child-filter").value;
}

function selectedStatus() {
  return document.getElementById("request-status-filter").value;
}

function renderFiltered() {
  const host = document.getElementById("requests-list");
  host.replaceChildren();
  const childId = selectedChild();
  const status = selectedStatus();
  const filtered = allRequests.filter(
    (item) =>
      (!childId || item.child_id === childId) &&
      (!status || item.status === status),
  );

  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state card border-0 shadow-sm";
    const icon = document.createElement("i");
    icon.className = "bi bi-chat-square-heart";
    const text = document.createElement("p");
    text.textContent =
      allRequests.length === 0
        ? "Chưa có yêu cầu nào. Yêu cầu sẽ xuất hiện khi Agent/Tray của trẻ gửi yêu cầu xin thêm thời gian."
        : "Không có yêu cầu phù hợp với bộ lọc hiện tại.";
    empty.append(icon, text);
    host.append(empty);
    return;
  }

  filtered.forEach((item) => host.append(requestCard(item)));
}

function syncChildFilter() {
  const select = document.getElementById("request-child-filter");
  const desired =
    new URLSearchParams(window.location.search).get("child_id") || select.value;
  const existing = new Map(
    Array.from(select.options).map((option) => [option.value, option]),
  );
  allChildren.forEach((child) => {
    if (!existing.has(child.id)) {
      const option = document.createElement("option");
      option.value = child.id;
      option.textContent = child.display_name;
      select.append(option);
    }
  });
  if (desired && allChildren.some((child) => child.id === desired))
    select.value = desired;
}

async function loadRequests(signal) {
  const children = await apiRequest("/api/v1/children", {
    signal,
    cache: "no-store",
  });
  const groups = await Promise.all(
    children.map(async (child) => {
      const requests = await apiRequest(
        `/api/v1/children/${encodeURIComponent(child.id)}/requests`,
        { signal, cache: "no-store" },
      );
      return requests.map((request) => ({
        ...request,
        child_name: child.display_name,
      }));
    }),
  );
  return {
    children,
    requests: groups.flat().sort((a, b) => {
      if (a.status === "pending" && b.status !== "pending") return -1;
      if (a.status !== "pending" && b.status === "pending") return 1;
      return (
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
    }),
  };
}

function renderRequestsError(error) {
  const host = document.getElementById("requests-list");
  host.replaceChildren();
  const alert = document.createElement("div");
  alert.className = "alert alert-danger mb-0";
  const title = document.createElement("strong");
  title.textContent = "Không tải được danh sách yêu cầu.";
  const detail = document.createElement("div");
  detail.className = "small mt-1";
  detail.textContent =
    error?.message || "Vui lòng kiểm tra Server API rồi tải lại trang.";
  alert.append(title, detail);
  host.append(alert);
}

function renderRequests(payload) {
  allChildren = payload.children;
  allRequests = payload.requests;
  syncChildFilter();
  renderFiltered();
}

export function initRequestsPage() {
  document
    .getElementById("request-child-filter")
    .addEventListener("change", renderFiltered);
  document
    .getElementById("request-status-filter")
    .addEventListener("change", renderFiltered);
  return startLiveRefresh(loadRequests, renderRequests, {
    onError: renderRequestsError,
  });
}
