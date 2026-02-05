"""
Django management command to check Telegram webhook configuration.
"""
from django.core.management.base import BaseCommand
from core.telegram_service import get_telegram_service
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check current Telegram webhook configuration'

    def handle(self, *args, **options):
        """Check and display webhook info."""
        try:
            telegram_service = get_telegram_service()
            
            self.stdout.write(self.style.SUCCESS('Checking Telegram webhook configuration...'))
            
            # Get webhook info
            webhook_info = telegram_service._run_async(telegram_service.bot.get_webhook_info())
            
            self.stdout.write('\n' + '=' * 60)
            self.stdout.write(self.style.SUCCESS('Webhook Information:'))
            self.stdout.write('=' * 60)
            
            if webhook_info.url:
                self.stdout.write(f"URL: {self.style.WARNING(webhook_info.url)}")
                self.stdout.write(f"Has custom certificate: {webhook_info.has_custom_certificate}")
                self.stdout.write(f"Pending update count: {self.style.WARNING(str(webhook_info.pending_update_count))}")
                self.stdout.write(f"Max connections: {webhook_info.max_connections}")
                
                if webhook_info.ip_address:
                    self.stdout.write(f"IP address: {webhook_info.ip_address}")
                
                if webhook_info.last_error_date:
                    self.stdout.write(self.style.ERROR(f"\nLast error date: {webhook_info.last_error_date}"))
                    self.stdout.write(self.style.ERROR(f"Last error message: {webhook_info.last_error_message}"))
                else:
                    self.stdout.write(self.style.SUCCESS("\n✓ No recent errors"))
                
                if webhook_info.pending_update_count > 0:
                    self.stdout.write(self.style.WARNING(f"\n⚠ Warning: {webhook_info.pending_update_count} pending updates in queue"))
                    self.stdout.write("Consider running: python manage.py set_webhook <url> --drop-pending-updates")
                
            else:
                self.stdout.write(self.style.WARNING("No webhook is currently set (polling mode)"))
            
            self.stdout.write('=' * 60 + '\n')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error checking webhook: {e}'))
            logger.error(f"Error in check_webhook command: {e}", exc_info=True)
