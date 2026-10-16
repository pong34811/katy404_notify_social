import sqlite3

import pytest
from django.core.management import CommandError, call_command


def test_database_backup_is_consistent_and_exclusive(tmp_path):
    from social.management.commands.backup_state import backup_database

    source, destination = tmp_path / "source.sqlite3", tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as con:
        con.execute("CREATE TABLE sample (value TEXT)")
        con.execute("INSERT INTO sample VALUES (?)", ("kept",))
    backup_database(source, destination)
    with sqlite3.connect(destination) as con:
        assert con.execute("SELECT value FROM sample").fetchall() == [("kept",)]
    with pytest.raises(ValueError):
        backup_database(source, destination)


def test_backup_rejects_media_directory(settings, tmp_path):
    settings.BASE_DIR = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    with pytest.raises(CommandError):
        call_command("backup_state", output=str(settings.MEDIA_ROOT))
    assert not settings.MEDIA_ROOT.exists()
