import { apiError, getSession } from "./api.js";
import { setButtonBusy } from "./common.js";
import { initPasswordToggles, authErrorMessage } from "./auth-ui.js";

export function passwordChecks(value) {
    return {
        length: value.length >= 10 && value.length <= 128,
        uppercase: /[A-Z]/.test(value),
        digit: /[0-9]/.test(value),
        special: /[\x21-\x2F\x3A-\x40\x5B-\x60\x7B-\x7E]/.test(value),
        ascii: /^[\x21-\x7E]+$/.test(value),
    };
}

export async function initRegisterPage() {
    initPasswordToggles();
    if (await getSession(true)) {
        window.location.replace("/dashboard");
        return;
    }
    const form = document.getElementById("register-form");
    const password = document.getElementById("password");
    const confirmation = document.getElementById("confirm-password");
    const match = document.getElementById("password-match");
    const button = document.getElementById("register-button");
    const errorBox = document.getElementById("register-error");
    let submitting = false;

    const validate = () => {
        const checks = passwordChecks(password.value);
        document.querySelectorAll("[data-rule]").forEach((item) => {
            const valid = checks[item.dataset.rule];
            item.classList.toggle("is-valid", valid);
            item.firstElementChild.textContent = valid ? "✓" : "○";
        });
        password.setCustomValidity(Object.values(checks).every(Boolean) ? "" : "Mật khẩu cần thỏa mãn tất cả điều kiện bên dưới.");
        const mismatch = confirmation.value !== password.value;
        confirmation.setCustomValidity(mismatch ? "Mật khẩu xác nhận chưa khớp." : "");
        match.textContent = confirmation.value ? (mismatch ? "Mật khẩu xác nhận chưa khớp." : "Mật khẩu đã khớp.") : "";
        match.classList.toggle("matched", !mismatch);
    };
    password.addEventListener("input", validate);
    confirmation.addEventListener("input", validate);
    // Validate autofilled values before the browser's native submit validation.
    button.addEventListener("click", validate);
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (submitting) return;
        validate();
        if (!form.reportValidity()) return;
        errorBox.classList.add("d-none");
        submitting = true;
        setButtonBusy(button, true, "Đang tạo tài khoản...");
        try {
            const response = await fetch("/api/v1/auth/register", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({ email: document.getElementById("email").value.trim(), password: password.value }),
            });
            if (!response.ok) throw await apiError(response);
            window.location.replace("/login?registered=1");
        } catch (error) {
            errorBox.textContent = authErrorMessage(error);
            errorBox.classList.remove("d-none");
            errorBox.focus();
        } finally {
            submitting = false;
            setButtonBusy(button, false);
        }
    });
}
