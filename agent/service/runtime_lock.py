"""OS-released local lease: never account or enforce twice for the same database."""
import os


class RuntimeLock:
    def __init__(self, database_path, suffix='.runtime.lock'):
        path = database_path.with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError('An agent is already running for this database') from exc

    def close(self):
        if not self.file.closed:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
