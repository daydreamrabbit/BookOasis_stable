"""Process-local caches with byte/item budgets and active expiry reclamation."""
import sys
import time
import threading
import weakref
from collections import OrderedDict
from collections.abc import MutableMapping

_caches = weakref.WeakValueDictionary()
_guard = threading.Lock()
_started = False


def _sweep():
    while True:
        time.sleep(15)
        with _guard:
            caches = list(_caches.values())
        for cache in caches:
            cache.prune()


def _size(value, ceiling):
    seen = set()
    stack = [value]
    total = 0
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        if total > ceiling:
            return total
        if isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (tuple, list, set, frozenset)):
            stack.extend(item)
    return total


class BoundedCache(MutableMapping):
    def __init__(self, ttl, max_bytes=16 * 1024 * 1024, max_items=8):
        self.ttl, self.max_bytes, self.max_items = ttl, max_bytes, max_items
        self._data = OrderedDict()
        self._lock = threading.RLock()
        self.used_bytes = 0

    def prune(self):
        now = time.monotonic()
        with self._lock:
            for key, (_, size, deadline) in list(self._data.items()):
                if deadline <= now:
                    del self._data[key]
                    self.used_bytes -= size

    def __getitem__(self, key):
        with self._lock:
            self.prune()
            value, _, _ = self._data[key]
            self._data.move_to_end(key)
            return value

    def __setitem__(self, key, value):
        global _started
        size = _size((key, value), self.max_bytes)
        with self._lock:
            self.prune()
            if key in self._data:
                self.__delitem__(key)
            if size > self.max_bytes:
                return
            while self._data and (len(self._data) >= self.max_items or self.used_bytes + size > self.max_bytes):
                _, (_, old_size, _) = self._data.popitem(last=False)
                self.used_bytes -= old_size
            self._data[key] = (value, size, time.monotonic() + self.ttl)
            self.used_bytes += size
        with _guard:
            _caches[id(self)] = self
            if not _started:
                threading.Thread(target=_sweep, name='list-cache-expiry', daemon=True).start()
                _started = True

    def __delitem__(self, key):
        with self._lock:
            _, size, _ = self._data.pop(key)
            self.used_bytes -= size

    def __iter__(self):
        with self._lock:
            self.prune()
            return iter(list(self._data))

    def __len__(self):
        with self._lock:
            self.prune()
            return len(self._data)

    def items(self):
        with self._lock:
            self.prune()
            return [(k, entry[0]) for k, entry in self._data.items()]

    def clear(self):
        with self._lock:
            self._data.clear()
            self.used_bytes = 0

    def stats(self):
        with self._lock:
            self.prune()
            return {'items': len(self._data), 'estimated_bytes': self.used_bytes,
                    'max_bytes': self.max_bytes, 'ttl_seconds': self.ttl}
