"""Safely restore a retained physical index as the active search index."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.index_manager import ALIAS_NAME
from documents.management.commands.rebuild_index import (
    Command as RebuildCommand,
)
from documents.rebuild_lock import acquire_document_write_lock
from documents.search_client import get_opensearch_client


class Command(BaseCommand):
    """Refresh and activate a retained physical index."""

    help = "Safely restore a retained physical OpenSearch index."

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            required=True,
            help="Name of the retained physical index to restore.",
        )

    def handle(self, *args, **options):
        target = options["target"].strip()

        if not target:
            raise CommandError("A physical index name is required.")

        if target == ALIAS_NAME:
            raise CommandError("The target must be a physical index, not the search alias.")

        client = get_opensearch_client()
        rebuild = RebuildCommand()
        rebuild.stdout = self.stdout
        rebuild.stderr = self.stderr

        if not client.indices.exists(index=target):
            raise CommandError(f"Target index {target!r} does not exist.")

        try:
            current_targets = client.indices.get_alias(name=ALIAS_NAME)
        except Exception as exc:
            raise CommandError(f"Could not resolve alias {ALIAS_NAME!r}: {exc}") from exc

        if target in current_targets:
            self.stdout.write(
                self.style.SUCCESS(f"Index {target!r} is already attached to {ALIAS_NAME!r}.")
            )
            return

        self.stdout.write(f"Refreshing retained index: {target}")

        try:
            with transaction.atomic():
                acquire_document_write_lock()

                # Reapply the complete event history using external versions.
                rebuild._replay_events(client, target)
                client.indices.refresh(index=target)

                rebuild._validate_replacement(client, target)

                current_targets = client.indices.get_alias(name=ALIAS_NAME)
                if target in current_targets:
                    raise CommandError(
                        f"Target {target!r} became an alias target during "
                        "rollback; refusing to change the alias."
                    )

                actions = [
                    {"remove": {"index": index, "alias": ALIAS_NAME}} for index in current_targets
                ]
                actions.append({"add": {"index": target, "alias": ALIAS_NAME}})
                client.indices.update_aliases(body={"actions": actions})

            self.stdout.write(
                self.style.SUCCESS(
                    f"Rollback complete. Alias {ALIAS_NAME!r} now points "
                    f"to {target}. Previous indexes were retained."
                )
            )

        except Exception as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(f"Rollback failed: {exc}") from exc
