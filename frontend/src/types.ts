export type Host = {
  id: string;
  name: string;
  hostname: string;
  username: string;
  port: number;
  auth: "password" | "key";
  has_credentials?: boolean;
};
export type AppError = { code: string; detail?: string };
export type Session = {
  id: string;
  host_id: string;
  name: string;
  hostname: string;
  username: string;
  port: number;
  state: "connecting" | "verifying" | "connected" | "closed" | "error";
  error: AppError | null;
};
export type Challenge = {
  id: string;
  session_id: string;
  hostname: string;
  algorithm: string;
  fingerprint: string;
};
export type Dependency = { available: boolean; installing: boolean; error: string | null };
export type Snapshot = { hosts: Host[]; session: Session | null; dependency: Dependency };
export type BridgeEvent =
  | { event: "session"; session: Session }
  | { event: "output"; session_id: string; seq: number; data: string }
  | { event: "host_key"; challenge: Challenge }
  | { event: "dependency"; dependency: Dependency }
  | { event: "hosts"; hosts: Host[] }
  | { event: "navigate"; page: "hosts" }
  | { event: "error"; error: AppError };
export type Credentials = { password?: string; private_key?: string; passphrase?: string };
export type Request = { id: number; action: string; payload?: Record<string, unknown> };
export type Reply = { id: number; result?: unknown; error?: AppError };

declare global {
  interface Window {
    PYTHONA_SSH?: { mode: "native" | "preview"; language: string };
    webkit?: { messageHandlers?: { ssh?: { postMessage: (body: string) => void } } };
    sshBridge: { receive: (messages: (Reply | BridgeEvent)[]) => void };
  }
}
