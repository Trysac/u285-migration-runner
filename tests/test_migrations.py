"""Tests for migration_runner."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from migration_runner import (
    LockError,
    MigrationError,
    MigrationStatus,
    Migrator,
    load_migrations,
)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def write_migration(
    directory: Path,
    version: int,
    name: str,
    sql: str = "SELECT 1;",
    newline: str = "\n",
) -> Path:
    path = directory / f"V{version}__{name}.sql"
    path.write_text(sql.replace("\n", newline), encoding="utf-8")
    return path


def make_conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:", isolation_level=None)


def test_load_migrations_basic(tmp_path: Path) -> None:
    (tmp_path / "V1__init.sql").write_text("CREATE TABLE t (id);", encoding="utf-8")
    (tmp_path / "V2__add_email.sql").write_text("ALTER TABLE t ADD email;", encoding="utf-8")
    (tmp_path / "V10__idx.sql").write_text("CREATE INDEX idx ON t(id);", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    migrations = load_migrations(tmp_path)
    assert [m.version for m in migrations] == [1, 2, 10]
    assert [m.name for m in migrations] == ["init", "add_email", "idx"]


def test_load_migrations_invalid_name(tmp_path: Path) -> None:
    (tmp_path / "v1_bad.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError) as excinfo:
        load_migrations(tmp_path)
    assert excinfo.value.code == "invalid_name"


def test_load_migrations_duplicate_version(tmp_path: Path) -> None:
    write_migration(tmp_path, 2, "a")
    write_migration(tmp_path, 2, "b")
    with pytest.raises(MigrationError) as excinfo:
        load_migrations(tmp_path)
    assert excinfo.value.code == "duplicate_version"
    assert excinfo.value.version == 2


def test_load_migrations_file_too_large(tmp_path: Path) -> None:
    path = tmp_path / "V1__big.sql"
    path.write_text("x" * 1_000_001, encoding="utf-8")
    with pytest.raises(MigrationError) as excinfo:
        load_migrations(tmp_path)
    assert excinfo.value.code == "file_too_large"
    assert excinfo.value.version == 1


def test_load_migrations_too_many_files(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "a")
    write_migration(tmp_path, 2, "b")
    with pytest.raises(MigrationError) as excinfo:
        load_migrations(tmp_path, max_files=1)
    assert excinfo.value.code == "too_many_files"


def test_load_migrations_ignores_non_sql(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    write_migration(tmp_path, 1, "init")
    migrations = load_migrations(tmp_path)
    assert len(migrations) == 1


def test_load_migrations_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_migrations(tmp_path / "missing")


def test_migrate_applies_all_and_records_checksums(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t1 (id);", newline="\r\n")
    write_migration(tmp_path, 2, "add", "ALTER TABLE t1 ADD col;")
    write_migration(tmp_path, 10, "idx", "CREATE INDEX idx ON t1(id);")
    migrations = load_migrations(tmp_path)

    conn = make_conn()
    migrator = Migrator(conn, migrations, owner="a")
    applied = migrator.migrate()
    assert applied == [1, 2, 10]
    assert migrator.migrate() == []

    rows = conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [r[0] for r in rows] == [1, 2, 10]
    assert [r[1] for r in rows] == ["init", "add", "idx"]
    for row, migration in zip(rows, migrations, strict=True):
        expected_checksum = hashlib.sha256(
            migration.sql.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest()
        assert row[2] == expected_checksum


def test_migrate_failure_rolls_back(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(
        tmp_path,
        2,
        "bad",
        "CREATE TABLE a (x);\nINSERT INTO nope VALUES (1);",
    )
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    migrator = Migrator(conn, migrations, owner="a")

    with pytest.raises(MigrationError) as excinfo:
        migrator.migrate()
    assert excinfo.value.code == "migration_failed"
    assert excinfo.value.version == 2

    # table a should not exist because CREATE TABLE was rolled back
    table_a = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='a'"
    ).fetchone()
    assert table_a is None
    # version 1 is applied
    row = conn.execute("SELECT version FROM schema_migrations WHERE version = 1").fetchone()
    assert row is not None
    # lock row is gone
    lock_row = conn.execute("SELECT id FROM schema_migrations_lock WHERE id = 1").fetchone()
    assert lock_row is None


def test_checksum_mismatch_detected(tmp_path: Path) -> None:
    path = write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    Migrator(conn, migrations, owner="a").migrate()

    # a pending migration must not run while a checksum mismatch is detected
    write_migration(tmp_path, 2, "pending", "CREATE TABLE p2 (id);")
    # modify file content
    path.write_text("CREATE TABLE t (id); -- changed", encoding="utf-8")
    new_migrations = load_migrations(tmp_path)
    with pytest.raises(MigrationError) as excinfo:
        Migrator(conn, new_migrations, owner="a").migrate()
    assert excinfo.value.code == "checksum_mismatch"
    assert excinfo.value.version == 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='p2'").fetchone() is None
    assert (
        conn.execute("SELECT version FROM schema_migrations WHERE version = 2").fetchone() is None
    )


def test_line_endings_only_change_does_not_mismatch(tmp_path: Path) -> None:
    write_migration(
        tmp_path, 1, "init", "CREATE TABLE t (id);\nINSERT INTO t VALUES (1);", newline="\n"
    )
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    Migrator(conn, migrations, owner="a").migrate()

    # rewrite with CRLF but same logical content
    path = tmp_path / "V1__init.sql"
    path.write_text(path.read_text(encoding="utf-8").replace("\n", "\r\n"), encoding="utf-8")
    new_migrations = load_migrations(tmp_path)
    Migrator(conn, new_migrations, owner="a").migrate()  # should not raise


def test_lock_held_and_stolen(tmp_path: Path) -> None:
    conn = make_conn()
    # manually create lock table and insert a lock row owned by 'other'
    conn.executescript(
        """
        CREATE TABLE schema_migrations_lock (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            owner TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        INSERT INTO schema_migrations_lock (id, owner, expires_at) VALUES (1, 'other', 1100.0);
        """
    )
    clock = FakeClock(start=1000.0)
    migrator = Migrator(
        conn,
        [],
        owner="a",
        clock=clock,
        on_event=lambda event: events.append(event),
    )
    events: list[dict[str, Any]] = []
    with pytest.raises(LockError) as excinfo:
        migrator.migrate()
    assert excinfo.value.code == "lock_held"
    assert "other" in str(excinfo.value)

    # advance clock past expiry; now should steal lock
    clock.advance(200.0)
    applied = migrator.migrate()
    assert applied == []
    assert {"event": "lock_stolen", "previous_owner": "other"} in events


def test_out_of_order_detection(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(tmp_path, 10, "idx", "CREATE INDEX idx ON t(id);")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    Migrator(conn, migrations, owner="a").migrate()

    # add version 2 after both applied
    write_migration(tmp_path, 2, "late", "ALTER TABLE t ADD col;")
    new_migrations = load_migrations(tmp_path)
    with pytest.raises(MigrationError) as excinfo:
        Migrator(conn, new_migrations, owner="a").migrate()
    assert excinfo.value.code == "out_of_order"
    assert excinfo.value.version == 2

    # with allow_out_of_order=True it succeeds
    applied = Migrator(conn, new_migrations, owner="a", allow_out_of_order=True).migrate()
    assert applied == [2]


def test_target_and_status(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(tmp_path, 2, "add", "ALTER TABLE t ADD col;")
    write_migration(tmp_path, 10, "idx", "CREATE INDEX idx ON t(id);")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    migrator = Migrator(conn, migrations, owner="a")

    applied = migrator.migrate(target=2)
    assert applied == [1, 2]

    statuses = migrator.status()
    assert [s.version for s in statuses] == [1, 2, 10]
    assert [s.state for s in statuses] == ["applied", "applied", "pending"]
    assert statuses[2].name == "idx"


def test_transaction_control_raises(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "bad", "BEGIN; CREATE TABLE t (id);")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    migrator = Migrator(conn, migrations, owner="a")
    with pytest.raises(MigrationError) as excinfo:
        migrator.migrate()
    assert excinfo.value.code == "transaction_in_script"
    assert excinfo.value.version == 1


def test_trigger_body_is_not_transaction_control(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        1,
        "trigger",
        "CREATE TABLE t (a);\nCREATE TRIGGER trg AFTER INSERT ON t BEGIN UPDATE t SET a=1; END;",
    )
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    applied = Migrator(conn, migrations, owner="a").migrate()
    assert applied == [1]


def test_semicolon_inside_string_is_ignored(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        1,
        "strings",
        "CREATE TABLE t (a);\nINSERT INTO t VALUES ('a;BEGIN');",
    )
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    applied = Migrator(conn, migrations, owner="a").migrate()
    assert applied == [1]


def test_comments_do_not_hide_or_fake_transaction_control(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        1,
        "comments",
        "-- BEGIN;\n/* COMMIT; */\nCREATE TABLE t (a);",
    )
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    applied = Migrator(conn, migrations, owner="a").migrate()
    assert applied == [1]

    write_migration(
        tmp_path,
        2,
        "hidden",
        "CREATE TABLE t2 (a);\nINSERT INTO t VALUES ('a--b'); BEGIN;",
    )
    hidden_migrations = load_migrations(tmp_path)
    with pytest.raises(MigrationError) as excinfo:
        Migrator(conn, hidden_migrations, owner="a").migrate()
    assert excinfo.value.code == "transaction_in_script"
    assert excinfo.value.version == 2


def test_missing_file_status(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(tmp_path, 2, "add", "ALTER TABLE t ADD col;")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    Migrator(conn, migrations, owner="a").migrate()

    # remove V1 file from disk; create new Migrator with only V2
    (tmp_path / "V1__init.sql").unlink()
    remaining_migrations = load_migrations(tmp_path)
    migrator = Migrator(conn, remaining_migrations, owner="a")
    statuses = migrator.status()
    assert statuses[0] == MigrationStatus(1, "init", "missing_file")
    assert statuses[1] == MigrationStatus(2, "add", "applied")

    # migrate should still run pending migrations (none here)
    applied = migrator.migrate()
    assert applied == []


def test_empty_migration_file(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "empty", "")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    applied = Migrator(conn, migrations, owner="a").migrate()
    assert applied == [1]
    row = conn.execute("SELECT version, name FROM schema_migrations WHERE version = 1").fetchone()
    assert row == (1, "empty")


def test_two_migrators_same_database(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    conn1 = sqlite3.connect(db_path, isolation_level=None)
    conn2 = sqlite3.connect(db_path, isolation_level=None)
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    migrations = load_migrations(tmp_path)

    # acqure lock on conn1 manually by inserting lock row
    conn1.executescript(
        """
        CREATE TABLE schema_migrations_lock (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            owner TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        INSERT INTO schema_migrations_lock (id, owner, expires_at) VALUES (1, 'a', 9999999999);
        """
    )
    # now second migrator should fail with lock_held
    with pytest.raises(LockError):
        Migrator(conn2, migrations, owner="b").migrate()


def test_lock_released_after_failure(tmp_path: Path) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(tmp_path, 2, "bad", "INSERT INTO nope VALUES (1);")
    migrations = load_migrations(tmp_path)
    conn = make_conn()
    migrator = Migrator(conn, migrations, owner="a")
    with pytest.raises(MigrationError):
        migrator.migrate()
    # lock row should be gone
    lock_row = conn.execute("SELECT id FROM schema_migrations_lock WHERE id = 1").fetchone()
    assert lock_row is None


def test_cli_migrate_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(tmp_path, 2, "add", "ALTER TABLE t ADD col;")
    db_path = tmp_path / "app.db"
    from migration_runner.__main__ import main

    rc = main(["migrate", "--db", str(db_path), "--dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "applied 1 init" in captured.out
    assert "applied 2 add" in captured.out


def test_cli_status_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    write_migration(tmp_path, 10, "idx", "CREATE INDEX idx ON t(id);")
    db_path = tmp_path / "app.db"
    from migration_runner.__main__ import main

    # apply only version 1 first
    main(["migrate", "--db", str(db_path), "--dir", str(tmp_path), "--target", "1"])
    capsys.readouterr()  # clear
    rc = main(["status", "--db", str(db_path), "--dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "applied 1 init" in captured.out
    assert "pending 10 idx" in captured.out


def test_cli_plan_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_migration(tmp_path, 1, "init", "CREATE TABLE t (id);")
    db_path = tmp_path / "app.db"
    from migration_runner.__main__ import main

    rc = main(["plan", "--db", str(db_path), "--dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "pending 1 init" in captured.out


def test_cli_failed_migration_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_migration(tmp_path, 1, "bad", "INSERT INTO nope VALUES (1);")
    db_path = tmp_path / "app.db"
    from migration_runner.__main__ import main

    rc = main(["migrate", "--db", str(db_path), "--dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err


def test_cli_missing_db_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_migration(tmp_path, 1, "init")
    from migration_runner.__main__ import main

    rc = main(["migrate", "--dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "usage" in captured.err.lower()


def test_cli_invalid_name_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "v1_bad.sql").write_text("SELECT 1;", encoding="utf-8")
    db_path = tmp_path / "app.db"
    from migration_runner.__main__ import main

    rc = main(["migrate", "--db", str(db_path), "--dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err


def test_cli_io_error_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "app.db"
    from migration_runner.__main__ import main

    rc = main(["migrate", "--db", str(db_path), "--dir", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert rc == 2
    assert "error:" in captured.err
