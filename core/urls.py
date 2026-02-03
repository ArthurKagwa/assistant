"""
URL configuration for core app.
"""
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('webhook/telegram/', views.telegram_webhook, name='telegram_webhook'),
    path('task/<int:task_id>/<str:action>/', views.task_action, name='task_action'),
    path('health/', views.health_check, name='health_check'),
]
