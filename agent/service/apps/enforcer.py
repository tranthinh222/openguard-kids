import os
import psutil

# Never terminate the OS session or the agent's own process tree ancestors.
PROTECTED = {'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'services.exe',
             'lsass.exe', 'winlogon.exe', 'svchost.exe', 'dwm.exe', 'explorer.exe',
             'fontdrvhost.exe', 'sihost.exe', 'securityhealthservice.exe'}


class AppEnforcer:
    def __init__(self):
        self.protected_pids = {os.getpid(), *(p.pid for p in psutil.Process().parents())}

    def terminate(self, process):
        if process.name.lower() in PROTECTED or process.pid in self.protected_pids:
            return False
        try:
            live = psutil.Process(process.pid)
            if live.create_time() != process.started or live.name().lower() != process.name:
                return False  # PID reused; do not kill a different process.
            live.terminate()
            return True
        except (psutil.Error, OSError):
            return False
