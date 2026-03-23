"""Repo lock manager (.workflow/lock)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class LockManager:
    def __init__(self, workflow_dir: Path):
        self._path = workflow_dir / "lock"

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self, agent: str, dispatch_id: str) -> bool:
        data = {
            "agent": agent,
            "dispatch_id": dispatch_id,
            "pid": os.getpid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(str(self._path), flags)
        except FileExistsError:
            return False
        try:
            os.write(fd, json.dumps(data).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return True

    def release(self):
        if self._path.exists():
            self._path.unlink()

    def is_locked(self) -> bool:
        return self._path.exists()

    def read_lock(self) -> dict | None:
        if not self._path.exists():
            return None
        with open(self._path) as f:
            return json.load(f)

    def check_stale(self) -> bool:
        """Returns True if stale lock was found and removed."""
        lock = self.read_lock()
        if lock is None:
            return False
        pid = lock.get("pid")
        if pid is None:
            self.release()
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self.release()
            return True
        except PermissionError:
            pass
        return False
