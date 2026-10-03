import type { AppError, BridgeEvent, Reply, Request } from "./types";
import { createPreview } from "./preview";

type Listener = (event: BridgeEvent) => void;
const listeners = new Set<Listener>();
const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: AppError) => void; timer: number }>();
let nextID = 0;

export const isPreview = window.PYTHONA_SSH?.mode !== "native";
const publish = (event: BridgeEvent) => { for (const listener of listeners) listener(event); };
const preview = isPreview ? createPreview(publish) : null;

window.sshBridge = {
  receive(messages) {
    for (const message of messages) {
      if ("event" in message) {
        publish(message);
        continue;
      }
      const reply = message as Reply;
      if (!reply.id) {
        if (reply.error) publish({ event: "error", error: reply.error });
        continue;
      }
      const entry = pending.get(reply.id);
      if (!entry) continue;
      window.clearTimeout(entry.timer);
      pending.delete(reply.id);
      if (reply.error) entry.reject(reply.error);
      else entry.resolve(reply.result);
    }
  },
};

function send(request: Request) {
  const handler = window.webkit?.messageHandlers?.ssh;
  if (!handler) throw { code: "bridge_unavailable" };
  handler.postMessage(JSON.stringify(request));
}

export function call<T>(action: string, payload: Record<string, unknown> = {}): Promise<T> {
  if (preview) return preview(action, payload) as Promise<T>;
  return new Promise<T>((resolve, reject) => {
    const id = ++nextID;
    const timer = window.setTimeout(() => {
      pending.delete(id);
      reject({ code: "bridge_timeout" });
    }, 20000);
    pending.set(id, { resolve: (value) => resolve(value as T), reject, timer });
    try { send({ id, action, payload }); }
    catch (error) {
      pending.delete(id);
      window.clearTimeout(timer);
      reject(error);
    }
  });
}

export function notify(action: string, payload: Record<string, unknown>) {
  if (preview) {
    preview(action, payload).catch((error: AppError) => publish({ event: "error", error }));
  } else {
    try { send({ id: 0, action, payload }); }
    catch (error) { publish({ event: "error", error: error as AppError }); }
  }
}

export function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
