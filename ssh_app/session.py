"""One interactive SSH session with bounded input and acknowledged output."""

import base64
import hashlib
import io
import queue
import socket
import threading
import time
import uuid

from .storage import atomic_write


OUTPUT_WINDOW = 128 * 1024
CHUNK_SIZE = 16 * 1024
INPUT_LIMIT = 256 * 1024
TERMINAL_STATES = {"closed", "error"}


class Cancelled(Exception):
    pass


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")


def load_private_key(paramiko, text, passphrase):
    if not isinstance(text, str) or not text.strip() or len(text) > 65536:
        raise ValueError("invalid_private_key")
    for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_class.from_private_key(io.StringIO(text), password=passphrase or None)
        except (ValueError, paramiko.SSHException):
            pass
    raise ValueError("invalid_private_key")


class SSHSession:
    def __init__(self, host, known_hosts_path, emit, *, output_window=OUTPUT_WINDOW, on_authenticated=None):
        self.id = uuid.uuid4().hex
        self.host = dict(host)
        self.known_hosts_path = known_hosts_path
        self.emit = emit
        self.output_window = output_window
        self.on_authenticated = on_authenticated
        self.lock = threading.RLock()
        self.credit = threading.Condition(self.lock)
        self.cancel = threading.Event()
        self.wakeup = threading.Event()
        self.trusted = threading.Event()
        self.trust_answer = False
        self.challenge = None
        self.state = "connecting"
        self.error = None
        self.sent = self.acknowledged = 0
        self.input_bytes = 0
        self.input_queue = queue.Queue()
        self.size = (80, 24)
        self.resize_pending = None
        self.client = self.channel = self.sock = None
        self.worker = self.writer = None

    def snapshot(self):
        with self.lock:
            return {"id": self.id, "host_id": self.host["id"], "name": self.host["name"],
                    "hostname": self.host["hostname"], "username": self.host["username"],
                    "port": self.host["port"], "state": self.state, "error": self.error}

    def _state(self, state, error=None):
        with self.lock:
            if self.state in TERMINAL_STATES or (self.cancel.is_set() and state not in TERMINAL_STATES):
                return
            self.state, self.error = state, error
            self.emit({"event": "session", "session": self.snapshot()})

    def start(self, credentials, cols=80, rows=24):
        self.size = self._dimensions(cols, rows)
        self.emit({"event": "session", "session": self.snapshot()})
        self.worker = threading.Thread(target=self._run, args=(dict(credentials),),
                                       name="Pythona SSH connection", daemon=True)
        self.worker.start()

    @staticmethod
    def _dimensions(cols, rows):
        if type(cols) is not int or type(rows) is not int or not 2 <= cols <= 1000 or not 1 <= rows <= 1000:
            raise ValueError("invalid_size")
        return cols, rows

    def resize(self, cols, rows):
        size = self._dimensions(cols, rows)
        with self.lock:
            self.size = size
            self.resize_pending = size
        self.wakeup.set()

    def send(self, text):
        if not isinstance(text, str):
            raise ValueError("invalid_input")
        data = text.encode("utf-8")
        with self.lock:
            if self.state != "connected" or self.cancel.is_set():
                raise ValueError("not_connected")
            if len(data) > 65536 or self.input_bytes + len(data) > INPUT_LIMIT:
                raise ValueError("input_full")
            self.input_bytes += len(data)
            self.input_queue.put(data)
        self.wakeup.set()

    def acknowledge(self, seq):
        with self.credit:
            if type(seq) is not int or not self.acknowledged <= seq <= self.sent:
                raise ValueError("invalid_ack")
            self.acknowledged = seq
            self.credit.notify_all()

    def trust(self, challenge_id, accepted):
        with self.lock:
            if self.challenge is None or self.challenge["id"] != challenge_id or type(accepted) is not bool or self.trusted.is_set():
                raise ValueError("expired_challenge")
            self.trust_answer = accepted
            self.trusted.set()

    def _verify_unknown(self, client, hostname, key):
        with self.lock:
            if self.cancel.is_set():
                raise Cancelled()
            self.challenge = {"id": uuid.uuid4().hex, "session_id": self.id, "hostname": hostname,
                              "algorithm": key.get_name(), "fingerprint": fingerprint(key)}
            self._state("verifying")
            self.emit({"event": "host_key", "challenge": dict(self.challenge)})
        if not self.trusted.wait(120):
            raise ValueError("trust_timeout")
        with self.lock:
            if self.cancel.is_set():
                raise Cancelled()
            if not self.trust_answer:
                raise ValueError("trust_rejected")
            client.get_host_keys().add(hostname, key.get_name(), key)
            # Paramiko has already loaded the existing records, including other hosts.
            lines = [name + " " + algorithm + " " + saved.get_base64() + "\n"
                     for name, keys in client.get_host_keys().items() for algorithm, saved in keys.items()]
            atomic_write(self.known_hosts_path, "".join(lines))
            self.challenge = None
        self._state("connecting")

    def _attach(self, name, resource):
        with self.lock:
            if self.cancel.is_set():
                resource.close()
                raise Cancelled()
            setattr(self, name, resource)
        return resource

    def _authenticate(self, paramiko, credentials):
        session = self

        class AskHostKey(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                session._verify_unknown(client, hostname, key)

        client = self._attach("client", paramiko.SSHClient())
        if self.known_hosts_path.exists():
            client.load_host_keys(str(self.known_hosts_path))
        client.set_missing_host_key_policy(AskHostKey())
        pkey = None
        if self.host["auth"] == "key":
            pkey = load_private_key(paramiko, credentials.get("private_key"), credentials.get("passphrase"))
        sock = self._attach("sock", socket.create_connection((self.host["hostname"], self.host["port"]), timeout=10))
        client.connect(self.host["hostname"], port=self.host["port"], username=self.host["username"],
                       password=credentials.get("password") if self.host["auth"] == "password" else None,
                       pkey=pkey, sock=sock, allow_agent=False, look_for_keys=False,
                       timeout=10, banner_timeout=10, auth_timeout=20, channel_timeout=10)
        if self.cancel.is_set():
            raise Cancelled()
        client.get_transport().set_keepalive(30)
        return client

    def _run(self, credentials):
        try:
            import paramiko

            try:
                client = self._authenticate(paramiko, credentials)
                if self.on_authenticated and not self.cancel.is_set():
                    self.on_authenticated(credentials)
            finally:
                credentials.clear()
            with self.lock:
                cols, rows = self.size
            channel = self._attach("channel", client.invoke_shell(term="xterm-256color", width=cols, height=rows))
            channel.settimeout(0.2)
            self._state("connected")
            self.writer = threading.Thread(target=self._write_loop, name="Pythona SSH input", daemon=True)
            self.writer.start()
            while not self.cancel.is_set():
                with self.credit:
                    while self.sent - self.acknowledged >= self.output_window and not self.cancel.is_set():
                        self.credit.wait(0.5)
                    if self.cancel.is_set():
                        break
                    allowance = min(CHUNK_SIZE, self.output_window - (self.sent - self.acknowledged))
                try:
                    data = channel.recv(allowance)
                except socket.timeout:
                    continue
                if not data:
                    break
                with self.credit:
                    self.sent += len(data)
                    self.emit({"event": "output", "session_id": self.id, "seq": self.sent,
                               "data": base64.b64encode(data).decode("ascii")})
            self._state("closed")
        except Cancelled:
            self._state("closed")
        except Exception as error:
            if self.cancel.is_set():
                self._state("closed")
            else:
                code = "connection_failed"
                detail = str(error)
                if isinstance(error, ModuleNotFoundError):
                    code, detail = "dependency_missing", ""
                elif isinstance(error, ValueError):
                    code, detail = str(error), ""
                else:
                    try:
                        import paramiko
                        if isinstance(error, paramiko.BadHostKeyException):
                            code, detail = "host_key_changed", ""
                        elif isinstance(error, paramiko.AuthenticationException):
                            code, detail = "authentication_failed", ""
                    except ImportError:
                        pass
                self._state("error", {"code": code, "detail": detail})
        finally:
            credentials.clear()
            self._stop_resources()
            if self.writer and self.writer is not threading.current_thread():
                self.writer.join(timeout=1)

    def _write_loop(self):
        try:
            while not self.cancel.is_set():
                with self.lock:
                    size, self.resize_pending = self.resize_pending, None
                if size:
                    self.channel.resize_pty(width=size[0], height=size[1])
                try:
                    data = self.input_queue.get_nowait()
                except queue.Empty:
                    self.wakeup.wait(0.1)
                    self.wakeup.clear()
                    continue
                view = memoryview(data)
                deadline = time.monotonic() + 30
                while view and not self.cancel.is_set():
                    try:
                        sent = self.channel.send(view)
                    except socket.timeout:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("SSH input timed out.")
                        continue
                    if not sent:
                        raise EOFError("SSH channel closed.")
                    view = view[sent:]
                with self.lock:
                    self.input_bytes -= len(data)
        except Exception as error:
            if not self.cancel.is_set():
                self._state("error", {"code": "connection_failed", "detail": str(error)})
                self._stop_resources()

    def _stop_resources(self):
        self.cancel.set()
        self.trusted.set()
        self.wakeup.set()
        with self.credit:
            self.credit.notify_all()
            # Abort transport I/O before Channel.close can wait on its send lock.
            resources = (self.client, self.sock, self.channel)
            self.channel = self.client = self.sock = None
        for resource in resources:
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
        # Discard queued keystrokes and pasted data after disconnect.
        while True:
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break

    def close(self):
        self._stop_resources()
        self._state("closed")

    def join(self, timeout=1):
        if self.worker is not None:
            self.worker.join(timeout=timeout)
