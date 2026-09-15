"""일일 리서치의 요청 예산, 식별자, 누락, 시각 및 표현을 오프라인 검증한다."""
import asyncio
import copy
import datetime as dt
import json

import httpx
import pytest

from nansen_digest import research_token as R

NOW = dt.datetime(2026, 9, 15, 2, 20, tzinfo=dt.timezone.utc)
ADDR = '0x' + '1' * 40
OTHER = '0x' + '2' * 40
QUERY = {'chain': 'base', 'address': ADDR}


def bodies():
    return {
        'flow-intelligence': {'data': [{'smart_trader_net_flow_usd': 20_000,
            'smart_trader_wallet_count': 5, 'whale_net_flow_usd': -10_000,
            'whale_wallet_count': 2, 'exchange_net_flow_usd': 0,
            'exchange_wallet_count': 0}]},
        'holders': {'data': [{'address': '0x' + str(x) * 40,
                     'token_amount': 40 - x * 10, 'value_usd': 100} for x in (2, 3, 4)]},
        'token-information': {'data': {'contract_address': ADDR, 'symbol': 'TOKEN',
            'token_details': {'total_supply': 1000},
            'spot_metrics': {'liquidity_usd': 200000, 'volume_total_usd': 50000}}},
    }


def collect(payload=None, statuses=None, **kwargs):
    payload = bodies() if payload is None else payload
    calls = []
    def answer(req):
        calls.append(req)
        endpoint = req.url.path.rsplit('/', 1)[1]
        return httpx.Response((statuses or {}).get(endpoint, 200), json=payload[endpoint])
    result = asyncio.run(R.collect_token_research(QUERY, 'private-key', now=NOW,
                        transport=httpx.MockTransport(answer), **kwargs))
    return result, calls


def test_exact_existing_three_requests_and_json_safe_snapshot():
    result, calls = collect()
    assert len(calls) == result['api_calls'] == 3
    assert result['status'] == 'observed' and result['identity_verified']
    assert result['market']['top3_supply_share_pct'] == 3
    assert result['cohorts']['exchange']['wallet_count'] is None
    assert result['cohorts']['exchange']['net_flow_usd'] == 0
    assert all(req.headers['apiKey'] == 'private-key' for req in calls)
    reqs = {r.url.path.rsplit('/', 1)[1]: json.loads(r.content) for r in calls}
    assert reqs['flow-intelligence'] == {'chain':'base', 'token_address':ADDR, 'timeframe':'1d'}
    assert reqs['holders']['label_type'] == 'all_holders'
    assert reqs['holders']['pagination'] == {'page':1, 'per_page':3}
    assert reqs['token-information']['timeframe'] == '1d'
    assert all(x['provider_at'] is None and x['time_basis'] == 'request_time' for x in result['source_times'].values())
    assert 'private-key' not in json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('section,field,value', [
    ('token-information','contract_address',OTHER),
    ('token-information','chain','solana'),
    ('flow-intelligence','token_address',OTHER),
    ('holders','token_address',OTHER),
])
def test_identity_mismatch_suppresses_all_sections(section, field, value):
    data = bodies()
    target = data[section]['data']
    (target[0] if isinstance(target,list) else target)[field] = value
    result, calls = collect(data)
    assert len(calls) == 3 and not result['identity_verified']
    assert result['status'] == 'unavailable'
    assert not result['cohorts'] and not result['market'] and not result['holders']
    assert result['errors']['identity'] == 'identity_mismatch'
    assert '$20,000' not in R.format_token_research(result, now=NOW)


def test_unverified_identity_blocks_otherwise_valid_flows():
    result, _ = collect(statuses={'token-information':403})
    assert not result['identity_verified'] and result['errors']['identity'] == 'identity_unverified'
    assert result['cohorts'] == {}


@pytest.mark.parametrize('stamp,code', [('2026-09-15T02:20:00','invalid_source_time'),
    ('2026-09-15T01:20:00Z','stale_source_time'),
    ('2026-09-15T03:20:00Z','future_source_time')])
def test_bad_source_time_redacts_relevant_section(stamp,code):
    data = bodies()
    data['flow-intelligence']['observed_at'] = stamp
    result,_ = collect(data)
    assert result['status'] == 'partial' and not result['cohorts']
    assert result['errors']['flows'] == code
    assert result['market']['liquidity_usd'] == 200000


def test_provider_time_and_request_time_are_distinct():
    data = bodies()
    data['flow-intelligence']['observed_at'] = '2026-09-15T02:19:00Z'
    result,_ = collect(data)
    times = result['source_times']['flows']
    assert times['provider_at'] != times['fetched_at'] and times['time_basis'] == 'provider_time'


def test_partial_failure_no_raw_error_or_labels_and_missing_is_not_zero():
    data = bodies()
    data['flow-intelligence'] = {'error':'private-key @everyone'}
    result,_ = collect(data,statuses={'flow-intelligence':500})
    text = R.format_token_research(result,now=NOW)
    assert result['status'] == 'partial' and result['errors']['flows'] == 'http_500'
    assert '스마트 트레이더: 미관측' in text and '$0' not in text
    assert 'private-key' not in text and '@everyone' not in text


