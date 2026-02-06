"""
Celery tasks for Kabanda.
"""
from celery import shared_task
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import datetime, timedelta
import logging
from urllib.parse import quote

from .models import Task, Reminder, ConversationLog
from .ai_service import get_ai_service
from .telegram_service import get_telegram_service

logger = logging.getLogger(__name__)


def generate_google_maps_link(latitude: float, longitude: float, place_name: str = None) -> str:
    """
    Generate a Google Maps link for a location.
    
    Args:
        latitude: Location latitude
        longitude: Location longitude
        place_name: Optional place name for better link
    
    Returns:
        Google Maps URL
    """
    if place_name:
        # Search for the place name at the coordinates
        query = quote(place_name)
        return f"https://www.google.com/maps/search/?api=1&query={query}&query_place_id={latitude},{longitude}"
    else:
        # Direct coordinate link
        return f"https://www.google.com/maps?q={latitude},{longitude}"


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
        
        # IDEMPOTENCY CHECK: Skip if this message was already processed
        # This is a second layer of defense in case webhook idempotency fails
        if telegram_message_id:
            existing_log = ConversationLog.objects.filter(
                user=user,
                telegram_message_id=telegram_message_id,
                direction='incoming'
            ).first()
            
            if existing_log:
                logger.warning(f"Task already processed for telegram_message_id {telegram_message_id}. Skipping.")
                return
        
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
        
        # Log incoming message (Django model) & start timer
        start_time = timezone.now()
        conversation = ConversationLog.objects.create(
            user=user,
            direction='incoming',
            message_type='text',
            content=message,
            telegram_message_id=telegram_message_id
        )

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
            # Single task (legacy/backward compatibility)
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
        
        elif parsed['intent'] == 'new_tasks':
            # Multiple tasks from one message
            tasks_data = parsed.get('tasks', [])
            
            # Check if we need location input first
            if parsed.get('needs_location_input'):
                response = parsed.get('location_prompt', 'Where are you right now?')
                # Store pending tasks in user context for next message
                from .models import UserContext
                import json
                UserContext.objects.update_or_create(
                    user=user,
                    context_type='preference',
                    key='pending_location_tasks',
                    defaults={
                        'value': json.dumps({
                            'tasks': tasks_data,
                            'original_message': message
                        }),
                        'is_active': True
                    }
                )
                telegram_service.send_message(user, response)
            else:
                # Resolve location-based tasks if any
                tasks_data = _resolve_location_tasks(user, tasks_data)
                
                # Create all tasks
                created_tasks = _create_multiple_tasks(user, tasks_data, message, telegram_message_id)
                
                # Update conversation with first task
                if created_tasks:
                    conversation.task = created_tasks[0]
                    conversation.save()
                
                # Schedule all reminders
                for task in created_tasks:
                    schedule_reminder.apply_async(
                        args=[task.id],
                        eta=task.due_at
                    )
                
                # Send comprehensive confirmation
                response = _format_multiple_tasks_confirmation(created_tasks, parsed)
                telegram_service.send_message(user, response)
                
                # Send location widgets for location-based tasks
                _send_location_widgets(user, created_tasks, telegram_service)
        
        elif parsed['intent'] == 'location_query_needed':
            # User is providing location for pending tasks
            from .models import UserContext
            import json
            
            pending_context = UserContext.objects.filter(
                user=user,
                context_type='preference',
                key='pending_location_tasks',
                is_active=True
            ).first()
            
            if pending_context:
                pending_data = json.loads(pending_context.value)
                tasks_data = pending_data.get('tasks', [])
                
                # Use the current message as location
                tasks_data = _resolve_location_tasks(user, tasks_data, location_str=message)
                
                # Create tasks
                created_tasks = _create_multiple_tasks(
                    user, 
                    tasks_data, 
                    pending_data.get('original_message', message), 
                    telegram_message_id
                )
                
                # Schedule reminders
                for task in created_tasks:
                    schedule_reminder.apply_async(args=[task.id], eta=task.due_at)
                
                # Clear pending context
                pending_context.is_active = False
                pending_context.save()
                
                # Send confirmation
                response = _format_multiple_tasks_confirmation(created_tasks, parsed)
                telegram_service.send_message(user, response)
                
                # Send location widgets for location-based tasks
                _send_location_widgets(user, created_tasks, telegram_service)
            else:
                response = "I'm not sure what location you're referring to. Could you rephrase that?"
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
        
        # Send location widget if this is a location-based task
        if task.location_name and task.location_data and 'location' in task.location_data:
            lat = task.location_data['location'].get('lat')
            lng = task.location_data['location'].get('lng')
            if lat and lng:
                telegram_service.send_location(
                    task.user, 
                    lat, 
                    lng, 
                    title=task.location_name,
                    address=task.location_address
                )
        
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
    due_datetime = parsed.get('due_datetime')
    if isinstance(due_datetime, str):
        due_datetime = date_parser.parse(due_datetime)
    
    task = Task.objects.create(
        user=user,
        title=parsed.get('task_title', 'New Task'),
        description=parsed.get('task_description', ''),
        priority=parsed.get('priority', 'medium'),
        due_at=due_datetime,
        source_message=original_message,
        telegram_message_id=telegram_msg_id,
        location_name=parsed.get('location_name', ''),
        location_address=parsed.get('location_address', ''),
        location_data=parsed.get('location_data')
    )
    return task


