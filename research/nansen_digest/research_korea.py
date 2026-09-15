"""업비트 KRW 거래대금과 같은 자산의 Nansen 집단 순이동을 비교한다.

원화 거래대금은 거래 관심의 대리지표이며 국적별 이용자 수가 아니다.
종목 코드는 검토된 원장 주소에만 연결하고 동일 주소 Nansen 응답을 재사용한다.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

import httpx

from .token_analysis import CACHE_TTL

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
MAX_SKEW_SECONDS = 15 * 60
REGISTRY = {
    "KRW-JUP": {"symbol": "JUP", "chain": "solana",
        "address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "source": "https://discuss.jup.ag/t/faq-token-list-v3-verification/23074"},
    "KRW-WIF": {"symbol": "WIF", "chain": "solana",
        "address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "source": "https://dogwifcoin.org/"},
}


def _time(value: Any) -> dt.datetime | None:
    try:
        result = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo and result.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and abs(number) <= 1e18 else None
    except OverflowError:
        return None


def _empty(now: Any, reason: str) -> dict:
    observed = _time(now)
    return {"schema_version": 1, "status": "unavailable", "reason": reason,
            "observed_at": observed.isoformat() if observed else None, "timeframe": "24h",
            "source": "Upbit KRW", "rows": [], "listed_count": 0,
            "observed_count": 0, "total_traded_value_krw": None}


def build_korea_attention(markets: Any, tickers: Any, now: dt.datetime) -> dict:
    """순위·점유율의 분모를 관측된 현재 KRW 종목으로 고정한다."""
    result = _empty(now, "invalid_upbit_response")
    clock = _time(now)
    if not clock or not isinstance(markets, list) or not isinstance(tickers, list):
        return result
    listed = {}
    for row in markets:
        if not isinstance(row, dict):
            continue
        market = row.get("market")
        if isinstance(market, str) and market.startswith("KRW-") and market[4:].isalnum():
            if market in listed:
                return _empty(now, "duplicate_market")
            listed[market] = row
    if not listed:
        return _empty(now, "no_krw_markets")
    rows, seen = [], set()
    for row in tickers:
        if not isinstance(row, dict) or row.get("market") not in listed:
            continue
        market = row["market"]
        if market in seen:
            return _empty(now, "duplicate_ticker")
        seen.add(market)
        volume = _num(row.get("acc_trade_price_24h"))
        stamp = _num(row.get("timestamp"))
        change = _num(row.get("signed_change_rate"))
        if volume is None or volume < 0 or stamp is None:
            continue
        try:
            source_at = dt.datetime.fromtimestamp(stamp / 1000, UTC)
        except (OverflowError, ValueError, OSError):
            continue
        age = (clock - source_at).total_seconds()
        # 거래가 드문 종목의 오래된 현재가는 전체 순위 분모에서도 제외한다.
        if age < -60 or age > MAX_SKEW_SECONDS:
            continue
        event = listed[market].get("market_event")
        warning = bool(event.get("warning")) if isinstance(event, dict) else listed[market].get("market_warning") == "CAUTION"
        rows.append({"market": market, "symbol": market[4:], "traded_value_24h_krw": volume,
                     "price_change_since_utc_close_pct": change * 100 if change is not None and -1 <= change <= 100 else None,
                     "source_at": source_at.isoformat(), "warning": warning})
    total = sum(row["traded_value_24h_krw"] for row in rows)
    if not rows or not math.isfinite(total) or total <= 0:
        return _empty(now, "no_valid_ticker_volume")
    rows.sort(key=lambda row: (-row["traded_value_24h_krw"], row["market"]))
    for rank, row in enumerate(rows, 1):
        row.update(rank=rank, traded_value_share_pct=100 * row["traded_value_24h_krw"] / total)
    result.update(status="ok" if len(rows) == len(listed) else "partial", reason=None,
                  rows=rows, listed_count=len(listed), observed_count=len(rows), total_traded_value_krw=total)
    return result


async def collect_korea_attention(http: httpx.AsyncClient, now: dt.datetime | None = None) -> dict:
    """공식 공개 API를 최대 두 번 읽는다. 인증·재시도·외부 전송은 없다."""
    clock = now or dt.datetime.now(UTC)
    if not _time(clock):
        return _empty(clock, "invalid_time")
    responses = []
    for path, params in (("market/all", {"is_details": "true"}),
                         ("ticker/all", {"quote_currencies": "KRW"})):
        try:
            response = await http.get(f"https://api.upbit.com/v1/{path}", params=params,
                                      timeout=15.0, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                return _empty(clock, "upbit_response_too_large")
            responses.append(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            return _empty(clock, "upbit_unavailable")
    return build_korea_attention(*responses, clock)


def choose_research_asset(attention: dict) -> dict | None:
    """검토된 자산 중 최신·유의종목 제외·최대 거래대금 한 종목만 선택한다."""
    clock = _time(attention.get("observed_at"))
    if not clock or attention.get("status") not in ("ok", "partial"):
        return None
    candidates = []
    for row in attention.get("rows", []):
        asset = REGISTRY.get(row.get("market"))
        stamp = _time(row.get("source_at"))
        if asset and not row.get("warning") and stamp and -60 <= (clock - stamp).total_seconds() <= MAX_SKEW_SECONDS:
            candidates.append((row, asset))
    if not candidates:
        return None
    row, asset = max(candidates, key=lambda pair: pair[0]["traded_value_24h_krw"])
    return {**asset, "market": row["market"]}


select_korea_asset = choose_research_asset


def build_korea_comparison(attention: dict, token_research: dict | None, now: dt.datetime | None = None) -> dict:
    """같은 자산·24시간 창·15분 이내 자료에만 집단 방향 해설을 붙인다."""
    clock = _time(now or dt.datetime.now(UTC))
    asset = choose_research_asset(attention)
    result = {"schema_version": 1, "status": "unavailable", "reason": "no_verified_asset",
              "asset": asset, "attention": None, "onchain": None, "direction": None,
              "upbit_observed_at": attention.get("observed_at"), "nansen_observed_at": None,
              "observed_count": attention.get("observed_count", 0), "listed_count": attention.get("listed_count", 0)}
    if not asset:
        return result
    row = next(row for row in attention["rows"] if row["market"] == asset["market"])
    result["attention"] = row
    data = token_research if isinstance(token_research, dict) else {}
    source_times = data.get("source_times") if isinstance(data.get("source_times"), dict) else {}
    flow_time = source_times.get("flows") if isinstance(source_times.get("flows"), dict) else {}
    nansen_time = flow_time.get("fetched_at") or data.get("observed_at")
    result["nansen_observed_at"] = nansen_time
    result["upbit_observed_at"] = row.get("source_at")
    if data.get("chain") != asset["chain"] or data.get("address") != asset["address"]:
        result["reason"] = "asset_mismatch"
        return result
    if data.get("identity_verified") is not True:
        result["reason"] = "identity_unverified"
        return result
    if data.get("timeframe") not in ("1d", "24h"):
        result["reason"] = "window_mismatch"
        return result
    upstream, downstream = _time(row.get("source_at")), _time(nansen_time)
    if not clock or not upstream or not downstream or any((clock - x).total_seconds() < -60 or (clock - x).total_seconds() > ttl for x, ttl in ((upstream, MAX_SKEW_SECONDS), (downstream, CACHE_TTL))) or abs((upstream - downstream).total_seconds()) > MAX_SKEW_SECONDS:
        result["reason"] = "stale_or_skewed_sources"
        return result
    cohorts = data.get("cohorts") if isinstance(data.get("cohorts"), dict) else {}
    normalized = {}
    for name in ("smart_trader", "whale"):
        item = cohorts.get(name)
        normalized[name] = _num(item.get("net_flow_usd")) if isinstance(item, dict) else None
    result["onchain"] = normalized
    smart, whale = normalized["smart_trader"], normalized["whale"]
    if smart is None or whale is None:
        result.update(status="partial", reason="cohort_missing")
        return result
    direction = "flat" if smart == 0 or whale == 0 else "aligned_inflow" if smart > 0 and whale > 0 else "aligned_outflow" if smart < 0 and whale < 0 else "divergent"
    result.update(status="ok", reason=None, direction=direction)
    return result


_REASON = {"no_verified_asset": ("동일 자산 매핑·최신 관측 없음", "No fresh verified asset mapping"),
    "asset_mismatch": ("자산 주소 불일치", "Asset address mismatch"),
    "identity_unverified": ("Nansen 토큰 주소 미검증", "Nansen identity unverified"),
    "window_mismatch": ("조회 기간 불일치", "Observation windows differ"),
    "stale_or_skewed_sources": ("자료가 오래됐거나 시각 차이 초과", "Sources stale or over 15 minutes apart"),
    "cohort_missing": ("집단별 순이동 일부 미관측", "Some cohort flows unobserved")}


def format_korea_comparison(report: dict, lang: str = "ko") -> str:
    """자동 발행 본문용 짧은 일반 텍스트. 수치의 의미·분모·시각을 유지한다."""
    ko = lang.lower() == "ko"
    row, asset = report.get("attention"), report.get("asset")
    if not isinstance(row, dict) or not isinstance(asset, dict):
        return "한국 거래 관심 × 온체인: 비교 가능한 최신 자료 미관측." if ko else "Korean trading attention × onchain: no comparable fresh data."
    stamp = _time(report.get("upbit_observed_at"))
    nstamp = _time(report.get("nansen_observed_at"))
    stamp_text = lambda value: value.astimezone(KST).strftime("%m/%d %H:%M KST") if value else ("미관측" if ko else "unobserved")
    lines = [f"{'한국 거래 관심 × 온체인' if ko else 'Korean trading attention × onchain'} · {asset['symbol']}",
             f"Upbit KRW 24h: ₩{row['traded_value_24h_krw']:,.0f} · #{row['rank']}/{report['observed_count']} · {row['traded_value_share_pct']:.2f}%"]
    change = row.get("price_change_since_utc_close_pct")
    if change is not None:
        lines.append(f"{'UTC 전일 종가 대비' if ko else 'Vs previous UTC close'} {change:+.2f}%")
    lines.append(f"Upbit {stamp_text(stamp)} / Nansen {'조회' if ko else 'fetched'} {stamp_text(nstamp)}")
    if report.get("status") == "ok":
        names = ("스마트 트레이더", "고래") if ko else ("Smart traders", "Whales")
        flows = report["onchain"]
        lines.append(" · ".join(f"{label} {flows[key]:+,.0f} USD" for label, key in zip(names, ("smart_trader", "whale"))))
        meanings = {"aligned_inflow": ("두 집단 모두 순유입", "Both cohorts have net inflows"), "aligned_outflow": ("두 집단 모두 순유출", "Both cohorts have net outflows"), "divergent": ("두 집단 순이동 방향 엇갈림", "Cohort flow directions diverge"), "flat": ("0인 집단이 있어 공통 방향 판단 보류", "A zero flow prevents a shared direction")}
        lines.append(meanings[report["direction"]][0 if ko else 1])
    else:
        lines.append(("비교 보류: " if ko else "Comparison withheld: ") + _REASON.get(report.get("reason"), ("자료 미관측", "Data unobserved"))[0 if ko else 1])
    lines.extend([f"{asset['chain']} · {asset['address']}",
        (f"KRW {report['listed_count']}종 중 {report['observed_count']}종 관측. 거래대금은 인원·매수세가 아닙니다. 집단은 중복 가능해 합산하지 않습니다." if ko else f"{report['observed_count']}/{report['listed_count']} KRW pairs observed. Turnover is not people or buying pressure; cohorts may overlap."),
        "Data: Upbit · @nansen_ai. Snapshot only, not a trading signal."])
    return "\n".join(lines)
