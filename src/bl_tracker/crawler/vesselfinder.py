from __future__ import annotations
import argparse, asyncio, json, re, sys, threading
from datetime import datetime
from typing import Any

import reverse_geocoder as _rg

from ._browser import browser_context

IMO_MAP_URL = "https://www.vesselfinder.com/?imo={imo}"
RENDER_TIMEOUT_MS = 30_000

_META_TAG = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)
_META_POS = re.compile(
    r"last\s+position\s+is\s+"
    r"(?P<lat>\d+(?:\.\d+)?)\s*(?P<ns>[NS])\s*,?\s*"
    r"(?P<lon>\d+(?:\.\d+)?)\s*(?P<ew>[EW])",
    re.I,
)
_VESSEL_NAME = re.compile(r"^\s*(.+?)\s+last\s+position\s+is\b", re.I)

# reverse_geocoder lazy-init is NOT thread-safe. Warm up at import time and
# guard concurrent searches with a lock so bulk refresh workers don't trigger
# "dictionary changed size during iteration".
_RG_LOCK = threading.Lock()
try:
    _rg.search([(0.0, 0.0)], mode=1)
except Exception:
    pass


_CC_KO: dict[str, str] = {
    "KR": "대한민국", "JP": "일본", "CN": "중국", "TW": "대만", "HK": "홍콩",
    "SG": "싱가포르", "MY": "말레이시아", "TH": "태국", "VN": "베트남",
    "ID": "인도네시아", "PH": "필리핀", "IN": "인도", "PK": "파키스탄",
    "BD": "방글라데시", "LK": "스리랑카",
    "AE": "아랍에미리트", "SA": "사우디아라비아", "OM": "오만", "QA": "카타르",
    "KW": "쿠웨이트", "BH": "바레인", "IR": "이란", "TR": "튀르키예", "EG": "이집트",
    "ZA": "남아프리카공화국", "MA": "모로코", "DZ": "알제리", "NG": "나이지리아",
    "KE": "케냐", "TZ": "탄자니아", "GH": "가나",
    "GB": "영국", "IE": "아일랜드", "FR": "프랑스", "DE": "독일", "NL": "네덜란드",
    "BE": "벨기에", "ES": "스페인", "PT": "포르투갈", "IT": "이탈리아", "GR": "그리스",
    "DK": "덴마크", "NO": "노르웨이", "SE": "스웨덴", "FI": "핀란드",
    "PL": "폴란드", "RU": "러시아", "UA": "우크라이나",
    "US": "미국", "CA": "캐나다", "MX": "멕시코", "PA": "파나마",
    "BR": "브라질", "AR": "아르헨티나", "CL": "칠레", "PE": "페루", "CO": "콜롬비아",
    "AU": "호주", "NZ": "뉴질랜드",
}


def parse_meta_position(html: str) -> dict[str, Any]:
    """Parse <meta name=description> for vessel name + lat/lon. Pure & sync."""
    tag = _META_TAG.search(html)
    desc = tag.group(1) if tag else ""
    pos = _META_POS.search(desc)
    if not pos:
        return {"status": "failed", "reason": "not_found"}
    lat = float(pos.group("lat"))
    lon = float(pos.group("lon"))
    if pos.group("ns").upper() == "S":
        lat = -lat
    if pos.group("ew").upper() == "W":
        lon = -lon
    name_m = _VESSEL_NAME.search(desc)
    return {
        "status": "ok",
        "data": {
            "vessel": (name_m.group(1).strip() if name_m else None),
            "lat": lat,
            "lon": lon,
        },
    }


def nearest_country_ko(lat: float, lon: float) -> tuple[str, str, str]:
    """(korean_country, iso2, nearest_city). Offline, single-thread-safe."""
    with _RG_LOCK:
        hits = _rg.search([(lat, lon)], mode=1)
    if not hits:
        return "알 수 없음", "", ""
    rec = hits[0]
    cc = (rec.get("cc") or "").upper()
    city = rec.get("name") or ""
    return _CC_KO.get(cc, cc or "알 수 없음"), cc, city


def format_label(country_ko: str, city: str) -> str:
    return f"{country_ko} 해상 (" + city + " 인근)" if city else f"{country_ko} 해상"


async def fetch_location(imo: str, headless: bool = True) -> dict[str, Any]:
    """IMO 직접 조회 → 위치 dict. 검색 경로는 사용하지 않는다."""
    async with browser_context(headless=headless) as ctx:
        page = await ctx.new_page()
        try:
            await page.goto(
                IMO_MAP_URL.format(imo=imo),
                wait_until="domcontentloaded",
                timeout=RENDER_TIMEOUT_MS,
            )
            await page.wait_for_timeout(2_500)
            html = await page.content()
        except Exception as e:
            return {
                "imo": imo, "status": "failed",
                "reason": f"{type(e).__name__}: {e}",
                "fetched_at": datetime.utcnow().isoformat() + "Z",
            }
        finally:
            try:
                await page.close()
            except Exception:
                pass

    parsed = parse_meta_position(html)
    if parsed["status"] != "ok":
        parsed["imo"] = imo
        parsed["fetched_at"] = datetime.utcnow().isoformat() + "Z"
        return parsed

    lat = parsed["data"]["lat"]
    lon = parsed["data"]["lon"]
    country_ko, cc, city = nearest_country_ko(lat, lon)
    return {
        "imo": imo,
        "status": "ok",
        "data": {
            "vessel": parsed["data"]["vessel"],
            "lat": lat, "lon": lon,
            "country_ko": country_ko, "cc": cc, "nearest_city": city,
            "location_label": format_label(country_ko, city),
        },
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch vessel location from vesselfinder.com")
    p.add_argument("imo", help="7-digit IMO number")
    p.add_argument("--headed", action="store_true")
    args = p.parse_args()
    result = asyncio.run(fetch_location(args.imo, headless=not args.headed))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
