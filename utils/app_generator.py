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

            # Find the first { and last }
            start = response_text.find('{')
            end = response_text.rindex('}') + 1
            
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
            
            # Load and format the app structure prompt
            prompt_template = self._load_prompt_template('app_structure')
            formatted_prompt = prompt_template.replace('{datastore_model}', datastore_model)
            formatted_prompt = formatted_prompt.replace('{prompt_content}', self.prompt.content)
            
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
                
                # First get the page structure without detailed CSS
                page_structure = self._get_page_structure(page, initial_structure)
                
                # Then get the detailed CSS
                try:
                    css_content = self._get_page_css(page['name'], initial_structure.get('theme', {}))
                    page_structure['css'] = css_content
                except Exception as e:
                    logger.error(f"Failed to generate CSS for {page['name']}: {str(e)}")
                    # Use minimal CSS if detailed CSS generation fails
                    page_structure['css'] = "/* Minimal CSS */"
                
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
        """Generate page structure without detailed CSS."""
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
                
                # Construct the page structure
                page_structure = sections['METADATA']
                page_structure['template'] = sections['TEMPLATE']
                page_structure['js'] = sections.get('JAVASCRIPT', '')  # JavaScript is optional
                
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
            formatted_prompt = formatted_prompt.replace('{css_content}', page.css_content)
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
            page.css_content = page_update.get('css', '')
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

            # Load and format the app update prompt
            prompt_template = self._load_prompt_template('app_update')
            # Replace placeholders with actual values
            formatted_prompt = prompt_template.replace('{app_name}', app.name)
            formatted_prompt = formatted_prompt.replace('{app_description}', app.description)
            formatted_prompt = formatted_prompt.replace('{data_structure}', json.dumps([{
                'key': ds.key,
                'value_type': ds.value_type,
                'value': ds.value
            } for ds in app.data_store.all()], indent=2))
            formatted_prompt = formatted_prompt.replace('{pages}', json.dumps([{
                'name': p.name,
                'slug': p.slug,
                'description': 'Existing page'
            } for p in app.pages.all()], indent=2))
            formatted_prompt = formatted_prompt.replace('{update_content}', update_content)
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
                # Parse the updated structure
                response_text = self._clean_json_response(message.content[0].text.strip())
                logger.info(f"Attempting to parse updated structure: {response_text}")
                updated_structure = json.loads(response_text)
                logger.info(f"Successfully parsed updated app structure")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse updated structure: {str(e)}")
                logger.error(f"Raw text that failed to parse: {response_text}")
                raise

            # Update app details
            app.name = updated_structure['name']
            app.description = updated_structure['description']
            app.save()

            # Update data structure
            current_data_keys = set(app.data_store.values_list('key', flat=True))
            new_data_keys = {data['key'] for data in updated_structure['data_structure']}

            # Remove deleted data stores
            app.data_store.filter(key__in=current_data_keys - new_data_keys).delete()

            # Update or create data stores
            for data_def in updated_structure['data_structure']:
                DataStore.objects.update_or_create(
                    app=app,
                    key=data_def['key'],
                    defaults={
                        'value_type': data_def['value_type'],
                        'value': ''  # Keep existing value if updating
                    }
                )

            # Now generate detailed page structures and update pages
            current_page_slugs = set(app.pages.values_list('slug', flat=True))
            new_page_slugs = {page['slug'] for page in updated_structure['pages']}

            # Remove deleted pages
            app.pages.filter(slug__in=current_page_slugs - new_page_slugs).delete()

            # Update or create pages
            for page_def in updated_structure['pages']:
                # Define the base template content
                template = r'''
<div class="page-details" data-controller="page-details">
  <div class="page-header">
    <h1>{{ page.name }}</h1>
    <div class="page-actions">
      <button class="btn btn-primary" data-action="click->page-details#showAddForm">Add Data</button>
      <div class="search-box">
        <input type="text" class="form-control" placeholder="Search..." data-page-details-target="searchInput" data-action="input->page-details#filterData">
      </div>
    </div>
  </div>

  <div class="data-grid" data-page-details-target="dataGrid">
    {% for item in paginated_data %}
    <div class="data-row" data-item-id="{{ item.id }}">
      {% for field, value in item.items %}
      <div class="data-cell">
        <strong>{{ field }}</strong> {{ value }}
      </div>
      {% endfor %}
      <div class="row-actions">
        <button class="btn btn-sm btn-danger" data-action="click->page-details#deleteItem" data-item-id="{{ item.id }}">Delete</button>
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="pagination">
    {% if paginated_data.has_previous %}
    <a href="?page={{ paginated_data.previous_page_number }}" class="btn btn-outline-primary">Previous</a>
    {% endif %}
    <span class="current-page">Page {{ paginated_data.number }} of {{ paginated_data.paginator.num_pages }}</span>
    {% if paginated_data.has_next %}
    <a href="?page={{ paginated_data.next_page_number }}" class="btn btn-outline-primary">Next</a>
    {% endif %}
  </div>

  <div class="modal fade" id="addDataModal" tabindex="-1" data-page-details-target="addModal">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Add New Data</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">
          <form data-action="submit->page-details#addData">
            {% for field in data_structure %}
            <div class="mb-3">
              <label class="form-label">{{ field.key }}</label>
              <input type="{{ field.input_type }}" class="form-control" name="{{ field.key }}" required>
            </div>
            {% endfor %}
            <button type="submit" class="btn btn-primary">Save</button>
          </form>
        </div>
      </div>
    </div>
  </div>
</div>
'''
                # Define the Stimulus controller
                js = r'''
import { Controller } from '@hotwired/stimulus'

export default class extends Controller {
  static targets = ['dataGrid', 'searchInput', 'addModal']

  connect() {
    this.originalData = Array.from(this.dataGridTarget.children)
  }

  filterData() {
    const searchTerm = this.searchInputTarget.value.toLowerCase()
    this.originalData.forEach(row => {
      const text = row.textContent.toLowerCase()
      row.style.display = text.includes(searchTerm) ? '' : 'none'
    })
  }

  showAddForm() {
    const modal = new bootstrap.Modal(this.addModalTarget)
    modal.show()
  }

  async addData(event) {
    event.preventDefault()
    const form = event.target
    const formData = new FormData(form)

    try {
      const response = await fetch(window.location.pathname + '/add-data/', {
        method: 'POST',
        body: formData,
        headers: {
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        }
      })

      if (response.ok) {
        window.location.reload()
      } else {
        throw new Error('Failed to add data')
      }
    } catch (error) {
      console.error('Error adding data:', error)
      alert('Failed to add data. Please try again.')
    }
  }

  async deleteItem(event) {
    if (!confirm('Are you sure you want to delete this item?')) return

    const itemId = event.target.dataset.itemId
    try {
      const response = await fetch(`${window.location.pathname}/delete-data/${itemId}/`, {
        method: 'DELETE',
        headers: {
          'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        }
      })

      if (response.ok) {
        event.target.closest('.data-row').remove()
      } else {
        throw new Error('Failed to delete item')
      }
    } catch (error) {
      console.error('Error deleting item:', error)
      alert('Failed to delete item. Please try again.')
    }
  }
}
'''
                # Define the CSS
                css = r'''
/* Base styles */
.page-details {
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

/* Header styles */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e5e7eb;
}

.page-header h1 {
  color: #111827;
  font-size: 1.875rem;
  font-weight: 600;
}

/* Form styles */
.form-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  color: #374151;
  margin-bottom: 0.5rem;
}

.form-control {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  background-color: #ffffff;
  color: #111827;
  font-size: 0.875rem;
}

.form-control:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

/* Button styles */
.btn {
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: 500;
  font-size: 0.875rem;
  transition: all 0.2s;
}

.btn-primary {
  background-color: #3b82f6;
  color: #ffffff;
  border: none;
}

.btn-primary:hover {
  background-color: #2563eb;
}

.btn-danger {
  background-color: #ef4444;
  color: #ffffff;
  border: none;
}

.btn-danger:hover {
  background-color: #dc2626;
}

/* Search box */
.search-box {
  min-width: 300px;
}

.search-box input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  background-color: #ffffff;
}

/* Data grid */
.data-grid {
  display: grid;
  gap: 1rem;
  margin-bottom: 2rem;
}

.data-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  padding: 1.25rem;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  align-items: center;
}

.data-cell {
  flex: 1;
  min-width: 200px;
  color: #374151;
}

.data-cell strong {
  color: #111827;
  font-weight: 500;
  margin-right: 0.5rem;
}

/* Modal styles */
.modal-content {
  background: #ffffff;
  border-radius: 0.5rem;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.modal-header {
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #e5e7eb;
}

.modal-title {
  color: #111827;
  font-weight: 600;
}

.modal-body {
  padding: 1.5rem;
}

/* Pagination */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  margin-top: 2rem;
}

.pagination a {
  padding: 0.5rem 1rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.375rem;
  color: #374151;
  text-decoration: none;
  transition: all 0.2s;
}

.pagination a:hover {
  background-color: #f3f4f6;
}

.current-page {
  padding: 0.5rem 1rem;
  background: #f3f4f6;
  border-radius: 0.375rem;
  color: #374151;
  font-weight: 500;
}
'''
                # Create or update the page
                page, created = AppPage.objects.update_or_create(
                    app=app,
                    slug=page_def['slug'],
                    defaults={
                        'name': page_def['name'],
                        'template_content': template.strip(),
                        'js_content': js.strip(),
                        'css_content': css.strip()
                    }
                )

                # Update context queries
                if not created:
                    page.context_queries.all().delete()

                # Create the standard context queries
                ContextQuery.objects.create(
                    page=page,
                    context_key='data',
                    query_content='data = DataStore.objects.filter(app=app).values()',
                    query_type='orm'
                )

                ContextQuery.objects.create(
                    page=page,
                    context_key='paginated_data',
                    query_content='''from django.core.paginator import Paginator
data = DataStore.objects.filter(app=app).values()
paginator = Paginator(data, 10)  # 10 items per page
page_number = request.GET.get("page", 1)
paginated_data = paginator.get_page(page_number)''',
                    query_type='orm'
                )

                ContextQuery.objects.create(
                    page=page,
                    context_key='data_structure',
                    query_content='data_structure = [{"key": ds.key, "value_type": ds.value_type, "input_type": "text" if ds.value_type in ["str", "date", "datetime"] else "number" if ds.value_type in ["int", "float"] else "checkbox" if ds.value_type == "bool" else "textarea" if ds.value_type == "json" else "text"} for ds in DataStore.objects.filter(app=app)]',
                    query_type='orm'
                )

            logger.info(f"Successfully updated app {app.id}")
            return app

        except Exception as e:
            logger.error(f"Error updating app {app.id}: {str(e)}")
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

    def _get_page_logic(self, page_name: str, template: str, context: list) -> str:
        """Get the JavaScript logic for a specific page."""
        try:
            logic_prompt = self._load_prompt_template('page_logic')
            formatted_prompt = logic_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{template}', template)
            formatted_prompt = formatted_prompt.replace('{context}', json.dumps(context))
            
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
            logger.error(f"Error getting page logic for {page_name}: {str(e)}")
            raise

    def _get_component_styles(self, theme: dict) -> str:
        """Get reusable component styles based on theme."""
        try:
            style_prompt = self._load_prompt_template('component_styles')
            formatted_prompt = style_prompt.replace('{theme}', json.dumps(theme))
            
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
            logger.error(f"Error getting component styles: {str(e)}")
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
                prompt=self.prompt
            )
            
            # Step 2: Get pages structure
            pages_structure = self._get_app_pages_structure(app_metadata)
            
            # Step 3: Generate each page with split concerns
            for page_data in pages_structure:
                # Get page template
                template = self._get_page_template(
                    page_data['name'],
                    page_data.get('description', '')
                )
                
                # Get page context
                context = self._get_page_context(page_data['name'], template)
                
                # Get page logic
                js_logic = self._get_page_logic(page_data['name'], template, context)
                
                # Get component styles
                component_styles = self._get_component_styles(app_metadata.get('theme', {}))
                
                # Create the page
                AppPage.objects.create(
                    app=app,
                    name=page_data['name'],
                    slug=page_data.get('slug', ''),
                    template=template,
                    js=js_logic,
                    css=component_styles
                )
                
                # Create context queries
                for ctx in context:
                    ContextQuery.objects.create(
                        page=page,
                        key=ctx['key'],
                        query=ctx['query'],
                        description=ctx.get('description', '')
                    )
            
            # Step 4: Set up initial data structure if defined
            if 'data_structure' in app_metadata:
                self._setup_data_structure(app, app_metadata['data_structure'])
            
            return app
            
        except Exception as e:
            logger.error(f"Error in generate_app_v2: {str(e)}")
            raise 