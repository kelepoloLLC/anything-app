from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from users.models import UserProfile

User = get_user_model()

class Command(BaseCommand):
    help = 'Ensures all users have associated profiles'

    def handle(self, *args, **kwargs):
        users = User.objects.all()
        created_count = 0
        
        for user in users:
            _, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'token_count': 0,
                    'bio': '',
                }
            )
            if created:
                created_count += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully processed all users. Created {created_count} new profiles.'
            )
        ) 