from django.db import migrations


def seed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Coordinators")
    Group.objects.get_or_create(name="Facilitators")


def unseed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["Coordinators", "Facilitators"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_magic_link_token"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_groups, reverse_code=unseed_groups),
    ]
