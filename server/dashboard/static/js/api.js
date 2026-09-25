let cachedSession = null;

export async function getSession(force = false) {
	if (cachedSession && !force) return cachedSession;

	const response = await fetch("/api/v1/auth/session", {
		method: "GET",
		credentials: "same-origin",
		headers: { Accept: "application/json" },
	});

	if (response.status === 401) {
		cachedSession = null;
		return null;
	}

	if (!response.ok) {
		throw await apiError(response);
	}

	cachedSession = await response.json();
	return cachedSession;
}

export function clearSessionCache() {
	cachedSession = null;
}

export async function apiRequest(url, options = {}) {
	const response = await fetch(url, {
		credentials: "same-origin",
		...options,
		headers: {
			Accept: "application/json",
			...(options.headers || {}),
		},
	});

	if (response.status === 401) {
		clearSessionCache();
		window.location.href = "/login";
		throw new Error("Authentication required");
	}

	if (!response.ok) {
		throw await apiError(response);
	}

	if (response.status === 204) return null;
	return response.json();
}

export async function apiWrite(url, method, payload = undefined) {
	const session = await getSession();
	if (!session) {
		window.location.href = "/login";
		throw new Error("Authentication required");
	}

	const headers = {
		"X-CSRF-Token": session.csrf_token,
	};

	const options = { method, headers };
	if (payload !== undefined) {
		headers["Content-Type"] = "application/json";
		options.body = JSON.stringify(payload);
	}

	return apiRequest(url, options);
}

export async function apiError(response) {
	let message = `HTTP ${response.status}`;
	try {
		const body = await response.json();
		if (typeof body.detail === "string") {
			message = body.detail;
		} else if (Array.isArray(body.detail)) {
			message = body.detail
				.map((item) => item.msg || "Dữ liệu không hợp lệ")
				.join("; ");
		}
	} catch (_) {
		// Keep the HTTP fallback message.
	}
	const error = new Error(message);
	error.status = response.status;
	return error;
}

export function formatDateTime(value) {
	if (!value) return "Chưa có";
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return "Không xác định";
	return new Intl.DateTimeFormat("vi-VN", {
		day: "2-digit",
		month: "2-digit",
		year: "numeric",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	}).format(date);
}
