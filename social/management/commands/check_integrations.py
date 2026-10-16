"""Read-only identity checks, not a publishing permission guarantee."""

import os

from django.core.management.base import BaseCommand, CommandError

from social.facebook import Facebook
from social.models import Channel, Page
from social.validators import channel_id_validator, token_env_validator
from social.youtube import YouTube


class Command(BaseCommand):
    help = "GET-only integration identity check. Never posts or changes records."

    def handle(self, *args, **options):
        channels = list(Channel.objects.filter(enabled=True, ownership_confirmed=True))
        pages = list(Page.objects.all())
        if not channels or not pages:
            raise CommandError("no_integrations_configured")
        try:
            yt = YouTube(os.getenv("YOUTUBE_API_KEY", ""))
            for channel in channels:
                channel_id_validator(channel.channel_id)
                data = yt._get("channels", part="id", id=channel.channel_id)
                if [item["id"] for item in data.get("items", [])] != [channel.channel_id]:
                    raise ValueError("source_mismatch")
            for page in pages:
                token_env_validator(page.token_env)
                fb = Facebook(
                    page.page_id,
                    os.getenv(page.token_env, ""),
                    os.getenv("FB_GRAPH_VERSION", "v26.0"),
                )
                data = fb._request(
                    "get",
                    f"https://graph.facebook.com/{fb.version}/{page.page_id}",
                    params={"fields": "id,name"},
                    timeout=(10, 60),
                )
                if str(data.get("id")) != page.page_id:
                    raise ValueError("page_mismatch")
        except Exception:
            raise CommandError("preflight_failed_check_credentials_and_permissions") from None
        self.stdout.write("preflight_ok")
