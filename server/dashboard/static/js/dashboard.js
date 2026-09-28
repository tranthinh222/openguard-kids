import { apiRequest, formatDateTime } from "./api.js";
import { statusBadge } from "./common.js";
import { startLiveRefresh } from "./live-refresh.js";

export function initDashboardPage() {
	return startLiveRefresh(
		(signal) => apiRequest("/api/v1/dashboard/summary", { signal, cache: "no-store" }),
		renderSummary,
	);
}

function renderSummary(summary) {
	document.getElementById("children-count").textContent =
		summary.children_count;
	document.getElementById("device-count").textContent = summary.device_count;
	document.getElementById("online-count").textContent = summary.online_count;
	document.getElementById("offline-count").textContent =
		summary.offline_count;

	const container = document.getElementById("recent-devices");
	container.replaceChildren();

	if (summary.recent_devices.length === 0) {
		const empty = document.createElement("div");
		empty.className = "empty-state";
		const icon = document.createElement("i");
		icon.className = "bi bi-laptop";
		const text = document.createElement("p");
		text.textContent = "Chưa có thiết bị nào được ghép đôi.";
		empty.append(icon, text);
		container.append(empty);
		return;
	}

	const wrapper = document.createElement("div");
	wrapper.className = "table-responsive";
	const table = document.createElement("table");
	table.className = "table align-middle mb-0";
	table.innerHTML =
		"<thead><tr><th>Thiết bị</th><th>Trẻ</th><th>Trạng thái</th><th>Heartbeat cuối</th><th>Policy</th></tr></thead>";
	const tbody = document.createElement("tbody");

	for (const device of summary.recent_devices) {
		const tr = document.createElement("tr");

		const name = document.createElement("td");
		name.className = "fw-medium";
		name.textContent = device.device_name;

		const child = document.createElement("td");
		const childLink = document.createElement("a");
		childLink.href = `/children/${encodeURIComponent(device.child_id)}`;
		childLink.textContent = device.child_name;
		childLink.className = "text-decoration-none";
		child.append(childLink);

		const status = document.createElement("td");
		status.append(statusBadge(device.online));

		const heartbeat = document.createElement("td");
		heartbeat.textContent = formatDateTime(device.last_seen_at);

		const policy = document.createElement("td");
		policy.textContent = `v${device.current_policy_version}`;

		tr.append(name, child, status, heartbeat, policy);
		tbody.append(tr);
	}

	table.append(tbody);
	wrapper.append(table);
	container.append(wrapper);
}
