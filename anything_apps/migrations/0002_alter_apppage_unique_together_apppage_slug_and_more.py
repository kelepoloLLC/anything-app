# Generated by Django 4.2.11 on 2025-02-17 04:24

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('anything_apps', '0001_initial'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='apppage',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='apppage',
            name='slug',
            field=models.SlugField(default=''),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='apppage',
            name='css_content',
            field=models.TextField(blank=True, help_text='Custom CSS for this page'),
        ),
        migrations.AlterField(
            model_name='apppage',
            name='js_content',
            field=models.TextField(blank=True, help_text='Custom JavaScript for this page'),
        ),
        migrations.AlterField(
            model_name='apppage',
            name='template_content',
            field=models.TextField(help_text='Django template content for this page'),
        ),
        migrations.AlterUniqueTogether(
            name='apppage',
            unique_together={('app', 'slug')},
        ),
        migrations.RemoveField(
            model_name='apppage',
            name='url_path',
        ),
        migrations.CreateModel(
            name='DataStore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=100)),
                ('value', models.TextField()),
                ('value_type', models.CharField(choices=[('str', 'String'), ('int', 'Integer'), ('float', 'Float'), ('bool', 'Boolean'), ('json', 'JSON'), ('date', 'Date'), ('datetime', 'DateTime')], max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('app', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='data_store', to='anything_apps.app')),
            ],
            options={
                'unique_together': {('app', 'key')},
            },
        ),
        migrations.CreateModel(
            name='ContextQuery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('context_key', models.CharField(help_text="The key this query's result will be stored under in the template context", max_length=100)),
                ('query_type', models.CharField(choices=[('orm', 'Django ORM'), ('raw', 'Raw SQL')], default='orm', max_length=50)),
                ('query_content', models.TextField(help_text='The ORM query or raw SQL to execute')),
                ('order', models.IntegerField(default=0, help_text='Order in which to execute queries')),
                ('page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='context_queries', to='anything_apps.apppage')),
            ],
            options={
                'ordering': ['order'],
                'unique_together': {('page', 'context_key')},
            },
        ),
    ]
