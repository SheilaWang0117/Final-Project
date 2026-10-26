-- Ocra Pipeline Tracker: initial schema.
-- Money is stored as INTEGER minor units (cents/fen) with an explicit currency.
-- Exchange rates are stored as decimal TEXT to avoid binary floating point.
-- `origin` marks provenance: 'user' (entered), 'import', 'synthetic' (demo), 'agent' (AI draft).

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE activity_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_activity_ts ON activity_log(ts);

-- ---------------------------------------------------------------- pipelines
CREATE TABLE programs (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    therapeutic_area TEXT,
    indication TEXT,
    use_type TEXT NOT NULL DEFAULT 'unknown' CHECK (use_type IN ('human','veterinary','unknown')),
    species_json TEXT NOT NULL DEFAULT '[]',
    target TEXT,
    mechanism TEXT,
    modality TEXT,
    molecule_category TEXT NOT NULL DEFAULT 'unknown'
        CHECK (molecule_category IN ('small_molecule','biologic','other','unknown')),
    route TEXT,
    stage_template TEXT NOT NULL DEFAULT 'veterinary' CHECK (stage_template IN ('veterinary','human')),
    stage TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','on_hold','discontinued','completed')),
    owner TEXT,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
    jurisdictions_json TEXT NOT NULL DEFAULT '[]',
    key_dates_json TEXT NOT NULL DEFAULT '[]',
    risks TEXT,
    notes TEXT,
    public_keywords_json TEXT NOT NULL DEFAULT '[]',
    profile_confirmed_at TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE classification_proposals (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),
    input_text TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    agent_run_id INTEGER,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','confirmed','rejected')),
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE milestones (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL REFERENCES programs(id),
    name TEXT NOT NULL,
    description TEXT,
    stage TEXT,
    planned_start TEXT,
    planned_end TEXT,
    baseline_start TEXT,
    baseline_end TEXT,
    actual_end TEXT,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned','in_progress','done','at_risk','cancelled')),
    owner TEXT,
    is_decision_point INTEGER NOT NULL DEFAULT 0,
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_milestones_program ON milestones(program_id);

-- ------------------------------------------------------------------ finance
CREATE TABLE legal_entities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL
);

CREATE TABLE cash_accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    legal_entity_id INTEGER REFERENCES legal_entities(id),
    currency TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    origin TEXT NOT NULL DEFAULT 'user'
);

-- A reconciled balance: the anchor for cash. Transactions after as_of_date roll it forward.
CREATE TABLE cash_balances (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES cash_accounts(id),
    as_of_date TEXT NOT NULL,
    balance_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    source TEXT,
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

CREATE TABLE fx_rates (
    id INTEGER PRIMARY KEY,
    base TEXT NOT NULL,
    quote TEXT NOT NULL,
    rate TEXT NOT NULL,           -- 1 base = rate quote (decimal string)
    rate_date TEXT NOT NULL,
    source TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'manual' CHECK (method IN ('manual','ecb_reference','fixture')),
    created_at TEXT NOT NULL,
    UNIQUE (base, quote, rate_date, source)
);

CREATE TABLE budget_lines (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),       -- NULL = shared company cost
    milestone_id INTEGER REFERENCES milestones(id),
    category TEXT NOT NULL,
    description TEXT,
    currency TEXT NOT NULL,
    planned_minor INTEGER NOT NULL DEFAULT 0,
    approved_minor INTEGER,                           -- NULL until approved
    contingency_bps INTEGER NOT NULL DEFAULT 0,       -- 1000 = 10%
    owner TEXT,
    estimate_source TEXT,
    assumptions TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','closed')),
    approved_at TEXT,
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE budget_schedule (
    id INTEGER PRIMARY KEY,
    budget_line_id INTEGER NOT NULL REFERENCES budget_lines(id) ON DELETE CASCADE,
    month TEXT NOT NULL,          -- YYYY-MM
    amount_minor INTEGER NOT NULL,
    UNIQUE (budget_line_id, month)
);

CREATE TABLE allocation_rules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,                -- NULL = all shared categories
    shares_json TEXT NOT NULL,    -- {"program_id": basis_points}; must sum to 10000
    note TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    file_type TEXT NOT NULL,
    sheet_name TEXT,
    sheets_json TEXT NOT NULL DEFAULT '[]',
    header_row INTEGER NOT NULL DEFAULT 1,
    mapping_json TEXT NOT NULL DEFAULT '{}',
    options_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded','validated','committed','reversed','discarded')),
    summary_json TEXT NOT NULL DEFAULT '{}',
    origin TEXT NOT NULL DEFAULT 'import',
    created_at TEXT NOT NULL,
    committed_at TEXT,
    reversed_at TEXT,
    reverse_reason TEXT
);

