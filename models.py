"""Standalone models for synthetic research demonstrations; no production services."""
from dataclasses import dataclass, field


@dataclass
class Position:
    token: str
    long_pct: float
    long_pct_delta_pp: float | None = None


@dataclass
class Token:
    token: str
    chain: str
    token_address: str
    net_flow: float
    liquidity: float | None
    verified_meme: bool = True
    new_to_sample: bool | None = None
    observed_positive_streak: int | None = None


@dataclass
class Digest:
    observed_at: str | None
    observation_kind: str = "scheduled"
    token_mode: str = "verified_meme"
    perp_rows: list[Position] = field(default_factory=list)
    meme_rows: list[Token] = field(default_factory=list)
    perp_dynamic: list[Position] = field(default_factory=list)
    section_errors: dict = field(default_factory=dict)
    comparison_context: dict = field(default_factory=dict)
