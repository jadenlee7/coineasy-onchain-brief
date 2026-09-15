"""한국 거래 관심의 주소 연결·분모·최신성·요청 예산을 검증한다."""
import asyncio
import copy
import datetime as dt

import httpx
import pytest

from nansen_digest import research_korea as K

NOW = dt.datetime(2026, 9, 15, 13, 35, tzinfo=dt.timezone.utc)


def inputs():
    markets = [{"market": x} for x in ("KRW-BTC", "KRW-JUP", "KRW-WIF", "BTC-JUP")]
    tickers = [{"market": x, "acc_trade_price_24h": volume, "signed_change_rate": -.02,
                "timestamp": int(NOW.timestamp() * 1000)}
               for x, volume in (("KRW-BTC", 600), ("KRW-JUP", 300), ("KRW-WIF", 100), ("BTC-JUP", 999))]
    return markets, tickers


def attention():
    return K.build_korea_attention(*inputs(), NOW)


def research():
    asset = K.REGISTRY['KRW-JUP']
    return {**asset, "identity_verified": True, "timeframe": "1d", "observed_at": NOW.isoformat(),
            "cohorts": {"smart_trader": {"net_flow_usd": 500}, "whale": {"net_flow_usd": -200}}}


def test_real_asset_registry_not_symbol_join():
    att = attention()
    assert K.choose_research_asset(att)['address'] == 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN'
    assert K.choose_research_asset(att)['market'] == 'KRW-JUP'
    assert att['rows'][1]['rank'] == 2
    assert att['rows'][1]['traded_value_share_pct'] == 30
    assert att['observed_count'] == 3
    assert att['total_traded_value_krw'] == 1000
    assert att['rows'][1]['price_change_since_utc_close_pct'] == -2


def test_no_listing_or_warning_never_selects_asset():
    markets, tickers = inputs()
    markets = [m for m in markets if m['market'] != 'KRW-JUP']
    markets[1]['market_event'] = {'warning': True}
    att = K.build_korea_attention(markets, tickers, NOW)
    assert K.choose_research_asset(att) is None
    assert K.build_korea_comparison(att, research(), NOW)['reason'] == 'no_verified_asset'


@pytest.mark.parametrize('invalid', [True, None, '12', float('nan'), float('inf'), -1, 10**400])
def test_invalid_volume_not_zero_or_denominator(invalid):
    markets, tickers = inputs()
    tickers[0]['acc_trade_price_24h'] = invalid
    att = K.build_korea_attention(markets, tickers, NOW)
    assert att['status'] == 'partial'
    assert att['observed_count'] == 2
    assert att['total_traded_value_krw'] == 400
    assert att['rows'][0]['traded_value_share_pct'] == 75


def test_duplicate_ticker_blocks_ambiguous_ranking():
    markets, tickers = inputs()
    tickers.append(tickers[0])
    assert K.build_korea_attention(markets, tickers, NOW)['reason'] == 'duplicate_ticker'


def test_stale_mapped_asset_not_selected():
    markets, tickers = inputs()
    tickers[1]['timestamp'] -= 901_000
    assert K.choose_research_asset(K.build_korea_attention(markets, tickers, NOW))['symbol'] == 'WIF'


@pytest.mark.parametrize('field,value,reason', [
    ('address', '0x'+'b'*40, 'asset_mismatch'), ('chain', 'base', 'asset_mismatch'),
    ('identity_verified', False, 'identity_unverified'), ('timeframe', '7d', 'window_mismatch'),
    ('observed_at', (NOW-dt.timedelta(minutes=16)).isoformat(), 'stale_or_skewed_sources'),
    ('observed_at', NOW.replace(tzinfo=None).isoformat(), 'stale_or_skewed_sources'),
    ('observed_at', (NOW+dt.timedelta(minutes=2)).isoformat(), 'stale_or_skewed_sources')])
