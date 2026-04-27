from bl_tracker.crawler.vesselfinder import parse_meta_position, format_label


def test_parses_lat_lon_from_meta(fixture_html):
    html = fixture_html("vesselfinder_ok.html")
    r = parse_meta_position(html)
    assert r["status"] == "ok"
    assert r["data"]["lat"] == -34.0   # 34 S
    assert r["data"]["lon"] == 18.0    # 18 E


def test_not_found_when_meta_missing_position(fixture_html):
    html = fixture_html("vesselfinder_notfound.html")
    r = parse_meta_position(html)
    assert r["status"] == "failed"
    assert r["reason"] == "not_found"


def test_format_label_with_city():
    assert format_label("남아프리카공화국", "Cape Town") == "남아프리카공화국 해상 (Cape Town 인근)"


def test_format_label_without_city():
    assert format_label("대한민국", "") == "대한민국 해상"
