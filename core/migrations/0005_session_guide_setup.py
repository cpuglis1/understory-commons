"""Session-guide setup: Program pay defaults + the ProgramFacilitator through-model.

The M2M -> through conversion is handwritten (the autodetector would drop the join
table and lose assignments). Per the ADR (D2): adopt the existing
``core_program_facilitators`` table via ``SeparateDatabaseAndState`` (state-only — the
table already exists), then ``AddField`` the rate column as a real ALTER. The state
``CreateModel`` mirrors the auto-M2M exactly (BigAutoField id, ``user_id`` column,
unique_together) so model state and DB stay in sync.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_profile_snapshot_slugs_descriptive"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="default_session_length_minutes",
            field=models.PositiveIntegerField(default=90),
        ),
        migrations.AddField(
            model_name="program",
            name="default_facilitator",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"role": "facilitator"},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="default_for_programs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ProgramFacilitator",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "program",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="facilitator_links",
                                to="core.program",
                            ),
                        ),
                        (
                            "facilitator",
                            models.ForeignKey(
                                db_column="user_id",
                                limit_choices_to={"role": "facilitator"},
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="program_links",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "core_program_facilitators",
                        "unique_together": {("program", "facilitator")},
                    },
                ),
                migrations.AlterField(
                    model_name="program",
                    name="facilitators",
                    field=models.ManyToManyField(
                        blank=True,
                        limit_choices_to={"role": "facilitator"},
                        related_name="facilitated_programs",
                        through="core.ProgramFacilitator",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            # No database_operations: the join table already exists; this only
            # repoints model state at the explicit through-model.
        ),
        migrations.AddField(
            model_name="programfacilitator",
            name="hourly_rate_cents",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
