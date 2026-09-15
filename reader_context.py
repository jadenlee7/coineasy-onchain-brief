"""수집 시각과 비교 근거를 고정 문구로 표시한다. 누락된 메타데이터는 추정하지 않는다."""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
_KINDS = {
    "scheduled": ("정규 관측", "Scheduled observation."),
    "manual": ("수동 관측", "Manual observation."),
    "recovery_probe": ("복구 점검 · 정규 관측 아님", "Recovery check, not a scheduled observation."),
    "unknown": ("관측 용도 미확인", "Observation purpose unconfirmed."),
}
_COMPARISONS = {
    "no_previous_snapshot": ("전일 비교 불가: 전일 관측 없음", "Prior-day comparison unavailable: no prior-day observation."),
    "cohort_changed": ("전일 비교 불가: 조회 대상 기준 변경", "Prior-day comparison unavailable: cohort changed."),
    "time_mismatch": ("전일 비교 불가: 수집 시각 기준 미충족", "Prior-day comparison unavailable: collection times not comparable."),
    "previous_value_missing": ("전일 비교 불가: 해당 항목의 전일 유효 관측 없음", "Prior-day comparison unavailable: prior values unobserved."),
    "candidate_sample": ("전일 비교 미제공: 투자 집단 미확인 후보 표본", "Prior-day comparison unavailable: candidate cohort unconfirmed."),
    "non_scheduled_observation": ("전일 비교 미제공: 정규 관측 아님", "Prior-day comparison unavailable: non-scheduled observation."),
    "unknown": ("전일 비교 미확인", "Prior-day comparison unconfirmed."),
}


def _observed(digest):
    raw = getattr(digest, "observed_at", None)
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    try:
        value = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value.astimezone(KST) if value.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def observation_label(digest, *, english=False):
    """API의 최종 갱신 시각이 아닌, 해당 실행의 수집 기준 시각을 표시한다."""
    kind = getattr(digest, "observation_kind", "unknown")
    if not isinstance(kind, str) or kind not in _KINDS:
        kind = "unknown"
    observed = _observed(digest)
    purpose = _KINDS[kind][bool(english)]
    if english:
        prefix = f"Collected {observed:%m/%d %H:%M} KST." if observed else "Collection time unobserved."
        return f"{prefix}\n{purpose}"
    prefix = f"수집: {observed:%m/%d %H:%M} KST" if observed else "수집 시각 미관측"
    return f"{prefix} · {purpose}"


def observation_date_label(digest):
    """작은 카드 날짜 영역에도 수집 시각을 남기며 렌더 시각으로 대체하지 않는다."""
    observed = _observed(digest)
    return f"{observed:%m/%d %H:%M} KST" if observed else "수집 시각 미관측"


def comparison_label(digest, section, *, english=False):
    """유효한 비교 수치는 기존 해설로 전달하고 미비 사유만 한 번 표시한다."""
    context = getattr(digest, "comparison_context", None)
    code = context.get(section) if isinstance(context, dict) else None
    if code == "available":
        return ""
    if not isinstance(code, str) or code not in _COMPARISONS:
        code = "unknown"
    return _COMPARISONS[code][bool(english)]


def short_address(chain, address):
    """전체 주소를 검증한 뒤 시각적 식별용으로만 줄인다. 비교·조회 키로 쓰지 않는다."""
    if not isinstance(chain, str) or not isinstance(address, str):
        return "주소 미관측"
    if chain.lower() == "base" and re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
        value = address.lower()
    elif chain.lower() == "solana" and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address):
        value = address
    else:
        return "주소 미관측"
    return value[:6] + "…" + value[-4:]
