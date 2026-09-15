"""공개 변화 해설의 관측 범위와 불완전 자료 경계를 검증한다."""
import datetime as dt
import json
from copy import deepcopy

import pytest

from nansen_digest.history import PERP_COHORT, TOKEN_COHORT
from nansen_digest.research_changes import build_research_changes, format_research_changes

NOW = dt.datetime(2026, 9, 16, 2, 20, tzinfo=dt.timezone.utc)
ADDRESS = "0x" + "1" * 40


def snapshot(offset=0, long=65, flow=200_000):
    observed = NOW - dt.timedelta(days=offset)
    return {"schema_version": 1, "kst_date": observed.date().isoformat(),
            "observed_at": observed.isoformat(), "observation_kind": "scheduled",
            "perp_cohort": PERP_COHORT, "token_cohort": TOKEN_COHORT, "section_errors": {},
            "perp_rows": [{"token": "BTC", "long_pct": long}],
            "meme_rows": [{"token": "LEAF", "chain": "Base", "token_address": ADDRESS,
                           "net_flow": flow, "liquidity": 200_000, "verified_meme": True}]}


def history():
    return [snapshot(), *[snapshot(i, long=45, flow=20_000) for i in range(1, 5)]]


def build(rows=None):
    return build_research_changes(history() if rows is None else rows, NOW)


def test_selects_real_changes_with_exact_identity_and_evidence():
    result = build()
    assert result["status"] == "observations"
    position, meme = result["items"]
    assert position["kind"] == "positioning_flip"
    assert position["stats"]["delta_pp"] == 20
    assert meme["kind"] == "meme_inflow_spike"
    assert meme["token_address"] == ADDRESS
    assert meme["baseline_days"] == 4
    assert meme["stats"]["positive_observations"] == 5
    assert len(meme["baseline_observed_at"]) == 4
    json.dumps(result, allow_nan=False)
    for language in ("ko", "en"):
        text = format_research_changes(result, language)
        assert ADDRESS in text
        assert len(text) <= 1000
        assert "200,000" in text
        assert "continuous" in text if language == "en" else "연속" in text


def test_no_change_is_not_insufficient_source():
    result = build([snapshot(i, long=45, flow=20_000) for i in range(5)])
    assert result["status"] == "no_material_change"
    assert not result["items"]
    assert "선정 기준" in format_research_changes(result)
    missing = build([])
    assert missing["status"] == "insufficient_data"
    assert "확인하지 못" in format_research_changes(missing)


@pytest.mark.parametrize("kind", ["unknown", None, "manual", "recovery_probe", [], {}])
def test_non_scheduled_today_is_never_promoted(kind):
    rows = history()
    rows[0]["observation_kind"] = kind
    assert build(rows)["status"] == "insufficient_data"


@pytest.mark.parametrize("bad", [None, "", "garbage", "2026-09-16T02:20:00", "2026-09-17T02:20:00+00:00"])
def test_current_time_must_be_valid_aware_and_not_future(bad):
    rows = history()
    rows[0]["observed_at"] = bad
    assert build(rows)["status"] == "insufficient_data"


def test_malformed_inputs_are_unavailable():
    for rows in (None, {}, "bad", [None, [], {}, {"schema_version": 1}]):
        assert build_research_changes(rows, NOW)["status"] == "insufficient_data"
    assert build_research_changes(history(), "naive")["reasons"] == ["invalid_reference_time"]


@pytest.mark.parametrize("value", [None, True, "bad", float("nan"), float("inf"), -1, 101])
def test_bad_position_values_never_fabricate_change(value):
    rows = history()
    rows[0]["perp_rows"][0]["long_pct"] = value
    result = build(rows)
    assert all(item["kind"] == "meme_inflow_spike" for item in result["items"])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("value", [None, True, "bad", float("nan"), float("inf")])
def test_bad_flow_never_fabricates_spike(value):
    rows = history()
    rows[0]["meme_rows"][0]["net_flow"] = value
    assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])


def test_at_least_three_baselines_required_for_selected_observations():
    assert build(history()[:3])["status"] == "insufficient_data"
    assert build(history()[:4])["status"] == "observations"


def test_prior_day_gap_does_not_become_day_change_or_continuous_flow():
    rows = [row for row in history() if row["kst_date"] != "2026-09-15"]
    result = build(rows)
    assert [item["kind"] for item in result["items"]] == ["meme_inflow_spike"]
    assert result["items"][0]["stats"]["total_observations"] == 4
    assert "exact_previous_day_unavailable" in result["reasons"]


@pytest.mark.parametrize("field,value", [("observation_kind", "recovery_probe"),
                                         ("perp_cohort", "other"), ("token_cohort", "other"),
                                         ("observed_at", "2026-09-15T05:20:00+00:00")])
def test_incomparable_previous_snapshot_is_excluded(field, value):
    rows = history()
    rows[1][field] = value
    result = build(rows)
    if field != "token_cohort":
        assert not any(item["kind"].startswith("positioning") for item in result["items"])
    if field == "token_cohort":
        assert next(item for item in result["items"] if item["kind"] == "meme_inflow_spike")["baseline_days"] == 3


@pytest.mark.parametrize("value", [None, 99_999, float("nan"), -1])
def test_current_and_baseline_liquidity_guards(value):
    rows = history()
    rows[0]["meme_rows"][0]["liquidity"] = value
    assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])
    rows = history()
    for old in rows[1:3]:
        old["meme_rows"][0]["liquidity"] = value
    assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])


def test_same_symbol_different_address_does_not_join():
    rows = history()
    for old in rows[1:]:
        old["meme_rows"][0]["token_address"] = "0x" + "2" * 40
    assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])


