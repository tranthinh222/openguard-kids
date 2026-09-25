import { apiRequest } from "./api.js";

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

export async function initChildrenPage() {
	const children = await apiRequest("/api/v1/children");
	const grid = document.getElementById("children-grid");
	grid.replaceChildren();

	if (children.length === 0) {
		const col = document.createElement("div");
		col.className = "col-12";
		const empty = document.createElement("div");
		empty.className = "empty-state card border-0 shadow-sm";
		const icon = document.createElement("i");
		icon.className = "bi bi-people";
		const text = document.createElement("p");
		text.textContent = "Chưa có hồ sơ trẻ em.";
		const link = document.createElement("a");
		link.className = "btn btn-primary";
		link.href = "/children/new";
		link.textContent = "Tạo hồ sơ đầu tiên";
		empty.append(icon, text, link);
		col.append(empty);
		grid.append(col);
		return;
	}

	children.forEach((child) => grid.append(childCard(child)));
}
