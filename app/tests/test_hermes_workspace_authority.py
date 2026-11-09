import asyncio
import hashlib
import json
import secrets
import shutil
import socket
import sys
from pathlib import Path
from uuid import uuid4

import aiohttp
import httpx
import pytest
from aiohttp import web
from nanobot.bus.queue import MessageBus
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.webui.gateway_services import build_gateway_services
from websockets.asyncio.server import serve

from agent_chat_budget import AgentChatBudget
from agent_artifact_workspace import ArtifactWorkspace
from agent_run_api import product_application
from agent_run_broker import RunBroker, RunIdentity
from agent_run_concurrency import RunConcurrencyBudget
from agent_run_dispatcher import AgentRunDispatcher
from agent_run_method_selection import AgentRunMethodSelection
from agent_run_requirements import RunRequirements
from agent_run_scope import RunScopeService
from agent_run_store import RunStore
from agent_run_tool_budget import RunToolBudget
from boss_memory_sessions import MemorySessionManager
from boss_native_skills import BossSkillCatalog
from boss_simulation_api import _context
from boss_skill_drafts import BossSkillDrafts
from business import checksum
from controls import ControlStore
from hermes_bridge import EngineEventSink, EngineRunConfig, HermesBridge
from hermes_bi_authority import HermesBIQueryAuthority
from hermes_budget_gateway import ProviderGateway, RunBoundBudgetStore
from hermes_process_evidence import HermesProcessEvidence
from hermes_product import HermesProductServices
from hermes_run_authority import HermesRunAuthority
from hermes_run_recovery import HermesRunRecovery
from hermes_runtime_transport import HermesExecutionLifecycle, HermesRuntimeTransport
from hermes_runtime_binding import HermesDeploymentConfig, HermesExecutionFactory
from hermes_transport import HermesTransport
from hermes_transport_client import HermesTransportClient
from hermes_vm_channel import HermesVMServerTLS
from hermes_vm_identity import HermesVMRunAccess, HermesVMRunBindings
from hermes_workspace_relay import HermesWorkspaceRelay
from model_probe import BusinessTool
from role_channel import RoleChannel
from test_hermes_vm_channel import contexts


