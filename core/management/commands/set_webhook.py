"""
Django management command to set Telegram webhook URL.
"""
from django.core.management.base import BaseCommand, CommandError
from core.telegram_service import get_telegram_service
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Set Telegram webhook URL'

    def add_arguments(self, parser):
        parser.add_argument(
            'webhook_url',
            type=str,
            help='Webhook URL to set (e.g., https://yourdomain.com/api/webhook/telegram/)'
        )
        parser.add_argument(
            '--drop-pending-updates',
            action='store_true',
            help='Drop all pending updates before setting webhook'
        )
        parser.add_argument(
            '--max-connections',
            type=int,
            default=40,
            help='Maximum allowed number of simultaneous HTTPS connections (1-100, default: 40)'
        )

    def handle(self, *args, **options):
        """Set webhook URL."""
        webhook_url = options['webhook_url']
        drop_pending = options['drop_pending_updates']
        max_connections = options['max_connections']
        
        try:
            telegram_service = get_telegram_service()
            
            # Validate URL
            if not webhook_url.startswith('https://'):
                raise CommandError('Webhook URL must use HTTPS')
            
            self.stdout.write(self.style.SUCCESS(f'Setting webhook to: {webhook_url}'))
            
            # Delete existing webhook first
            self.stdout.write('Deleting existing webhook...')
            telegram_service._run_async(telegram_service.bot.delete_webhook(drop_pending_updates=drop_pending))
            self.stdout.write(self.style.SUCCESS('✓ Existing webhook deleted'))
            
            if drop_pending:
                self.stdout.write(self.style.WARNING('✓ Pending updates dropped'))
            
            # Set new webhook
            self.stdout.write(f'Setting new webhook (max_connections={max_connections})...')
            result = telegram_service._run_async(
                telegram_service.bot.set_webhook(
                    url=webhook_url,
                    max_connections=max_connections,
                    drop_pending_updates=False  # Already dropped above if requested
                )
            )
            
            if result:
                self.stdout.write(self.style.SUCCESS('✓ Webhook set successfully!'))
                
                # Verify
                self.stdout.write('\nVerifying webhook configuration...')
                webhook_info = telegram_service._run_async(telegram_service.bot.get_webhook_info())
                
                self.stdout.write(f"  URL: {webhook_info.url}")
                self.stdout.write(f"  Pending updates: {webhook_info.pending_update_count}")
                self.stdout.write(f"  Max connections: {webhook_info.max_connections}")
                
                self.stdout.write(self.style.SUCCESS('\n✓ Webhook configuration complete!'))
            else:
                self.stdout.write(self.style.ERROR('✗ Failed to set webhook'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error setting webhook: {e}'))
            logger.error(f"Error in set_webhook command: {e}", exc_info=True)
            raise CommandError(f'Failed to set webhook: {e}')
