"""Tkinter interface for pairing and running OpenGuard Kids Agent.

The window has two states, following the pairing flow of family-safety apps:
an "enter the code" screen before pairing and a simple "this device is
protected" status screen afterwards. Colours match the parent dashboard.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable

from gui_controller import (
    AgentController,
    HeartbeatWorker,
    describe_error,
    format_sync_time,
    is_network_error,
    needs_reenroll,
    normalize_enrollment_code,
    normalize_server_url,
)
from openguard_agent import AGENT_VERSION, device_name

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "logo.png"
CODE_LENGTH = 8
CODE_EXPIRE_MINUTES = 10
WRAP = 360

# Same family-first palette as server/dashboard/static/css/app.css.
BG = "#f6f8f5"
SURFACE = "#ffffff"
BORDER = "#e4eae3"
INPUT_BORDER = "#d5dfd8"
GREEN = "#22634d"
GREEN_DARK = "#174d3b"
GREEN_DISABLED = "#537869"
GREEN_SOFT = "#e9f2ec"
GREEN_PANEL = "#eff6ef"
GREEN_PANEL_BORDER = "#c9ddcc"
INK = "#203b32"
MUTED = "#607268"
FOCUS = "#b27d27"
AMBER = "#c98a1e"
AMBER_SOFT = "#fbf1dc"
RED = "#b3452c"
RED_SOFT = "#fbe9e4"
GREY = "#8a9a90"
GREY_SOFT = "#edf1e9"

STEPS = ("Nhập mã", "Kết nối", "Ghép", "Bảo vệ")


# Pixel scale factor. Fonts are sized in points and follow the display DPI, but
# Tk pixel sizes do not (e.g. XWayland with Xft.dpi=192 renders fonts at 2x), so
# every padding, wrap width and canvas size goes through px().
SCALE = 1.0


def px(value: float) -> int:
    return round(value * SCALE)


def detect_scale(root: tk.Misc) -> float:
    # 75pt equals 100px at 96 DPI; the measured ratio is the real font scaling.
    points = tkfont.Font(root, family="TkDefaultFont", size=75).measure("MMMM")
    pixels = tkfont.Font(root, family="TkDefaultFont", size=-100).measure("MMMM")
    return max(1.0, round(points / pixels * 4) / 4) if pixels else 1.0


def pick_font(root: tk.Misc, *families: str) -> str:
    available = set(tkfont.families(root))
    return next((name for name in families if name in available), "TkDefaultFont")


class FlatButton(tk.Label):
    """Label-based button so colours look the same on Windows, Linux and macOS.

    It takes keyboard focus, shows the dashboard's amber focus ring and runs on
    Enter or Space, so the whole window works without a mouse.
    """

    VARIANTS = {
        "primary": (GREEN, "#ffffff", GREEN_DARK, GREEN),
        "secondary": (SURFACE, GREEN, GREEN_SOFT, INPUT_BORDER),
        "link": (None, GREEN, None, None),
    }

    def __init__(self, master: tk.Misc, text: str, command: Callable[[], None], font, variant: str = "primary", **kw):
        self.command = command
        self.enabled = True
        parent_bg = master.cget("bg")
        bg, fg, hover, border = self.VARIANTS[variant]
        self.colors = (bg or parent_bg, fg, hover or parent_bg, border or parent_bg)
        self.variant = variant
        pad = {"padx": px(4), "pady": px(2)} if variant == "link" else {"padx": px(16), "pady": px(10)}
        super().__init__(
            master, text=text, font=font, bg=self.colors[0], fg=fg, cursor="hand2", takefocus=1,
            highlightthickness=px(2) if variant != "link" else px(1), highlightbackground=self.colors[3],
            highlightcolor=FOCUS, **pad, **kw,
        )
        self.bind("<Button-1>", lambda _e: self.invoke())
        self.bind("<Return>", lambda _e: self.invoke())
        self.bind("<space>", lambda _e: self.invoke())
        self.bind("<Enter>", lambda _e: self._hover(True))
        self.bind("<Leave>", lambda _e: self._hover(False))

    def _hover(self, inside: bool) -> None:
        if self.enabled:
            self.configure(bg=self.colors[2] if inside else self.colors[0])

    def invoke(self) -> None:
        if self.enabled:
            self.command()

    def set_enabled(self, enabled: bool, text: str | None = None) -> None:
        self.enabled = enabled
        if text is not None:
            self.configure(text=text)
        if self.variant == "primary":
            self.configure(bg=GREEN if enabled else GREEN_DISABLED, fg="#ffffff" if enabled else "#dfe8e2")
        else:
            self.configure(fg=self.colors[1] if enabled else GREY)
        self.configure(cursor="hand2" if enabled else "arrow")


class Collapsible:
    """A "Cài đặt nâng cao ▸" style toggle that reveals a body frame below it."""

    def __init__(self, master: tk.Misc, title: str, font, on_toggle: Callable[[], None] = lambda: None):
        self.title = title
        self.on_toggle = on_toggle
        self.open = False
        self.button = FlatButton(master, f"{title}  ▸", self.toggle, font, variant="link")
        self.body = tk.Frame(master, bg=master.cget("bg"))

    def pack(self, **kw) -> None:
        self.button.pack(anchor="w", **kw)

    def toggle(self, force: bool | None = None) -> None:
        self.open = (not self.open) if force is None else force
        self.button.configure(text=f"{self.title}  {'▾' if self.open else '▸'}")
        if self.open:
            self.body.pack(fill="x", pady=(px(6), px(0)), after=self.button)
        else:
            self.body.pack_forget()
        self.on_toggle()


class Stepper(tk.Canvas):
    """Onboarding progress: Nhập mã → Kết nối → Ghép → Bảo vệ."""

    def __init__(self, master: tk.Misc, font, width: int = 390):
        self.width = px(width)
        super().__init__(master, width=self.width, height=px(56), bg=master.cget("bg"), highlightthickness=0)
        self.font = font
        self.set_step(0)

    def set_step(self, active: int) -> None:
        self.delete("all")
        gap = self.width / len(STEPS)
        centers = [gap * index + gap / 2 for index in range(len(STEPS))]
        r, cy = px(12), px(15)
        for index in range(len(STEPS) - 1):
            color = GREEN if index < active else INPUT_BORDER
            self.create_line(centers[index] + r + px(4), cy, centers[index + 1] - r - px(4), cy, fill=color, width=px(2))
        for index, (x, label) in enumerate(zip(centers, STEPS)):
            box = (x - r, cy - r, x + r, cy + r)
            if index < active:
                self.create_oval(*box, fill=GREEN, outline=GREEN)
                self.create_text(x, cy, text="✓", fill="#ffffff", font=self.font)
            elif index == active:
                self.create_oval(*box, fill=SURFACE, outline=GREEN, width=px(2))
                self.create_text(x, cy, text=str(index + 1), fill=GREEN, font=self.font)
            else:
                self.create_oval(*box, fill=BG, outline=INPUT_BORDER, width=px(2))
                self.create_text(x, cy, text=str(index + 1), fill=GREY, font=self.font)
            self.create_text(x, px(45), text=label, fill=INK if index <= active else GREY, font=self.font)


class StatusBadge(tk.Canvas):
    """Large friendly status illustration: a coloured circle with a glyph."""

    def __init__(self, master: tk.Misc, font):
        super().__init__(master, width=px(104), height=px(104), bg=master.cget("bg"), highlightthickness=0)
        self.font = font

    def show(self, color: str, soft: str, glyph: str) -> None:
        self.delete("all")
        self.create_oval(px(2), px(2), px(102), px(102), fill=soft, outline="")
        self.create_oval(px(20), px(20), px(84), px(84), fill=color, outline="")
        self.create_text(px(52), px(53), text=glyph, fill="#ffffff", font=self.font)


class AgentWindow:
    def __init__(self, root: tk.Tk):
        global SCALE
        SCALE = detect_scale(root)
        self.root = root
        self.controller = AgentController()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker = HeartbeatWorker(self.controller, self._queue_heartbeat)
        self.server_var = tk.StringVar(value=self.controller.config.server_url)
        self.code_var = tk.StringVar()
        self.connection = "checking"  # checking | ok | offline | rejected | error
        self.connection_error = ""
        self.policy_version: int | None = None
        self.checking = False
        self._banner_job: str | None = None
        self._init_fonts()
        self._build()
        self._show_initial_view()
        root.after(100, self._process_events)
        root.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------ layout

    def _init_fonts(self) -> None:
        sans = pick_font(self.root, "Inter", "Segoe UI", "Noto Sans", "DejaVu Sans", "Helvetica")
        mono = pick_font(self.root, "JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo")
        self.f_brand = (sans, 14, "bold")
        self.f_title = (sans, 17, "bold")
        self.f_heading = (sans, 11, "bold")
        self.f_body = (sans, 10)
        self.f_small = (sans, 9)
        self.f_button = (sans, 11, "bold")
        self.f_code = (mono, 22, "bold")
        self.f_glyph = (sans, 26, "bold")
        self.f_step = (sans, 9, "bold")

    def _build(self) -> None:
        self.root.title("OpenGuard Kids Agent")
        self.root.geometry(f"{px(460)}x{px(640)}")
        self.root.minsize(px(430), px(520))
        self.root.configure(bg=BG)
        self.logo = None
        if LOGO_PATH.exists():
            try:
                image = tk.PhotoImage(file=str(LOGO_PATH))
                self.root.iconphoto(True, image)
                self.logo = image.subsample(max(1, image.width() // px(36)))
            except tk.TclError:
                self.logo = None

        header = tk.Frame(self.root, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=SURFACE, padx=px(22), pady=px(12))
        inner.pack(fill="x")
        if self.logo:
            tk.Label(inner, image=self.logo, bg=SURFACE).pack(side="left", padx=(px(0), px(10)))
        tk.Label(inner, text="OpenGuard", font=self.f_brand, fg=GREEN, bg=SURFACE).pack(side="left")
        tk.Label(inner, text=" Kids", font=(self.f_brand[0], 14), fg=GREEN, bg=SURFACE).pack(side="left")
        self.header_pill = tk.Label(inner, font=self.f_small, padx=px(10), pady=px(3))
        self.header_pill.pack(side="right")

        self.content = tk.Frame(self.root, bg=BG, padx=px(24), pady=px(18))
        self.content.pack(fill="both", expand=True)
        self.pair_view = tk.Frame(self.content, bg=BG)
        self.status_view = tk.Frame(self.content, bg=BG)
        self._build_pair_view(self.pair_view)
        self._build_status_view(self.status_view)

    def _card(self, master: tk.Misc, bg: str = SURFACE, border: str = BORDER, pad: int = 22) -> tk.Frame:
        # The border is the outer frame's background showing around the body, which
        # renders the same on every platform (highlight borders may turn black).
        outer = tk.Frame(master, bg=border, padx=max(1, px(1)), pady=max(1, px(1)))
        body = tk.Frame(outer, bg=bg, padx=px(pad), pady=px(pad - 4))
        body.pack(fill="both", expand=True)
        outer.body = body  # type: ignore[attr-defined]
        return outer

    def _label(self, master: tk.Misc, text: str = "", font=None, fg: str = INK, **kw) -> tk.Label:
        return tk.Label(master, text=text, font=font or self.f_body, fg=fg, bg=master.cget("bg"),
                        justify="left", anchor="w", wraplength=px(kw.pop("wraplength", WRAP)), **kw)

    def _entry(self, master: tk.Misc, variable: tk.StringVar, font, **kw) -> tk.Entry:
        return tk.Entry(
            master, textvariable=variable, font=font, relief="flat", bg=SURFACE, fg=INK,
            insertbackground=INK, disabledbackground=GREY_SOFT, disabledforeground=MUTED,
            highlightthickness=px(2), highlightbackground=INPUT_BORDER, highlightcolor=GREEN, **kw,
        )

    def _build_pair_view(self, view: tk.Frame) -> None:
        self.stepper = Stepper(view, self.f_step)
        self.stepper.pack(pady=(px(0), px(12)))

        card = self._card(view)
        card.pack(fill="x")
        body = card.body  # type: ignore[attr-defined]
        self.back_button = FlatButton(body, "← Quay lại trạng thái", self._back_to_status, self.f_small, variant="link")
        self.pair_title = self._label(body, "Kết nối thiết bị này", self.f_title)
        self.pair_title.pack(anchor="w")
        self._label(body, "Nhập mã đang hiển thị trên trang phụ huynh (Hồ sơ trẻ → Tạo mã ghép đôi).",
                    fg=MUTED).pack(anchor="w", pady=(px(4), px(16)))

        label_row = tk.Frame(body, bg=SURFACE)
        label_row.pack(fill="x")
        code_label = self._label(label_row, "Mã ghép đôi", self.f_heading, wraplength=0)
        code_label.pack(side="left")
        self.counter = self._label(label_row, f"0/{CODE_LENGTH}", self.f_small, fg=MUTED, wraplength=0)
        self.counter.pack(side="right")

        self.code_entry = self._entry(body, self.code_var, self.f_code, justify="center", width=12)
        self.code_entry.pack(fill="x", pady=(px(6), px(6)), ipady=px(8))
        self.code_entry.bind("<Return>", lambda _e: self._enroll())
        code_label.bind("<Button-1>", lambda _e: self.code_entry.focus_set())
        self.code_var.trace_add("write", self._on_code_change)

        self.code_hint = self._label(body, f"{CODE_LENGTH} ký tự gồm chữ và số. Có thể dán cả mã có khoảng trắng.",
                                     self.f_small, fg=MUTED)
        self.code_hint.pack(anchor="w")
        self.code_error = self._label(body, "", self.f_small, fg=RED)

        self.enroll_button = FlatButton(body, "Ghép thiết bị", self._enroll, self.f_button)
        self.enroll_button.pack(fill="x", pady=(px(16), px(10)))
        self._label(body, f"Mã hết hạn sau {CODE_EXPIRE_MINUTES} phút. Nếu hết hạn, hãy tạo mã mới trên trang phụ huynh.",
                    self.f_small, fg=MUTED).pack(anchor="w")

        info = self._card(view, bg=GREEN_PANEL, border=GREEN_PANEL_BORDER, pad=16)
        info.pack(fill="x", pady=(px(14), px(0)))
        info_body = info.body  # type: ignore[attr-defined]
        self._label(info_body, "Sau khi ghép, phụ huynh có thể", self.f_heading).pack(anchor="w")
        for line in ("thấy máy này đang trực tuyến hay không,",
                     "đặt chính sách và giới hạn thời gian sử dụng.",):
            self._label(info_body, f"•  {line}", fg=INK).pack(anchor="w", pady=(px(3), px(0)))
        self._label(info_body, "Agent chỉ gửi tên máy, trạng thái kết nối và thời gian đã dùng.",
                    self.f_small, fg=MUTED).pack(anchor="w", pady=(px(8), px(0)))

        self.advanced = Collapsible(view, "Cài đặt nâng cao", self.f_body, self._fit_window)
        self.advanced.pack(pady=(px(12), px(0)))
        adv = self.advanced.body
        self._label(adv, "Địa chỉ server", self.f_heading).pack(anchor="w")
        self.server_entry = self._entry(adv, self.server_var, self.f_body)
        self.server_entry.pack(fill="x", pady=(px(5), px(4)), ipady=px(6))
        self.server_entry.bind("<Return>", lambda _e: self._enroll())
        self._label(adv, "Chỉ thay đổi khi phụ huynh hoặc quản trị viên yêu cầu.", self.f_small, fg=MUTED).pack(anchor="w")
        self.server_error = self._label(adv, "", self.f_small, fg=RED)

    def _build_status_view(self, view: tk.Frame) -> None:
        card = self._card(view)
        card.pack(fill="x")
        body = card.body  # type: ignore[attr-defined]
        self.badge = StatusBadge(body, self.f_glyph)
        self.badge.pack(pady=(px(6), px(10)))
        self.status_title = tk.Label(body, font=self.f_title, fg=INK, bg=SURFACE)
        self.status_title.pack()
        self.status_subtitle = tk.Label(body, font=self.f_body, fg=MUTED, bg=SURFACE, wraplength=px(WRAP), justify="center")
        self.status_subtitle.pack(pady=(px(4), px(16)))

        rows_card = self._card(body, bg=BG, pad=14)
        rows_card.pack(fill="x")
        rows = rows_card.body  # type: ignore[attr-defined]
        self.row_account = self._status_row(rows, "Tài khoản phụ huynh")
        self.row_service = self._status_row(rows, "Dịch vụ agent")
        self.row_server = self._status_row(rows, "Kết nối server")
        self.row_sync = self._status_row(rows, "Đồng bộ lần cuối", dot=False)
        self.row_policy = self._status_row(rows, "Chính sách", dot=False)

        self.banner = tk.Label(body, font=self.f_small, wraplength=px(WRAP), justify="left", anchor="w", padx=px(12), pady=px(8))
        self.check_button = FlatButton(body, "Kiểm tra kết nối", self._check_connection, self.f_button)
        self.check_button.pack(fill="x", pady=(px(16), px(0)))

        self.details = Collapsible(view, "Thông tin thiết bị", self.f_body, self._fit_window)
        self.details.pack(pady=(px(12), px(0)))
        info_card = self._card(self.details.body, pad=16)
        info_card.pack(fill="x")
        info = info_card.body  # type: ignore[attr-defined]
        self.detail_name = self._detail_row(info, "Tên máy")
        self.detail_id = self._detail_row(info, "Mã thiết bị")
        self.detail_server = self._detail_row(info, "Server")
        self._detail_row(info, "Phiên bản agent").set(AGENT_VERSION)
        actions = tk.Frame(info, bg=SURFACE)
        actions.pack(fill="x", pady=(px(10), px(2)))
        self.service_button = FlatButton(actions, "Tạm dừng đồng bộ", self._toggle_service, self.f_body, variant="secondary")
        self.service_button.pack(side="left")
        FlatButton(actions, "Ghép lại thiết bị", self._start_repair, self.f_body, variant="link").pack(side="right")

    def _status_row(self, master: tk.Frame, label: str, dot: bool = True) -> tuple[tk.Canvas | None, tk.StringVar]:
        row = tk.Frame(master, bg=master.cget("bg"))
        row.pack(fill="x", pady=px(5))
        canvas = None
        if dot:
            canvas = tk.Canvas(row, width=px(10), height=px(10), bg=master.cget("bg"), highlightthickness=0)
            canvas.create_oval(px(1), px(1), px(9), px(9), fill=GREY, outline="", tags="dot")
            canvas.pack(side="left", padx=(px(0), px(8)))
        else:
            tk.Frame(row, width=px(18), bg=master.cget("bg")).pack(side="left")
        tk.Label(row, text=label, font=self.f_body, fg=MUTED, bg=master.cget("bg")).pack(side="left")
        value = tk.StringVar()
        tk.Label(row, textvariable=value, font=self.f_heading, fg=INK, bg=master.cget("bg")).pack(side="right")
        return canvas, value

    def _detail_row(self, master: tk.Frame, label: str) -> tk.StringVar:
        row = tk.Frame(master, bg=SURFACE)
        row.pack(fill="x", pady=px(3))
        tk.Label(row, text=label, font=self.f_small, fg=MUTED, bg=SURFACE, width=14, anchor="w").pack(side="left")
        value = tk.StringVar()
        tk.Label(row, textvariable=value, font=self.f_small, fg=INK, bg=SURFACE, anchor="w",
                 justify="left", wraplength=px(250)).pack(side="left", fill="x")
        return value

    @staticmethod
    def _set_row(row: tuple[tk.Canvas | None, tk.StringVar], text: str, color: str = GREY) -> None:
        canvas, value = row
        value.set(text)
        if canvas is not None:
            canvas.itemconfigure("dot", fill=color)

    def _fit_window(self) -> None:
        """Grow the window when a section opens so nothing is clipped; never shrink it."""
        self.root.update_idletasks()
        needed = self.root.winfo_reqheight()
        screen = self.root.winfo_screenheight() - px(80)
        if self.root.winfo_height() < needed:
            self.root.geometry(f"{self.root.winfo_width()}x{min(needed, screen)}")

    def _set_pill(self, text: str, fg: str, bg: str) -> None:
        self.header_pill.configure(text=f"●  {text}", fg=fg, bg=bg)

    # ------------------------------------------------------------ view states

    def _show_initial_view(self) -> None:
        try:
            enrolled = self.controller.state().enrolled
        except RuntimeError as exc:
            self._show_pair_view()
            self._show_code_error(describe_error(exc))
            return
        if enrolled:
            self._show_status_view()
            self.worker.start()
            self._refresh_status()
        else:
            self._show_pair_view()

    def _show_pair_view(self, allow_back: bool = False) -> None:
        self.status_view.pack_forget()
        self.pair_view.pack(fill="both", expand=True)
        self.stepper.set_step(0)
        self._fit_window()
        if allow_back:
            self.back_button.pack(anchor="w", pady=(px(0), px(8)), before=self.pair_title)
        else:
            self.back_button.pack_forget()
        self._set_pill("Chưa ghép", MUTED, GREY_SOFT)
        self.code_entry.focus_set()

    def _show_status_view(self) -> None:
        self.pair_view.pack_forget()
        self.status_view.pack(fill="both", expand=True)
        self.root.focus_set()
        self._fit_window()

    def _refresh_status(self) -> None:
        try:
            state = self.controller.state()
        except RuntimeError as exc:
            self.connection, self.connection_error = "error", describe_error(exc)
            state = None
        running = self.worker.running
        self._set_row(self.row_account, "Đã ghép", GREEN)
        self._set_row(self.row_service, "Đang chạy" if running else "Tạm dừng", GREEN if running else GREY)
        if not running:
            look = (GREY, GREY_SOFT, "‖", "Đồng bộ đang tạm dừng",
                    "Phụ huynh sẽ thấy máy này ngoại tuyến cho tới khi bạn tiếp tục đồng bộ.")
            self._set_row(self.row_server, "Không kiểm tra", GREY)
        elif self.connection == "ok":
            look = (GREEN, GREEN_SOFT, "✓", "Thiết bị đang được bảo vệ",
                    "OpenGuard đang chạy và đồng bộ với trang phụ huynh.")
            self._set_row(self.row_server, "Đã kết nối", GREEN)
        elif self.connection == "offline":
            look = (AMBER, AMBER_SOFT, "!", "Đang mất kết nối",
                    f"Agent vẫn chạy và sẽ tự thử lại mỗi {self.controller.config.heartbeat_interval_sec} giây.")
            self._set_row(self.row_server, "Mất kết nối", AMBER)
        elif self.connection == "rejected":
            look = (RED, RED_SOFT, "!", "Cần ghép lại thiết bị", self.connection_error)
            self._set_row(self.row_server, "Bị từ chối", RED)
        elif self.connection == "error":
            look = (RED, RED_SOFT, "!", "Đồng bộ gặp lỗi", self.connection_error)
            self._set_row(self.row_server, "Lỗi", RED)
        else:
            look = (GREY, GREY_SOFT, "…", "Đang kết nối tới server", "Vui lòng chờ trong giây lát.")
            self._set_row(self.row_server, "Đang kiểm tra", GREY)
        color, soft, glyph, title, subtitle = look
        self.badge.show(color, soft, glyph)
        self.status_title.configure(text=title)
        self.status_subtitle.configure(text=subtitle)
        self._set_pill({GREEN: "Đang bảo vệ", AMBER: "Mất kết nối", RED: "Cần xử lý"}.get(color, "Tạm dừng"),
                       color if color != GREY else MUTED, soft)

        if state is not None:
            self._set_row(self.row_sync, format_sync_time(state.last_heartbeat_at))
            version = self.policy_version if self.policy_version is not None else state.policy_version
            self._set_row(self.row_policy, f"phiên bản {version}")
            self.detail_id.set(state.device_id or "—")
        self.detail_name.set(device_name())
        self.detail_server.set(self.controller.config.server_url)
        self.service_button.configure(text="Tạm dừng đồng bộ" if running else "Tiếp tục đồng bộ")
        self.check_button.set_enabled(running and not self.checking,
                                      "Đang kiểm tra..." if self.checking else "Kiểm tra kết nối")

    def _show_banner(self, text: str, kind: str = "success") -> None:
        fg, bg = {"success": (GREEN_DARK, GREEN_SOFT), "warning": ("#7a5410", AMBER_SOFT),
                  "error": (RED, RED_SOFT)}[kind]
        self.banner.configure(text=("✓  " if kind == "success" else "⚠  ") + text, fg=fg, bg=bg)
        self.banner.pack(fill="x", pady=(px(14), px(0)), before=self.check_button)
        if self._banner_job:
            self.root.after_cancel(self._banner_job)
        self._banner_job = self.root.after(6000, self.banner.pack_forget) if kind == "success" else None
        self._fit_window()

    # -------------------------------------------------------------- pairing

    def _on_code_change(self, *_args) -> None:
        raw = self.code_var.get()
        cleaned = "".join(raw.split()).upper()
        if cleaned != raw:
            self.code_var.set(cleaned)  # re-enters this callback once with the clean value
            self.code_entry.icursor("end")
            return
        self.counter.configure(text=f"{len(cleaned)}/{CODE_LENGTH}",
                               fg=GREEN if len(cleaned) == CODE_LENGTH else MUTED)
        self._clear_errors()

    def _show_code_error(self, message: str, network: bool = False) -> None:
        self.code_error.configure(text=f"⚠  {message}", fg=AMBER if network else RED)
        self.code_error.pack(anchor="w", pady=(px(6), px(0)), after=self.code_hint)
        if not network:
            self.code_entry.configure(highlightbackground=RED, highlightcolor=RED)

    def _clear_errors(self) -> None:
        self.code_error.pack_forget()
        self.server_error.pack_forget()
        self.code_entry.configure(highlightbackground=INPUT_BORDER, highlightcolor=GREEN)
        self.server_entry.configure(highlightbackground=INPUT_BORDER, highlightcolor=GREEN)

    def _set_enrolling(self, busy: bool) -> None:
        self.enroll_button.set_enabled(not busy, "Đang ghép..." if busy else "Ghép thiết bị")
        state = "disabled" if busy else "normal"
        self.server_entry.configure(state=state)
        self.code_entry.configure(state=state)
        self.stepper.set_step(1 if busy else 0)

    def _enroll(self) -> None:
        if not self.enroll_button.enabled:
            return
        self._clear_errors()
        try:
            code = normalize_enrollment_code(self.code_var.get())
        except ValueError as exc:
            self._show_code_error(str(exc))
            self.code_entry.focus_set()
            return
        try:
            server_url = normalize_server_url(self.server_var.get())
        except ValueError as exc:
            self.advanced.toggle(True)
            self.server_error.configure(text=f"⚠  {exc}")
            self.server_error.pack(anchor="w", pady=(px(4), px(0)))
            self.server_entry.configure(highlightbackground=RED, highlightcolor=RED)
            self.server_entry.focus_set()
            return
        self._set_enrolling(True)

        def task() -> None:
            try:
                self.events.put(("enrolled", self.controller.enroll(code, server_url)))
            except Exception as exc:
                self.events.put(("enroll_error", exc))

        threading.Thread(target=task, name="openguard-enroll", daemon=True).start()

    def _start_repair(self) -> None:
        self.worker.stop()
        self.code_var.set("")
        self._show_pair_view(allow_back=True)

    def _back_to_status(self) -> None:
        self._show_status_view()
        self.worker.start()
        self._refresh_status()

    # ------------------------------------------------------------ heartbeat

    def _toggle_service(self) -> None:
        if self.worker.running:
            self.worker.stop()
        else:
            self.connection = "checking"
            self.worker.start()
        self._refresh_status()

    def _check_connection(self) -> None:
        if self.checking:
            return
        self.checking = True
        self._refresh_status()

        def task() -> None:
            try:
                self.events.put(("checked", (self.controller.heartbeat(), None)))
            except Exception as exc:
                self.events.put(("checked", (None, exc)))

        threading.Thread(target=task, name="openguard-check", daemon=True).start()

    def _queue_heartbeat(self, result: dict | None, error: Exception | None) -> None:
        self.events.put(("heartbeat", (result, error)))

    def _apply_heartbeat(self, result: dict | None, error: Exception | None) -> None:
        if error is None:
            self.connection, self.connection_error = "ok", ""
            if result is not None and "policy_version" in result:
                self.policy_version = result["policy_version"]
        elif is_network_error(error):
            self.connection, self.connection_error = "offline", describe_error(error)
        elif needs_reenroll(error):
            self.connection, self.connection_error = "rejected", describe_error(error)
        else:
            self.connection, self.connection_error = "error", describe_error(error)

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "enrolled":
                    self._set_enrolling(False)
                    self.stepper.set_step(3)
                    self.code_var.set("")
                    self.connection, self.policy_version = "checking", None
                    self._show_status_view()
                    self.worker.start()
                    self._refresh_status()
                    self._show_banner("Ghép thiết bị thành công.")
                elif event == "enroll_error":
                    self._set_enrolling(False)
                    self._show_code_error(describe_error(payload), network=is_network_error(payload))
                    self.code_entry.focus_set()
                elif event in {"heartbeat", "checked"}:
                    result, error = payload
                    if event == "heartbeat" and not self.worker.running:
                        continue
                    self._apply_heartbeat(result, error)
                    if event == "checked":
                        self.checking = False
                        if error is None:
                            self._show_banner("Kết nối ổn định. Đã đồng bộ với trang phụ huynh.")
                        else:
                            self._show_banner(self.connection_error,
                                              "warning" if self.connection == "offline" else "error")
                    if self.status_view.winfo_ismapped():
                        self._refresh_status()
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _close(self) -> None:
        self.worker.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    AgentWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
