import base64
import json
import logging
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ssh_app.app import SSHApp
from ssh_app.session import SSHSession, fingerprint, load_private_key
from ssh_app.storage import HostStore, clean_host
from tests.ssh_server import SSHServer


logging.getLogger("paramiko").setLevel(logging.CRITICAL)
HOST = {"name": "Test host", "hostname": "127.0.0.1", "port": 22, "username": "tester", "auth": "password"}


def wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for condition.")


class Events:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []

    def __call__(self, event):
        with self.lock:
            self.events.append(event)

    def list(self, kind):
        with self.lock:
            return [event for event in self.events if event["event"] == kind]

    def output(self):
        return b"".join(base64.b64decode(event["data"]) for event in self.list("output"))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = HostStore(self.directory.name)

    def test_roundtrip_allowlist_and_atomic_update(self):
        host = self.store.save({**HOST, "password": "secret", "private_key": "secret-key", "extra": 9})
        self.assertNotIn("password", host)
        self.assertNotIn("secret", self.store.path.read_text())
        self.assertEqual(HostStore(self.directory.name).get(host["id"]), host)
        host["name"] = "Changed"
        self.store.save(host)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.store.delete(host["id"])
        self.assertEqual(HostStore(self.directory.name).list(), [])

    def test_bad_storage_is_never_silently_replaced(self):
        self.store.path.write_text("{broken")
        with self.assertRaises(json.JSONDecodeError):
            HostStore(self.directory.name)
        self.assertEqual(self.store.path.read_text(), "{broken")

    def test_host_validation_and_ipv6(self):
        host = clean_host({**HOST, "hostname": "[::1]"}, new=True)
        self.assertEqual(host["hostname"], "::1")
        for key, value in (("hostname", "ssh://example.com"), ("username", "a\nb"), ("port", True), ("port", 0), ("port", 65536)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                clean_host({**HOST, key: value}, new=True)

    def test_unknown_id_does_not_create_or_delete_profile(self):
        with self.assertRaises(ValueError):
            self.store.save({**HOST, "id": "a" * 32})
        with self.assertRaises(ValueError):
            self.store.delete("a" * 32)
        self.assertFalse(self.store.path.exists())

    def test_credentials_are_encrypted_and_restore_after_reopening(self):
        host = self.store.save(HOST)
        secret = "password-保存-plain-text-must-not-appear"
        self.assertTrue(self.store.remember(host, {"password": secret}, self.store.credential_revision(host["id"])))
        first = json.loads(self.store.path.read_text())["hosts"][0]["credentials_encrypted"]
        self.assertNotIn(secret, self.store.path.read_text())
        self.assertNotIn(base64.b64encode(secret.encode()).decode(), first)
        self.assertEqual(HostStore(self.directory.name).credentials(host["id"]), {"password": secret})
        self.assertTrue(self.store.get(host["id"])["has_credentials"])
        self.assertNotIn(first, json.dumps(self.store.list()))
        self.store.remember(host, {"password": secret}, self.store.credential_revision(host["id"]))
        second = json.loads(self.store.path.read_text())["hosts"][0]["credentials_encrypted"]
        self.assertNotEqual(first, second)

    def test_private_key_and_passphrase_roundtrip(self):
        host = self.store.save({**HOST, "auth": "key"})
        credentials = {"private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret-key\n", "passphrase": "private-passphrase"}
        self.store.remember(host, credentials, 0)
        self.assertEqual(HostStore(self.directory.name).credentials(host["id"]), credentials)
        self.assertNotIn("secret-key", self.store.path.read_text())
        self.assertNotIn("private-passphrase", self.store.path.read_text())

    def test_renaming_preserves_credentials_but_endpoint_changes_clear_them(self):
        host = self.store.save(HOST)
        self.store.remember(host, {"password": "secret"}, 0)
        renamed = self.store.save({**host, "name": "Renamed"})
        self.assertTrue(renamed["has_credentials"])
        self.assertEqual(self.store.credentials(host["id"]), {"password": "secret"})
        changed = self.store.save({**host, "hostname": "other.example.com"})
        self.assertFalse(changed["has_credentials"])
        with self.assertRaisesRegex(ValueError, "credentials_missing"):
            self.store.credentials(host["id"])

    def test_forget_prevents_late_authentication_from_saving_again(self):
        host = self.store.save(HOST)
        revision = self.store.credential_revision(host["id"])
        self.store.remember(host, {"password": "secret"}, revision)
        self.store.forget(host["id"])
        self.assertFalse(self.store.remember(host, {"password": "late-secret"}, revision))
        self.assertFalse(HostStore(self.directory.name).get(host["id"])["has_credentials"])

    def test_tampered_or_reassigned_credentials_are_rejected_without_overwriting(self):
        host = self.store.save(HOST)
        self.store.remember(host, {"password": "secret"}, 0)
        value = json.loads(self.store.path.read_text())
        value["hosts"][0]["username"] = "different-user"
        self.store.path.write_text(json.dumps(value))
        changed = HostStore(self.directory.name)
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "credentials_unreadable"):
            changed.credentials(host["id"])
        self.assertEqual(self.store.path.read_bytes(), before)
        value["hosts"][0]["credentials_encrypted"] = "not-a-valid-token"
        self.store.path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "credentials_unreadable"):
            HostStore(self.directory.name).credentials(host["id"])

    def test_deleting_host_removes_its_credential_record(self):
        host = self.store.save(HOST)
        self.store.remember(host, {"password": "secret"}, 0)
        self.store.delete(host["id"])
        self.assertEqual(json.loads(self.store.path.read_text())["hosts"], [])


class SSHTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "known_hosts"
        self.sessions = []
        self.servers = []

    def tearDown(self):
        for session in self.sessions:
            session.close()
            session.join(2)
            self.assertFalse(session.worker.is_alive())
            if session.writer:
                self.assertFalse(session.writer.is_alive())
        for server in self.servers:
            server.close()

    def make(self, *, credentials=None, auth="password", public_key=None, window=128 * 1024):
        server = SSHServer(public_key=public_key)
        self.servers.append(server)
        events = Events()
        host = clean_host({**HOST, "port": server.port, "auth": auth}, new=True)
        session = SSHSession(host, self.path, events, output_window=window)
        self.sessions.append(session)
        session.start(credentials or {"password": "test-password"})
        return session, server, events

    def accept(self, session, events):
        challenge = wait(lambda: events.list("host_key"))[0]["challenge"]
        session.trust(challenge["id"], True)
        wait(lambda: session.snapshot()["state"] == "connected")

    def test_password_pty_unicode_resize_and_explicit_close(self):
        session, server, events = self.make()
        self.accept(session, events)
        self.assertEqual(server.interface.sizes[0], (80, 24))
        session.send("你好 🐍\r")
        wait(lambda: "你好 🐍".encode() in events.output())
        session.resize(132, 40)
        wait(lambda: (132, 40) in server.interface.sizes)
        self.assertIn(fingerprint(server.key), events.list("host_key")[0]["challenge"]["fingerprint"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        session.close()
        session.join(2)
        self.assertEqual(session.snapshot()["state"], "closed")
        self.assertIsNone(session.client)

    def test_unknown_host_rejection_never_authenticates_or_saves(self):
        session, server, events = self.make()
        challenge = wait(lambda: events.list("host_key"))[0]["challenge"]
        session.trust(challenge["id"], False)
        wait(lambda: session.snapshot()["state"] == "error")
        self.assertEqual(session.error["code"], "trust_rejected")
        self.assertFalse(self.path.exists())
        self.assertEqual(server.interface.auth_attempts, [])

    def test_cancel_during_verification_does_not_save_or_resurrect(self):
        session, server, events = self.make()
        wait(lambda: events.list("host_key"))
        session.close()
        session.join(2)
        self.assertEqual(session.snapshot()["state"], "closed")
        self.assertFalse(self.path.exists())
        self.assertEqual(server.interface.auth_attempts, [])
        self.assertNotIn("connected", [event["session"]["state"] for event in events.list("session")])

    def test_changed_key_is_blocked_before_credentials(self):
        server = SSHServer()
        self.servers.append(server)
        keys = paramiko.HostKeys()
        keys.add("[127.0.0.1]:" + str(server.port), "ssh-rsa", paramiko.RSAKey.generate(2048))
        keys.save(str(self.path))
        original = self.path.read_bytes()
        events = Events()
        session = SSHSession(clean_host({**HOST, "port": server.port}, new=True), self.path, events)
        self.sessions.append(session)
        session.start({"password": "test-password"})
        wait(lambda: session.snapshot()["state"] == "error")
        self.assertEqual(session.error["code"], "host_key_changed")
        self.assertEqual(events.list("host_key"), [])
        self.assertEqual(server.interface.auth_attempts, [])
        self.assertEqual(self.path.read_bytes(), original)

    def test_wrong_password_has_specific_error(self):
        session, server, events = self.make(credentials={"password": "wrong"})
        challenge = wait(lambda: events.list("host_key"))[0]["challenge"]
        session.trust(challenge["id"], True)
        wait(lambda: session.snapshot()["state"] == "error")
        self.assertEqual(session.error["code"], "authentication_failed")

    def test_encrypted_ed25519_key_authentication(self):
        private = Ed25519PrivateKey.generate()
        encoded = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                        serialization.BestAvailableEncryption(b"passphrase")).decode()
        public = load_private_key(paramiko, encoded, "passphrase")
        with self.assertRaisesRegex(ValueError, "invalid_private_key"):
            load_private_key(paramiko, encoded, "wrong")
        session, server, events = self.make(auth="key", credentials={"private_key": encoded, "passphrase": "passphrase"}, public_key=public)
        self.accept(session, events)
        self.assertEqual(server.interface.auth_attempts, [("tester", "publickey")])
        self.assertNotIn("PRIVATE", self.path.read_text())

    def test_output_window_requires_ack_and_keeps_input_responsive(self):
        session, server, events = self.make(window=32768)
        self.accept(session, events)
        session.send("flood\r")
        wait(lambda: session.sent == 32768)
        self.assertEqual(len(events.output()), 32768)
        with self.assertRaises(ValueError):
            session.acknowledge(session.sent + 1)
        # Input uses an independent worker, even while output is backpressured.
        session.send("\x03")
        wait(lambda: session.input_bytes == 0)
        session.acknowledge(session.sent)
        wait(lambda: session.sent == 65536)
        self.assertLessEqual(session.sent - session.acknowledged, 32768)

    def test_remote_eof_preserves_final_output(self):
        session, server, events = self.make()
        self.accept(session, events)
        session.send("exit\r")
        wait(lambda: session.snapshot()["state"] == "closed")
        self.assertTrue(events.output().endswith(b"bye\r\n"))

    def test_close_interrupts_blocked_socket_writes(self):
        session, server, events = self.make()
        self.accept(session, events)
        transport = session.client.get_transport()
        sock = session.sock

        class BlockedWrites:
            def __init__(self):
                self.entered = threading.Event()
                self.closed = threading.Event()

            def send(self, data):
                self.entered.set()
                if self.closed.wait(0.05):
                    raise OSError("Socket closed.")
                raise socket.timeout()

            def close(self):
                sock.close()
                self.closed.set()

            def __getattr__(self, name):
                return getattr(sock, name)

        blocked = BlockedWrites()
        closer = threading.Thread(target=session.close, daemon=True)
        # Keep real Paramiko channel/transport shutdown, but deterministically
        # reproduce a socket that times out on every write until it is closed.
        with patch.object(transport.packetizer, "_Packetizer__socket", blocked):
            try:
                session.send("blocked input")
                self.assertTrue(blocked.entered.wait(2), "The input worker did not reach the socket.")
                closer.start()
                closer.join(2)
                self.assertFalse(closer.is_alive(), "Disconnect waited for the blocked SSH writer.")
                session.join(2)
                self.assertEqual(session.snapshot()["state"], "closed")
                self.assertFalse(transport.is_active())
                self.assertTrue(sock._closed)
                self.assertFalse(session.worker.is_alive())
                self.assertFalse(session.writer.is_alive())
            finally:
                # Also unblock the old implementation so a regression fails
                # the assertion instead of hanging the test suite's cleanup.
                blocked.close()
                if closer.ident is not None:
                    closer.join(2)
                session.join(2)


class AppCredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pythona_ssh_credentials_")
        self.store = HostStore(self.directory.name)
        self.events = Events()
        self.server = SSHServer()
        self.app = SSHApp(self.store, self.events)
        self.host = self.store.save({**HOST, "port": self.server.port})

    def tearDown(self):
        self.app.close()
        self.server.close()
        self.directory.cleanup()

    def connect(self, password, remember=True):
        self.app.dispatch("connect", {"host_id": self.host["id"], "credentials": {"password": password}, "remember": remember})
        challenge = wait(lambda: self.events.list("host_key"))[0]["challenge"]
        self.app.dispatch("trust_host", {"session_id": self.app.session.id, "challenge_id": challenge["id"], "accepted": True})

    def test_successful_authentication_saves_and_next_app_uses_credentials(self):
        self.connect("test-password")
        wait(lambda: self.app.session.snapshot()["state"] == "connected")
        self.assertTrue(self.store.get(self.host["id"])["has_credentials"])
        self.assertNotIn("test-password", self.store.path.read_text())
        self.app.close()
        reopened = SSHApp(HostStore(self.directory.name))
        captured = []

        def start(session, credentials, cols, rows):
            captured.append(dict(credentials))

        try:
            with patch.object(SSHSession, "start", start):
                reopened.dispatch("connect", {"host_id": self.host["id"]})
            self.assertEqual(captured, [{"password": "test-password"}])
            self.assertNotIn("credentials_encrypted", json.dumps(reopened.snapshot()))
        finally:
            reopened.close()

    def test_failed_authentication_does_not_save(self):
        self.connect("incorrect-password")
        wait(lambda: self.app.session.snapshot()["state"] == "error")
        self.assertFalse(self.store.get(self.host["id"])["has_credentials"])
        self.assertNotIn("credentials_encrypted", self.store.path.read_text())

    def test_opt_out_does_not_save(self):
        self.connect("test-password", remember=False)
        wait(lambda: self.app.session.snapshot()["state"] == "connected")
        self.assertFalse(HostStore(self.directory.name).get(self.host["id"])["has_credentials"])


class AppTests(unittest.TestCase):
    def test_invalid_terminal_size_does_not_leave_a_busy_session(self):
        with tempfile.TemporaryDirectory(prefix="pythona_ssh_test_") as directory:
            app = SSHApp(HostStore(directory))
            host = app.store.save(HOST)
            with self.assertRaisesRegex(ValueError, "invalid_size"):
                app.dispatch("connect", {"host_id": host["id"], "credentials": {}, "cols": 0, "rows": 24})
            self.assertIsNone(app.session)

    def test_installation_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory(prefix="pythona_ssh_test_") as directory:
            app = SSHApp(HostStore(directory))
            for payload in ({}, {"confirmed": False}, {"confirmed": 1}):
                with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, "installation_not_confirmed"):
                    app.dispatch("install_dependency", payload)
            self.assertIsNone(app.install_worker)
            self.assertFalse(app.installing)

    def test_only_current_session_may_send_or_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            app = SSHApp(HostStore(directory))
            with self.assertRaisesRegex(ValueError, "session_expired"):
                app.dispatch("input", {"session_id": "stale", "data": "danger"})
            with self.assertRaisesRegex(ValueError, "session_expired"):
                app.dispatch("ack", {"session_id": "stale", "seq": 123})
            self.assertNotIn("credentials", app.snapshot())
            app.close()
            with self.assertRaisesRegex(ValueError, "app_closed"):
                app.dispatch("bootstrap")


if __name__ == "__main__":
    unittest.main()
