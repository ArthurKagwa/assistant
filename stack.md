# Kabanda - the satck
Since you're building this on your own infrastructure (Kali, Microservices background) and you want it to be "literally" an assistant, we need a stack that is **robust**, **persistent**, and **low-latency**.

Here is the official **Kabanda Tech Stack**.

### 1. The Core (The Nervous System)

* **Framework:** **Django** (Python).
* *Why:* You already know it (`Bookutu`), it has the best ORM for managing complex relationships (User -> Tasks -> Reminders -> Logs), and the built-in Admin panel gives you a "God View" of Kabanda’s brain.


* **Database:** **PostgreSQL**.
* *Why:* You're already using single-instance schemas. We will create a dedicated schema `kabanda_core`. It handles the concurrency of Celery workers better than SQLite.


* **API Gateway:** **Nginx** + **Gunicorn**.
* *Why:* You need a reverse proxy to handle the SSL termination required for Telegram Webhooks.



### 2. The Muscle (The Scheduler)

* **Broker:** **Redis**.
* *Why:* It’s the industry standard for Celery. It’s fast, in-memory, and prevents task loss if the Django app restarts.


* **Worker:** **Celery**.
* *Why:* It allows "Kabanda" to multi-task. He can be parsing a long email from your professor in the background while simultaneously pinging you about a farm sensor alert.


* **Beat:** **Django Celery Beat**.
* *Why:* This adds a database-backed scheduler. You can view/edit scheduled tasks directly in the Django Admin. If you need to "postpone" a task, you just update the record in the DB, and Beat handles the rest.



### 3. The Brain (The Intelligence)

* **LLM Interface:** **Google Gemini Pro** or **Grok** (via XAI).
* *Why:*
* **Gemini 2.0 Flash:** Ultra-low latency, huge context window (great for forwarding entire PDFs/documents), and free tier.
* **Grok:** You’re already using it for `MemoDraft`. It has a "rebellious/truthful" persona that fits the "Kabanda" vibe if you want him to be blunt.




* **Framework:** **Raw API Calls** (No LangChain).
* *Why:* Keep it "bare metal." You don't need the bloat. Just a clean `ai_service.py` module that inputs text and outputs JSON.



### 4. The Mouth (Input/Output)

* **Primary Interface:** **Telegram Bot API**.
* *Why:* No cost, unlimited messages, easy file handling, and reliable push notifications.


* **Escalation Channel:** **Twilio Voice API**.
* *Why:* When you ignore Telegram, Kabanda calls your actual phone number.


* **Ears (Transcription):** **OpenAI Whisper** (Self-hosted or API).
* *Why:* Send a voice note -> Kabanda transcribes it -> Parser extracts tasks.



---

### The "Kabanda" Data Flow

1. **Ingest:** `Telegram Webhook` -> `Django View`.
2. **Parse:** `Django` -> `Gemini/Grok` (Extracts Intent & Time).
3. **Persist:** Save to `Postgres` (Model: `Task`).
4. **Schedule:** Create `Celery Task` (Payload: `task_id`).
5. **Wait:** `Redis` holds the ticket.
6. **Execute:** `Celery Worker` wakes up at `eta`.
7. **Notify:** `Worker` -> `Telegram API` (or `Twilio` if urgent).

### The Deployment (Kali/Server)

Since you like containerization and microservices:

```yaml
# docker-compose.yml (Concept)
services:
  kabanda-web:
    build: .
    command: gunicorn kabanda.wsgi:application
    ports: ["8000:8000"]
    depends_on:
      - db
      - redis

  kabanda-worker:
    build: .
    command: celery -A kabanda worker -l info
    depends_on:
      - redis

  kabanda-beat:
    build: .
    command: celery -A kabanda beat -l info
    depends_on:
      - redis

  redis:
    image: redis:alpine

  db:
    image: postgres:15

```

### The "Secret Sauce": Context Awareness

To make Kabanda smart, we add a **Context Table** in Postgres.

* **Table:** `user_context`
* **Fields:** `key` (e.g., "current_project"), `value` (e.g., "Tundamate Inventory"), `expiry`.

When you say "Remind me to fix the bug," Kabanda checks `current_project` and realizes you mean the **Tundamate** bug, not the **Bookutu** bug.

**Does this stack feel heavy or just right for you?** (I think for a dev on Kali, this is the perfect "power user" setup).