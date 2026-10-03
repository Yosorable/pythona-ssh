import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const row = (page: Page, name = "Development") => page.locator(".host-row", { hasText: name });
const terminal = (page: Page) => page.locator(".terminal-pane");

async function openHost(page: Page, name = "Development") {
  await row(page, name).locator(".host-open").click();
  await expect(page.locator(".workspace")).toHaveAttribute("data-page", "terminal");
}
async function login(page: Page, remember = true, trust = true) {
  await page.locator('input[name="password"]').fill("preview-password");
  await page.locator('input[name="remember"]').setChecked(remember);
  await page.locator(".modal-footer .primary").click();
  if (trust) {
    await expect(page.locator(".fingerprint-box")).toBeVisible();
    await page.locator(".modal-footer .primary").click();
  }
  await expect(terminal(page)).toHaveAttribute("data-state", "connected");
}
async function disconnect(page: Page) {
  await page.locator(".terminal-options").click();
  await page.locator(".terminal-menu .disconnect").click();
  await expect(terminal(page)).toHaveAttribute("data-state", "closed");
}
async function nativePage(page: Page) {
  await page.route("**/*", async (route) => {
    if (route.request().resourceType() !== "document") return route.continue();
    const response = await route.fetch();
    await route.fulfill({ response, body: (await response.text()).replace('"mode": "preview"', '"mode": "native"') });
  });
}

