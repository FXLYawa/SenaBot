-- Context keeps full history; active entries/summaries are reconstructed on read.
CREATE TABLE context_sessions (
    session_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(session_id)) > 0),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
    platform TEXT,
    account_namespace TEXT,
    scene_type TEXT,
    scene_id TEXT,
    work_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    latest_sequence INTEGER NOT NULL DEFAULT 0 CHECK (latest_sequence >= 0),
    CHECK (
        (purpose = 'conversation' AND work_id IS NULL
         AND platform IS NOT NULL AND length(trim(platform)) > 0
         AND account_namespace IS NOT NULL AND length(trim(account_namespace)) > 0
         AND scene_type IS NOT NULL AND length(trim(scene_type)) > 0
         AND scene_id IS NOT NULL AND length(trim(scene_id)) > 0)
        OR
        (purpose <> 'conversation' AND work_id IS NOT NULL AND length(trim(work_id)) > 0
         AND platform IS NULL AND account_namespace IS NULL
         AND scene_type IS NULL AND scene_id IS NULL)
    )
);
CREATE UNIQUE INDEX context_conversation_identity
    ON context_sessions(account_namespace, platform, scene_type, scene_id)
    WHERE purpose = 'conversation';
CREATE UNIQUE INDEX context_work_identity
    ON context_sessions(purpose, work_id) WHERE purpose <> 'conversation';

CREATE TABLE context_entries (
    entry_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(entry_id)) > 0),
    session_id TEXT NOT NULL REFERENCES context_sessions(session_id),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    entry_type TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'sena', 'system', 'tool', 'extension')),
    actor_id TEXT NOT NULL,
    actor_display_name TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL CHECK (json_valid(content_json) AND json_type(content_json) = 'object'),
    source_event_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, sequence)
);
CREATE INDEX context_entries_source ON context_entries(source_event_id);

CREATE TABLE context_summaries (
    summary_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(summary_id)) > 0),
    session_id TEXT NOT NULL REFERENCES context_sessions(session_id),
    level INTEGER NOT NULL CHECK (level >= 1),
    first_sequence INTEGER NOT NULL CHECK (first_sequence >= 1),
    last_sequence INTEGER NOT NULL CHECK (last_sequence >= first_sequence),
    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
    created_at TEXT NOT NULL
);
CREATE INDEX context_summaries_range
    ON context_summaries(session_id, first_sequence, last_sequence);

CREATE TABLE context_summary_sources (
    parent_summary_id TEXT NOT NULL REFERENCES context_summaries(summary_id),
    child_summary_id TEXT NOT NULL REFERENCES context_summaries(summary_id),
    position INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (parent_summary_id, child_summary_id),
    UNIQUE (parent_summary_id, position),
    CHECK (parent_summary_id <> child_summary_id)
);
CREATE INDEX context_summary_sources_child ON context_summary_sources(child_summary_id);

-- Provenance is stored separately and reconstructed into the domain payload.
CREATE TABLE memory_items (
    item_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(item_id)) > 0),
    memory_space_id TEXT NOT NULL CHECK (length(trim(memory_space_id)) > 0),
    domain TEXT NOT NULL CHECK (domain IN ('fact', 'experience', 'understanding', 'knowledge')),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
    recorded_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    CHECK (domain = 'fact' OR (valid_from IS NULL AND valid_to IS NULL)),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to)
);
CREATE INDEX memory_items_space_domain ON memory_items(memory_space_id, domain);

CREATE TABLE memory_scopes (
    item_id TEXT NOT NULL REFERENCES memory_items(item_id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('global', 'user', 'group', 'session')),
    scope_id TEXT,
    CHECK ((scope_kind = 'global' AND scope_id IS NULL)
        OR (scope_kind <> 'global' AND scope_id IS NOT NULL AND length(trim(scope_id)) > 0))
);
CREATE UNIQUE INDEX memory_scopes_global ON memory_scopes(item_id) WHERE scope_kind = 'global';
CREATE UNIQUE INDEX memory_scopes_scoped
    ON memory_scopes(item_id, scope_kind, scope_id) WHERE scope_kind <> 'global';
CREATE INDEX memory_scopes_lookup ON memory_scopes(scope_kind, scope_id, item_id);

CREATE TABLE memory_provenances (
    item_id TEXT NOT NULL REFERENCES memory_items(item_id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    source_type TEXT NOT NULL CHECK (length(trim(source_type)) > 0),
    source_id TEXT NOT NULL CHECK (length(trim(source_id)) > 0),
    PRIMARY KEY (item_id, position)
);
CREATE INDEX memory_provenances_source ON memory_provenances(source_type, source_id);

CREATE TABLE memory_replacements (
    previous_item_id TEXT PRIMARY KEY NOT NULL REFERENCES memory_items(item_id),
    replacement_item_id TEXT NOT NULL REFERENCES memory_items(item_id),
    operation_id TEXT NOT NULL CHECK (length(trim(operation_id)) > 0),
    CHECK (previous_item_id <> replacement_item_id)
);
CREATE INDEX memory_replacements_new ON memory_replacements(replacement_item_id);

CREATE TABLE memory_embeddings (
    embedding_id INTEGER PRIMARY KEY,
    item_id TEXT NOT NULL UNIQUE REFERENCES memory_items(item_id),
    model TEXT NOT NULL CHECK (length(trim(model)) > 0),
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    created_at TEXT NOT NULL
);
-- memory_vectors is created separately once the configured dimension is known.
