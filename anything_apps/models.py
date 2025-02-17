from django.db import models
from django.conf import settings

# Create your models here.

class Prompt(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed')
    ]

    content = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey('anything_org.Organization', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    tokens_used = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Prompt by {self.user.username} - {self.created_at}"

class PromptUpdate(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed')
    ]

    original_prompt = models.ForeignKey(Prompt, on_delete=models.CASCADE, related_name='updates')
    update_content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    tokens_used = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Update to {self.original_prompt} - {self.created_at}"

class App(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('UPDATING', 'Updating'),
        ('ERROR', 'Error')
    ]

    organization = models.ForeignKey('anything_org.Organization', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField()
    initial_prompt = models.ForeignKey(Prompt, on_delete=models.CASCADE, related_name='created_apps')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']

class AppPage(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='pages')
    name = models.CharField(max_length=100)
    template_content = models.TextField()
    js_content = models.TextField(blank=True)
    css_content = models.TextField(blank=True)
    url_path = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.app.name} - {self.name}"

    class Meta:
        unique_together = ('app', 'url_path')

class AppModel(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='models')
    name = models.CharField(max_length=100)
    fields = models.JSONField()
    relationships = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.app.name} - {self.name}"

    class Meta:
        unique_together = ('app', 'name')

class Permission(models.Model):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='permissions')
    name = models.CharField(max_length=100)
    codename = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.app.name} - {self.name}"

    class Meta:
        unique_together = ('app', 'codename')
