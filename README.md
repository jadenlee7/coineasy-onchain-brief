# New: CoinEasy Onchain Research

Start with the [three-step research walkthrough](research/README.md): KRW trading attention → exact token address and distinct Nansen cohorts → changes supported by scheduled observations. It includes the three production research modules, 124 offline tests, and an explicit five-request live CLI.

From the repository root, run `python3 -m http.server 8000 --bind 127.0.0.1`, then open **http://localhost:8000/research/**. No credentials are needed to inspect the saved actual observation or the separately labelled fictional example. See the research README for installing dependencies and using your own Nansen key.

CoinEasy uses the workflow to explain onchain research to Korean communities. Existing public daily brief examples are linked below. New edition delivery and contest qualification require their own receipts; no audience, conversion or investment-performance claims are made.

---

# CoinEasy Onchain Brief

Nansen research, explained for Korean communities. A runnable extraction of the data interpretation layer behind CoinEasy's daily brief: observation context, comparable history, token identity and honest missing-data handling.

**This legacy root demo extracts the research layer of the production workflow.** Its default mode uses invented values and addresses; the new research walkthrough uses the separately disclosed saved observation below. It makes zero Nansen API calls, requires no credentials, stores no user analytics and sends no posts. Real September 15 production links are presented separately as product evidence.

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

See [PROVENANCE.md](PROVENANCE.md) for the exact extracted modules, their hashes and the boundaries of new demo code. The viewers fetch no external assets, fonts or scripts. The research walkthrough bundles CoinEasy branding and existing generated pixel-art scenes locally, with Nansen attribution rendered as text. The source is shared for inspection and reproducibility. No permissive open-source license is granted. Private live outputs and account usage receipts are excluded. The sole reviewed saved observation is `research/demo-data.json`, a normalized manual JUP/Upbit snapshot from September 15, 2026, 22:47 KST. Its holder addresses and token metrics are public onchain data; it includes no account email, key or private receipt.

The optional adapter was validated on September 15, 2026: three successful HTTP responses yielded four core positions and four verified tokens. This is a manual integration check, not proof of meeting the competition quota. The [updated Nansen Academy requirements](https://academy.nansen.ai/articles/3540155-nansen-meridian-buildathon-sep-14-27), checked September 26, specify 100+ API calls between September 14–27. Competition eligibility and submission remain separate from this runnable project.
