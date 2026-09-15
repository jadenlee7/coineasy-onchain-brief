"""Standalone live orchestration is exercised entirely through a mocked transport."""
import asyncio
import datetime as dt
import json

import httpx
import pytest

import run_research as CLI
from nansen_digest.research_korea import REGISTRY

NOW = dt.datetime(2026, 9, 16, 2, 20, tzinfo=dt.timezone.utc)


def test_read_only_five_call_pipeline_reuses_one_token_analysis():
    calls = []
    address = REGISTRY['KRW-JUP']['address']
    def reply(request):
        calls.append(request)
        if request.url.host == 'api.upbit.com':
            assert request.method == 'GET' and 'apiKey' not in request.headers
            data = ([{'market': 'KRW-JUP'}] if request.url.path.endswith('market/all') else
                    [{'market': 'KRW-JUP', 'acc_trade_price_24h': 1000,
                      'signed_change_rate': 0.02, 'timestamp': NOW.timestamp()*1000}])
            return httpx.Response(200, json=data)
        assert request.url.host == 'api.nansen.ai' and request.method == 'POST'
        body = json.loads(request.content)
        assert body['chain'] == 'solana' and body['token_address'] == address
        if request.url.path.endswith('flow-intelligence'):
            data = [{'smart_trader_net_flow_usd': 100, 'whale_net_flow_usd': -50, 'exchange_net_flow_usd': 0}]
        elif request.url.path.endswith('token-information'):
            data = {'contract_address': address, 'symbol': 'JUP', 'token_details': {'total_supply': 1000},
                    'spot_metrics': {'liquidity_usd': 1_000_000, 'volume_total_usd': 5000}}
        else:
            assert request.url.path.endswith('holders')
            data = []
        return httpx.Response(200, json={'data': data, 'irrelevant_private_key': 'MUST_NOT_EXPORT'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            return await CLI.run_live(client, 'LOCAL_KEY_ONLY', now=NOW)
    bundle = asyncio.run(run())
    assert len(calls) == 5
    assert bundle['api_attempts'] == 3
    assert bundle['korea']['direction'] == 'divergent'
    assert bundle['token']['identity_verified']
    assert bundle['changes']['status'] == 'insufficient_data'
    assert bundle['_demo']['fixture'] is False
    assert bundle['_demo']['kind'] == 'manual_saved_snapshot'
    serialized = json.dumps(bundle, allow_nan=False)
    for secret in ('LOCAL_KEY_ONLY', 'MUST_NOT_EXPORT', 'irrelevant_private_key', 'api_events'):
        assert secret not in serialized


def test_no_live_opt_in_never_requests(monkeypatch):
    monkeypatch.setenv('NANSEN_API_KEY', 'fixture')
    monkeypatch.setattr(CLI, 'run_live', lambda *a, **k: pytest.fail('unexpected call'))
    with pytest.raises(SystemExit) as exc:
        CLI.main([])
    assert exc.value.code == 2


def test_missing_key_never_creates_output(monkeypatch, tmp_path):
    monkeypatch.delenv('NANSEN_API_KEY', raising=False)
    target = tmp_path/'demo.local.json'
    with pytest.raises(SystemExit):
        CLI.main(['--live', '--output', str(target)])
    assert not target.exists()


def test_existing_output_prevents_paid_repeat(monkeypatch, tmp_path):
    monkeypatch.setenv('NANSEN_API_KEY', 'fixture')
    target = tmp_path/'demo.local.json'
    target.write_text('keep')
    monkeypatch.setattr(CLI, 'run_live', lambda *a, **k: pytest.fail('unexpected call'))
    with pytest.raises(SystemExit):
        CLI.main(['--live', '--output', str(target)])
    assert target.read_text() == 'keep'


@pytest.mark.parametrize('data', [{}, [None], [{}]*33])
def test_malformed_history_rejected(data, tmp_path):
    target = tmp_path/'history.json'
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        CLI.load_history(target)


def test_no_history_does_not_create_fake_baseline():
    assert CLI.load_history(None) == []
