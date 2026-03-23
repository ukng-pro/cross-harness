"""Idempotency store backed by processed_keys.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


class IdempotencyStore:
    def __init__(self, path: Path):
        self._path = path
        self._keys: set[str] = set()
        self._load()

    def _load(self):
        if self._path.exists():
            with open(self._path) as f:
                self._keys = set(json.load(f))

    def _save(self):
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(sorted(self._keys), f)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self._path)

    def has_key(self, key: str) -> bool:
        return key in self._keys

    def add_key(self, key: str):
        self._keys.add(key)
        self._save()
