"""
AI Service for parsing user messages and extracting tasks using Grok (xAI).
"""
import os
import re
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import pytz
from django.conf import settings
import requests


class AIService:
    """Service for AI-powered message parsing and task extraction."""
    
    def __init__(self):
        """Initialize the AI service with Grok API."""
        self.api_key = settings.GROK_API_KEY
        if not self.api_key:
            raise ValueError("GROK_API_KEY not configured in settings")
        
        self.api_url = "https://api.x.ai/v1/chat/completions"
        self.model = settings.GROK_MODEL
        self.timezone = pytz.timezone(settings.TIME_ZONE)
    
    def parse_message(self, message: str, user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parse a user message and extract intent, task details, and timing.
        
        Args:
            message: The user's message text
            user_context: Optional dictionary with user context (projects, routines, etc.)
        
        Returns:
            Dictionary with parsed intent, task details, and normalized datetime
        """
        now = datetime.now(self.timezone)
        context_str = self._build_context_string(user_context) if user_context else ""
        
        # Include conversation history if available
        conversation_history = ""
        if user_context and 'conversation_history' in user_context:
            conversation_history = f"\n\n{user_context['conversation_history']}\n"
        
        prompt = f"""You are Kabanda, an AI personal assistant. Analyze this message and extract task information.

Current date/time: {now.strftime('%Y-%m-%d %H:%M %Z')} (East Africa Time)
{context_str}{conversation_history}

User message: "{message}"

Extract the following in JSON format:
{{
    "intent": "new_task|new_tasks|modify_task|delete_task|query_tasks|general_question|location_query_needed",
    "tasks": [
        {{
            "task_title": "Brief title of the task (max 100 chars). For location-based tasks, use simple action-oriented titles like 'Dinner', 'Lunch', 'Coffee meeting' without 'find' or 'search'.",
            "task_description": "Detailed description if provided",
            "priority": "low|medium|high|urgent",
            "due_datetime": "ISO 8601 datetime string in EAT timezone when task should be reminded",
            "requires_location": true/false,
            "location_query": "what type of place (e.g., 'cool restaurant', 'coffee shop', 'bar')",
            "location_type": "restaurant|cafe|bar|gym|etc"
        }}
    ],
    "query_type": "today|afternoon|evening|morning|week|upcoming|all",
    "confidence": 0.0-1.0,
    "clarification_needed": "Question to ask user if time/details are unclear",
    "conversational_response": "Natural language response to the user's message",
    "needs_location_input": true/false,
    "location_prompt": "Question to ask user for their location (e.g., 'Where are you right now?')"
}}

Rules:
- If message contains MULTIPLE tasks/reminders, use intent "new_tasks" and include all in tasks array
- Consider the conversation history when interpreting vague references like "that", "it", "the task"
- Parse natural time expressions like "in 20 mins", "at 5 PM", "tomorrow", "next Friday"

**CONTEXT-AWARE TIME PARSING:**
- If user says "at 7" or "at 10" and current time is {now.strftime('%H:%M')}:
  * If current hour is before noon (e.g., 8am) and time mentioned is < 12, assume they mean PM (evening)
  * If current hour is late night (after 11pm) and time is ambiguous, set clarification_needed
  * Times that have passed today should default to same time tomorrow UNLESS context suggests today
  * Example: It's 8am, user says "meeting at 7" → assume 7pm today (19:00)
  * Example: It's midnight, user says "at 7" → ask "Do you mean 7am or 7pm?"

**LOCATION HANDLING:**
- If user requests location-based task ("find a cool place", "nearby restaurant", "good bar"), set requires_location=true
- Set needs_location_input=true and provide location_prompt like "Where are you right now?" or "What area should I search in?"
- Make Kabanda "the plug for cool hangouts" - prioritize trendy, highly-rated places
- For location-based tasks, use simple action-oriented task_title like "Dinner", "Lunch", "Coffee" (NOT "Find place to eat" or "Search for restaurant")
  * Example: User says "find a place for dinner at 7" → task_title should be "Dinner" (NOT "Find place to eat for dinner")
  * The actual place name will be appended automatically when location is resolved

- If time is vague ("later", "soon"), set due_datetime to 2 hours from now and set clarification_needed
- Always output datetime in ISO 8601 format with EAT timezone (+03:00)
- For "remind me to X", intent is "new_task" (singular if one task)
- For "I have two meetings" or "schedule three things", intent is "new_tasks" (plural)
- For "move that to...", "change...", "update...", intent is "modify_task"
- For "delete...", "cancel...", "remove...", "forget...", intent is "delete_task"
- For "what do I have...", "list my tasks", intent is "query_tasks"
  * Set query_type based on user's question:
    - "this afternoon" → query_type="afternoon"
    - "this evening" / "tonight" → query_type="evening"
    - "this morning" → query_type="morning"
    - "this week" → query_type="week"
    - "upcoming" / "next few days" → query_type="upcoming"
    - "all tasks" / "everything" → query_type="all"
    - default / "today" → query_type="today"
- For general greetings or questions ("hi", "who are you"), intent is "general_question" and provide a clever/helpful conversational_response
- Set priority based on urgency indicators (ASAP, urgent, important, etc.)
- If user needs to provide location for location-based task, set intent to "location_query_needed"

Return ONLY valid JSON, no markdown or explanations."""

        try:
            # Call Grok API
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are Kabanda, an AI personal assistant. You parse user messages and extract task information. Always respond with valid JSON only, no markdown formatting."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3
            }
            
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            
            parsed_data = self._parse_ai_response(content)
            
            # Validate and normalize datetime for backward compatibility
            # Handle both old schema (single task) and new schema (tasks array)
            if parsed_data.get('intent') in ['new_task', 'modify_task']:
                # Legacy single-task format
                if parsed_data.get('due_datetime'):
                    parsed_data['due_datetime'] = self._normalize_datetime(parsed_data['due_datetime'])
            elif parsed_data.get('intent') == 'new_tasks':
                # New multi-task format
                if parsed_data.get('tasks'):
                    for task in parsed_data['tasks']:
                        if task.get('due_datetime'):
                            task['due_datetime'] = self._normalize_datetime(task['due_datetime'])
            
            return parsed_data
            
        except Exception as e:
            # Fallback to basic parsing if AI fails
            return self._fallback_parse(message, now)
    
    def _build_context_string(self, context: Dict[str, Any]) -> str:
        """Build context string from user context data."""
        lines = ["User Context:"]
        if context.get('projects'):
            lines.append(f"Current projects: {', '.join(context['projects'])}")
        if context.get('routines'):
            lines.append(f"Regular routines: {', '.join(context['routines'])}")
        return '\n'.join(lines)
    
    def _parse_ai_response(self, response_text: str) -> Dict[str, Any]:
        """Parse AI response, handling markdown code blocks."""
        # Remove markdown code blocks if present
        text = response_text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        
        return json.loads(text.strip())
    
    def _normalize_datetime(self, dt_string: str) -> str:
        """Normalize datetime string to ISO 8601 with EAT timezone."""
        # Parse various datetime formats and ensure EAT timezone
        try:
            # Try parsing as ISO 8601
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            # Convert to EAT
            dt_eat = dt.astimezone(self.timezone)
            return dt_eat.isoformat()
        except:
            # Return as-is if already valid
            return dt_string
    
    def _fallback_parse(self, message: str, now: datetime) -> Dict[str, Any]:
        """
        Fallback parser when AI fails.
        Basic regex-based parsing for simple time expressions.
        """
        # Default to 2 hours from now
        default_due = now + timedelta(hours=2)
        
        # Simple time pattern matching
        minutes_match = re.search(r'in (\d+) ?(mins?|minutes?)', message, re.IGNORECASE)
        hours_match = re.search(r'in (\d+) ?(hrs?|hours?)', message, re.IGNORECASE)
        
        if minutes_match:
            minutes = int(minutes_match.group(1))
            due_time = now + timedelta(minutes=minutes)
        elif hours_match:
            hours = int(hours_match.group(1))
            due_time = now + timedelta(hours=hours)
        else:
            due_time = default_due
        
        return {
            'intent': 'new_task',
            'task_title': message[:100],
            'task_description': '',
            'priority': 'medium',
            'due_datetime': due_time.isoformat(),
            'confidence': 0.5,
            'clarification_needed': 'Could you specify when you want to be reminded?',
            'confidence': 0.5,
            'clarification_needed': 'Could you specify when you want to be reminded?',
            'extracted_time_phrase': '',
            'conversational_response': "I'm not quite sure what you mean. Could you rephrase that as a task?"
        }


# Singleton instance
_ai_service = None

def get_ai_service() -> AIService:
    """Get or create AI service singleton."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
