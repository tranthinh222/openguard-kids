from unittest.mock import Mock

import psutil

from service.runtime import TrayWatchdog
from tray_client import ServiceLink


def process(pid, created):
    result = Mock()
    result.pid = pid
    result.create_time.return_value = created
    result.is_running.return_value = True
    result.children.return_value = []
    return result


def test_stop_reaps_launcher_children_and_prevents_relaunch(monkeypatch):
    root, child = process(100, 1), process(101, 2)
    root.children.return_value = [child]
    monkeypatch.setattr(psutil, "Process", lambda pid: {100: root, 101: child}[pid])
    wait = Mock(side_effect=[([], [root, child]), ([root], [child]), ([child], [])])
    monkeypatch.setattr(psutil, "wait_procs", wait)
    launch = Mock(return_value=100)
    watchdog = TrayWatchdog(session=lambda: 1, launch=launch)
    watchdog.tick()
    watchdog.stop()
    watchdog.tick()
    launch.assert_called_once()
    root.terminate.assert_called_once()
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert not watchdog._owned


def test_stop_keeps_track_of_orphan_without_killing_reused_root_pid(monkeypatch):
    root, child, reused = process(100, 1), process(101, 2), process(100, 99)
    root.children.return_value = [child]
    lookup = {100: root, 101: child}
    monkeypatch.setattr(psutil, "Process", lambda pid: lookup[pid])
    watchdog = TrayWatchdog(session=lambda: 1, launch=lambda *args, **kwargs: 100)
    watchdog.tick()
    root.is_running.return_value = False
    lookup[100] = reused
    wait = Mock(side_effect=[([], [child]), ([child], []), ([], [])])
    monkeypatch.setattr(psutil, "wait_procs", wait)
    watchdog.stop()
    assert wait.call_args_list[0].args[0] == [child]
    child.terminate.assert_called_once()
    root.terminate.assert_not_called()
    reused.terminate.assert_not_called()


def test_stop_notification_does_not_depend_on_events_or_idle_rpc():
    client, post = Mock(), Mock()
    client.call.return_value = {"stopping": True}
    link = ServiceLink(client, post)
    link.poll_once()
    client.call.assert_called_once_with("status", tray=True, visible=False)
    post.assert_called_once_with("service_status", {"stopping": True})
    assert link._stop.is_set()
