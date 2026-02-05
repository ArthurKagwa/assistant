"""
Celery tasks for Kabanda.
"""
from celery import shared_task
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import datetime, timedelta
import logging

from .models import Task, Reminder, ConversationLog
from .ai_service import get_ai_service
from .telegram_service import get_telegram_service

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def parse_user_message(self, user_id: int, message: str, telegram_message_id: int = None):
    """
    Parse user message using AI and create/update tasks.
    
    Args:
        user_id: User ID
        message: User's message text
        telegram_message_id: Optional Telegram message ID
    """
    try:
        user = User.objects.get(id=user_id)
        ai_service = get_ai_service()
        telegram_service = get_telegram_service()
        
        # Get MongoDB service
        from .mongo_service import get_mongo_service
        mongo_service = get_mongo_service()
        
        # Get chat_id from user context
        from .models import UserContext
        chat_id_context = UserContext.objects.filter(
            user=user,
            context_type='preference',
            key='telegram_chat_id',
            is_active=True
        ).first()
        chat_id = int(chat_id_context.value) if chat_id_context else 0
        
        # Get user context and conversation history (before saving new message to avoid dup)
        user_context = _get_user_context(user)
        conversation_context = mongo_service.get_conversation_context(user.id, limit=6)
        user_context['conversation_history'] = conversation_context

        # Save incoming message to MongoDB
        mongo_service.save_message(
            user_id=user.id,
            chat_id=chat_id,
            direction='incoming',
            message=message,
            telegram_message_id=telegram_message_id
        )
        
        # Parse message with AI (now includes conversation context)
        parsed = ai_service.parse_message(message, user_context)
        
        # Update conversation log with AI response
        processing_time = (timezone.now() - start_time).total_seconds() * 1000
        conversation.ai_intent = parsed.get('intent', '')
        conversation.processing_time_ms = int(processing_time)
        conversation.save()
        
        # Handle based on intent
        if parsed['intent'] == 'new_task':
            task = _create_task(user, parsed, message, telegram_message_id)
            conversation.task = task
            conversation.save()
            
            # Schedule reminder
            schedule_reminder.apply_async(
                args=[task.id],
                eta=task.due_at
            )
            
            # Send confirmation to user
            response = _format_task_confirmation(task, parsed)
            telegram_service.send_message(user, response)
            
        elif parsed['intent'] == 'modify_task':
            # Find recent task and modify it
            task = _find_and_modify_task(user, parsed)
            if task:
                from django.conf import settings
                import pytz
                tz = pytz.timezone(settings.TIME_ZONE)
                local_time = task.due_at.astimezone(tz)
                response = f"✓ Updated: {task.title} is now scheduled for {local_time.strftime('%I:%M %p on %b %d')}"
            else:
                response = "I couldn't find a recent task to modify. Could you be more specific?"
            telegram_service.send_message(user, response)

        elif parsed['intent'] == 'delete_task':
            # Find recent task and cancel it
            task = _find_recent_task(user)
            if task:
                task.status = 'cancelled'
                task.save()
                response = f"🗑️ Task cancelled: {task.title}"
            else:
                response = "I couldn't find a pending task to cancel."
            telegram_service.send_message(user, response)
            
        elif parsed['intent'] == 'query_tasks':
            tasks = _get_user_tasks(user, parsed)
            response = _format_tasks_list(tasks)
            telegram_service.send_message(user, response)
            
        else:
            # General question/conversation
            response = parsed.get('conversational_response')
            if not response:
                response = "I'm listening. You can ask me to remind you of tasks or check your schedule."
            telegram_service.send_message(user, response)
        
        # Log outgoing response (Django model)
        ConversationLog.objects.create(
            user=user,
            task=conversation.task,
            direction='outgoing',
            message_type='text',
            content=response,
            ai_response=response
        )
        
        # Save outgoing message to MongoDB
        mongo_service.save_message(
            user_id=user.id,
            chat_id=chat_id,
            direction='outgoing',
            message=response,
            ai_intent=parsed.get('intent'),
            ai_response=response,
            task_id=conversation.task.id if conversation.task else None
        )
        
    except Exception as e:
        logger.error(f"Error parsing message for user {user_id}: {e}", exc_info=True)
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=5)
def schedule_reminder(self, task_id: int):
    """
    Send reminder for a task.
    
    Args:
        task_id: Task ID to remind about
    """
    try:
        task = Task.objects.get(id=task_id)
        
        # Skip if task is already completed or cancelled
        if task.status in ['completed', 'cancelled']:
            logger.info(f"Skipping reminder for task {task_id} - status: {task.status}")
            return
        
        # Check if snoozed
        if task.status == 'snoozed' and task.snoozed_until > timezone.now():
            # Reschedule for snooze time
            schedule_reminder.apply_async(args=[task_id], eta=task.snoozed_until)
            return
        
        telegram_service = get_telegram_service()
        
        # Create reminder record
        message, buttons = _format_reminder_message(task)
        reminder = Reminder.objects.create(
            task=task,
            channel='telegram',
            status='scheduled',
            scheduled_at=timezone.now(),
            message_content=message
        )
        
        # Send reminder with buttons
        telegram_service.send_message(task.user, message, buttons=buttons)
        reminder.mark_sent()
        
        # Update task
        task.increment_reminder()
        
        # Schedule escalation if needed
        if task.reminder_count >= 2:
            # After 2 reminders, escalate every 10 minutes
            escalate_reminder.apply_async(args=[task_id], countdown=600)  # 10 minutes
        
    except Task.DoesNotExist:
        logger.error(f"Task {task_id} not found for reminder")
    except Exception as e:
        logger.error(f"Error sending reminder for task {task_id}: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=300)  # Retry in 5 minutes


@shared_task
def escalate_reminder(task_id: int):
    """
    Escalate reminder if user hasn't acknowledged.
    
    Args:
        task_id: Task ID
    """
    try:
        task = Task.objects.get(id=task_id)
        
        # Skip if completed
        if task.status in ['completed', 'cancelled']:
            return
        
        telegram_service = get_telegram_service()
        
        if task.reminder_count >= 3:
            # Level 3: More urgent message
            message = f"⚠️ URGENT: You have ignored '{task.title}' for {task.reminder_count} reminders. Please address this now!"
        else:
            # Level 2: Persistent reminder
            message = f"🔔 Reminder ({task.reminder_count}x): {task.title}"
        
        # Add buttons for quick action
        buttons = [
            {'text': '✅ Complete', 'callback_data': f'complete_{task_id}'},
            {'text': '💤 Snooze 30min', 'callback_data': f'snooze_{task_id}'}
        ]
        
        telegram_service.send_message(task.user, message, buttons=buttons)
        task.increment_reminder()
        
        # Keep escalating every 10 minutes until acknowledged
        if task.reminder_count < 10:  # Max 10 escalations
            escalate_reminder.apply_async(args=[task_id], countdown=600)
        
    except Task.DoesNotExist:
        logger.error(f"Task {task_id} not found for escalation")


# Helper functions

def _get_user_context(user: User) -> dict:
    """Get user context for AI parsing."""
    from .models import UserContext
    
    contexts = UserContext.objects.filter(user=user, is_active=True)
    return {
        'projects': [c.value for c in contexts.filter(context_type='project')],
        'routines': [c.value for c in contexts.filter(context_type='routine')],
    }


def _create_task(user: User, parsed: dict, original_message: str, telegram_msg_id: int = None) -> Task:
    """Create a new task from parsed data."""
    from dateutil import parser as date_parser
    
    # Parse due_datetime if it's a string
    due_datetime = parsed['due_datetime']
    if isinstance(due_datetime, str):
        due_datetime = date_parser.parse(due_datetime)
    
    task = Task.objects.create(
        user=user,
        title=parsed['task_title'],
        description=parsed.get('task_description', ''),
        priority=parsed.get('priority', 'medium'),
        due_at=due_datetime,
        source_message=original_message,
        telegram_message_id=telegram_msg_id
    )
    return task


def _format_task_confirmation(task: Task, parsed: dict) -> str:
    """Format task confirmation message."""
    from django.utils import timezone
    from django.conf import settings
    import pytz
    
    # Convert to user's timezone
    tz = pytz.timezone(settings.TIME_ZONE)
    local_time = task.due_at.astimezone(tz)
    
    msg = f"✓ Task created: **{task.title}**\n"
    msg += f"⏰ Reminder: {local_time.strftime('%I:%M %p on %b %d, %Y')}\n"
    msg += f"📊 Priority: {task.priority.title()}"
    
    if parsed.get('clarification_needed'):
        msg += f"\n\n❓ {parsed['clarification_needed']}"
    
    return msg


def _format_reminder_message(task: Task) -> tuple:
    """Format reminder message with buttons.
    
    Returns:
        tuple: (message_text, buttons_list)
    """
    if task.reminder_count == 0:
        msg = f"🔔 Reminder: {task.title}"
    else:
        msg = f"🔔 Reminder ({task.reminder_count + 1}x): {task.title}"
    
    # Add buttons
    buttons = [
        {'text': '✅ Complete', 'callback_data': f'complete_{task.id}'},
        {'text': '💤 Snooze 30min', 'callback_data': f'snooze_{task.id}'},
        {'text': '🗑️ Delete', 'callback_data': f'delete_{task.id}'}
    ]
    
    return msg, buttons


def _find_recent_task(user: User) -> Task:
    """Find most recent pending task."""
    return Task.objects.filter(
        user=user,
        status='pending'
    ).order_by('-created_at').first()


def _find_and_modify_task(user: User, parsed: dict) -> Task:
    """Find and modify a recent task."""
    task = _find_recent_task(user)
    
    if task and parsed.get('due_datetime'):
        task.due_at = parsed['due_datetime']
        task.save()
        
        # Cancel old reminder and schedule new one
        schedule_reminder.apply_async(args=[task.id], eta=task.due_at)
    
    return task


def _get_user_tasks(user: User, parsed: dict) -> list:
    """Get user's tasks based on query."""
    # For now, get today's pending tasks
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    tasks = Task.objects.filter(
        user=user,
        status='pending',
        due_at__gte=today_start,
        due_at__lt=today_end
    ).order_by('due_at')
    
    return list(tasks)


def _format_tasks_list(tasks: list) -> str:
    """Format list of tasks for display."""
    from django.conf import settings
    import pytz
    
    if not tasks:
        return "You have no pending tasks for today. All clear! 🎉"
    
    # Get user's timezone
    tz = pytz.timezone(settings.TIME_ZONE)
    
    msg = f"📋 You have {len(tasks)} pending task(s):\n\n"
    for i, task in enumerate(tasks, 1):
        # Convert to local timezone
        local_time = task.due_at.astimezone(tz)
        msg += f"{i}. **{task.title}**\n"
        msg += f"   ⏰ {local_time.strftime('%I:%M %p on %b %d')}\n"
        msg += f"   📊 {task.priority.title()}\n\n"
    
    return msg
