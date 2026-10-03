import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 20000,
  fullyParallel: true,
  use: { baseURL: "http://127.0.0.1:8878", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop-chrome", use: { browserName: "chromium", channel: "chrome", viewport: { width: 1280, height: 850 } } },
    { name: "mobile-webkit", use: { browserName: "webkit", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: { command: "python3 ../main.py --preview --port 8878", url: "http://127.0.0.1:8878", reuseExistingServer: false },
});
