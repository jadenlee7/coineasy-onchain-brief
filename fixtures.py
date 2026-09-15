"""Explicitly synthetic values and addresses. No Nansen API data or calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from models import Digest, Position, Token

NOW = datetime(2026, 9, 15, 2, 5, tzinfo=timezone.utc)
SYNTHETIC = "Synthetic demo fixture — not live Nansen data"


def digest_at(day, kind="scheduled"):
    offset = (NOW.date() - day.date()).days
    return Digest(
        observed_at=day.isoformat(), observation_kind=kind,
        perp_rows=[Position("BTC", 62.0 - offset * 2), Position("ETH", 47.0 + offset),
                   Position("SOL", 55.0), Position("HYPE", 71.0 - offset)],
        meme_rows=[Token("BTC", "base", "0x" + "1" * 40, 26000.0, 210000.0),
                   Token("LEAF", "base", "0x" + "2" * 40, 8100.0, 150000.0)],
    )


def scenarios(snapshot_digest):
    history = [snapshot_digest(digest_at(NOW - timedelta(days=d))) for d in range(6, 0, -1)]
    full = dict(digest=digest_at(NOW), snapshots=history)
    missing = deepcopy(full)
    missing["snapshots"] = missing["snapshots"][:-1]
    changed = deepcopy(full)
    changed["snapshots"][-1]["perp_cohort"] = "demo:other-cohort"
    changed["snapshots"][-1]["token_cohort"] = "demo:other-cohort"
    recovery = deepcopy(full)
    recovery["digest"].observation_kind = "recovery_probe"
    unknown = deepcopy(full)
    unknown["digest"].observation_kind = "unknown"
    unknown["digest"].observed_at = "not-a-timestamp"
    partial = deepcopy(full)
    partial["digest"].meme_rows[1].liquidity = None
    partial["digest"].meme_rows[1].verified_meme = False
    partial["digest"].token_mode = "candidate"
    return {"comparable": full, "missing": missing, "cohort": changed,
            "recovery": recovery, "unknown": unknown, "partial": partial}