CREATE TABLE import_rows (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    sheet_row INTEGER NOT NULL,       -- 1-based row number in the source file
    raw_json TEXT NOT NULL,           -- original cell values, as text
    parsed_json TEXT,
    issues_json TEXT NOT NULL DEFAULT '[]',
    suggestion_json TEXT NOT NULL DEFAULT '{}',
    decision TEXT NOT NULL DEFAULT 'include' CHECK (decision IN ('include','skip')),
    UNIQUE (batch_id, sheet_row)
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER REFERENCES import_batches(id),
    source_row INTEGER,
    txn_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('outflow','inflow')),
    kind TEXT NOT NULL DEFAULT 'operating' CHECK (kind IN ('operating','refund','financing','transfer')),
    counterparty TEXT,
    description TEXT,
    category TEXT,
    program_id INTEGER REFERENCES programs(id),
    milestone_id INTEGER REFERENCES milestones(id),
    allocation TEXT NOT NULL DEFAULT 'unallocated' CHECK (allocation IN ('direct','shared','unallocated')),
    legal_entity TEXT,
    account_id INTEGER REFERENCES cash_accounts(id),
    commitment_id INTEGER,
    original_json TEXT NOT NULL DEFAULT '{}',
    dedupe_hash TEXT NOT NULL,
    reversed INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'import',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_txn_date ON transactions(txn_date);
CREATE INDEX idx_txn_hash ON transactions(dedupe_hash);

CREATE TABLE commitments (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),
    milestone_id INTEGER REFERENCES milestones(id),
    category TEXT,
    counterparty TEXT NOT NULL,
    description TEXT,
    currency TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    expected_payment_date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','paid','cancelled')),
    paid_transaction_id INTEGER REFERENCES transactions(id),
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

-- Expected future inflows/outflows outside budgets (e.g. confirmed grant).
CREATE TABLE planned_flows (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    flow_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('outflow','inflow')),
    kind TEXT NOT NULL DEFAULT 'operating' CHECK (kind IN ('operating','financing')),
    certainty TEXT NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('confirmed','hypothetical')),
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

CREATE TABLE scenarios (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'custom' CHECK (kind IN ('base','accelerated','conservative','custom')),
    description TEXT,
    assumptions_json TEXT NOT NULL DEFAULT '{}',
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ------------------------------------------------------------- intelligence
CREATE TABLE competitors (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),
    company TEXT NOT NULL,
    product TEXT,
    species_json TEXT NOT NULL DEFAULT '[]',
    indication TEXT,
    mechanism TEXT,
    modality TEXT,
    geography TEXT,
    stage TEXT,
    status TEXT NOT NULL DEFAULT 'tracked' CHECK (status IN ('tracked','suggested','dismissed')),
    match_reason TEXT,
    source_url TEXT,
    notes TEXT,
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE intel_events (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),
    competitor_id INTEGER REFERENCES competitors(id),
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    observed TEXT NOT NULL,             -- what the source reports
    interpretation TEXT,                -- AI interpretation
    possible_next_move TEXT,            -- labeled hypothesis
    suggested_action TEXT,              -- for internal review
    relevance INTEGER NOT NULL DEFAULT 0,
    relevance_reason TEXT,
    source_name TEXT,
    source_url TEXT NOT NULL,
    published_at TEXT,
    event_date TEXT,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    duplicate_of INTEGER REFERENCES intel_events(id),
    change_note TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    agent_run_id INTEGER,
    origin TEXT NOT NULL DEFAULT 'agent',  -- 'agent' (live), 'fixture' (demo), 'user'
    UNIQUE (program_id, dedupe_key)
);

