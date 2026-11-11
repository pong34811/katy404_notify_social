"""Queue unnotified landscape videos as Page photo posts."""

from concurrent.futures import ThreadPoolExecutor
import os

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone
from filelock import Timeout

from social import downloader
from social.locking import worker_lock
from social.media import route_for_geometry
from social.models import Page, PublishJob, Video
from social.notifications import valid_thumbnail_url
from social.services import duplicate_notification_video_ids, prepare_video


class Command(BaseCommand):
    help = "Verify unnotified clip dimensions and queue unique landscape clips as photo posts."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-apply", action="store_true")

    def handle(self, *args, **options):
        if os.getenv("LIVE_PUBLISH", "0") != "1":
            raise CommandError("live_publish_disabled")
        if not options["confirm_apply"]:
            raise CommandError("confirm_apply_required")

        duplicate_count = converted = queued = not_landscape = metadata_failed = thumbnail_missing = 0
        try:
            with worker_lock():
                page = Page.objects.get(pk=1)
                if not page.auto_publish or not page.post_photo:
                    raise CommandError("page_photo_publish_gate_closed")
                duplicates = duplicate_notification_video_ids(page)
                candidates = Video.objects.filter(
                    Q(baseline=True) | Q(state=Video.State.WAITING_FILE),
                    channel__page=page,
                    channel__enabled=True,
                    channel__ownership_confirmed=True,
                    available=True,
                    media_error="",
                    publishjob__isnull=True,
                ).select_related("channel").order_by("first_seen_at", "video_id")

                candidate_list = list(candidates)
                unique_candidates = [v for v in candidate_list if v.video_id not in duplicates]
                duplicate_count = len(candidate_list) - len(unique_candidates)

                def inspect(video):
                    try:
                        return route_for_geometry(*downloader.info(video.video_id)), False
                    except Exception:
                        return "skip", True

                with ThreadPoolExecutor(max_workers=4) as pool:
                    routes = list(pool.map(inspect, unique_candidates))

                for video, (route, failed) in zip(unique_candidates, routes):
                    if failed:
                        metadata_failed += 1
                        continue
                    if route != "photo":
                        video.media_error = "not_landscape"
                        video.save(update_fields=["media_error"])
                        not_landscape += 1
                        continue
                    if not valid_thumbnail_url(video.thumbnail_url):
                        thumbnail_missing += 1
                        continue

                    video.baseline = False
                    video.landscape_confirmed = True
                    video.rights_confirmed = True
                    video.state = Video.State.WAITING_FILE
                    video.prepared_at = timezone.now()
                    video.save(
                        update_fields=[
                            "baseline",
                            "landscape_confirmed",
                            "rights_confirmed",
                            "state",
                            "prepared_at",
                        ]
                    )
                    converted += 1
                    prepare_video(video)
                    if PublishJob.objects.filter(
                        video=video, page=page, kind=PublishJob.Kind.PHOTO
                    ).exists():
                        queued += 1
        except Timeout:
            raise CommandError("worker_busy") from None
        except Page.DoesNotExist:
            raise CommandError("page_not_found") from None

        self.stdout.write(
            " ".join(
                [
                    f"converted={converted}",
                    f"queued={queued}",
                    f"duplicate_skipped={duplicate_count}",
                    f"not_landscape={not_landscape}",
                    f"metadata_failed={metadata_failed}",
                    f"thumbnail_missing={thumbnail_missing}",
                ]
            )
        )
