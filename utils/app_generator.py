import anthropic
from django.conf import settings
from anything_apps.models import App, AppPage, DataStore, ContextQuery, Prompt
from anything_org.models import Organization
from django.contrib.staticfiles.finders import find
import json
import logging
import os
import re
import inspect

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if getattr(settings, 'DEBUG', False) else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Get DEBUG setting, defaulting to False if not set
DEBUG = getattr(settings, 'DEBUG', False)

def debug_log(message: str, extra: dict = None) -> None:
    """Helper function to log debug messages only when DEBUG is enabled"""
    if DEBUG:  # Use the global DEBUG setting
        try:
            if extra:
                # Handle non-serializable objects in extra
                cleaned_extra = {k: str(v) if not isinstance(v, (str, int, float, bool, list, dict)) else v 
                               for k, v in extra.items()}
                logger.debug(f"{message} | Extra: {json.dumps(cleaned_extra, default=str)}")
            else:
                logger.debug(message)
        except Exception as e:
            logger.error(f"Error in debug_log: {str(e)}")
            logger.debug(message)  # Still log the message even if extras fail

# Add a startup debug log to verify logging is working
debug_log("AppGenerator module initialized", {"debug_enabled": DEBUG})

class AppGenerator:
    def __init__(self, organization: Organization, prompt: Prompt):
        debug_log("Initializing AppGenerator", {
            "organization_id": str(organization.id),  # Convert UUID to string
            "prompt_id": str(prompt.id)
        })
        self.organization = organization
        self.prompt = prompt
        self.claude = anthropic.Client(
            api_key=settings.ANTHROPIC_API_KEY
        )
        self.base_prompt_path = os.path.join(settings.BASE_DIR, 'static', 'prompts')
        debug_log("AppGenerator initialized successfully")

    def _load_prompt_template(self, template_name: str) -> str:
        """Load a prompt template using Django's static file finders."""
        debug_log(f"Loading prompt template: {template_name}")
        
        # First try to find the template with .txt extension
        template_path = find(f'prompts/{template_name}.txt')
        if not template_path:
            # Try without extension as fallback
            template_path = find(f'prompts/{template_name}')
            
        if not template_path:
            error_msg = f"Could not find prompt template: prompts/{template_name}.txt"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
            
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
                debug_log(f"Successfully loaded template: {template_name}", {
                    "template_length": len(template_content),
                    "template_path": template_path
                })
                return template_content
        except Exception as e:
            error_msg = f"Error loading prompt template {template_name}: {str(e)}"
            logger.error(error_msg)
            debug_log("Template loading failed", {
                "template_name": template_name,
                "error": str(e),
                "template_path": template_path
            })
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
                # Each data_def should now include table_name
                DataStore.objects.create(
                    app=app,
                    table_name=data_def['table_name'],
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
                
                # Create or update context queries for the page
                for ctx in context:
                    ContextQuery.objects.update_or_create(
                        page=page,
                        context_key=ctx['key'],
                        defaults={
                            'query_content': ctx['query'],
                            'query_type': 'orm'  # Default to ORM queries
                        }
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
        """Generate the complete app."""
        try:
            debug_log(f"Starting app generation for prompt {self.prompt.id}")
            self.prompt.status = 'PROCESSING'
            self.prompt.save()

            # Get app name and description
            debug_log("Getting app name and description")
            name, description = self._get_app_name_and_description()
            debug_log("Got app name and description", {
                "name": name,
                "description": description
            })
            
            # Create the app
            debug_log("Creating app instance")
            app = App.objects.create(
                organization=self.organization,
                name=name,
                description=description,
                initial_prompt=self.prompt,
                status='ACTIVE'
            )
            debug_log(f"Created app instance with ID: {app.id}")

            # Get data structure
            debug_log("Getting data tables structure")
            tables = self._get_data_tables()
            debug_log(f"Got {len(tables)} data tables")
            
            # Set up data structure
            debug_log("Setting up data structure")
            for table in tables:
                debug_log(f"Processing table: {table['table_name']}")
                for column in table['columns']:
                    DataStore.objects.create(
                        app=app,
                        table_name=table['table_name'],
                        key=column['key'],
                        value='',  # Empty initial value
                        value_type=column['value_type']
                    )
                debug_log(f"Completed setup for table: {table['table_name']}")

            # Get pages
            debug_log("Getting page list")
            pages = self._get_page_list()
            debug_log(f"Got {len(pages)} pages")
            
            # Create pages
            for page_data in pages:
                debug_log(f"Processing page: {page_data['name']}")
                
                # Get page template
                debug_log(f"Getting template for page: {page_data['name']}")
                template = self._get_page_template(
                    page_data['name'],
                    page_data['description'],
                    tables
                )
                
                # Get page JavaScript
                debug_log(f"Getting JavaScript for page: {page_data['name']}")
                js_logic = self._get_page_js(
                    page_data['name'],
                    template
                )
                
                # Get page queries
                debug_log(f"Getting queries for page: {page_data['name']}")
                queries = self._get_page_queries(
                    page_data['name'],
                    template,
                    tables
                )
                
                # Create the page
                debug_log(f"Creating page instance: {page_data['name']}")
                page = AppPage.objects.create(
                    app=app,
                    name=page_data['name'],
                    slug=page_data['slug'],
                    template_content=template,
                    js_content=js_logic
                )
                
                # Create context queries
                debug_log(f"Creating context queries for page: {page_data['name']}")
                for query in queries:
                    ContextQuery.objects.create(
                        page=page,
                        context_key=query['key'],
                        query_content=query['query'],
                        query_type='orm'
                    )
                debug_log(f"Completed processing page: {page_data['name']}")

            self.prompt.status = 'COMPLETED'
            self.prompt.save()
            debug_log(f"Successfully completed app generation for prompt {self.prompt.id}")

            return app

        except Exception as e:
            error_msg = f"Error in app generation for prompt {self.prompt.id}: {str(e)}"
            logger.error(error_msg)
            debug_log(f"App generation failed: {str(e)}")
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            
            if app:
                app.status = 'ERROR'
                app.save()
                
            raise

    def _get_app_name_and_description(self) -> tuple[str, str]:
        """Get the app name and description."""
        debug_log("Getting app name and description from Claude")
        prompt = """You are an expert app architect. Based on this app idea, provide a concise name (max 3-4 words) and description (1-2 sentences).
        Respond in this exact format:
        NAME: [app name]
        DESCRIPTION: [app description]

        App idea: {prompt}"""
        
        message = self.claude.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt.format(prompt=self.prompt.content)}]
        )
        
        response = message.content[0].text.strip()
        name = response.split('NAME: ')[1].split('\n')[0].strip()
        description = response.split('DESCRIPTION: ')[1].strip()
        
        debug_log("Got app name and description", {
            "name": name,
            "description": description
        })
        return name, description

    def _get_data_tables(self) -> list[dict]:
        """Get the data table structure."""
        debug_log("Getting data table structure from Claude")
        prompt = """You are an expert database architect. Based on this app idea, list the tables needed and their columns.
        For each table, provide:
        1. A clear table name
        2. Each column with its name and type (str, int, float, bool, json, date, datetime)
        3. A brief description of what the column represents

        Format each table like this:
        TABLE: [table name]
        COLUMNS:
        [column name] | [type] | [description]
        
        App idea: {prompt}"""
        
        message = self.claude.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt.format(prompt=self.prompt.content)}]
        )
        
        response = message.content[0].text.strip()
        tables = []
        current_table = None
        
        debug_log("Parsing data table response")
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('TABLE: '):
                if current_table:
                    tables.append(current_table)
                    debug_log(f"Added table: {current_table['table_name']}")
                current_table = {'table_name': line[7:].strip(), 'columns': []}
            elif line and '|' in line and current_table:
                col_parts = [p.strip() for p in line.split('|')]
                if len(col_parts) == 3:
                    current_table['columns'].append({
                        'key': col_parts[0],
                        'value_type': col_parts[1],
                        'description': col_parts[2]
                    })
                    debug_log(f"Added column {col_parts[0]} to table {current_table['table_name']}")
        
        if current_table:
            tables.append(current_table)
            debug_log(f"Added final table: {current_table['table_name']}")
        
        debug_log(f"Completed data table structure with {len(tables)} tables")
        return tables

    def _get_page_list(self) -> list[dict]:
        """Get the list of pages needed."""
        debug_log("Getting page list from Claude")
        prompt = """You are an expert UI/UX architect. Based on this app idea, list the pages needed.
        For each page provide:
        1. A clear, concise name
        2. A URL-friendly slug
        3. A brief description of the page's purpose

        Format each page like this:
        PAGE: [page name]
        SLUG: [url-friendly-slug]
        PURPOSE: [brief description]
        
        App idea: {prompt}"""
        
        message = self.claude.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2000,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt.format(prompt=self.prompt.content)}]
        )
        
        response = message.content[0].text.strip()
        pages = []
        current_page = None
        
        debug_log("Parsing page list response")
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('PAGE: '):
                if current_page:
                    pages.append(current_page)
                    debug_log(f"Added page: {current_page['name']}")
                current_page = {'name': line[6:].strip()}
            elif line.startswith('SLUG: ') and current_page:
                current_page['slug'] = line[6:].strip()
            elif line.startswith('PURPOSE: ') and current_page:
                current_page['description'] = line[9:].strip()
        
        if current_page:
            pages.append(current_page)
            debug_log(f"Added final page: {current_page['name']}")
        
        debug_log(f"Completed page list with {len(pages)} pages")
        return pages

    def _get_page_template(self, page_name: str, page_description: str, tables: list[dict]) -> str:
        """Get the HTML template for a specific page."""
        try:
            debug_log(f"Getting template for page {page_name}")
            template_prompt = self._load_prompt_template('page_template')
            formatted_prompt = template_prompt.replace('{page_name}', page_name)
            formatted_prompt = formatted_prompt.replace('{page_description}', page_description)
            formatted_prompt = formatted_prompt.replace('{tables}', json.dumps(tables, indent=2))
            
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
            
            template_content = message.content[0].text.strip()
            debug_log(f"Generated template for page {page_name}", {
                "template_length": len(template_content)
            })
            return template_content
        except Exception as e:
            logger.error(f"Error getting page template for {page_name}: {str(e)}")
            debug_log(f"Template generation failed for page {page_name}", {
                "error": str(e)
            })
            raise

    def _get_page_js(self, page_name: str, template: str) -> str:
        """Get the JavaScript logic for a specific page."""
        debug_log(f"Getting JavaScript for page {page_name}")
        
        # Load the page_logic prompt template
        prompt_template = self._load_prompt_template('page_logic')
        
        # Get the app CSS from the app's DataStore
        try:
            app_css = self.prompt.app.css_content if hasattr(self.prompt, 'app') else ''
        except Exception:
            app_css = ''  # Default to empty if not found
            
        # Extract page purpose from the template's first comment if available
        page_purpose = ''
        if template.strip().startswith('<!--'):
            purpose_match = re.search(r'<!--\s*(.*?)\s*-->', template)
            if purpose_match:
                page_purpose = purpose_match.group(1)
        
        formatted_prompt = prompt_template.replace('{page_name}', page_name)
        formatted_prompt = formatted_prompt.replace('{page_template}', template)
        formatted_prompt = formatted_prompt.replace('{page_purpose}', page_purpose)
        formatted_prompt = formatted_prompt.replace('{app_css}', app_css)
        
        message = self.claude.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=4096,
            temperature=0.7,
            messages=[{
                "role": "user", 
                "content": formatted_prompt
            }]
        )
        
        # Extract only the JavaScript code, removing any explanatory text
        js_content = message.content[0].text.strip()
        
        # If the response contains markdown code blocks, extract only the code
        if '```' in js_content:
            js_blocks = re.findall(r'```(?:javascript|js)?\n(.*?)```', js_content, re.DOTALL)
            if js_blocks:
                js_content = js_blocks[0].strip()
        
        debug_log(f"Generated JavaScript for page {page_name}", {
            "js_length": len(js_content),
            "has_purpose": bool(page_purpose),
            "has_css": bool(app_css)
        })
        return js_content

    def _get_page_queries(self, page_name: str, template: str, tables: list[dict]) -> list[dict]:
        """Get the context queries needed for a page."""
        debug_log(f"Getting queries for page {page_name}")
        
        # Get DataStore model information using inspect
        datastore_info = {
            "fields": [field.name for field in DataStore._meta.get_fields()],
            "methods": [method[0] for method in inspect.getmembers(DataStore, predicate=inspect.isfunction)],
            "model_source": inspect.getsource(DataStore)
        }
        
        # Load the page_context prompt template
        prompt_template = self._load_prompt_template('page_context')
        formatted_prompt = prompt_template.replace('{page_name}', page_name)
        formatted_prompt = formatted_prompt.replace('{template}', template)
        formatted_prompt = formatted_prompt.replace('{datastore_model}', datastore_info['model_source'])
        formatted_prompt = formatted_prompt.replace('{tables}', json.dumps(tables, indent=2))
        
        message = self.claude.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2000,
            temperature=0.7,
            messages=[{
                "role": "user", 
                "content": formatted_prompt
            }]
        )
        
        try:
            # Parse the JSON response directly
            response = message.content[0].text.strip()
            
            # If the response contains markdown code blocks, extract only the code
            if '```' in response:
                json_blocks = re.findall(r'```(?:json)?\n(.*?)```', response, re.DOTALL)
                if json_blocks:
                    response = json_blocks[0].strip()
            
            queries = json.loads(response)
            
            debug_log(f"Successfully parsed {len(queries)} queries for page {page_name}")
            return queries
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse queries response: {str(e)}")
            debug_log("Attempting to parse non-JSON response")
            
            # Fallback parsing for non-JSON responses
            queries = []
            current_query = None
            
            for line in response.split('\n'):
                line = line.strip()
                if line.startswith('QUERY NAME: '):
                    if current_query:
                        queries.append(current_query)
                        debug_log(f"Added query: {current_query['key']}")
                    current_query = {'key': line[12:].strip()}
                elif line.startswith('QUERY: ') and current_query:
                    current_query['query'] = line[7:].strip()
                elif line.startswith('PURPOSE: ') and current_query:
                    current_query['description'] = line[9:].strip()
            
            if current_query:
                queries.append(current_query)
                debug_log(f"Added final query: {current_query['key']}")
            
            debug_log(f"Completed queries for page {page_name} with {len(queries)} queries")
            return queries

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
    table_name = models.CharField(max_length=100)
    key = models.CharField(max_length=100, help_text="Column name in the abstract table")
    value = models.TextField()
    value_type = models.CharField(max_length=10, choices=VALUE_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['app', 'table_name']

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
                    "table_name": ds.table_name,
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
            debug_log(f"Starting page update for page {page.id}")
            
            # Get the updated page structure
            debug_log(f"Getting updated page structure for page {page.name}")
            page_update = self._get_page_update(page, update_prompt)
            debug_log("Got updated page structure", {
                "has_template": bool(page_update.get('template')),
                "has_js": bool(page_update.get('js')),
                "context_count": len(page_update.get('contexts', []))
            })
            
            # Update the page
            debug_log(f"Updating page content for {page.name}")
            page.template_content = page_update['template']
            page.js_content = page_update.get('js', '')
            page.save()
            
            # Update or create context queries
            existing_contexts = {ctx.context_key: ctx for ctx in page.contextquery_set.all()}
            
            debug_log(f"Updating context queries for page {page.name}")
            for ctx_data in page_update.get('contexts', []):
                if ctx_data['key'] in existing_contexts:
                    # Update existing context
                    debug_log(f"Updating existing context: {ctx_data['key']}")
                    ctx = existing_contexts[ctx_data['key']]
                    ctx.query_content = ctx_data['query']
                    ctx.save()
                else:
                    # Create new context
                    debug_log(f"Creating new context: {ctx_data['key']}")
                    ContextQuery.objects.create(
                        page=page,
                        context_key=ctx_data['key'],
                        query_content=ctx_data['query'],
                        query_type='orm'
                    )
            
            debug_log(f"Successfully updated page {page.id}")
            return page
            
        except Exception as e:
            error_msg = f"Error updating page {page.id}: {str(e)}"
            logger.error(error_msg)
            debug_log(f"Page update failed: {str(e)}")
            raise

    def update_app(self, app: App, update_content: str) -> App:
        """Update an existing app based on the update prompt."""
        try:
            debug_log(f"Starting app update for app {app.id}")
            self.prompt.status = 'PROCESSING'
            self.prompt.save()

            # Get app intent and requirements
            debug_log("Getting updated app intent")
            intent = self._get_app_intent(existing_app=app)
            debug_log("Got app intent", {
                "has_purpose": bool(intent.get('PURPOSE')),
                "has_ui_requirements": bool(intent.get('UI_REQUIREMENTS')),
                "has_data": bool(intent.get('DATA')),
                "has_pages": bool(intent.get('PAGES'))
            })
            
            # Update app details if needed
            if intent['PURPOSE'].strip() != app.description:
                debug_log("Updating app details and generating new CSS")
                # Generate new CSS if purpose/requirements changed
                app_css = self._get_app_css(
                    app_purpose=intent['PURPOSE'],
                    ui_requirements=intent['UI_REQUIREMENTS']
                )
                
                app.name = intent['PURPOSE'].split('\n')[0]  # First line as name
                app.description = intent['PURPOSE']
                app.css_content = app_css
                app.save()
                debug_log("Updated app details")
            
            # Update data structure
            debug_log("Updating data structure")
            self._setup_data_structure(app, intent['DATA'])
            
            # Update pages
            debug_log("Updating pages")
            for page_info in intent['PAGES'].split('\n'):
                if ':' in page_info:
                    page_name, page_purpose = page_info.split(':', 1)
                    page_name = page_name.strip()
                    page_purpose = page_purpose.strip()
                    
                    debug_log(f"Processing page update: {page_name}")
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
                    debug_log(f"Creating/updating page: {page_name}")
                    page, created = AppPage.objects.update_or_create(
                        app=app,
                        name=page_name,
                        defaults={
                            'template_content': template,
                            'js_content': js_logic,
                            'slug': page_name.lower().replace(' ', '-')
                        }
                    )
                    debug_log(f"{'Created' if created else 'Updated'} page: {page_name}")
            
            self.prompt.status = 'COMPLETED'
            self.prompt.save()
            debug_log(f"Successfully updated app {app.id}")
            
            return app
            
        except Exception as e:
            error_msg = f"Error updating app {app.id}: {str(e)}"
            logger.error(error_msg)
            debug_log(f"App update failed: {str(e)}")
            self.prompt.status = 'FAILED'
            self.prompt.error_message = str(e)
            self.prompt.save()
            raise

    def _get_app_intent(self, existing_app: App = None) -> dict:
        """Determine user intent and app requirements."""
        try:
            debug_log("Getting app intent", {
                "has_existing_app": existing_app is not None
            })
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
            debug_log("Parsing app intent response")
            response = message.content[0].text.strip()
            sections = {}
            current_section = None
            current_content = []
            
            for line in response.split('\n'):
                if ':' in line and line.split(':')[0].isupper():
                    if current_section:
                        sections[current_section] = '\n'.join(current_content).strip()
                        debug_log(f"Added section: {current_section}")
                        current_content = []
                    current_section = line.split(':')[0].strip()
                else:
                    current_content.append(line)
            
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()
                debug_log(f"Added final section: {current_section}")
            
            debug_log("Completed parsing app intent", {
                "section_count": len(sections),
                "sections": list(sections.keys())
            })
            return sections
            
        except Exception as e:
            error_msg = f"Error getting app intent: {str(e)}"
            logger.error(error_msg)
            debug_log(f"App intent failed: {str(e)}")
            raise

    def _get_app_css(self, app_purpose: str, ui_requirements: str) -> str:
        """Generate app-wide CSS."""
        try:
            debug_log("Generating app-wide CSS")
            css_template = self._load_prompt_template('app_styling')
            formatted_prompt = css_template.replace('{app_purpose}', app_purpose)
            formatted_prompt = formatted_prompt.replace('{ui_requirements}', ui_requirements)
            
            message = self.claude.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4096,
                temperature=0.7,
                messages=[{"role": "user", "content": formatted_prompt}]
            )
            
            css_content = message.content[0].text.strip()
            debug_log("Generated app-wide CSS", {
                "css_length": len(css_content)
            })
            return css_content
            
        except Exception as e:
            error_msg = f"Error generating app CSS: {str(e)}"
            logger.error(error_msg)
            debug_log(f"CSS generation failed: {str(e)}")
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