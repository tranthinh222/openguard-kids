"""Visible system tray; all Tk actions are passed back through its event queue."""
import threading
import pystray
from PIL import Image, ImageDraw


class TrayUI:
    def __init__(self, events):
        icon = Image.new('RGBA', (64, 64), '#194c47')
        draw = ImageDraw.Draw(icon)
        draw.polygon([(32, 8), (53, 17), (48, 43), (32, 57), (16, 43), (11, 17)], fill='#e7f5d5')
        draw.line([(22, 31), (29, 38), (43, 24)], fill='#194c47', width=5)
        def action(name):
            return lambda _icon, _item: events.put((name, None))
        self.icon = pystray.Icon('OpenGuardKids', icon, 'OpenGuard Kids — bảo vệ và minh bạch', menu=pystray.Menu(
            pystray.MenuItem('Mở OpenGuard', action('tray_open'), default=True),
            pystray.MenuItem('Hôm nay / quyền riêng tư', action('tray_today')),
            pystray.MenuItem('Thoát agent', action('tray_exit'))))
        self.thread = threading.Thread(target=self.icon.run, daemon=True, name='openguard-tray')

    def start(self):
        self.thread.start()

    @property
    def visible(self):
        return self.icon.visible

    def notify(self, message):
        if self.visible:
            self.icon.notify(message, 'OpenGuard Kids')

    def stop(self):
        self.icon.stop()

    def clear_notification(self):
        if self.visible:
            self.icon.remove_notification()
