from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_q.tasks import async_task
from .models import App, Prompt, PromptUpdate, AppPage
from anything_org.models import Organization, OrganizationMember
from utils.tasks import generate_app_async
from django.urls import reverse
from django.conf import settings
from django.core.exceptions import PermissionDenied
import logging

@login_required
def app_list(request):
    """View to list user's apps across all organizations."""
    user_orgs = request.user.organizations.all()
    apps = App.objects.filter(organization__in=user_orgs).select_related('organization')
    
    return render(request, 'apps/list.html', {
        'apps': apps
    })

@login_required
def app_detail(request, app_id):
    """View to show app details."""
    app = get_object_or_404(App, id=app_id)
    
    # Check if user has access to the app
    if not app.organization.organizationmember_set.filter(user=request.user).exists():
        messages.error(request, 'You do not have access to this app.')
        return redirect('app_list')
    
    return render(request, 'apps/detail.html', {
        'app': app,
        'pages': app.pages.all(),
        'models': app.models.all()
    })

@login_required
@require_http_methods(['POST'])
def generate_app(request):
    """View to handle app generation from prompt."""
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': 'Invalid request'}, status=400)
    
    # Check for API key
    if not settings.ANTHROPIC_API_KEY:
        return JsonResponse({
            'error': 'Anthropic API key not configured. Please set the ANTHROPIC_API_KEY environment variable.',
            'message': 'Server configuration error'
        }, status=500)
    
    prompt_content = request.POST.get('prompt')
    org_id = request.POST.get('organization_id')
    
    if not prompt_content:
        return JsonResponse({'error': 'Prompt is required'}, status=400)
    
    try:
        # Get or use default organization
        if org_id:
            organization = get_object_or_404(Organization, id=org_id)
        else:
            organization = request.user.owned_organizations.first()
            if not organization:
                # Create a default organization for the user if none exists
                organization = Organization.objects.create(
                    name=f"{request.user.username}'s Organization",
                    owner=request.user
                )
                OrganizationMember.objects.create(
                    organization=organization,
                    user=request.user,
                    role='ADMIN'
                )
        
        # Create prompt
        prompt = Prompt.objects.create(
            content=prompt_content,
            user=request.user,
            organization=organization,
            tokens_used=0,
            status='PENDING'
        )
        
        # Start async task
        task_id = async_task(
            generate_app_async,
            organization.id,
            prompt.id,
            request.user.id
        )
        
        return JsonResponse({
            'success': True,
            'message': 'App generation started',
            'prompt_id': prompt.id,
            'task_id': task_id,
            'redirect_url': reverse('apps:check_generation', args=[prompt.id])
        })
        
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'message': 'Failed to start app generation'
        }, status=500)

@login_required
def app_update(request, app_id):
    """View to handle app updates."""
    app = get_object_or_404(App, id=app_id)
    
    # Check if user has permission to update
    member = app.organization.organizationmember_set.filter(user=request.user).first()
    if not member or member.role not in ['ADMIN', 'OWNER']:
        messages.error(request, 'You do not have permission to update this app.')
        return redirect('app_detail', app_id=app_id)
    
    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        update_content = request.POST.get('prompt')
        
        if not update_content:
            return JsonResponse({'error': 'Update prompt is required'}, status=400)
        
        try:
            # Create prompt update
            prompt_update = PromptUpdate.objects.create(
                original_prompt=app.initial_prompt,
                update_content=update_content,
                tokens_used=0,
                status='PENDING'
            )
            
            # Update app status
            app.status = 'UPDATING'
            app.save()
            
            # Start async task
            task_id = async_task(
                'utils.tasks.update_app_async',
                app.id,
                prompt_update.id,
                request.user.id
            )
            
            return JsonResponse({
                'success': True,
                'message': 'App update started',
                'update_id': prompt_update.id,
                'task_id': task_id
            })
            
        except Exception as e:
            return JsonResponse({
                'error': str(e),
                'message': 'Failed to start app update'
            }, status=500)
    
    return render(request, 'apps/update.html', {'app': app})

@login_required
def check_generation_status(request, prompt_id):
    """View to check the status of app generation."""
    prompt = get_object_or_404(Prompt, id=prompt_id)
    
    if prompt.user != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    return JsonResponse({
        'status': prompt.status,
        'error_message': prompt.error_message,
        'tokens_used': prompt.tokens_used,
        'app_id': prompt.created_apps.first().id if prompt.status == 'COMPLETED' else None
    })

@login_required
def check_update_status(request, update_id):
    """View to check the status of app update."""
    update = get_object_or_404(PromptUpdate, id=update_id)
    
    if update.original_prompt.user != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    return JsonResponse({
        'status': update.status,
        'error_message': update.error_message,
        'tokens_used': update.tokens_used
    })

@login_required
def render_app_page(request, app_id, page_slug):
    """View to render a specific app page."""
    app = get_object_or_404(App, id=app_id)
    page = get_object_or_404(AppPage, app=app, slug=page_slug)
    
    # Check if user has access to this app
    if not app.organization.organizationmember_set.filter(user=request.user).exists():
        messages.error(request, 'You do not have permission to view this app.')
        return redirect('apps:list')
    
    try:
        # Render the page with its contexts
        rendered_content = page.render(request)
        
        return render(request, 'apps/dynamic_page.html', {
            'app': app,
            'page': page,
            'rendered_content': rendered_content,
            'custom_js': page.js_content
        })
        
    except Exception as e:
        messages.error(request, f'Error rendering page: {str(e)}')
        return redirect('apps:detail', app_id=app_id)

@login_required
def page_details_api(request, page_id):
    """API endpoint to get page details."""
    logger = logging.getLogger(__name__)
    logger.info(f"Fetching page details for page_id: {page_id}")
    
    try:
        page = AppPage.objects.get(id=page_id)
        logger.info(f"Found page: {page.name} (id: {page.id})")
        
        # Check if user has access to the app through organization membership
        has_access = page.app.organization.organizationmember_set.filter(user=request.user).exists()
        logger.info(f"User {request.user.username} has access to app: {has_access}")
        
        if not has_access:
            logger.warning(f"Access denied for user {request.user.username} to page {page_id}")
            raise PermissionDenied("You do not have access to this app.")
        
        # Get context queries
        context_queries = [{
            'context_key': query.context_key,
            'query_content': query.query_content
        } for query in page.context_queries.all()]
        logger.info(f"Found {len(context_queries)} context queries")
        
        response_data = {
            'id': page.id,
            'name': page.name,
            'slug': page.slug,
            'app_id': page.app_id,
            'template_content': page.template_content,
            'js_content': page.js_content,
            'css_content': page.app.css_content,  # Use app-level CSS
            'context_queries': context_queries
        }
        logger.info("Successfully prepared response data")
        
        return JsonResponse(response_data)
        
    except AppPage.DoesNotExist:
        logger.error(f"Page not found: {page_id}")
        return JsonResponse({'error': 'Page not found'}, status=404)
    except PermissionDenied as e:
        logger.error(f"Permission denied: {str(e)}")
        return JsonResponse({'error': str(e)}, status=403)
    except Exception as e:
        logger.exception(f"Unexpected error in page_details_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
