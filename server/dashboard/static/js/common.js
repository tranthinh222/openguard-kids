import { apiRequest, clearSessionCache, getSession } from "./api.js";

export async function initAuthenticatedShell() {
	const session = await getSession();
	if (!session) {
		window.location.href = "/login";
		return null;
	}

	const email = document.getElementById("parent-email");
	if (email) email.textContent = session.user.email;

	const logoutButton = document.getElementById("logout-button");
	if (logoutButton) {
		logoutButton.addEventListener("click", async () => {
			logoutButton.disabled = true;
			try {
				await apiRequest("/api/v1/auth/logout", {
					method: "POST",
					headers: { "X-CSRF-Token": session.csrf_token },
				});
				clearSessionCache();
				window.location.href = "/login";
			} catch (error) {
				logoutButton.disabled = false;
				showGlobalError(error.message);
			}
		});
	}

	return session;
}

export function showGlobalError(message) {
	const alert = document.getElementById("global-alert");
	if (!alert) return;
	alert.className = "alert alert-danger";
	alert.textContent = message;
}

export function setButtonBusy(button, busy, busyLabel = "Đang xử lý...") {
	if (!button) return;
	if (busy) {
		button.dataset.originalLabel = button.innerHTML;
		button.disabled = true;
		button.textContent = busyLabel;
	} else {
		button.disabled = false;
		if (button.dataset.originalLabel)
			button.innerHTML = button.dataset.originalLabel;
	}
}

export function statusBadge(online) {
	const badge = document.createElement("span");
	badge.className = online
		? "badge text-bg-success-subtle text-success-emphasis"
		: "badge text-bg-secondary-subtle text-secondary-emphasis";
	badge.textContent = online ? "Online" : "Offline";
	return badge;
}
