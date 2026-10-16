"""Back up during maintenance with the Admin web process stopped."""

import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from filelock import Timeout

from social.locking import worker_lock


def backup_database(source: Path, destination: Path):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or destination.exists():
        raise ValueError("invalid_backup_path")
    # Reserve exclusively, preventing an overwrite race.
    with destination.open("xb"):
        pass
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


class Command(BaseCommand):
    help = "Back up SQLite and originals. Stop Admin and schedulers first."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        destination = Path(options["output"]).resolve()
        root, media = settings.BASE_DIR.resolve(), settings.MEDIA_ROOT.resolve()
        if (
            destination in {root, media}
            or media in destination.parents
            or destination in root.parents
        ):
            raise CommandError("invalid_backup_directory")
        try:
            with worker_lock():
                destination.mkdir(parents=True, exist_ok=False)
                source = Path(settings.DATABASES["default"]["NAME"]).resolve()
                backup_database(source, destination / "db.sqlite3")
                if media.exists():
                    shutil.copytree(media, destination / "media")
        except Timeout:
            raise CommandError("worker_busy") from None
        except (OSError, ValueError, sqlite3.Error):
            raise CommandError("backup_failed_incomplete_directory_must_not_be_used") from None
        self.stdout.write("backup_complete")
