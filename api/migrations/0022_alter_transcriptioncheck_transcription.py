# Generated by Django 3.2.12 on 2022-02-26 15:29

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0021_auto_20220225_2009"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transcriptioncheck",
            name="transcription",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="api.transcription"
            ),
        ),
    ]
