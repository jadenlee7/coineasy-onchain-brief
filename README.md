# CoinEasy Onchain Brief

Nansen research, explained for Korean communities. A runnable extraction of the data interpretation layer behind CoinEasy's daily brief: observation context, comparable history, token identity and honest missing-data handling.

**This standalone demo extracts the research layer of the production workflow.** Default mode uses invented values and addresses. It makes zero Nansen API calls, requires no credentials, stores no user analytics and sends no posts. Real September 15 production links are presented separately as product evidence.

## Run in under 10 minutes

Requirements: Python 3.10 or newer with the standard library and system timezone data. No package install is required on macOS/Linux with normal timezone data.

```sh
python3 app.py
python3 -m unittest discover -v
python3 -m http.server 8000 --bind 127.0.0.1
```

Open **http://localhost:8000**. Switch English/Korean, select a scenario, and expand a token row. Do not open the HTML with `file://`: the viewer loads its generated JSON through the local server.

The first command executes the actual extracted Python history and label logic and writes `demo-data.json`. The browser renders those outputs; it does not simulate a live API or silently request data. The generated file is already included for convenient inspection, and can be regenerated exactly from the fixture.

## What to try

- **Comparable prior day:** BTC position notional share rises 2 percentage points. This is not 2% price appreciation.
- **Missing prior day:** no comparison is fabricated from the day before yesterday. Positive sample observations stop at the gap.
- **Changed cohort:** the previous number exists, but its cohort no longer matches. No delta is shown.
- **Recovery check:** the explicit recovery purpose suppresses regular comparison and appears outside regular coverage.
- **Unknown collection time:** an invalid input timestamp is not replaced with the current render time.
- **Token details:** the invented Base token called BTC is distinct from the Hyperliquid BTC position. Unknown liquidity is not $0.

The seven-date coverage visualization is a small demo adapter. It is not the production weekly OPS module, and September 9–15 is not presented as a completed calendar week.

## Optional manual Nansen input

The companion `live_nansen.py` adapter supports an explicit read-only Nansen request path. Check its `--help` before use. Supply your own key through `NANSEN_API_KEY`, never in a file committed to this repository. API requests consume your account's credits; fixture mode does not.

```sh
python3 live_nansen.py --help
# Set NANSEN_API_KEY in your environment through your normal secret manager.
# This explicit command makes 3 read requests and consumes API credits:
python3 live_nansen.py --live --output snapshot.local.json
python3 app.py --snapshot snapshot.local.json
```

Then open **http://localhost:8000/?local=1**. Manual mode produces `demo-data.local.json`, labels it as a manual observation and makes no history or scheduled-publication claim. The UI itself does not fetch from Nansen. The adapter creates a sanitized snapshot and a separate numeric usage receipt; it does not retry or publish. Calls and credits are different units, and the receipt does not prove contest eligibility. Local snapshots and API receipts are private outputs: do not commit or publish them. `.gitignore` is a convenience, not a privacy guarantee.

## Design and production use case

CoinEasy's broader deployed workflow delivers Korean briefs to Telegram and English briefs to X, LinkedIn and Threads, followed by optional token research. The public package isolates reusable research semantics. It contains no Telegram/Typefully sender, production configuration, customer identifiers, private receipts or partner messages.

The public X examples in the viewer are:

- [September 15 positioning](https://x.com/Coiniseasy/status/2099682118536417287)
- [September 15 memecoin sample](https://x.com/Coiniseasy/status/2099683376727023770)

These demonstrate actual product output. They do not establish audience size, acquisition, revenue or trading returns. The standalone demo itself has not been deployed as the production service.

## Source and license status

See [PROVENANCE.md](PROVENANCE.md) for the exact extracted modules, their hashes and the boundaries of new demo code. No third-party assets, fonts or scripts are fetched by the viewer. The source is shared for inspection and reproducibility. No permissive open-source license is granted. Live API snapshots and account usage receipts are excluded from this repository.

The optional adapter was validated on September 15, 2026: three successful HTTP responses yielded four core positions and four verified tokens. This is a manual integration check, not proof of 1,000 qualifying calls. Competition eligibility and submission remain separate from this runnable project.
