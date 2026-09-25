import { apiError, getSession } from "./api.js";
import { setButtonBusy } from "./common.js";

export async function initLoginPage() {
	const existing = await getSession(true);
	if (existing) {
		window.location.href = "/dashboard";
		return;
	}

	const form = document.getElementById("login-form");
	const button = document.getElementById("login-button");
	const errorBox = document.getElementById("login-error");
	const loginCsrf = document.body.dataset.loginCsrf;

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		errorBox.classList.add("d-none");

		const email = document.getElementById("email").value.trim();
		const password = document.getElementById("password").value;

		if (!email || !password) {
			errorBox.textContent = "Vui lòng nhập email và mật khẩu.";
			errorBox.classList.remove("d-none");
			return;
		}

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
			errorBox.textContent = error.message;
			errorBox.classList.remove("d-none");
			setButtonBusy(button, false);
		}
	});
}
