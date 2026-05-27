# Codee — Fase 1: Design (Dados + Dashboard)

**Data:** 2026-05-27
**Autor:** Alexandre (Codee) + Claude
**Status:** Spec aprovado em brainstorming, aguardando review final antes do plano de implementação
**Projeto:** `F:\codefee\AAVE_STRAT` (separado do Volume_tracker; integração futura opcional)

---

## 1. Propósito

Codee é um bot/dashboard de yield DeFi. **A Fase 1 entrega a fundação de dados:** puxa rates de empréstimo do DefiLlama em cadência fixa, calcula spreads e rotas (passive supply + leveraged loops), persiste history, e expõe tudo via API REST consumida por um dashboard.

A Fase 1 **não executa transações** — é a camada de inteligência que informa decisões de capital. Execução on-chain, Binance e alertas são Fases 2-3.

---

## 2. Achado crítico que moldou este design (reality check 25-mai-2026)

Antes de fechar o design, rodamos `demo_routes.py` contra a API real do DefiLlama. Resultado refuta a tese central do documento de contexto (`codee_strategy_context.md`):

| Métrica | Contexto (snapshot abr/2026) | Live (25-mai-2026) |
|---|---|---|
| BSC Venus USDT supply | 8,0% (com rewards XVS) | **2,00% (apyReward = 0)** |
| Spread estrutural BSC | ~5% | **negativo (−1,86%)** |
| Pools globais com `apyReward > 0` | (muitos, implícito) | **134 de 4.134 (3,2%)** |
| Loops com spread positivo | "sempre BSC/Base" | **2, ambos em Ethereum** |
| Melhor oportunidade hoje | leveraged loop ~25% | **passive supply 17,9% (Base yearn USDC)** |

**Conclusões que viraram requisitos:**

1. **Passive supply > leveraged loops no mercado atual** (17,9% vs 7,3% no melhor loop). A Strategy 1 do contexto (BSC ping-pong) hoje **perde dinheiro** (−3,27% net APY).
2. **Programas de incentivo (XVS/Merit) provavelmente pausaram ou migraram** (USD1 migrou de BSC pra Ethereum Dolomite, $43M TVL).
3. O Codee precisa ser **discovery-first** (onde existe spread, em qualquer chain), não chain-anchored (rankear BSC).
4. **Detectar o retorno do regime de rewards** é a função primária — `reward_active_pools` subindo de 0 é o sinal de timing.

O framework do contexto (LAV buckets, matemática de loop, escada de risco) continua válido. Os **números** do contexto são ilustrativos, não correntes.

---

## 3. Escopo da Fase 1

**Inclui:** ingestão DefiLlama (2 endpoints), validação de sanidade, persistência SQLite com history, agregados 7d/30d, ranking passive + loops, API REST, dashboard Streamlit, reward token prices + classificação LAV.

**Fora (Fases futuras):**
- Execução on-chain (Aave/Venus/Morpho contracts) — Fase 3
- Binance API — Fase 3
- Alertas Telegram/Slack — Fase 2 (health endpoint já expõe os dados)
- Sub-hour RPC polling — Fase 4
- Backtesting — Fase 4
- `liquidation_threshold`, `oracle_source`, `e_mode_enabled` (exigem integração on-chain) — Fase 2/3

---

## 4. Stack

| Camada | Tecnologia | Razão |
|---|---|---|
| Backend | Python 3.13 + FastAPI + APScheduler | Ecossistema DeFi/quant; APScheduler para cron in-process |
| ORM/DB | SQLAlchemy + SQLite (aiosqlite) | Prototipagem rápida; abstração para migrar a QuestDB depois |
| Dashboard | Streamlit (agora) → dash HTML existente (depois) | Streamlit consome a API; migração futura só troca o front |
| Testes | pytest + pytest-asyncio + httpx | TDD na implementação |

**Decisão arquitetural:** o dashboard **nunca** acessa o DB direto — só `/api/codee/*`. Garante que a migração Streamlit→HTML não reescreve lógica.

---

## 5. Arquitetura (3 camadas + orquestração)

```
INGESTION   →   STORAGE + DERIVATION   →   PRESENTATION
(sources/)      (db/ + services/*/)        (api/ + web/)
```

