"""Bounded hash cache invalidated when executable metadata changes."""
import hashlib
from collections import OrderedDict
from pathlib import Path


class ExecutableHasher:
    def __init__(self, capacity=512):
        self.capacity = capacity
        self.cache = OrderedDict()

    def digest(self, executable):
        try:
            path = Path(executable)
            before = path.stat()
            key = (str(path).casefold(), before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino
            ):
                return None
            value = digest.hexdigest()
            self.cache[key] = value
            while len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
            return value
        except (OSError, ValueError):
            return None
