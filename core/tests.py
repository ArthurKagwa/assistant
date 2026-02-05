"""
Tests for webhook and task idempotency.
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.cache import cache
from unittest.mock import patch, MagicMock
import json

from core.models import Task, ConversationLog, UserContext
from core.tasks import parse_user_message


class TestWebhookIdempotency(TestCase):
    """Test idempotency in webhook view."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass')
        
        # Create user context with telegram chat_id
        UserContext.objects.create(
            user=self.user,
            context_type='preference',
            key='telegram_chat_id',
            value='12345'
        )
        
        # Clear cache before each test
        cache.clear()
    
    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
    
    @patch('core.views.parse_user_message')
    def test_duplicate_webhook_calls_prevented(self, mock_parse):
        """Test that duplicate webhook calls are prevented by idempotency check."""
        # Prepare webhook payload
        payload = {
            'message': {
                'message_id': 123,
                'chat': {'id': 12345},
                'text': 'Test message'
            }
        }
        
        # First call should succeed
        response1 = self.client.post(
            '/api/webhook/telegram/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(mock_parse.delay.call_count, 1)
        
        # Second call with same message_id should be skipped
        response2 = self.client.post(
            '/api/webhook/telegram/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response2.status_code, 200)
        # Should still be 1, not 2
        self.assertEqual(mock_parse.delay.call_count, 1)
        
        # Third call with same message_id should also be skipped
        response3 = self.client.post(
            '/api/webhook/telegram/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response3.status_code, 200)
        # Should still be 1, not 3
        self.assertEqual(mock_parse.delay.call_count, 1)


class TestTaskIdempotency(TestCase):
    """Test idempotency in parse_user_message task."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        
        # Create user context
        UserContext.objects.create(
            user=self.user,
            context_type='preference',
            key='telegram_chat_id',
            value='12345'
        )
    
    @patch('core.tasks.get_ai_service')
    @patch('core.tasks.get_telegram_service')
    @patch('core.mongo_service.get_mongo_service')
    def test_duplicate_task_execution_prevented(self, mock_mongo, mock_telegram, mock_ai):
        """Test that duplicate task executions are prevented."""
        # Mock services
        mock_ai_instance = MagicMock()
        mock_ai_instance.parse_message.return_value = {
            'intent': 'general',
            'conversational_response': 'Hello!'
        }
        mock_ai.return_value = mock_ai_instance
        
        mock_telegram_instance = MagicMock()
        mock_telegram.return_value = mock_telegram_instance
        
        mock_mongo_instance = MagicMock()
        mock_mongo_instance.get_conversation_context.return_value = []
        mock_mongo.return_value = mock_mongo_instance
        
        # First execution should create ConversationLog
        parse_user_message(
            user_id=self.user.id,
            message='Test message',
            telegram_message_id=123
        )
        
        # Verify one incoming log was created
        incoming_logs = ConversationLog.objects.filter(
            user=self.user,
            telegram_message_id=123,
            direction='incoming'
        )
        self.assertEqual(incoming_logs.count(), 1)
        
        # Second execution with same telegram_message_id should be skipped
        parse_user_message(
            user_id=self.user.id,
            message='Test message',
            telegram_message_id=123
        )
        
        # Should still be 1, not 2
        incoming_logs = ConversationLog.objects.filter(
            user=self.user,
            telegram_message_id=123,
            direction='incoming'
        )
        self.assertEqual(incoming_logs.count(), 1)
        
        # Third execution should also be skipped
        parse_user_message(
            user_id=self.user.id,
            message='Test message',
            telegram_message_id=123
        )
        
        # Should still be 1, not 3
        incoming_logs = ConversationLog.objects.filter(
            user=self.user,
            telegram_message_id=123,
            direction='incoming'
        )
        self.assertEqual(incoming_logs.count(), 1)