@pytest.mark.parametrize('ending', ['withdrawal', 'logout', 'cancel', 'revision', 'child_revision', 'child_method', 'child_withdrawal', 'child_logout', 'child_updated', 'child_budget', 'child_metering', 'child_input', 'child_factory', 'child_factory_current', 'child_concurrent', 'child_process_goal', 'child_process_method', 'child_process_withdrawal'])
def test_product_authorization_closes_workspace_connection(tmp_path, ending):
    async def check():
        business = ControlStore(tmp_path / 'business.sqlite')
        business.initialize('ui-check')
        store = RunStore(business.path)
        if ending in {'child_factory', 'child_factory_current'}:
            from agent_simulation_migration_install import install_simulation_migrations
            install_simulation_migrations(business.path)
        RunRequirements(store, allow_migration=True)
        sessions = MemorySessionManager(tmp_path / 'workspace', business_store=business, sessions_root=tmp_path / 'sessions')
        scope = RunScopeService(business, sessions, 'ui-check')
        broker = RunBroker(store, scope_service=scope)
        skill_workspace = tmp_path / 'method-workspace'
        skill_workspace.mkdir()
        shutil.copytree(Path(__file__).resolve().parents[2] / 'agent/skills', skill_workspace / 'skills')
        skill_config = Config()
        skill_config.agents.defaults.workspace = str(skill_workspace)
        skill_config_path = tmp_path / 'method-config.json'
        save_config(skill_config, skill_config_path)
        skill_registry = ToolRegistry()
        for operation in ('query_metrics', 'read_evidence'):
            skill_registry.register(BusinessTool(operation, business, {'execution_namespace': 'ui-check'}, {}, []))
        catalog = BossSkillCatalog(SkillsLoader(skill_workspace), skill_registry)
        drafts = BossSkillDrafts(business, catalog, skill_config_path)
        broker.method_selection = AgentRunMethodSelection(store, scope, catalog, drafts, allow_migration=True)
        role_secrets = {role: secrets.token_urlsafe(32) for role in ('BOSS', 'MAINTAINER')}
        config = WebSocketConfig(host='127.0.0.1', port=0, token_issue_secret=role_secrets['BOSS'], token_ttl_s=180)
        bus = MessageBus()
        gateway = build_gateway_services(config=config, bus=bus, session_manager=sessions, static_dist_path=None,
            workspace_path=tmp_path, default_restrict_to_workspace=True, config_path=tmp_path / 'config.json',
            runtime_model_name=None, runtime_surface='webui', runtime_capabilities_overrides=None)
        channel = RoleChannel(WebSocketChannel(config, bus, gateway=gateway), role_secrets, tmp_path / 'audit.jsonl', business)
        chat_budget = AgentChatBudget(store, channel, scope, allow_migration=True)
        concurrency = RunConcurrencyBudget(store, allow_migration=True)
        tool_budget = RunToolBudget(store, allow_migration=True)
        evidence = HermesProcessEvidence(store, allow_migration=True)
        bindings = HermesVMRunBindings(store, allow_migration=True)
        recovery = HermesRunRecovery(channel, scope, store)
        services = HermesProductServices(store, scope, broker, HermesBridge(business), recovery, chat_budget)
        dispatcher = AgentRunDispatcher(services)
        server_context, client_context, _, client_hash = contexts(tmp_path)
        active = {}
        budget = {'model_requests': 2, 'rounds': 2, 'tools': 5, 'seconds': 60, 'concurrency': 1,
                  'context_tokens': 128, 'files': 5, 'file_bytes': 1024, 'open_files': 16, 'cpu_seconds': 5}

        async def target(reader, writer):
            assert await reader.readexactly(4) == b'read'
            writer.write((Path(__file__).resolve().parents[2] / 'AGENTS.md').read_bytes())
            await writer.drain()
            await reader.read()
            writer.close()
            await writer.wait_closed()

        target_server = await asyncio.start_server(target, '127.0.0.1', 0)
        target_port = target_server.sockets[0].getsockname()[1]
        async with serve(channel._connection_loop, '127.0.0.1', 0, process_request=channel._dispatch_http) as upstream:
            upstream_port = upstream.sockets[0].getsockname()[1]
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.setblocking(False)
            public_port = listener.getsockname()[1]
            origin = 'http://127.0.0.1:' + str(public_port)
            app = product_application(channel, broker, public_port=public_port, upstream_port=upstream_port)

            async def configure(request):
                return web.json_response(chat_budget.configure(request, 'workspace-budget', 0, budget))

            async def set_method(request):
                chat_budget.require_maintainer(request)
                body = await request.json()
                return web.json_response(drafts.execute('MAINTAINER', body['action'], body['payload']))

            async def create(request):
                chat_id = (await request.json())['conversation_id']
                channel.require_run_subscription(request, chat_id)
                session = sessions.get_or_create('websocket:' + chat_id)
                sessions.save(session, fsync=True)
                with business.connect() as db:
                    context = _context(db)
                    document = business.get(db, 'ui-check', 'document', 'finance-note')
                    initial = business.get(db, 'ui-check', 'initial', 'snapshot')
                    selection = {'source_id': 'finance-note', 'version': document['version']}
                    binding = {key: context[key] for key in ('namespace', 'owner_id', 'dataset_id', 'dataset_version')}
                    binding.update({'chat_id': chat_id, 'session_id': session.key, 'native_session_created_at': session.created_at.isoformat(),
                                    'binding_id': 'workspace-binding', 'context_version': '1', 'source_refs': [selection],
                                    'source_pins': [{**selection, 'content_sha256': checksum(document)}]})
                    business.put(db, 'ui-check', 'conversation_source_binding', session.key, binding)
                proof = scope.prove(chat_id, ['finance-note'])
                identity = RunIdentity(proof.owner_id, proof.namespace, 'BOSS', frozenset({chat_id}), frozenset({'finance-note'}),
                                       verify=lambda: channel.require_run_subscription(request, chat_id))
                goal = ('查询 region-1 的全部当前产品的毛利率，查询期间' + '至'.join(initial['periods']['CURRENT'])
                        + '，对比期间' + '至'.join(initial['periods']['BASE']) + '，使用当前获准口径')
                body = {'conversation_id': chat_id, 'goal': goal, 'selected_refs': ['finance-note'], 'request_key': str(uuid4()), 'required_outputs': ['TEXT']}
                _, references = catalog.context('BOSS', ['SOP03'])
                body['method_selection'] = {key: references[0][key] for key in ('sop_id', 'version', 'content_sha256')}
                access = HermesBIQueryAuthority(scope)
                binding = access.prepare(request, identity, body)
                result = broker.create(identity, body, request=request, chat_budget=chat_budget)
                with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    access.save_in_transaction(db, result['run_id'], binding)
                active['bi_binding'] = binding
                return web.json_response(result)

            async def open_relay(request):
                run_id = (await request.json())['run_id']
                lease = store.acquire_queued_for_execution(run_id, 0, 'worker', 60)
                epoch = lease['epoch']
                concurrency.configure(run_id, 'worker', epoch, 1)
                tool_budget.configure(run_id, 'worker', epoch, 5)
                store.configure_file_budget(run_id, 'worker', epoch, 5, 1024)
                workspace = tmp_path / run_id
                workspace.mkdir()
                vm_id, boot_id = str(uuid4()), str(uuid4())
                with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    concurrency.reserve_in_transaction(db, run_id, 'worker', epoch, 'slot', 'digest')
                    evidence.record_vm_start_in_transaction(db, bindings, run_id, 'slot', 'digest', 'worker', epoch,
                                                            'boss-1', 'ui-check', vm_id, boot_id, workspace)
                    plan, saved_budget = dispatcher.approved_budget_in_transaction(db, run_id)
                transport_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                transport_listener.bind(('127.0.0.1', 0))
                transport_listener.listen()
                transport_listener.setblocking(False)
                transport_port = transport_listener.getsockname()[1]
                config = EngineRunConfig(run_id, epoch, '903230b1e23e0c496b28e5d2e8c4f2639cd506b6', 'http://127.0.0.1:' + str(transport_port), 1)
                sink = EngineEventSink(store, config, 'worker')
                access = HermesVMRunAccess(bindings, run_id, 'slot', 'worker', epoch, vm_id, boot_id, workspace)
                factory = None
                if ending in {'child_factory', 'child_factory_current'}:
                    root = Path(__file__).resolve().parents[2]
                    runtime_dir = root / ('.work/upgrade2/u2-03/managed-runtime-001' if ending == 'child_factory_current' else '.work/upgrade2/u2-03/dependency-audit-001/environment')
                    engine = root / ('.work/upgrade2/u2-03/managed-hermes-source-001' if ending == 'child_factory_current' else '.work/upgrade2/u2-03/clean-hermes')
                    python = runtime_dir / ('environment/bin/python' if ending == 'child_factory_current' else 'bin/python')
                    deployment = HermesDeploymentConfig(engine,
                        root / '.work/upgrade2/u2-01/hermes.tar.gz', runtime_dir, python,
                        tmp_path, root / 'validation/hermes_process_isolation.sb', transport_port, None, True)
                    factory = HermesExecutionFactory(services, deployment)
                authority = HermesRunAuthority(services, request, sink, checksum(plan), saved_budget, execution_factory=factory)
                authority.bind_vm_access(access)
                active['authority'] = authority
                HermesBIQueryAuthority(scope).bind_epoch(authority)
                capability = secrets.token_urlsafe(32)
                transport = HermesTransport(sink, capability, actor_id='boss-1', space_id='ui-check', scope_service=scope,
                                            tool_budget=tool_budget, bridge=services.bridge, authority=authority)
                transport_app = web.Application()
                transport.install(transport_app)
                transport_runner = web.AppRunner(transport_app)
                await transport_runner.setup()
                await web.SockSite(transport_runner, transport_listener).start()
                active['transport_runner'] = transport_runner
                relay = HermesWorkspaceRelay(HermesVMServerTLS(server_context, client_hash, access), target_port, authority=authority)
                endpoint = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                endpoint.bind(('127.0.0.1', 0))
                endpoint.listen()
                port = endpoint.getsockname()[1]
                await relay.listen(endpoint)
                active['relay'] = relay
                return web.json_response({'port': port, 'transport_port': transport_port, 'capability': capability})

            async def open_process(request):
                run_id = (await request.json())['run_id']
                lease = store.acquire_queued_for_execution(run_id, 0, 'process-worker', 60)
                epoch = lease['epoch']
                concurrency.configure(run_id, 'process-worker', epoch, 1)
                tool_budget.configure(run_id, 'process-worker', epoch, 5)
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                listener.setblocking(False)
                endpoint = 'http://127.0.0.1:' + str(listener.getsockname()[1])
                config = EngineRunConfig(run_id, epoch, '903230b1e23e0c496b28e5d2e8c4f2639cd506b6', endpoint, 2)
                sink = EngineEventSink(store, config, 'process-worker')
                with store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    concurrency.reserve_in_transaction(db, run_id, 'process-worker', epoch, 'process-slot', 'process-digest')
                    plan, saved_budget = dispatcher.approved_budget_in_transaction(db, run_id)
                    ticket = evidence.record_start_in_transaction(db, run_id, 'process-slot', 'process-digest',
                        'process-worker', epoch, 'boss-1', 'ui-check')
                authority = HermesRunAuthority(services, request, sink, checksum(plan), saved_budget)
                capability, provider_capability = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                provider = ProviderGateway(RunBoundBudgetStore(sink, allow_migration=True), provider_capability,
                                           secrets.token_urlsafe(32), offline=True)
                active['process_budget'] = provider.store
                transport = HermesRuntimeTransport(sink, scope, services.bridge, actor_id='boss-1', space_id='ui-check',
                    capability=capability, max_tools=5, provider_gateway=provider, authority=authority)
                lifecycle = HermesExecutionLifecycle(transport, evidence)
                bootstrap = {'endpoint': endpoint, 'capability': capability, 'provider_capability': provider_capability,
                             'run_id': run_id, 'engine_commit': config.engine_commit}
                root = Path(__file__).resolve().parents[2]
                command = [sys.executable, str(root / 'app/tests/hermes_runtime_transport_probe.py'),
                           str(root / '.work/upgrade2/u2-03/clean-hermes'), '503', '--wait-for-cancel']
                task = asyncio.create_task(lifecycle.run(listener, ticket, command, cwd=tmp_path,
                                                         bootstrap=bootstrap, max_seconds=30, interval=0.02))
                active['process_task'] = task
                async def wait_started():
                    while not any(event['type'] == 'RUN_STARTED' for event in store.events(run_id, 0)):
                        if task.done():
                            await task
                            raise ValueError('受管进程未产生启动事件')
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(wait_started(), 20)
                return web.json_response({'run_id': run_id})

            app.router.add_post('/technical/configure', configure)
            app.router.add_post('/technical/method', set_method)
            app.router.add_post('/technical/create', create)
            app.router.add_post('/technical/relay', open_relay)
            app.router.add_post('/technical/process', open_process)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.SockSite(runner, listener).start()
            try:
                async with aiohttp.ClientSession() as client:
                    async with client.get(origin + '/webui/bootstrap', headers={'Authorization': 'Bearer ' + role_secrets['MAINTAINER']}) as response:
                        response.raise_for_status()
                        maintainer = await response.json()
                    async with client.post(origin + '/technical/configure', headers={'Authorization': 'Bearer ' + maintainer['api_token'], 'Origin': origin}) as response:
                        response.raise_for_status()
                    async with client.get(origin + '/webui/bootstrap', headers={'Authorization': 'Bearer ' + role_secrets['BOSS']}) as response:
                        response.raise_for_status()
                        authentication = await response.json()
                    headers = {'Authorization': 'Bearer ' + authentication['api_token'], 'Origin': origin}
                    async with client.ws_connect(authentication['ws_url'], params={'token': authentication['token']}) as websocket:
                        while json.loads((await websocket.receive()).data).get('event') != 'ready':
                            pass
                        await websocket.send_json({'type': 'new_chat'})
                        while True:
                            event = json.loads((await websocket.receive()).data)
                            if event.get('event') == 'attached':
                                chat_id = event['chat_id']
                                break
                        async with client.post(origin + '/technical/create', json={'conversation_id': chat_id}, headers=headers) as response:
                            data = await response.json()
                            assert response.status == 200, data
                            run_id = data['run_id']
                        async with client.post(origin + '/technical/relay', json={'run_id': run_id}, headers=headers) as response:
                            response.raise_for_status()
                            addresses = await response.json()
                            port = addresses['port']
                        if ending.startswith('child_'):
                            payload = {'request_key': 'child-request', 'description': '分析当前经营指标'}
                            async with client.post('http://127.0.0.1:' + str(addresses['transport_port']) + '/internal/v1/children',
                                    json={'protocol_version': 1, **payload}, headers={'Authorization': 'Bearer invalid'}) as response:
                                assert response.status == 401
                            tool_client = HermesTransportClient('http://127.0.0.1:' + str(addresses['transport_port']), addresses['capability'], run_id)
                            if ending == 'child_concurrent':
                                another = HermesTransportClient('http://127.0.0.1:' + str(addresses['transport_port']), addresses['capability'], run_id)
                                results = await asyncio.gather(asyncio.to_thread(tool_client.create_child, **payload),
                                                               asyncio.to_thread(another.create_child, **payload))
                                assert results[0] == results[1]
                                with store.connect() as db:
                                    assert db.execute('SELECT count(*) FROM agent_runs WHERE parent_run_id=?', (run_id,)).fetchone() == (1,)
                                    assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?', (run_id,)).fetchone() == (1,)
                                another.close()
                                tool_client.close()
                                target_server.close()
                                await target_server.wait_closed()
                                return
                            if ending == 'child_updated':
                                async with client.post(origin + '/api/v2/runs/' + run_id + '/inputs',
                                        json={'input': '指标改为销售收入', 'expected_goal_revision': 1, 'request_key': 'child-updated-input', 'required_outputs': ['TEXT']}, headers=headers) as response:
                                    assert response.status == 200, await response.text()
                                    added = await response.json()
                                _, references = catalog.context('BOSS', ['SOP03'])
                                method = {key: references[0][key] for key in ('sop_id', 'version', 'content_sha256')}
                                async with client.post(origin + '/api/v2/runs/' + run_id + '/method-selection',
                                        json={'expected_goal_revision': 2, 'request_key': 'child-updated-method', 'method_selection': method}, headers=headers) as response:
                                    assert response.status == 200, await response.text()
                                await asyncio.to_thread(tool_client.acknowledge_input, added['input_seq'])
                            result = await asyncio.to_thread(tool_client.create_child, **payload)
                            assert result['goal_revision'] == 1
                            assert result['parent_goal_revision'] == (2 if ending == 'child_updated' else 1)
                            child = result['run_id']
                            assert await asyncio.to_thread(tool_client.create_child, **payload) == result
                            with pytest.raises(httpx.HTTPStatusError) as conflict:
                                await asyncio.to_thread(tool_client.create_child, payload['request_key'], '查看其他任务')
                            assert conflict.value.response.status_code == 409
                            if ending in {'child_factory', 'child_factory_current'}:
                                ArtifactWorkspace(tmp_path).create(child)
                            with pytest.raises(httpx.HTTPStatusError) as unavailable:
                                await asyncio.to_thread(tool_client.dispatch_child, child, 'child-dispatch')
                            assert unavailable.value.response.status_code == 503
                            with pytest.raises(httpx.HTTPStatusError) as pending:
                                await asyncio.to_thread(tool_client.child_result, child, 'child-result-check')
                            assert pending.value.response.status_code == 409
                            if ending == 'child_metering':
                                with pytest.raises(httpx.HTTPStatusError) as repeated:
                                    await asyncio.to_thread(tool_client.child_result, child, 'child-result-check')
                                assert repeated.value.response.status_code == 409
                                with store.connect() as db:
                                    assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?', (run_id,)).fetchone() == (2,)
                            if ending in {'child_budget', 'child_metering'}:
                                for index in range(3):
                                    additional = await asyncio.to_thread(tool_client.create_child, 'child-budget-' + str(index), '分析当前经营指标')
                                if ending == 'child_metering':
                                    with pytest.raises(httpx.HTTPStatusError) as changed:
                                        await asyncio.to_thread(tool_client.child_result, additional['run_id'], 'child-result-check')
                                    assert changed.value.response.status_code == 409
                                    with pytest.raises(httpx.HTTPStatusError) as result_exhausted:
                                        await asyncio.to_thread(tool_client.child_result, child, 'child-result-over')
                                    assert result_exhausted.value.response.status_code == 429
                                with pytest.raises(httpx.HTTPStatusError) as exhausted:
                                    await asyncio.to_thread(tool_client.create_child, 'child-budget-over', '分析当前经营指标')
                                assert exhausted.value.response.status_code == 429
                                with store.connect() as db:
                                    assert db.execute('SELECT count(*) FROM agent_runs WHERE parent_run_id=?', (run_id,)).fetchone() == (4,)
                                    assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?', (run_id,)).fetchone() == (5,)
                                tool_client.close()
                                target_server.close()
                                await target_server.wait_closed()
                                return
                            if ending in {'child_factory', 'child_factory_current'}:
                                assert store.read_run(child)['status'] == 'QUEUED'
                                tool_client.close()
                                target_server.close()
                                await target_server.wait_closed()
                                return
                            tool_client.close()
                            child_lease = store.acquire_queued_for_execution(child, 0, 'child-worker', 60)
                            child_config = EngineRunConfig(child, child_lease['epoch'], '903230b1e23e0c496b28e5d2e8c4f2639cd506b6',
                                                           'http://127.0.0.1:' + str(addresses['transport_port']), 1)
                            child_sink = EngineEventSink(store, child_config, 'child-worker')
                            parent_authority = active['authority']
                            child_authority = HermesRunAuthority(services, parent_authority.request, child_sink,
                                                                 parent_authority.plan_digest, parent_authority.budget)
                            child_authority.require()
                            if ending.startswith('child_process_'):
                                query_authority = HermesBIQueryAuthority(scope)
                                query_authority.bind_epoch(child_authority)
                                child_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                child_listener.bind(('127.0.0.1', 0))
                                child_listener.listen()
                                child_listener.setblocking(False)
                                child_port = child_listener.getsockname()[1]
                                child_config = EngineRunConfig(child, child_lease['epoch'], '903230b1e23e0c496b28e5d2e8c4f2639cd506b6',
                                                               'http://127.0.0.1:' + str(child_port), 1)
                                child_sink = EngineEventSink(store, child_config, 'child-worker')
                                child_authority = HermesRunAuthority(services, parent_authority.request, child_sink,
                                                                     parent_authority.plan_digest, parent_authority.budget)
                                capability = secrets.token_urlsafe(32)
                                child_transport = HermesTransport(child_sink, capability, actor_id='boss-1', space_id='ui-check',
                                    scope_service=scope, tool_budget=tool_budget, bridge=services.bridge, authority=child_authority)
                                child_app = web.Application()
                                child_transport.install(child_app)
                                child_runner = web.AppRunner(child_app)
                                await child_runner.setup()
                                await web.SockSite(child_runner, child_listener).start()
                                process = None
                                try:
                                    probe = Path(__file__).with_name('hermes_child_bi_probe.py')
                                    process = await asyncio.create_subprocess_exec(sys.executable, str(probe), stdin=asyncio.subprocess.PIPE,
                                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                                    request = {'endpoint': 'http://127.0.0.1:' + str(child_port), 'capability': capability,
                                               'run_id': child, 'query': active['bi_binding']['binding']['parameters'],
                                               'expected_statuses': [401, 403, 409] if ending == 'child_process_withdrawal' else [409]}
                                    process.stdin.write((json.dumps(request) + '\n').encode())
                                    await process.stdin.drain()
                                    output = await asyncio.wait_for(process.stdout.readline(), 30)
                                    if not output:
                                        raise ValueError((await process.stderr.read()).decode())
                                    result = json.loads(output)
                                    assert result['metric_ids'] == ['gross_margin'] and result['records'] > 0
                                    if ending == 'child_process_goal':
                                        async with client.post(origin + '/api/v2/runs/' + run_id + '/inputs',
                                                json={'input': '指标改为销售收入', 'expected_goal_revision': 1, 'request_key': 'child-process-parent-input'}, headers=headers) as response:
                                            assert response.status == 200, await response.text()
                                    elif ending == 'child_process_method':
                                        _, references = catalog.context('BOSS', ['SOP03'])
                                        method_payload = {'client_request_id': 'child-process-disable', 'sop_id': 'SOP03', 'expected_active_sha256': references[0]['content_sha256']}
                                        maintainer_headers = {'Authorization': 'Bearer ' + maintainer['api_token'], 'Origin': origin}
                                        async with client.post(origin + '/technical/method', json={'action': 'disable', 'payload': method_payload}, headers=maintainer_headers) as response:
                                            assert response.status == 200, await response.text()
                                    else:
                                        business.control('ui-check', 'withdraw', {'source_id': 'finance-note', 'version': '1'})
                                    process.stdin.write(b'\n')
                                    await process.stdin.drain()
                                    denied = json.loads(await asyncio.wait_for(process.stdout.readline(), 30))
                                    assert denied['status'] in request['expected_statuses']
                                    _, errors = await asyncio.wait_for(process.communicate(), 30)
                                    assert process.returncode == 0, errors.decode()
                                    with store.connect() as db:
                                        assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?', (run_id,)).fetchone() == (4,)
                                finally:
                                    if process is not None and process.returncode is None:
                                        process.terminate()
                                        await process.wait()
                                    await child_runner.cleanup()
                                target_server.close()
                                await target_server.wait_closed()
                                return
                            if ending == 'child_updated':
                                query_authority = HermesBIQueryAuthority(scope)
                                query_authority.bind_epoch(child_authority)
                                context = query_authority.context(child_authority)
                                assert json.loads(context.query_bindings[0].parameters_json)['metric_ids'] == ['revenue']
                                target_server.close()
                                await target_server.wait_closed()
                                return
                            with store.connect() as db:
                                db.execute('BEGIN IMMEDIATE')
                                dispatcher._verify_child_authorizations_in_transaction(db, child)
                                root_id = store.require_active_lineage(db, child)
                                assert root_id == run_id
                                _, child_budget = dispatcher.approved_budget_in_transaction(db, child)
                                assert child_budget == budget
                                assert db.execute('SELECT count(*) FROM agent_chat_run_budgets WHERE run_id=?', (child,)).fetchone() == (0,)
                                assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?', (run_id,)).fetchone() == (1,)
                            if ending == 'child_revision':
                                async with client.post(origin + '/api/v2/runs/' + run_id + '/inputs',
                                        json={'input': '指标改为销售收入', 'expected_goal_revision': 1, 'request_key': 'child-parent-input'}, headers=headers) as response:
                                    assert response.status == 200, await response.text()
                            elif ending == 'child_input':
                                async with client.post(origin + '/api/v2/runs/' + child + '/inputs',
                                        json={'input': '指标改为销售收入', 'expected_goal_revision': 1, 'request_key': 'child-own-input'}, headers=headers) as response:
                                    assert response.status == 200, await response.text()
                            elif ending == 'child_method':
                                _, references = catalog.context('BOSS', ['SOP03'])
                                method_payload = {'client_request_id': 'child-disable-method', 'sop_id': 'SOP03', 'expected_active_sha256': references[0]['content_sha256']}
                                maintainer_headers = {'Authorization': 'Bearer ' + maintainer['api_token'], 'Origin': origin}
                                async with client.post(origin + '/technical/method', json={'action': 'disable', 'payload': method_payload}, headers=maintainer_headers) as response:
                                    assert response.status == 200, await response.text()
                            elif ending == 'child_withdrawal':
                                business.control('ui-check', 'withdraw', {'source_id': 'finance-note', 'version': '1'})
                            else:
                                await websocket.send_json({'type': 'webui_request', 'action': 'boss.auth.logout', 'request_id': 'child-logout', 'payload': {}})
                                while True:
                                    event = json.loads((await websocket.receive()).data)
                                    if event.get('request_id') == 'child-logout':
                                        assert event.get('ok') is True
                                        break
                            with pytest.raises((ValueError, web.HTTPException)):
                                child_authority.require()
                            if ending in {'child_revision', 'child_input', 'child_method'}:
                                stale_client = HermesTransportClient('http://127.0.0.1:' + str(addresses['transport_port']), addresses['capability'], run_id)
                                with pytest.raises(httpx.HTTPStatusError) as stale:
                                    await asyncio.to_thread(stale_client.child_result, child)
                                assert stale.value.response.status_code == 409
                                stale_client.close()
                            assert child_lease['epoch'] > 0
                            target_server.close()
                            await target_server.wait_closed()
                            return
                        tool_url = 'http://127.0.0.1:' + str(addresses['transport_port']) + '/internal/v1/tools/'
                        tool_headers = {'Authorization': 'Bearer ' + addresses['capability']}
                        root = Path(__file__).resolve().parents[2]
                        probe = root / 'app/tests/hermes_runtime_transport_probe.py'
                        engine = root / '.work/upgrade2/u2-03/clean-hermes'
                        process = await asyncio.create_subprocess_exec(sys.executable, str(probe), str(engine), '--bi-reselect' if ending == 'revision' else '--observe-revocation',
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                        bootstrap = {'endpoint': 'http://127.0.0.1:' + str(addresses['transport_port']),
                                     'capability': addresses['capability'], 'run_id': run_id,
                                     'engine_commit': '903230b1e23e0c496b28e5d2e8c4f2639cd506b6'}
                        process.stdin.write((json.dumps(bootstrap) + '\n').encode())
                        await process.stdin.drain()
                        output = await asyncio.wait_for(process.stdout.readline(), 20)
                        process_result = json.loads(output)
                        assert process_result['request']['run_id'] == run_id
                        assert process_result['event'] == process_result['repeated']
                        if ending == 'revision':
                            original = active['bi_binding']['binding']['parameters']
                            process.stdin.write((json.dumps(original) + '\n').encode())
                            await process.stdin.drain()
                            first = json.loads(await asyncio.wait_for(process.stdout.readline(), 20))['query']
                            async with client.post(origin + '/api/v2/runs/' + run_id + '/inputs',
                                    json={'input': '指标改为销售收入', 'expected_goal_revision': 1, 'request_key': 'bi-revision-input'}, headers=headers) as response:
                                assert response.status == 200, await response.text()
                                added = await response.json()
                            _, references = catalog.context('BOSS', ['SOP03'])
                            method = {key: references[0][key] for key in ('sop_id', 'version', 'content_sha256')}
                            maintainer_headers = {'Authorization': 'Bearer ' + maintainer['api_token'], 'Origin': origin}
                            async with client.post(origin + '/api/v2/runs/' + run_id + '/method-selection',
                                    json={'expected_goal_revision': 2, 'request_key': 'maintainer-reselection', 'method_selection': method}, headers=maintainer_headers) as response:
                                assert response.status == 403, await response.text()
                            async with client.post(origin + '/api/v2/runs/' + run_id + '/method-selection',
                                    json={'expected_goal_revision': 2, 'request_key': 'bi-revision-selection', 'method_selection': method}, headers=headers) as response:
                                assert response.status == 200, await response.text()
                            with store.connect() as db:
                                saved = db.execute("SELECT body FROM objects WHERE namespace='ui-check' AND kind='hermes_bi_query_authorization' AND id=?", (run_id + ':2',)).fetchone()
                            updated = json.loads(saved[0])['binding']['parameters']
                            process.stdin.write((json.dumps({'input_seq': added['input_seq'], 'query': updated}) + '\n').encode())
                            await process.stdin.drain()
                            line = await asyncio.wait_for(process.stdout.readline(), 20)
                            if not line:
                                raise ValueError((await process.stderr.read()).decode())
                            result = json.loads(line)
                            assert result['old_evidence_status'] == result['old_query_status'] == 403
                            assert result['evidence_verified'] is True
                            assert result['query']['query_id'] != first['query_id']
                            assert result['query']['context_snapshot']['metric_ids'] == ['revenue']
                            method_payload = {'client_request_id': 'bi-disable-method', 'sop_id': 'SOP03', 'expected_active_sha256': method['content_sha256']}
                            async with client.post(origin + '/technical/method', json={'action': 'disable', 'payload': method_payload}, headers=maintainer_headers) as response:
                                assert response.status == 200, await response.text()
                            process.stdin.write(b'method-disabled\n')
                            await process.stdin.drain()
                            denied_method = json.loads(await asyncio.wait_for(process.stdout.readline(), 20))
                            assert denied_method['disabled_status'] == 409
                            method_payload['client_request_id'] = 'bi-enable-method'
                            async with client.post(origin + '/technical/method', json={'action': 'enable', 'payload': method_payload}, headers=maintainer_headers) as response:
                                assert response.status == 200, await response.text()
                            business.control('ui-check', 'withdraw', {'source_id': 'finance-note', 'version': '1'})
                            process.stdin.write(b'\n')
                            await process.stdin.drain()
                            denied = json.loads(await asyncio.wait_for(process.stdout.readline(), 20))
                            assert denied['withdrawn_status'] in (401, 403, 409)
                            output, errors = await asyncio.wait_for(process.communicate(), 20)
                            assert process.returncode == 0, errors.decode()
                            with store.connect() as db:
                                assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE root_run_id=?', (run_id,)).fetchone() == (4,)
                            target_server.close()
                            await target_server.wait_closed()
                            return
                        async with client.post(origin + '/technical/create', json={'conversation_id': chat_id}, headers=headers) as response:
                            assert response.status == 200, await response.text()
                            process_run = (await response.json())['run_id']
                        async with client.post(origin + '/technical/process', json={'run_id': process_run}, headers=headers) as response:
                            assert response.status == 200, await response.text()
                        if ending == 'cancel':
                            revision = store.read_run(process_run)['revision']
                            async with client.post(origin + '/api/v2/runs/' + process_run + '/cancel',
                                    json={'expected_revision': revision, 'request_key': 'managed-process-cancel'}, headers=headers) as response:
                                assert response.status == 200, await response.text()
                            assert await asyncio.wait_for(active['process_task'], 20) == 'RECONCILING'
                            assert evidence.read(process_run, 'process-slot')['exit_scope'] == 'LEADER_ONLY'
                            usage = [event for event in store.events(process_run, 0) if event['type'] == 'USAGE_RECORDED']
                            assert len(usage) == 1 and usage[0]['payload']['usage_state'] == 'EMPTY'
                            assert usage[0]['payload']['requests_used'] == 0
                            with pytest.raises((ValueError, web.HTTPException)):
                                active['process_budget'].reserve()
                            with store.connect() as db:
                                assert db.execute('SELECT count(*) FROM hermes_model_requests WHERE root_run_id=?', (process_run,)).fetchone() == (0,)
                        args = {'path': 'note.txt', 'content': '工作区内容'}
                        argument_digest = hashlib.sha256(json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                        reservation = {'protocol_version': 1, 'call_id': 'file-check-1', 'tool_name': 'workspace_write_file', 'arguments_sha256': argument_digest}
                        async with client.post(tool_url + 'workspace-file-reserve', json={**reservation, 'tool_name': []}, headers=tool_headers) as response:
                            assert response.status == 400
                        tool_client = HermesTransportClient('http://127.0.0.1:' + str(addresses['transport_port']), addresses['capability'], run_id)
                        definitions = await asyncio.to_thread(tool_client.bi_definitions)
                        assert {item['name'] for item in definitions} == {'query_metrics', 'read_evidence'}
                        parameters = active['bi_binding']['binding']['parameters']
                        invalid = {**parameters, 'question': parameters['question'] + ' 变化'}
                        denied = {'protocol_version': 1, 'call_id': 'bi-denied', 'tool_name': 'query_metrics', 'arguments': invalid}
                        async with client.post(tool_url + 'bi', json=denied, headers=tool_headers) as response:
                            assert response.status == 403, await response.text()
                        def dispatch_bi():
                            from hermes_tool_registration import registered_bi_tools
                            from tools.registry import registry
                            with registered_bi_tools(tool_client, tool_client.bi_definitions()):
                                query_result = json.loads(registry.dispatch('query_metrics', parameters))
                                args = {'query_id': query_result['query_id'], 'source_ids': [item['source_id'] for item in query_result['sources']], 'detail_refs': query_result['detail_refs']}
                                return query_result, args, json.loads(registry.dispatch('read_evidence', args))
                        query, evidence_args, evidence_result = await asyncio.to_thread(dispatch_bi)
                        assert query['sources'] and query['sources'][0]['source_id'] == 'finance-note'
                        assert evidence_result['original_records'] and evidence_result['sources'][0]['version'] == query['sources'][0]['version']
                        other_session = sessions.get_or_create('websocket:' + str(uuid4()))
                        sessions.save(other_session, fsync=True)
                        trusted = active['bi_binding']
                        other_envelope = {'owner_id': trusted['owner_id'], 'execution_namespace': trusted['namespace'],
                                          'dataset_id': trusted['dataset_id'], 'dataset_version': trusted['dataset_version'],
                                          'request_id': str(uuid4()), 'session_id': other_session.key}
                        foreign = business.invoke('query_metrics', {**parameters, 'envelope': other_envelope})
                        foreign_args = {'query_id': foreign['query_id'], 'source_ids': [item['source_id'] for item in foreign['sources']], 'detail_refs': foreign['detail_refs']}
                        async with client.post(tool_url + 'bi', json={'protocol_version': 1, 'call_id': 'bi-foreign', 'tool_name': 'read_evidence', 'arguments': foreign_args}, headers=tool_headers) as response:
                            assert response.status == 403, await response.text()
                        with business.connect() as db:
                            query_count = db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='query'").fetchone()
                        repeated_query = await asyncio.to_thread(tool_client.call_bi_tool, 'query_metrics', parameters, 'bi-query')
                        assert repeated_query['query_id'] == query['query_id']
                        with business.connect() as db:
                            assert db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='query'").fetchone() == query_count
                        async with client.post(tool_url + 'bi', json={'protocol_version': 1, 'call_id': 'bi-query', 'tool_name': 'query_metrics', 'arguments': parameters}, headers=tool_headers) as response:
                            assert response.status == 409, await response.text()
                        await asyncio.to_thread(tool_client.reserve_workspace_file_tool, 'workspace_write_file', 'file-check-1', argument_digest)
                        async with client.post(tool_url + 'workspace-file-reserve', json=reservation, headers=tool_headers) as response:
                            assert response.status == 409
                        receipt = {'protocol_version': 1, 'call_id': 'file-check-1', 'tool_name': 'workspace_write_file', 'outcome': 'RETURNED'}
                        async with client.post(tool_url + 'workspace-file-finish', json={**receipt, 'outcome': []}, headers=tool_headers) as response:
                            assert response.status == 400
                        await asyncio.to_thread(tool_client.finish_workspace_file_tool, 'workspace_write_file', 'file-check-1', 'RETURNED')
                        async with client.post(tool_url + 'workspace-file-finish', json=receipt, headers=tool_headers) as response:
                            assert response.status == 409
                        inflight = {**reservation, 'call_id': 'file-check-2'}
                        async with client.post(tool_url + 'workspace-file-reserve', json=inflight, headers=tool_headers) as response:
                            assert response.status == 200, await response.text()
                        with business.connect() as db:
                            before = db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='query'").fetchone()
                        async with client.post(tool_url + 'bi', json={'protocol_version': 1, 'call_id': 'bi-over-budget', 'tool_name': 'query_metrics', 'arguments': parameters}, headers=tool_headers) as response:
                            assert response.status == 429, await response.text()
                        with business.connect() as db:
                            assert db.execute("SELECT count(*) FROM objects WHERE namespace='ui-check' AND kind='query'").fetchone() == before
                        reader, writer = await asyncio.open_connection('127.0.0.1', port, ssl=client_context, server_hostname='localhost')
                        writer.write(b'read')
                        await writer.drain()
                        payload = (Path(__file__).resolve().parents[2] / 'AGENTS.md').read_bytes()
                        assert await asyncio.wait_for(reader.readexactly(len(payload)), 10) == payload
                        if ending == 'withdrawal':
                            business.control('ui-check', 'withdraw', {'source_id': 'finance-note', 'version': '1'})
                        elif ending == 'logout':
                            await websocket.send_json({'type': 'webui_request', 'action': 'boss.auth.logout',
                                                       'request_id': 'workspace-logout', 'payload': {}})
                            while True:
                                event = json.loads((await websocket.receive()).data)
                                if event.get('request_id') == 'workspace-logout':
                                    assert event.get('ok') is True
                                    break
                        else:
                            revision = store.read_run(run_id)['revision']
                            async with client.post(origin + '/api/v2/runs/' + run_id + '/cancel',
                                    json={'expected_revision': revision, 'request_key': 'workspace-cancel'}, headers=headers) as response:
                                assert response.status == 200, await response.text()
                        if ending in ('withdrawal', 'logout'):
                            with pytest.raises((ValueError, web.HTTPException)):
                                await asyncio.wait_for(active['process_task'], 20)
                            assert evidence.read(process_run, 'process-slot')['exit_scope'] == 'LEADER_ONLY'
                        assert await asyncio.wait_for(reader.read(), 10) == b''
                        with pytest.raises((ValueError, web.HTTPException)):
                            await active['relay'].watcher
                        late_receipt = {**receipt, 'call_id': 'file-check-2'}
                        async with client.post(tool_url + 'workspace-file-finish', json=late_receipt, headers=tool_headers) as response:
                            assert response.status in {401, 403, 409}, await response.text()
                        reservation['call_id'] = 'file-check-3'
                        async with client.post(tool_url + 'workspace-file-reserve', json=reservation, headers=tool_headers) as response:
                            assert response.status in {401, 403, 409}, await response.text()
                        async with client.post(tool_url + 'bi', json={'protocol_version': 1, 'call_id': 'bi-late', 'tool_name': 'read_evidence', 'arguments': evidence_args}, headers=tool_headers) as response:
                            assert response.status in {401, 403, 409}, await response.text()
                        process.stdin.write(b'\n')
                        await process.stdin.drain()
                        output, errors = await asyncio.wait_for(process.communicate(), 20)
                        assert process.returncode == 0, errors.decode()
                        revoked_status = json.loads(output)['revoked_status']
                        assert revoked_status in (401, 403, 409)
                        with store.connect() as db:
                            assert db.execute('SELECT count(*) FROM agent_tool_reservations WHERE run_id=?', (run_id,)).fetchone() == (5,)
                            assert db.execute("SELECT count(*) FROM agent_run_events WHERE run_id=? AND type='TOOL_FINISHED'", (run_id,)).fetchone() == (4,)
                        tool_client.close()
                        writer.close()
                        await writer.wait_closed()
            finally:
                if 'relay' in active and not active['relay'].closed:
                    await active['relay'].close()
                if 'transport_runner' in active:
                    await active['transport_runner'].cleanup()
                await runner.cleanup()
        target_server.close()
        await target_server.wait_closed()

    asyncio.run(check())
