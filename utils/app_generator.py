import anthropic
from django.conf import settings
from anything_apps.models import App, AppPage, DataStore, ContextQuery, Prompt
from anything_org.models import Organization
import json
import logging

logger = logging.getLogger(__name__)

class AppGenerator:
    def __init__(self, organization: Organization, prompt: Prompt):
        self.organization = organization
        self.prompt = prompt
        self.claude = anthropic.Client(
            api_key=settings.ANTHROPIC_API_KEY
        )

    def _get_app_structure(self):
        """Generate app structure based on the prompt using Claude."""
        try:
            logger.info(f"Requesting app structure from Claude for prompt {self.prompt.id}")
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4000,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """You are an expert CRM template architect. Your task is to analyze the user's CRM app idea and create:
                1. Page templates with proper styling
                2. Data structure definitions
                3. Context queries to populate the templates
                4. Any necessary JavaScript for interactivity
                
                Return the response in JSON format with the following structure:
                {
                    "name": "App name",
                    "description": "App description",
                    "pages": [
                        {
                            "name": "Page name",
                            "slug": "page-slug",
                            "template": "Django template content",
                            "js": "JavaScript content",
                            "css": "CSS content",
                            "contexts": [
                                {
                                    "key": "context_key",
                                    "query": "Django ORM query",
                                    "description": "What this context provides"
                                }
                            ]
                        }
                    ],
                    "data_structure": [
                        {
                            "key": "data_key",
                            "value_type": "str|int|float|bool|json|date|datetime",
                            "description": "What this data represents"
                        }
                    ]
                }

                Here is the user's app idea to analyze: {self.prompt.content}"""
                            }
                        ]
                    }
                ]
            )
            
            # Log the raw response for debugging
            logger.info(f"Raw Claude response type: {type(message)}")
            logger.info(f"Raw Claude response: {message}")
            logger.info(f"Response content type: {type(message.content)}")
            logger.info(f"Response content: {message.content}")
            
            if not message.content or not isinstance(message.content, list) or len(message.content) == 0:
                raise ValueError("Empty or invalid response from Claude")
            
            # Update token usage
            self.prompt.tokens_used = message.usage.output_tokens
            self.prompt.save()
            
            # Parse and validate the response
            try:
                # The response is a list of content blocks, get the first one's text
                response_text = message.content[0].text
                logger.info(f"Response text to parse: {response_text}")
                
                if not response_text:
                    raise ValueError("Empty response text from Claude")
                    
                app_structure = json.loads(response_text)
                logger.info(f"Successfully received and parsed app structure for prompt {self.prompt.id}")
                return app_structure
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Claude response for prompt {self.prompt.id}: {str(e)}")
                logger.error(f"Raw text that failed to parse: {response_text}")
                raise ValueError(f"Invalid JSON response from Claude: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error getting app structure from Claude for prompt {self.prompt.id}: {str(e)}")
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            raise

    def _setup_data_structure(self, app: App, data_structure: list):
        """Set up the initial data structure for the app."""
        try:
            logger.info(f"Setting up data structure for app {app.id}")
            for data_def in data_structure:
                DataStore.objects.create(
                    app=app,
                    key=data_def['key'],
                    value='',  # Empty initial value
                    value_type=data_def['value_type']
                )
            logger.info(f"Successfully set up data structure for app {app.id}")
        except Exception as e:
            logger.error(f"Error setting up data structure for app {app.id}: {str(e)}")
            raise

    def _create_pages(self, app: App, pages_data: list):
        """Create pages with templates, contexts, and static content."""
        try:
            logger.info(f"Creating pages for app {app.id}")
            for page_data in pages_data:
                # Create the page
                page = AppPage.objects.create(
                    app=app,
                    name=page_data['name'],
                    slug=page_data['slug'],
                    template_content=page_data['template'],
                    js_content=page_data.get('js', ''),
                    css_content=page_data.get('css', '')
                )
                
                # Create context queries for the page
                for ctx in page_data.get('contexts', []):
                    ContextQuery.objects.create(
                        page=page,
                        context_key=ctx['key'],
                        query_content=ctx['query'],
                        query_type='orm'  # Default to ORM queries
                    )
            logger.info(f"Successfully created pages for app {app.id}")
        except Exception as e:
            logger.error(f"Error creating pages for app {app.id}: {str(e)}")
            raise

    def generate_app(self) -> App:
        """Main method to generate the complete app."""
        app = None
        try:
            logger.info(f"Starting app generation for prompt {self.prompt.id}")
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
            logger.info(f"Created app {app.id} for prompt {self.prompt.id}")

            # Set up data structure
            self._setup_data_structure(app, app_structure['data_structure'])

            # Create pages with templates and contexts
            self._create_pages(app, app_structure['pages'])

            self.prompt.status = 'COMPLETED'
            self.prompt.save()
            logger.info(f"Successfully completed app generation for prompt {self.prompt.id}")

            return app

        except Exception as e:
            logger.error(f"Error in app generation for prompt {self.prompt.id}: {str(e)}")
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            
            # If app was created but generation failed, mark it as error
            if app:
                app.status = 'ERROR'
                app.save()
                
            raise 