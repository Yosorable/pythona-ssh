import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Copy, Clipboard, Ellipsis, Eraser, Minus, Plus, Unplug } from "lucide-react";
import { call, notify, subscribe } from "../bridge";
import { t } from "../i18n";
import type { AppError, Session } from "../types";
import { Popover } from "./Popover";
import "@xterm/xterm/css/xterm.css";

type Props = {
  session: Session | null;
  visible: boolean;
  onError: (error: AppError | null) => void;
  onDisconnect: () => void;
  onSize: (cols: number, rows: number) => void;
};

export function TerminalPane({ session, visible, onError, onDisconnect, onSize }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const term = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const current = useRef<Session | null>(null);
  const control = useRef(false);
  const [ctrl, setCtrl] = useState(false);
  const [menu, setMenu] = useState(false);
  const menuAnchor = useRef<HTMLButtonElement>(null);
  const [size, setSize] = useState({ cols: 80, rows: 24 });
  const callbacks = useRef({ onError, onSize });
  callbacks.current = { onError, onSize };
  const active = session?.state === "connected";

  useEffect(() => {
    if (!visible) { term.current?.blur(); setMenu(false); }
  }, [visible]);

  useEffect(() => {
    if (!container.current) return;
    const terminal = new Terminal({
      cursorBlink: true, cursorStyle: "bar", fontFamily: 'Menlo, "SFMono-Regular", Consolas, monospace',
      fontSize: 13, lineHeight: 1.25, scrollback: 5000, allowProposedApi: false,
      theme: {
        background: "#11151c", foreground: "#d6dfed", cursor: "#8ba5ff", cursorAccent: "#11151c",
        selectionBackground: "#304566", black: "#1d2532", red: "#ee8892", green: "#78c9a5",
        yellow: "#e3c489", blue: "#89adf2", magenta: "#bd9ade", cyan: "#7dc8d6", white: "#d4ddeb",
        brightBlack: "#728198", brightRed: "#f3a1a8", brightGreen: "#98dfb7", brightYellow: "#eed5a3",
        brightBlue: "#a9c5fb", brightMagenta: "#d0b3eb", brightCyan: "#a0deeb", brightWhite: "#f2f5fa",
      },
    });
    const addon = new FitAddon();
    terminal.loadAddon(addon);
    terminal.open(container.current);
    term.current = terminal;
    fit.current = addon;
    const reportSize = () => {
      const cols = Math.max(2, terminal.cols);
      const rows = Math.max(1, terminal.rows);
      setSize({ cols, rows });
      callbacks.current.onSize(cols, rows);
      if (current.current && !["closed", "error"].includes(current.current.state)) {
        notify("resize", { session_id: current.current.id, cols, rows });
      }
    };
    const resize = () => {
      if (!container.current?.clientWidth || !container.current.clientHeight) return;
      addon.fit();
      reportSize();
    };
    const sizeChanges = terminal.onResize(reportSize);
    const observer = new ResizeObserver(resize);
    observer.observe(container.current);
    const data = terminal.onData((text) => {
      if (current.current?.state !== "connected") return;
      if (control.current && text.length === 1) {
        const code = text.toUpperCase().charCodeAt(0);
        if (code >= 64 && code <= 95) text = String.fromCharCode(code - 64);
        else if (text === "?") text = "\x7f";
      }
      control.current = false;
      setCtrl(false);
      // Chunk by Unicode code points so neither UTF-16 pairs nor UTF-8 bytes split.
      const points = Array.from(text);
      for (let index = 0; index < points.length; index += 4096) {
        notify("input", { session_id: current.current.id, data: points.slice(index, index + 4096).join("") });
      }
    });
    const unsubscribe = subscribe((event) => {
      if (event.event === "session") {
        if (current.current?.id !== event.session.id) {
          // Reset in stream order; old queued writes must precede this reset.
          terminal.write("\x1bc");
          control.current = false;
          setCtrl(false);
        }
        current.current = event.session;
        terminal.options.disableStdin = event.session.state !== "connected";
      } else if (event.event === "output" && event.session_id === current.current?.id) {
        const bytes = Uint8Array.from(atob(event.data), (char) => char.charCodeAt(0));
        terminal.write(bytes, () => {
          if (current.current?.id === event.session_id) {
            notify("ack", { session_id: event.session_id, seq: event.seq });
          }
        });
      }
    });
    resize();
    return () => { unsubscribe(); observer.disconnect(); data.dispose(); sizeChanges.dispose(); terminal.dispose(); term.current = null; fit.current = null; };
  }, []);

  const send = (text: string) => {
    if (current.current?.state === "connected") notify("input", { session_id: current.current.id, data: text });
    term.current?.focus();
  };
  async function copy() {
    const text = term.current?.getSelection();
    if (!text) { onError({ code: "selectFirst" }); return; }
    try { await call("clipboard_write", { text }); }
    catch { onError({ code: "clipboard_failed" }); }
  }
  async function paste() {
    try {
      const text = await call<string>("clipboard_read");
      term.current?.paste(text);
      term.current?.focus();
    } catch { onError({ code: "clipboard_failed" }); }
  }
  function font(delta: number) {
    if (!term.current) return;
    term.current.options.fontSize = Math.min(24, Math.max(10, (term.current.options.fontSize || 13) + delta));
    fit.current?.fit();
  }

  return <div className="terminal-pane" data-cols={size.cols} data-rows={size.rows} data-state={session?.state || "idle"}>
    <div className="terminal-surface" ref={container} data-testid="terminal" />
    <div className="keybar">
      <div className="keys">
        <button disabled={!active} onPointerDown={(event) => event.preventDefault()} onClick={() => send("\x1b")}>esc</button>
        <button disabled={!active} onPointerDown={(event) => event.preventDefault()} onClick={() => send("\t")}>tab</button>
        <button disabled={!active} className={ctrl ? "pressed" : ""} onPointerDown={(event) => event.preventDefault()}
          onClick={() => { control.current = !control.current; setCtrl(control.current); term.current?.focus(); }}>ctrl</button>
        <span className="key-separator" />
        <button disabled={!active} onPointerDown={(event) => event.preventDefault()} onClick={() => send("\x1b[D")}><ArrowLeft size={16} /></button>
        <button disabled={!active} onPointerDown={(event) => event.preventDefault()} onClick={() => send("\x1b[A")}><ArrowUp size={16} /></button>
        <button disabled={!active} onPointerDown={(event) => event.preventDefault()} onClick={() => send("\x1b[B")}><ArrowDown size={16} /></button>
        <button disabled={!active} onPointerDown={(event) => event.preventDefault()} onClick={() => send("\x1b[C")}><ArrowRight size={16} /></button>
      </div>
      <div className="terminal-menu-anchor">
        <span className={"status-dot " + (session?.state || "idle")} />
        <button ref={menuAnchor} className="terminal-options" title={t("terminalOptions")} onClick={() => setMenu(!menu)}><Ellipsis size={19} /></button>
        {menu && visible && menuAnchor.current && <Popover anchor={menuAnchor.current} className="terminal-menu" onClose={() => setMenu(false)}>
          <div className="terminal-menu-status"><span><span className={"status-dot " + (session?.state || "idle")} />{session ? t(session.state) : t("idle")}</span><code>{size.cols} × {size.rows}</code></div>
          <button onClick={() => { setMenu(false); void copy(); }}><Copy size={16} />{t("copy")}</button>
          <button disabled={!active} onClick={() => { setMenu(false); void paste(); }}><Clipboard size={16} />{t("paste")}</button>
          <button onClick={() => { setMenu(false); term.current?.clear(); }}><Eraser size={16} />{t("clear")}</button>
          <div className="font-controls"><span>{t("fontSize")}</span>
            <button title={t("smaller")} onClick={() => font(-1)}><Minus size={15} /></button>
            <button title={t("larger")} onClick={() => font(1)}><Plus size={15} /></button>
          </div>
          <button className="disconnect" disabled={!session || ["closed", "error"].includes(session.state)}
            onClick={() => { setMenu(false); onDisconnect(); }}><Unplug size={16} />{t("disconnect")}</button>
        </Popover>}
      </div>
    </div>
  </div>;
}
