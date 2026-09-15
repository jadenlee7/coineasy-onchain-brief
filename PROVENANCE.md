# Source, data and evidence boundaries

## Faithful extraction

These modules were copied byte for byte from CoinEasy's current reader-upgrade source on September 15, 2026. Their presence here does not by itself establish a production deployment. They import only Python standard-library modules. The Redis persistence helpers remain in the extraction for fidelity but are never called by the default demo.

| Public module | Source module | Method | SHA-256 |
|---|---|---|---|
| `history.py` | `nansen_digest/history.py` | Exact byte copy | `1158f19c0756c050237be9d4fcf6fcdc2df58b0f70a78892fb1f24c4efbb52e3` |
| `reader_context.py` | `nansen_digest/reader_context.py` | Exact byte copy | `396704cd86201f419428ec284099ac4029ac68fb681de57ca3c136a677c0c93f` |

`history.py` owns comparable observations, snapshot metadata and missing-day boundaries. `reader_context.py` owns English/Korean observation and comparison labels and visual address shortening. Namespace constants are generic source code, not credentials or live Redis contents.

## New standalone code

- `models.py`: minimal compatible dataclasses, independently declared for the demonstration.
- `fixtures.py`: invented numeric values and addresses, clearly labeled synthetic. No raw API snapshot is embedded.
- `app.py`: runs extracted functions, builds bilingual scenario JSON and provides a separate explicit manual-snapshot mode. Its small coverage adapter is new demonstration code, not the production weekly reporting module.
- `index.html`: new offline bilingual viewer. The default browser makes one same-origin JSON request; there are no external fonts, scripts, images, analytics or Nansen requests.
- `test_demo.py`: offline semantic checks for exact-day comparison, missing values, cohort changes, recovery purpose, invalid time and identity.
- `live_nansen.py` and `tests/test_live_nansen.py`: a new optional explicit Nansen adapter and mock tests. They are not required for the synthetic demo. See their CLI for request and credit boundaries.

## Evidence boundaries

The two September 15 public X URLs demonstrate the broader production product. They are intentionally separate from the synthetic example. There are no usage, reach, conversion or revenue counters in the demo. The fixture's positive streak is a deterministic example, not an actual market observation.

No production log, customer identifier, deployment identifier, private receipt, partner-chat image, account email, API key or credential is included. The legacy root viewer embeds no brand image or font: its name is text and its orange “c” is a simple CSS/text mark. The branded `research/` viewer separately bundles CoinEasy wordmark/character art and existing generated pixel-art scenes. It renders Nansen attribution as text and identifies NORI as a CoinEasy character concept, not an official Nansen mascot. See `research/assets/brand-manifest.json` for asset hashes.

## Release status

This standalone source release is separate from the competition submission. No permissive open-source license is granted. The legacy root viewer uses a synthetic default dataset. The new `research/` walkthrough separately includes one explicitly reviewed, normalized manual API observation in `research/demo-data.json` and a clearly labelled fictional example in `research/demo-data.fixture.json`. Other local API outputs and private receipts remain excluded. See `research/provenance.json` for exact production module/helper hashes.
