"""
Initial migration — creates only the three Django-managed tables.
JTP_Pathways and EE_JTP_Status are managed via sql/schema_changes.sql.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='JTPAdminUser',
            fields=[
                ('id',         models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('wwid',       models.CharField(blank=True, max_length=50,  null=True, unique=True)),
                ('isid',       models.CharField(blank=True, max_length=50,  null=True, unique=True)),
                ('email',      models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'db_table': 'jtp_admin_users'},
        ),
        migrations.CreateModel(
            name='JTPTeamMember',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mgr_wwid',       models.CharField(max_length=50)),
                ('employee_wwid',  models.CharField(max_length=50)),
                ('employee_name',  models.CharField(max_length=255)),
                ('employee_email', models.CharField(blank=True, default='', max_length=255)),
                ('created_at',     models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'jtp_team_members',
                'unique_together': {('mgr_wwid', 'employee_wwid')},
            },
        ),
        migrations.CreateModel(
            name='JTPAccessLog',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_email',  models.CharField(max_length=255)),
                ('user_name',   models.CharField(blank=True, default='', max_length=255)),
                ('wwid',        models.CharField(blank=True, default='', max_length=50)),
                ('page_url',    models.CharField(max_length=512)),
                ('accessed_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'db_table': 'jtp_access_log'},
        ),
    ]