def _create_multiple_tasks(user: User, tasks_data: list, original_message: str, telegram_msg_id: int = None) -> list:
    """Create multiple tasks from parsed data array."""
    from .models import Task
    import uuid
    from dateutil import parser as date_parser
    
    batch_id = uuid.uuid4()
    created_tasks = []
    
    for task_data in tasks_data:
        due_at = task_data.get('due_datetime')
        if isinstance(due_at, str):
            due_at = date_parser.parse(due_at)
            
        task = Task.objects.create(
            user=user,
            title=task_data.get('task_title', 'New Task'),
            description=task_data.get('task_description', ''),
            priority=task_data.get('priority', 'medium'),
            due_at=due_at,
            source_message=original_message,
            telegram_message_id=telegram_msg_id,
            batch_id=batch_id,
            location_name=task_data.get('location_name', ''),
            location_address=task_data.get('location_address', ''),
            location_data=task_data.get('location_data')
        )
        created_tasks.append(task)
    
    return created_tasks


def _resolve_location_tasks(user: User, tasks_data: list, location_str: str = None) -> list:
    """Resolve location-based tasks using Places service."""
    from .places_service import get_places_service
    places_service = get_places_service()
    
    resolved_tasks = []
    lat, lng = None, None
    
    if location_str:
        coords = places_service.geocode_location(location_str)
        if coords:
            lat, lng = coords
            
    for task_data in tasks_data:
        if task_data.get('requires_location') and lat and lng:
            query = task_data.get('location_query', 'cool restaurant')
            recommendations = places_service.get_top_recommendations(query, lat, lng, limit=1)
            
            if recommendations:
                place = recommendations[0]
                task_data['location_name'] = place['name']
                task_data['location_address'] = place['address']
                task_data['location_data'] = place
                task_data['task_title'] = f"{task_data['task_title']} at {place['name']}"
                task_data['task_description'] = f"Recommended: {places_service.format_place_for_task(place)}"
        
        resolved_tasks.append(task_data)
        
    return resolved_tasks


