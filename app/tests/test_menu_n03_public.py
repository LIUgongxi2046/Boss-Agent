import pytest

from controls import ControlStore
from boss_command_api import BossCommandAPI
from boss_page_api import BossPageAPI


@pytest.fixture
def store(tmp_path):
    value = ControlStore(tmp_path / 'business-overview-public.sqlite')
    value.initialize('ui-check')
    return value


def current_scope(dimensions):
    period = next(row for row in dimensions['periods'] if row['id'] == 'CURRENT')
    return {'legal_entity_id': dimensions['legal_entity_ids'][0], 'region_id': None,
            'period_start': period['period_start'], 'period_end': period['period_end'],
            'timezone': dimensions['timezones'][0], 'attention': 'ALL'}


def database_state(store):
    with store.connect() as db:
        return {table: db.execute('SELECT * FROM ' + table).fetchall() for table in ('objects', 'audit', 'idempotency')}


def test_current_public_reads_adopt_same_scope_and_remain_readonly(store):
    command = BossCommandAPI(store)
    before = database_state(store)
    status, dimensions = command.execute('BOSS', 'boss.business_overview.dimensions', {})
    assert status == 200
    scope = current_scope(dimensions)
    status, view = command.execute('BOSS', 'boss.business_overview.read', scope)
    assert status == 200 and view['applied_scope'] == scope
    assert [row['page_id'] for row in view['topics']] == ['F' + str(index) for index in range(14, 24)]
    status, detail = command.execute('BOSS', 'boss.business_overview.detail',
                                     {'scope': scope, 'page_id': 'F14', 'snapshot_sha256': view['snapshot_sha256']})
    assert status == 200 and detail['topic'] == view['topics'][0]
    assert detail['business_mutation_performed'] is False
    assert database_state(store) == before


def test_current_public_dimensions_http_and_strict_scope_rejection(store):
    pages, command = BossPageAPI(store), BossCommandAPI(store)
    status, dimensions = pages.serve('BOSS', '/api/boss/ui/business-overview/dimensions')
    assert status == 200
    assert pages.serve('BOSS', '/api/boss/ui/business-overview/dimensions', 'owner_id=other')[0] == 400
    scope = current_scope(dimensions)
    for role, expected in ((None, 401), ('MAINTAINER', 403)):
        assert pages.serve(role, '/api/boss/ui/business-overview/dimensions')[0] == expected
        assert command.execute(role, 'boss.business_overview.read', scope)[0] == expected
    assert command.execute('BOSS', 'boss.business_overview.dimensions', {'owner_id': 'other'})[0] == 400
    assert command.execute('BOSS', 'boss.business_overview.read', {**scope, 'owner_id': 'other'})[0] == 400
    assert command.execute('BOSS', 'boss.business_overview.read', {**scope, 'attention': 'unsupported'})[0] == 400


def test_current_public_source_change_rejects_old_snapshot_and_reopens_current_read(store):
    command = BossCommandAPI(store)
    status, dimensions = command.execute('BOSS', 'boss.business_overview.dimensions', {})
    assert status == 200
    scope = current_scope(dimensions)
    status, previous = command.execute('BOSS', 'boss.business_overview.read', scope)
    assert status == 200
    store.control('ui-check', 'withdraw', {'source_id': 'finance-note', 'version': '1'})
    status, rejected = command.execute('BOSS', 'boss.business_overview.detail',
                                       {'scope': scope, 'page_id': 'F14', 'snapshot_sha256': previous['snapshot_sha256']})
    assert status == 409
    status, current = command.execute('BOSS', 'boss.business_overview.read', scope)
    assert status == 200 and current['query_handoff'] is None
    assert all(row['value'] is None for row in current['metrics'])
    restored = BossCommandAPI(ControlStore(store.path)).execute('BOSS', 'boss.business_overview.read', scope)[1]
    assert restored['snapshot_sha256'] == current['snapshot_sha256']