- **Ingestion:** DefiLlama poller (60min), reward token prices (15min).
- **Storage + derivation:** SQLite via SQLAlchemy; validação de sanidade; agregados 7d/30d.
- **Presentation:** FastAPI `/api/codee/*` (JSON); Streamlit consome a API.

**Orquestração:** `main.py` faz `asyncio.gather` de todos os loops (padrão Volume_tracker). FastAPI roda no mesmo event loop via uvicorn.Server. Streamlit roda em processo separado.

### Estrutura de pastas

```
AAVE_STRAT/
├── main.py                          # asyncio.gather de todos os loops
├── requirements.txt / pyproject.toml
├── .env.example
├── config/
│   ├── config.py                    # Config class, lê .env
│   ├── chains.json                  # gas_per_tx, excluded flag por chain
│   ├── stable_symbols.json          # whitelist de stables
│   ├── lav_buckets.json             # token symbol -> A/B/C
│   └── projects.json                # project -> reward token, display name
├── db/
│   ├── sqlite_client.py             # aiosqlite + SQLAlchemy async
│   ├── models.py                    # tabelas declarative
│   └── migrations/001_initial_schema.sql
├── sources/
│   ├── defillama/client.py          # /pools + /lendBorrow + /chart
│   ├── coingecko/client.py          # reward token prices
│   └── dexscreener/client.py        # fallback
├── services/
│   ├── pools/
│   │   ├── ingestor.py              # async run() 60min: fetch+JOIN+validate+persist
│   │   ├── validators.py            # regras de sanidade -> quality_flag
│   │   ├── aggregator.py            # 7d/30d rolling
│   │   └── snapshot.py              # upsert snapshot + insert history
│   ├── rewards/
│   │   ├── ingestor.py              # async run() 15min: prices
│   │   └── lav.py                   # bucket_for_token(), discount()
│   ├── routes/
│   │   └── analyzer.py              # PURO: effective rates, loops, ranking
│   └── api/
│       ├── router.py                # FastAPI endpoints
│       └── models.py                # Pydantic response schemas
├── web/
│   └── dashboard.py                 # Streamlit
├── scripts/
│   ├── bootstrap_db.py              # schema + configs + dispara backfill
│   └── backfill_history.py          # /chart/{uuid} para 90d
└── tests/
    ├── fixtures/                    # payloads DefiLlama capturados (offline)
    ├── test_defillama_client.py
    ├── test_validators.py
    ├── test_pools_ingestor.py
    ├── test_analyzer.py             # coração da suíte
    └── test_api.py
```

### Direção de dependências (sem ciclos)

```
config → sources → services → api → web
                ↓
               db ←──────┘
```

- `sources/`: só HTTP. Sem DB, sem config (injetada).
- `services/pools` + `services/rewards`: usam `sources/`, escrevem em `db/`.
- `services/routes/analyzer.py`: **100% puro** — lê do `db/`, sem I/O, sem state. Testável sem rede.
- `services/api`: lê `db/` ou chama `analyzer`. Retorna JSON.
- `web/dashboard.py`: só consome `/api/codee/*`.

Trocar SQLite→QuestDB mexe só em `db/`. Trocar Streamlit→HTML mexe só em `web/`.

---

## 6. Fluxo de dados

### Pipeline de um snapshot

```
[cron 60min] pools_ingestor.run()
  → GET /pools + GET /lendBorrow  (paralelo via asyncio.gather)
  → JOIN por pool UUID
  → filtros (TVL>=$1M, stable, chain not excluded)
  → VALIDATE (validators.py → quality_flag por pool)
  → snapshot.py: BEGIN; UPSERT pools_snapshot; INSERT pools_history; COMMIT
  → aggregator.py (chained): recalcula rate_aggregates 7d/30d
```

### Cadência

| Loop | Cadência | Offset | Razão |
|---|---|---|---|
| pools_ingestor | 60 min | T=0 | DefiLlama atualiza hourly — mais rápido = duplicata |
| rewards_ingestor | 15 min | T=2,5 | CoinGecko move mais rápido; reward≈0 hoje torna 15min generoso |
| aggregator | on-trigger | pós-ingest | 7d/30d rolling |

Configurável via `.env` (`SNAPSHOT_INTERVAL_MIN`). Apertar para 15/5 quando rewards/loops voltarem.

