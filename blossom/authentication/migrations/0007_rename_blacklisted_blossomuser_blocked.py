# Generated by Django 3.2.15 on 2022-08-23 22:43

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0006_blossomuser_overwrite_check_percentage"),
    ]

    operations = [
        migrations.RenameField(
            model_name="blossomuser",
            old_name="blacklisted",
            new_name="blocked",
        ),
    ]
