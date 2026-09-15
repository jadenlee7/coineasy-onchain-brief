"""실제 구현에서 허용 목록의 순수 검증 함수만 추출한 공개 실행 지원 코드."""
from __future__ import annotations
import datetime as dt
import math
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


PERP_COHORT = "hyperliquid:smart_money:current_position_usd:v1"


TOKEN_COHORT = "smart_money:meme:24h:v1"


def _aware_datetime(value):
    """출처 시각은 시간대가 있는 값만 인정한다."""
    try:
        parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _regular_observation(kind):
    # 기존 schema 1에는 목적 필드가 없다. 과거 관측을 정규 수집으로 재분류하지 않는다.
    return kind in (None, "unknown", "scheduled")


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
