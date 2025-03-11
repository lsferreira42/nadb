CREATE TABLE metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    key TEXT NOT NULL,
    db TEXT NOT NULL,
    namespace TEXT NOT NULL,
    created_at DATETIME DEFAULT NULL,
    last_updated DATETIME DEFAULT NULL,
    last_accessed DATETIME DEFAULT NULL,
    size INTEGER DEFAULT NULL,
    ttl INTEGER DEFAULT NULL,
    UNIQUE (path, key, db, namespace)
);


-- Tags Table
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_name TEXT NOT NULL UNIQUE
);

-- Linking Table
CREATE TABLE metadata_tags (
    metadata_id INTEGER,
    tag_id INTEGER,
    PRIMARY KEY (metadata_id, tag_id),
    FOREIGN KEY (metadata_id) REFERENCES metadata(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

