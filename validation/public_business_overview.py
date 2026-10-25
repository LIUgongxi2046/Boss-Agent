from aiohttp import web

from business import require
from boss_business_overview import BusinessOverviewAPI

READ_ACTIONS = frozenset({'boss.business_overview.dimensions', 'boss.business_overview.read', 'boss.business_overview.detail',
                          'boss.business_overview.preparation', 'boss.business_overview.preparation.verify'})


def read_business_overview(store, role, action, payload):
    require(action in READ_ACTIONS, '经营总览读取动作无效', web.HTTPBadRequest)
    service = BusinessOverviewAPI(store)
    if action == 'boss.business_overview.dimensions':
        require(payload == {}, '经营范围选项不接受额外参数', web.HTTPBadRequest)
        return service.dimensions(role)
    if action == 'boss.business_overview.read':
        return service.read(role, payload)
    if action == 'boss.business_overview.preparation':
        return service.preparation().read(role, payload)
    if action == 'boss.business_overview.preparation.verify':
        require(isinstance(payload, dict) and set(payload) == {'input', 'context_sha256'}, '经营准备核查字段无效', web.HTTPBadRequest)
        return service.preparation().verify(role, payload['input'], payload['context_sha256'])
    return service.detail(role, payload)
