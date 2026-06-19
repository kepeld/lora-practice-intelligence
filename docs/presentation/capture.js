// One-off: capture dashboard screenshots for the deck via system Edge.
//   EDGE_PATH="...msedge.exe" node capture.js
// Requires the app on 127.0.0.1:8099 (+ Qdrant and ANTHROPIC_API_KEY for Ask).
const puppeteer = require("puppeteer-core");

const EDGE = process.env.EDGE_PATH;
const BASE = "http://127.0.0.1:8099";
const OUT = __dirname + "/assets";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars"],
    defaultViewport: { width: 1440, height: 900, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();

  // 1. Insights (default view)
  await page.goto(BASE, { waitUntil: "networkidle2" });
  await page.waitForSelector(".card", { timeout: 30000 });
  await sleep(700);
  await page.screenshot({ path: OUT + "/app_insights.png" });
  console.log("app_insights.png");

  // 2. Evidence drawer
  await page.click(".card");
  await page.waitForSelector(".drawer.open .evidence", { timeout: 20000 });
  await sleep(500);
  await page.screenshot({ path: OUT + "/app_evidence.png" });
  console.log("app_evidence.png");
  await page.keyboard.press("Escape");
  await sleep(300);

  // 3. Search results
  await page.evaluate(() => document.querySelector("#search").scrollIntoView());
  await page.click("#search-input", { clickCount: 3 });
  await page.type("#search-input", "8-bit adamw optimizer for qlora");
  await page.click("#search-btn");
  await page.waitForSelector("#search-out .result", { timeout: 30000 });
  await sleep(500);
  await page.evaluate(() => document.querySelector("#search").scrollIntoView());
  await page.screenshot({ path: OUT + "/app_search.png" });
  console.log("app_search.png");

  // 4. Ask (RAG) — formatted answer
  await page.click("#search-input", { clickCount: 3 });
  await page.type("#search-input", "which optimizer do successful qlora fine-tunes use?");
  await page.click("#ask-btn");
  await page.waitForSelector(".answer .md", { timeout: 90000 });
  await sleep(900);
  await page.evaluate(() => document.querySelector(".answer").scrollIntoView());
  await sleep(200);
  await page.screenshot({ path: OUT + "/app_ask.png" });
  console.log("app_ask.png");

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
