CREATE TABLE deletion_events (
  receipt TEXT PRIMARY KEY,
  received_at TEXT NOT NULL,
  body TEXT NOT NULL
);
