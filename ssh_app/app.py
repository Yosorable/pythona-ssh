"""Commands shared by the WebKit bridge and backend tests."""

import importlib.metadata
import importlib.util
import threading

from .session import SSHSession, TERMINAL_STATES
from .storage import HostStore, clean_credentials


class SSHApp:
    def __init__(self, store=None, emit=None):
        self.store = store or HostStore()
        self.emit = emit or (lambda event: None)
        self.closed = threading.Event()
        self.session = None
        self.retired = []
        self.installing = False
        self.install_worker = None
        self.dependency_error = None

    def dependency(self):
        try:
            importlib.metadata.version("paramiko")
            available = importlib.util.find_spec("paramiko") is not None
        except (ImportError, ValueError):
            available = False
        return {"available": available,
                "installing": self.installing, "error": self.dependency_error}

    def snapshot(self):
        return {"hosts": self.store.list(), "session": self.session.snapshot() if self.session else None,
                "dependency": self.dependency()}

    def _current(self, payload):
        if self.session is None or payload.get("session_id") != self.session.id:
            raise ValueError("session_expired")
        return self.session

    def _session_event(self, event):
        identity = event.get("session_id") or event.get("session", {}).get("id") or event.get("challenge", {}).get("session_id")
        if not self.closed.is_set() and self.session and self.session.id == identity:
            self.emit(event)

    def dispatch(self, action, payload=None):
        if self.closed.is_set():
            raise ValueError("app_closed")
        payload = payload or {}
        if not isinstance(payload, dict):
            raise ValueError("invalid_request")
        if action == "bootstrap":
            return self.snapshot()
        if action == "save_host":
            host = self.store.save(payload)
            return {"host": host, "hosts": self.store.list()}
        if action == "delete_host":
            self.store.delete(payload.get("id"))
            return {"hosts": self.store.list()}
        if action == "forget_credentials":
            self.store.forget(payload.get("id"))
            return {"hosts": self.store.list()}
        if action == "connect":
            if self.session and self.session.snapshot()["state"] not in TERMINAL_STATES:
                raise ValueError("session_busy")
            if not self.dependency()["available"]:
                raise ValueError("dependency_missing")
            host = self.store.get(payload.get("host_id"))
            use_saved = "credentials" not in payload
            supplied = payload.get("credentials")
            credentials = self.store.credentials(host["id"]) if use_saved else clean_credentials(host["auth"], supplied)
            remember = payload.get("remember", False)
            if type(remember) is not bool:
                credentials.clear()
                raise ValueError("invalid_credentials")
            cols, rows = SSHSession._dimensions(payload.get("cols", 80), payload.get("rows", 24))
            revision = self.store.credential_revision(host["id"])
            if self.session:
                self.retired.append(self.session)
            self.retired = [session for session in self.retired if session.worker and session.worker.is_alive()]
            def authenticated(value):
                if use_saved or self.closed.is_set() or session.cancel.is_set() or self.session is not session:
                    return
                try:
                    if remember:
                        self.store.remember(host, value, revision)
                    elif self.store.credential_revision(host["id"]) == revision:
                        self.store.forget(host["id"])
                    self.emit({"event": "hosts", "hosts": self.store.list()})
                except Exception:
                    self.emit({"event": "error", "error": {"code": "credentials_save_failed", "detail": ""}})

            session = SSHSession(host, self.store.known_hosts_path, self._session_event, on_authenticated=authenticated)
            self.session = session
            try:
                self.session.start(credentials, cols, rows)
            except Exception:
                self.session.close()
                raise
            finally:
                credentials.clear()
                if isinstance(supplied, dict):
                    supplied.clear()
            return self.session.snapshot()
        if action == "disconnect":
            self._current(payload).close()
        elif action == "input":
            self._current(payload).send(payload.get("data"))
        elif action == "resize":
            self._current(payload).resize(payload.get("cols"), payload.get("rows"))
        elif action == "ack":
            self._current(payload).acknowledge(payload.get("seq"))
        elif action == "trust_host":
            self._current(payload).trust(payload.get("challenge_id"), payload.get("accepted"))
        elif action == "resume":
            if self.session:
                current = self.session
                with current.lock:
                    transport = current.client.get_transport() if current.client else None
                    dead = current.state == "connected" and (transport is None or not transport.is_active())
                if dead:
                    current.close()
            return self.snapshot()
        elif action == "install_dependency":
            if payload.get("confirmed") is not True:
                raise ValueError("installation_not_confirmed")
            if not self.installing:
                self.installing = True
                self.dependency_error = None
                self.install_worker = threading.Thread(target=self._install, name="Pythona SSH dependencies", daemon=True)
                self.install_worker.start()
            return self.dependency()
        else:
            raise ValueError("unknown_action")
        return None

    def _install(self):
        try:
            from pythona import packages
            packages.install("paramiko", version="5.0.0")
            importlib.invalidate_caches()
        except Exception as error:
            self.dependency_error = str(error)
        finally:
            self.installing = False
            if not self.closed.is_set():
                self.emit({"event": "dependency", "dependency": self.dependency()})

    def close(self):
        self.closed.set()
        sessions = self.retired + ([self.session] if self.session else [])
        for session in sessions:
            session.close()
        for session in sessions:
            session.join()
