export function initPasswordToggles() {
    document.querySelectorAll("[data-toggle-password]").forEach((button) => {
        const input = document.getElementById(button.dataset.togglePassword);
        const originalLabel = button.getAttribute("aria-label");
        button.addEventListener("click", () => {
            const visible = input.type === "password";
            input.type = visible ? "text" : "password";
            button.setAttribute("aria-pressed", String(visible));
            button.setAttribute("aria-label", visible ? originalLabel.replace("Hiện", "Ẩn") : originalLabel);
            button.firstElementChild.className = visible ? "bi bi-eye-slash" : "bi bi-eye";
        });
    });
}

export function authErrorMessage(error) {
    const messages = {
        "Email already registered": "Email này đã được đăng ký. Hãy đăng nhập hoặc dùng email khác.",
        "Invalid email or password": "Email hoặc mật khẩu chưa đúng. Vui lòng thử lại.",
        "Invalid login CSRF token": "Phiên đăng nhập đã hết hạn hoặc thay đổi. Vui lòng tải lại trang.",
        "Account temporarily locked": "Tài khoản đang tạm khóa. Vui lòng thử lại sau.",
        "Account disabled": "Tài khoản đã bị vô hiệu hóa.",
    };
    if (error instanceof TypeError) return "Không thể kết nối đến máy chủ. Kiểm tra kết nối và thử lại.";
    return messages[error.message] || error.message || "Có lỗi xảy ra. Vui lòng thử lại.";
}
