from __future__ import annotations
import argparse, asyncio, json, re, sys
from datetime import datetime
from typing import Any

from playwright.async_api import (
    BrowserContext, Page, TimeoutError as PWTimeout,
)

from ._browser import browser_context

URL = "https://www.track-trace.com/bol"
RENDER_TIMEOUT_MS = 30_000

BL_INPUT          = 'form#bolform input[name="number"]'
SUBMIT_BTN        = 'form#bolform input[type="submit"][name="commit"]'
RESULT_FRAME      = 'iframe.track_res_frame'
ACTIVE_CARRIER    = 'wc-multi-track-tab[data-tab-active="true"]'

FULLSCREEN_CARRIERS = ("HMM", "COSCO")
_FULLSCREEN_LINK_RE = re.compile(
    r"show\s+.+?results?\s+without\s+frame", re.IGNORECASE
)


# ──────────────────────────── Router (async) ────────────────────────────

async def _submit(ctx: BrowserContext, bl_no: str) -> Page:
    page = await ctx.new_page()
    await page.goto(URL, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS)
    await page.locator(BL_INPUT).fill(bl_no)
    async with ctx.expect_page(timeout=RENDER_TIMEOUT_MS) as info:
        await page.locator(SUBMIT_BTN).click()
    result = await info.value
    await result.wait_for_load_state("domcontentloaded", timeout=RENDER_TIMEOUT_MS)
    return result


async def _carrier_name(result: Page) -> str | None:
    try:
        el = result.locator(ACTIVE_CARRIER).first
        return await el.get_attribute("data-text")
    except Exception:
        return None


async def _dismiss_cookies(frame_or_page) -> None:
    for sel in (
        'button:has-text("Allow all")',
        'button:has-text("Essential only")',
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
    ):
        try:
            btn = frame_or_page.locator(sel).first
            await btn.wait_for(state="visible", timeout=2_000)
            await btn.click(timeout=2_000)
            return
        except Exception:
            continue


async def _read_iframe(result: Page, bl_no: str, carrier: str | None) -> str:
    iframe_el = await result.wait_for_selector(RESULT_FRAME, timeout=RENDER_TIMEOUT_MS)
    frame = await iframe_el.content_frame()
    assert frame is not None
    try:
        await frame.wait_for_load_state("domcontentloaded", timeout=RENDER_TIMEOUT_MS)
    except PWTimeout:
        pass
    await _dismiss_cookies(frame)
    if carrier and ("KMTC" in carrier or "Korea Marine Transport" in carrier):
        await _kmtc_resubmit(frame, bl_no)
    try:
        await frame.wait_for_function(
            """() => {
                const t = (document.body && document.body.innerText) || '';
                const u = t.toLowerCase();
                return u.includes('vessel arrival')
                    || u.includes('estimated arrival')
                    || u.includes('arrival(etb)')
                    || u.includes('discharging port')
                    || u.includes('busan') || u.includes('incheon')
                    || u.includes('no results found')
                    || u.includes('access denied');
            }""",
            timeout=RENDER_TIMEOUT_MS,
        )
    except PWTimeout:
        pass
    return await frame.evaluate("() => document.body ? document.body.innerText : ''")


async def _kmtc_resubmit(frame, bl_no: str) -> None:
    inputs = frame.locator('input[type="text"]:not([readonly])')
    n = await inputs.count()
    for i in range(n):
        el = inputs.nth(i)
        try:
            if not await el.is_visible():
                continue
            cur = (await el.input_value()) or ""
            if cur and cur != bl_no:
                continue
            if cur != bl_no:
                await el.fill(bl_no)
            await el.press("Enter")
            return
        except Exception:
            continue


