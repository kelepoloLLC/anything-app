import anthropic
from django.conf import settings
from anything_apps.models import App, AppPage, DataStore, ContextQuery, Prompt
from anything_org.models import Organization
from django.contrib.staticfiles.finders import find
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

class AppGenerator:
    def __init__(self, organization: Organization, prompt: Prompt):
        self.organization = organization
        self.prompt = prompt
        self.claude = anthropic.Client(
            api_key=settings.ANTHROPIC_API_KEY
        )
        self.base_prompt_path = os.path.join(settings.BASE_DIR, 'static', 'prompts')

    def _load_prompt_template(self, template_name: str) -> str:
        """Load a prompt template using Django's static file finders."""
        template_path = find(f'prompts/{template_name}.txt')
        if not template_path:
            error_msg = f"Could not find prompt template: prompts/{template_name}.txt"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
            
        try:
            with open(template_path, 'r') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error loading prompt template {template_name}: {str(e)}")
            raise

    def _clean_json_response(self, response_text: str) -> str:
        """Clean the response text to extract only the JSON part and handle control characters."""
        try:
            # First try to parse the entire response as JSON
            try:
                json.loads(response_text)
                return response_text
            except json.JSONDecodeError:
                pass

            # Try to find JSON object or array
            obj_start = response_text.find('{')
            arr_start = response_text.find('[')
            
            # Determine if we're dealing with an object or array
            if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
                start = obj_start
                end = response_text.rindex('}') + 1
            elif arr_start >= 0:
                start = arr_start
                end = response_text.rindex(']') + 1
            else:
                return response_text
            
            if start >= 0 and end > start:
                json_text = response_text[start:end]
                
                # Remove any leading/trailing whitespace
                json_text = json_text.strip()
                
                # Try to parse the extracted JSON
                try:
                    json.loads(json_text)
                    return json_text
                except json.JSONDecodeError:
                    # First normalize all newlines
                    cleaned_text = json_text.replace('\r\n', '\n').replace('\r', '\n')
                    
                    # Handle HTML attributes with double quotes
                    cleaned_text = cleaned_text.replace('class="', 'class=\\"')
                    cleaned_text = cleaned_text.replace('" ', '\\" ')
                    
                    # Handle data attributes
                    cleaned_text = cleaned_text.replace('data-action="', 'data-action=\\"')
                    cleaned_text = cleaned_text.replace('data-target="', 'data-target=\\"')
                    
                    # Handle template variables
                    cleaned_text = cleaned_text.replace('{{', '\\{\\{').replace('}}', '\\}\\}')
                    cleaned_text = cleaned_text.replace('{%', '\\{\\%').replace('%}', '\\%\\}')
                    
                    # Escape newlines
                    cleaned_text = cleaned_text.replace('\n', '\\n')
                    
                    # Remove extra spaces
                    cleaned_text = ' '.join(line.strip() for line in cleaned_text.split('\n'))
                    
                    try:
                        json.loads(cleaned_text)
                        return cleaned_text
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to clean JSON: {cleaned_text}")
                        logger.error(f"JSON error: {str(e)}")
                        raise
                        
            return response_text
        except Exception as e:
            logger.error(f"Error cleaning JSON response: {str(e)}")
            return response_text

    def _get_page_css(self, page_name: str, theme: dict) -> str:
        """Generate detailed CSS for a page."""
        try:
            # Load and format the base styling prompt
            css_template = self._load_prompt_template('base_styling')
            formatted_prompt = css_template.replace('{{ theme.primaryColor }}', theme.get('primaryColor', 'hsl(215, 90%, 50%)'))
            formatted_prompt = formatted_prompt.replace('{{ theme.accentColor }}', theme.get('accentColor', 'hsl(280, 90%, 50%)'))
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            return message.content[0].text.strip()
                
        except Exception as e:
            logger.error(f"Error generating CSS for page {page_name}: {str(e)}")
            raise

    def _escape_json_string(self, s: str) -> str:
        """Properly escape a string for JSON inclusion."""
        # First normalize newlines
        s = s.replace('\r\n', '\n').replace('\r', '\n')
        
        # Handle HTML attributes with double quotes
        s = s.replace('class="', 'class=\\"')
        s = s.replace('" ', '\\" ')
        s = s.replace('data-action="', 'data-action=\\"')
        s = s.replace('data-target="', 'data-target=\\"')
        
        # Handle template variables
        s = s.replace('{{', '\\{\\{').replace('}}', '\\}\\}')
        s = s.replace('{%', '\\{\\%').replace('%}', '\\%\\}')
        
        # Escape remaining quotes and backslashes
        s = s.replace('\\', '\\\\')
        s = s.replace('"', '\\"')
        
        # Finally escape newlines
        s = s.replace('\n', '\\n')
        
        return s

    def _get_app_structure(self):
        """Get the high-level app structure and page definitions."""
        try:
            logger.info(f"Requesting initial app structure from Claude for prompt {self.prompt.id}")
            
            # First, get the base CSS that will be used across all pages
            base_css = self._get_component_styles(self.prompt.content)
            
            # Load and format the app structure prompt
            prompt_template = self._load_prompt_template('app_structure')
            formatted_prompt = prompt_template.replace('{prompt_content}', self.prompt.content)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            try:
                # Parse the initial structure
                response_text = self._clean_json_response(message.content[0].text.strip())
                logger.info(f"Attempting to parse initial structure: {response_text}")
                initial_structure = json.loads(response_text)
                initial_structure['base_css'] = base_css
                logger.info(f"Successfully parsed initial app structure for prompt {self.prompt.id}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse initial structure: {str(e)}")
                logger.error(f"Raw text that failed to parse: {response_text}")
                raise
            
            # Now generate detailed page structures one by one
            detailed_pages = []
            for page in initial_structure['pages']:
                logger.info(f"Generating detailed structure for page: {page['name']}")
                page_structure = self._get_page_structure(page, initial_structure)
                detailed_pages.append(page_structure)
                
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

    def _convert_template_delimiters(self, template: str) -> str:
        """Convert special template delimiters back to Django syntax."""
        # Replace template variable delimiters
        template = template.replace('((', '{{').replace('))', '}}')
        
        # Replace template tag delimiters
        template = template.replace('(%', '{%').replace('%)', '%}')
        
        # Replace quote delimiters in HTML attributes
        # Use regex to handle multi-line attributes properly
        template = re.sub(r'=\|\|([^|]+)\|\|', r'="\1"', template)
        
        return template

    def _parse_llm_response(self, response_text: str) -> dict:
        """Parse the LLM response that contains separated sections."""
        try:
            sections = {}
            current_section = None
            current_content = []
            
            # Split response into lines and process each line
            for line in response_text.split('\n'):
                # Check for section markers
                if line.strip().startswith('---') and line.strip().endswith('---'):
                    if current_section:
                        # Save the previous section
                        sections[current_section] = '\n'.join(current_content).strip()
                        current_content = []
                    # Set new section (remove dashes and whitespace)
                    current_section = line.strip().replace('-', '').strip()
                else:
                    if current_section:
                        current_content.append(line)
            
            # Save the last section
            if current_section and current_content:
                sections[current_section] = '\n'.join(current_content).strip()
            
            # Convert template delimiters if TEMPLATE section exists
            if 'TEMPLATE' in sections:
                sections['TEMPLATE'] = self._convert_template_delimiters(sections['TEMPLATE'])
            
            # Parse the METADATA section as JSON
            if 'METADATA' in sections:
                sections['METADATA'] = json.loads(sections['METADATA'])
            
            return sections
            
        except Exception as e:
            logger.error(f"Error parsing LLM response: {str(e)}")
            logger.error(f"Response text: {response_text}")
            raise

    def _get_page_structure(self, page: dict, app_structure: dict) -> dict:
        """Generate page structure without CSS."""
        try:
            # Load and format the page structure prompt
            page_prompt_template = self._load_prompt_template('page_structure')
            formatted_page_prompt = page_prompt_template.replace('{page_name}', page['name'])
            formatted_page_prompt = formatted_page_prompt.replace('{page_description}', page['description'])
            formatted_page_prompt = formatted_page_prompt.replace('{page_slug}', page['slug'])
            formatted_page_prompt = formatted_page_prompt.replace('{data_structure}', json.dumps(app_structure['data_structure'], indent=2))
            
            page_message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_page_prompt}]
                    }
                ]
            )
            
            try:
                # Parse the response into sections
                sections = self._parse_llm_response(page_message.content[0].text.strip())
                
                # Get the base template
                template = sections['TEMPLATE']
                metadata = sections['METADATA']
                
                # Now generate the page logic based on the template
                logic = self._get_page_logic(page['name'], template, app_structure['base_css'])
                
                # Construct the final page structure
                page_structure = metadata
                page_structure['template'] = template
                page_structure['js'] = logic
                
                logger.info(f"Successfully parsed structure for page: {page['name']}")
                return page_structure
                
            except Exception as e:
                logger.error(f"Failed to parse page structure for {page['name']}: {str(e)}")
                logger.error(f"Raw text that failed to parse: {page_message.content[0].text.strip()}")
                raise
                
        except Exception as e:
            logger.error(f"Error generating page structure: {str(e)}")
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
        """Create pages with templates and contexts."""
        try:
            logger.info(f"Creating pages for app {app.id}")
            for page_data in pages_data:
                # Get page template
                template = self._get_page_template(
                    page_data['name'],
                    page_data.get('description', ''),
                    self._get_component_styles(self.prompt.content)
                )
                
                # Get page context
                context = self._get_page_context(page_data['name'], template)
                
                # Get page logic
                js_logic = self._get_page_logic(
                    page_data['name'],
                    page_data['description'],
                    template,
                    self._get_component_styles(self.prompt.content)
                )
                
                # Create the page
                page = AppPage.objects.create(
                    app=app,
                    name=page_data['name'],
                    slug=page_data['slug'],
                    template_content=template,
                    js_content=js_logic
                )
                
                # Create context queries for the page
                for ctx in context:
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

    def _get_component_styles(self, prompt_content: str) -> str:
        """Generate app-wide CSS based on theme and requirements."""
        try:
            style_prompt = self._load_prompt_template('base_styling')
            formatted_prompt = style_prompt.replace('{prompt_content}', prompt_content)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            return message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error generating component styles: {str(e)}")
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

            # Generate app-wide CSS
            app_css = self._get_component_styles(self.prompt.content)

            # Create the app instance
            app = App.objects.create(
                organization=self.organization,
                name=app_structure['name'],
                description=app_structure['description'],
                initial_prompt=self.prompt,
                css_content=app_css,
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

    def _get_page_update(self, page: AppPage, update_prompt: str) -> dict:
        """Generate an updated page structure based on the update prompt."""
        try:
            logger.info(f"Requesting page update from Claude for page {page.id}")
            
            # Get the DataStore model definition
            datastore_model = '''class DataStore(models.Model):
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
        return self.value'''
            
            # Get the current data structure
            data_structure = [
                {
                    "key": ds.key,
                    "value_type": ds.value_type,
                    "value": ds.value
                }
                for ds in page.app.datastore_set.all()
            ]
            
            # Load and format the page update prompt
            prompt_template = self._load_prompt_template('page_update')
            # Replace placeholders with actual values
            formatted_prompt = prompt_template.replace('{page_name}', page.name)
            formatted_prompt = formatted_prompt.replace('{page_slug}', page.slug)
            formatted_prompt = formatted_prompt.replace('{data_structure}', json.dumps(data_structure, indent=2))
            formatted_prompt = formatted_prompt.replace('{template_content}', page.template_content)
            formatted_prompt = formatted_prompt.replace('{js_content}', page.js_content)
            formatted_prompt = formatted_prompt.replace('{update_prompt}', update_prompt)
            formatted_prompt = formatted_prompt.replace('{datastore_model}', datastore_model)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            try:
                response_text = self._clean_json_response(message.content[0].text.strip())
                logger.info(f"Attempting to parse page update: {response_text}")
                page_update = json.loads(response_text)
                logger.info(f"Successfully parsed update for page: {page.name}")
                return page_update
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse page update: {str(e)}")
                logger.error(f"Raw text that failed to parse: {response_text}")
                raise
                
        except Exception as e:
            logger.error(f"Error getting page update from Claude: {str(e)}")
            raise

    def update_page(self, page: AppPage, update_prompt: str) -> AppPage:
        """Update a page based on the provided prompt."""
        try:
            logger.info(f"Starting page update for page {page.id}")
            
            # Get the updated page structure
            page_update = self._get_page_update(page, update_prompt)
            
            # Update the page
            page.template_content = page_update['template']
            page.js_content = page_update.get('js', '')
            page.save()
            
            # Update or create context queries
            existing_contexts = {ctx.context_key: ctx for ctx in page.contextquery_set.all()}
            
            for ctx_data in page_update.get('contexts', []):
                if ctx_data['key'] in existing_contexts:
                    # Update existing context
                    ctx = existing_contexts[ctx_data['key']]
                    ctx.query_content = ctx_data['query']
                    ctx.save()
                else:
                    # Create new context
                    ContextQuery.objects.create(
                        page=page,
                        context_key=ctx_data['key'],
                        query_content=ctx_data['query'],
                        query_type='orm'
                    )
            
            logger.info(f"Successfully updated page {page.id}")
            return page
            
        except Exception as e:
            logger.error(f"Error updating page {page.id}: {str(e)}")
            raise 

    def update_app(self, app: App, update_content: str) -> App:
        """Update an existing app based on the update prompt."""
        try:
            logger.info(f"Starting app update for app {app.id}")
            self.prompt.status = 'PROCESSING'
            self.prompt.save()

            # Get app intent and requirements
            intent = self._get_app_intent(existing_app=app)
            
            # Update app details if needed
            if intent['PURPOSE'].strip() != app.description:
                # Generate new CSS if purpose/requirements changed
                app_css = self._get_app_css(
                    app_purpose=intent['PURPOSE'],
                    ui_requirements=intent['UI_REQUIREMENTS']
                )
                
                app.name = intent['PURPOSE'].split('\n')[0]  # First line as name
                app.description = intent['PURPOSE']
                app.css_content = app_css
                app.save()
            
            # Update data structure
            self._setup_data_structure(app, intent['DATA'])
            
            # Update pages
            for page_info in intent['PAGES'].split('\n'):
                if ':' in page_info:
                    page_name, page_purpose = page_info.split(':', 1)
                    page_name = page_name.strip()
                    page_purpose = page_purpose.strip()
                    
                    # Generate page components
                    template = self._get_page_template(
                        page_name=page_name,
                        page_purpose=page_purpose,
                        app_css=app.css_content
                    )
                    
                    js_logic = self._get_page_logic(
                        page_name=page_name,
                        page_purpose=page_purpose,
                        template=template,
                        app_css=app.css_content
                    )
                    
                    # Create or update page
                    page, created = AppPage.objects.update_or_create(
                        app=app,
                        name=page_name,
                        defaults={
                            'template_content': template,
                            'js_content': js_logic,
                            'slug': page_name.lower().replace(' ', '-')
                        }
                    )
            
            self.prompt.status = 'COMPLETED'
            self.prompt.save()
            logger.info(f"Successfully updated app {app.id}")
            
            return app
            
        except Exception as e:
            logger.error(f"Error updating app {app.id}: {str(e)}")
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            raise

    def _get_app_intent(self, existing_app: App = None) -> dict:
        """Determine user intent and app requirements."""
        try:
            # Load and format the intent prompt
            intent_template = self._load_prompt_template('app_intent')
            
            # Format app info if it exists
            app_info = "None" if not existing_app else f"""
            Name: {existing_app.name}
            Description: {existing_app.description}
            Pages: {', '.join(p.name for p in existing_app.pages.all())}
            Data: {', '.join(f'{d.key} ({d.value_type})' for d in existing_app.data_store.all())}
            """
            
            formatted_prompt = intent_template.replace('{app_info}', app_info)
            formatted_prompt = formatted_prompt.replace('{user_prompt}', self.prompt.content)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                temperature=0.7,
                messages=[{"role": "user", "content": formatted_prompt}]
            )
            
            # Parse the structured response
            response = message.content[0].text.strip()
            sections = {}
            current_section = None
            current_content = []
            
            for line in response.split('\n'):
                if ':' in line and line.split(':')[0].isupper():
                    if current_section:
                        sections[current_section] = '\n'.join(current_content).strip()
                        current_content = []
                    current_section = line.split(':')[0].strip()
                else:
                    current_content.append(line)
            
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()
            
            return sections
            
        except Exception as e:
            logger.error(f"Error getting app intent: {str(e)}")
            raise

    def _get_app_css(self, app_purpose: str, ui_requirements: str) -> str:
        """Generate app-wide CSS."""
        try:
            css_template = self._load_prompt_template('app_styling')
            formatted_prompt = css_template.replace('{app_purpose}', app_purpose)
            formatted_prompt = formatted_prompt.replace('{ui_requirements}', ui_requirements)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[{"role": "user", "content": formatted_prompt}]
            )
            
            return message.content[0].text.strip()
            
        except Exception as e:
            logger.error(f"Error generating app CSS: {str(e)}")
            raise

    def _get_page_template(self, page_name: str, page_purpose: str, app_css: str) -> str:
        """Generate HTML template for a page."""
        try:
            template_prompt = self._load_prompt_template('page_template')
            formatted_prompt = template_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{page_purpose}', page_purpose)
            formatted_prompt = formatted_prompt.replace('{app_css}', app_css)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[{"role": "user", "content": formatted_prompt}]
            )
            
            return message.content[0].text.strip()
            
        except Exception as e:
            logger.error(f"Error generating page template: {str(e)}")
            raise

    def _get_page_logic(self, page_name: str, page_purpose: str, template: str, app_css: str) -> str:
        """Generate JavaScript logic for a page."""
        try:
            logic_prompt = self._load_prompt_template('page_logic')
            formatted_prompt = logic_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{page_purpose}', page_purpose)
            formatted_prompt = formatted_prompt.replace('{page_template}', template)
            formatted_prompt = formatted_prompt.replace('{app_css}', app_css)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[{"role": "user", "content": formatted_prompt}]
            )
            
            return message.content[0].text.strip()
            
        except Exception as e:
            logger.error(f"Error generating page logic: {str(e)}")
            raise

    def generate_app_v2(self) -> App:
        """Generate an app using the split prompting approach for better reliability."""
        try:
            # Step 1: Get app metadata
            app_metadata = self._get_app_metadata()
            
            # Create the app
            app = App.objects.create(
                organization=self.organization,
                name=app_metadata['name'],
                description=app_metadata.get('description', ''),
                initial_prompt=self.prompt,
                status='ACTIVE'
            )
            
            # Step 2: Get pages structure
            pages_structure = self._get_app_pages_structure(app_metadata)
            
            # Step 3: Generate each page with split concerns
            self._create_pages(app, pages_structure)
            
            # Step 4: Set up initial data structure if defined
            if 'data_structure' in app_metadata:
                self._setup_data_structure(app, app_metadata['data_structure'])
            
            return app

        except Exception as e:
            logger.error(f"Error in generate_app_v2: {str(e)}")
            raise 

    def _get_app_metadata(self) -> dict:
        """Get basic app metadata including name, description, and theme."""
        try:
            metadata_template = self._load_prompt_template('app_metadata')
            formatted_prompt = metadata_template.replace('{prompt_content}', self.prompt.content)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            response_text = self._clean_json_response(message.content[0].text.strip())
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Error getting app metadata: {str(e)}")
            raise

    def _get_app_pages_structure(self, app_metadata: dict) -> list:
        """Get the structure of pages for the app."""
        try:
            pages_template = self._load_prompt_template('app_pages')
            formatted_prompt = pages_template.replace('{prompt_content}', self.prompt.content)
            formatted_prompt = formatted_prompt.replace('{app_metadata}', json.dumps(app_metadata))
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=2000,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            response_text = self._clean_json_response(message.content[0].text.strip())
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Error getting app pages structure: {str(e)}")
            raise

    def _get_page_context(self, page_name: str, template: str) -> list:
        """Get the context variables needed for a page template."""
        try:
            context_prompt = self._load_prompt_template('page_context')
            formatted_prompt = context_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{template}', template)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            response_text = self._clean_json_response(message.content[0].text.strip())
            return json.loads(response_text)
        except Exception as e:
            logger.error(f"Error getting page context for {page_name}: {str(e)}")
            raise

    def _get_page_template(self, page_name: str, page_description: str) -> str:
        """Get the HTML template for a specific page."""
        try:
            template_prompt = self._load_prompt_template('page_template')
            formatted_prompt = template_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{page_description}', page_description)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=2000,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            return message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error getting page template for {page_name}: {str(e)}")
            raise

    def _get_page_logic(self, page_name: str, template: str, base_css: str) -> str:
        """Get the JavaScript logic for a specific page."""
        try:
            logic_prompt = self._load_prompt_template('page_logic')
            formatted_prompt = logic_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{template}', template)
            formatted_prompt = formatted_prompt.replace('{base_css}', base_css)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": formatted_prompt}]
                    }
                ]
            )
            
            return message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error getting page logic for {page_name}: {str(e)}")
            raise

    def generate_app_v2(self) -> App:
        """Generate an app using the split prompting approach for better reliability."""
        try:
            # Step 1: Get app metadata
            app_metadata = self._get_app_metadata()
            
            # Create the app
            app = App.objects.create(
                organization=self.organization,
                name=app_metadata['name'],
                description=app_metadata.get('description', ''),
                initial_prompt=self.prompt,
                status='ACTIVE'
            )
            
            # Step 2: Get pages structure
            pages_structure = self._get_app_pages_structure(app_metadata)
            
            # Step 3: Generate each page with split concerns
            self._create_pages(app, pages_structure)
            
            # Step 4: Set up initial data structure if defined
            if 'data_structure' in app_metadata:
                self._setup_data_structure(app, app_metadata['data_structure'])
            
            return app

        except Exception as e:
            logger.error(f"Error in generate_app_v2: {str(e)}")
            raise 