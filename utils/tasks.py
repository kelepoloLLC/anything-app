from django.contrib.auth import get_user_model
from anything_org.models import Organization
from anything_apps.models import Prompt
from .app_generator import AppGenerator

User = get_user_model()

def generate_app_async(organization_id: int, prompt_id: int, user_id: int):
    """
    Async task to generate an app based on the prompt.
    
    Args:
        organization_id (int): ID of the organization
        prompt_id (int): ID of the prompt
        user_id (int): ID of the user who initiated the generation
    
    Returns:
        dict: Result of the app generation process
    """
    try:
        # Get required objects
        organization = Organization.objects.get(id=organization_id)
        prompt = Prompt.objects.get(id=prompt_id)
        user = User.objects.get(id=user_id)

        # Check token balance
        if user.token_balance < 100:  # Example token cost
            prompt.status = 'FAILED'
            prompt.error_message = 'Insufficient tokens'
            prompt.save()
            return {'error': 'Insufficient tokens'}

        # Deduct tokens
        user.token_balance -= 100
        user.save()

        # Generate app
        generator = AppGenerator(organization, prompt)
        app = generator.generate_app()

        return {
            'success': True,
            'app_id': app.id,
            'message': 'App generated successfully'
        }

    except Organization.DoesNotExist:
        return {'error': 'Organization not found'}
    except Prompt.DoesNotExist:
        return {'error': 'Prompt not found'}
    except User.DoesNotExist:
        return {'error': 'User not found'}
    except Exception as e:
        return {
            'error': str(e),
            'message': 'Failed to generate app'
        } 