async def _follow_fullscreen(ctx: BrowserContext, result: Page, bl_no: str) -> str:
    link = result.get_by_text(_FULLSCREEN_LINK_RE).first
    if await link.count() == 0:
        return ""
    try:
        async with ctx.expect_page(timeout=RENDER_TIMEOUT_MS) as info:
            await link.click()
        carrier_page = await info.value
    except PWTimeout:
        return ""
    await carrier_page.wait_for_load_state("domcontentloaded", timeout=RENDER_TIMEOUT_MS)

    if "elines.coscoshipping.com" in carrier_page.url:
        digits = re.sub(r"\D", "", bl_no)
        fixed = re.sub(r"(number=)S?\d+", r"\g<1>" + digits, carrier_page.url)
        if fixed != carrier_page.url:
            try:
                await carrier_page.goto(fixed, wait_until="domcontentloaded",
                                         timeout=RENDER_TIMEOUT_MS)
            except PWTimeout:
                pass
        await _dismiss_cookies(carrier_page)
    try:
        await carrier_page.wait_for_load_state("networkidle", timeout=RENDER_TIMEOUT_MS)
    except PWTimeout:
        pass

    # COSCO renders results inside iframe#scctCargoTracking. Drill into it if present.
    target = carrier_page
    try:
        scct_el = await carrier_page.wait_for_selector(
            "iframe#scctCargoTracking", timeout=8_000
        )
        scct_frame = await scct_el.content_frame()
        if scct_frame is not None:
            try:
                await scct_frame.wait_for_load_state(
                    "domcontentloaded", timeout=RENDER_TIMEOUT_MS
                )
            except PWTimeout:
                pass
            try:
                await scct_frame.wait_for_load_state(
                    "networkidle", timeout=RENDER_TIMEOUT_MS
                )
            except PWTimeout:
                pass
            target = scct_frame
    except PWTimeout:
        pass

    # Wait for tracking content keywords to appear before scraping
    try:
        await target.wait_for_function(
            """() => {
                const t = (document.body && document.body.innerText) || '';
                const u = t.toLowerCase();
                return u.includes('last pod')
                    || u.includes('arrival(etb)')
                    || u.includes('estimated arrival')
                    || u.includes('vessel arrival')
                    || u.includes('location')
                    || u.includes('busan') || u.includes('incheon')
                    || u.includes('no results found');
            }""",
            timeout=RENDER_TIMEOUT_MS,
        )
    except PWTimeout:
        pass
    await carrier_page.wait_for_timeout(3_000)
    return await target.evaluate(
        "() => document.body ? document.body.innerText : ''"
    )


async def fetch_eta(bl_no: str, headless: bool = False) -> dict[str, Any]:
    async with browser_context(headless=headless) as ctx:
        try:
            result = await _submit(ctx, bl_no)
            carrier = await _carrier_name(result)
            if carrier and any(c in carrier for c in FULLSCREEN_CARRIERS):
                text = await _follow_fullscreen(ctx, result, bl_no)
            else:
                text = await _read_iframe(result, bl_no, carrier)
        except Exception as e:
            return {
                "bl_no": bl_no, "status": "failed",
                "reason": f"{type(e).__name__}: {e}",
                "fetched_at": datetime.utcnow().isoformat() + "Z",
            }
    parsed = parse_iframe_text(text, carrier=carrier)
    parsed["bl_no"] = bl_no
    parsed["carrier"] = carrier
    parsed["fetched_at"] = datetime.utcnow().isoformat() + "Z"
    return parsed


# ──────────────────────────── Parser (pure / sync) ────────────────────────────

_DATE_RE = re.compile(r"\b(20\d{2}[-./]\d{2}[-./]\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?")


def parse_iframe_text(text: str, *, carrier: str | None) -> dict[str, Any]:
    """Carrier-aware plain-text parser. Returns: {status, data?: {port, eta}, reason?}"""
    low = text.lower()
    if "no results found" in low or "no tracking information" in low:
        return {"status": "failed", "reason": "not_found"}
    if "access denied" in low:
        return {"status": "failed", "reason": "blocked"}

    if carrier and "Maersk" in carrier:
        return _parse_maersk(text)
    if carrier and "COSCO" in carrier:
        return _parse_cosco(text)
    if carrier and "HMM" in carrier:
        return _parse_hmm(text)
    if carrier and ("KMTC" in carrier or "Korea Marine Transport" in carrier):
        return _parse_kmtc(text)
    return {"status": "failed", "reason": f"unsupported_carrier:{carrier}"}


