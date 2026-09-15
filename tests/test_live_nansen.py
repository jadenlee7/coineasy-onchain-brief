"""외부 요청 없는 Nansen 수집 계약·검증·민감정보 회귀 검사."""
import datetime as dt
import io
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_nansen as live

NOW = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.timezone.utc)
ADDRESS = "0x" + "a" * 40
KEY = "never-write-this-key"


def perp_rows():
    return [{"token_symbol": token, "current_smart_money_position_longs_usd": 60,
             "current_smart_money_position_shorts_usd": -40} for token in live.CORE]


def sm(address=ADDRESS):
    return {"chain": "base", "token_address": address, "token_symbol": "LEAF",
            "token_sectors": ["Meme"], "net_flow_24h_usd": 1000,
            "net_flow_7d_usd": -2000, "trader_count": 4}


def screen(address=ADDRESS):
    return {"chain": "base", "token_address": address, "token_symbol": "LEAF",
            "market_cap_usd": 1_000_000, "liquidity": 100_000, "volume": 10_000,
            "netflow": 999_999, "nof_traders": 999_999}


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status
        self.headers = headers or {}
    def read(self, limit):
        return self.payload[:limit]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def responses():
    return [Response({"data": perp_rows()}), Response({"data": [sm()]}),
            Response({"data": [screen()]})]