### Política: "fail open, never lie"

Nunca servir dado sintético/estimado. Em falha, servir o último snapshot bom + timestamp. Se snapshot > 3h: dashboard mostra **banner vermelho**, health vira `degraded`.

### Error handling

| Falha | Resposta |
|---|---|
| DefiLlama timeout/5xx | Pula tick, mantém último snapshot bom |
| Schema drift | ValidationError clara, ingere o que conseguir, flag no health |
| `/lendBorrow` falha, `/pools` ok | Persiste só supply, borrow fields NULL |
| Pool some do feed | `status='inactive'` (não DELETE — preserva history) |
| CoinGecko 429 | Backoff exponencial → fallback DexScreener |
| LAV bucket desconhecido | Default bucket B (12,5%), flag `lav_uncertain=true` ("B?") |
| Anomalia de dado (validators) | `quality_flag` setado, pool destacado no dashboard, não dropado |

---

## 7. Database schema

**Decisão central: armazenar rates CRUS, computar efetivo on-read.** `pools_snapshot`/`pools_history` guardam `supply_apy_base`/`supply_apy_reward` separados. O `effective_*` (com LAV) é calculado em `analyzer.py` no request. Reclassificar um token recalcula todo o history de graça.

DDL completo no Apêndice A.

**Tabelas:**
- `pools_snapshot` — estado atual, 1 linha/pool, UPSERT. Inclui `quality_flag`, `lav_uncertain`, `status`, e os campos do `/lendBorrow` (`total_supply_usd`, `debt_ceiling_usd`, `borrowable`, `borrow_factor`, `underlying_tokens`).
- `pools_history` — append-only. PK `(pool_id, ts, source)` onde `source ∈ {'live','chart_daily'}` permite coexistir backfill diário + coletas live.
- `reward_token_prices` — preço + classificação LAV, current + histórico.
- `rate_aggregates` — médias rolling 7d/30d. **Exceção à regra do cru**: guarda efetivo (descartável, recomputado pós-ingest e em mudança de LAV config).

**Princípio: capturar todo campo que a fonte dá no ingest, mesmo sem usar** — history não dá pra backfillar retroativamente.

**Retenção:** sem purge na Fase 1 (disco barato, history longo é necessário pra detectar regime change). Purge entra na migração QuestDB.

---

## 8. Validação & testing

### Pirâmide (peso invertido — math é onde bug custa dinheiro)

```
API tests (router)        ~15%
Integration (DB)          ~25%
Contract (sources)        ~20%
Unit: analyzer.py (math)  ~40%
```

**Regra absoluta:** testes nunca tocam a rede. Payloads DefiLlama capturados uma vez em `tests/fixtures/`, suíte roda offline.

### Cobertura por nível

- **Unit `analyzer.py`** (meta ≥95%): effective supply/borrow APY com LAV (buckets A/B/C); floor em 0 do borrow; **fórmula de alavancagem fixada em teste** (pin 5,46x para 0,855/10iter — resolve a discrepância 5,46 vs 6,60 do contexto); enumeração de loops 4-pernas; edge cases (spread negativo não crasha, pool sem borrow, reward 0).
- **Contract `defillama/client.py`**: parse das fixtures; JOIN por UUID; schema drift.
- **Integration `ingestor`/`aggregator`** (SQLite tmpfile): idempotência (2x ingest → 1 snapshot, 2 history); pool inativo não deletado; recompute pós-LAV-change.
- **API `router.py`** (TestClient): cold start → 503 `warming_up`; param inválido → 422; staleness flag.

### Validações adicionais (decididas no brainstorm)

**Obrigatórias na Fase 1:**
1. **Camada de sanidade do dado** (`validators.py` + `quality_flag`): detecta supply APY absurdo (ex. >1000%), TVL crash (>X% queda inter-snapshot), utilization impossível (>100%), rates negativos inválidos. Sinaliza, **nunca dropa silenciosamente**. Pool com flag aparece destacado no dashboard.
2. **Golden regression**: payload de 25-mai-2026 congelado como fixture; trava que o ranking produz os números conhecidos (17,9% passive, 7,3% loop). Pega regressão de math.
3. **Join coverage assertion**: alerta se `join_rate` cair abaixo de ~50% do normal histórico (breakage silencioso do `/lendBorrow`).

