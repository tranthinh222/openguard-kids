import { apiWrite } from "./api.js";
import { setButtonBusy } from "./common.js";

export function initChildCreatePage() {
	const form = document.getElementById("child-create-form");
	const button = document.getElementById("child-create-button");
	const errorBox = document.getElementById("child-create-error");

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		errorBox.classList.add("d-none");

		const displayName = document
			.getElementById("display_name")
			.value.trim();
		const birthYearRaw = document.getElementById("birth_year").value.trim();
		const birthYear = birthYearRaw ? Number(birthYearRaw) : null;

		if (!displayName) {
			errorBox.textContent = "Tên hiển thị không được để trống.";
			errorBox.classList.remove("d-none");
			return;
		}

		setButtonBusy(button, true, "Đang tạo...");
		try {
			const child = await apiWrite("/api/v1/children", "POST", {
				display_name: displayName,
				birth_year: birthYear,
			});
			window.location.href = `/children/${encodeURIComponent(child.id)}`;
		} catch (error) {
			errorBox.textContent = error.message;
			errorBox.classList.remove("d-none");
			setButtonBusy(button, false);
		}
	});
}
