"""정규 관측에서 독자가 후속 조사할 만한 변화만 고르는 순수 함수."""
from __future__ import annotations

import datetime as dt
import re
import statistics

from .history import KST, PERP_COHORT, TOKEN_COHORT, _aware_datetime, _comparable_observation, _finite
from .ops import MIN_FLOW, MIN_LIQUIDITY
from .token_analysis import _valid_address

LOOKBACK_DAYS = 14
MIN_BASELINE = 3


def _identity(row):
    chain, address = row.get("chain"), row.get("token_address")
    if not isinstance(chain, str) or not isinstance(address, str):
        return None
    chain = chain.lower()
    verified = _valid_address(chain, address)
    return (chain, verified) if verified else None


def _label(value):
    # 외부 토큰 이름은 HTML 또는 제어 문자를 공개 메시지에 끼워 넣을 수 없다.
    return re.sub(r"[^\w .+$-]", "", value)[:32] if isinstance(value, str) else ""


def _rows(snapshot, section):
    errors = snapshot.get("section_errors")
    if not isinstance(errors, dict) or errors.get(section) or (section == "memecoin" and errors.get("verified_meme")):
        return {}, "section_unavailable"
    key, cohort_key, cohort = (("perp_rows", "perp_cohort", PERP_COHORT) if section == "positioning"
                               else ("meme_rows", "token_cohort", TOKEN_COHORT))
    if snapshot.get(cohort_key) != cohort:
        return {}, "cohort_mismatch"
    rows = snapshot.get(key)
    if not isinstance(rows, list) or not rows:
        return {}, "values_unobserved"
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            return {}, "invalid_values"
        token = _label(row.get("token"))
        if not token:
            return {}, "invalid_values"
        if section == "positioning":
            identity = row.get("token")
            value = _finite(row.get("long_pct"))
            if not isinstance(identity, str) or value is None or not 0 <= value <= 100:
                return {}, "invalid_values"
        else:
            identity = _identity(row)
            value = _finite(row.get("net_flow"))
            liquidity = _finite(row.get("liquidity"))
            if identity is None or row.get("verified_meme") is not True or value is None:
                return {}, "invalid_values"
            if liquidity is None or liquidity < MIN_LIQUIDITY:
                # 유동성이 관측되지 않은 항목은 비교 근거에도 넣지 않는다.
                continue
        if identity in result:
            return {}, "ambiguous_values"
        result[identity] = row
    return (result, None) if result else ({}, "liquidity_unobserved_or_low")


def build_research_changes(snapshots, now=None):
    """최근 14일 중 동일 시각·코호트의 최소 3개 관측을 요구한다.

    누락된 날과 표본 밖 토큰은 0으로 취급하지 않는다. 호출자는 현재 정규
    스냅샷을 저장하거나 전달한 뒤 호출해야 한다. 수동/복구 관측은 제외한다.
    """
    current = _aware_datetime(now if now is not None else dt.datetime.now(dt.timezone.utc))
    result = {"schema_version": 1, "status": "insufficient_data", "kst_date": None,
              "observed_at": None, "reasons": [], "items": [],
              "coverage": {"lookback_days": LOOKBACK_DAYS, "positioning_comparable": 0,
                           "memecoin_comparable": 0, "baseline_dates": []}}
    reasons = set()
    if current is None:
        result["reasons"] = ["invalid_reference_time"]
        return result
    today = current.astimezone(KST).date()
    result["kst_date"] = today.isoformat()
    by_date, ambiguous = {}, set()
    for snapshot in snapshots if isinstance(snapshots, (list, tuple)) else []:
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
            continue
        observed = _aware_datetime(snapshot.get("observed_at"))
        if snapshot.get("observation_kind") != "scheduled":
            continue
        if observed is None or observed > current:
            continue
        day = observed.astimezone(KST).date()
        if snapshot.get("kst_date") != day.isoformat() or not 0 <= (today - day).days <= LOOKBACK_DAYS:
            continue
        if day in by_date and snapshot != by_date[day]:
            ambiguous.add(day)
        else:
            by_date[day] = snapshot
    for day in ambiguous:
        by_date.pop(day, None)
    latest = by_date.get(today)
    if latest is None:
        result["reasons"] = ["current_scheduled_observation_unavailable"]
        return result
    observed = _aware_datetime(latest["observed_at"])
    result["observed_at"] = observed.isoformat()
    eligible = {}
    for offset in range(1, LOOKBACK_DAYS + 1):
        day = today - dt.timedelta(days=offset)
        prior = by_date.get(day)
        if prior and _comparable_observation(prior, observed, offset):
            eligible[day] = prior
    result["coverage"]["baseline_dates"] = [day.isoformat() for day in sorted(eligible)]
    if today - dt.timedelta(days=1) not in eligible:
        reasons.add("exact_previous_day_unavailable")
    selected = []
    for section in ("positioning", "memecoin"):
        rows, reason = _rows(latest, section)
        if reason:
            reasons.add(section + ":" + reason)
        history_rows = {day: _rows(prior, section)[0] for day, prior in eligible.items()}
        for identity, row in rows.items():
            baseline = [(day, old[identity]) for day, old in sorted(history_rows.items()) if identity in old]
            if len(baseline) < MIN_BASELINE:
                reasons.add(section + ":insufficient_baseline")
                continue
            dates = [day.isoformat() for day, _ in baseline]
            times = [eligible[day]["observed_at"] for day, _ in baseline]
            common = {"token": _label(row["token"]), "observed_at": result["observed_at"],
                      "baseline_dates": dates, "baseline_observed_at": times,
                      "baseline_days": len(baseline)}
            if section == "positioning":
                prior_day = today - dt.timedelta(days=1)
                prior = history_rows.get(prior_day, {}).get(identity)
                if prior is None:
                    reasons.add("positioning:exact_previous_value_unavailable")
                    continue
                result["coverage"]["positioning_comparable"] += 1
                before, after = _finite(prior["long_pct"]), _finite(row["long_pct"])
                delta = after - before
                flip = (before < 50 < after or after < 50 < before) and abs(delta) >= 5
                if not flip and abs(delta) < 10:
                    continue
                selected.append({**common, "kind": "positioning_flip" if flip else "positioning_change",
                                 "stats": {"previous_long_pct": before, "long_pct": after,
                                           "delta_pp": round(delta, 3)},
                                 "previous_observed_at": eligible[prior_day]["observed_at"]})
            else:
                values = [_finite(old["net_flow"]) for _, old in baseline]
                median = statistics.median(values)
                mad = statistics.median(abs(v - median) for v in values)
                threshold = max(MIN_FLOW, 3 * max(abs(median), 1), median + 6 * mad)
                value = _finite(row["net_flow"])
                # 유한 입력도 통계 계산에서 넘칠 수 있으므로 경계값을 다시 확인한다.
                if any(_finite(v) is None for v in (median, mad, threshold)):
                    reasons.add("memecoin:invalid_baseline_statistics")
                    continue
                result["coverage"]["memecoin_comparable"] += 1
                if value <= threshold:
                    continue
                selected.append({**common, "kind": "meme_inflow_spike", "chain": identity[0],
                                 "token_address": identity[1],
                                 "stats": {"net_flow": value, "baseline_median": median,
                                           "threshold": threshold, "liquidity": _finite(row["liquidity"]),
                                           "positive_observations": sum(v > 0 for v in values) + int(value > 0),
                                           "total_observations": len(values) + 1}})
    # 각 종류가 들어갈 기회를 주며 토큰 이름으로 안정적으로 정렬한다.
    selected.sort(key=lambda item: (0 if item["kind"] == "positioning_flip" else
                                   1 if item["kind"] == "meme_inflow_spike" else 2,
                                   item.get("chain", ""), item["token"], item.get("token_address", "")))
    result["items"] = selected[:3]
    comparable = result["coverage"]["positioning_comparable"] + result["coverage"]["memecoin_comparable"]
    result["status"] = "observations" if result["items"] else "no_material_change" if comparable else "insufficient_data"
    result["reasons"] = sorted(reasons)
    return result


