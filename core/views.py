"""
API views for Kabanda.
"""
import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User

from .tasks import parse_user_message
from .models import UserContext

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """
    Telegram webhook endpoint.
    Receives messages and button callbacks from Telegram.
    """
    try:
        # Parse Telegram update
        data = json.loads(request.body)
        logger.info(f"Received Telegram update: {data}")
        
        # Handle callback query (button press)
        callback_query = data.get('callback_query')
        if callback_query:
            return _handle_callback_query(callback_query)
        
        # Extract message
        message = data.get('message')
        if not message:
            return HttpResponse(status=200)  # Acknowledge but ignore
        
        # Get chat and message details
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '')
        message_id = message.get('message_id')
        
        if not chat_id or not text:
            return HttpResponse(status=200)
        
        # Find or create user based on chat_id
        user = _get_or_create_user_from_chat_id(chat_id)
        if not user:
            logger.error(f"Could not find/create user for chat_id {chat_id}")
            return HttpResponse(status=200)
        
        # Trigger async message parsing
        parse_user_message.delay(
            user_id=user.id,
            message=text,
            telegram_message_id=message_id
        )
        
        return HttpResponse(status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        return HttpResponse(status=400)
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return HttpResponse(status=500)


def _handle_callback_query(callback_query: dict) -> HttpResponse:
    """
    Handle button callback from Telegram.
    """
    from .models import Task
    from .telegram_service import get_telegram_service
    
    try:
        callback_data = callback_query.get('data', '')
        chat_id = callback_query.get('from', {}).get('id')
        callback_id = callback_query.get('id')
        
        logger.info(f"Callback received: {callback_data} from chat_id {chat_id}")
        
        # Parse callback data (format: action_taskid)
        if '_' in callback_data:
            action, task_id = callback_data.split('_', 1)
            task_id = int(task_id)
            
            # Get user from chat_id
            user = _get_or_create_user_from_chat_id(chat_id)
            if not user:
                return HttpResponse(status=200)
            
            # Get task
            try:
                task = Task.objects.get(id=task_id, user=user)
                
                if action == 'complete':
                    task.mark_completed()
                    response = f"✅ Task completed: {task.title}"
                elif action == 'snooze':
                    task.snooze(minutes=30)
                    response = f"💤 Snoozed for 30 minutes: {task.title}"
                else:
                    response = "Unknown action"
                
                # Send acknowledgment
                telegram_service = get_telegram_service()
                telegram_service._run_async(telegram_service.bot.answer_callback_query(
                    callback_query_id=callback_id,
                    text=response
                ))
                
            except Task.DoesNotExist:
                logger.error(f"Task {task_id} not found")
        
        return HttpResponse(status=200)
        
    except Exception as e:
        logger.error(f"Error handling callback: {e}", exc_info=True)
        return HttpResponse(status=200)


def _get_or_create_user_from_chat_id(chat_id: int) -> User:
    """
    Get or create user from Telegram chat ID.
    
    First tries to find existing user with this chat_id in UserContext.
    If not found, creates a new user.
    """
    # Try to find existing user
    try:
        context = UserContext.objects.filter(
            context_type='preference',
            key='telegram_chat_id',
            value=str(chat_id),
            is_active=True
        ).first()
        
        if context:
            return context.user
    except Exception as e:
        logger.error(f"Error looking up user by chat_id: {e}")
    
    # Create new user
    try:
        # Generate username from chat_id
        username = f"telegram_{chat_id}"
        
        # Check if user already exists
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'first_name': 'Telegram User',
            }
        )
        
        # Store chat_id in UserContext
        UserContext.objects.get_or_create(
            user=user,
            context_type='preference',
            key='telegram_chat_id',
            defaults={'value': str(chat_id)}
        )
        
        if created:
            logger.info(f"Created new user {username} for chat_id {chat_id}")
        
        return user
        
    except Exception as e:
        logger.error(f"Error creating user for chat_id {chat_id}: {e}", exc_info=True)
        return None


@require_POST
def task_action(request, task_id: int, action: str):
    """
    Handle task actions (complete, snooze, cancel).
    
    URL: /api/task/<task_id>/<action>/
    Actions: complete, snooze, cancel
    """
    try:
        from .models import Task
        
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        task = Task.objects.filter(id=task_id, user=user).first()
        if not task:
            return JsonResponse({'error': 'Task not found'}, status=404)
        
        if action == 'complete':
            task.mark_completed()
            return JsonResponse({'status': 'success', 'message': 'Task marked as completed'})
        
        elif action == 'snooze':
            minutes = request.POST.get('minutes', 10)
            task.snooze(minutes=int(minutes))
            return JsonResponse({
                'status': 'success',
                'message': f'Task snoozed for {minutes} minutes',
                'snoozed_until': task.snoozed_until.isoformat()
            })
        
        elif action == 'cancel':
            task.status = 'cancelled'
            task.save()
            return JsonResponse({'status': 'success', 'message': 'Task cancelled'})
        
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)
    
    except Exception as e:
        logger.error(f"Error in task_action: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse({'status': 'healthy', 'service': 'kabanda'})

