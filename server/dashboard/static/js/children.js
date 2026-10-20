import { apiRequest } from "./api.js";
import { startLiveRefresh } from "./live-refresh.js";

function emptyState(iconClass, message, linkLabel = null, linkHref = null) {
  const col = document.createElement("div");
  col.className = "col-12";
  const empty = document.createElement("div");
  empty.className = "empty-state card border-0 shadow-sm";
  const icon = document.createElement("i");
  icon.className = iconClass;
  const text = document.createElement("p");
  text.textContent = message;
  empty.append(icon, text);
  if (linkLabel && linkHref) {
    const link = document.createElement("a");
    link.className = "btn btn-primary";
    link.href = linkHref;
    link.textContent = linkLabel;
    empty.append(link);
  }
  col.append(empty);
  return col;
}

function childCard(item) {
  const column = document.createElement("div");
  column.className = "col-12 col-md-6 col-xl-4";

  const card = document.createElement("div");
  card.className = "card border-0 shadow-sm h-100";
  const body = document.createElement("div");
  body.className = "card-body p-4";

  const header = document.createElement("div");
  header.className = "d-flex align-items-start justify-content-between gap-3";
  const text = document.createElement("div");
  const title = document.createElement("h2");
  title.className = "h5 mb-1";
  title.textContent = item.display_name;
  const birth = document.createElement("p");
  birth.className = "text-secondary small mb-3";
  birth.textContent = item.birth_year
    ? `Năm sinh ${item.birth_year}`
    : "Chưa nhập năm sinh";
  text.append(title, birth);

  const avatar = document.createElement("div");
  avatar.className = "avatar-circle";
  const icon = document.createElement("i");
  icon.className = "bi bi-person";
  avatar.append(icon);
  header.append(text, avatar);

  const stats = document.createElement("div");
  stats.className = "d-flex gap-3 small mb-4";
  const devices = document.createElement("span");
  devices.textContent = `${item.device_count} thiết bị`;
  const online = document.createElement("span");
  online.className = "text-success";
  online.textContent = `${item.online_count} online`;
  stats.append(devices, online);

  const link = document.createElement("a");
  link.className = "btn btn-outline-primary w-100";
  link.href = `/children/${encodeURIComponent(item.id)}`;
  link.textContent = "Xem chi tiết";

  body.append(header, stats, link);
  card.append(body);
  column.append(card);
  return column;
}

function renderChildren(children) {
  const focusedHref = document.activeElement
    ?.closest("#children-grid a")
    ?.getAttribute("href");
  const grid = document.getElementById("children-grid");
  grid.replaceChildren();

  if (children.length === 0) {
    grid.append(
      emptyState(
        "bi bi-people",
        "Chưa có hồ sơ trẻ em.",
        "Tạo hồ sơ đầu tiên",
        "/children/new",
      ),
    );
    return;
  }

  children.forEach((child) => grid.append(childCard(child)));
  if (focusedHref) {
    Array.from(grid.querySelectorAll("a"))
      .find((link) => link.getAttribute("href") === focusedHref)
      ?.focus({ preventScroll: true });
  }
}

export function initChildrenPage() {
  return startLiveRefresh(
    (signal) => apiRequest("/api/v1/children", { signal, cache: "no-store" }),
    renderChildren,
  );
}
