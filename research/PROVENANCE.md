# Source provenance

This package preserves `research_token.py`, `research_korea.py` and `research_changes.py` byte-for-byte from the implementation reviewed for CoinEasy's Korean research product. Their three unit test files are also exact copies.

`provenance.json` records SHA-256 hashes. For helper modules it records both the exact source AST node slices and the assembled output file hash. Only the following symbols were extracted; import headers are newly written for standalone use:

- `token_analysis.py`: `API_BASE`, `KST`, `CACHE_TTL`, `_BASE`, `_SOLANA`, `_B58`, `TokenQuery`, `_valid_address`, `_number`, `_count`, `_holders`.
- `history.py`: `KST`, `PERP_COHORT`, `TOKEN_COHORT`, `_aware_datetime`, `_regular_observation`, `_finite`, `_comparable_observation`.
- `ops.py`: `MIN_LIQUIDITY`, `MIN_FLOW` constants only.

No operational module was copied wholesale. Telegram consumers, Typefully publishing, Redis keys, account configuration and private run receipts are absent. `run_research.py`, its CLI tests and package documentation are new standalone glue.

## Primary asset and data references

- [Upbit ticker reference](https://docs.upbit.com/kr/reference/tickers_by_quote): trailing 24-hour traded value; price change refers to previous UTC close.
- [Jupiter official token-list FAQ](https://discuss.jup.ag/t/faq-token-list-v3-verification/23074): JUP mint `JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN`.
- [dogwifcoin official website](https://dogwifcoin.org/): footer contract links to `EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm` on Solana.

These mappings are manually reviewed identifiers, not a claim that a symbol will remain listed. Runtime lookup and address verification remain mandatory.

## Included observation and branded UI

`demo-data.json` is a normalized, manually collected saved observation from September 15, 2026, 22:46–22:47 KST. It includes the public JUP token/holder addresses and sanitized Upbit/Nansen metrics; it is the explicit exception to exclusion of local API outputs. It contains no API key, account email or private usage receipt. `demo-data.fixture.json` is an independently labelled fictional change example. Insufficient actual scheduled history remains insufficient rather than being replaced by fixture values.

`index.html` is the branded bilingual walkthrough used in the product film. The six PNG assets reuse the existing CoinEasy wordmark, Easyboy/diver/NORI art and generated office/underwater scenes; no paid generation is part of running this package. The images are served locally. The Nansen name is data-source attribution, not a claim of official product endorsement. NORI is a CoinEasy concept character, not an official Nansen mascot. `assets/brand-manifest.json` lists exact content hashes. No additional license for trademarks or artwork is granted.
