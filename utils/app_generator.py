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

    def _clean_json_response(self, response_text: str) -> str:
        """Clean the response text to extract only the JSON part."""
        # Find the first { and last }
        try:
            start = response_text.find('{')
            end = response_text.rindex('}') + 1
            if start >= 0 and end > start:
                return response_text[start:end]
            return response_text
        except ValueError:
            return response_text

    def _get_app_structure(self):
        """Get the high-level app structure and page definitions."""
        try:
            logger.info(f"Requesting initial app structure from Claude for prompt {self.prompt.id}")
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"""You are an expert CRM architect. Analyze this app idea and provide a high-level structure.
                                
Return ONLY a JSON response in this exact format, with no additional text or notes:
{{
    "name": "App name",
    "description": "App description",
    "data_structure": [
        {{
            "key": "data_key",
            "value_type": "str|int|float|bool|json|date|datetime",
            "description": "What this data represents"
        }}
    ],
    "pages": [
        {{
            "name": "Page name",
            "slug": "page-slug",
            "description": "What this page does"
        }}
    ]
}}

Here is the app idea to analyze: {self.prompt.content}"""
                            }
                        ]
                    }
                ]
            )
            
            logger.info(f"Initial structure response: {message.content}")
            
            try:
                # Parse the initial structure
                response_text = self._clean_json_response(message.content[0].text.strip())
                logger.info(f"Attempting to parse initial structure: {response_text}")
                initial_structure = json.loads(response_text)
                logger.info(f"Successfully parsed initial app structure for prompt {self.prompt.id}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse initial structure: {str(e)}")
                logger.error(f"Raw text that failed to parse: {response_text}")
                raise
            
            # Now generate detailed page structures one by one
            detailed_pages = []
            for page in initial_structure['pages']:
                logger.info(f"Generating detailed structure for page: {page['name']}")
                page_message = self.claude.messages.create(
                    model="claude-3-sonnet-20240229",
                    max_tokens=2000,
                    temperature=0.7,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"""You are an expert Django template architect. Generate a detailed page structure for a {page['name']} page in a CRM app.
                                    
This page's purpose: {page['description']}

The app has the following data structure:
{json.dumps(initial_structure['data_structure'], indent=2)}

Return ONLY a JSON response in this exact format, with no additional text, notes, or explanations:
{{
    "name": "{page['name']}",
    "slug": "{page['slug']}",
    "template": "HTML template content with proper styling",
    "js": "JavaScript content in Stimulus format",
    "css": "CSS content",
    "contexts": [
        {{
            "key": "context_key",
            "query": "Django ORM query",
            "description": "What this context provides"
        }}
    ]
}}

Important: 
1. Return ONLY the JSON object, no other text
2. Properly escape all special characters in strings
3. Use \\" for quotes and \\n for newlines
4. Make sure the response is valid JSON"""
                                }
                            ]
                        }
                    ]
                )
                
                try:
                    logger.info(f"Received response for page {page['name']}")
                    response_text = self._clean_json_response(page_message.content[0].text.strip())
                    logger.info(f"Attempting to parse page structure: {response_text}")
                    page_structure = json.loads(response_text)
                    logger.info(f"Successfully parsed structure for page: {page['name']}")
                    detailed_pages.append(page_structure)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse page structure for {page['name']}: {str(e)}")
                    logger.error(f"Raw text that failed to parse: {response_text}")
                    raise
                
                # Accumulate token usage
                self.prompt.tokens_used += page_message.usage.output_tokens
            
            # Update the initial structure with detailed pages
            initial_structure['pages'] = detailed_pages
            
            # Add initial message tokens
            self.prompt.tokens_used += message.usage.output_tokens
            self.prompt.save()
            
            return initial_structure
                
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