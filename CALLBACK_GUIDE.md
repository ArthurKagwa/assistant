# How to Add Your Callback to the Server



### Step 1: Register Your Webhook URL with Telegram

Tell Telegram where to send callbacks by POSTing to their API:

```
POST https://api.telegram.org/bot/setWebhook
```

**Body:**
```json
{
  "url": "https://yourdomain.com/api/webhook/telegram/"
}
```

Once set, Telegram will POST all user interactions to this URL.

---

curl -X POST "https://api.telegram.org/bot7962143733:AAEBpHcRDZB32SWSXaUy8dLTpBwLT00NJK0/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://kabanda.memodraft.com/api/webhook/telegram/"}'

### Step 2: Telegram POSTs to Your Server

When a user clicks a button, Telegram sends:

```
POST https://yourdomain.com/api/webhook/telegram/
Content-Type: application/json

{
  "callback_query": {
    "id": "123456",
    "from": {
      "id": 987654321,
      "first_name": "User"
    },
    "data": "complete_456"
  }
}
```

The `data` field contains the button's callback data.

---

### Step 3: Your Server Receives and Processes

Your server at `/api/webhook/telegram/` receives the POST request and:

1. Extracts the callback data (`complete_456`)
2. Parses it (action: `complete`, task ID: `456`)
3. Performs the action (mark task complete)
4. Responds to Telegram
5. Returns HTTP 200 to acknowledge receipt

---

## Setting Up Your Callback Handler

### URL Configuration

In [core/urls.py](core/urls.py), you already have:

```
/api/webhook/telegram/  → handles all Telegram callbacks
```

### View Handler

In [core/views.py](core/views.py), the `telegram_webhook` function receives all POSTs from Telegram.

It routes button callbacks to `_handle_callback_query()`.

---

## Adding Your Custom Callback

### 1. Choose a Callback Pattern

Format: `action_identifier`

Examples:
- `approve_123` - Approve item 123
- `delete_456` - Delete item 456
- `menu_settings` - Open settings menu

### 2. Edit the Callback Handler

In [core/views.py](core/views.py), find `_handle_callback_query()` and add your action:

```python
if action == 'approve':
    # Your logic here
    item = get_item(identifier)
    item.approve()
    response = "✅ Approved"
```

### 3. Send a Button with Your Callback

When sending messages with buttons, include your callback data:

```python
buttons = [
    {'text': '✅ Approve', 'callback_data': 'approve_123'}
]
```

Telegram will POST this exact string back to your server when clicked.

---

## Testing Your Callback

### Option 1: Test via Telegram
1. Send a message with your button
2. Click the button in Telegram
3. Watch your server logs

### Option 2: Simulate the POST
Send a POST request to your local server:

```bash
curl -X POST http://localhost:8000/api/webhook/telegram/ \
  -H "Content-Type: application/json" \
  -d '{
    "callback_query": {
      "id": "test",
      "from": {"id": 123456},
      "data": "approve_789"
    }
  }'
```

---

## Key Points

1. **Telegram POSTs to you** - You don't poll or request, Telegram pushes
2. **Always return 200** - Even if processing fails, acknowledge receipt
3. **Callback data is a string** - Parse it however you like
4. **Keep it simple** - `action_id` format works for most cases

---

## Checking Your Webhook Status

Verify Telegram knows your webhook URL:

```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
```

Response shows:
- Your registered URL
- Last error (if any)
- Pending update count

---

*Last updated: February 4, 2026*
