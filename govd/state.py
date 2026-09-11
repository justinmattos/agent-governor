import threading
import time


class LockTable:
    def __init__(self):
        self._lock = threading.Lock()
        self._held = {}

    def _active(self, resource, ttl):
        info = self._held.get(resource)
        if not info:
            return None
        if ttl and time.time() - info["started_at"] > ttl:
            self._held.pop(resource, None)
            return None
        return info

    def holder(self, resource, ttl=0):
        with self._lock:
            return self._active(resource, ttl)

    def acquire(self, resource, session, agent, ttl=0):
        with self._lock:
            info = self._active(resource, ttl)
            if info and info["session"] != session:
                return info
            self._held[resource] = {
                "session": session,
                "agent": agent,
                "started_at": time.time(),
            }
            return None

    def release(self, resource, session):
        with self._lock:
            info = self._held.get(resource)
            if info and info["session"] == session:
                self._held.pop(resource, None)

    def release_session(self, session):
        with self._lock:
            for resource in [r for r, i in self._held.items() if i["session"] == session]:
                self._held.pop(resource, None)

    def snapshot(self):
        with self._lock:
            return dict(self._held)


class SessionPlans:
    """Plan files each session has written under `.context/plans/`, so the daemon
    can validate them once at the turn boundary instead of on every chunked edit."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_session = {}

    def add(self, session, path):
        with self._lock:
            self._by_session.setdefault(session, set()).add(path)

    def paths(self, session):
        with self._lock:
            return set(self._by_session.get(session, ()))

    def clear(self, session):
        with self._lock:
            self._by_session.pop(session, None)
