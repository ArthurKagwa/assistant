"""
MongoDB service for storing conversation history.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from pymongo import MongoClient, DESCENDING
from django.conf import settings

logger = logging.getLogger(__name__)


class MongoConversationService:
    """Service for managing conversation history in MongoDB."""
    
    def __init__(self):
        """Initialize MongoDB connection."""
        self.mongodb_url = settings.MONGODB_URL
        self.client = MongoClient(self.mongodb_url)
        self.db = self.client.kabanda
        self.conversations = self.db.conversations
        
        # Create indexes
        self.conversations.create_index([("user_id", 1), ("timestamp", DESCENDING)])
        self.conversations.create_index([("chat_id", 1), ("timestamp", DESCENDING)])
    
    def save_message(
        self,
        user_id: int,
        chat_id: int,
        direction: str,
        message: str,
        message_type: str = 'text',
        telegram_message_id: Optional[int] = None,
        ai_intent: Optional[str] = None,
        ai_response: Optional[str] = None,
        task_id: Optional[int] = None
    ) -> str:
        """
        Save a message to conversation history.
        
        Args:
            user_id: Django user ID
            chat_id: Telegram chat ID
            direction: 'incoming' or 'outgoing'
            message: Message content
            message_type: Type of message (text, image, etc.)
            telegram_message_id: Telegram message ID
            ai_intent: Detected intent from AI
            ai_response: AI response text
            task_id: Associated task ID if any
        
        Returns:
            MongoDB document ID as string
        """
        try:
            doc = {
                'user_id': user_id,
                'chat_id': chat_id,
                'direction': direction,
                'message': message,
                'message_type': message_type,
                'telegram_message_id': telegram_message_id,
                'ai_intent': ai_intent,
                'ai_response': ai_response,
                'task_id': task_id,
                'timestamp': datetime.utcnow()
            }
            
            result = self.conversations.insert_one(doc)
            logger.info(f"Saved message to MongoDB: {result.inserted_id}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Error saving message to MongoDB: {e}", exc_info=True)
            return None
    
    def get_recent_messages(
        self,
        user_id: int,
        limit: int = 6
    ) -> List[Dict[str, Any]]:
        """
        Get recent conversation messages for context.
        
        Args:
            user_id: Django user ID
            limit: Number of messages to retrieve (default 6)
        
        Returns:
            List of message dictionaries ordered by timestamp (oldest first)
        """
        try:
            messages = list(
                self.conversations
                .find({'user_id': user_id})
                .sort('timestamp', DESCENDING)
                .limit(limit)
            )
            
            # Reverse to get chronological order (oldest first)
            messages.reverse()
            
            # Format messages for AI context
            formatted = []
            for msg in messages:
                formatted.append({
                    'direction': msg.get('direction'),
                    'message': msg.get('message'),
                    'ai_intent': msg.get('ai_intent'),
                    'timestamp': msg.get('timestamp').isoformat() if msg.get('timestamp') else None
                })
            
            return formatted
            
        except Exception as e:
            logger.error(f"Error retrieving messages from MongoDB: {e}", exc_info=True)
            return []
    
    def get_conversation_context(
        self,
        user_id: int,
        limit: int = 6
    ) -> str:
        """
        Get conversation context as formatted string for AI.
        
        Args:
            user_id: Django user ID
            limit: Number of recent messages to include
        
        Returns:
            Formatted conversation context string
        """
        messages = self.get_recent_messages(user_id, limit)
        
        if not messages:
            return "No previous conversation history."
        
        context_lines = ["Recent conversation:"]
        for msg in messages:
            role = "User" if msg['direction'] == 'incoming' else "Assistant"
            context_lines.append(f"{role}: {msg['message']}")
            
            if msg.get('ai_intent'):
                context_lines.append(f"  (Intent: {msg['ai_intent']})")
        
        return "\n".join(context_lines)
    
    def clear_old_messages(self, days: int = 30):
        """
        Clear messages older than specified days.
        
        Args:
            days: Number of days to keep (default 30)
        """
        try:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            result = self.conversations.delete_many({
                'timestamp': {'$lt': cutoff}
            })
            
            logger.info(f"Deleted {result.deleted_count} old messages")
            
        except Exception as e:
            logger.error(f"Error clearing old messages: {e}", exc_info=True)


# Singleton instance
_mongo_service = None


def get_mongo_service() -> MongoConversationService:
    """Get or create MongoDB service singleton."""
    global _mongo_service
    if _mongo_service is None:
        _mongo_service = MongoConversationService()
    return _mongo_service
