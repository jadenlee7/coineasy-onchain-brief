"""Run the extracted research logic and build the offline viewer data."""
from dataclasses import asdict
from pathlib import Path
import datetime as dt
import json
import argparse
import math
import re
from models import Digest, Position, Token
from fixtures import NOW, SYNTHETIC, scenarios
from history import PERP_COHORT, TOKEN_COHORT, enrich_digest_from_history, snapshot_digest
from reader_context import comparison_label, observation_label, short_address


LABELS = {
    "comparable": ["같은 기준의 전일", "Comparable prior day"],
    "missing": ["전일 관측 누락", "Missing prior day"],
    "cohort": ["조회 대상 변경", "Changed cohort"],
    "recovery": ["복구 점검", "Recovery check"],
    "unknown": ["수집 시각 미확인", "Unknown collection time"],
    "partial": ["유동성 미관측", "Missing liquidity"],
}


def coverage(snapshots, current):
    """Demo-only transparent coverage adapter; not the production weekly report."""
    by_day = {s["kst_date"]: s for s in snapshots}
    try:
        by_day.update({current["kst_date"]: current})
    except (TypeError, KeyError):
        pass
    result = []
    for offset in range(6, -1, -1):
        day = (NOW + dt.timedelta(hours=9) - dt.timedelta(days=offset)).date().isoformat()
        s = by_day.get(day)
        row = {"day": day}
        for name, cohort, field in [("positioning", PERP_COHORT, "perp_rows"),
                                    ("memecoin", TOKEN_COHORT, "meme_rows")]:
            key = "perp_cohort" if name == "positioning" else "token_cohort"
            if not s:
                state = "missing"
            elif s.get("observation_kind") != "scheduled":
                state = "non_scheduled"
            elif s.get(key) != cohort:
                state = "cohort_changed"
            elif s.get("section_errors", {}).get(name) or not s.get(field):
                state = "unavailable"
            else:
                state = "observed"
            row[name] = state
        result.append(row)
    return result


def build_payload():
    result = {"data_mode": SYNTHETIC, "scenarios": {}, "proof": {
        "description": "Separate real production posts, not the synthetic values above.",
        "date": "2026-09-15", "links": [
            {"label": "Positioning", "url": "https://x.com/Coiniseasy/status/2099682118536417287"},
            {"label": "Memecoin flows", "url": "https://x.com/Coiniseasy/status/2099683376727023770"},
        ]}}
    for key, example in scenarios(snapshot_digest).items():
        digest = enrich_digest_from_history(example["digest"], example["snapshots"])
        try:
            current = snapshot_digest(digest)
        except ValueError:
            current = None
        item = {"title": LABELS[key], "digest": asdict(digest),
                "coverage": coverage(example["snapshots"], current), "labels": {}}
        for lang, english in [("ko", False), ("en", True)]:
            item["labels"][lang] = {
                "observation": observation_label(digest, english=english),
                "positioning": comparison_label(digest, "positioning", english=english),
                "memecoin": comparison_label(digest, "memecoin", english=english),
            }
        for token in item["digest"]["meme_rows"]:
            token["short_address"] = short_address(token["chain"], token["token_address"])
        result["scenarios"][key] = item
    return result



