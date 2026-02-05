#!/bin/bash

BASE_URL="http://localhost:8000/api/webhook/telegram/"

echo "1. Sending 'Hi'..."
curl -s -X POST $BASE_URL \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "chat": {"id": 12345},
      "text": "Hi, who are you?",
      "message_id": 1001
    }
  }'
echo -e "\n"
sleep 2

echo "2. Sending 'New Task'..."
curl -s -X POST $BASE_URL \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "chat": {"id": 12345},
      "text": "Remind me to check the logs in 5 minutes",
      "message_id": 1002
    }
  }'
echo -e "\n"
sleep 5  # Wait for Celery

echo "3. Sending 'Delete Task'..."
curl -s -X POST $BASE_URL \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "chat": {"id": 12345},
      "text": "Delete that task",
      "message_id": 1003
    }
  }'
echo -e "\n"
sleep 2

echo "Done."