def test_unsafe_comparisons_never_publish_flow(field, value, reason):
    data = research()
    data[field] = value
    report = K.build_korea_comparison(attention(), data, NOW)
    assert report['status'] == 'unavailable'
    assert report['reason'] == reason
    assert report['onchain'] is None
    assert 'Comparison withheld' in K.format_korea_comparison(report, 'en')


@pytest.mark.parametrize('smart,whale,direction', [(1, 2, 'aligned_inflow'), (-1, -2, 'aligned_outflow'), (-1, 2, 'divergent'), (0, 2, 'flat')])
def test_cohort_directions_independent_of_krw_trading_volume(smart, whale, direction):
    data = research()
    data['cohorts']['smart_trader']['net_flow_usd'] = smart
    data['cohorts']['whale']['net_flow_usd'] = whale
    report = K.build_korea_comparison(attention(), data, NOW)
    assert report['direction'] == direction
    for lang in ('ko', 'en'):
        text = K.format_korea_comparison(report, lang)
        assert len(text) < 800
        assert K.REGISTRY['KRW-JUP']['address'] in text
        assert 'UTC' in text and '24h' in text


def test_missing_cohort_is_not_zero_or_common_direction():
    data = research()
    data['cohorts']['whale']['net_flow_usd'] = None
    report = K.build_korea_comparison(attention(), data, NOW)
    assert report['status'] == 'partial'
    assert report['direction'] is None
    assert '비교 보류' in K.format_korea_comparison(report)


def test_http_exact_two_official_public_requests_no_auth():
    calls = []
    markets, tickers = inputs()
    def respond(request):
        calls.append(request)
        assert request.url.host == 'api.upbit.com'
        assert 'apiKey' not in request.headers
        return httpx.Response(200, json=markets if request.url.path.endswith('market/all') else tickers)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await K.collect_korea_attention(client, NOW)
    assert asyncio.run(run())['status'] == 'ok'
    assert len(calls) == 2
    assert calls[1].url.params['quote_currencies'] == 'KRW'


def test_http_failure_stops_without_retry():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={'error': {}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await K.collect_korea_attention(client, NOW)
    assert asyncio.run(run())['status'] == 'unavailable'
    assert len(calls) == 1


def test_actual_flow_request_time_cannot_be_hidden_by_fresh_report_time():
    data = research()
    data['source_times'] = {'flows': {'fetched_at': (NOW-dt.timedelta(minutes=16)).isoformat()}}
    report = K.build_korea_comparison(attention(), data, NOW)
    assert report['reason'] == 'stale_or_skewed_sources'


def test_two_fresh_sources_can_still_exceed_skew_limit():
    att = attention()
    att['rows'][1]['source_at'] = (NOW-dt.timedelta(minutes=15)).isoformat()
    data = research()
    data['observed_at'] = (NOW+dt.timedelta(seconds=60)).isoformat()
    report = K.build_korea_comparison(att, data, NOW)
    assert report['reason'] == 'stale_or_skewed_sources'


@pytest.mark.parametrize('age,status', [(600, 'ok'), (601, 'unavailable')])
def test_nansen_matches_shared_cache_ttl(age, status):
    data = research()
    data['source_times'] = {'flows': {'fetched_at': (NOW-dt.timedelta(seconds=age)).isoformat()}}
    report = K.build_korea_comparison(attention(), data, NOW)
    assert report['status'] == status


@pytest.mark.parametrize('age,observed,total', [(900, 3, 1000), (901, 2, 400)])
def test_all_ranking_denominator_rows_require_fresh_ticker(age, observed, total):
    markets, tickers = inputs()
    tickers[0]['timestamp'] -= age * 1000
    result = K.build_korea_attention(markets, tickers, NOW)
    assert result['observed_count'] == observed
    assert result['total_traded_value_krw'] == total
    assert result['rows'][0]['market'] == ('KRW-BTC' if observed == 3 else 'KRW-JUP')