**Recomendadas (Fase 1.5, documentadas):**
4. Property-based testing (hypothesis): `net_apy ≤ gross_apy`, `effective_borrow_apr ≥ 0`, leverage monotônica.
5. Cross-validação do agregado 7d contra `/chart`.
6. Consistência UTC/timestamp (history monotônico, espaçado — guarda contra bugs de drift de meia-noite).
7. Decimal vs float: float serve na Fase 1; math monetária vira Decimal na Fase 3.

---

## 9. Deploy & observability

### Dev (agora — Windows local)

```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python scripts\bootstrap_db.py      # schema + backfill 90d
python main.py                      # terminal 1: scheduler + API
streamlit run web\dashboard.py      # terminal 2: dashboard
```

Dois processos: reiniciar o dashboard (frequente ao iterar UI) não derruba a coleta. Conversam só via HTTP.

### Produção (futuro — quando provado)

Padrão Volume_tracker: servidor `199.247.3.163`, git bundle, systemd (`codee.service` + `codee-dashboard.service`). **Não é Fase 1** — local Windows enquanto validamos a tese.

### Observability

- **Logging:** módulo `logging` (não `print`), estilo legível (`[Pools] ingested 4123, 234 in-scope, join_rate 87%`), console + arquivo rotativo.
- **Health endpoint** `GET /api/codee/health`: `status`, `last_snapshot_at`, `snapshot_age_s`, `stale`, `pool_count_total/in_scope`, `join_rate`, `lav_coverage_pct`, `quality_flags{}`, **`reward_active_pools`** (sinal de regime), `last_error`.

Sem APM/Prometheus na Fase 1 — health + logs bastam para 1 usuário local.

---

## 10. Operação diária

Dashboard com 4 abas + cards de regime no topo:
- **Topo:** `reward_active_pools`, best passive, best loop, snapshot age, join_rate.
- **Aba 1 — Passive supply:** ranking por net APY, qualquer chain.
- **Aba 2 — Loops:** só spread positivo (hoje provavelmente vazio = sinal válido).
- **Aba 3 — Reward health:** programas ativos, LAV coverage.
- **Aba 4 — History:** evolução 7d/30d/90d por pool.

Inputs ajustáveis: `principal` ($250k default), `hold_h` (7d default).

**Pergunta primária que o Codee responde:** *"O regime mudou? Os rewards/spreads voltaram pra valer alavancar — ou ainda é passive / não fazer nada?"* Até `reward_active_pools` subir de 0 e a Aba 2 encher, o Codee impede rodar a Strategy 1 do contexto no autopiloto.

---

## 11. Estimativa de tamanho

~2.000 linhas de produção + ~400 de teste. Legível em uma tarde.

