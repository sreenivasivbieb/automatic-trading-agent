# Generated backend source reference

Generated from the active source. Regenerate with `.venv/bin/python -m scripts.generate_code_reference`; verify with `--check`.

This tool reads source only. It does not load environment files, databases, AWS credentials, models or providers. [Development](DEVELOPMENT.md) explains the module layout; this index supplies exact code locations.

## Local HTTP routes

Use the local session/CSRF client or configured bearer authentication. Health/readiness/session/schema routes have their documented local exceptions. `/api/*` is separate from cloud `/platform/*`.

- `GET /api/aegis/state` → [aegis_state](../backend/api.py#L397)
- `GET /api/aegis/market-details` → [aegis_market_details](../backend/api.py#L408)
- `GET /api/aegis/vault` → [aegis_vault](../backend/api.py#L414)
- `POST /api/aegis/vault/prepare` → [aegis_owner_prepare](../backend/api.py#L420)
- `POST /api/aegis/vault/receipt` → [aegis_owner_receipt](../backend/api.py#L433)
- `POST /api/aegis/verify` → [aegis_verify](../backend/api.py#L439)
- `POST /api/aegis/check` → [aegis_check](../backend/api.py#L459)
- `PUT /api/aegis/settings` → [aegis_settings](../backend/api.py#L463)
- `POST /api/aegis/settings/confirm` → [aegis_settings_confirm](../backend/api.py#L470)
- `POST /api/aegis/settings/rollback` → [aegis_settings_rollback](../backend/api.py#L480)
- `GET /api/selection` → [selection_config](../backend/api.py#L486)
- `PUT /api/selection` → [update_selection](../backend/api.py#L491)
- `POST /api/aegis/control` → [aegis_control](../backend/api.py#L499)
- `POST /api/aegis/chat` → [aegis_chat](../backend/api.py#L508)
- `POST /api/session` → [session](../backend/api.py#L512)
- `GET /api/health` → [health](../backend/api.py#L551)
- `GET /api/ready` → [ready](../backend/api.py#L555)
- `GET /api/status` → [status](../backend/api.py#L593)
- `GET /api/dashboard` → [dashboard](../backend/api.py#L633)
- `GET /api/markets` → [markets](../backend/api.py#L656)
- `GET /api/correlations` → [correlation_data](../backend/api.py#L660)
- `GET /api/markets/{symbol}` → [market](../backend/api.py#L665)
- `GET /api/desk/budget/{symbol}` → [desk_budget](../backend/api.py#L680)
- `GET /api/alerts` → [alerts](../backend/api.py#L685)
- `POST /api/alerts` → [create_alert](../backend/api.py#L689)
- `DELETE /api/alerts/{alert_id}` → [delete_alert](../backend/api.py#L694)
- `GET /api/news` → [news](../backend/api.py#L698)
- `POST /api/news/refresh` → [refresh_news](../backend/api.py#L719)
- `GET /api/news/{article_id}` → [article](../backend/api.py#L723)
- `GET /api/strategies` → [strategies](../backend/api.py#L744)
- `PUT /api/strategies/{strategy_id}` → [strategy_config](../backend/api.py#L761)
- `POST /api/runs` → [run](../backend/api.py#L768)
- `GET /api/runs/{run_id}` → [run_detail](../backend/api.py#L772)
- `GET /api/runs/{run_id}/brief` → [run_brief](../backend/api.py#L779)
- `GET /api/risk` → [risk](../backend/api.py#L786)
- `PUT /api/risk` → [risk_config](../backend/api.py#L796)
- `GET /api/portfolio` → [portfolio](../backend/api.py#L803)
- `POST /api/positions/{symbol}/exit-preview` → [exit_preview](../backend/api.py#L808)
- `GET /api/history/{kind}` → [history](../backend/api.py#L852)
- `GET /api/trades` → [trades](../backend/api.py#L861)
- `GET /api/trades/{workspace}/{trade_id}` → [trade_detail](../backend/api.py#L871)
- `POST /api/execution/preview` → [preview](../backend/api.py#L879)
- `POST /api/execution/authorize` → [authorize](../backend/api.py#L887)
- `POST /api/execution/{intent_id}/reconcile` → [reconcile](../backend/api.py#L891)
- `POST /api/agent/control` → [control](../backend/api.py#L895)
- `POST /api/emergency-stop` → [emergency_stop](../backend/api.py#L899)
- `POST /api/backtests` → [backtests](../backend/api.py#L906)
- `PUT /api/settings/providers` → [provider_settings](../backend/api.py#L942)
- `GET /api/settings/news-scoring` → [news_scoring](../backend/api.py#L958)
- `GET /api/settings/provider-refresh` → [provider_refresh](../backend/api.py#L967)
- `PUT /api/settings/provider-refresh` → [change_provider_refresh](../backend/api.py#L972)
- `PUT /api/settings/news-scoring` → [change_news_scoring](../backend/api.py#L980)
- `GET /api/wallet/{address}` → [wallet](../backend/api.py#L987)
- `POST /api/chat` → [chat](../backend/api.py#L996)
- `GET /{path:path}` → [frontend](../backend/api.py#L1210)

## Cloud HTTP routes

Cognito access-token identity and tenant-aware repositories protect application resources. Authentication endpoints establish or clear sessions; `/platform/health` is public and does not attest AWS account availability.

- `GET /platform/health` → [server.ts:249](../backend/src/server.ts#L249)
- `GET /platform/ready` → [server.ts:258](../backend/src/server.ts#L258)
- `GET /platform/emergency` → [server.ts:262](../backend/src/server.ts#L262)
- `POST /platform/emergency-stop` → [server.ts:270](../backend/src/server.ts#L270)
- `POST /platform/emergency-clear` → [server.ts:273](../backend/src/server.ts#L273)
- `GET /platform/profile` → [server.ts:313](../backend/src/server.ts#L313)
- `POST /platform/profile/preview` → [server.ts:315](../backend/src/server.ts#L315)
- `GET /platform/agents` → [server.ts:332](../backend/src/server.ts#L332)
- `GET /platform/portfolio` → [server.ts:336](../backend/src/server.ts#L336)
- `POST /platform/agents` → [server.ts:337](../backend/src/server.ts#L337)
- `GET /platform/agent-templates` → [server.ts:338](../backend/src/server.ts#L338)
- `POST /platform/agent-templates/:id/instantiate` → [server.ts:341](../backend/src/server.ts#L341)
- `GET /platform/agents/:id` → [server.ts:349](../backend/src/server.ts#L349)
- `GET /platform/agents/:id/preview` → [server.ts:352](../backend/src/server.ts#L352)
- `POST /platform/agents/:id/deploy` → [server.ts:355](../backend/src/server.ts#L355)
- `POST /platform/agents/:id/configuration/preview` → [server.ts:358](../backend/src/server.ts#L358)
- `POST /platform/agents/:id/rollback/preview` → [server.ts:380](../backend/src/server.ts#L380)
- `POST /platform/agents/:id/control` → [server.ts:402](../backend/src/server.ts#L402)
- `GET /platform/agents/:id/events` → [server.ts:426](../backend/src/server.ts#L426)
- `GET /platform/agents/:id/logs` → [server.ts:431](../backend/src/server.ts#L431)
- `GET /platform/agents/:id/metrics` → [server.ts:436](../backend/src/server.ts#L436)
- `GET /platform/agents/:id/versions` → [server.ts:445](../backend/src/server.ts#L445)
- `POST /platform/conversations` → [server.ts:451](../backend/src/server.ts#L451)
- `GET /platform/conversations` → [server.ts:454](../backend/src/server.ts#L454)
- `GET /platform/conversations/:id/messages` → [server.ts:458](../backend/src/server.ts#L458)
- `POST /platform/conversations/:id/messages` → [server.ts:464](../backend/src/server.ts#L464)
- `GET /platform/conversations/:id/requests/:requestId` → [server.ts:473](../backend/src/server.ts#L473)
- `POST /platform/actions/:id/approve` → [server.ts:483](../backend/src/server.ts#L483)
- `GET /platform/history/:kind` → [server.ts:493](../backend/src/server.ts#L493)
- `GET /platform/strategies` → [server.ts:508](../backend/src/server.ts#L508)
- `POST /platform/auth/register` → [cognito.ts:112](../backend/src/auth/cognito.ts#L112)
- `POST /platform/auth/verify` → [cognito.ts:133](../backend/src/auth/cognito.ts#L133)
- `POST /platform/auth/login` → [cognito.ts:144](../backend/src/auth/cognito.ts#L144)
- `POST /platform/auth/refresh` → [cognito.ts:158](../backend/src/auth/cognito.ts#L158)
- `POST /platform/auth/forgot` → [cognito.ts:171](../backend/src/auth/cognito.ts#L171)
- `POST /platform/auth/reset` → [cognito.ts:183](../backend/src/auth/cognito.ts#L183)
- `POST /platform/auth/logout` → [cognito.ts:195](../backend/src/auth/cognito.ts#L195)
- `GET /platform/auth/session` → [cognito.ts:219](../backend/src/auth/cognito.ts#L219)

## Python classes and functions

### backend/aegis_bridge.py

- [strategy_catalog](../backend/aegis_bridge.py#L18) — `strategy_catalog(store)`
- [collect_library](../backend/aegis_bridge.py#L39) — `async collect_library(engine, state: dict)`

### backend/analytics.py

- [ChartPoint](../backend/analytics.py#L11) — class
- [ChartIndicators](../backend/analytics.py#L21) — class
- [chart_indicators](../backend/analytics.py#L30) — `chart_indicators(market: Market)`
- [aggregate](../backend/analytics.py#L78) — `aggregate(market: Market, timeframe: str)`
- [correlations](../backend/analytics.py#L117) — `correlations(markets: dict[str, Market])`

### backend/api.py

- [PreviewRequest](../backend/api.py#L70) — class
- [ProviderSettings](../backend/api.py#L74) — class
- [RefreshSettings](../backend/api.py#L80) — class
- [AegisControl](../backend/api.py#L85) — class
- [AegisSettings](../backend/api.py#L93) — class
- [AegisSettingsConfirm](../backend/api.py#L98) — class
- [AegisRollback](../backend/api.py#L105) — class
- [VersionedSelection](../backend/api.py#L110) — class
- [diff](../backend/api.py#L115) — `diff(before: dict, after: dict)`
- [OwnerRequest](../backend/api.py#L121) — class
- [OwnerReceipt](../backend/api.py#L129) — class
- [DecisionProof](../backend/api.py#L135) — class
- [create_app](../backend/api.py#L141) — `create_app(db_path=None, *, testing=False, transport=None, api_token=None, aegis_factory=None)`
- [create_app.lifespan](../backend/api.py#L156) — `async lifespan(app)`
- [create_app.lifespan.reference_source](../backend/api.py#L207) — `async reference_source(state)`
- [create_app.lifespan.terminal_tool](../backend/api.py#L210) — `async terminal_tool(name: str, args: dict)`
- [create_app.error](../backend/api.py#L263) — `error(request, code, message, status=400, details=None)`
- [create_app.origin_allowed](../backend/api.py#L276) — `origin_allowed(request)`
- [create_app.authorize_api](../backend/api.py#L284) — `async authorize_api(request: Request)`
- [create_app.boundary](../backend/api.py#L300) — `async boundary(request: Request, call_next)`
- [create_app.value_error](../backend/api.py#L377) — `async value_error(request, exc)`
- [create_app.validation_error](../backend/api.py#L381) — `async validation_error(request, exc)`
- [create_app.engine](../backend/api.py#L393) — `engine(request: Request)`
- [create_app.aegis_state](../backend/api.py#L397) — `async aegis_state(request: Request)`
- [create_app.aegis_market_details](../backend/api.py#L408) — `async aegis_market_details(request: Request, asset: Literal['WHSK', 'WETH', 'WBTC']='WHSK')`
- [create_app.aegis_vault](../backend/api.py#L414) — `async aegis_vault(network: Literal['testnet', 'mainnet']='testnet')`
- [create_app.aegis_owner_prepare](../backend/api.py#L420) — `async aegis_owner_prepare(body: OwnerRequest)`
- [create_app.aegis_owner_receipt](../backend/api.py#L433) — `async aegis_owner_receipt(body: OwnerReceipt)`
- [create_app.aegis_verify](../backend/api.py#L439) — `async aegis_verify(body: DecisionProof)`
- [create_app.aegis_verify.verify](../backend/api.py#L444) — `verify()`
- [create_app.aegis_check](../backend/api.py#L459) — `async aegis_check(request: Request)`
- [create_app.aegis_settings](../backend/api.py#L463) — `async aegis_settings(body: AegisSettings, request: Request)`
- [create_app.aegis_settings_confirm](../backend/api.py#L470) — `async aegis_settings_confirm(body: AegisSettingsConfirm, request: Request)`
- [create_app.aegis_settings_rollback](../backend/api.py#L480) — `async aegis_settings_rollback(body: AegisRollback, request: Request)`
- [create_app.selection_config](../backend/api.py#L486) — `async selection_config(e: Engine=Depends(engine))`
- [create_app.update_selection](../backend/api.py#L491) — `async update_selection(body: VersionedSelection, e: Engine=Depends(engine))`
- [create_app.aegis_control](../backend/api.py#L499) — `async aegis_control(body: AegisControl, request: Request)`
- [create_app.aegis_chat](../backend/api.py#L508) — `async aegis_chat(body: ChatRequest, request: Request)`
- [create_app.session](../backend/api.py#L512) — `async session(request: Request)`
- [create_app.health](../backend/api.py#L551) — `async health()`
- [create_app.ready](../backend/api.py#L555) — `async ready(e: Engine=Depends(engine))`
- [create_app.market_summary](../backend/api.py#L564) — `market_summary(market)`
- [create_app.status](../backend/api.py#L593) — `async status(request: Request, e: Engine=Depends(engine))`
- [create_app.dashboard](../backend/api.py#L633) — `async dashboard(e: Engine=Depends(engine))`
- [create_app.markets](../backend/api.py#L656) — `async markets(e: Engine=Depends(engine))`
- [create_app.correlation_data](../backend/api.py#L660) — `async correlation_data(e: Engine=Depends(engine))`
- [create_app.market](../backend/api.py#L665) — `async market(symbol: Literal['BTC', 'ETH', 'SOL'], timeframe: Literal['1h', '4h', '1d']='1h', e: Engine=Depends(engine))`
- [create_app.desk_budget](../backend/api.py#L680) — `async desk_budget(symbol: Literal['BTC', 'ETH', 'SOL'], e: Engine=Depends(engine))`
- [create_app.alerts](../backend/api.py#L685) — `async alerts(e: Engine=Depends(engine))`
- [create_app.create_alert](../backend/api.py#L689) — `async create_alert(body: AlertRequest, e: Engine=Depends(engine))`
- [create_app.delete_alert](../backend/api.py#L694) — `async delete_alert(alert_id: str, e: Engine=Depends(engine))`
- [create_app.news](../backend/api.py#L698) — `async news(breaking: bool=False, q: str=Query(default='', max_length=200), asset: str=Query(default='', max_length=20), e: Engine=Depends(engine))`
- [create_app.refresh_news](../backend/api.py#L719) — `async refresh_news(breaking: bool=False, e: Engine=Depends(engine))`
- [create_app.article](../backend/api.py#L723) — `async article(article_id: str, e: Engine=Depends(engine))`
- [create_app.strategies](../backend/api.py#L744) — `async strategies(e: Engine=Depends(engine))`
- [create_app.save_strategy](../backend/api.py#L747) — `save_strategy(e: Engine, strategy_id: str, config: StrategyConfig, expected_version: int)`
- [create_app.strategy_config](../backend/api.py#L761) — `async strategy_config(strategy_id: str, body: VersionedStrategy, e: Engine=Depends(engine))`
- [create_app.run](../backend/api.py#L768) — `async run(body: RunRequest, e: Engine=Depends(engine))`
- [create_app.run_detail](../backend/api.py#L772) — `async run_detail(run_id: str, e: Engine=Depends(engine))`
- [create_app.run_brief](../backend/api.py#L779) — `async run_brief(run_id: str, e: Engine=Depends(engine))`
- [create_app.risk](../backend/api.py#L786) — `async risk(e: Engine=Depends(engine))`
- [create_app.risk_config](../backend/api.py#L796) — `async risk_config(body: VersionedRisk, e: Engine=Depends(engine))`
- [create_app.portfolio](../backend/api.py#L803) — `async portfolio(e: Engine=Depends(engine))`
- [create_app.exit_preview](../backend/api.py#L808) — `async exit_preview(symbol: Literal['BTC', 'ETH', 'SOL'], e: Engine=Depends(engine))`
- [create_app.history](../backend/api.py#L852) — `async history(kind: Literal['runs', 'risks', 'intents', 'ledger', 'audit', 'snapshots'], limit: int=Query(default=50, ge=1, le=200), offset: int=Query(default=0, ge=0), e: E...`
- [create_app.trades](../backend/api.py#L861) — `async trades(request: Request, workspace: Literal['research', 'aegis']='research', filters: TradeFilters=Depends())`
- [create_app.trade_detail](../backend/api.py#L871) — `async trade_detail(workspace: Literal['research', 'aegis'], trade_id: str, request: Request)`
- [create_app.preview](../backend/api.py#L879) — `async preview(body: PreviewRequest, e: Engine=Depends(engine))`
- [create_app.authorize](../backend/api.py#L887) — `async authorize(body: Authorize, e: Engine=Depends(engine))`
- [create_app.reconcile](../backend/api.py#L891) — `async reconcile(intent_id: str, e: Engine=Depends(engine))`
- [create_app.control](../backend/api.py#L895) — `async control(body: SchedulerAction, e: Engine=Depends(engine))`
- [create_app.emergency_stop](../backend/api.py#L899) — `async emergency_stop(request: Request, e: Engine=Depends(engine))`
- [create_app.backtests](../backend/api.py#L906) — `async backtests(body: BacktestRequest, e: Engine=Depends(engine))`
- [create_app.provider_settings](../backend/api.py#L942) — `async provider_settings(body: ProviderSettings, e: Engine=Depends(engine))`
- [create_app.news_scoring](../backend/api.py#L958) — `async news_scoring(e: Engine=Depends(engine))`
- [create_app.provider_refresh](../backend/api.py#L967) — `async provider_refresh(e: Engine=Depends(engine))`
- [create_app.change_provider_refresh](../backend/api.py#L972) — `async change_provider_refresh(body: RefreshSettings, e: Engine=Depends(engine))`
- [create_app.change_news_scoring](../backend/api.py#L980) — `async change_news_scoring(body: VersionedNewsScoring, e: Engine=Depends(engine))`
- [create_app.wallet](../backend/api.py#L987) — `async wallet(address: str, request: Request)`
- [create_app.chat](../backend/api.py#L996) — `async chat(body: ChatRequest, e: Engine=Depends(engine))`
- [create_app.frontend](../backend/api.py#L1210) — `async frontend(path: str)`

### backend/backtesting.py

- [backtest](../backend/backtesting.py#L11) — `backtest(market: Market, news: NewsFeed, request: BacktestRequest, strategy_config, risk: RiskConfig)`
- [backtest.segment](../backend/backtesting.py#L19) — `segment(start, end)`

### backend/cloud_worker.py

- [control_scalars](../backend/cloud_worker.py#L30) — `control_scalars(value)`
- [risk_adapter](../backend/cloud_worker.py#L43) — `risk_adapter(r)`
- [CloudWorker](../backend/cloud_worker.py#L60) — class
- [CloudWorker.__init__](../backend/cloud_worker.py#L61) — `__init__(self)`
- [CloudWorker.control](../backend/cloud_worker.py#L89) — `control(self)`
- [CloudWorker.event](../backend/cloud_worker.py#L96) — `event(self, name, data)`
- [CloudWorker.heartbeat](../backend/cloud_worker.py#L114) — `heartbeat(self, status, **extra)`
- [CloudWorker.lease](../backend/cloud_worker.py#L132) — `lease(self)`
- [CloudWorker.release](../backend/cloud_worker.py#L153) — `release(self)`
- [CloudWorker.checkpoint](../backend/cloud_worker.py#L163) — `checkpoint(self)`
- [CloudWorker.initialize](../backend/cloud_worker.py#L210) — `async initialize(self, spec)`
- [CloudWorker.initialize.configure](../backend/cloud_worker.py#L237) — `configure(name, value)`
- [CloudWorker.recover_manifests](../backend/cloud_worker.py#L266) — `recover_manifests(self, store)`
- [CloudWorker.renew_loop](../backend/cloud_worker.py#L291) — `async renew_loop(self)`
- [CloudWorker.execution_permitted](../backend/cloud_worker.py#L302) — `execution_permitted(self)`
- [CloudWorker.request_analysis](../backend/cloud_worker.py#L319) — `request_analysis(self, packet)`
- [CloudWorker.reviewed](../backend/cloud_worker.py#L342) — `reviewed(self, spec, asset)`
- [CloudWorker.reserve_execution](../backend/cloud_worker.py#L356) — `reserve_execution(self, intent, spec, asset)`
- [CloudWorker.run_once](../backend/cloud_worker.py#L420) — `async run_once(self, spec, *, request_review=True, assets=None)`
- [CloudWorker.run](../backend/cloud_worker.py#L630) — `async run(self)`
- [main](../backend/cloud_worker.py#L732) — `main()`

### backend/data.py

- [fixture_market](../backend/data.py#L28) — `fixture_market(symbol: str, count=238)`
- [canonical_url](../backend/data.py#L79) — `canonical_url(raw: str)`
- [text_content](../backend/data.py#L106) — `text_content(raw, limit=1500)`
- [parse_time](../backend/data.py#L110) — `parse_time(raw)`
- [normalize_news](../backend/data.py#L118) — `normalize_news(payload: dict, retrieved: datetime, breaking=False, scoring: NewsScoring | None=None)`
- [fixture_news](../backend/data.py#L228) — `fixture_news()`
- [Providers](../backend/data.py#L284) — class
- [Providers.__init__](../backend/data.py#L285) — `__init__(self, store: Store, market_provider='fixture', news_provider='fixture', transport=None, news_key='', refresh: ProviderRefresh | None=None)`
- [Providers.close](../backend/data.py#L316) — `async close(self)`
- [Providers.request](../backend/data.py#L319) — `async request(self, url, **kwargs)`
- [Providers._candles](../backend/data.py#L333) — `async _candles(self, symbol: str, refresh: bool)`
- [Providers._cached_market](../backend/data.py#L370) — `_cached_market(self, cached, *, failed: bool=False)`
- [Providers.market](../backend/data.py#L384) — `async market(self, symbol: str, refresh=False)`
- [Providers.news](../backend/data.py#L448) — `async news(self, breaking=False, refresh=False)`

### backend/desk.py

- [AlertRequest](../backend/desk.py#L12) — class
- [PriceAlert](../backend/desk.py#L18) — class
- [PriceAlerts](../backend/desk.py#L30) — class
- [PriceAlerts.__init__](../backend/desk.py#L38) — `__init__(self, store: Store)`
- [PriceAlerts._load](../backend/desk.py#L42) — `_load(self)`
- [PriceAlerts.view](../backend/desk.py#L46) — `view(self)`
- [PriceAlerts._save](../backend/desk.py#L51) — `_save(self, rows, version)`
- [PriceAlerts._valid](../backend/desk.py#L57) — `_valid(self, market: Market | None)`
- [PriceAlerts.create](../backend/desk.py#L68) — `create(self, request: AlertRequest, markets: dict[str, Market])`
- [PriceAlerts.delete](../backend/desk.py#L83) — `delete(self, identifier: str)`
- [PriceAlerts.evaluate](../backend/desk.py#L93) — `evaluate(self, markets: dict[str, Market])`
- [sizing_preview](../backend/desk.py#L139) — `sizing_preview(portfolio, config: RiskConfig, symbol: str)`

### backend/engine.py

- [WorkflowState](../backend/engine.py#L50) — class
- [Engine](../backend/engine.py#L54) — class
- [Engine.__init__](../backend/engine.py#L55) — `__init__(self, store: Store, providers: Providers, research=None)`
- [Engine.strategies](../backend/engine.py#L80) — `strategies(self)`
- [Engine.refresh_markets](../backend/engine.py#L108) — `async refresh_markets(self)`
- [Engine._persist](../backend/engine.py#L122) — `_persist(self, run)`
- [Engine._node](../backend/engine.py#L125) — `_node(self, name)`
- [Engine._node.node](../backend/engine.py#L126) — `async node(state)`
- [Engine._stage](../backend/engine.py#L151) — `async _stage(self, name, ctx)`
- [Engine.run](../backend/engine.py#L410) — `async run(self, request: RunRequest, *, external_evidence=None)`
- [Engine.authorize](../backend/engine.py#L458) — `async authorize(self, request: Authorize)`
- [Engine.state](../backend/engine.py#L480) — `state(self)`
- [Engine.control](../backend/engine.py#L484) — `control(self, request: SchedulerAction)`
- [Engine.scheduler_loop](../backend/engine.py#L543) — `async scheduler_loop(self)`
- [Engine.recover](../backend/engine.py#L596) — `recover(self)`
- [Engine.close](../backend/engine.py#L618) — `async close(self)`

### backend/exchanges.py

- [IntegrationUnavailable](../backend/exchanges.py#L18) — class
- [QuoteProvider](../backend/exchanges.py#L22) — class
- [QuoteProvider.quote](../backend/exchanges.py#L23) — `async quote(self, proposal: Proposal, notional: Decimal)`
- [SwapExecutor](../backend/exchanges.py#L26) — class
- [SwapExecutor.submit](../backend/exchanges.py#L27) — `async submit(self, intent_id: str, quote: Quote)`
- [TransactionStatusProvider](../backend/exchanges.py#L30) — class
- [TransactionStatusProvider.transaction_status](../backend/exchanges.py#L31) — `async transaction_status(self, tx_hash: str)`
- [ExchangeAdapter](../backend/exchanges.py#L34) — class
- [SimulationAdapter](../backend/exchanges.py#L38) — class
- [SimulationAdapter.__init__](../backend/exchanges.py#L41) — `__init__(self, settings: SimulationSettings | None=None)`
- [SimulationAdapter.estimate_costs](../backend/exchanges.py#L44) — `estimate_costs(self, notional: Decimal, side: str)`
- [SimulationAdapter.quote](../backend/exchanges.py#L52) — `async quote(self, proposal: Proposal, notional: Decimal)`
- [SimulationAdapter.transaction_status](../backend/exchanges.py#L102) — `async transaction_status(self, tx_hash: str)`
- [HSKSwapAdapter](../backend/exchanges.py#L109) — class
- [HSKSwapAdapter.__init__](../backend/exchanges.py#L118) — `__init__(self, transport=None, settings: NetworkSettings | None=None)`
- [HSKSwapAdapter.close](../backend/exchanges.py#L134) — `async close(self)`
- [HSKSwapAdapter.configuration](../backend/exchanges.py#L137) — `configuration(self)`
- [HSKSwapAdapter.rpc](../backend/exchanges.py#L163) — `async rpc(self, method, params)`
- [HSKSwapAdapter.wallet](../backend/exchanges.py#L185) — `async wallet(self, address: str)`
- [HSKSwapAdapter.quote](../backend/exchanges.py#L211) — `async quote(self, proposal: Proposal, notional: Decimal)`
- [HSKSwapAdapter.submit](../backend/exchanges.py#L214) — `async submit(self, intent_id: str, quote: Quote)`
- [HSKSwapAdapter.transaction_status](../backend/exchanges.py#L219) — `async transaction_status(self, tx_hash: str)`
- [AlpacaPaperAdapter](../backend/exchanges.py#L240) — class
- [AlpacaPaperAdapter.account](../backend/exchanges.py#L243) — `account(self)`
- [AlpacaPaperAdapter.quote](../backend/exchanges.py#L254) — `async quote(self, proposal, notional)`

### backend/execution.py

- [Execution](../backend/execution.py#L19) — class
- [Execution.__init__](../backend/execution.py#L20) — `__init__(self, store: Store, portfolio: Portfolio, markets: dict, adapter=None)`
- [Execution.risk](../backend/execution.py#L38) — `risk(self)`
- [Execution.stopped](../backend/execution.py#L42) — `stopped(self)`
- [Execution.decision](../backend/execution.py#L46) — `decision(self, proposal: Proposal)`
- [Execution.record_risk](../backend/execution.py#L92) — `record_risk(self, decision)`
- [Execution.preview](../backend/execution.py#L96) — `async preview(self, proposal: Proposal)`
- [Execution.validate_context](../backend/execution.py#L100) — `validate_context(self, proposal: Proposal)`
- [Execution._preview](../backend/execution.py#L125) — `async _preview(self, proposal: Proposal)`
- [Execution.authorize](../backend/execution.py#L166) — `async authorize(self, request: Authorize)`
- [Execution.recover](../backend/execution.py#L281) — `recover(self)`
- [Execution.reconcile](../backend/execution.py#L301) — `reconcile(self, intent_id)`

### backend/models.py

- [now](../backend/models.py#L15) — `now()`
- [uid](../backend/models.py#L19) — `uid()`
- [Model](../backend/models.py#L27) — class
- [Mode](../backend/models.py#L31) — class
- [Token](../backend/models.py#L37) — class
- [Token.identity](../backend/models.py#L49) — `identity(self)`
- [Candle](../backend/models.py#L65) — class
- [Candle.valid_bar](../backend/models.py#L75) — `valid_bar(self)`
- [Market](../backend/models.py#L83) — class
- [Article](../backend/models.py#L97) — class
- [NewsFeed](../backend/models.py#L121) — class
- [NewsScoring](../backend/models.py#L135) — class
- [NewsScoring.validate_terms](../backend/models.py#L169) — `validate_terms(self)`
- [VersionedNewsScoring](../backend/models.py#L177) — class
- [StrategyConfig](../backend/models.py#L182) — class
- [StrategyConfig.periods](../backend/models.py#L203) — `periods(self)`
- [Signal](../backend/models.py#L211) — class
- [ResearchEvidence](../backend/models.py#L226) — class
- [RiskConfig](../backend/models.py#L234) — class
- [Proposal](../backend/models.py#L255) — class
- [Check](../backend/models.py#L278) — class
- [RiskDecision](../backend/models.py#L286) — class
- [Quote](../backend/models.py#L298) — class
- [IntentState](../backend/models.py#L323) — class
- [Position](../backend/models.py#L337) — class
- [StageTiming](../backend/models.py#L354) — class
- [ExecutionIntent](../backend/models.py#L360) — class
- [ExecutionIntent.consistent_intent](../backend/models.py#L376) — `consistent_intent(self)`
- [RunRequest](../backend/models.py#L392) — class
- [VersionedStrategy](../backend/models.py#L397) — class
- [VersionedRisk](../backend/models.py#L402) — class
- [Authorize](../backend/models.py#L407) — class
- [SchedulerAction](../backend/models.py#L413) — class
- [ChatRequest](../backend/models.py#L425) — class
- [BacktestRequest](../backend/models.py#L429) — class

### backend/portfolio.py

- [Portfolio](../backend/portfolio.py#L13) — class
- [Portfolio.__init__](../backend/portfolio.py#L14) — `__init__(self, store: Store)`
- [Portfolio.view](../backend/portfolio.py#L21) — `view(self, markets: dict[str, Market])`
- [Portfolio.observe](../backend/portfolio.py#L151) — `observe(self, markets)`
- [Portfolio.snapshot](../backend/portfolio.py#L163) — `snapshot(self, markets)`

### backend/research.py

- [NoMemory](../backend/research.py#L22) — class
- [NoMemory.get_memories](../backend/research.py#L23) — `get_memories(self, situation, n_matches=2)`
- [BoundedResearchLLM](../backend/research.py#L27) — class
- [BoundedResearchLLM.__init__](../backend/research.py#L28) — `__init__(self, llm)`
- [BoundedResearchLLM.invoke](../backend/research.py#L31) — `invoke(self, prompt)`
- [ResearchBridge](../backend/research.py#L41) — class
- [ResearchBridge.__init__](../backend/research.py#L44) — `__init__(self, llm=None)`
- [ResearchBridge.analyze](../backend/research.py#L58) — `async analyze(self, market_report: str, news_report: str)`
- [ResearchBridge.analyze.invoke](../backend/research.py#L89) — `async invoke(factory)`

### backend/research_brief.py

- [Finding](../backend/research_brief.py#L20) — class
- [Citation](../backend/research_brief.py#L27) — class
- [RiskPlan](../backend/research_brief.py#L39) — class
- [BriefBody](../backend/research_brief.py#L55) — class
- [SnapshotReceipt](../backend/research_brief.py#L80) — class
- [ResearchBrief](../backend/research_brief.py#L87) — class
- [_url](../backend/research_brief.py#L91) — `_url(value: Any)`
- [_money](../backend/research_brief.py#L103) — `_money(value: Any)`
- [build_brief](../backend/research_brief.py#L111) — `build_brief(run: dict)`
- [build_brief.output](../backend/research_brief.py#L114) — `output(name: str)`

### backend/risk.py

- [assess](../backend/risk.py#L12) — `assess(proposal: Proposal, portfolio: dict, config: RiskConfig, version: int, *, stopped=False, pending=False, recent_failures=0, last_trade: datetime | None=None, clo...`
- [assess.check](../backend/risk.py#L27) — `check(code, passed, actual, limit, reason)`
- [validate_quote](../backend/risk.py#L238) — `validate_quote(quote: Quote, proposal: Proposal, decision: RiskDecision, config: RiskConfig, clock=None, wallet=None)`

### backend/selection.py

- [selection_inputs](../backend/selection.py#L14) — `selection_inputs(store, symbol: str, market: Market)`
- [SelectionConfig](../backend/selection.py#L36) — class
- [rank_strategies](../backend/selection.py#L53) — `rank_strategies(market: Market, news: NewsFeed, signals: list[Signal], config: SelectionConfig, previous: dict | None=None, performance: dict | None=None, contextual_a...`
- [rank_strategies.clip](../backend/selection.py#L74) — `clip(x)`

### backend/settings.py

- [SettingsModel](../backend/settings.py#L20) — class
- [public_https](../backend/settings.py#L24) — `public_https(value: str)`
- [ProviderRefresh](../backend/settings.py#L50) — class
- [ReferenceAsset](../backend/settings.py#L57) — class
- [DataSettings](../backend/settings.py#L62) — class
- [DataSettings.supported_identity](../backend/settings.py#L77) — `supported_identity(self)`
- [SimulationSettings](../backend/settings.py#L86) — class
- [SimulationSettings.deadline_after_expiry](../backend/settings.py#L98) — `deadline_after_expiry(self)`
- [SchedulerSettings](../backend/settings.py#L104) — class
- [DocumentedToken](../backend/settings.py#L109) — class
- [NetworkSettings](../backend/settings.py#L114) — class
- [RuntimeSettings](../backend/settings.py#L125) — class
- [RuntimeSettings.default_asset_available](../backend/settings.py#L133) — `default_asset_available(self)`
- [RuntimeSettings.fingerprint](../backend/settings.py#L139) — `fingerprint(self)`
- [get_settings](../backend/settings.py#L146) — `get_settings()`

### backend/storage.py

- [json_default](../backend/storage.py#L17) — `json_default(value)`
- [encode](../backend/storage.py#L27) — `encode(value)`
- [safe](../backend/storage.py#L31) — `safe(value: Any)`
- [Store](../backend/storage.py#L47) — class
- [Store.__init__](../backend/storage.py#L48) — `__init__(self, path: str)`
- [Store.transaction](../backend/storage.py#L84) — `transaction(self)`
- [Store.close](../backend/storage.py#L99) — `close(self)`
- [Store.config](../backend/storage.py#L102) — `config(self, name: str, default=None)`
- [Store.update_config](../backend/storage.py#L116) — `update_config(self, name: str, value, expected: int | None=None)`
- [Store.audit](../backend/storage.py#L131) — `audit(self, kind: str, payload)`
- [Store.put](../backend/storage.py#L138) — `put(self, table: str, identifier: str, payload, *, state: str='', proposal_id: str='')`
- [Store.get](../backend/storage.py#L172) — `get(self, table: str, identifier: str)`
- [Store.financial_history](../backend/storage.py#L182) — `financial_history(self, table: str)`
- [Store.history](../backend/storage.py#L191) — `history(self, table: str, limit=50, offset=0)`
- [Store.snapshot](../backend/storage.py#L208) — `snapshot(self, payload)`
- [Store.prune_chat](../backend/storage.py#L215) — `prune_chat(self)`

### backend/strategies.py

- [indicators](../backend/strategies.py#L63) — `indicators(market: Market)`
- [evaluate](../backend/strategies.py#L134) — `evaluate(strategy_id: str, market: Market, news: NewsFeed, config: StrategyConfig, holding=False, clock=None)`

### backend/strategy_registry.py

- [StrategyEvaluation](../backend/strategy_registry.py#L13) — class
- [TradingStrategy](../backend/strategy_registry.py#L27) — class
- [TradingStrategy.evaluate](../backend/strategy_registry.py#L31) — `evaluate(self, market: Market, news: NewsFeed, holding: bool=False, clock=None)`
- [TradingStrategy.validate](../backend/strategy_registry.py#L34) — `validate(self, market: Market)`
- [TradingStrategy.get_configuration](../backend/strategy_registry.py#L35) — `get_configuration(self)`
- [RuleStrategy](../backend/strategy_registry.py#L38) — class
- [RuleStrategy.__init__](../backend/strategy_registry.py#L39) — `__init__(self, identifier: str, configuration: StrategyConfig)`
- [RuleStrategy.get_configuration](../backend/strategy_registry.py#L44) — `get_configuration(self)`
- [RuleStrategy.validate](../backend/strategy_registry.py#L47) — `validate(self, market)`
- [RuleStrategy.evaluate](../backend/strategy_registry.py#L56) — `evaluate(self, market, news, holding=False, clock=None)`
- [builtins](../backend/strategy_registry.py#L78) — `builtins(configurations: dict[str, StrategyConfig])`

### backend/trade_history.py

- [realized_deltas](../backend/trade_history.py#L19) — `realized_deltas(records: list[dict])`
- [research_record](../backend/trade_history.py#L46) — `research_record(record: dict, realized: str)`
- [research_history](../backend/trade_history.py#L76) — `research_history(store, filters: TradeFilters)`
- [research_detail](../backend/trade_history.py#L113) — `research_detail(store, trade_id: str)`

## TypeScript exported entry points and contracts

### backend/src/agents/agent.service.ts

- [AgentService](../backend/src/agents/agent.service.ts#L39)

### backend/src/auth/cognito.ts

- [Authenticator](../backend/src/auth/cognito.ts#L20)
- [CognitoAuth](../backend/src/auth/cognito.ts#L23)

### backend/src/config.ts

- [Config](../backend/src/config.ts#L89)
- [loadConfig](../backend/src/config.ts#L104)

### backend/src/domain/errors.ts

- [PlatformError](../backend/src/domain/errors.ts#L1)

### backend/src/domain/schemas.ts

- [AgentSpec](../backend/src/domain/schemas.ts#L262)
- [Profile](../backend/src/domain/schemas.ts#L263)
- [DeploymentState](../backend/src/domain/schemas.ts#L278)
- [Agent](../backend/src/domain/schemas.ts#L279)
- [Deployment](../backend/src/domain/schemas.ts#L295)
- [Principal](../backend/src/domain/schemas.ts#L308)
- [RecordItem](../backend/src/domain/schemas.ts#L313)

### backend/src/integrations/llm/agent-analysis.service.ts

- [AgentAnalysisService](../backend/src/integrations/llm/agent-analysis.service.ts#L28)

### backend/src/integrations/llm/analysis-consumer.ts

- [consumeAnalysis](../backend/src/integrations/llm/analysis-consumer.ts#L8)

### backend/src/integrations/llm/bedrock.client.ts

- [createBedrockClient](../backend/src/integrations/llm/bedrock.client.ts#L5)

### backend/src/integrations/llm/conversation.service.ts

- [ConversationService](../backend/src/integrations/llm/conversation.service.ts#L54)

### backend/src/integrations/llm/llm.interface.ts

- [ModelMessage](../backend/src/integrations/llm/llm.interface.ts#L1)
- [ToolDefinition](../backend/src/integrations/llm/llm.interface.ts#L15)
- [LLMContext](../backend/src/integrations/llm/llm.interface.ts#L20)
- [LLMRequest](../backend/src/integrations/llm/llm.interface.ts#L26)
- [LLMResponse](../backend/src/integrations/llm/llm.interface.ts#L33)
- [LLMProvider](../backend/src/integrations/llm/llm.interface.ts#L40)

### backend/src/integrations/llm/minimax.provider.ts

- [MiniMaxProvider](../backend/src/integrations/llm/minimax.provider.ts#L15)

### backend/src/integrations/llm/prompt-manager.ts

- [PromptManager](../backend/src/integrations/llm/prompt-manager.ts#L4)

### backend/src/integrations/llm/structured-output.ts

- [validateOutput](../backend/src/integrations/llm/structured-output.ts#L3)
- [bedrockSchema](../backend/src/integrations/llm/structured-output.ts#L14)

### backend/src/integrations/llm/token-usage.service.ts

- [TokenUsageService](../backend/src/integrations/llm/token-usage.service.ts#L14)

### backend/src/integrations/llm/tool-registry.ts

- [ToolRegistry](../backend/src/integrations/llm/tool-registry.ts#L18)

### backend/src/profiles/profile.service.ts

- [ProfileService](../backend/src/profiles/profile.service.ts#L9)

### backend/src/runtime/agent-template.ts

- [agentTemplate](../backend/src/runtime/agent-template.ts#L6)

### backend/src/runtime/aws-runtime.ts

- [AwsRuntime](../backend/src/runtime/aws-runtime.ts#L51)

### backend/src/runtime/broker.ts

- [handler](../backend/src/runtime/broker.ts#L18)

### backend/src/runtime/janitor.ts

- [handler](../backend/src/runtime/janitor.ts#L12)

### backend/src/runtime/runtime.interface.ts

- [RuntimeStatus](../backend/src/runtime/runtime.interface.ts#L7)
- [RuntimeProvider](../backend/src/runtime/runtime.interface.ts#L32)

### backend/src/server.ts

- [createPlatform](../backend/src/server.ts#L37)

### backend/src/storage/tenant-store.ts

- [Write](../backend/src/storage/tenant-store.ts#L11)
- [Page](../backend/src/storage/tenant-store.ts#L17)
- [TenantStore](../backend/src/storage/tenant-store.ts#L21)
- [DynamoTenantStore](../backend/src/storage/tenant-store.ts#L67)
- [MemoryTenantStore](../backend/src/storage/tenant-store.ts#L195)
