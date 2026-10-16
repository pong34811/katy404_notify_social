import pytest
from django.conf import settings
from django.urls import Resolver404, resolve


def test_local_safe_settings():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert settings.DATABASES["default"]["OPTIONS"]["timeout"] == 30
    assert settings.TIME_ZONE == "Asia/Bangkok"
    assert "social" in settings.INSTALLED_APPS
    assert settings.MEDIA_ROOT.name == "media"
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE
    with pytest.raises(Resolver404):
        resolve("/private-media/original.mp4")
