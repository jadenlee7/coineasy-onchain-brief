"""실제 구현에서 허용 목록의 순수 검증 함수만 추출한 공개 실행 지원 코드."""
from __future__ import annotations
import re
import math
import zoneinfo
from dataclasses import dataclass
from typing import Any


API_BASE = "https://api.nansen.ai/api/v1"


KST = zoneinfo.ZoneInfo("Asia/Seoul")


CACHE_TTL = 600


_BASE = re.compile(r"0x[0-9a-fA-F]{40}")


_SOLANA = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass(frozen=True)
class TokenQuery:
    chain: str
    address: str


def _valid_address(chain: str, address: Any) -> str:
    if not isinstance(address, str):
        return ""
    if chain == "base" and _BASE.fullmatch(address) and int(address[2:], 16):
        return address.lower()
    if chain == "solana" and _SOLANA.fullmatch(address):
        # 문자열 길이뿐 아니라 실제 32바이트 공개키인지 확인한다.
        number = 0
        for char in address:
            number = number * 58 + _B58.index(char)
        leading = len(address) - len(address.lstrip("1"))
        if leading + (number.bit_length() + 7) // 8 == 32 and number:
            return address
    return ""


def _number(value: Any, *, nonnegative: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    if not math.isfinite(value) or abs(value) > 1e15 or (nonnegative and value < 0):
        return None
    return value


def _count(value: Any) -> int | None:
    number = _number(value, nonnegative=True)
    if number is None or number > 1e9 or number != int(number):
        return None
    return int(number)


def _holders(query, holders):
    data = holders.get('data') if isinstance(holders, dict) else None
    rows, seen = [], set()
    if isinstance(data, list):
        for holder in data[:3]:
            if not isinstance(holder, dict):
                continue
            address = _valid_address(query.chain, holder.get('address'))
            amount = _number(holder.get('token_amount'), nonnegative=True)
            if not address or address in seen or amount is None:
                continue
            seen.add(address)
            rows.append((address, amount, _number(holder.get('value_usd'), nonnegative=True)))
    return rows
