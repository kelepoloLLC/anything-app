import anthropic
from django.conf import settings
from anything_apps.models import App, AppPage, AppModel, Permission, Prompt
from anything_org.models import Organization

class AppGenerator:
    def __init__(self, organization: Organization, prompt: Prompt):
        self.organization = organization
        self.prompt = prompt
        self.claude = anthropic.Client(settings.ANTHROPIC_API_KEY)

    def _get_app_structure(self):
        """Generate app structure based on the prompt using Claude."""
        try:
            message = self.claude.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=4000,
                temperature=0.7,
                system="You are an expert app architect. Your task is to analyze the user's app idea and create a detailed app structure including models, pages, and permissions. Return the response in JSON format.",
                messages=[{
                    "role": "user",
                    "content": f"Create an app structure for: {self.prompt.content}"
                }]
            )
            
            # Update token usage
            self.prompt.tokens_used = message.usage.output_tokens
            self.prompt.save()
            
            return message.content
        except Exception as e:
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            raise

    def _generate_models(self, app: App, models_data: dict):
        """Generate Django models based on the app structure."""
        for model_data in models_data:
            AppModel.objects.create(
                app=app,
                name=model_data['name'],
                fields=model_data['fields'],
                relationships=model_data.get('relationships', {})
            )

    def _generate_pages(self, app: App, pages_data: dict):
        """Generate pages with templates, JS, and CSS."""
        for page_data in pages_data:
            AppPage.objects.create(
                app=app,
                name=page_data['name'],
                template_content=page_data['template'],
                js_content=page_data.get('js', ''),
                css_content=page_data.get('css', ''),
                url_path=page_data['url_path']
            )

    def _generate_permissions(self, app: App):
        """Generate default permissions for the app."""
        default_permissions = [
            ('view_app', 'Can view app'),
            ('edit_app', 'Can edit app'),
            ('delete_app', 'Can delete app'),
            ('manage_users', 'Can manage app users')
        ]

        for codename, name in default_permissions:
            Permission.objects.create(
                app=app,
                name=name,
                codename=codename
            )

    def generate_app(self) -> App:
        """Main method to generate the complete app."""
        try:
            self.prompt.status = 'PROCESSING'
            self.prompt.save()

            # Get app structure from Claude
            app_structure = self._get_app_structure()

            # Create the app instance
            app = App.objects.create(
                organization=self.organization,
                name=app_structure['name'],
                description=app_structure['description'],
                initial_prompt=self.prompt,
                status='ACTIVE'
            )

            # Generate models
            self._generate_models(app, app_structure['models'])

            # Generate pages
            self._generate_pages(app, app_structure['pages'])

            # Generate permissions
            self._generate_permissions(app)

            self.prompt.status = 'COMPLETED'
            self.prompt.save()

            return app

        except Exception as e:
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            raise 