| Módulo | ~Linhas |
|---|---|
| sources/defillama/client.py | 80 |
| services/pools/* (ingestor, validators, aggregator, snapshot) | 400 |
| services/rewards/* | 150 |
| services/routes/analyzer.py | 200 |
| services/api/* | 200 |
| db/* | 150 |
| web/dashboard.py | 300 |
| main.py | 80 |
| tests | 400 |

---

## 12. Perguntas em aberto (resolver durante implementação)

1. **Fórmula de alavancagem definitiva** — 5,46x (0,855/10iter, nosso cálculo) vs 6,60x (contexto). Travada em teste; confirmar com estrategista qual é a intenção (buffer reduz LTV por iteração, ou é reserva separada?).
2. **Thresholds dos validators** — qual % de TVL crash dispara flag? Qual APY é "absurdo"? Calibrar com dados reais.
3. **`join_rate` baseline** — qual o normal histórico para setar o alerta? Medir nas primeiras semanas.
4. **LAV classification dos tokens novos** — ember, bitway, avantis aparecem como "B?". Classificar conforme investigarmos cada programa.
5. **Resolução de reward token** — `rewardTokens` do DefiLlama são addresses; mapear address → symbol → preço CoinGecko exige tabela. Definir fonte da verdade.

---

## Apêndice A — DDL completo

```sql
-- pools_snapshot — estado atual, 1 linha por pool, UPSERT
CREATE TABLE pools_snapshot (
    pool_id           TEXT PRIMARY KEY,
    chain             TEXT NOT NULL,
    project           TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    pool_meta         TEXT,
    tvl_usd           REAL NOT NULL,
    total_supply_usd  REAL,
    total_borrow_usd  REAL,
    debt_ceiling_usd  REAL,
    utilization       REAL,
    supply_apy_base   REAL NOT NULL DEFAULT 0,
    supply_apy_reward REAL NOT NULL DEFAULT 0,
    borrow_apr_base   REAL,
    borrow_apr_reward REAL,
    ltv               REAL,
    borrow_factor     REAL,
    borrowable        INTEGER,
    reward_tokens     TEXT,
    underlying_tokens TEXT,
    lav_uncertain     INTEGER NOT NULL DEFAULT 0,
    quality_flag      TEXT NOT NULL DEFAULT 'ok',
    status            TEXT NOT NULL DEFAULT 'active',
    updated_at        INTEGER NOT NULL
);
CREATE INDEX idx_snapshot_chain    ON pools_snapshot(chain);
CREATE INDEX idx_snapshot_symbol   ON pools_snapshot(symbol);
CREATE INDEX idx_snapshot_util     ON pools_snapshot(utilization);
CREATE INDEX idx_snapshot_loopable ON pools_snapshot(chain, symbol) WHERE borrow_apr_base IS NOT NULL;

-- pools_history — append-only
CREATE TABLE pools_history (
    pool_id           TEXT NOT NULL,
    ts                INTEGER NOT NULL,
    source            TEXT NOT NULL,             -- 'live' | 'chart_daily'
    tvl_usd           REAL,
    total_supply_usd  REAL,
    total_borrow_usd  REAL,
    debt_ceiling_usd  REAL,
    supply_apy_base   REAL,
    supply_apy_reward REAL,
    borrow_apr_base   REAL,
    borrow_apr_reward REAL,
    utilization       REAL,
    quality_flag      TEXT NOT NULL DEFAULT 'ok',
    PRIMARY KEY (pool_id, ts, source)
);
CREATE INDEX idx_history_pool_ts ON pools_history(pool_id, ts);
CREATE INDEX idx_history_ts      ON pools_history(ts);

-- reward_token_prices
CREATE TABLE reward_token_prices (
    token_id         TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    ts               INTEGER NOT NULL,
    price_usd        REAL NOT NULL,
    source           TEXT NOT NULL,              -- 'coingecko' | 'dexscreener'
    lav_bucket       TEXT,                        -- 'A'|'B'|'C'|NULL
    lav_discount_pct REAL NOT NULL DEFAULT 0.125,
    PRIMARY KEY (token_id, ts)
);
CREATE INDEX idx_prices_symbol_ts ON reward_token_prices(symbol, ts);

-- rate_aggregates — médias rolling (guarda efetivo, recomputável)
CREATE TABLE rate_aggregates (
    pool_id                  TEXT NOT NULL,
    window                   TEXT NOT NULL,       -- '7d' | '30d'
    supply_apy_effective_avg REAL,
    borrow_apr_effective_avg REAL,
    utilization_avg          REAL,
    tvl_avg                  REAL,
    sample_count             INTEGER NOT NULL,
    computed_at              INTEGER NOT NULL,
    PRIMARY KEY (pool_id, window)
);
```

## Apêndice B — Endpoints da API

```
GET /api/codee/health                                    -> status do sistema
GET /api/codee/pools/snapshot                            -> pools atuais (paginado)
GET /api/codee/pools/{pool_id}/history?d=30              -> time series por pool
GET /api/codee/routes/passive?principal=&hold_h=         -> ranking passive supply
GET /api/codee/routes/loops?principal=&hold_h=           -> ranking loops (spread positivo)
GET /api/codee/rewards/coverage                          -> tokens classificados vs "B?"
GET /api/codee/chains/summary                            -> spread médio por chain (7d/30d)
```

## Apêndice C — Referências

- `codee_strategy_context.md` — documento de contexto/estratégia (framework válido, números desatualizados)
- `demo_routes.py` — proof-of-concept do pipeline (fetch→JOIN→filter→rank), valida o design
- DefiLlama API: `yields.llama.fi/pools` (supply), `yields.llama.fi/lendBorrow` (borrow), `yields.llama.fi/chart/{uuid}` (history)
