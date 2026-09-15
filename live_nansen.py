"""선택적 수동 Nansen 수집. 3개 읽기 요청만 실행하며 재시도·게시하지 않는다.

Usage: NANSEN_API_KEY=... python live_nansen.py --live --output snapshot.json
The key should normally be supplied by the shell environment, never committed.
Output: snapshot.json and snapshot.json.usage.json. Neither proves buildathon
eligibility. Request credit costs vary; only observed numeric headers are saved.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import math
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

BASE_URL = "https://api.nansen.ai/api/v1"
CORE = ("BTC", "ETH", "SOL", "HYPE")
MAX_USD = 1_000_000_000_000_000
MAX_COUNT = 1_000_000_000
PERP_COHORT = "hyperliquid:smart_money:current_position_usd:v1"
TOKEN_COHORT = "smart_money:meme:24h:v1"
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._+$-]{0,31}")
BASE_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
SOL_ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
MAX_BODY = 4 * 1024 * 1024


def finite(value, minimum=0, maximum=MAX_USD):
    """누락·bool·비유한 수·범위 밖 값을 0으로 바꾸지 않는다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and minimum <= value <= maximum else None


def token_symbol(raw):
    value = raw.get("token_symbol")
    if not isinstance(value, str):
        return None
    value = value.strip().upper()
    return value if SYMBOL.fullmatch(value) else None


def identity(raw):
    if not isinstance(raw, dict):
        return None
    chain = raw.get("chain")
    address = raw.get("token_address")
    if not isinstance(chain, str) or not isinstance(address, str):
        return None
    chain = chain.lower()
    if chain == "base" and BASE_ADDRESS.fullmatch(address):
        return ("Base", address.lower())
    if chain == "solana" and SOL_ADDRESS.fullmatch(address):
        return ("Solana", address)
    return None


def unique(rows, key_fn):
    """동일 식별자의 상충 행은 어느 쪽도 채택하지 않는다."""
    found, conflicts = {}, set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        key = key_fn(raw)
        if key is None:
            continue
        if key in found and found[key] != raw:
            conflicts.add(key)
        found[key] = raw
    return {key: raw for key, raw in found.items() if key not in conflicts}


def parse_perps(rows):
    found = {}
    for token, raw in unique(rows, token_symbol).items():
        if token not in CORE:
            continue
        longs = finite(raw.get("current_smart_money_position_longs_usd"))
        shorts = finite(raw.get("current_smart_money_position_shorts_usd"), -MAX_USD, 0)
        if longs is None or shorts is None or longs - shorts <= 0:
            continue
        count = finite(raw.get("trader_count"), 0, MAX_COUNT)
        found[token] = {
            "token": token, "long_pct": 100 * longs / (longs - shorts),
            "open_interest": finite(raw.get("open_interest")),
            "n_traders": int(count) if count is not None and count.is_integer() else None,
            "long_pct_delta_pp": None,
        }
    # 일부 core만 반환하여 전체 표본으로 오인시키지 않는다.
    return [found[token] for token in CORE] if len(found) == len(CORE) else []


def parse_memes(sm_rows, screener_rows):
    screens = unique(screener_rows, identity)
    result = []
    for key, raw in unique(sm_rows, identity).items():
        screen = screens.get(key)
        sectors = raw.get("token_sectors")
        if screen is None or not isinstance(sectors, list):
            continue
        if not any(isinstance(s, str) and s in ("Meme", "Memecoins", "AI Meme") for s in sectors):
            continue
        symbol = token_symbol(raw)
        if symbol is None or symbol != token_symbol(screen):
            continue
        flow = finite(raw.get("net_flow_24h_usd"), 1)
        count = finite(raw.get("trader_count"), 3, MAX_COUNT)
        cap = finite(screen.get("market_cap_usd"), 1_000_000)
        volume = finite(screen.get("volume"), 10_000)
        liquidity = finite(screen.get("liquidity"), 100_000)
        if any(v is None for v in (flow, count, cap, volume, liquidity)) or not count.is_integer():
            continue
        result.append({
            "token": symbol, "chain": key[0], "token_address": key[1],
            "net_flow": flow, "n_wallets": int(count), "market_cap": cap,
            "volume": volume, "liquidity": liquidity, "verified_meme": True,
            "sm_net_flow_7d": finite(raw.get("net_flow_7d_usd"), -MAX_USD),
            "new_to_sample": None, "observed_positive_streak": None,
        })
    return sorted(result, key=lambda row: (-row["net_flow"], row["chain"], row["token_address"]))[:4]


