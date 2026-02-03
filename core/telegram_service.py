"""
Telegram Bot service for sending/receiving messages.
"""
import logging
import asyncio
from typing import Optional
from django.conf import settings
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class TelegramService:
    """Service for Telegram Bot interactions."""
    
    def __init__(self):
        """Initialize Telegram Bot."""
        self.token = settings.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")
        
        self.bot = Bot(token=self.token)
    
    def send_message(self, user, message: str, parse_mode: str = 'Markdown') -> Optional[int]:
        """
        Send a message to a user via Telegram.
        
        Args:
            user: Django User object (should have telegram_chat_id attribute or profile)
            message: Message text to send
            parse_mode: Parse mode for formatting (Markdown or HTML)
        
        Returns:
            Message ID if successful, None otherwise
        """
        try:
            # Get Telegram chat ID from user
            chat_id = self._get_user_chat_id(user)
            if not chat_id:
                logger.error(f"No Telegram chat ID found for user {user.username}")
                return None
            
            # Run async operation in sync context
            result = asyncio.run(self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode
            ))
            return result.message_id
            
        except TelegramError as e:
            logger.error(f"Telegram error sending message to {user.username}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}", exc_info=True)
            return None
    
    def _get_user_chat_id(self, user) -> Optional[int]:
        """
        Get Telegram chat ID for user.
        
        Try to get from:
        1. user.profile.telegram_chat_id
        2. user.telegram_chat_id
        3. UserContext with key 'telegram_chat_id'
        """
        # Try profile first
        if hasattr(user, 'profile') and hasattr(user.profile, 'telegram_chat_id'):
            return user.profile.telegram_chat_id
        
        # Try direct attribute
        if hasattr(user, 'telegram_chat_id'):
            return user.telegram_chat_id
        
        # Try UserContext
        try:
            from .models import UserContext
            context = UserContext.objects.filter(
                user=user,
                context_type='preference',
                key='telegram_chat_id',
                is_active=True
            ).first()
            if context:
                return int(context.value)
        except:
            pass
        
        return None
    
    def set_webhook(self, webhook_url: str) -> bool:
        """
        Set webhook URL for receiving messages.
        
        Args:
            webhook_url: Full webhook URL
        
        Returns:
            True if successful
        """
        try:
            result = asyncio.run(self.bot.set_webhook(url=webhook_url))
            logger.info(f"Webhook set to {webhook_url}: {result}")
            return result
        except TelegramError as e:
            logger.error(f"Error setting webhook: {e}")
            return False
    
    def delete_webhook(self) -> bool:
        """
        Delete webhook (switch to polling mode).
        
        Returns:
            True if successful
        """
        try:
            result = asyncio.run(self.bot.delete_webhook())
            logger.info(f"Webhook deleted: {result}")
            return result
        except TelegramError as e:
            logger.error(f"Error deleting webhook: {e}")
            return False


# Singleton instance
_telegram_service = None


def get_telegram_service() -> TelegramService:
    """Get or create Telegram service singleton."""
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service
