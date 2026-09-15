"""일일 토큰 리서치 자료와 한국어/영어 설명. 발송·스케줄·인증 저장은 하지 않는다.

기존 /token의 세 TGM 계약과 검증기를 재사용한다. 반환 자료는 최대 10분
재사용할 수 있으며 조회 시각과 제공자 시각을 분리한다.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any

import httpx

from .token_analysis import API_BASE, CACHE_TTL, KST, TokenQuery, _count, _holders, _number, _valid_address

VERSION = 1
_COHORTS = ("smart_trader", "whale", "exchange")
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+$-]{0,31}")


def _aware(value: Any) -> dt.datetime | None:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(dt.timezone.utc)


def _query(query: Any) -> TokenQuery:
    if isinstance(query, dict):
        query = TokenQuery(query.get("chain"), query.get("address"))
    if not isinstance(query, TokenQuery):
        raise ValueError("invalid_token_query")
    address = _valid_address(query.chain, query.address)
    if not address:
        raise ValueError("invalid_token_query")
    return TokenQuery(query.chain, address)


def _empty(query: TokenQuery, now: dt.datetime) -> dict:
    return {"schema_version": VERSION, "chain": query.chain, "address": query.address,
            "symbol": None, "observed_at": now.isoformat(), "timeframe": "1d", "status": "unavailable",
            "identity_verified": False, "source_times": {}, "cohorts": {},
            "market": {}, "holders": [], "errors": {}, "api_calls": 0, "api_events": []}


def _identity_mismatch(query: TokenQuery, body: Any, *, rows: bool = False) -> bool:
    """응답의 명시적 식별자만 대조하며 보유자 address를 토큰 주소로 해석하지 않는다."""
    if not isinstance(body, dict):
        return False
    objects = [body]
    data = body.get("data")
    if isinstance(data, dict):
        objects.append(data)
    elif rows and isinstance(data, list):
        objects.extend(row for row in data if isinstance(row, dict))
    for obj in objects:
        if "chain" in obj and obj["chain"] != query.chain:
            return True
        for field in ("token_address", "contract_address"):
            if field in obj and _valid_address(query.chain, obj[field]) != query.address:
                return True
    return False


def _source_time(body: dict, now: dt.datetime) -> tuple[dict, str | None]:
    result = {"fetched_at": now.isoformat(), "provider_at": None,
              "time_basis": "request_time"}
    objects = [body]
    if isinstance(body.get("data"), dict):
        objects.append(body["data"])
    elif isinstance(body.get("data"), list):
        objects.extend(row for row in body["data"] if isinstance(row, dict))
    stamps = []
    for obj in objects:
        for key in ("observed_at", "updated_at", "source_timestamp"):
            if key in obj:
                stamp = _aware(obj[key])
                if stamp is None:
                    return result, "invalid_source_time"
                age = (now - stamp).total_seconds()
                if age < -60 or age > CACHE_TTL:
                    return result, "stale_source_time" if age > CACHE_TTL else "future_source_time"
                stamps.append(stamp)
    if stamps:
        result.update(provider_at=min(stamps).isoformat(), time_basis="provider_time")
    return result, None


async def collect_token_research(query: TokenQuery | dict, api_key: str, *,
                                 transport: httpx.AsyncBaseTransport | None = None,
                                 http: httpx.AsyncClient | None = None,
                                 now: dt.datetime | None = None) -> dict:
    """기존 API를 각 1회 조회한다. 재시도 없이 JSON 안전 자료만 반환한다.

    호출자는 일일 예산·중복·캐시를 관리한다. http 주입 시 클라이언트를 닫지
    않는다. source_times의 request_time은 제공자 관측 시각을 뜻하지 않는다.
    """
    query = _query(query)
    moment = _aware(now if now is not None else dt.datetime.now(dt.timezone.utc))
    if moment is None:
        raise ValueError("aware_now_required")
    snapshot = _empty(query, moment)
    if not isinstance(api_key, str) or not api_key.strip():
        snapshot["errors"]["collection"] = "missing_api_key"
        return snapshot
    common = {"chain": query.chain, "token_address": query.address}
    endpoints = {
        "flows": ("/tgm/flow-intelligence", {**common, "timeframe": "1d"}),
        "holders": ("/tgm/holders", {**common, "aggregate_by_entity": False,
                    "label_type": "all_holders", "pagination": {"page": 1, "per_page": 3},
                    "order_by": [{"field": "token_amount", "direction": "DESC"}]}),
        "market": ("/tgm/token-information", {**common, "timeframe": "1d"}),
    }
    client = http or httpx.AsyncClient(timeout=20, transport=transport, follow_redirects=False)

    async def fetch(section: str) -> tuple[str, dict | None, str | None, dict]:
        path, body = endpoints[section]
        # 요청 시도 기록은 응답 본문·헤더·키를 저장하지 않는다.
        event = {"section": section, "path": path,
                 "requested_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                 "http_status": None, "transport_unknown": True}
        try:
            response = await client.post(API_BASE + path, headers={"apiKey": api_key},
                                         json=body, follow_redirects=False)
            event.update(http_status=response.status_code, transport_unknown=False)
            if response.status_code != 200:
                return section, None, f"http_{response.status_code}", event
            if len(response.content) > 262144:
                return section, None, "response_too_large", event
            data = response.json()
            if not isinstance(data, dict):
                return section, None, "invalid_response", event
            return section, data, None, event
        except (httpx.HTTPError, ValueError, TypeError):
            return section, None, "request_failed", event

    try:
        results = await asyncio.gather(*(fetch(section) for section in endpoints))
    finally:
        if http is None:
            await client.aclose()
    snapshot["api_events"] = [event for _, _, _, event in results]
    snapshot["api_calls"] = len(results)  # 성공 횟수가 아닌 요청 시도 횟수
    accepted = {}
    mismatch = False
    for section, body, error, _ in results:
        if error:
            snapshot["errors"][section] = error
            continue
        times, error = _source_time(body, moment)
        snapshot["source_times"][section] = times
        if _identity_mismatch(query, body, rows=section in ("flows", "holders")):
            mismatch = True
            snapshot["errors"][section] = "identity_mismatch"
        elif error:
            snapshot["errors"][section] = error
        else:
            accepted[section] = body
    info = accepted.get("market", {}).get("data")
    # 토큰 정보로 요청 주소를 검증하지 못하면 다른 집단 숫자도 함께 보류한다.
    if mismatch or not isinstance(info, dict) or _valid_address(query.chain, info.get("contract_address")) != query.address:
        snapshot["errors"]["identity"] = "identity_mismatch" if mismatch else "identity_unverified"
        return snapshot
    snapshot["identity_verified"] = True
    symbol = info.get("symbol")
    snapshot["symbol"] = symbol if isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) else None
    flows = accepted.get("flows", {}).get("data")
    if isinstance(flows, list) and len(flows) == 1 and isinstance(flows[0], dict):
        row = flows[0]
        snapshot["cohorts"] = {
            group: {"net_flow_usd": _number(row.get(group + "_net_flow_usd")),
                    "wallet_count": None if group == "exchange" else _count(row.get(group + "_wallet_count")),
                    "wallet_count_status": "not_counted" if group == "exchange" else "observed" if _count(row.get(group + "_wallet_count")) is not None else "unobserved",
                    "window": "1d"}
            for group in _COHORTS}
    else:
        snapshot["errors"].setdefault("flows", "invalid_or_missing_data")
    details = info.get("token_details")
    spot = info.get("spot_metrics")
    details = details if isinstance(details, dict) else {}
    spot = spot if isinstance(spot, dict) else {}
    supply = _number(details.get("total_supply"), nonnegative=True)
    snapshot["market"] = {"liquidity_usd": _number(spot.get("liquidity_usd"), nonnegative=True),
                          "volume_24h_usd": _number(spot.get("volume_total_usd"), nonnegative=True),
                          "total_supply": supply, "top3_supply_share_pct": None}
    holder_body = accepted.get("holders", {})
    rows = _holders(query, holder_body)
    snapshot["holders"] = [{"address": address, "token_amount": amount, "value_usd": value}
                            for address, amount, value in rows]
    if not isinstance(holder_body.get("data"), list) or not rows:
        snapshot["errors"].setdefault("holders", "invalid_or_missing_data")
    amounts = [row[1] for row in rows]
    if len(amounts) == 3 and supply and amounts == sorted(amounts, reverse=True) and sum(amounts) <= supply:
        snapshot["market"]["top3_supply_share_pct"] = 100 * sum(amounts) / supply
    snapshot["status"] = "partial" if snapshot["errors"] else "observed"
    return snapshot


def _usd(value: Any, *, signed: bool = False, missing: str = "미관측") -> str:
    value = _number(value)
    if value is None:
        return missing
    sign = "+" if signed and value > 0 else "−" if value < 0 else ""
    amount = f"${abs(value):,.0f}" if abs(value) >= 1 or value == 0 else "<$1"
    return sign + amount


def format_token_research(snapshot: dict, lang: str = "ko", *, now: dt.datetime | None = None) -> str:
    """캐시 만료·불명확한 시각·주소 불일치는 수치를 숨긴다. 사용자 HTML은 받지 않는다."""
    if lang not in ("ko", "en"):
        raise ValueError("unsupported_language")
    query = _query(snapshot)
    ko = lang == "ko"
    missing = "미관측" if ko else "unobserved"
    observed = _aware(snapshot.get("observed_at"))
    moment = _aware(now if now is not None else dt.datetime.now(dt.timezone.utc))
    fresh = bool(moment and observed and -60 <= (moment - observed).total_seconds() <= CACHE_TTL)
    valid = fresh and snapshot.get("identity_verified") is True and snapshot.get("status") in ("observed", "partial")
    symbol = snapshot.get("symbol")
    symbol = symbol if valid and isinstance(symbol, str) and _SYMBOL.fullmatch(symbol) else ""
    title = "오늘의 토큰 리서치" if ko else "Token research spotlight"
    lines = [f"CoinEasy · {title}", f"{query.chain.title()} {symbol}".strip(), query.address]
    lines.append(("조회 시각: " if ko else "Fetched: ") + (f"{observed.astimezone(KST):%m/%d %H:%M} KST" if observed else missing))
    if not valid:
        lines.append("주소·시각 검증 자료가 없거나 조회가 만료되어 수치를 표시하지 않습니다." if ko else
                     "Figures withheld: token identity or time is unverified, or the snapshot expired.")
    else:
        lines.append("최근 24시간 순이동 · Nansen 분류" if ko else "Last 24h net transfers · Nansen cohorts")
        groups = snapshot.get("cohorts") or {}
        labels = ("스마트 트레이더", "고래", "거래소") if ko else ("Smart traders", "Whales", "Exchanges")
        for group, label in zip(_COHORTS, labels):
            row = groups.get(group) or {}
            amount = _usd(row.get("net_flow_usd"), signed=True, missing=missing)
            count = _count(row.get("wallet_count"))
            count_text = ("지갑 수 미집계" if ko else "wallet count not counted") if group == "exchange" else (f"{count:,}개 지갑" if ko else f"{count:,} wallets") if count is not None else ("지갑 수 미관측" if ko else "wallet count unobserved")
            lines.append(f"• {label}: {amount} · {count_text}")
        smart = _number((groups.get("smart_trader") or {}).get("net_flow_usd"))
        whale = _number((groups.get("whale") or {}).get("net_flow_usd"))
        if smart is None or whale is None:
            meaning = "집단 간 비교 자료 일부 미관측." if ko else "Some cohort comparison data is unobserved."
        elif not smart or not whale:
            meaning = "0인 순이동이 있어 공통 방향을 판단하지 않습니다." if ko else "A zero net transfer does not establish a shared direction."
        elif (smart > 0) == (whale > 0):
            meaning = ("스마트 트레이더·고래 모두 순유입." if smart > 0 else "스마트 트레이더·고래 모두 순유출.") if ko else ("Smart traders and whales both have net inflows." if smart > 0 else "Smart traders and whales both have net outflows.")
        else:
            meaning = "스마트 트레이더·고래의 순이동 방향이 엇갈립니다." if ko else "Smart trader and whale flows point in different directions."
        lines.append(("해석: " if ko else "Interpretation: ") + meaning)
        market = snapshot.get("market") or {}
        lines.append(("유동성 " if ko else "Liquidity ") + _usd(market.get("liquidity_usd"), missing=missing) + (" · 24h 거래량 " if ko else " · 24h volume ") + _usd(market.get("volume_24h_usd"), missing=missing))
        share = _number(market.get("top3_supply_share_pct"), nonnegative=True)
        share_text = missing if share is None or share > 100 else "<0.1%" if 0 < share < 0.1 else f"{share:.1f}%"
        lines.append(("상위 3개 주소 / 총발행량: " if ko else "Top 3 addresses / total supply: ") + share_text)
        lines.append("다음 확인: 거래소 입출금 이후 실제 거래량과 다음 관측의 흐름을 비교하세요." if ko else "Next check: compare exchange transfers with actual volume and the next observation.")
        lines.append("집단은 중복될 수 있어 합산하지 않습니다. 주소 비중은 소유주 집중도가 아닙니다." if ko else "Cohorts can overlap; do not add them. Address share is not owner concentration.")
        lines.append("조회 시각은 제공자 관측 시각과 다를 수 있습니다." if ko else "Fetch time may differ from the provider observation time.")
    lines.extend(["", "직접 확인: " + f"/token {query.chain} {query.address}" if ko else "Explore: " + f"/token {query.chain} {query.address}",
                  "순이동은 매수·매도 확정이나 가격 전망이 아닙니다." if ko else "Net transfers do not confirm buys, sells, or a price forecast.",
                  "Powered by Nansen API · https://www.nansen.ai"])
    return "\n".join(lines)
