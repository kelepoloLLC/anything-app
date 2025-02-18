from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.template import Template, Context
import json

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
    css_content = models.TextField(blank=True, help_text="Custom CSS for the entire app")
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
    slug = models.SlugField()
    template_content = models.TextField(help_text="Django template content for this page")
    js_content = models.TextField(blank=True, help_text="Custom JavaScript for this page")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['app', 'slug']

    def __str__(self):
        return f"{self.app.name} - {self.name}"

    def render(self, request):
        """Renders the page with all its contexts"""
        context_data = {}
        
        # Get all context queries for this page
        for context_query in self.context_queries.all():
            try:
                context_data[context_query.context_key] = context_query.execute()
            except Exception as e:
                context_data[context_query.context_key] = None
                # Log the error
        
        # Add request-specific context
        context_data['request'] = request
        context_data['app'] = self.app
        context_data['page'] = self
        
        template = Template(self.template_content)
        return template.render(Context(context_data))

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

class DataStore(models.Model):
    VALUE_TYPES = [
        ('str', 'String'),
        ('int', 'Integer'),
        ('float', 'Float'),
        ('bool', 'Boolean'),
        ('json', 'JSON'),
        ('date', 'Date'),
        ('datetime', 'DateTime'),
    ]

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='data_store')
    key = models.CharField(max_length=100)
    value = models.TextField()
    value_type = models.CharField(max_length=10, choices=VALUE_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['app', 'key']

    def __str__(self):
        return f"{self.app.name} - {self.key}"

    def get_typed_value(self):
        """Returns the value converted to its proper type"""
        try:
            if self.value_type == 'str':
                return self.value
            elif self.value_type == 'int':
                return int(self.value)
            elif self.value_type == 'float':
                return float(self.value)
            elif self.value_type == 'bool':
                return self.value.lower() == 'true'
            elif self.value_type == 'json':
                return json.loads(self.value)
            elif self.value_type == 'date':
                return datetime.strptime(self.value, '%Y-%m-%d').date()
            elif self.value_type == 'datetime':
                return datetime.strptime(self.value, '%Y-%m-%d %H:%M:%S')
        except Exception:
            return None
        return self.value

class ContextQuery(models.Model):
    page = models.ForeignKey(AppPage, on_delete=models.CASCADE, related_name='context_queries')
    context_key = models.CharField(max_length=100, help_text="The key this query's result will be stored under in the template context")
    query_type = models.CharField(max_length=50, default='orm', choices=[('orm', 'Django ORM'), ('raw', 'Raw SQL')])
    query_content = models.TextField(help_text="The ORM query or raw SQL to execute")
    order = models.IntegerField(default=0, help_text="Order in which to execute queries")
    
    class Meta:
        ordering = ['order']
        unique_together = ['page', 'context_key']

    def __str__(self):
        return f"{self.page.app.name} - {self.page.name} - {self.context_key}"

    def execute(self):
        """Executes the stored query and returns the result"""
        try:
            if self.query_type == 'orm':
                # Be very careful with eval here - need to add security measures
                # This is just a basic example
                return eval(self.query_content)
            else:
                # For raw SQL queries
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(self.query_content)
                    return cursor.fetchall()
        except Exception as e:
            # Log the error
            return None
