import pytest
from filelock import Timeout


def test_second_worker_cannot_enter(settings, tmp_path):
    from social.locking import worker_lock

    settings.BASE_DIR = tmp_path
    with worker_lock():
        with pytest.raises(Timeout):
            with worker_lock():
                pass