def test_invalid_numbers_never_coerced_or_aggregated():
    data=bodies()
    data['flow-intelligence']['data'][0].update(smart_trader_net_flow_usd='1000',whale_net_flow_usd=True)
    data['token-information']['data']['spot_metrics']['liquidity_usd'] = -5
    result,_=collect(data)
    assert result['cohorts']['smart_trader']['net_flow_usd'] is None
    assert result['cohorts']['whale']['net_flow_usd'] is None
    assert result['market']['liquidity_usd'] is None
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('change', ['duplicate','unsorted','over_supply'])
def test_top_three_share_requires_three_distinct_sorted_consistent_addresses(change):
    data=bodies()
    if change=='duplicate': data['holders']['data'][1]['address']=OTHER
    elif change=='unsorted': data['holders']['data'].reverse()
    else: data['holders']['data'][0]['token_amount']=10000
    result,_=collect(data)
    assert result['market']['top3_supply_share_pct'] is None


@pytest.mark.parametrize('age', [601,-61])
def test_expired_cache_is_not_published_as_fresh(age):
    result,_=collect()
    text=R.format_token_research(result,now=NOW+dt.timedelta(seconds=age))
    assert '$20,000' not in text and '수치를 표시하지 않습니다' in text


def test_naive_now_does_not_trigger_api_and_naive_snapshot_redacts():
    with pytest.raises(ValueError,match='aware_now_required'):
        asyncio.run(R.collect_token_research(QUERY,'key',now=NOW.replace(tzinfo=None)))
    result,_=collect()
    result['observed_at']='2026-09-15T02:20:00'
    assert '$20,000' not in R.format_token_research(result,now=NOW)


def test_missing_key_and_invalid_query_do_not_request():
    result=asyncio.run(R.collect_token_research(QUERY,'',now=NOW))
    assert result['api_calls']==0 and result['errors']=={'collection':'missing_api_key'}
    with pytest.raises(ValueError):
        asyncio.run(R.collect_token_research({'chain':'base','address':'<script>'},'key',now=NOW))


def test_compact_bilingual_format_has_identity_interpretation_and_real_command():
    result,_=collect()
    for lang in ('ko','en'):
        text=R.format_token_research(result,lang,now=NOW)
        assert len(text)<=1000
        assert ADDR in text and f'/token base {ADDR}' in text
        assert 'https://www.nansen.ai' in text
    ko=R.format_token_research(result,now=NOW)
    assert '엇갈립니다' in ko and '미집계' in ko


def test_injected_http_is_not_closed():
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:
            httpx.Response(200,json=bodies()[r.url.path.rsplit('/',1)[1]]))) as client:
            result=await R.collect_token_research(QUERY,'key',http=client,now=NOW)
            assert not client.is_closed and result['api_calls']==3
    asyncio.run(scenario())


def test_api_events_record_attempts_without_request_body_headers_or_key():
    result, calls = collect(statuses={'holders': 403})
    assert len(result['api_events']) == len(calls) == result['api_calls'] == 3
    assert {event['section'] for event in result['api_events']} == {'flows', 'holders', 'market'}
    for event in result['api_events']:
        assert set(event) == {'section', 'path', 'requested_at', 'http_status', 'transport_unknown'}
        assert R._aware(event['requested_at']) is not None
        assert event['path'].startswith('/tgm/')
        assert event['http_status'] == (403 if event['section'] == 'holders' else 200)
        assert event['transport_unknown'] is False
    encoded = json.dumps(result['api_events'])
    assert 'private-key' not in encoded and ADDR not in encoded


def test_timeout_records_transport_unknown_once_without_retry():
    calls = []
    def answer(request):
        calls.append(request)
        if request.url.path.endswith('flow-intelligence'):
            raise httpx.ReadTimeout('secret-private-key', request=request)
        return httpx.Response(200, json=bodies()[request.url.path.rsplit('/', 1)[1]])
    result = asyncio.run(R.collect_token_research(QUERY, 'private-key', now=NOW,
                           transport=httpx.MockTransport(answer)))
    assert len(calls) == result['api_calls'] == 3
    event = next(e for e in result['api_events'] if e['section'] == 'flows')
    assert event['http_status'] is None and event['transport_unknown'] is True
    assert 'secret-private-key' not in json.dumps(result)


def test_invalid_json_retains_actual_http_receipt():
    def answer(request):
        if request.url.path.endswith('flow-intelligence'):
            return httpx.Response(200, content='not-json-private-key')
        return httpx.Response(200, json=bodies()[request.url.path.rsplit('/', 1)[1]])
    result = asyncio.run(R.collect_token_research(QUERY, 'private-key', now=NOW,
                           transport=httpx.MockTransport(answer)))
    event = next(e for e in result['api_events'] if e['section'] == 'flows')
    assert event['http_status'] == 200 and event['transport_unknown'] is False
    assert result['errors']['flows'] == 'request_failed'
    assert 'not-json-private-key' not in json.dumps(result)


def test_no_api_events_when_missing_credentials():
    result = asyncio.run(R.collect_token_research(QUERY, '', now=NOW))
    assert result['api_calls'] == 0 and result['api_events'] == []
