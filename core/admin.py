"""
Admin interface configuration for Kabanda models.
"""
from django.contrib import admin
from .models import UserContext, Task, Reminder, ConversationLog


@admin.register(UserContext)
class UserContextAdmin(admin.ModelAdmin):
    list_display = ('user', 'context_type', 'key', 'is_active', 'updated_at')
    list_filter = ('context_type', 'is_active')
    search_fields = ('user__username', 'key', 'value')
    date_hierarchy = 'updated_at'


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'status', 'priority', 'due_at', 'reminder_count', 'created_at')
    list_filter = ('status', 'priority', 'is_recurring')
    search_fields = ('title', 'description', 'user__username')
    date_hierarchy = 'due_at'
    readonly_fields = ('created_at', 'updated_at', 'completed_at', 'last_reminded_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'title', 'description', 'status', 'priority')
        }),
        ('Timing', {
            'fields': ('due_at', 'snoozed_until', 'created_at', 'updated_at', 'completed_at')
        }),
        ('Source', {
            'fields': ('source_message', 'telegram_message_id')
        }),
        ('Escalation', {
            'fields': ('reminder_count', 'last_reminded_at')
        }),
        ('Recurrence', {
            'fields': ('is_recurring', 'recurrence_pattern'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ('task', 'channel', 'status', 'scheduled_at', 'sent_at')
    list_filter = ('channel', 'status')
    search_fields = ('task__title', 'message_content')
    date_hierarchy = 'scheduled_at'
    readonly_fields = ('sent_at', 'acknowledged_at')


@admin.register(ConversationLog)
class ConversationLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'direction', 'message_type', 'ai_intent', 'created_at', 'processing_time_ms')
    list_filter = ('direction', 'message_type', 'ai_intent')
    search_fields = ('user__username', 'content', 'ai_response')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('Message Info', {
            'fields': ('user', 'task', 'direction', 'message_type', 'content')
        }),
        ('AI Processing', {
            'fields': ('ai_intent', 'ai_response', 'processing_time_ms')
        }),
        ('Metadata', {
            'fields': ('telegram_message_id', 'created_at')
        }),
    )

