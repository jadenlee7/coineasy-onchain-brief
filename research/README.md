# CoinEasy Onchain Research — reproducible core

Three working research functions turn Nansen data into Korean-language questions and explanations:

1. **Address-specific research:** smart-trader, whale and exchange net flows, liquidity, volume and top-address context for one exact token address.
2. **Changes worth investigating:** compare compatible scheduled observations; distinguish a positioning flip or unusual inflow from missing evidence.
3. **KRW trading attention × onchain:** rank current Upbit KRW traded value, select one officially mapped Solana token, and compare independent Nansen cohort directions.

These are the exact three production research modules, plus an explicit allowlist of their pure validation helpers. See [PROVENANCE.md](PROVENANCE.md) and [provenance.json](provenance.json). This standalone package has no message sender or scheduler.

## Reproduce in under 10 minutes

Python 3.11 or newer is required. From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python run_research.py --help
```

The offline tests make **zero network requests**. They execute production behavior for identity mismatches, missing data, invalid numbers, observation windows, ranking denominators, cohort overlap and finite budgets. The CLI test verifies the whole five-request sequence with a fake HTTP transport.

## Optional real read

Set `NANSEN_API_KEY` using your own shell environment or local secret manager. Never commit it, paste it into a command argument or enter it in a browser. This package does not obtain credentials from another application.

```sh
python run_research.py --live
```

This explicitly requests two public Upbit reads and, **only when a fresh mapped token is available**, three Nansen reads. They query `/tgm/flow-intelligence`, `/tgm/holders` and `/tgm/token-information` once each for the same token. This shares the paid result between the token-research and Korea-comparison features. There are no retries or polling loops. An Upbit failure or absent eligible mapping stops the Nansen portion; do not generate calls solely to increase a contest counter.

The default output is `demo-data.local.json`, ignored by git. It is labelled **manual saved observation**, not a scheduled publication or continuously live feed. An existing output path blocks a repeat before any request. Pick a new `--output another-observation.local.json` only when intentionally making another paid read.

The output is normalized data, not provider response bodies or headers. It does contain public token and holder addresses. Inspect any local observation before sharing it. For a presentation UI that supports the production bundle shape, import this file explicitly; do not silently substitute it for a labelled fixture.

## Optional scheduled history

```sh
python run_research.py --live --history observations.local.json --output with-history.local.json
```

History is a local JSON list, at most 32 schema-1 objects and 1 MB. The production change detector checks date, timezone, `observation_kind: scheduled`, exact cohort identity, section errors, token addresses and comparable time windows. It requires today's regular observation and at least three comparable prior days. Manual/recovery rows cannot stand in for scheduled observations. The package does not verify the origin of a user-supplied history file; that limitation is labelled in output. With no valid history it says **insufficient data**, never zero change.

## Interpretation

- Upbit KRW traded value is a trading-attention proxy, not a count of Korean people, Korea-wide activity or buying pressure.
- Rank/share denominators include only fresh (15-minute) valid currently listed KRW tickers. Coverage counts are retained.
- `signed_change_rate` is relative to the previous UTC close, **not** a 24-hour price return.
- JUP/WIF addresses are explicitly mapped from issuer sources. Current Upbit listing and Nansen token-information identity are rechecked; matching a ticker alone is insufficient.
- Nansen observations expire after 10 minutes; Upbit/Nansen observation skew must also be within 15 minutes. Fetch times are not claimed to be provider observation times.
- Smart-trader and whale cohorts may overlap and are never added together. Flows do not establish price causation or predict returns.
- The CLI's attempt count is not proof of successful or qualifying buildathon calls. The package makes no claim to have met 1,000 calls.

No open-source licence is assigned by this package. Publication permissions and contest submission remain separate from local execution.

## Interactive walkthrough

Run `python -m http.server 8000 --bind 127.0.0.1` from this directory and open `http://localhost:8000`. The default is a saved actual manual API observation from September 15, 2026, 22:47 KST; it is not a live feed. A separate, explicitly labelled fictional example demonstrates change detection when regular history is available. The preview is an excerpt, not a publication receipt.

After `python run_research.py --live`, open `http://localhost:8000/?local=1` to display your own new result. A missing local result shows an error and never silently falls back to the saved example. Refreshing the page does not make API calls.

## CoinEasy × Nansen visual walkthrough

The bilingual research page follows the same Easyboy pixel-art world as the 55-second product demo: Easyboy’s office, a token research dive, then the evidence desk. CoinEasy’s wordmark and characters guide the flow; Nansen is credited as a data source with mint and deep-teal styling. NORI is a CoinEasy character concept, not an official Nansen mascot. All images are local files; the page has no tracking, paid queries or publishing controls. Asset hashes are in `assets/brand-manifest.json`.

The featured product film shows this working page using the saved observation. It is an edited walkthrough, not an uninterrupted live API recording. Full token identity, separate cohort interpretation, the missing-history state and Korean research preview remain functional. The text-copy action only copies a research command; it does not send a message.
