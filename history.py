"""일별 관측 보관과 동일 코호트의 정확한 전일 비교."""
from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import asdict
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
PERP_COHORT = "hyperliquid:smart_money:current_position_usd:v1"
TOKEN_COHORT = "smart_money:meme:24h:v1"
SNAPSHOT_KEY = "coineasydaily:nansen_digest:snapshot:{kst_date}"
SNAPSHOT_TTL = 60 * 86400


def _aware_datetime(value):
    """출처 시각은 시간대가 있는 값만 인정한다."""
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _observation_time(digest, now):
    supplied = getattr(digest, "observed_at", None)
    if supplied is not None:
        # 잘못된 수집 시각을 렌더 시각으로 대체하면 전일 비교가 성립한 것처럼 보인다.
        return _aware_datetime(supplied)
    return _aware_datetime(now if now is not None else dt.datetime.now(dt.timezone.utc))


def _regular_observation(kind):
    # 기존 schema 1에는 목적 필드가 없다. 과거 관측을 정규 수집으로 재분류하지 않는다.
    return kind in (None, "unknown", "scheduled")


def snapshot_digest(digest, now=None):
    observed = _observation_time(digest, now)
    if observed is None:
        raise ValueError("snapshot requires a valid timezone-aware observation time")
    kind = getattr(digest, "observation_kind", "unknown")
    if kind not in ("unknown", "scheduled", "manual", "recovery_probe"):
        raise ValueError("snapshot has an unsupported observation kind")
    return {
        "schema_version": 1,
        "kst_date": observed.astimezone(KST).date().isoformat(),
        "observed_at": observed.astimezone(dt.timezone.utc).isoformat(),
        "observation_kind": kind,
        "perp_cohort": PERP_COHORT,
        "token_cohort": TOKEN_COHORT if digest.token_mode == "verified_meme" else "candidate:24h:v1",
        "perp_rows": [asdict(row) for row in digest.perp_rows],
        "meme_rows": [asdict(row) for row in digest.meme_rows],
        "section_errors": dict(digest.section_errors),
    }


async def persist_snapshot(redis, snapshot):
    """하루 첫 유효 관측을 고정해 재실행이 전일 비교를 바꾸지 않게 한다."""
    if not _regular_observation(snapshot.get("observation_kind")):
        return False
    observed = _aware_datetime(snapshot.get("observed_at"))
    if observed is None or observed.astimezone(KST).date().isoformat() != snapshot.get("kst_date"):
        return False
    return await redis.set(
        SNAPSHOT_KEY.format(kst_date=snapshot["kst_date"]),
        json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
        ex=SNAPSHOT_TTL, nx=True,
    )


async def load_snapshots(redis, end_date, days=7):
    end = dt.date.fromisoformat(str(end_date)) if not isinstance(end_date, dt.date) else end_date
    result = []
    for offset in range(min(max(int(days), 1), 60) - 1, -1, -1):
        day = (end - dt.timedelta(days=offset)).isoformat()
        raw = await redis.get(SNAPSHOT_KEY.format(kst_date=day))
        try:
            item = json.loads(raw) if raw else None
        except (ValueError, TypeError):
            continue
        if (isinstance(item, dict) and item.get("schema_version") == 1 and item.get("kst_date") == day
                and _regular_observation(item.get("observation_kind"))):
            result.append(item)
    return result


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _comparable_observation(snapshot, now, days_ago):
    """날짜뿐 아니라 수집 시각도 전일 정규 관측과 1시간 이내여야 한다."""
    try:
        observed = _aware_datetime(snapshot.get("observed_at"))
        if observed is None or not _regular_observation(snapshot.get("observation_kind")):
            return False
        expected = now - dt.timedelta(days=days_ago)
        return (observed.astimezone(KST).date() == expected.astimezone(KST).date()
                and abs((observed - expected).total_seconds()) <= 3600)
    except (ValueError, TypeError, OverflowError):
        return False


def _comparison_reason(snapshot, now, cohort_key, cohort):
    if snapshot is None:
        return "no_previous_snapshot"
    if not _regular_observation(snapshot.get("observation_kind")):
        return "non_scheduled_observation"
    if snapshot.get(cohort_key) != cohort:
        return "cohort_changed"
    if not _comparable_observation(snapshot, now, 1):
        return "time_mismatch"
    return "available"


