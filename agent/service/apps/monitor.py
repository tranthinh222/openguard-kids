"""Poll only this user's session; paths are used in memory and never uploaded."""
import ctypes
import os
import time
from dataclasses import dataclass
from datetime import timedelta
import psutil
from service.content_rules import process_name
from .classifier import classify
from .hasher import ExecutableHasher
from .enforcer import AppEnforcer, PROTECTED


@dataclass(frozen=True)
class Process:
    pid: int
    started: float
    name: str
    executable: str


def session_id(pid):
    if os.name != 'nt':
        return None
    value = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(value)):
        return -1
    return value.value


def processes():
    current = psutil.Process()
    username, session = current.username(), session_id(current.pid)
    for item in psutil.process_iter(['pid', 'create_time', 'name', 'exe', 'username']):
        try:
            info = item.info
            if info['username'] != username or session_id(info['pid']) != session or info['pid'] == os.getpid():
                continue
            name = process_name(info['name'])
            if name not in PROTECTED and info['exe'] and info['create_time'] is not None:
                yield Process(info['pid'], info['create_time'], name, info['exe'])
        except (psutil.Error, ValueError, TypeError):
            continue


class AppMonitor:
    def __init__(self, policy, emit, notify, now, snapshot=processes, hasher=None, enforcer=None, monotonic=time.monotonic):
        self.policy, self.emit, self.notify, self.now = policy, emit, notify, now
        self.snapshot, self.hasher = snapshot, hasher or ExecutableHasher()
        self.enforcer, self.monotonic = enforcer or AppEnforcer(), monotonic
        self.active = {}

    def tick(self):
        moment, mono, policy = self.now(), self.monotonic(), self.policy()
        seen = set()
        for process in self.snapshot():
            key = process.pid, process.started
            seen.add(key)
            state = self.active.get(key)
            if state is None:
                state = self.active[key] = dict(process=process, sha=self.hasher.digest(process.executable),
                                               mono=mono, at=moment, blocked=False, retry=0, warned=False,
                                               policy_id=policy.policy_id if policy else None)
                self.emit('app_start', moment, subject=process.name, policy_id=state['policy_id'])
            if mono - state['mono'] >= 60 or moment.date() != state['at'].date() or (
                state['policy_id'] != (policy.policy_id if policy else None)
            ):
                self._flush(state, mono, moment)
                state['policy_id'] = policy.policy_id if policy else None
            action, reason = classify(process.name, state['sha'], policy.payload.get('apps', []) if policy else [])
            if action == 'block' and not state['blocked'] and mono >= state['retry']:
                state['retry'] = mono + 10
                if self.enforcer.terminate(process):
                    self.emit('blocked_app', moment, subject=process.name, policy_id=state['policy_id'])
                    state['blocked'] = True
                    self.notify(dict(type='APP_BLOCKED', subject=process.name, reason=reason))
                elif not state['warned']:
                    state['warned'] = True
                    self.notify(dict(type='CONTENT_ERROR', message=f'Không thể chặn {process.name}: quyền truy cập hoặc tiến trình được bảo vệ.'))
        for key in set(self.active) - seen:
            self._flush(self.active.pop(key), mono, moment, final=True)

    def _flush(self, state, mono, moment, final=False):
        seconds = max(0, int(mono - state['mono']))
        # Attribute segments to their actual day, including a crossing of midnight.
        # A first heartbeat may replace an untrusted startup wall-clock anchor.
        # Keep monotonic duration, but timestamp this segment using the current clock.
        cursor = moment - timedelta(seconds=max(0, mono - state['mono']))
        remaining = seconds
        while remaining:
            midnight = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            count = min(remaining, max(1, int((midnight - cursor).total_seconds())), 86400)
            end = cursor + timedelta(seconds=count)
            stamp = end - timedelta(microseconds=1) if end == midnight else end
            self.emit('app_stop', stamp, subject=state['process'].name, duration_sec=count,
                      policy_id=state['policy_id'], sha256=state['sha'])
            remaining -= count
            cursor = end
        if final and not seconds:
            self.emit('app_stop', moment, subject=state['process'].name, policy_id=state['policy_id'])
        state['mono'] += seconds
        state['at'] = cursor

    def close(self):
        for state in self.active.values():
            self._flush(state, self.monotonic(), self.now(), final=True)
        self.active.clear()
