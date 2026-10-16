"""Local interprocess lock shared by workers and publication-sensitive Admin writes."""

from django.conf import settings
from filelock import FileLock


def worker_lock():
    directory = settings.BASE_DIR / ".runtime"
    directory.mkdir(parents=True, exist_ok=True)
    return FileLock(str(directory / "social.lock"), timeout=0)
