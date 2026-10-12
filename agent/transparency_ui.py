"""Child-readable local and server activity; no credentials or machine paths."""
import tkinter as tk
from tkinter import ttk

PRIVACY = ('Ứng dụng này ghi nhận gì về em?\n\n'
           'Có ghi: tên ứng dụng, domain chính, thời lượng và thời điểm sử dụng.\n'
           'Không ghi: tin nhắn, nội dung gõ, ảnh màn hình, URL đầy đủ, tiêu đề cửa sổ hoặc tên tài liệu.\n'
           'Đường dẫn executable chỉ dùng trong bộ nhớ để tính SHA-256; không gửi lên server.\n'
           'Lịch sử hoạt động được giữ tối đa 90 ngày. App chạy cùng lúc được tính riêng; '
           'thời lượng app không phải tổng screen time.\n'
           'Domain được gộp theo domain chính, tối đa một event mỗi 30 giây cho cùng loại/kết quả policy.\n')


def policy_text(payload):
    if not payload:
        return 'Chưa có policy.'
    screen = payload.get('screen_time', {})
    lines = [f"Ngày thường: {screen.get('weekday_minutes', '—')} phút; cuối tuần: {screen.get('weekend_minutes', '—')} phút."]
    schedule = payload.get('weekly_schedule', [])
    if schedule:
        from gui_controller import format_schedule
        for day, label in enumerate(('Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy', 'Chủ nhật')):
            lines.append(label + ': ' + format_schedule(schedule[day * 48:(day + 1) * 48]))
    for rule in payload.get('apps', []):
        lines.append(('Chặn' if rule['action'] == 'block' else 'Cho phép') + ': ' + rule['name'] +
                     (' (nhận dạng SHA-256)' if rule.get('sha256') else ' (tên executable)'))
    domains = payload.get('domains') or {}
    lines += ['Domain được phép: ' + ', '.join(domains.get('allow', [])),
              'Domain bị chặn: ' + ', '.join(domains.get('block', [])),
              'Nhóm bị chặn: ' + ', '.join(domains.get('blocked_categories', [])),
              'SafeSearch Google: ' + ('bật' if domains.get('safe_search') else 'tắt')]
    return '\n'.join(lines)


def sections(result, active_policy, usage=None):
    offline = result['source'] != 'server'
    data = result.get('data') or {}
    if offline:
        date = data.get('date', 'chưa có')
        data = data.get('data') or {}
        heading = f'Đang offline — bản server lưu gần nhất, ngày {date}.\n'
    else:
        heading = 'Dữ liệu server giống báo cáo của phụ huynh, gồm các thiết bị của em.\n'
    summary = data.get('summary', {})
    today = heading + '\nScreen time: ' + (str(summary['screen_time_sec']) + ' giây' if summary.get('has_screen_time_data') else 'chưa có dữ liệu') + '\n'
    today += 'Số lượt chặn: ' + str(summary.get('blocked_count', 0)) + '\n\nỨng dụng:\n'
    for item in summary.get('top_apps', []):
        today += f"{item.get('subject', '')}: {item.get('duration_sec', 0)} giây\n"
    today += '\nDomain:\n' + '\n'.join(item.get('subject', '') for item in summary.get('top_domains', []))
    if usage:
        today += f'\n\nScreen time cục bộ hôm nay (máy này): {int(usage.used_seconds)} giây'
    activity = '\n'.join(f"{e.get('timestamp', '')} | {e['type']} | {e.get('subject') or '—'} | {e.get('duration_sec', 0)} giây"
                         for e in data.get('activity', [])) or 'Chưa có hoạt động trên server.'
    activity += '\n\nGần đây trên máy này (tối đa 100):\n'
    for item in result.get('local', []):
        status = 'đã đồng bộ' if item['synced'] else ('bị từ chối: ' + item['rejection'] if item['rejection'] else 'đang chờ đồng bộ')
        activity += f"{item['ts']} | {item['type']} | {item['subject'] or '—'} | {item['duration_sec']} giây | {status}\n"
    audits = []
    for item in data.get('audit', []):
        audits.append(f"{item['timestamp']}: phụ huynh đổi v{item['old_version']} → v{item['new_version']}\n"
                      + 'Trước:\n' + policy_text(item.get('old_payload')) + '\nSau:\n' + policy_text(item.get('new_payload')))
    policy = (f'Đang áp dụng trên máy: v{active_policy.version}\n' + policy_text(active_policy.payload)
              if active_policy else 'Chưa nhận policy hợp lệ.')
    remote = data.get('policy', {})
    if remote and (not active_policy or remote.get('version') != active_policy.version):
        policy += f"\n\nServer hiện có v{remote.get('version')} (chưa xác nhận áp dụng trên máy)."
    return {'Hôm nay': today, 'Hoạt động / chặn': activity, 'Policy': policy,
            'Lịch sử policy': '\n\n'.join(audits) or 'Chưa có thay đổi trong ngày.', 'Quyền riêng tư': PRIVACY}


def show(root, result, policy, usage=None):
    window = tk.Toplevel(root)
    window.title('OpenGuard — Hôm nay và quyền riêng tư')
    window.geometry('820x580')
    notebook = ttk.Notebook(window)
    notebook.pack(fill='both', expand=True, padx=12, pady=12)
    for title, content in sections(result, policy, usage).items():
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        text = tk.Text(frame, wrap='word', font=('Segoe UI', 11), padx=12, pady=12)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.insert('1.0', content)
        text.configure(state='disabled')
