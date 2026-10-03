import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ChevronRight, CircleAlert, CodeXml, Ellipsis, FolderOpen, KeyRound, LoaderCircle, LockKeyhole, Pencil, Plus, Search, Server, ShieldCheck, Trash2, X } from "lucide-react";
import { call, isPreview, notify, subscribe } from "./bridge";
import { errorText, t } from "./i18n";
import type { AppError, Challenge, Credentials, Dependency, Host, Session, Snapshot } from "./types";
import { ConnectDialog, DeleteDialog, HostDialog, InstallDialog, TrustDialog } from "./components/Dialogs";
import { TerminalPane } from "./components/TerminalPane";
import { Popover } from "./components/Popover";

type Dialog = { kind: "host"; host: Host | null } | { kind: "connect" | "delete"; host: Host } | { kind: "install" } | null;
const live = (session: Session | null) => !!session && !["closed", "error"].includes(session.state);

export default function App() {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [page, setPage] = useState<"hosts" | "terminal">("hosts");
  const [selected, setSelected] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [dependency, setDependency] = useState<Dependency>({ available: true, installing: false, error: null });
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState<AppError | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const menuAnchor = useRef<HTMLButtonElement | null>(null);
  const dimensions = useRef({ cols: 80, rows: 24 });
  const currentSession = useRef<Session | null>(null);
  const host = hosts.find((item) => item.id === selected) || null;
  const shownSession = session?.host_id === selected ? session : null;
  const title = host?.name || shownSession?.name || t("terminal");
  const menuHost = hosts.find((item) => item.id === menu) || null;
  const filtered = hosts.filter((item) => (item.name + " " + item.hostname + " " + item.username).toLowerCase().includes(search.toLowerCase()));

  useEffect(() => {
    const unsubscribe = subscribe((event) => {
      if (event.event === "session") {
        if (currentSession.current?.id !== event.session.id) {
          setSelected(event.session.host_id);
        }
        currentSession.current = event.session;
        setSession(event.session);
        if (event.session.state !== "verifying") setChallenge(null);
        if (event.session.error) setError(event.session.error);
      } else if (event.event === "host_key") setChallenge(event.challenge);
      else if (event.event === "hosts") setHosts(event.hosts);
      else if (event.event === "navigate") {
        const current = currentSession.current;
        if (current && ["connecting", "verifying"].includes(current.state)) notify("disconnect", { session_id: current.id });
        setPage("hosts"); setDialog(null); setMenu(null); setChallenge(null);
      }
      else if (event.event === "dependency") setDependency(event.dependency);
      else if (event.event === "error") setError(event.error);
    });
    call<Snapshot>("bootstrap").then((state) => {
      setHosts(state.hosts); setSession(state.session); currentSession.current = state.session;
      setDependency(state.dependency); setLoading(false);
    }).catch((reason: AppError) => { setError(reason); setLoading(false); });
    const resume = () => {
      if (!document.hidden) call<Snapshot>("resume").then((state) => {
        setHosts(state.hosts); setSession(state.session); currentSession.current = state.session;
      }).catch((reason: AppError) => setError(reason));
    };
    document.addEventListener("visibilitychange", resume);
    return () => { unsubscribe(); document.removeEventListener("visibilitychange", resume); };
  }, []);

  useEffect(() => {
    if (!isPreview) notify("set_page", { page, title });
  }, [page, title]);

  async function perform(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); }
    catch (reason) { setError(reason as AppError); }
    finally { setBusy(false); }
  }
  async function startConnection(target: Host, credentials?: Credentials, remember = false) {
    await perform(async () => {
      try {
        await call("connect", { host_id: target.id, ...dimensions.current,
          ...(credentials ? { credentials, remember } : {}) });
        setDialog(null);
      } catch (reason) {
        const error = reason as AppError;
        if (!credentials && ["credentials_missing", "credentials_unreadable"].includes(error.code)) {
          setDialog({ kind: "connect", host: target });
        }
        throw reason;
      }
    });
    if (credentials) for (const key of Object.keys(credentials)) delete credentials[key as keyof Credentials];
  }
  function openHost(target: Host, changeCredentials = false) {
    setMenu(null); setError(null);
    if (live(session)) {
      if (session?.host_id !== target.id || changeCredentials) { setError({ code: "session_busy" }); return; }
      setSelected(target.id); setPage("terminal"); return;
    }
    if (!dependency.available) { setDialog({ kind: "install" }); return; }
    setSelected(target.id); setPage("terminal");
    if (target.has_credentials && !changeCredentials && !(session?.host_id === target.id && session.error?.code === "authentication_failed")) {
      void startConnection(target);
    } else setDialog({ kind: "connect", host: target });
  }
  async function saveHost(value: Omit<Host, "id"> & { id?: string }) {
    await perform(async () => {
      const result = await call<{ host: Host; hosts: Host[] }>("save_host", value);
      setHosts(result.hosts); setDialog(null); setMenu(null);
    });
  }
  async function login(credentials: Credentials, remember: boolean) {
    if (dialog?.kind === "connect") await startConnection(dialog.host, credentials, remember);
  }
  function answerTrust(accepted: boolean) {
    if (!challenge) return;
    void perform(async () => {
      await call("trust_host", { session_id: challenge.session_id, challenge_id: challenge.id, accepted });
      setChallenge(null);
    });
  }
  function back() {
    const current = currentSession.current;
    if (current && ["connecting", "verifying"].includes(current.state)) notify("disconnect", { session_id: current.id });
    setPage("hosts"); setDialog(null); setMenu(null); setError(null); setChallenge(null);
  }
  function disconnect() {
    if (shownSession) void perform(async () => { await call("disconnect", { session_id: shownSession.id }); });
  }

  return <div className={"workspace" + (isPreview ? " browser" : " native")} data-page={page}>
    <main className="hosts-page" hidden={page !== "hosts"}>
      <header className="hosts-header"><div className="hosts-title"><h1>{t("hosts")}</h1>{!loading && <span className="host-count">{hosts.length}</span>}</div>
        <button className="button primary new-host" disabled={loading} onClick={() => { setError(null); setDialog({ kind: "host", host: null }); }}>
          <Plus size={17} />{t("newHost")}
        </button>
      </header>
      {!dependency.available && <div className="dependency-banner">
        <span><strong>{t("installTitle")}</strong>{t("installNote")}{dependency.error && <small>{dependency.error}</small>}</span>
        <button className="button primary small" disabled={dependency.installing || busy} onClick={() => setDialog({ kind: "install" })}>
          {dependency.installing && <LoaderCircle className="spin" size={15} />}{t(dependency.installing ? "installing" : "install")}
        </button>
      </div>}
      <div className="search"><Search size={18} /><input placeholder={t("search")} value={search} onChange={(event) => setSearch(event.target.value)} />
        {search && <button className="search-clear" title={t("clearSearch")} onClick={() => setSearch("")}><X size={14} /></button>}
      </div>
      {live(session) && !hosts.some((item) => item.id === session?.host_id) && <button className="resume-session" onClick={() => { setSelected(session!.host_id); setPage("terminal"); }}>
        <span className="status-dot connected" />{session?.name}<ArrowRight size={16} />
      </button>}
      <div className="host-list">
        {filtered.map((item) => <div key={item.id} className={"host-row" + (session?.host_id === item.id && live(session) ? " is-live" : "")} data-host-id={item.id}>
          <button className="host-open" disabled={busy || loading} onClick={() => openHost(item)}>
            <span className={"host-symbol tone-" + ((parseInt(item.id.slice(0, 2), 16) || 0) % 4)}><Server size={22} strokeWidth={1.7} /></span>
            <span className="host-copy"><span className="host-name-line"><strong>{item.name}</strong>
              {session?.host_id === item.id && live(session) && <span className={"host-state " + session.state}><span className={"status-dot " + session.state} />{t(session.state)}</span>}
            </span>
              <span className="host-address"><span>{item.username}@</span>{item.hostname}{item.port !== 22 ? ":" + item.port : ""}</span>
              <span className="host-details">
                <span className="host-auth">{item.auth === "key" ? <KeyRound size={12} /> : <LockKeyhole size={12} />}{t(item.auth)}</span>
                {item.has_credentials && <span className="saved-credential"><ShieldCheck size={12} />{t("credentialsSaved")}</span>}
              </span>
            </span>
            <ChevronRight size={16} className="host-chevron" />
          </button>
          <button className="icon-button host-options" title={t("hostOptions")} onClick={(event) => {
            menuAnchor.current = event.currentTarget; setMenu(menu === item.id ? null : item.id);
          }}><Ellipsis size={20} /></button>
        </div>)}
        {!filtered.length && <div className="empty-hosts"><span className="empty-symbol">{loading ? <LoaderCircle className="spin" size={24} /> : <FolderOpen size={25} />}</span>
          <p>{t(loading ? "loading" : hosts.length ? "noMatches" : "emptyHosts")}</p>
          {!loading && !hosts.length && <span>{t("savedHosts")}</span>}
        </div>}
      </div>
      {isPreview && <div className="preview-note"><span><CodeXml size={14} />{t("preview")}</span><p>{t("previewNote")}</p></div>}
    </main>
    <section className="terminal-page" hidden={page !== "terminal"}>
      {isPreview && <header className="terminal-nav">
        <button className="icon-button back-hosts" title={t("hosts")} onClick={back}><ArrowLeft size={19} /></button>
        <strong>{title}</strong><span className="nav-connection"><span className={"status-dot " + (shownSession?.state || "idle")} /></span>
      </header>}
      <div className="terminal-body">
        <TerminalPane session={shownSession} visible={page === "terminal"} onError={setError} onDisconnect={disconnect}
          onSize={(cols, rows) => { dimensions.current = { cols, rows }; }} />
        {shownSession && ["connecting", "verifying"].includes(shownSession.state) && <div className="connection-progress">
          <LoaderCircle className="spin" size={20} /><span>{t(shownSession.state === "verifying" ? "verifyWaiting" : "waiting")}</span>
        </div>}
        {shownSession && !live(shownSession) && <div className="session-ended"><span>{t(shownSession.state)}</span>
          {host && <button onClick={() => openHost(host)}>{t("reconnect")}<ArrowRight size={14} /></button>}
        </div>}
      </div>
    </section>
    {menuHost && menuAnchor.current && <Popover anchor={menuAnchor.current} className="host-menu" onClose={() => setMenu(null)}>
      <div className="popover-caption">{menuHost.name}</div>
      <button onClick={() => { setMenu(null); setDialog({ kind: "host", host: menuHost }); }}><Pencil size={16} />{t("edit")}</button>
      {menuHost.has_credentials && <>
        <button onClick={() => openHost(menuHost, true)}><KeyRound size={16} />{t("changeCredentials")}</button>
        <button onClick={() => void perform(async () => {
          const result = await call<{ hosts: Host[] }>("forget_credentials", { id: menuHost.id });
          setHosts(result.hosts); setMenu(null);
        })}><X size={16} />{t("forgetCredentials")}</button>
      </>}
      <div className="popover-divider" />
      <button className="delete-action" onClick={() => { setMenu(null); setDialog({ kind: "delete", host: menuHost }); }}><Trash2 size={16} />{t("delete")}</button>
    </Popover>}
    {dialog?.kind === "host" && <HostDialog key={dialog.host?.id || "new"} host={dialog.host} busy={busy} onSave={saveHost} onClose={() => setDialog(null)} />}
    {dialog?.kind === "connect" && <ConnectDialog host={dialog.host} busy={busy} onConnect={login} onError={(code) => setError({ code })} onClose={back} />}
    {dialog?.kind === "delete" && <DeleteDialog host={dialog.host} busy={busy} onClose={() => setDialog(null)} onDelete={() => void perform(async () => {
      const result = await call<{ hosts: Host[] }>("delete_host", { id: dialog.host.id });
      setHosts(result.hosts); setDialog(null);
    })} />}
    {challenge && <TrustDialog challenge={challenge} busy={busy} onAnswer={answerTrust} />}
    {dialog?.kind === "install" && <InstallDialog busy={busy} onClose={() => setDialog(null)} onInstall={() => void perform(async () => {
      setDependency(await call<Dependency>("install_dependency", { confirmed: true })); setDialog(null);
    })} />}
    {error && <div className="error-toast"><CircleAlert size={19} /><span>{errorText(error)}</span>
      <button title={t("dismiss")} onClick={() => setError(null)}><X size={17} /></button></div>}
  </div>;
}
