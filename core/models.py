"""
Core database models for Kabanda AI Assistant.
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserContext(models.Model):
    """
    Stores user context to help AI understand ongoing projects and tasks.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contexts')
    context_type = models.CharField(
        max_length=50,
        choices=[
            ('project', 'Project'),
            ('routine', 'Routine'),
            ('preference', 'Preference'),
            ('location', 'Location'),
        ]
    )
    key = models.CharField(max_length=100)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'user_contexts'
        indexes = [
            models.Index(fields=['user', 'context_type']),
            models.Index(fields=['user', 'key']),
        ]
        unique_together = ['user', 'context_type', 'key']

    def __str__(self):
        return f"{self.user.username} - {self.context_type}: {self.key}"


class Task(models.Model):
    """
    Main task model representing reminders and tasks.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('snoozed', 'Snoozed'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    
    # Timing
    due_at = models.DateTimeField(help_text="When the task is due/should be reminded")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    source_message = models.TextField(help_text="Original user message that created this task")
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    
    # Escalation tracking
    reminder_count = models.IntegerField(default=0, help_text="Number of times user has been reminded")
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    
    # Recurrence (for future implementation)
    is_recurring = models.BooleanField(default=False)
    recurrence_pattern = models.CharField(max_length=100, blank=True, help_text="Cron-like pattern")

    class Meta:
        db_table = 'tasks'
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'due_at']),
            models.Index(fields=['status', 'due_at']),
        ]
        ordering = ['due_at']

    def __str__(self):
        return f"{self.user.username} - {self.title} (Due: {self.due_at})"

    def mark_completed(self):
        """Mark task as completed."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()

    def snooze(self, minutes=10):
        """Snooze task for specified minutes."""
        self.status = 'snoozed'
        self.snoozed_until = timezone.now() + timezone.timedelta(minutes=minutes)
        self.save()

    def increment_reminder(self):
        """Increment reminder count and update timestamp."""
        self.reminder_count += 1
        self.last_reminded_at = timezone.now()
        self.save()


class Reminder(models.Model):
    """
    Tracks individual reminder attempts for a task (escalation history).
    """
    CHANNEL_CHOICES = [
        ('telegram', 'Telegram'),
        ('phone_call', 'Phone Call'),
        ('sms', 'SMS'),
    ]

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('acknowledged', 'Acknowledged'),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='reminders')
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    
    scheduled_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    
    message_content = models.TextField()
    error_message = models.TextField(blank=True)
    
    # External service IDs
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    twilio_call_sid = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'reminders'
        indexes = [
            models.Index(fields=['task', 'channel']),
            models.Index(fields=['status', 'scheduled_at']),
        ]
        ordering = ['-scheduled_at']

    def __str__(self):
        return f"Reminder for {self.task.title} via {self.channel} ({self.status})"

    def mark_sent(self):
        """Mark reminder as sent."""
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save()

    def mark_acknowledged(self):
        """Mark reminder as acknowledged by user."""
        self.status = 'acknowledged'
        self.acknowledged_at = timezone.now()
        self.save()


class ConversationLog(models.Model):
    """
    Logs all interactions with the user for context and debugging.
    """
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('voice', 'Voice'),
        ('image', 'Image'),
        ('command', 'Command'),
    ]

    DIRECTION_CHOICES = [
        ('incoming', 'Incoming'),
        ('outgoing', 'Outgoing'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES)
    content = models.TextField()
    
    # AI Processing
    ai_intent = models.CharField(max_length=100, blank=True, help_text="Extracted intent from AI")
    ai_response = models.TextField(blank=True, help_text="AI's generated response")
    processing_time_ms = models.IntegerField(null=True, blank=True)
    
    # Metadata
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conversation_logs'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['task']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.direction} {self.message_type} at {self.created_at}"

