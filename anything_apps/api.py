from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from .models import App, DataStore
import json
import math

@login_required
@require_http_methods(["GET"])
def data_store_list(request, app_id):
    """API endpoint to list and filter DataStore items."""
    try:
        app = App.objects.get(id=app_id)
        
        # Check if user has access to the app
        if not app.organization.organizationmember_set.filter(user=request.user).exists():
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Get query parameters
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 10))
        sort_column = request.GET.get('sort_column', 'id')
        sort_direction = request.GET.get('sort_direction', 'asc')
        filter_value = request.GET.get('filter', '')
        search_query = request.GET.get('search', '')
        
        # Start with all items for this app
        query = app.data_store.all()
        
        # Apply search if provided
        if search_query:
            query = query.filter(
                Q(key__icontains=search_query) |
                Q(value__icontains=search_query)
            )
        
        # Apply filters if provided
        if filter_value:
            query = query.filter(value_type=filter_value)
        
        # Get total count before pagination
        total_count = query.count()
        
        # Apply sorting
        sort_prefix = "-" if sort_direction == "desc" else ""
        query = query.order_by(f"{sort_prefix}{sort_column}")
        
        # Apply pagination
        paginator = Paginator(query, per_page)
        items = paginator.get_page(page)
        
        # Format results
        return JsonResponse({
            "items": [
                {
                    "id": item.id,
                    "key": item.key,
                    "value": item.get_typed_value(),
                    "value_type": item.value_type,
                    "updated_at": item.updated_at.isoformat()
                }
                for item in items
            ],
            "total": total_count,
            "page": page,
            "per_page": per_page,
            "total_pages": math.ceil(total_count / per_page)
        })
        
    except App.DoesNotExist:
        return JsonResponse({'error': 'App not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def data_store_detail(request, app_id, item_id):
    """API endpoint to get a single DataStore item."""
    try:
        app = App.objects.get(id=app_id)
        
        # Check if user has access to the app
        if not app.organization.organizationmember_set.filter(user=request.user).exists():
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        item = app.data_store.get(id=item_id)
        
        return JsonResponse({
            "id": item.id,
            "key": item.key,
            "value": item.get_typed_value(),
            "value_type": item.value_type,
            "updated_at": item.updated_at.isoformat()
        })
        
    except App.DoesNotExist:
        return JsonResponse({'error': 'App not found'}, status=404)
    except DataStore.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
def data_store_create(request, app_id):
    """API endpoint to create a new DataStore item."""
    try:
        app = App.objects.get(id=app_id)
        
        # Check if user has access to the app
        if not app.organization.organizationmember_set.filter(user=request.user).exists():
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        data = json.loads(request.body)
        
        # Validate required fields
        if not all(k in data for k in ['key', 'value', 'value_type']):
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        # Create the item
        item = DataStore.objects.create(
            app=app,
            key=data['key'],
            value=str(data['value']),  # Convert to string for storage
            value_type=data['value_type']
        )
        
        return JsonResponse({
            "id": item.id,
            "key": item.key,
            "value": item.get_typed_value(),
            "value_type": item.value_type,
            "updated_at": item.updated_at.isoformat()
        }, status=201)
        
    except App.DoesNotExist:
        return JsonResponse({'error': 'App not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["PUT", "PATCH"])
def data_store_update(request, app_id, item_id):
    """API endpoint to update a DataStore item."""
    try:
        app = App.objects.get(id=app_id)
        
        # Check if user has access to the app
        if not app.organization.organizationmember_set.filter(user=request.user).exists():
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        item = app.data_store.get(id=item_id)
        data = json.loads(request.body)
        
        # Update fields
        if 'key' in data:
            item.key = data['key']
        if 'value' in data:
            item.value = str(data['value'])
        if 'value_type' in data:
            item.value_type = data['value_type']
            
        item.save()
        
        return JsonResponse({
            "id": item.id,
            "key": item.key,
            "value": item.get_typed_value(),
            "value_type": item.value_type,
            "updated_at": item.updated_at.isoformat()
        })
        
    except App.DoesNotExist:
        return JsonResponse({'error': 'App not found'}, status=404)
    except DataStore.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["DELETE"])
def data_store_delete(request, app_id, item_id):
    """API endpoint to delete a DataStore item."""
    try:
        app = App.objects.get(id=app_id)
        
        # Check if user has access to the app
        if not app.organization.organizationmember_set.filter(user=request.user).exists():
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        item = app.data_store.get(id=item_id)
        item.delete()
        
        return JsonResponse({'message': 'Item deleted successfully'})
        
    except App.DoesNotExist:
        return JsonResponse({'error': 'App not found'}, status=404)
    except DataStore.DoesNotExist:
        return JsonResponse({'error': 'Item not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500) 