test("home lists hosts; cancelling, saving, editing and deleting profiles", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator(".hosts-page")).toBeVisible();
  await expect(page.locator(".terminal-page")).not.toBeVisible();
  await expect(page.locator(".host-row")).toHaveCount(2);
  await page.locator(".new-host").click();
  await page.locator('input[name="name"]').fill("Discard this draft");
  await page.locator(".close-modal").click();
  await expect(page.locator(".host-row")).toHaveCount(2);
  await page.locator(".new-host").click();
  await page.locator('input[name="name"]').fill("Staging");
  await page.locator('input[name="hostname"]').fill("staging.example.com");
  await page.locator('input[name="username"]').fill("deploy");
  await page.locator(".modal-footer .primary").click();
  await expect(page.locator(".host-row")).toHaveCount(3);
  await row(page, "Staging").locator(".host-options").click();
  await page.locator(".host-menu button").first().click();
  await page.locator('input[name="name"]').fill("Staging renamed");
  await page.locator(".modal-footer .primary").click();
  await expect(row(page, "Staging renamed")).toBeVisible();
  await row(page, "Staging renamed").locator(".host-options").click();
  await page.locator(".delete-action").click();
  await page.locator(".modal-footer .danger").click();
  await expect(page.locator(".host-row")).toHaveCount(2);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("terminal uses the page; typing, Ctrl, font size and saved reconnection", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await openHost(page);
  await login(page);
  const bounds = await page.locator(".terminal-surface").boundingBox();
  const viewport = page.viewportSize()!;
  expect(bounds!.width).toBeGreaterThan(viewport.width - 5);
  expect(bounds!.height).toBeGreaterThan(viewport.height * .87);
  await expect(page.locator(".terminal-heading, .terminal-footer, .sidebar")).toHaveCount(0);
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("pwd");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("/home/alex");
  await page.locator(".keys button", { hasText: "ctrl" }).click();
  await page.keyboard.type("c");
  await expect(page.locator(".xterm-rows")).toContainText("^C");
  const oldRows = await terminal(page).getAttribute("data-rows");
  await page.locator(".terminal-options").click();
  await page.locator('.font-controls button[title="Larger text"]').click();
  await expect(terminal(page)).not.toHaveAttribute("data-rows", oldRows!);
  await page.locator(".terminal-menu .disconnect").click();
  await expect(page.locator(".session-ended")).toBeVisible();
  await page.locator(".session-ended button").click();
  await expect(terminal(page)).toHaveAttribute("data-state", "connected");
  await expect(page.locator('input[name="password"], .fingerprint-box')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("back preserves the session and terminal output", async ({ page }) => {
  await page.goto("/");
  await openHost(page);
  await login(page);
  await page.locator(".xterm-helper-textarea").focus();
  await page.keyboard.type("echo retained-output");
  await page.keyboard.press("Enter");
  await expect(page.locator(".xterm-rows")).toContainText("retained-output");
  await page.locator(".back-hosts").click();
  await expect(page.locator(".hosts-page")).toBeVisible();
  await expect(row(page)).toContainText("Credentials saved");
  await expect(row(page).locator(".status-dot.connected")).toBeVisible();
  await openHost(page);
  await expect(page.locator(".xterm-rows")).toContainText("retained-output");
  await expect(page.locator(".modal")).toHaveCount(0);
});

test("not remembering and forgetting both require a new prompt", async ({ page }) => {
  await page.goto("/");
  await openHost(page);
  await login(page, false);
  await disconnect(page);
  await page.locator(".session-ended button").click();
  await login(page, true, false);
  await page.locator(".back-hosts").click();
  await row(page).locator(".host-options").click();
  await page.locator(".host-menu button", { hasText: "Forget credentials" }).click();
  await expect(row(page)).not.toContainText("Credentials saved");
  await openHost(page);
  await disconnect(page);
  await page.locator(".session-ended button").click();
  await expect(page.locator('input[name="password"]')).toBeVisible();
  await expect(page.locator('input[name="password"]')).toHaveValue("");
});

test("rejecting the host does not save credentials", async ({ page }) => {
  await page.goto("/");
  await openHost(page);
  await page.locator('input[name="password"]').fill("not-saved");
  await page.locator(".modal-footer .primary").click();
  await expect(page.locator(".fingerprint-box")).toBeVisible();
  await page.locator(".modal-footer .secondary").click();
  await expect(terminal(page)).toHaveAttribute("data-state", "closed");
  await page.locator(".back-hosts").click();
  await expect(row(page)).not.toContainText("Credentials saved");
});

test("private-key drafts clear when cancelled", async ({ page }) => {
  await page.goto("/");
  await openHost(page, "Home server");
  await page.locator('textarea[name="private_key"]').fill("PRIVATE-KEY-DRAFT");
  await page.locator('input[name="passphrase"]').fill("secret");
  await page.locator('.secret-input button').click();
  await expect(page.locator('input[name="passphrase"]')).toHaveAttribute("type", "text");
  await expect(page.locator('input[name="passphrase"]')).toHaveValue("secret");
  await page.locator(".close-modal").click();
  await expect(page.locator(".hosts-page")).toBeVisible();
  await openHost(page, "Home server");
  await expect(page.locator('textarea[name="private_key"]')).toHaveValue("");
  await expect(page.locator('input[name="passphrase"]')).toHaveValue("");
  await expect(page.locator('input[name="passphrase"]')).toHaveAttribute("type", "password");
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
});

test("host menus remain usable at the end of a long list", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 420 });
  await page.goto("/");
  await expect(page.locator(".host-row")).toHaveCount(2);
  await page.evaluate(() => window.sshBridge.receive([{ event: "hosts", hosts: Array.from({ length: 24 }, (_, index) => ({
    id: String(index), name: `Server ${index} — ${"long name ".repeat(20)}`, hostname: "subdomain.".repeat(15) + "example.com",
    port: 2222, username: "remote-username", auth: "key", has_credentials: true,
  })) }]));
  await expect(page.locator(".host-row")).toHaveCount(24);
  const last = page.locator(".host-row").last();
  await last.locator(".host-options").click();
  const menu = page.locator(".host-menu");
  await expect(menu).toBeVisible();
  const bounds = (await menu.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(420);
  await menu.locator(".delete-action").click();
  await expect(page.locator(".modal-delete")).toContainText("Server 23");
  await page.locator(".modal-footer .secondary").click();
  await last.locator(".host-options").click();
  await page.mouse.click(4, 4);
  await expect(menu).toHaveCount(0);
  expect(await page.locator(".hosts-page").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
});

test("forms and terminal options fit a keyboard-sized viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 320 });
  await page.goto("/");
  await page.locator(".new-host").click();
  const name = "Long server name ".repeat(14);
  await page.locator('input[name="name"]').fill(name);
  await page.locator('input[name="hostname"]').fill("subdomain.".repeat(20) + "example.com");
  await page.locator('input[name="username"]').fill("tester");
  await page.locator(".modal-footer .primary").click();
  await expect(page.locator(".host-row")).toHaveCount(3);
  await openHost(page, name.trim());
  await login(page);
  await page.locator(".terminal-options").click();
  const menu = page.locator(".terminal-menu");
  const bounds = (await menu.boundingBox())!;
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(320);
  await menu.locator(".disconnect").click();
  await expect(terminal(page)).toHaveAttribute("data-state", "closed");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("native navigation and streaming continue on the host list", async ({ page }) => {
  await nativePage(page);
  await page.addInitScript(() => {
    const requests: { action: string; payload?: Record<string, unknown> }[] = [];
    (window as unknown as { nativeRequests: typeof requests }).nativeRequests = requests;
    const host = { id: "host", name: "Native", hostname: "example.com", username: "tester", port: 22, auth: "password", has_credentials: true };
    window.webkit = { messageHandlers: { ssh: { postMessage(body: string) {
      const message = JSON.parse(body);
      requests.push(message);
      if (message.action === "bootstrap") {
        setTimeout(() => window.sshBridge.receive([{ id: message.id, result: {
          hosts: [host], session: null, dependency: { available: true, installing: false, error: null },
        } }]), 0);
      } else if (message.action === "connect") {
        setTimeout(() => window.sshBridge.receive([
          { event: "session", session: { id: "native-session", host_id: host.id, name: host.name, hostname: host.hostname,
            username: host.username, port: 22, state: "connected", error: null } },
          { id: message.id, result: null },
        ]), 0);
      }
    } } } };
  });
  await page.goto("/");
  await openHost(page, "Native");
  await expect(terminal(page)).toHaveAttribute("data-state", "connected");
  await expect(page.locator(".terminal-nav")).toHaveCount(0);
  await page.evaluate(() => {
    const bytes = new TextEncoder().encode("你好 🐍\r\n");
    window.sshBridge.receive([
      { event: "output", session_id: "native-session", seq: 2, data: btoa(String.fromCharCode(...bytes.slice(0, 2))) },
      { event: "output", session_id: "native-session", seq: bytes.length, data: btoa(String.fromCharCode(...bytes.slice(2))) },
    ]);
  });
  await expect(page.locator(".xterm-rows")).toContainText("你好 🐍");
  await page.evaluate(() => window.sshBridge.receive([
    { event: "navigate", page: "hosts" },
    { event: "output", session_id: "native-session", seq: 50, data: btoa("background-output\r\n") },
  ]));
  await expect(page.locator(".hosts-page")).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as unknown as { nativeRequests: { action: string }[] }).nativeRequests.filter((item) => item.action === "ack").length)).toBe(3);
  await openHost(page, "Native");
  await expect(page.locator(".xterm-rows")).toContainText("background-output");
  const requests = await page.evaluate(() => (window as unknown as { nativeRequests: { action: string; payload?: Record<string, unknown> }[] }).nativeRequests);
  expect(requests.filter((entry) => entry.action === "ack").map((entry) => entry.payload?.seq)).toEqual([2, new TextEncoder().encode("你好 🐍\r\n").length, 50]);
  expect(requests.filter((entry) => entry.action === "connect")).toHaveLength(1);
  expect(requests.some((entry) => entry.action === "set_page" && entry.payload?.page === "hosts")).toBe(true);
  expect(requests.some((entry) => entry.action === "set_page" && entry.payload?.page === "terminal")).toBe(true);
});

