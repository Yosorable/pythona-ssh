import { useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ArrowRight, Download, Eye, EyeOff, FileKey, Fingerprint, KeyRound, LockKeyhole, Server, ShieldCheck, Trash2, X } from "lucide-react";
import { t } from "../i18n";
import type { Challenge, Credentials, Host } from "../types";

export function Modal({ title, subtitle, icon, children, onClose, variant = "default" }: {
  title: string; subtitle?: string; icon: ReactNode; children: ReactNode; onClose: () => void;
  variant?: "default" | "connect" | "trust" | "delete";
}) {
  return <div className="modal-backdrop">
    <section className={"modal modal-" + variant}>
      <header className="modal-header">
        <div className="modal-heading"><span className="modal-icon">{icon}</span><h2>{title}</h2>
          <button className="icon-button close-modal" title={t("cancel")} onClick={onClose}><X size={18} /></button>
        </div>
        {subtitle && <p className="modal-subtitle">{subtitle}</p>}
      </header>
      <div className="modal-body">{children}</div>
    </section>
  </div>;
}

function SecretField({ label, name, value, onChange, placeholder }: {
  label: string; name: string; value: string; onChange: (value: string) => void; placeholder: string;
}) {
  const [visible, setVisible] = useState(false);
  return <label>{label}<span className="secret-input">
    <input name={name} type={visible ? "text" : "password"} autoComplete="off" autoCapitalize="none" spellCheck={false}
      value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    <button type="button" title={t(visible ? "hideSecret" : "showSecret")} onPointerDown={(event) => event.preventDefault()} onClick={() => setVisible(!visible)}>
      {visible ? <EyeOff size={18} /> : <Eye size={18} />}
    </button>
  </span></label>;
}

export function HostDialog({ host, onClose, onSave, busy }: {
  host: Host | null; onClose: () => void; onSave: (host: Omit<Host, "id"> & { id?: string }) => Promise<void>; busy: boolean;
}) {
  const [name, setName] = useState(host?.name || "");
  const [hostname, setHostname] = useState(host?.hostname || "");
  const [port, setPort] = useState(String(host?.port || 22));
  const [username, setUsername] = useState(host?.username || "");
  const [auth, setAuth] = useState<Host["auth"]>(host?.auth || "password");
  function submit(event: FormEvent) {
    event.preventDefault();
    void onSave({ ...(host ? { id: host.id } : {}), name: name.trim(), hostname: hostname.trim(),
      port: Number(port), username: username.trim(), auth });
  }
  return <Modal title={t(host ? "editHost" : "newHost")} subtitle={t("hostFormNote")} icon={<Server size={24} />} onClose={onClose}>
    <form onSubmit={submit}>
      <label>{t("name")}<input name="name" required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} placeholder={t("namePlaceholder")} /></label>
      <div className="field-row">
        <label>{t("hostname")}<input name="hostname" required maxLength={255} autoCapitalize="none" spellCheck={false} value={hostname} onChange={(event) => setHostname(event.target.value)} placeholder={t("hostnamePlaceholder")} /></label>
        <label className="port-field">{t("port")}<input name="port" required type="number" min={1} max={65535} inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value)} /></label>
      </div>
      <label>{t("username")}<input name="username" required maxLength={255} autoCapitalize="none" autoComplete="off" spellCheck={false} value={username} onChange={(event) => setUsername(event.target.value)} placeholder={t("usernamePlaceholder")} /></label>
      <div className="field-label">{t("authentication")}</div>
      <div className="segmented">
        <button type="button" className={auth === "password" ? "selected" : ""} onClick={() => setAuth("password")}><LockKeyhole size={16} />{t("password")}</button>
        <button type="button" className={auth === "key" ? "selected" : ""} onClick={() => setAuth("key")}><KeyRound size={16} />{t("key")}</button>
      </div>
      <div className="modal-footer">
        <button type="button" className="button secondary" disabled={busy} onClick={onClose}>{t("cancel")}</button>
        <button className="button primary" disabled={busy}>{t("save")}<ArrowRight size={16} /></button>
      </div>
    </form>
  </Modal>;
}

