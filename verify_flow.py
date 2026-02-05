
import os
import django
from unittest.mock import MagicMock, patch

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kabanda.settings")
django.setup()

from core.tasks import parse_user_message
from core.models import User, Task
from core.ai_service import AIService

def test_conversational_flow():
    print("Testing Conversational Flow...")
    
    # Mock services
    with patch('core.mongo_service.get_mongo_service') as mock_mongo_get, \
         patch('core.tasks.get_ai_service') as mock_ai_get, \
         patch('core.tasks.get_telegram_service') as mock_telegram_get:
        
        # Setup mocks
        mock_mongo = MagicMock()
        mock_mongo_get.return_value = mock_mongo
        mock_mongo.get_conversation_context.return_value = "Mock Context"
        
        mock_ai = MagicMock()
        mock_ai_get.return_value = mock_ai
        
        mock_telegram = MagicMock()
        mock_telegram_get.return_value = mock_telegram
        
        # Create dummy user
        user, _ = User.objects.get_or_create(username='test_user')
        
        # Test 1: General Question
        print("\n[Test 1] General Question")
        mock_ai.parse_message.return_value = {
            'intent': 'general_question',
            'conversational_response': 'Hello! I am Kabanda.'
        }
        
        parse_user_message(user.id, "Hi there")
        
        # Verify AI called
        mock_ai.parse_message.assert_called()
        # Verify response sent
        mock_telegram.send_message.assert_called_with(user, 'Hello! I am Kabanda.')
        print("✅ General question handled correctly with AI response.")
        
        # Test 2: Delete Task
        print("\n[Test 2] Delete Task")
        # Create task to delete
        Task.objects.create(user=user, title="Task to delete", status='pending', due_at="2024-01-01T12:00:00Z", source_message="src")
        
        mock_ai.parse_message.return_value = {
            'intent': 'delete_task',
        }
        
        parse_user_message(user.id, "Delete that task")
        
        # Check task status
        task = Task.objects.filter(user=user, title="Task to delete").last()
        if task.status == 'cancelled':
            print(f"✅ Task '{task.title}' was cancelled.")
        else:
            print(f"❌ Task status is {task.status}")

        # Check response
        args, _ = mock_telegram.send_message.call_args
        if "cancelled" in args[1]:
            print(f"✅ Confirmation sent: {args[1]}")
        else:
            print(f"❌ Unexpected response: {args[1]}")

if __name__ == "__main__":
    test_conversational_flow()
