import type { BridgeEvent, Challenge, Credentials, Host, Session } from "./types";

// This adapter is only selected in a desktop browser. It never opens a socket.
export function createPreview(emit: (event: BridgeEvent) => void) {
  let hosts: Host[] = [
    { id: "1".repeat(32), name: "Development", hostname: "dev.example.com", port: 22, username: "alex", auth: "password" },
    { id: "2".repeat(32), name: "Home server", hostname: "192.168.1.42", port: 22, username: "pi", auth: "key" },
  ];
  let session: Session | null = null;
  let challenge: Challenge | null = null;
  let line = "";
  let seq = 0;
  const credentials = new Map<string, Credentials>();
  let pending: { hostID: string; value: Credentials; remember: boolean } | null = null;
  const trusted = new Set<string>();
  const dependency = { available: true, installing: false, error: null };
  const update = () => { if (session) emit({ event: "session", session: { ...session } }); };
  const output = (text: string) => {
    if (!session) return;
    const bytes = new TextEncoder().encode(text);
    seq += bytes.length;
    emit({ event: "output", session_id: session.id, seq, data: btoa(String.fromCharCode(...bytes)) });
  };
  const prompt = () => output("\x1b[38;2;94;210;174m" + session?.username + "@" + session?.hostname + "\x1b[0m \x1b[38;2;140;160;188m~\x1b[0m $ ");
  function connected() {
    if (!session) return;
    session.state = "connected";
    if (pending) {
      if (pending.remember) credentials.set(pending.hostID, pending.value);
      else credentials.delete(pending.hostID);
      hosts = hosts.map((host) => host.id === pending!.hostID ? { ...host, has_credentials: pending!.remember } : host);
      pending = null;
      emit({ event: "hosts", hosts: [...hosts] });
    }
    update();
    output("This is a browser preview. No server is connected.\r\nTry \x1b[1mhelp\x1b[0m, \x1b[1mpwd\x1b[0m, \x1b[1mls\x1b[0m or \x1b[1mclear\x1b[0m.\r\n\r\n");
    prompt();
  }
  return async (action: string, payload: Record<string, unknown> = {}): Promise<unknown> => {
    if (action === "bootstrap" || action === "resume") return { hosts: [...hosts], session, dependency };
    if (action === "save_host") {
      const host = { ...payload, id: payload.id || crypto.randomUUID().replaceAll("-", "") } as Host;
      if (!host.name?.trim() || !host.hostname?.trim() || !host.username?.trim()) throw { code: "invalid_host" };
      if (!Number.isInteger(host.port) || host.port < 1 || host.port > 65535) throw { code: "invalid_port" };
      const previous = hosts.find((item) => item.id === host.id);
      const changed = previous && (["hostname", "port", "username", "auth"] as const).some((key) => previous[key] !== host[key]);
      if (changed) credentials.delete(host.id);
      host.has_credentials = credentials.has(host.id);
      hosts = previous ? hosts.map((item) => item.id === host.id ? host : item) : [...hosts, host];
      return { host, hosts: [...hosts] };
    }
    if (action === "delete_host") {
      credentials.delete(String(payload.id));
      hosts = hosts.filter((host) => host.id !== payload.id);
      return { hosts: [...hosts] };
    }
    if (action === "forget_credentials") {
      credentials.delete(String(payload.id));
      if (pending?.hostID === payload.id) pending = null;
      hosts = hosts.map((host) => host.id === payload.id ? { ...host, has_credentials: false } : host);
      return { hosts: [...hosts] };
    }
    if (action === "connect") {
      const host = hosts.find((item) => item.id === payload.host_id);
      if (!host) throw { code: "host_missing" };
      if (session && !["closed", "error"].includes(session.state)) throw { code: "session_busy" };
      if (!("credentials" in payload) && !credentials.has(host.id)) throw { code: "credentials_missing" };
      pending = payload.credentials ? { hostID: host.id, value: { ...payload.credentials as Credentials }, remember: payload.remember === true } : null;
      line = ""; seq = 0;
      session = { id: crypto.randomUUID(), host_id: host.id, name: host.name, hostname: host.hostname,
        username: host.username, port: host.port, state: "connecting", error: null };
      update();
      if (trusted.has(host.hostname)) connected();
      else {
        session.state = "verifying";
        update();
        challenge = { id: crypto.randomUUID(), session_id: session.id, hostname: host.hostname,
          algorithm: "ssh-ed25519", fingerprint: "SHA256:tBYMqfjvxmJqRvaBwwEvSmNlrMpAF1yiPxakFCcHEfQ" };
        emit({ event: "host_key", challenge });
      }
      return session;
    }
    if (action === "trust_host" && session && payload.challenge_id === challenge?.id) {
      if (payload.accepted) { trusted.add(session.hostname); connected(); }
      else { session.state = "closed"; pending = null; update(); }
      challenge = null;
      return null;
    }
    if (action === "disconnect" && session) { session.state = "closed"; pending = null; update(); return null; }
    if (action === "input" && session?.state === "connected") {
      const data = String(payload.data);
      if (data.startsWith("\x1b")) return null;
      for (const char of data) {
        if (char === "\r" || char === "\n") {
          output("\r\n");
          const command = line.trim();
          if (command === "help") output("help   pwd   ls   whoami   date   echo <text>   clear   exit\r\n");
          else if (command === "pwd") output("/home/" + session.username + "\r\n");
          else if (command === "whoami") output(session.username + "\r\n");
          else if (command === "ls") output("\x1b[34mprojects\x1b[0m  \x1b[34mbackups\x1b[0m  README.md\r\n");
          else if (command === "date") output(new Date().toLocaleString() + "\r\n");
          else if (command.startsWith("echo ")) output(command.slice(5) + "\r\n");
          else if (command === "clear") output("\x1b[2J\x1b[H");
          else if (command === "exit") { session.state = "closed"; update(); return null; }
          else if (command) output("Preview: command not available. Type help.\r\n");
          line = ""; prompt();
        } else if (char === "\x03") { output("^C\r\n"); line = ""; prompt(); }
        else if (char === "\x04") { session.state = "closed"; update(); }
        else if (char === "\x7f") { if (line) { line = [...line].slice(0, -1).join(""); output("\b \b"); } }
        else if (char >= " ") { line += char; output(char); }
      }
      return null;
    }
    if (action === "clipboard_read") return navigator.clipboard.readText();
    if (action === "clipboard_write") return navigator.clipboard.writeText(String(payload.text));
    if (["ack", "resize", "install_dependency"].includes(action)) return null;
    throw { code: "unknown_action" };
  };
}