def _format_multiple_tasks_confirmation(tasks: list, parsed: dict) -> str:
    """Format confirmation message for multiple tasks."""
    from django.conf import settings
    import pytz
    
    tz = pytz.timezone(settings.TIME_ZONE)
    
    msg = f"✅ I've scheduled {len(tasks)} tasks for you:\n\n"
    
    for i, task in enumerate(tasks, 1):
        local_time = task.due_at.astimezone(tz)
        msg += f"{i}. **{task.title}**\n"
        msg += f"   ⏰ Reminder: {local_time.strftime('%I:%M %p on %b %d')}\n"
        if task.location_name:
            msg += f"   📍 Location: {task.location_name}\n"
            # Add Google Maps link if we have coordinates
            if task.location_data and 'location' in task.location_data:
                lat = task.location_data['location'].get('lat')
                lng = task.location_data['location'].get('lng')
                if lat and lng:
                    maps_link = generate_google_maps_link(lat, lng, task.location_name)
                    msg += f"   🗺️ [View on Maps]({maps_link})\n"
        msg += "\n"
        
    if parsed.get('clarification_needed'):
        msg += f"❓ {parsed['clarification_needed']}\n\n"
        
    msg += parsed.get('conversational_response', "Let me know if you need anything else!")
    return msg


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
    
    # Add location info if available
    if task.location_name:
        msg += f"\n📍 {task.location_name}"
        if task.location_address:
            msg += f"\n{task.location_address}"
        
        # Add maps link if we have coordinates
        if task.location_data and 'location' in task.location_data:
            lat = task.location_data['location'].get('lat')
            lng = task.location_data['location'].get('lng')
            if lat and lng:
                maps_link = generate_google_maps_link(lat, lng, task.location_name)
                msg += f"\n🗺️ [View on Maps]({maps_link})"
    
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
        # Parse due_datetime if it's a string
        from dateutil import parser as date_parser
        due_datetime = parsed['due_datetime']
        if isinstance(due_datetime, str):
            due_datetime = date_parser.parse(due_datetime)
            
        task.due_at = due_datetime
        task.save()
        
        # Cancel old reminder and schedule new one
        schedule_reminder.apply_async(args=[task.id], eta=task.due_at)
    
    return task


def _get_user_tasks(user: User, parsed: dict) -> list:
    """Get user's tasks based on query."""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    # Get query timeframe from parsed data (default to today)
    query_type = parsed.get('query_type', 'today')
    
    # Base queryset - always filter by user and pending status
    queryset = Task.objects.filter(user=user, status='pending')
    
    # Apply time-based filters based on query type
    if query_type == 'afternoon':
        # Afternoon: 12 PM to 6 PM (exclusive end)
        afternoon_start = today_start.replace(hour=12)
        afternoon_end = today_start.replace(hour=18)
        queryset = queryset.filter(due_at__gte=afternoon_start, due_at__lt=afternoon_end)
    elif query_type == 'evening':
        # Evening: 6 PM onwards (until midnight)
        evening_start = today_start.replace(hour=18)
        queryset = queryset.filter(due_at__gte=evening_start, due_at__lt=today_end)
    elif query_type == 'morning':
        # Morning: midnight to 12 PM
        queryset = queryset.filter(due_at__gte=today_start, due_at__lt=today_start.replace(hour=12))
    elif query_type == 'week':
        # This week
        week_end = today_start + timedelta(days=7)
        queryset = queryset.filter(due_at__gte=today_start, due_at__lt=week_end)
    elif query_type == 'upcoming':
        # All upcoming tasks (next 30 days)
        upcoming_end = today_start + timedelta(days=30)
        queryset = queryset.filter(due_at__gte=now, due_at__lt=upcoming_end)
    elif query_type == 'all':
        # All pending tasks
        queryset = queryset.filter(due_at__gte=now)
    else:
        # Default: today's tasks
        queryset = queryset.filter(due_at__gte=today_start, due_at__lt=today_end)
    
    return list(queryset.order_by('due_at'))


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


def _send_location_widgets(user: User, tasks: list, telegram_service) -> None:
    """
    Send location widgets for tasks that have location data.
    
    Args:
        user: User to send to
        tasks: List of Task objects
        telegram_service: TelegramService instance
    """
    for task in tasks:
        if task.location_name and task.location_data and 'location' in task.location_data:
            lat = task.location_data['location'].get('lat')
            lng = task.location_data['location'].get('lng')
            if lat and lng:
                telegram_service.send_location(
                    user,
                    lat,
                    lng,
                    title=task.location_name,
                    address=task.location_address
                )
