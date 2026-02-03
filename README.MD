# Kabanda - personal chief of staff

Here is the architectural blueprint for the **AI Receptionist**. We are moving away from code syntax and focusing on the **system design** and **logic flow**.

Think of this system not as a "script," but as a digital employee sitting at a desk (your server), managing your time 24/7.

### The "Receptionist" Architecture

This system has four distinct stages. The AI "Receptionist" lives in Stage 2, but it controls the entire pipeline.

---

### Stage 1: The Ingestion (The "In-Tray")

The goal here is **zero friction**. You shouldn't have to type formatted commands. The system must accept "brain dumps."

* **Channels:**
* **Text:** Forwarded messages from other chats, quick one-liners ("buy milk"), or complex project thoughts.
* **Voice:** Audio notes sent while walking. The system must transcribe these (using Whisper) before handing them to the Receptionist.
* **Images:** A photo of a handwritten sticky note or a whiteboard. The system OCRs this text.


* **The "Receptionist" Hook:** Every single input is immediately wrapped in a JSON payload with metadata: `User ID`, `Timestamp (EAT)`, and `Source Platform`.

### Stage 2: The "Receptionist" Brain (Logic & MCP)

This is the core. The AI doesn't just "read" text; it **interrogates** it against a set of rules (The Model Context Protocol).

**The Decision Tree:**
When a message arrives, the Receptionist categorizes it into one of three buckets:

**A. The "New Task" Bucket**

* **Input:** "Remind me to check the heater in the brooder in 20 mins."
* **Action:**
1. **Normalize Time:** Converts "20 mins" from "Now" (Uganda Time) into a strict ISO timestamp.
2. **Clarify:** If the time is vague ("remind me later"), it applies a default rule (e.g., +2 hours) or flags it to ask you for clarification.
3. **Dispatch:** Sends the packet to the Scheduler.



**B. The "Modifier" Bucket (The MCP Power)**

* **Input:** "Actually, move that heater check to 5 PM."
* **Action:**
1. **Query:** The Receptionist looks up your "Pending Tasks" database.
2. **Match:** It identifies the task you *just* created.
3. **Update:** It kills the old timer (revokes the Celery task) and creates a new one for 17:00 EAT.



**C. The "Consultant" Bucket**

* **Input:** "What do I have to do this afternoon?"
* **Action:**
1. **Retrieve:** Fetches all tasks due between 12:00 PM and 6:00 PM.
2. **Summarize:** Returns a bulleted list.



### Stage 3: The Scheduler (The "Calendar")

The Receptionist hands off the approved work to the "dumb" but reliable automation layer.

* **The Ledger (Database):** Every request is logged. This is your "paper trail." If the server crashes, the database remembers what tasks are pending so they can be re-queued on reboot.
* **The Timer (Celery/Redis):** This is the mechanical clock. It holds the trigger. It doesn't "think"; it just waits for the exact millisecond to fire.

### Stage 4: The Output (The "Nag")

How the system gets your attention.

* **Level 1 (Gentle):** A Telegram text. "Arthur, check the brooder."
* **Level 2 (Urgent):** If you don't mark it "Done" within 10 minutes, the Receptionist escalates.
* **Level 3 (Nuclear):** The system triggers a **Phone Call** (via Twilio). The AI voice says: *"You have ignored the brooder task for 10 minutes. Do it now."*

---

### The User Experience (UX) Flow

1. **You:** *Forward a confusing email from a lecturer.*
2. **Receptionist (Thinking):** "This email mentions a submission on Friday at 5 PM. Today is Tuesday."
3. **Receptionist (Reply):** "I've extracted a deadline: **Project Submission**. scheduled for **Friday @ 17:00**. I will remind you at 10:00 AM that morning to finalize it. Is that correct?"
4. **You:** "Make it Thursday night."
5. **Receptionist:** "Updated. Reminder set for **Thursday @ 20:00**."

### Next Step: Building the "Receptionist" Persona

Since this is "literally" an assistant, we need to define its personality in the System Prompt.

**Do you want it to be:**

* **Ruthless:** "You are lazy. Get up and do the work."
* **Professional:** "Sir, your 3 PM task is due."
* **Adaptive:** Chill when you're ahead, urgent when you're behind.

Which persona fits your workflow best?