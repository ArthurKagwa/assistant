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


class TestLocationBasedTaskTitles(TestCase):
    """Test that location-based tasks get proper titles with place names."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
    
    @patch('core.places_service.get_places_service')
    def test_location_task_title_includes_place_name(self, mock_places_service):
        """Test that location-based tasks include the place name in the title."""
        from core.tasks import _resolve_location_tasks
        
        # Mock places service
        mock_places_instance = MagicMock()
        mock_places_instance.geocode_location.return_value = (0.1, 30.5)
        mock_places_instance.get_top_recommendations.return_value = [{
            'name': 'The Green Valley Eatery',
            'address': 'Kahunge, Kamwenge',
            'rating': 4.5,
            'total_ratings': 100
        }]
        mock_places_instance.format_place_for_task.return_value = 'The Green Valley Eatery ⭐⭐⭐⭐ (4.5) - Kahunge, Kamwenge'
        mock_places_service.return_value = mock_places_instance
        
        # Test data with location-based task
        tasks_data = [{
            'task_title': 'Dinner',
            'task_description': '',
            'priority': 'medium',
            'due_datetime': '2026-02-06T19:00:00+03:00',
            'requires_location': True,
            'location_query': 'nice restaurant',
            'location_type': 'restaurant'
        }]
        
        # Resolve tasks with location
        resolved_tasks = _resolve_location_tasks(
            self.user,
            tasks_data,
            location_str='Kahunge, Kamwenge'
        )
        
        # Verify the task title was updated to include place name
        self.assertEqual(len(resolved_tasks), 1)
        self.assertEqual(resolved_tasks[0]['task_title'], 'Dinner at The Green Valley Eatery')
        self.assertEqual(resolved_tasks[0]['location_name'], 'The Green Valley Eatery')
        self.assertIn('Recommended:', resolved_tasks[0]['task_description'])
    
    @patch('core.places_service.get_places_service')
    def test_non_location_task_title_unchanged(self, mock_places_service):
        """Test that non-location tasks keep their original title.
        
        Note: geocode_location is still called to geocode the location_str
        (for efficiency, it's geocoded once for all tasks), but the
        coordinates are not used for tasks with requires_location=False.
        """
        from core.tasks import _resolve_location_tasks
        
        # Mock places service
        mock_places_instance = MagicMock()
        # Return None to simulate geocoding failure (or could return coords, 
        # but they won't be used for non-location tasks anyway)
        mock_places_instance.geocode_location.return_value = None
        mock_places_service.return_value = mock_places_instance
        
        # Test data without location requirement
        tasks_data = [{
            'task_title': 'Meeting with Tom',
            'task_description': '',
            'priority': 'medium',
            'due_datetime': '2026-02-06T14:00:00+03:00',
            'requires_location': False
        }]
        
        # Resolve tasks (should not modify title)
        resolved_tasks = _resolve_location_tasks(
            self.user,
            tasks_data,
            location_str='Kahunge, Kamwenge'
        )
        
        # Verify the task title was NOT modified
        self.assertEqual(len(resolved_tasks), 1)
        self.assertEqual(resolved_tasks[0]['task_title'], 'Meeting with Tom')
        # Geocode is called once for the batch, but recommendations are not 
        # called for non-location tasks
        mock_places_instance.geocode_location.assert_called_once()
        mock_places_instance.get_top_recommendations.assert_not_called()


class TestLocationMapsAndWidgets(TestCase):
    """Test maps link generation and location widget functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username='testuser', password='testpass')
        
        # Create user context with telegram chat_id
        UserContext.objects.create(
            user=self.user,
            context_type='preference',
            key='telegram_chat_id',
            value='12345'
        )
    
    def test_generate_google_maps_link_with_place_name(self):
        """Test Google Maps link generation with place name."""
        from core.tasks import generate_google_maps_link
        
        link = generate_google_maps_link(
            latitude=0.1,
            longitude=30.5,
            place_name='The Green Valley Eatery'
        )
        
        # Should contain encoded place name and coordinates
        self.assertIn('maps/search', link)
        # URL encoding uses %20 for spaces, not +
        self.assertIn('The%20Green%20Valley%20Eatery', link)
        self.assertIn('0.1,30.5', link)
    
    def test_generate_google_maps_link_without_place_name(self):
        """Test Google Maps link generation with coordinates only."""
        from core.tasks import generate_google_maps_link
        
        link = generate_google_maps_link(
            latitude=0.1,
            longitude=30.5
        )
        
        # Should be a direct coordinate link
        self.assertIn('maps?q=', link)
        self.assertIn('0.1,30.5', link)
    
    @patch('core.telegram_service.TelegramService.__init__', return_value=None)
    @patch('core.telegram_service.TelegramService._run_async')
    def test_send_location_widget_as_venue(self, mock_run_async, mock_init):
        """Test sending location widget as venue (with title and address)."""
        from core.telegram_service import TelegramService
        
        # Mock the async result
        mock_message = MagicMock()
        mock_message.message_id = 999
        mock_run_async.return_value = mock_message
        
        # Create telegram service instance directly
        telegram_service = TelegramService()
        telegram_service.bot = MagicMock()
        
        message_id = telegram_service.send_location(
            self.user,
            latitude=0.1,
            longitude=30.5,
            title='The Green Valley Eatery',
            address='Kahunge, Kamwenge'
        )
        
        # Verify message was sent
        self.assertEqual(message_id, 999)
        mock_run_async.assert_called_once()
    
    @patch('core.telegram_service.TelegramService.__init__', return_value=None)
    @patch('core.telegram_service.TelegramService._run_async')
    def test_send_location_widget_simple(self, mock_run_async, mock_init):
        """Test sending simple location widget without venue details."""
        from core.telegram_service import TelegramService
        
        # Mock the async result
        mock_message = MagicMock()
        mock_message.message_id = 888
        mock_run_async.return_value = mock_message
        
        # Create telegram service instance directly
        telegram_service = TelegramService()
        telegram_service.bot = MagicMock()
        
        message_id = telegram_service.send_location(
            self.user,
            latitude=0.1,
            longitude=30.5
        )
        
        # Verify message was sent
        self.assertEqual(message_id, 888)
        mock_run_async.assert_called_once()
    
    def test_format_confirmation_includes_maps_link(self):
        """Test that task confirmation includes maps link for location tasks."""
        from core.tasks import _format_multiple_tasks_confirmation
        from datetime import datetime
        import pytz
        
        # Create a task with location data
        task = Task.objects.create(
            user=self.user,
            title='Dinner at The Green Valley Eatery',
            description='Great restaurant',
            priority='medium',
            due_at=datetime(2026, 2, 6, 19, 0, 0, tzinfo=pytz.timezone('Africa/Nairobi')),
            location_name='The Green Valley Eatery',
            location_address='Kahunge, Kamwenge',
            location_data={
                'name': 'The Green Valley Eatery',
                'address': 'Kahunge, Kamwenge',
                'location': {'lat': 0.1, 'lng': 30.5},
                'rating': 4.5
            }
        )
        
        parsed = {
            'conversational_response': 'Enjoy your dinner!'
        }
        
        # Format confirmation
        confirmation = _format_multiple_tasks_confirmation([task], parsed)
        
        # Should include maps link
        self.assertIn('View on Maps', confirmation)
        self.assertIn('maps', confirmation.lower())
        self.assertIn('The Green Valley Eatery', confirmation)
    
    def test_format_reminder_includes_maps_link(self):
        """Test that reminder message includes maps link for location tasks."""
        from core.tasks import _format_reminder_message
        from datetime import datetime
        import pytz
        
        # Create a task with location data
        task = Task.objects.create(
            user=self.user,
            title='Dinner at The Green Valley Eatery',
            description='Great restaurant',
            priority='medium',
            due_at=datetime(2026, 2, 6, 19, 0, 0, tzinfo=pytz.timezone('Africa/Nairobi')),
            location_name='The Green Valley Eatery',
            location_address='Kahunge, Kamwenge',
            location_data={
                'name': 'The Green Valley Eatery',
                'address': 'Kahunge, Kamwenge',
                'location': {'lat': 0.1, 'lng': 30.5},
                'rating': 4.5
            }
        )
        
        # Format reminder
        message, buttons = _format_reminder_message(task)
        
        # Should include location info and maps link
        self.assertIn('The Green Valley Eatery', message)
        self.assertIn('View on Maps', message)
        self.assertIn('maps', message.lower())
        
        # Should have buttons
        self.assertEqual(len(buttons), 3)
