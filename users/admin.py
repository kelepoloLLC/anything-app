from django.contrib import admin
from .models import UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'token_count', 'birth_date', 'created_at', 'updated_at')
    search_fields = ('user__username', 'user__email', 'bio')
    list_filter = ('created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
