"""Read-only, explicit live demonstration of the production research functions."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from pathlib import Path

import httpx

from nansen_digest.research_token import collect_token_research, format_token_research
from nansen_digest.research_korea import collect_korea_attention, choose_research_asset, build_korea_comparison, format_korea_comparison
from nansen_digest.research_changes import build_research_changes, format_research_changes


def load_history(path: Path | None) -> list:
    """Bound the user-supplied local history; the production builder validates evidence."""
    if path is None:
        return []
    if path.stat().st_size > 1_000_000:
        raise ValueError('history_too_large')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list) or len(data) > 32 or any(not isinstance(row, dict) for row in data):
        raise ValueError('history_must_be_at_most_32_snapshot_objects')
    return data


async def run_live(http: httpx.AsyncClient, api_key: str, *, history: list | None = None,
                   now: dt.datetime | None = None) -> dict:
    """Two public reads, then at most three shared Nansen reads for one mapped token."""
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError('NANSEN_API_KEY_required')
    started = now or dt.datetime.now(dt.timezone.utc)
    if started.tzinfo is None or started.utcoffset() is None:
        raise ValueError('aware_now_required')
    attention = await collect_korea_attention(http, started)
    asset = choose_research_asset(attention)
    token = await collect_token_research(asset, api_key, http=http, now=started) if asset else None
    comparison = build_korea_comparison(attention, token, now=started)
    changes = build_research_changes(history or [], now=started)
    # Only normalized production fields leave the collector; no raw provider payloads.
    if token is not None:
        token = {key: value for key, value in token.items() if key != 'api_events'}
    return {'schema_version': 1, 'observed_at': started.isoformat(), 'asset': asset,
            'token': token, 'korea': comparison, 'changes': changes,
            'api_attempts': (token or {}).get('api_calls', 0),
            '_demo': {'fixture': False, 'kind': 'manual_saved_snapshot',
                      'note': 'Manual Upbit and Nansen read. Not scheduled publication or a continuous live feed.',
                      'history_source': 'user_supplied_local_file_not_independently_verified' if history else 'none'}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly permit up to 2 Upbit and 3 Nansen read requests.')
    parser.add_argument('--history', type=Path, help='Optional local schema-1 scheduled snapshots; no history is fabricated.')
    parser.add_argument('--output', type=Path, default=Path('demo-data.local.json'), help='New local JSON file; existing files are never overwritten.')
    args = parser.parse_args(argv)
    if not args.live:
        parser.error('--live is required; this command may consume Nansen API credits')
    api_key = os.environ.get('NANSEN_API_KEY', '')
    if not api_key.strip():
        parser.error('Set NANSEN_API_KEY in your local environment. Do not put the key in the command line.')
    try:
        history = load_history(args.history)
    except (OSError, ValueError, TypeError):
        parser.error('History must be a readable JSON list of at most 32 snapshots, up to 1 MB.')
    try:
        # Reserve the output before requests to prevent an accidental same-path repeat.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        parser.error('Output must be a new writable local file. No API requests were made.')
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write('{"status":"collecting","kind":"manual_saved_snapshot"}\n')
        output.flush()
        async def run():
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                return await run_live(client, api_key, history=history)
        try:
            bundle = asyncio.run(run())
        except Exception as exc:
            # Never print provider errors or headers: only the exception class.
            output.seek(0)
            json.dump({'status': 'failed', 'error': type(exc).__name__, 'kind': 'manual_saved_snapshot'}, output)
            output.truncate()
            print('Collection failed; no automatic retry. Inspect the local status file.')
            return 1
        output.seek(0)
        json.dump(bundle, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')
        output.truncate()
    print(f'Saved manual observation: {args.output}. Nansen attempts: {bundle["api_attempts"]}.')
    print('This is not a publication receipt or proof of 1,000 qualifying calls.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
