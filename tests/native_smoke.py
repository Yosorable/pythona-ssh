"""Run in Pythona to exercise the real WKWebView bridge with a loopback SSH peer.

The test uses a temporary profile store and closes its own UI and sockets.
It never connects to a saved host. Install development dependencies beforehand.
"""

import builtins
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback


def main():
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from ssh_app.storage import HostStore
    from ssh_app.ui import WebTerminal

    report = {"passed": False}
    dependency_error = None
    host = server = None
    with tempfile.TemporaryDirectory(prefix="pythona_ssh_smoke_") as directory:
        try:
            try:
                from tests.ssh_server import SSHServer
                from ssh_app.session import fingerprint
                server = SSHServer()
                expected = fingerprint(server.key)
            except ImportError as error:
                dependency_error = str(error)
                expected = ""
            store = HostStore(directory)
            store.save({"name": "Native smoke", "hostname": "127.0.0.1", "port": server.port if server else 22,
                        "username": "tester", "auth": "password"})
            host = WebTerminal(store)
            if server is None:
                # UI-only coverage must not download dependencies or open a connection.
                host.app.dependency = lambda: {"available": True, "installing": False, "error": None}
            reports = []
            ready = threading.Event()
            original = host.app.dispatch

            def dispatch(action, payload=None):
                if action == "smoke_report":
                    reports.append(payload)
                    return None
                if action == "smoke_back":
                    builtins.run_on_ui(host.handler.backTap).wait()
                    return None
                if action == "bootstrap":
                    ready.set()
                return original(action, payload)

            host.app.dispatch = dispatch
            builtins.run_on_ui(host.open).wait()
            deadline = time.monotonic() + 10
            while not ready.is_set() and time.monotonic() < deadline:
                host.process()
            if not ready.is_set():
                raise RuntimeError("The frontend did not bootstrap.")
            config = json.dumps({"ssh": bool(server), "fingerprint": expected})
            script = r"""
              (async function () {
                const config = CONFIG;
                const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
                const wait = async predicate => {
                  for (let i = 0; i < 200; i++) { if (predicate()) return; await delay(50); }
                  throw new Error("Timed out waiting for page condition");
                };
                const report = payload => window.webkit.messageHandlers.ssh.postMessage(JSON.stringify({ id: 0, action: "smoke_report", payload }));
                try {
                  await wait(() => document.querySelector(".host-open"));
                  if (document.querySelector(".workspace").dataset.page !== "hosts") throw new Error("Expected host list at startup");
                  document.querySelector(".host-open").click();
                  await wait(() => document.querySelector('input[name="password"]'));
                  if (config.ssh) {
                    const field = document.querySelector('input[name="password"]');
                    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, "test-password");
                    field.dispatchEvent(new Event("input", { bubbles: true }));
                    await delay(50);
                    document.querySelector(".modal-footer .primary").click();
                    await wait(() => document.querySelector(".fingerprint-box"));
                    if (!document.querySelector(".fingerprint-box").textContent.includes(config.fingerprint)) throw new Error("Unexpected loopback host key");
                    document.querySelector(".modal-footer .primary").click();
                    await wait(() => document.querySelector('.terminal-pane[data-state="connected"]'));
                    const channelID = await new Promise(resolve => {
                      const receive = window.sshBridge.receive;
                      window.sshBridge.receive = messages => {
                        for (const message of messages) if (message.id === 999) resolve(message.result.session.id);
                        receive(messages);
                      };
                      window.webkit.messageHandlers.ssh.postMessage(JSON.stringify({ id: 999, action: "bootstrap" }));
                    });
                    window.webkit.messageHandlers.ssh.postMessage(JSON.stringify({ id: 0, action: "input", payload: { session_id: channelID, data: "native-echo 你好 🐍\r" } }));
                    await wait(() => document.querySelector(".xterm-rows").textContent.includes("native-echo 你好 🐍"));
                    document.querySelector(".terminal-options").click();
                    await wait(() => document.querySelector(".disconnect"));
                    document.querySelector(".disconnect").click();
                    await wait(() => document.querySelector(".session-ended"));
                  }
                  const terminal = document.querySelector(".terminal-surface").getBoundingClientRect();
                  const viewport = { width: innerWidth, height: innerHeight, terminalHeight: terminal.height, terminalBottom: terminal.bottom };
                  window.webkit.messageHandlers.ssh.postMessage(JSON.stringify({ id: 0, action: "smoke_back" }));
                  await wait(() => document.querySelector(".workspace").dataset.page === "hosts");
                  report({ passed: true, ssh: config.ssh, width: innerWidth, height: innerHeight,
                    ...viewport, nativeBack: true,
                    secretInputs: document.querySelectorAll('input[type="password"]').length });
                } catch (error) { report({ passed: false, error: String(error), page: document.body.innerText }); }
              })();
            """.replace("CONFIG", config)
            builtins.run_on_ui(lambda: host.webview.evaluateJavaScript_completionHandler_(script, None)).wait()
            deadline = time.monotonic() + 25
            while not reports and time.monotonic() < deadline:
                host.process()
            report = reports[0] if reports else {"passed": False, "error": "Native bridge did not report."}
            if dependency_error:
                report["dependency_error"] = dependency_error
            if report.get("terminalBottom", 0) > report.get("height", 0) + 1:
                report = {**report, "passed": False, "error": "Terminal exceeds native viewport."}
            if report.get("terminalHeight", 0) < report.get("height", 0) - 45:
                report = {**report, "passed": False, "error": "Terminal lost space to extra controls."}
            if server and report.get("passed"):
                report["credentials_saved"] = store.list()[0]["has_credentials"]
                report["plaintext_present"] = "test-password" in store.path.read_text()
                report["passed"] = report["credentials_saved"] and not report["plaintext_present"]
        except Exception:
            report = {"passed": False, "error": traceback.format_exc()}
        finally:
            if host:
                host.app.close()
                builtins.run_on_ui(host.close).wait()
            if server:
                server.close()
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()