def request_bodies(now):
    now = now.astimezone(dt.timezone.utc)
    return [
        ("/perp-screener", {
            "date": {"from": (now - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "to": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "filters": {"trader_type": "sm"},
            "order_by": [{"field": "open_interest", "direction": "DESC"}],
            "pagination": {"page": 1, "per_page": 100},
        }),
        ("/smart-money/netflow", {
            "chains": ["base", "solana"],
            "filters": {"include_stablecoins": False, "include_native_tokens": False},
            "order_by": [{"field": "net_flow_24h_usd", "direction": "DESC"}],
            "pagination": {"page": 1, "per_page": 100},
        }),
        ("/token-screener", {
            "chains": ["base", "solana"], "timeframe": "24h",
            "filters": {"market_cap_usd": {"min": 1_000_000},
                        "liquidity": {"min": 100_000}, "volume": {"min": 10_000}},
            "order_by": [{"field": "buy_volume", "direction": "DESC"}],
            "pagination": {"page": 1, "per_page": 100},
        }),
    ]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """인증 헤더가 다른 목적지로 전달되지 않도록 리디렉션을 거절한다."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json_body(response):
    body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("response too large")
    return json.loads(body)


def _receipt_headers(headers):
    # 전체 헤더·오류·원문에는 내부 식별자가 포함될 수 있어 숫자 2개만 선택한다.
    headers = headers or {}
    return {field: finite(headers.get(header), 0, MAX_USD) for field, header in (
        ("credits_used", "X-Nansen-Credits-Used"),
        ("credits_remaining", "X-Nansen-Credits-Remaining"),
    )}


def fetch_rows(path, body, api_key, opener):
    request = urllib.request.Request(BASE_URL + path,
        data=json.dumps(body, allow_nan=False).encode(),
        headers={"Content-Type": "application/json", "apikey": api_key}, method="POST")
    receipt = {"path": "/api/v1" + path, "status": None,
               "credits_used": None, "credits_remaining": None}
    try:
        with opener(request, timeout=25) as response:
            receipt["status"] = response.status
            receipt.update(_receipt_headers(response.headers))
            if not 200 <= response.status < 300:
                return [], "collection:http_error", receipt
            payload = _json_body(response)
            rows = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                return [], "collection:invalid_response", receipt
            return rows, None, receipt
    except urllib.error.HTTPError as exc:
        receipt["status"] = exc.code
        receipt.update(_receipt_headers(exc.headers))
        error = "collection:http_error"
        try:
            payload = _json_body(exc)
            if exc.code == 403 and isinstance(payload, dict) and (
                payload.get("code") == "insufficient_credits" or
                (not payload.get("code") and payload.get("error") == "Insufficient credits")
            ):
                error = "collection:insufficient_credits"
        except (ValueError, UnicodeError, OSError, http.client.HTTPException):
            pass
        finally:
            exc.close()
        return [], error, receipt
    except (ValueError, UnicodeError):
        return [], "collection:invalid_response", receipt
    except (OSError, urllib.error.URLError, http.client.HTTPException):
        return [], "collection:transport_error", receipt


def collect(api_key, *, now=None, opener=None):
    """수동 3요청 관측. 네트워크 helper 주입으로 무과금 검증 가능."""
    if not isinstance(api_key, str) or not api_key.strip() or "\n" in api_key or "\r" in api_key:
        raise ValueError("NANSEN_API_KEY must be present and valid")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observation time must have a timezone")
    now = now.astimezone(dt.timezone.utc)
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    results = [fetch_rows(path, body, api_key, opener) for path, body in request_bodies(now)]
    perps = parse_perps(results[0][0])
    memes = parse_memes(results[1][0], results[2][0])
    errors = {}
    if results[0][1] or not perps:
        errors["positioning"] = results[0][1] or "validation:core_tokens_missing"
    if results[1][1] or results[2][1] or not memes:
        source_errors = [result[1] for result in results[1:] if result[1]]
        reason = ("collection:insufficient_credits" if "collection:insufficient_credits" in source_errors
                  else next(iter(source_errors), "validation:no_verified_meme"))
        errors["verified_meme"] = reason
        errors["memecoin"] = reason
    snapshot = {"schema_version": 1, "observed_at": now.isoformat(),
        "kst_date": now.astimezone(dt.timezone(dt.timedelta(hours=9))).date().isoformat(),
        "observation_kind": "manual", "perp_cohort": PERP_COHORT,
        "token_cohort": TOKEN_COHORT, "perp_rows": perps, "meme_rows": memes,
        "section_errors": errors}
    usage = {"schema_version": 1, "observed_at": now.isoformat(),
        "request_count": len(results), "successful_http_responses": sum(
            result[2]["status"] is not None and 200 <= result[2]["status"] < 300 for result in results),
        "eligibility_status": "not_verified", "requests": [result[2] for result in results]}
    return snapshot, usage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly make three Nansen read requests")
    parser.add_argument("--output", type=Path, required=True, help="new snapshot JSON path")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; no requests were made")
    key = os.environ.get("NANSEN_API_KEY", "")
    if not key.strip():
        parser.error("NANSEN_API_KEY is required; no requests were made")
    usage_path = args.output.with_name(args.output.name + ".usage.json")
    # 요청 전 쓰기 위치를 확인하며 기존 관측은 덮어쓰지 않는다.
    if args.output.exists() or usage_path.exists() or not args.output.parent.is_dir():
        parser.error("output files must be new and parent directory must exist")
    try:
        snapshot, usage = collect(key)
        for path, data in ((args.output, snapshot), (usage_path, usage)):
            with path.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
    except (ValueError, OSError):
        parser.exit(2, "Live collection or local save failed; do not retry without checking existing output.\n")
    print(json.dumps({"snapshot": str(args.output), "usage": str(usage_path),
                      "request_count": usage["request_count"], "section_errors": snapshot["section_errors"]}))
    return 0 if not snapshot["section_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
