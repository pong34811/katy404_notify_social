from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("social", "0005_publishjob_scheduled_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="video",
            name="state",
            field=models.CharField(
                choices=[
                    ("baseline", "Baseline (not queued)"),
                    ("waiting_file", "Waiting for original or landscape confirmation"),
                    ("waiting_rights", "Waiting for rights confirmation"),
                    ("waiting_thumbnail", "Waiting for thumbnail"),
                    ("ready", "Ready for video upload"),
                    ("ready_photo", "Ready for photo notification"),
                    ("rejected", "Unsupported media"),
                    ("needs_review", "Route changed: needs review"),
                    ("scheduled", "Scheduled on Facebook"),
                    ("published", "All configured Facebook deliveries verified"),
                ],
                default="waiting_file",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="publishjob",
            name="state",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sending", "Sending"),
                    ("verifying", "Verifying"),
                    ("scheduled", "Scheduled on Facebook"),
                    ("succeeded", "Remote object verified (visibility requires manual check)"),
                    ("needs_review", "Needs review; do not resend"),
                    ("blocked", "Blocked"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