_MAERSK_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def _maersk_iso(date_str: str) -> str:
    # "23 May 2026 15:00" -> "2026-05-23 15:00"
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})\s+(\d{2}:\d{2})", date_str.strip())
    if not m:
        return date_str.strip()
    day, mon, year, time = m.groups()
    return f"{year}-{_MAERSK_MONTHS.get(mon, mon)}-{int(day):02d} {time}"


def _parse_maersk(text: str) -> dict[str, Any]:
    # Format observed:
    #   PORT_NAME
    #   <terminal line>
    #   Vessel arrival (...)
    #   DD Mon YYYY HH:MM
    blocks = re.findall(
        r"([A-Z][A-Z ,]+?)\n[^\n]+\nVessel arrival[^\n]*\n"
        r"(\d{1,2}\s+[A-Za-z]{3}\s+20\d{2}\s+\d{2}:\d{2}|"
        r"20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2})",
        text,
    )
    if not blocks:
        return {"status": "failed", "reason": "selector_miss"}
    port, eta = blocks[-1]
    return {"status": "ok", "data": {"port": port.strip(), "eta": _maersk_iso(eta)}}


def _parse_cosco(text: str) -> dict[str, Any]:
    # Page header at top reads:  "<POR_city>\nPOR\n<FND_city>\nFND"
    port_m = re.search(r"([A-Za-z][^\n]*?,\s*[A-Z]{2})\s*\nFND\b", text)
    # ETA block:  "ETA\n2026-MM-DD\nHH:MM:SS\nTZ"
    eta_m = re.search(
        r"\bETA\b\s*\n(20\d{2}-\d{2}-\d{2})\s*\n(\d{2}:\d{2}(?::\d{2})?)\s*\n([A-Z]{3})",
        text,
    )
    if not (port_m and eta_m):
        return {"status": "failed", "reason": "selector_miss"}
    return {"status": "ok", "data": {
        "port": port_m.group(1).strip(),
        "eta":  f"{eta_m.group(1)} {eta_m.group(2)} {eta_m.group(3)}",
    }}


def _parse_hmm(text: str) -> dict[str, Any]:
    lines = [l.rstrip() for l in text.splitlines()]
    try:
        loc_idx = next(i for i, l in enumerate(lines) if l.strip() == "Location")
        arr_idx = next(i for i, l in enumerate(lines) if l.strip().startswith("Arrival(ETB)"))
    except StopIteration:
        return {"status": "failed", "reason": "selector_miss"}
    loc_cells = [l.strip() for l in lines[loc_idx + 1: loc_idx + 11] if l.strip()]
    arr_cells = [l.strip() for l in lines[arr_idx + 1: arr_idx + 11] if l.strip()]
    if len(loc_cells) < 4 or len(arr_cells) < 4:
        return {"status": "failed", "reason": "selector_miss"}
    return {"status": "ok", "data": {"port": loc_cells[3], "eta": arr_cells[3]}}


def _parse_kmtc(text: str) -> dict[str, Any]:
    # Layout (single-row tracking result):
    #   <POL>%%<TS_PORT>\n
    #   <POL_dep_dt>%%<TS_dep_dt>  <TS_PORT>%%<FND_PORT>\n
    #   <TS_arr_dt>%%<FND_arr_dt>  <vessel_info>
    # Dates are 12-digit YYYYMMDDHHMM. The final arrival date is the LAST
    # 12-digit token after a `%%`, sitting next to the FND port name.
    matches = re.findall(
        r"%%([A-Z][A-Z0-9 ()]+?)[ \t]*\n(\d{12})%%(\d{12})",
        text,
    )
    if not matches:
        return {"status": "failed", "reason": "selector_miss"}
    fnd_port, _dep_dt, eta_raw = matches[-1]
    fnd_port = fnd_port.strip()
    eta = (
        f"{eta_raw[0:4]}-{eta_raw[4:6]}-{eta_raw[6:8]} "
        f"{eta_raw[8:10]}:{eta_raw[10:12]}"
    )
    return {"status": "ok", "data": {"port": fnd_port, "eta": eta}}


# ──────────────────────────── CLI ────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Fetch ETA from track-trace.com")
    p.add_argument("bl_no")
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    result = asyncio.run(fetch_eta(args.bl_no, headless=not args.headed))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