test("dependency installation requires confirmation", async ({ page }) => {
  await nativePage(page);
  await page.addInitScript(() => {
    const installs: Record<string, unknown>[] = [];
    (window as unknown as { installs: typeof installs }).installs = installs;
    window.webkit = { messageHandlers: { ssh: { postMessage(body: string) {
      const message = JSON.parse(body);
      if (message.action === "bootstrap") {
        setTimeout(() => window.sshBridge.receive([{ id: message.id, result: {
          hosts: [], session: null, dependency: { available: false, installing: false, error: null },
        } }]), 0);
      } else if (message.action === "install_dependency") {
        installs.push(message.payload);
        setTimeout(() => window.sshBridge.receive([{ id: message.id, result: {
          available: true, installing: false, error: null,
        } }]), 0);
      }
    } } } };
  });
  await page.goto("/");
  await page.locator(".dependency-banner button").click();
  await expect(page.locator(".install-package")).toContainText("Paramiko");
  await page.locator(".modal-footer .secondary").click();
  expect(await page.evaluate(() => (window as unknown as { installs: unknown[] }).installs)).toEqual([]);
  await page.locator(".dependency-banner button").click();
  await page.locator(".modal-footer .primary").click();
  await expect(page.locator(".dependency-banner")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { installs: unknown[] }).installs)).toEqual([{ confirmed: true }]);
});
