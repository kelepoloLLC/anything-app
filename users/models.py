from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# Create your models here.

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(max_length=500, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    avatar = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    token_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def has_sufficient_tokens(self, required_tokens):
        """Check if user has sufficient tokens for an operation."""
        return self.token_count >= required_tokens

    def deduct_tokens(self, amount):
        """Deduct tokens from user's balance."""
        if self.has_sufficient_tokens(amount):
            self.token_count -= amount
            self.save()
            return True
        return False

    def add_tokens(self, amount):
        """Add tokens to user's balance."""
        self.token_count += amount
        self.save()

    @classmethod
    def get_or_create_profile(cls, user):
        """
        Gets or creates a profile for the given user.
        
        Args:
            user: The User instance to get/create profile for
            
        Returns:
            UserProfile: The user's profile, either existing or newly created
        """
        profile, created = cls.objects.get_or_create(
            user=user,
            defaults={
                'token_count': 0,
                'bio': '',
            }
        )
        return profile

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
