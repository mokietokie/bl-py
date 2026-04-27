import pytest
from bl_tracker.crawler.track_trace import parse_iframe_text


@pytest.mark.parametrize(
    "carrier,fixture,expected_port,expected_eta_contains",
    [
        ("Maersk Line",            "track_trace_maersk_ok.txt", "BUSAN",   "2026-05-23"),
        ("COSCO SHIPPING Lines",   "track_trace_cosco_ok.txt",  "Incheon", "2026-04-29"),
        ("HMM",                    "track_trace_hmm_ok.txt",    "BUSAN",   "2026-03-06"),
        ("KMTC",                   "track_trace_kmtc_ok.txt",   "INCHEON", "2026-03-30"),
    ],
)
def test_parses_each_carrier(fixture_text, carrier, fixture, expected_port, expected_eta_contains):
    text = fixture_text(fixture)
    result = parse_iframe_text(text, carrier=carrier)
    assert result["status"] == "ok", result
    assert expected_port.upper() in (result["data"]["port"] or "").upper()
    assert expected_eta_contains in result["data"]["eta"]


def test_no_results(fixture_text):
    text = fixture_text("track_trace_notfound.txt")
    result = parse_iframe_text(text, carrier="Maersk Line")
    assert result["status"] == "failed"
    assert result["reason"] == "not_found"
