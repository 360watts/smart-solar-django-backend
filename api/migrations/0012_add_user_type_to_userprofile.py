# Generated migration to add user_type field to UserProfile

from django.db import migrations, models
from django.contrib.auth.models import User


def populate_user_types(apps, schema_editor):
    """
    Populate user_type for existing users:
    - Superusers -> MASTER
    - Staff users -> ADMIN  
    - Regular users -> USER
    """
    UserProfile = apps.get_model('api', 'UserProfile')
    User = apps.get_model('auth', 'User')
    
    # Create UserProfile for all users that don't have one
    for user in User.objects.all():
        profile, created = UserProfile.objects.get_or_create(user=user)
        
        # Set user_type based on existing permissions
        if user.is_superuser:
            profile.user_type = 'MASTER'
        elif user.is_staff:
            profile.user_type = 'ADMIN'
        else:
            profile.user_type = 'USER'
        
        profile.save()


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_slave_preset_m2m_relationship'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='user_type',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('MASTER', 'Master'),
                    ('ADMIN', 'Admin'),
                    ('USER', 'User'),
                ],
                default='USER',
                help_text='Master: All rights, Admin: Staff/installers, User: Device owners'
            ),
        ),
        migrations.RunPython(populate_user_types, reverse_code=migrations.RunPython.noop),
    ]
