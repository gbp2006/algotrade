-- Схема индекса корня /mnt/DiskD/opencode
-- Читается db/memory.py при сборке; база производная — можно удалять и пересобирать.
-- Текст хранится ОДИН раз (в chunk); FTS-таблицы — external content.

PRAGMA page_size = 4096;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Документ = один md-файл корпуса
CREATE TABLE doc (
    id       INTEGER PRIMARY KEY,
    path     TEXT NOT NULL UNIQUE,   -- относительно корня
    project  TEXT NOT NULL,          -- папка проекта или 'root'
    kind     TEXT NOT NULL,          -- notes | dialogs | doc | root
    title    TEXT,                   -- первый H1
    size     INTEGER,
    mtime    INTEGER,
    hash     TEXT,
    nchunks  INTEGER DEFAULT 0
);
CREATE INDEX doc_project ON doc(project);
CREATE INDEX doc_kind ON doc(kind);

-- Фрагмент = секция под заголовком (или её часть, если секция длинная)
CREATE TABLE chunk (
    id       INTEGER PRIMARY KEY,
    doc_id   INTEGER NOT NULL REFERENCES doc(id) ON DELETE CASCADE,
    seq      INTEGER NOT NULL,
    heading  TEXT,                   -- путь заголовков: "H1 > H2 > H3"
    line     INTEGER NOT NULL,       -- первая строка фрагмента (1-based)
    end_line INTEGER,
    body     TEXT NOT NULL
);
CREATE INDEX chunk_doc ON chunk(doc_id);

-- Основной полнотекстовый индекс: слова + префиксы (bm25)
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    body,
    heading,
    content = 'chunk',
    content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '2 3 4'
);

-- Второй индекс: триграммы — подстрочный поиск, обход русской морфологии
CREATE VIRTUAL TABLE chunk_tri USING fts5(
    body,
    content = 'chunk',
    content_rowid = 'id',
    tokenize = 'trigram remove_diacritics 1'
);

-- Карточки проектов (из INDEX.md + файловой системы)
CREATE TABLE project (
    name          TEXT PRIMARY KEY,  -- имя папки; 'root' для корневых файлов
    title         TEXT,
    summary       TEXT,              -- описание из INDEX.md
    status        TEXT,              -- статус из INDEX.md
    status_notes  TEXT,              -- статус из последней записи «Конец:» в notes.md
    summary_notes TEXT,              -- её текст (первая фраза) — «правда файлов»
    entities      TEXT,
    started       TEXT,              -- YYYY-MM-DD из имени папки
    updated       TEXT,              -- YYYY-MM-DD по mtime файлов
    ndocs         INTEGER,
    nchunks       INTEGER
);

-- Указатель сущностей: адреса, домены, пути, юниты и т.п.
CREATE TABLE entity (
    id       INTEGER PRIMARY KEY,
    kind     TEXT NOT NULL,          -- ipv4 | ipv6 | domain | email | url | path | unit
    value    TEXT NOT NULL,
    chunk_id INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE
);
CREATE INDEX entity_value ON entity(value);
CREATE INDEX entity_kind_value ON entity(kind, value);

-- События из заголовков вида "14:10 — ..." / "17.11 00:41 — ..."
CREATE TABLE event (
    id       INTEGER PRIMARY KEY,
    date     TEXT,                   -- YYYY-MM-DD
    time     TEXT,                   -- HH:MM
    title    TEXT,
    project  TEXT,
    chunk_id INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE
);
CREATE INDEX event_date ON event(date);
CREATE INDEX event_project ON event(project, date);
