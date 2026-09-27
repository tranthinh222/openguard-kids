import { apiError, getSession } from "./api.js";
import { setButtonBusy } from "./common.js";

import { initPasswordToggles, authErrorMessage } from "./auth-ui.js";

export async function initLoginPage() {
    initPasswordToggles();
    if (new URLSearchParams(window.location.search).get("registered") === "1") {
        document.getElementById("login-success").classList.remove("d-none");
        window.history.replaceState(null, "", "/login");
    }
	const existing = await getSession(true);
	if (existing) {
		window.location.href = "/dashboard";
		return;
	}

	const form = document.getElementById("login-form");
	const button = document.getElementById("login-button");
	const errorBox = document.getElementById("login-error");
	const loginCsrf = document.body.dataset.loginCsrf;
	let submitting = false;

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		if (submitting || !form.reportValidity()) return;
		errorBox.classList.add("d-none");

		const email = document.getElementById("email").value.trim();
		const password = document.getElementById("password").value;

		if (!email || !password) {
			errorBox.textContent = "Vui lòng nhập email và mật khẩu.";
			errorBox.classList.remove("d-none");
			return;
		}

		submitting = true;
		setButtonBusy(button, true, "Đang đăng nhập...");
		try {
			const response = await fetch("/api/v1/auth/login", {
				method: "POST",
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/json",
					Accept: "application/json",
					"X-CSRF-Token": loginCsrf,
				},
				body: JSON.stringify({ email, password }),
			});

			if (!response.ok) throw await apiError(response);
			await response.json();
			window.location.href = "/dashboard";
		} catch (error) {
			errorBox.textContent = authErrorMessage(error);
			errorBox.classList.remove("d-none");
			errorBox.focus();
			submitting = false;
			setButtonBusy(button, false);
		}
	});
}
