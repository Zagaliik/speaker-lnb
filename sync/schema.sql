CREATE TABLE IF NOT EXISTS etat (
  cle     TEXT PRIMARY KEY,
  rev     INTEGER NOT NULL,
  updated TEXT    NOT NULL,
  device  TEXT,
  data    TEXT    NOT NULL
);
