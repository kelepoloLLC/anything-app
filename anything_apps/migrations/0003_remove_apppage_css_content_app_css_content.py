# Generated by Django 4.2.11 on 2025-02-18 04:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anything_apps', '0002_alter_apppage_unique_together_apppage_slug_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='apppage',
            name='css_content',
        ),
        migrations.AddField(
            model_name='app',
            name='css_content',
            field=models.TextField(blank=True, help_text='Custom CSS for the entire app'),
        ),
    ]