export function ConnectDialog({ host, onClose, onConnect, onError, busy }: {
  host: Host; onClose: () => void; onConnect: (credentials: Credentials, remember: boolean) => Promise<void>;
  onError: (code: string) => void; busy: boolean;
}) {
  const [password, setPassword] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [remember, setRemember] = useState(true);
  const file = useRef<HTMLInputElement>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const credentials = host.auth === "password" ? { password } : { private_key: privateKey, passphrase };
    setPassword(""); setPrivateKey(""); setPassphrase("");
    await onConnect(credentials, remember);
  }
  return <Modal variant="connect" title={t("connectTo") + " " + host.name} subtitle={host.username + "@" + host.hostname + ":" + host.port}
    icon={host.auth === "key" ? <KeyRound size={24} /> : <LockKeyhole size={24} />} onClose={onClose}>
    <form onSubmit={(event) => { void submit(event); }} autoComplete="off">
      {host.auth === "password"
        ? <SecretField label={t("password")} name="password" value={password} onChange={setPassword} placeholder={t("passwordPlaceholder")} />
        : <>
          <div className="key-label"><span className="field-label">{t("key")}</span>
            <button className="text-button" type="button" onClick={() => file.current?.click()}><FileKey size={15} />{t("chooseKey")}</button>
          </div>
          <input ref={file} className="file-input" type="file" onChange={async (event) => {
            const chosen = event.target.files?.[0];
            if (chosen) {
              if (chosen.size > 65536) onError("file_too_large");
              else {
                try { setPrivateKey(await chosen.text()); }
                catch { onError("invalid_private_key"); }
              }
            }
            event.target.value = "";
          }} />
          <textarea name="private_key" className="private-key" required autoCapitalize="none" autoComplete="off" spellCheck={false}
            maxLength={65536} value={privateKey} onChange={(event) => setPrivateKey(event.target.value)} placeholder={t("keyPlaceholder")} />
          <SecretField label={t("passphrase")} name="passphrase" value={passphrase} onChange={setPassphrase} placeholder={t("optional")} />
        </>}
      <p className="form-note"><ShieldCheck size={16} />{t(host.auth === "key" ? "keyNote" : "passwordNote")}</p>
      <label className="remember-credentials"><input name="remember" type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
        <span>{t("rememberCredentials")}<small>{t("rememberNote")}</small></span>
      </label>
      <div className="modal-footer">
        <button type="button" className="button secondary" disabled={busy} onClick={onClose}>{t("cancel")}</button>
        <button className="button primary" disabled={busy}>{t("connect")}<ArrowRight size={16} /></button>
      </div>
    </form>
  </Modal>;
}

export function TrustDialog({ challenge, onAnswer, busy }: {
  challenge: Challenge; onAnswer: (accepted: boolean) => void; busy: boolean;
}) {
  return <Modal variant="trust" title={t("trustTitle")} subtitle={challenge.hostname} icon={<Fingerprint size={24} />} onClose={() => onAnswer(false)}>
    <p className="trust-copy">{t("trustNote")}</p>
    <div className="fingerprint-box">
      <span>{t("fingerprint")}</span><code>{challenge.fingerprint}</code>
      <div>{t("algorithm")}<strong>{challenge.algorithm}</strong></div>
    </div>
    <div className="modal-footer">
      <button className="button secondary" disabled={busy} onClick={() => onAnswer(false)}>{t("cancel")}</button>
      <button className="button primary" disabled={busy} onClick={() => onAnswer(true)}><ShieldCheck size={16} />{t("trust")}</button>
    </div>
  </Modal>;
}

export function DeleteDialog({ host, onClose, onDelete, busy }: {
  host: Host; onClose: () => void; onDelete: () => void; busy: boolean;
}) {
  return <Modal variant="delete" title={t("deleteTitle")} subtitle={host.name} icon={<Trash2 size={22} />} onClose={onClose}>
    <p className="trust-copy">{t("deleteNote")}</p>
    <div className="modal-footer">
      <button className="button secondary" disabled={busy} onClick={onClose}>{t("cancel")}</button>
      <button className="button danger" disabled={busy} onClick={onDelete}>{t("remove")}</button>
    </div>
  </Modal>;
}

export function InstallDialog({ onClose, onInstall, busy }: {
  onClose: () => void; onInstall: () => void; busy: boolean;
}) {
  return <Modal title={t("installConfirmTitle")} subtitle={t("installConfirmNote")} icon={<Download size={24} />} onClose={onClose}>
    <div className="install-package"><span>Paramiko</span><code>5.0.0</code></div>
    <p className="form-note">{t("installDependencies")}</p>
    <div className="modal-footer">
      <button className="button secondary" disabled={busy} onClick={onClose}>{t("cancel")}</button>
      <button className="button primary" disabled={busy} onClick={onInstall}><Download size={15} />{t("confirmInstall")}</button>
    </div>
  </Modal>;
}
