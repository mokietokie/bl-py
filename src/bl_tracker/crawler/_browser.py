from __future__ import annotations
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, BrowserContext

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

# Bot-detection bypass: keep these three properties consistent with a real Chrome.
# Verified against Maersk/COSCO/HMM/KMTC tracking pages on 2026-04-27.
_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
"""


@asynccontextmanager
async def browser_context(headless: bool = True):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx: BrowserContext = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="Asia/Seoul",
        )
        await ctx.add_init_script(_INIT_SCRIPT)
        try:
            yield ctx
        finally:
            await ctx.close()
            await browser.close()
