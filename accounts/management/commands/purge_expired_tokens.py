from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from accounts.models import RefreshToken


class Command(BaseCommand):
    """Delete refresh_tokens rows that no longer carry any security value.

    Not wired to a scheduler yet since nothing is deployed. Once this
    project is deployed, run this on a daily cron/Celery-beat task — same
    idea as Django's built-in `clearsessions` command, applied to our
    hand-rolled refresh-token table instead of the session table.
    """

    help = "Delete expired refresh tokens, and revoked ones older than the grace period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--grace-days",
            type=int,
            default=7,
            help="Keep revoked rows for this many days after revocation before deleting them "
            "(default: 7). Expired rows are always deleted regardless of this value.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        grace_cutoff = now - timezone.timedelta(days=options["grace_days"])

        deletable = RefreshToken.objects.filter(
            Q(expires_at__lt=now) | Q(revoked_at__isnull=False, revoked_at__lt=grace_cutoff)
        )
        deleted_count, _ = deletable.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} refresh token row(s)."))