CREATE TABLE actions (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    detail TEXT,
    program_id INTEGER REFERENCES programs(id),
    source_type TEXT,
    source_id INTEGER,
    owner TEXT,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','open','done','dismissed')),
    created_by TEXT NOT NULL DEFAULT 'user',
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE briefings (
    id INTEGER PRIMARY KEY,
    briefing_date TEXT NOT NULL,       -- local date in configured timezone
    timezone TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'fresh' CHECK (status IN ('fresh','partial','failed')),
    items_json TEXT NOT NULL DEFAULT '[]',
    ranking_rule TEXT NOT NULL,
    coverage_json TEXT NOT NULL DEFAULT '{}',
    agent_run_id INTEGER,
    origin TEXT NOT NULL DEFAULT 'agent'
);

CREATE TABLE briefing_views (
    viewer TEXT NOT NULL,
    briefing_date TEXT NOT NULL,
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (viewer, briefing_date)
);

CREATE TABLE regulatory_sources (
    id INTEGER PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    authority TEXT NOT NULL,
    scope TEXT NOT NULL,               -- human_drug, human_biologic, vet_drug, vet_biologic
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    access TEXT NOT NULL,              -- api, index_page, manual_only
    language TEXT NOT NULL DEFAULT 'en',
    notes TEXT,
    last_checked_at TEXT,
    last_success_at TEXT,
    last_status TEXT,
    last_error TEXT,
    UNIQUE (jurisdiction, scope, url)
);

CREATE TABLE regulatory_documents (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES regulatory_sources(id),
    jurisdiction TEXT NOT NULL,
    authority TEXT NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    language TEXT NOT NULL DEFAULT 'en',
    url TEXT NOT NULL,
    product_scope TEXT,
    species_json TEXT NOT NULL DEFAULT '[]',
    published_date TEXT,
    revised_date TEXT,
    effective_date TEXT,
    doc_status TEXT NOT NULL DEFAULT 'unknown' CHECK (doc_status IN ('draft','final','superseded','unknown')),
    binding TEXT NOT NULL DEFAULT 'unknown' CHECK (binding IN ('binding','guidance','unknown')),
    topics_json TEXT NOT NULL DEFAULT '[]',
    retrieved_at TEXT NOT NULL,
    content_hash TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    previous_hash TEXT,
    changed_at TEXT,
    origin TEXT NOT NULL DEFAULT 'agent',
    UNIQUE (url)
);

CREATE TABLE regulatory_assessments (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES regulatory_documents(id),
    program_id INTEGER NOT NULL REFERENCES programs(id),
    relevance INTEGER NOT NULL DEFAULT 0,
    summary_en TEXT,                   -- AI summary (and translation if non-English)
    is_translation INTEGER NOT NULL DEFAULT 0,
    passages_json TEXT NOT NULL DEFAULT '[]',   -- verbatim excerpts with section refs
    applicability TEXT,
    unresolved_json TEXT NOT NULL DEFAULT '[]',
    affected_milestones_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'needs_review' CHECK (review_status IN ('needs_review','reviewed','not_applicable')),
    agent_run_id INTEGER,
    origin TEXT NOT NULL DEFAULT 'agent',
    created_at TEXT NOT NULL,
    UNIQUE (document_id, program_id)
);

CREATE TABLE market_observations (
    id INTEGER PRIMARY KEY,
    market_definition TEXT NOT NULL,
    indication TEXT,
    species TEXT,
    geography TEXT NOT NULL,
    product_category TEXT,
    period TEXT NOT NULL,
    metric TEXT NOT NULL CHECK (metric IN ('revenue','units','market_share','market_size')),
    company TEXT,
    segment TEXT,
    value TEXT NOT NULL,          -- decimal string
    unit TEXT,                    -- e.g. 'USD millions', '%'
    currency TEXT,
    value_type TEXT NOT NULL CHECK (value_type IN ('reported','estimated','sample')),
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    coverage_note TEXT,
    origin TEXT NOT NULL DEFAULT 'agent',
    UNIQUE (market_definition, period, metric, company, segment, source_url)
);

CREATE TABLE partner_candidates (
    id INTEGER PRIMARY KEY,
    program_id INTEGER REFERENCES programs(id),
    company TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',   -- [{criterion, fact, source_url, source_name, retrieved_at}]
    criteria_json TEXT NOT NULL DEFAULT '{}',   -- {criterion: score 0-3} deterministic from evidence
    fit_score INTEGER NOT NULL DEFAULT 0,
    ai_assessment TEXT,
    gaps_json TEXT NOT NULL DEFAULT '[]',
    agent_run_id INTEGER,
    origin TEXT NOT NULL DEFAULT 'agent',
    updated_at TEXT NOT NULL,
    UNIQUE (program_id, company)
);

-- ------------------------------------------------------- jobs and agent runs
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled','partial')),
    params_json TEXT NOT NULL DEFAULT '{}',
    progress TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE agent_runs (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs(id),
    mode TEXT NOT NULL,              -- live | demo | test
    provider TEXT,
    model TEXT,
    started_at TEXT NOT NULL,
    duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    requests INTEGER,
    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_tokens INTEGER,
    tool_calls INTEGER,
    app_cache_hits INTEGER NOT NULL DEFAULT 0,
    app_cache_misses INTEGER NOT NULL DEFAULT 0,
    cost_usd TEXT,                   -- NULL = unknown
    pricing_version TEXT,
    trace_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    prompt_version TEXT
);
CREATE INDEX idx_agent_runs_started ON agent_runs(started_at);
