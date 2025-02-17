from django.contrib.auth import get_user_model
from anything_org.models import Organization
from anything_apps.models import Prompt
from .app_generator import AppGenerator
from users.models import UserProfile
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

def generate_app_async(organization_id: int, prompt_id: int, user_id: int):
    """
    Async task to generate app template context based on the prompt.
    
    Args:
        organization_id (int): ID of the organization
        prompt_id (int): ID of the prompt
        user_id (int): ID of the user who initiated the generation
    
    Returns:
        dict: Result of the template context generation
    """
    logger.info(f"Starting app generation for prompt {prompt_id}")
    
    try:
        # Get required objects
        organization = Organization.objects.get(id=organization_id)
        prompt = Prompt.objects.get(id=prompt_id)
        user = User.objects.get(id=user_id)

        # Update prompt status to processing
        prompt.status = 'PROCESSING'
        prompt.save()
        logger.info(f"Updated prompt {prompt_id} status to PROCESSING")

        # Get or create user profile and check token balance
        profile = UserProfile.get_or_create_profile(user)
        
        # Calculate token cost based on prompt length (example calculation)
        token_cost = len(prompt.content.split()) // 4  # Simple example: 1 token per 4 words
        token_cost = max(10, min(token_cost, 100))  # Ensure cost is between 10 and 100 tokens
        
        if not profile.has_sufficient_tokens(token_cost):
            prompt.status = 'FAILED'
            prompt.error_message = 'Insufficient tokens'
            prompt.save()
            logger.error(f"Insufficient tokens for prompt {prompt_id}")
            return {'error': 'Insufficient tokens'}

        # Deduct tokens
        if not profile.deduct_tokens(token_cost):
            prompt.status = 'FAILED'
            prompt.error_message = 'Failed to deduct tokens'
            prompt.save()
            logger.error(f"Token deduction failed for prompt {prompt_id}")
            return {'error': 'Token deduction failed'}

        # Generate template context
        logger.info(f"Starting app generation with AppGenerator for prompt {prompt_id}")
        generator = AppGenerator(organization, prompt)
        app = generator.generate_app()
        logger.info(f"Successfully generated app {app.id} for prompt {prompt_id}")

        # Update prompt with token usage and status
        prompt.tokens_used = token_cost
        prompt.status = 'COMPLETED'
        prompt.save()

        return {
            'success': True,
            'app_id': app.id,
            'tokens_used': token_cost,
            'message': 'Template context generated successfully'
        }

    except Organization.DoesNotExist:
        logger.error(f"Organization {organization_id} not found")
        prompt.status = 'FAILED'
        prompt.error_message = 'Organization not found'
        prompt.save()
        return {'error': 'Organization not found'}
    except Prompt.DoesNotExist:
        logger.error(f"Prompt {prompt_id} not found")
        return {'error': 'Prompt not found'}
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
        return {'error': 'User not found'}
    except Exception as e:
        logger.exception(f"Error generating app for prompt {prompt_id}: {str(e)}")
        try:
            prompt.status = 'FAILED'
            prompt.error_message = str(e)
            prompt.save()
        except Exception as save_error:
            logger.exception(f"Error saving prompt failure status: {str(save_error)}")
        return {
            'error': str(e),
            'message': 'Failed to generate template context'
        } 