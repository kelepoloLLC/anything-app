import anthropic
from django.conf import settings
from anything_apps.models import App, AppPage, DataStore, ContextQuery, Prompt
from anything_org.models import Organization
from django.contrib.staticfiles.finders import find
import json
import logging
import os

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
            # Find the first { and last }
            start = response_text.find('{')
            end = response_text.rindex('}') + 1
            if start >= 0 and end > start:
                json_text = response_text[start:end]
                
                # First try to parse as is
                try:
                    json.loads(json_text)
                    return json_text
                except json.JSONDecodeError:
                    # If that fails, try to clean up the string
                    # First, normalize newlines
                    cleaned_text = json_text.replace('\r\n', '\n').replace('\r', '\n')
                    
                    # Handle escaped newlines in strings
                    in_string = False
                    string_char = None
                    result = []
                    i = 0
                    while i < len(cleaned_text):
                        char = cleaned_text[i]
                        
                        # Handle string boundaries
                        if char in ('"', "'") and (i == 0 or cleaned_text[i-1] != '\\'):
                            if not in_string:
                                in_string = True
                                string_char = char
                            elif char == string_char:
                                in_string = False
                                string_char = None
                        
                        # Handle newlines
                        if char == '\n':
                            if in_string:
                                result.append('\\n')
                            else:
                                result.append(' ')
                        else:
                            result.append(char)
                        
                        i += 1
                    
                    cleaned_text = ''.join(result)
                    
                    # Try to parse again
                    try:
                        json.loads(cleaned_text)
                        return cleaned_text
                    except json.JSONDecodeError:
                        # If still failing, try more aggressive cleaning
                        cleaned_text = cleaned_text.replace('\\"', '"')
                        cleaned_text = cleaned_text.replace('\\\\', '\\')
                        return cleaned_text
                        
            return response_text
        except ValueError:
            return response_text

    def _get_app_structure(self):
        """Get the high-level app structure and page definitions."""
        try:
            logger.info(f"Requesting initial app structure from Claude for prompt {self.prompt.id}")
            
            # Load and format the app structure prompt
            prompt_template = self._load_prompt_template('app_structure')
            formatted_prompt = prompt_template.format(
                prompt_content=self.prompt.content
            )
            
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
                
                # Load and format the page structure prompt
                page_prompt_template = self._load_prompt_template('page_structure')
                formatted_page_prompt = page_prompt_template.format(
                    page_name=page['name'],
                    page_description=page['description'],
                    page_slug=page['slug'],
                    data_structure=json.dumps(initial_structure['data_structure'], indent=2)
                )
                
                page_message = self.claude.messages.create(
                    model="claude-3-sonnet-20240229",
                    max_tokens=2000,
                    temperature=0.7,
                    messages=[
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": formatted_page_prompt}]
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

    def _get_page_update(self, page: AppPage, update_prompt: str) -> dict:
        """Generate an updated page structure based on the update prompt."""
        try:
            logger.info(f"Requesting page update from Claude for page {page.id}")
            
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
            formatted_prompt = prompt_template.format(
                page_name=page.name,
                page_slug=page.slug,
                data_structure=json.dumps(data_structure, indent=2),
                template_content=page.template_content,
                js_content=page.js_content,
                css_content=page.css_content,
                update_prompt=update_prompt
            )
            
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

            # Load and format the app update prompt
            prompt_template = self._load_prompt_template('app_update')
            formatted_prompt = prompt_template.format(
                app_name=app.name,
                app_description=app.description,
                data_structure=json.dumps([{
                    'key': ds.key,
                    'value_type': ds.value_type,
                    'value': ds.value
                } for ds in app.data_store.all()], indent=2),
                pages=json.dumps([{
                    'name': p.name,
                    'slug': p.slug,
                    'description': 'Existing page'
                } for p in app.pages.all()], indent=2),
                update_content=update_content
            )

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
.page-details {
  padding: 2rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.page-actions {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.search-box {
  min-width: 300px;
}

.data-grid {
  display: grid;
  gap: 1rem;
  margin-bottom: 2rem;
}

.data-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  padding: 1rem;
  background: #f8f9fa;
  border-radius: 0.5rem;
  align-items: center;
}

.data-cell {
  flex: 1;
  min-width: 200px;
}

.row-actions {
  display: flex;
  gap: 0.5rem;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
}

.current-page {
  padding: 0.5rem 1rem;
  background: #f8f9fa;
  border-radius: 0.25rem;
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
                    context_key='paginated_data',
                    query_content='from django.core.paginator import Paginator\npaginator = Paginator(DataStore.objects.filter(app=app), 10)  # 10 items per page\npage_number = request.GET.get("page", 1)\npaginated_data = paginator.get_page(page_number)',
                    query_type='orm'
                )

                ContextQuery.objects.create(
                    page=page,
                    context_key='data_structure',
                    query_content='data_structure = [{"key": ds.key, "value_type": ds.value_type, "input_type": "text" if ds.value_type in ["str", "date", "datetime"] else ds.value_type} for ds in DataStore.objects.filter(app=app)]',
                    query_type='orm'
                )

            logger.info(f"Successfully updated app {app.id}")
            return app

        except Exception as e:
            logger.error(f"Error updating app {app.id}: {str(e)}")
            raise 