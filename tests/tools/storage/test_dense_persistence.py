"""Dense memory must actually survive a restart.

These cover the regression where every backend was handed the same
``config.memory.db_path``: DenseMemory tried to JSON-parse the SQLite database
that sqlite.py had created there, failed on the file header, and silently began
empty on every startup -- so "memory is persistent" was not true. The first
save would then have written JSON over that SQLite file.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from orion.tools.storage.dense import DenseMemory
from orion.tools.storage.embeddings import Embedder


class StubEmbedder(Embedder):
    """Deterministic, dependency-free embeddings so tests never need Ollama."""

    DIM = 8

    def embed(self, texts):
        out = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            for j, ch in enumerate(t[: self.DIM]):
                out[i, j] = (ord(ch) % 17) / 17.0
            if not out[i].any():
                out[i, 0] = 1.0
        return out

    def dim(self) -> int:
        return self.DIM


def _make(db_path: Path) -> DenseMemory:
    return DenseMemory(embedder=StubEmbedder(), db_path=db_path)


def _sqlite_at(path: Path) -> None:
    """Write a real SQLite database, as the keyword backend would."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO documents VALUES ('a', 'hello')")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# The actual bug
# ---------------------------------------------------------------------------


def test_sqlite_db_at_db_path_is_not_parsed_as_json(tmp_path, caplog):
    """A SQLite file where db_path points must not raise or blank the index."""
    db = tmp_path / "memory.db"
    _sqlite_at(db)

    mem = _make(db)  # must not raise

    assert mem._contents == []
    assert "UnicodeDecodeError" not in caplog.text


def test_sqlite_db_at_db_path_is_never_overwritten(tmp_path):
    """The old code would have written JSON over the keyword backend's DB."""
    db = tmp_path / "memory.db"
    _sqlite_at(db)
    before = db.read_bytes()

    mem = _make(db)
    mem.store("orion remembers this", source="test")

    assert db.read_bytes() == before, "the SQLite database was modified"
    # And it is still a usable database.
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    conn.close()


def test_dense_writes_to_its_own_sidecar(tmp_path):
    db = tmp_path / "memory.db"
    _sqlite_at(db)

    mem = _make(db)
    mem.store("a fact worth keeping")

    assert (tmp_path / "memory.dense.json").exists()
    assert (tmp_path / "memory.dense.npz").exists()


# ---------------------------------------------------------------------------
# The claim: it remembers
# ---------------------------------------------------------------------------


def test_documents_survive_a_restart(tmp_path):
    db = tmp_path / "memory.db"

    first = _make(db)
    first.store("the user's name is Alex", source="chat")
    first.store("orion runs locally", source="chat")

    second = _make(db)  # simulates the next backend start
    assert len(second._contents) == 2
    assert "the user's name is Alex" in second._contents
    assert second._matrix is not None
    assert second._matrix.shape[0] == 2


def test_restored_index_is_searchable(tmp_path):
    db = tmp_path / "memory.db"
    first = _make(db)
    first.store("orion runs entirely on your own machine")

    second = _make(db)
    results = second.retrieve("orion runs entirely on your own machine", top_k=1)
    assert results, "a restored index returned no results"


def test_restart_survives_alongside_a_sqlite_file(tmp_path):
    """Both backends can own the same configured path without collision."""
    db = tmp_path / "memory.db"
    _sqlite_at(db)

    first = _make(db)
    first.store("persisted next to a sqlite db")

    second = _make(db)
    assert len(second._contents) == 1


# ---------------------------------------------------------------------------
# Migration and durability
# ---------------------------------------------------------------------------


def test_legacy_json_at_db_path_is_migrated(tmp_path):
    """Older builds wrote the metadata straight to db_path; adopt it."""
    db = tmp_path / "memory.db"
    payload = {
        "contents": ["legacy entry"],
        "sources": ["old"],
        "metadatas": [{}],
        "doc_ids": ["id-1"],
    }
    db.write_text(json.dumps(payload), encoding="utf-8")

    mem = _make(db)

    assert mem._contents == ["legacy entry"]
    assert (tmp_path / "memory.dense.json").exists()
    assert not db.exists(), "the legacy file should have been moved, not copied"


def test_json_db_path_is_used_directly(tmp_path):
    """A db_path that is already .json stays exactly where it is."""
    db = tmp_path / "index.json"
    mem = _make(db)
    mem.store("kept in place")
    assert db.exists()
    assert not (tmp_path / "index.dense.json").exists()


def test_corrupt_index_starts_empty_without_deleting_it(tmp_path, caplog):
    db = tmp_path / "memory.db"
    meta = tmp_path / "memory.dense.json"
    meta.write_text("{ this is not valid json", encoding="utf-8")

    mem = _make(db)

    assert mem._contents == []
    assert meta.exists(), "a corrupt index must be left on disk for recovery"


def test_no_temp_files_survive_a_save(tmp_path):
    """Saves go through a temp file and rename; nothing should be left behind."""
    db = tmp_path / "memory.db"
    mem = _make(db)
    mem.store("atomic write check")

    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_first_run_is_silent(tmp_path, caplog):
    """No persisted file yet is the normal case, not a warning."""
    import logging

    caplog.set_level(logging.WARNING)
    _make(tmp_path / "memory.db")
    assert "starting empty" not in caplog.text
