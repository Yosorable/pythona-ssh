"""A loopback SSH fixture. It echoes bytes without executing system commands."""

import socket
import threading

import paramiko


class TestServer(paramiko.ServerInterface):
    def __init__(self, public_key=None):
        self.public_key = public_key
        self.shell = threading.Event()
        self.sizes = []
        self.auth_attempts = []

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_auth_password(self, username, password):
        self.auth_attempts.append((username, "password"))
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("tester", "test-password") else paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        self.auth_attempts.append((username, "publickey"))
        return paramiko.AUTH_SUCCESSFUL if username == "tester" and key == self.public_key else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        self.sizes.append((width, height))
        return term == b"xterm-256color"

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        self.sizes.append((width, height))
        return True

    def check_channel_shell_request(self, channel):
        self.shell.set()
        return True


class SSHServer:
    def __init__(self, public_key=None, banner=b"test$ "):
        self.key = paramiko.RSAKey.generate(2048)
        self.interface = TestServer(public_key)
        self.banner = banner
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(1)
        self.socket.settimeout(0.2)
        self.port = self.socket.getsockname()[1]
        self.done = threading.Event()
        self.transport = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            while not self.done.is_set():
                try:
                    sock, _ = self.socket.accept()
                    break
                except socket.timeout:
                    continue
            else:
                return
            with paramiko.Transport(sock) as transport:
                self.transport = transport
                transport.add_server_key(self.key)
                transport.start_server(server=self.interface)
                channel = transport.accept(10)
                if channel is None or not self.interface.shell.wait(3):
                    return
                channel.settimeout(0.2)
                channel.sendall(self.banner)
                while not self.done.is_set():
                    try:
                        data = channel.recv(65536)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    if data == b"flood\r":
                        channel.sendall(b"x" * (512 * 1024))
                    elif data == b"exit\r":
                        channel.sendall(b"bye\r\n")
                        channel.send_exit_status(0)
                        channel.close()
                        break
                    else:
                        channel.sendall(data)
        except (EOFError, OSError, paramiko.SSHException):
            pass

    def close(self):
        self.done.set()
        self.socket.close()
        if self.transport:
            self.transport.close()
        self.thread.join(timeout=2)
