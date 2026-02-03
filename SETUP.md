# Kabanda - AI Personal Assistant

Kabanda is an AI-powered personal assistant that helps you manage tasks and reminders through natural language via Telegram. It uses Google Gemini AI for intelligent task parsing and Celery for reliable task scheduling.

## Architecture

The system follows a 4-stage architecture:

1. **Ingestion** - Telegram webhook receives messages
2. **AI Brain** - Gemini AI parses intent and extracts task details
3. **Scheduler** - Celery + Redis handle task timing
4. **Output** - Telegram notifications with escalation levels

## Tech Stack

- **Backend**: Django 5.0 + Django REST Framework
- **Database**: PostgreSQL (schema: `kabanda_core`)
- **Task Queue**: Celery + Redis
- **AI**: Google Gemini 2.0 Flash
- **Interface**: Telegram Bot API
- **Deployment**: Docker Compose
- **Web Server**: Gunicorn + Nginx

## Project Structure

```
assistant/
├── kabanda/              # Django project
│   ├── settings.py       # Configuration
│   ├── celery.py         # Celery setup
│   └── urls.py           # URL routing
├── core/                 # Main application
│   ├── models.py         # Database models
│   ├── views.py          # API endpoints
│   ├── tasks.py          # Celery tasks
│   ├── ai_service.py     # Gemini AI integration
│   └── telegram_service.py
├── docker-compose.yml    # Container orchestration
├── Dockerfile            # Application container
├── nginx.conf            # Reverse proxy config
├── requirements.txt      # Python dependencies
└── .env.example          # Environment template
```

## Quick Start

### 1. Environment Setup

Copy the environment template and configure your API keys:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:
- `TELEGRAM_BOT_TOKEN` - Get from [@BotFather](https://t.me/botfather)
- `GEMINI_API_KEY` - Get from [Google AI Studio](https://makersuite.google.com/app/apikey)
- `DB_PASSWORD` - Set a secure password
- `SECRET_KEY` - Generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

### 2. Development (Local with venv)

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies (already done)
# pip install -r requirements.txt

# Start PostgreSQL and Redis (you'll need these running)
# Option 1: Use system services
sudo systemctl start postgresql redis

# Option 2: Use Docker for services only
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16-alpine
docker run -d -p 6379:6379 redis:7-alpine

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start Django dev server
python manage.py runserver

# In separate terminals, start Celery
celery -A kabanda worker -l info
celery -A kabanda beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### 3. Production (Docker Compose)

```bash
# Build and start all services
docker-compose up -d

# Check logs
docker-compose logs -f

# Run migrations (first time only)
docker-compose exec web python manage.py migrate

# Create superuser
docker-compose exec web python manage.py createsuperuser

# Stop all services
docker-compose down
```

## Setting Up Telegram Webhook

### For Local Development (ngrok)

```bash
# Install ngrok
snap install ngrok

# Start ngrok tunnel
ngrok http 8000

# Get your ngrok URL (e.g., https://abc123.ngrok.io)
# Update .env with:
TELEGRAM_WEBHOOK_URL=https://abc123.ngrok.io/api/webhook/telegram/

# Set webhook with Telegram
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
     -d "url=https://abc123.ngrok.io/api/webhook/telegram/"
```

### For Production

1. Configure your domain's DNS to point to your server
2. Set up SSL certificates (Let's Encrypt recommended)
3. Update `.env` with your domain:
   ```
   TELEGRAM_WEBHOOK_URL=https://your-domain.com/api/webhook/telegram/
   ```
4. Set webhook:
   ```bash
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
        -d "url=https://your-domain.com/api/webhook/telegram/"
   ```

## Usage

### Basic Commands

Send messages to your Telegram bot:

**Create Tasks:**
- "Remind me to check the brooder in 20 minutes"
- "Call mom at 5 PM"
- "Submit project tomorrow at 10 AM"

**Modify Tasks:**
- "Move that to 6 PM"
- "Change it to tomorrow"
- "Make it urgent"

**Query Tasks:**
- "What do I have today?"
- "List my tasks"
- "What's next?"

### Task Completion

When you receive a reminder, reply with:
- "Done" - Mark as completed
- "Snooze 10" - Snooze for 10 minutes
- "Cancel" - Cancel the task

## Admin Interface

Access the Django admin at `http://localhost:8000/admin/`

View and manage:
- Tasks and their status
- User contexts (projects, preferences)
- Conversation logs
- Reminder history
- Scheduled Celery tasks

## API Endpoints

- `POST /api/webhook/telegram/` - Telegram webhook (public)
- `POST /api/task/<id>/complete/` - Mark task complete
- `POST /api/task/<id>/snooze/` - Snooze task
- `POST /api/task/<id>/cancel/` - Cancel task
- `GET /api/health/` - Health check

## Database Models

### Task
Main task/reminder model with:
- Status (pending, in_progress, completed, cancelled, snoozed)
- Priority (low, medium, high, urgent)
- Timing (due_at, snoozed_until)
- Escalation tracking (reminder_count)

### UserContext
Stores user information:
- Projects (ongoing work)
- Routines (regular activities)
- Preferences (settings)
- Location (context)

### Reminder
Tracks individual reminder attempts:
- Channel (telegram, phone_call, sms)
- Status (scheduled, sent, delivered, failed, acknowledged)
- Timestamps and external IDs

### ConversationLog
Logs all interactions for debugging and context:
- Message direction and type
- AI processing details
- Response times

## Escalation System

Kabanda uses a 3-level escalation:

1. **Level 1** (0-1 reminders): Gentle Telegram notification
2. **Level 2** (2-3 reminders): Persistent notifications every 10 minutes
3. **Level 3** (4+ reminders): Urgent warnings (Phone call in future)

## Development

### Running Tests

```bash
pytest
```

### Code Quality

```bash
# Format code
black .

# Lint
flake8
```

### Database Migrations

```bash
# Create migration
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration SQL
python manage.py sqlmigrate core 0001
```

## Troubleshooting

### Celery not picking up tasks
```bash
# Check Redis connection
redis-cli ping

# Restart Celery worker
celery -A kabanda worker -l info --purge
```

### Webhook not receiving messages
```bash
# Check webhook status
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo

# Delete and reset webhook
curl https://api.telegram.org/bot<TOKEN>/deleteWebhook
```

### Database connection errors
```bash
# Check PostgreSQL is running
pg_isready -h localhost -U postgres

# Test connection
psql -h localhost -U postgres -d kabanda_db
```

## Future Enhancements

- [ ] Twilio phone call escalation
- [ ] WhisperOpenAI voice transcription
- [ ] Image OCR for task extraction
- [ ] Recurring task patterns
- [ ] Team/shared tasks
- [ ] Natural language task queries
- [ ] Task dependencies
- [ ] Mobile app

## License

MIT

## Support

For issues and questions, check the conversation logs in Django admin or review Celery worker logs.
