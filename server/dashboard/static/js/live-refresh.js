// One request at a time; server-calculated online state is authoritative.
export function startLiveRefresh(load, render, { intervalMs = 5000, timeoutMs = 10000 } = {}) {
	const status = document.getElementById("live-refresh-status");
	let timer;
	let controller;
	let stopped = false;
	let suspended = false;
	let failures = 0;
	let previous;
	let refreshOnCompletion = false;

	function describe(message, stale = false) {
		if (!status) return;
		status.className = `live-refresh-status${stale ? " is-stale" : ""}`;
		if (status.textContent !== message) status.textContent = message;
	}

	async function refresh() {
		clearTimeout(timer);
		if (stopped || suspended || document.hidden) return;
		if (controller) {
			refreshOnCompletion = true;
			return;
		}
		const request = new AbortController();
		controller = request;
		let timedOut = false;
		const timeout = setTimeout(() => {
			timedOut = true;
			request.abort();
		}, timeoutMs);
		try {
			const data = await load(request.signal);
			if (stopped || suspended || document.hidden || request.signal.aborted) return;
			const snapshot = JSON.stringify(data);
			if (snapshot !== previous) {
				render(data);
				previous = snapshot;
			}
			failures = 0;
			describe("Tự động cập nhật · Vừa đồng bộ");
		} catch (error) {
			if (stopped || suspended || document.hidden || (request.signal.aborted && !timedOut)) return;
			if ([401, 403, 404].includes(error.status)) {
				describe("Không thể tiếp tục cập nhật. Vui lòng tải lại trang hoặc đăng nhập lại.", true);
				stop();
				return;
			}
			failures += 1;
			describe("Chưa cập nhật được dữ liệu. Đang tự kết nối lại…", true);
		} finally {
			clearTimeout(timeout);
			controller = null;
			if (!stopped && !suspended && !document.hidden) {
				const delay = refreshOnCompletion ? 0 : Math.min(intervalMs * 2 ** Math.min(failures, 3), 30000);
				refreshOnCompletion = false;
				timer = setTimeout(refresh, delay);
			}
		}
	}

	function pause() {
		refreshOnCompletion = false;
		clearTimeout(timer);
		controller?.abort();
	}
	function visibilityChanged() {
		if (document.hidden) pause();
		else refresh();
	}
	function pageHidden() {
		suspended = true;
		pause();
	}
	function pageShown() {
		if (!suspended) return;
		suspended = false;
		refresh();
	}
	function stop() {
		stopped = true;
		pause();
		document.removeEventListener("visibilitychange", visibilityChanged);
		window.removeEventListener("online", refresh);
		window.removeEventListener("pagehide", pageHidden);
		window.removeEventListener("pageshow", pageShown);
	}
	document.addEventListener("visibilitychange", visibilityChanged);
	window.addEventListener("online", refresh);
	window.addEventListener("pagehide", pageHidden);
	window.addEventListener("pageshow", pageShown);
	describe("Đang cập nhật dữ liệu…");
	refresh();
	return stop;
}
