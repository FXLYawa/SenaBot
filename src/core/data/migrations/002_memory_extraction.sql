-- One continuous extraction checkpoint per memory space and source session.
CREATE TABLE memory_extraction_progress (
    memory_space_id TEXT NOT NULL CHECK (length(trim(memory_space_id)) > 0),
    session_id TEXT NOT NULL REFERENCES context_sessions(session_id),
    processed_through_sequence INTEGER NOT NULL CHECK (processed_through_sequence >= 0),
    PRIMARY KEY (memory_space_id, session_id)
);