def build_manual_payload(path):
    """Explicit local-only adapter output; no automatic fetch, publication or history."""
    raw = json.loads(Path(path).read_text())
    if raw.get("schema_version") != 1:
        raise ValueError("snapshot schema_version must be 1")
    observed = dt.datetime.fromisoformat(str(raw.get("observed_at", "")).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("observation time must include timezone")
    def number(value, lower=None, upper=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("invalid numeric observation")
        if lower is not None and value < lower or upper is not None and value > upper:
            raise ValueError("numeric observation outside range")
        return value
    if raw.get("perp_cohort") != PERP_COHORT or raw.get("token_cohort") != TOKEN_COHORT:
        raise ValueError("snapshot cohorts must match the supported Nansen Smart Money definitions")
    errors = raw.get("section_errors", {})
    if not isinstance(errors, dict):
        raise ValueError("section_errors must be an object")
    errors = {name: "source_unavailable" for name in ("positioning", "memecoin", "verified_meme") if errors.get(name)}
    def symbol(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9._+$-]{0,31}", value):
            raise ValueError("invalid token symbol")
        return value
    def rows(name):
        value = raw.get(name, [])
        if not isinstance(value, list) or len(value) > 8 or any(not isinstance(row, dict) for row in value):
            raise ValueError("invalid or excessive rows")
        return value
    positions, tokens, seen_positions, seen_tokens = [], [], set(), set()
    for row in rows("perp_rows"):
        token = symbol(row.get("token"))
        if token not in ("BTC", "ETH", "SOL", "HYPE") or token in seen_positions:
            raise ValueError("unsupported or duplicate positioning token")
        seen_positions.add(token)
        positions.append(Position(token, number(row.get("long_pct"), 0, 100)))
    for row in rows("meme_rows"):
        token, chain, address = symbol(row.get("token")), row.get("chain"), row.get("token_address")
        if not isinstance(chain, str) or chain.lower() not in ("base", "solana") or not isinstance(address, str):
            raise ValueError("invalid token identity")
        pattern = r"0x[0-9a-fA-F]{40}" if chain.lower() == "base" else r"[1-9A-HJ-NP-Za-km-z]{32,44}"
        if not re.fullmatch(pattern, address):
            raise ValueError("invalid complete token address")
        identity = chain.lower(), address.lower() if chain.lower() == "base" else address
        if identity in seen_tokens:
            raise ValueError("duplicate token identity")
        seen_tokens.add(identity)
        if row.get("verified_meme") is not True:
            raise ValueError("row does not match the verified meme cohort")
        tokens.append(Token(token, chain, address, number(row.get("net_flow"), 1, 1e15),
                            number(row.get("liquidity"), 100000, 1e15), True))
    if "positioning" in errors:
        positions = []
    if "memecoin" in errors or "verified_meme" in errors:
        tokens = []
    digest = Digest(observed.isoformat(), "manual", "verified_meme", positions, tokens, section_errors=errors)
    enrich_digest_from_history(digest, [])
    item = {"title": ["수동 API 관측", "Manual API observation"], "digest": asdict(digest), "coverage": [], "labels": {}}
    for lang, english in [("ko", False), ("en", True)]:
        item["labels"][lang] = {"observation": observation_label(digest, english=english),
                               "positioning": comparison_label(digest, "positioning", english=english),
                               "memecoin": comparison_label(digest, "memecoin", english=english)}
    for lang in ("ko", "en"):
        if not positions:
            item["labels"][lang]["positioning"] = ("수동 조회의 포지션 자료 미관측" if lang == "ko" else "Positioning data unavailable in this manual snapshot.")
        if not tokens:
            item["labels"][lang]["memecoin"] = ("수동 조회의 검증된 밈 표본 미관측" if lang == "ko" else "Verified meme rows unavailable in this manual snapshot.")
    for token in item["digest"]["meme_rows"]:
        token["short_address"] = short_address(token["chain"], token["token_address"])
    return {"data_mode": "manual_api_observation", "scenarios": {"manual": item}, "proof": build_payload()["proof"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Explicit local sanitized snapshot; never automatically fetched")
    args = parser.parse_args()
    output = Path(__file__).with_name("demo-data.local.json" if args.snapshot else "demo-data.json")
    result = build_manual_payload(args.snapshot) if args.snapshot else build_payload()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"Built {output.name}: {len(result['scenarios'])} scenarios; 0 API calls; 0 publications.")
    if args.snapshot:
        print("Local private data: do not commit or publish. Viewer URL: http://localhost:8000/?local=1")
