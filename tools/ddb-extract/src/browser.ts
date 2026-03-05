import { chromium, Browser, Page } from "playwright";

export async function connectCDP(cdpUrl: string): Promise<Browser> {
  try {
    return await chromium.connectOverCDP(cdpUrl);
  } catch (err) {
    console.error(
      `\nFailed to connect to Chrome at ${cdpUrl}\n` +
        `\nStart Chrome with the debug port open:\n` +
        `  google-chrome --remote-debugging-port=9222 --profile-directory=Default\n` +
        `  # or on macOS:\n` +
        `  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222 --profile-directory=Default\n`
    );
    throw err;
  }
}

export function getPage(browser: Browser): Page {
  const contexts = browser.contexts();
  if (contexts.length === 0) throw new Error("No browser contexts found");
  const pages = contexts[0].pages();
  if (pages.length === 0) throw new Error("No pages found in browser context");
  return pages[0];
}

export function sleep(ms: number, jitter = true): Promise<void> {
  const delta = jitter ? Math.floor(Math.random() * 400) - 200 : 0;
  return new Promise((resolve) => setTimeout(resolve, ms + delta));
}