def test_case_normalizes_evm_but_preserves_solana():
    rows = history()
    for i, row in enumerate(rows):
        row["meme_rows"][0]["token_address"] = "0x" + ("A" if i % 2 else "a") * 40
    assert next(item for item in build(rows)["items"] if item["kind"] == "meme_inflow_spike")["token_address"] == "0x" + "a" * 40
    for i, row in enumerate(rows):
        row["meme_rows"][0].update(chain="solana", token_address=("A" if i else "a") * 32)
    assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])


@pytest.mark.parametrize("rows_key,section", [("perp_rows", "positioning"), ("meme_rows", "memecoin")])
def test_empty_failed_and_duplicate_rows_are_not_source(rows_key, section):
    for change in ([], None, [None]):
        rows = history()
        rows[0][rows_key] = change
        assert build(rows)["coverage"][section + "_comparable"] == 0
    rows = history()
    rows[0]["section_errors"][section] = "secret-internal-error"
    result = build(rows)
    assert result["coverage"][section + "_comparable"] == 0
    assert "secret" not in json.dumps(result)
    rows = history()
    rows[0][rows_key].append(deepcopy(rows[0][rows_key][0]))
    assert build(rows)["coverage"][section + "_comparable"] == 0


def test_conflicting_same_day_snapshots_reject_ambiguous_date():
    rows = history()
    rows.append(snapshot(long=70))
    assert build(rows)["status"] == "insufficient_data"
    assert build(history() + [snapshot()])["status"] == "observations"


def test_date_corruption_and_old_history_are_not_counted():
    rows = history()[:3]
    wrong = snapshot(3)
    wrong["kst_date"] = "2026-01-01"
    rows.extend([wrong, snapshot(15)])
    assert build(rows)["status"] == "insufficient_data"


def test_statistical_overflow_is_json_safe():
    rows = history()
    for old in rows[1:]:
        old["meme_rows"][0]["net_flow"] = 1e308
    result = build(rows)
    assert not any(item["kind"] == "meme_inflow_spike" for item in result["items"])
    json.dumps(result, allow_nan=False)


def test_repeated_runs_do_not_mutate_inputs_and_selection_is_capped():
    rows = history()
    for row in rows:
        row["perp_rows"] = [dict(row["perp_rows"][0], token=token) for token in ("ETH", "BTC", "SOL", "HYPE")]
    original = deepcopy(rows)
    assert len(build(rows)["items"]) == 3
    assert build(rows) == build(rows)
    assert rows == original


def test_format_budget_retains_complete_addresses_and_no_markup():
    rows = history()
    for row in rows:
        row["perp_rows"] = []
        original = row["meme_rows"][0]
        row["meme_rows"] = [dict(original, token="<b>" + "LONGNAME" * 4,
                                 token_address="0x" + str(i) * 40,
                                 liquidity=1e308) for i in range(1, 5)]
        if row["kst_date"] == NOW.date().isoformat():
            for token in row["meme_rows"]:
                token["net_flow"] = 1e308
    result = build(rows)
    assert len(result["items"]) == 3
    for language in ("ko", "en"):
        text = format_research_changes(result, language)
        assert len(text) <= 1000
        assert "<b>" not in text
        assert ADDRESS in text
        assert all(len(line) == 42 for line in text.splitlines() if line.startswith("0x"))


@pytest.mark.parametrize("seconds,allowed", [(3600, True), (3601, False), (-3600, True), (-3601, False)])
def test_exact_hour_tolerance_boundary(seconds, allowed):
    rows = history()
    rows[1]["observed_at"] = (NOW - dt.timedelta(days=1) + dt.timedelta(seconds=seconds)).isoformat()
    items = build(rows)["items"]
    assert any(item["kind"] == "positioning_flip" for item in items) is allowed


@pytest.mark.parametrize("long,kind", [(49, None), (50, None), (51, "positioning_flip"), (55, "positioning_flip")])
def test_position_selection_thresholds_are_fixed(long, kind):
    rows = history()
    rows[0]["perp_rows"][0]["long_pct"] = long
    selected = [item for item in build(rows)["items"] if item["kind"].startswith("positioning_")]
    assert (selected[0]["kind"] if selected else None) == kind


def test_invalid_meme_identity_or_candidate_flag_cannot_contribute():
    for mutation in ({"token_address": "0x123"}, {"chain": "ethereum"}, {"verified_meme": False}):
        rows = history()
        rows[0]["meme_rows"][0].update(mutation)
        assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])


def test_historical_zero_is_observed_but_missing_days_are_not_zero():
    rows = history()
    rows[1]["meme_rows"][0]["net_flow"] = 0
    result = build(rows)
    meme = next(item for item in result["items"] if item["kind"] == "meme_inflow_spike")
    assert meme["stats"]["positive_observations"] == 4
    assert meme["stats"]["total_observations"] == 5


@pytest.mark.parametrize("chain,address", [("base", "0x" + "0" * 40),
                                           ("solana", "1" * 32), ("solana", "A" * 32),
                                           ("solana", "z" * 44)])
def test_zero_and_bad_decoded_solana_addresses_are_withheld(chain, address):
    rows = history()
    for row in rows:
        row["meme_rows"][0].update(chain=chain, token_address=address)
    assert not any(item["kind"] == "meme_inflow_spike" for item in build(rows)["items"])


def test_valid_32_byte_solana_address_can_join():
    rows = history()
    address = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    for row in rows:
        row["meme_rows"][0].update(chain="Solana", token_address=address)
    assert next(item for item in build(rows)["items"] if item["kind"] == "meme_inflow_spike")["token_address"] == address