def _money(value):
    """매우 큰 금액도 공개 메시지 길이를 폭증시키지 않는다."""
    return f"{value:,.0f}" if abs(value) < 1e12 else f"{value:.3g}"


def format_research_changes(result, lang="ko"):
    """금액 비중을 인원 비중으로 바꾸지 않는 간결한 공개용 해설."""
    en = lang == "en"
    lines = ["What changed in the observed sample" if en else "평소와 달라진 움직임"]
    if result.get("status") == "insufficient_data":
        lines.append("Comparable scheduled observations are insufficient; changes are unconfirmed." if en else
                     "비교 가능한 정규 관측이 부족해 변화 여부를 확인하지 못했습니다.")
        return "\n".join(lines)
    observed = _aware_datetime(result.get("observed_at"))
    if observed:
        lines.append(("Collected " if en else "수집 ") + observed.astimezone(KST).strftime("%m/%d %H:%M KST"))
    if not result.get("items"):
        lines.append("No change met the selection thresholds in comparable items." if en else
                     "비교 가능한 항목에서 선정 기준을 넘는 변화가 관측되지 않았습니다.")
    for item in result.get("items", [])[:3]:
        start = len(lines)
        stats, token = item["stats"], _label(item.get("token"))
        if item["kind"].startswith("positioning_"):
            lines.append((f"• {token}: long USD share {stats['previous_long_pct']:g}% → {stats['long_pct']:g}% "
                          f"({stats['delta_pp']:+g}pp vs previous day)." if en else
                          f"• {token}: 현재 포지션 금액 기준 롱 비중 {stats['previous_long_pct']:g}% → "
                          f"{stats['long_pct']:g}% (전일 대비 {stats['delta_pp']:+g}%p)."))
        else:
            lines.append((f"• {token} ({item['chain']}): 24h net inflow ${_money(stats['net_flow'])}; "
                          f"prior {item['baseline_days']} observed days median ${_money(stats['baseline_median'])}. "
                          f"Positive in {stats['positive_observations']}/{stats['total_observations']} observations; "
                          f"liquidity ${_money(stats['liquidity'])}." if en else
                          f"• {token} ({item['chain']}): 24시간 순유입 ${_money(stats['net_flow'])}, "
                          f"이전 {item['baseline_days']}개 관측일 중앙값 ${_money(stats['baseline_median'])}. "
                          f"관측 {stats['total_observations']}회 중 양수 {stats['positive_observations']}회 · "
                          f"유동성 ${_money(stats['liquidity'])}."))
            lines.append(item["token_address"])
        if len("\n".join(lines)) > 800:
            del lines[start:]
            break
    lines.append("Observed samples only; missing days are not zero or evidence of continuous inflows." if en else
                 "관측 표본 내 비교입니다. 누락일은 0이나 연속 유입의 근거로 간주하지 않습니다.")
    if result.get("reasons"):
        lines.append("Some items lack comparable data." if en else "일부 항목은 비교 자료가 부족해 제외했습니다.")
    return "\n".join(lines)
