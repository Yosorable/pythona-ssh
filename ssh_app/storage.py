"""Atomic host storage with optional encrypted credentials."""

import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid

from .credentials import decrypt, encrypt

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / ".local"


def host_identity(host):
    return {key: host[key] for key in ("id", "hostname", "port", "username", "auth")}


def clean_credentials(auth, value):
    if not isinstance(value, dict):
        raise ValueError("invalid_credentials")
    keys = ("password",) if auth == "password" else ("private_key", "passphrase")
    result = {key: value.get(key, "") for key in keys}
    if any(not isinstance(item, str) or len(item) > 65536 for item in result.values()):
        raise ValueError("invalid_credentials")
    if auth == "key" and not result["private_key"].strip():
        raise ValueError("invalid_private_key")
    return result


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clean_host(value, *, new=False):
    if not isinstance(value, dict):
        raise ValueError("invalid_host")
    result = {}
    for key in ("name", "hostname", "username"):
        text = value.get(key)
        if not isinstance(text, str) or not text.strip() or len(text) > 255:
            raise ValueError("invalid_" + key)
        text = text.strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValueError("invalid_" + key)
        if key != "name" and any(char.isspace() for char in text):
            raise ValueError("invalid_" + key)
        result[key] = text
    hostname = result["hostname"]
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]
    if not hostname or any(char in hostname for char in "/\\@?#[]"):
        raise ValueError("invalid_hostname")
    result["hostname"] = hostname.lower()
    port = value.get("port", 22)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_port")
    result["port"] = port
    auth = value.get("auth", "password")
    if auth not in ("password", "key"):
        raise ValueError("invalid_auth")
    result["auth"] = auth
    identity = uuid.uuid4().hex if new else value.get("id")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError("invalid_host")
    result["id"] = identity
    return result


class HostStore:
    def __init__(self, directory=DATA_DIR):
        self.directory = Path(directory)
        self.path = self.directory / "hosts.json"
        self.known_hosts_path = self.directory / "known_hosts"
        self.lock = threading.RLock()
        self.revisions = {}
        self._hosts = []
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("hosts"), list):
                raise ValueError("Invalid hosts.json; restore or rename the file before starting.")
            for item in value["hosts"]:
                host = clean_host(item)
                token = item.get("credentials_encrypted")
                if token is not None:
                    if not isinstance(token, str) or len(token) > 512 * 1024:
                        raise ValueError("Invalid credential record.")
                    host["credentials_encrypted"] = token
                self._hosts.append(host)
            if len({host["id"] for host in self._hosts}) != len(self._hosts):
                raise ValueError("Duplicate host IDs in hosts.json.")

    def list(self):
        with self.lock:
            return [self._public(host) for host in self._hosts]

    @staticmethod
    def _public(host):
        return {**clean_host(host), "has_credentials": "credentials_encrypted" in host}

    def get(self, identity):
        with self.lock:
            return self._public(self._record(identity))

    def _record(self, identity):
        for host in self._hosts:
            if host["id"] == identity:
                return host
        raise ValueError("host_missing")

    def credential_revision(self, identity):
        with self.lock:
            self._record(identity)
            return self.revisions.get(identity, 0)

    def credentials(self, identity):
        with self.lock:
            host = self._record(identity)
            token = host.get("credentials_encrypted")
            if token is None:
                raise ValueError("credentials_missing")
            try:
                value = decrypt(token)
                if not isinstance(value, dict) or value.get("host") != host_identity(host):
                    raise ValueError()
                return clean_credentials(host["auth"], value.get("credentials"))
            except (ValueError, TypeError, UnicodeError) as error:
                raise ValueError("credentials_unreadable") from error

    def remember(self, host, credentials, revision):
        with self.lock:
            current = self._record(host["id"])
            if host_identity(current) != host_identity(host) or self.revisions.get(host["id"], 0) != revision:
                return False
            payload = {"host": host_identity(host), "credentials": clean_credentials(host["auth"], credentials)}
            token = encrypt(payload)
            self._commit([{**item, "credentials_encrypted": token} if item["id"] == host["id"] else item for item in self._hosts])
            return True

    def forget(self, identity):
        with self.lock:
            self._record(identity)
            records = [{key: value for key, value in item.items() if key != "credentials_encrypted"} if item["id"] == identity else item for item in self._hosts]
            self._commit(records)
            self.revisions[identity] = self.revisions.get(identity, 0) + 1

    def _commit(self, hosts):
        atomic_write(self.path, json.dumps({"version": 1, "hosts": hosts}, ensure_ascii=False, indent=2) + "\n")
        self._hosts = hosts

    def save(self, value):
        with self.lock:
            existing = value.get("id") if isinstance(value, dict) else None
            host = clean_host(value, new=not existing)
            changed = False
            if existing:
                previous = self._record(existing)
                changed = host_identity(previous) != host_identity(host)
                if not changed and "credentials_encrypted" in previous:
                    host["credentials_encrypted"] = previous["credentials_encrypted"]
                hosts = [host if item["id"] == existing else item for item in self._hosts]
            else:
                hosts = self._hosts + [host]
            self._commit(hosts)
            if changed:
                self.revisions[host["id"]] = self.revisions.get(host["id"], 0) + 1
            return self._public(host)

    def delete(self, identity):
        with self.lock:
            self._record(identity)
            self._commit([host for host in self._hosts if host["id"] != identity])
            self.revisions[identity] = self.revisions.get(identity, 0) + 1