def _observed_meme_rows(snapshot):
    """비어 있거나 실패한 전일 표본은 신규 등장이나 연속 관측의 근거가 아니다."""
    rows = snapshot.get("meme_rows")
    errors = snapshot.get("section_errors", {})
    if (not isinstance(rows, list) or not rows or not isinstance(errors, dict)
            or errors.get("memecoin") or errors.get("verified_meme")):
        return None
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("verified_meme") is not True
                or not isinstance(row.get("chain"), str) or not row["chain"].strip()
                or not isinstance(row.get("token_address"), str) or not row["token_address"].strip()
                or _finite(row.get("net_flow")) is None):
            return None
        identity = row["chain"], row["token_address"]
        if identity in seen:
            return None
        seen.add(identity)
    return rows


def enrich_digest_from_history(digest, snapshots, now=None):
    """누락일을 건너뛰지 않고 동일 조회 정의의 연속 관측만 비교한다."""
    digest.comparison_context = {"positioning": "unknown", "memecoin": "unknown"}
    for row in [*digest.perp_rows, *getattr(digest, "perp_dynamic", [])]:
        row.long_pct_delta_pp = None
    for row in digest.meme_rows:
        row.new_to_sample = None
        row.observed_positive_streak = None
    if not _regular_observation(getattr(digest, "observation_kind", None)):
        digest.comparison_context = dict.fromkeys(digest.comparison_context, "non_scheduled_observation")
        return digest
    now = _observation_time(digest, now)
    if now is None:
        digest.comparison_context = dict.fromkeys(digest.comparison_context, "time_mismatch")
        return digest
    today = now.astimezone(KST).date()
    by_date = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
            continue
        day = snapshot.get("kst_date")
        if not isinstance(day, str):
            continue
        previous = by_date.get(day)
        # 별도 점검 자료가 같은 날짜의 원래 관측을 덮어쓰지 않는다.
        if previous is None or (_regular_observation(snapshot.get("observation_kind"))
                                and not _regular_observation(previous.get("observation_kind"))):
            by_date[day] = snapshot
    yesterday = by_date.get((today - dt.timedelta(days=1)).isoformat())
    context = digest.comparison_context
    context["positioning"] = _comparison_reason(yesterday, now, "perp_cohort", PERP_COHORT)
    if context["positioning"] == "available":
        rows = yesterday.get("perp_rows")
        errors = yesterday.get("section_errors", {})
        usable = (isinstance(rows, list) and isinstance(errors, dict) and not errors.get("positioning"))
        old, repeated = {}, set()
        for row in rows if usable else []:
            if isinstance(row, dict) and isinstance(row.get("token"), str):
                if row["token"] in old:
                    repeated.add(row["token"])
                old[row["token"]] = row
        if not digest.perp_rows:
            context["positioning"] = "unknown"
        for row in digest.perp_rows:
            previous = _finite(old.get(row.token, {}).get("long_pct"))
            current = _finite(row.long_pct)
            if (row.token not in repeated and previous is not None and 0 <= previous <= 100
                    and current is not None and 0 <= current <= 100):
                row.long_pct_delta_pp = round(current - previous, 1)
            else:
                context["positioning"] = "previous_value_missing"
    if digest.token_mode != "verified_meme":
        context["memecoin"] = "candidate_sample"
        return digest
    context["memecoin"] = _comparison_reason(yesterday, now, "token_cohort", TOKEN_COHORT)
    previous_rows = _observed_meme_rows(yesterday) if context["memecoin"] == "available" else None
    if context["memecoin"] == "available" and previous_rows is None:
        context["memecoin"] = "previous_value_missing"
    previous_ids = {(r["chain"], r["token_address"]) for r in previous_rows or []}
    for row in digest.meme_rows:
        current_flow = _finite(row.net_flow)
        if not row.verified_meme or current_flow is None or current_flow <= 0:
            continue
        if context["memecoin"] == "available":
            row.new_to_sample = (row.chain, row.token_address) not in previous_ids
        streak = 1
        for offset in range(1, 7):
            snapshot = by_date.get((today - dt.timedelta(days=offset)).isoformat(), {})
            if snapshot.get("token_cohort") != TOKEN_COHORT or not _comparable_observation(snapshot, now, offset):
                break
            observed_rows = _observed_meme_rows(snapshot)
            match = next((r for r in observed_rows or [] if isinstance(r, dict)
                          and r.get("chain") == row.chain and r.get("token_address") == row.token_address
                          and r.get("verified_meme") is True), None)
            flow = _finite(match.get("net_flow")) if match else None
            if flow is None or flow <= 0:
                break
            streak += 1
        # 표본에서 빠진 날의 흐름은 미관측이다. 시장 전체 연속유입으로 표현하지 않는다.
        row.observed_positive_streak = streak
    return digest
