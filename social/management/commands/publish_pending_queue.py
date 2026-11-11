"""Publish a fixed batch of pending vertical videos, one verified post at a time."""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from filelock import Timeout

from social.locking import worker_lock
from social.media import probe, route_for_geometry
from social.models import Page, PublishJob
from social.worker import process_queue

MAX_BATCH = 147
MIN_INTERVAL = 60
BACKUP_RELATIVE = Path(".runtime/backups/facebook-batch-2026-10-21")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_with_hash(source, destination):
    digest = hashlib.sha256()
    size = 0
    with Path(source).open("rb") as src, Path(destination).open("xb") as dst:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


class Command(BaseCommand):
    help = "Preview, back up, or publish a fixed batch of pending vertical Page videos."

    def add_arguments(self, parser):
        parser.add_argument("--page-id", required=True)
        parser.add_argument("--limit", type=int, default=MAX_BATCH)
        parser.add_argument("--interval", type=int, default=MIN_INTERVAL)
        parser.add_argument("--backup", action="store_true")
        parser.add_argument("--publish", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= MAX_BATCH:
            raise CommandError("limit_must_be_1_to_147")
        if options["interval"] < MIN_INTERVAL:
            raise CommandError("interval_must_be_at_least_60_seconds")
        if options["backup"] and options["publish"]:
            raise CommandError("backup_and_publish_are_separate_steps")
        try:
            page = Page.objects.get(page_id=options["page_id"])
        except Page.DoesNotExist:
            raise CommandError("page_not_found") from None

        jobs = self._target_jobs(page, options["limit"], strict=False)
        if not options["backup"] and not options["publish"]:
            self.stdout.write(
                f"preview page={page.page_id} pending={len(jobs)} requested={options['limit']}"
            )
            return

        jobs = self._target_jobs(page, options["limit"], strict=True)
        self._validate_media(jobs)
        if options["backup"]:
            if page.auto_publish:
                raise CommandError("close_page_gate_before_backup")
            self._backup(jobs, page)
            self.stdout.write(f"backup_complete files={len(jobs)}")
            return

        if os.getenv("LIVE_PUBLISH", "0") != "1":
            raise CommandError("live_publish_disabled")
        try:
            if page.auto_publish:
                raise CommandError("page_gate_must_start_closed")
            if not page.post_video:
                raise CommandError("page_video_gate_disabled")
            if not sys.stdin.isatty():
                raise CommandError("interactive_terminal_required_for_first_public_check")
            self._verify_backup(jobs, page)
            self._assert_no_unrelated_verification(jobs)
            self._set_page_gate(page, True)
            self._publish(jobs, page, options["interval"])
        finally:
            try:
                self._set_page_gate(page, False)
            finally:
                self._set_live_gate(False)
        self.stdout.write("publish_gates_closed")

    @staticmethod
    def _target_jobs(page, limit, strict):
        pending = PublishJob.objects.filter(
            page=page,
            kind=PublishJob.Kind.VIDEO,
            state=PublishJob.State.PENDING,
            scheduled_at__isnull=True,
        )
        eligible = pending.filter(
            remote_id="",
            video__baseline=False,
            video__available=True,
            video__state="ready",
            video__inspected_kind="video",
            video__delivery_kind="video",
            video__rights_confirmed=True,
            video__file_matches_video=True,
            video__original__gt="",
            video__channel__page=page,
            video__channel__enabled=True,
            video__channel__ownership_confirmed=True,
        ).select_related("page", "video", "video__channel")
        if strict and (pending.count() != limit or eligible.count() != limit):
            raise CommandError("target_count_or_readiness_mismatch")
        return list(eligible.order_by("created_at", "pk")[:limit])

    @staticmethod
    def _validate_media(jobs):
        for job in jobs:
            try:
                width, height, _ = probe(job.video.original.path)
            except (OSError, ValueError):
                raise CommandError("target_media_invalid") from None
            if height <= width or route_for_geometry(width, height, 1) != "video":
                raise CommandError("target_media_not_vertical_video")

    def _backup(self, jobs, page):
        destination = settings.BASE_DIR / BACKUP_RELATIVE
        backup_root = destination.parent
        backup_root.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise CommandError("backup_destination_exists")
        try:
            destination.resolve().relative_to(backup_root.resolve())
        except ValueError:
            raise CommandError("invalid_backup_directory") from None

        temp = Path(tempfile.mkdtemp(prefix=".facebook-batch-", dir=backup_root))
        entries = []
        try:
            for job in jobs:
                source = Path(job.video.original.path)
                filename = f"{job.pk}-{job.video_id}.mp4"
                size, digest = _copy_with_hash(source, temp / filename)
                if size != source.stat().st_size or _sha256(temp / filename) != digest:
                    raise OSError("backup_verification_failed")
                entries.append(
                    {
                        "job_id": job.pk,
                        "video_id": job.video_id,
                        "filename": filename,
                        "size": size,
                        "sha256": digest,
                    }
                )
            manifest = {
                "page_id": page.page_id,
                "created_at": timezone.now().isoformat(),
                "jobs": entries,
            }
            (temp / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            temp.rename(destination)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise CommandError("backup_failed") from None

    @staticmethod
    def _verify_backup(jobs, page):
        backup = settings.BASE_DIR / BACKUP_RELATIVE
        try:
            manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("page_id") != page.page_id:
                raise ValueError
            entries = {entry["job_id"]: entry for entry in manifest["jobs"]}
            for job in jobs:
                entry = entries[job.pk]
                if entry["video_id"] != job.video_id:
                    raise ValueError
                source = Path(job.video.original.path)
                saved = (backup / entry["filename"]).resolve()
                saved.relative_to(backup.resolve())
                if (
                    source.stat().st_size != entry["size"]
                    or saved.stat().st_size != entry["size"]
                    or _sha256(source) != entry["sha256"]
                    or _sha256(saved) != entry["sha256"]
                ):
                    raise ValueError
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise CommandError("backup_missing_or_invalid") from None

    @staticmethod
    def _validate_pending_job(job, page):
        video = job.video
        channel = video.channel
        if (
            job.page_id != page.pk
            or job.kind != PublishJob.Kind.VIDEO
            or job.scheduled_at is not None
            or job.remote_id
            or video.baseline
            or not video.available
            or video.state != "ready"
            or video.inspected_kind != "video"
            or video.delivery_kind != "video"
            or not video.rights_confirmed
            or not video.file_matches_video
            or not video.original
            or channel.page_id != page.pk
            or not channel.enabled
            or not channel.ownership_confirmed
        ):
            raise CommandError(f"batch_stopped_job_{job.pk}_readiness_changed")

    @staticmethod
    def _assert_no_unrelated_verification(jobs):
        if PublishJob.objects.filter(state=PublishJob.State.VERIFYING).exclude(
            pk__in=[job.pk for job in jobs]
        ).exists():
            raise CommandError("unrelated_verification_pending")

    @staticmethod
    def _set_page_gate(page, enabled):
        try:
            with worker_lock(), transaction.atomic():
                current = Page.objects.select_for_update().get(pk=page.pk)
                if current.auto_publish == enabled:
                    page.auto_publish = enabled
                    return
                user_model = get_user_model()
                actor, created = user_model.objects.get_or_create(
                    username="codex-batch",
                    defaults={"is_active": True, "is_staff": False, "is_superuser": False},
                )
                if actor.is_staff or actor.is_superuser:
                    raise CommandError("gate_audit_actor_invalid")
                if created:
                    actor.set_unusable_password()
                    actor.save(update_fields=["password"])
                current.auto_publish = enabled
                current.save(update_fields=["auto_publish"])
                LogEntry.objects.log_actions(
                    user_id=actor.pk,
                    queryset=Page.objects.filter(pk=current.pk),
                    action_flag=CHANGE,
                    change_message=(
                        "Codex batch publisher {} Page auto_publish for the authorized video batch".format(
                            "enabled" if enabled else "disabled"
                        )
                    ),
                )
                page.auto_publish = enabled
        except Timeout:
            raise CommandError("worker_busy") from None

    @staticmethod
    def _set_live_gate(enabled):
        path = settings.BASE_DIR / ".env"
        pattern = re.compile(rb"(?m)^LIVE_PUBLISH=[^\r\n]*")
        try:
            content = path.read_bytes()
            if len(pattern.findall(content)) != 1:
                raise ValueError
            updated = pattern.sub(
                b"LIVE_PUBLISH=" + (b"1" if enabled else b"0"), content, count=1
            )
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".env-", delete=False) as tmp:
                tmp.write(updated)
            Path(tmp.name).replace(path)
        except (OSError, ValueError):
            raise CommandError("live_publish_gate_update_failed") from None
        os.environ["LIVE_PUBLISH"] = "1" if enabled else "0"

    def _publish(self, jobs, page, interval):
        last_post_at = None
        for position, target in enumerate(jobs, start=1):
            while True:
                page.refresh_from_db(fields=["auto_publish", "post_video"])
                if os.getenv("LIVE_PUBLISH", "0") != "1" or not page.auto_publish:
                    raise CommandError("publish_gate_closed")
                if not page.post_video:
                    raise CommandError("page_video_gate_closed")
                job = PublishJob.objects.get(pk=target.pk)
                if job.state == PublishJob.State.SUCCEEDED:
                    break
                if job.state in {
                    PublishJob.State.BLOCKED,
                    PublishJob.State.NEEDS_REVIEW,
                    PublishJob.State.SENDING,
                    PublishJob.State.SCHEDULED,
                }:
                    raise CommandError(f"batch_stopped_job_{job.pk}_{job.state}")
                if job.state == PublishJob.State.PENDING and job.error_code:
                    raise CommandError(f"batch_stopped_job_{job.pk}_{job.error_code}")
                now = timezone.now()
                if job.state == PublishJob.State.VERIFYING and job.retry_at and job.retry_at > now:
                    time.sleep((job.retry_at - now).total_seconds())
                    continue
                if job.state == PublishJob.State.PENDING and last_post_at is not None:
                    wait = interval - (time.monotonic() - last_post_at)
                    if wait > 0:
                        time.sleep(wait)
                        continue

                if job.state == PublishJob.State.PENDING:
                    self._assert_no_unrelated_verification(jobs)
                    job = PublishJob.objects.select_related("video__channel").get(pk=target.pk)
                    self._validate_pending_job(job, page)
                    self._verify_backup([job], page)

                previous_state, previous_remote_id = job.state, job.remote_id
                result = process_queue(1, include_unscheduled=True, job_ids=[job.pk])
                if result == "worker_busy":
                    time.sleep(30)
                    continue
                job.refresh_from_db()
                if previous_state == PublishJob.State.PENDING and job.state == PublishJob.State.VERIFYING:
                    if not job.remote_id or job.remote_id == previous_remote_id:
                        raise CommandError(f"batch_stopped_job_{job.pk}_post_outcome_unknown")
                    last_post_at = time.monotonic()
                    self.stdout.write(
                        f"posted={position}/{len(jobs)} job_id={job.pk} remote_id={job.remote_id}"
                    )
                elif job.state == PublishJob.State.PENDING:
                    raise CommandError(
                        f"batch_stopped_job_{job.pk}_{job.error_code or 'not_advanced'}"
                    )
            self.stdout.write(
                f"verified={position}/{len(jobs)} job_id={job.pk} remote_id={job.remote_id}"
            )
            if position == 1:
                self.stdout.write(
                    f"public_check_url=https://www.facebook.com/watch/?v={job.remote_id}"
                )
                if input('Type "public-ok" after checking the first post in a logged-out view: ').strip() != "public-ok":
                    raise CommandError("first_post_public_check_not_confirmed")
        self.stdout.write(f"batch_complete verified={len(jobs)}")