class LiveTests(unittest.TestCase):
    def test_three_exact_read_requests_and_canonical_manual_snapshot(self):
        opener = FakeOpener(responses())
        snapshot, usage = live.collect(KEY, now=NOW, opener=opener)
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual([r.full_url for r in opener.requests],
            [live.BASE_URL + p for p in ("/perp-screener", "/smart-money/netflow", "/token-screener")])
        bodies = [json.loads(r.data) for r in opener.requests]
        self.assertEqual(bodies[0]["filters"], {"trader_type": "sm"})
        self.assertEqual(bodies[0]["date"], {"from": "2026-09-08T12:00:00Z", "to": "2026-09-15T12:00:00Z"})
        self.assertEqual(bodies[1]["filters"], {"include_stablecoins": False, "include_native_tokens": False})
        self.assertEqual(bodies[2]["filters"]["liquidity"], {"min": 100_000})
        self.assertTrue(all(r.get_method() == "POST" and r.get_header("Apikey") == KEY for r in opener.requests))
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["observation_kind"], "manual")
        self.assertEqual(snapshot["perp_cohort"], live.PERP_COHORT)
        self.assertEqual([row["token"] for row in snapshot["perp_rows"]], list(live.CORE))
        self.assertEqual(snapshot["perp_rows"][0]["long_pct"], 60)
        self.assertIsNone(snapshot["perp_rows"][0]["open_interest"])
        self.assertEqual(snapshot["meme_rows"][0]["net_flow"], 1000)
        self.assertEqual(snapshot["meme_rows"][0]["n_wallets"], 4)
        self.assertEqual(snapshot["meme_rows"][0]["sm_net_flow_7d"], -2000)
        self.assertEqual(snapshot["section_errors"], {})
        self.assertEqual(usage["request_count"], 3)
        self.assertEqual(usage["eligibility_status"], "not_verified")
        self.assertNotIn(KEY, json.dumps([snapshot, usage]))

    def test_missing_nonfinite_or_wrong_sign_perp_is_not_zero(self):
        for value in (None, True, float("nan"), float("inf"), -1, live.MAX_USD + 1):
            with self.subTest(value=value):
                rows = perp_rows(); rows[0]["current_smart_money_position_longs_usd"] = value
                self.assertEqual(live.parse_perps(rows), [])
        rows = perp_rows(); rows[0]["current_smart_money_position_shorts_usd"] = 40
        self.assertEqual(live.parse_perps(rows), [])
        rows = perp_rows(); rows[0]["trader_count"] = 1.5
        self.assertIsNone(live.parse_perps(rows)[0]["n_traders"])

    def test_duplicate_core_conflict_rejected(self):
        rows = perp_rows(); rows.append(dict(rows[0], current_smart_money_position_longs_usd=40))
        self.assertEqual(live.parse_perps(rows), [])

    def test_meme_identity_sector_and_quality_validation(self):
        for delta in ({"token_address": "wrong"}, {"chain": "ethereum"},
                      {"token_symbol": "OTHER"}, {"token_sectors": []},
                      {"trader_count": None}, {"trader_count": 3.1},
                      {"trader_count": 2}, {"net_flow_24h_usd": True},
                      {"net_flow_24h_usd": float("nan")}, {"net_flow_24h_usd": 0}):
            with self.subTest(delta=delta):
                self.assertEqual(live.parse_memes([dict(sm(), **delta)], [screen()]), [])
        for field, value in (("liquidity", None), ("liquidity", float("inf")),
                             ("market_cap_usd", 999_999), ("volume", 9999)):
            self.assertEqual(live.parse_memes([sm()], [dict(screen(), **{field: value})]), [])

    def test_solana_case_sensitive_base_normalized_conflicts_and_cap(self):
        self.assertEqual(live.identity(dict(sm(), token_address="0x" + "A" * 40)), ("Base", ADDRESS))
        one = dict(sm(), chain="solana", token_address="A" * 32)
        two = dict(screen(), chain="solana", token_address="a" * 32)
        self.assertEqual(live.parse_memes([one], [two]), [])
        self.assertEqual(live.parse_memes([sm(), dict(sm(), trader_count=5)], [screen()]), [])
        many = ["0x" + str(i) * 40 for i in range(1, 7)]
        self.assertEqual(len(live.parse_memes([sm(a) for a in many], [screen(a) for a in many])), 4)

    def test_mixed_error_preserves_perps_and_credit_reason_without_retry(self):
        errors = [urllib.error.HTTPError(live.BASE_URL, 500, KEY, {}, io.BytesIO(b"private body")),
                  urllib.error.HTTPError(live.BASE_URL, 403, KEY, {},
                                         io.BytesIO(b'{"code":"insufficient_credits"}'))]
        opener = FakeOpener([responses()[0], *errors])
        snapshot, usage = live.collect(KEY, now=NOW, opener=opener)
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(len(snapshot["perp_rows"]), 4)
        self.assertEqual(snapshot["section_errors"]["memecoin"], "collection:insufficient_credits")
        self.assertEqual(usage["successful_http_responses"], 1)
        serialized = json.dumps([snapshot, usage])
        self.assertNotIn(KEY, serialized)
        self.assertNotIn("private body", serialized)

    def test_bad_json_shape_and_transport_are_sanitized(self):
        opener = FakeOpener([Response(b"NOT JSON " + KEY.encode()), Response({"data": {}}),
                             urllib.error.URLError(KEY)])
        snapshot, usage = live.collect(KEY, now=NOW, opener=opener)
        self.assertEqual(snapshot["section_errors"]["positioning"], "collection:invalid_response")
        self.assertEqual(usage["requests"][2]["status"], None)
        self.assertNotIn(KEY, json.dumps([snapshot, usage]))

    def test_numeric_cost_headers_only(self):
        items = responses()
        items[0].headers = {"X-Nansen-Credits-Used": "1", "X-Nansen-Credits-Remaining": "29999", "Secret": KEY}
        items[1].headers = {"X-Nansen-Credits-Used": KEY, "X-Nansen-Credits-Remaining": "NaN"}
        _, usage = live.collect(KEY, now=NOW, opener=FakeOpener(items))
        self.assertEqual(usage["requests"][0]["credits_used"], 1)
        self.assertEqual(usage["requests"][0]["credits_remaining"], 29999)
        self.assertIsNone(usage["requests"][1]["credits_used"])
        self.assertNotIn(KEY, json.dumps(usage))

    def test_interrupted_response_and_oversized_json_are_sanitized(self):
        opener = FakeOpener([http.client.IncompleteRead(KEY.encode()),
                             Response(b"x" * (live.MAX_BODY + 1)), responses()[2]])
        snapshot, usage = live.collect(KEY, now=NOW, opener=opener)
        self.assertEqual(snapshot["section_errors"]["positioning"], "collection:transport_error")
        self.assertEqual(snapshot["section_errors"]["memecoin"], "collection:invalid_response")
        self.assertNotIn(KEY, json.dumps([snapshot, usage]))

    def test_no_redirect_or_auth_fallback(self):
        self.assertIsNone(live.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org"))
        items = responses(); items[0] = urllib.error.HTTPError(live.BASE_URL, 401, KEY, {}, io.BytesIO(b""))
        opener = FakeOpener(items)
        live.collect(KEY, now=NOW, opener=opener)
        self.assertEqual(len(opener.requests), 3)

    def test_explicit_live_and_valid_key_required_before_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live, "collect") as collect:
            for env, argv in (({}, ["--output", folder + "/a.json"]),
                              ({}, ["--live", "--output", folder + "/b.json"])):
                with patch.dict(os.environ, env, clear=True), self.assertRaises(SystemExit):
                    live.main(argv)
            collect.assert_not_called()
        with self.assertRaises(ValueError):
            live.collect("", opener=lambda *a: self.fail("unexpected network"))
        with self.assertRaises(ValueError):
            live.collect(KEY, now=dt.datetime(2026, 9, 15), opener=lambda *a: self.fail("unexpected network"))

    def test_cli_local_receipts_and_refuses_overwrite(self):
        snapshot, usage = live.collect(KEY, now=NOW, opener=FakeOpener(responses()))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"NANSEN_API_KEY": KEY}), \
             patch.object(live, "collect", return_value=(snapshot, usage)) as collect:
            out = Path(folder) / "sample.json"
            self.assertEqual(live.main(["--live", "--output", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["observation_kind"], "manual")
            receipt = Path(str(out) + ".usage.json")
            self.assertEqual(json.loads(receipt.read_text())["request_count"], 3)
            self.assertNotIn(KEY, receipt.read_text())
            with self.assertRaises(SystemExit):
                live.main(["--live", "--output", str(out)])
            self.assertEqual(collect.call_count, 1)


if __name__ == "__main__":
    unittest.main()
