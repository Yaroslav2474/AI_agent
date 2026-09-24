import json
import logging
from typing import Dict, Any, Optional
from openai import AsyncOpenAI
from src.utils.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url="https://openrouter.ai/api/v1"
        )

    async def parse_guest_message(self, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse guest message to extract structured information
        Context includes booking info and current state
        """
        system_prompt = """
You are a helpful assistant for a recreation base check-in system. Parse guest messages to extract structured information.

Extract the following fields if present:
- adults: number of adults (integer)
- children: number of children (integer)
- arrival_time: arrival time in HH:MM format
- has_car: boolean (true if guest mentions car/vehicle/machine)
- car_plates: array of car license plates (strings)
- has_pet: boolean (true if guest mentions pet/animal/dog/cat)
- extra_bed_requested: boolean (true if guest requests extra bed)
- early_arrival_requested: boolean (true if guest requests early arrival)
- breakfast_requested: boolean (true if guest requests breakfast)
- coal_quantity: number of coal packages requested (integer)
- rules_accepted: boolean (true if guest accepts rules)
- human_request: any request that needs human attention (string)

IMPORTANT: Return ONLY a valid JSON object. Do not include any text outside the JSON.
For car_plates, return empty array [] if no car mentioned or "без машины".
For time, validate it's in HH:MM format (00:00-23:59).
Set null for any field not mentioned in the message.
"""

        content = None
        try:
            logger.info(f"LLM parsing message: {message}")
            response = await self.client.chat.completions.create(
                model="openrouter/free",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Message: {message}\nContext: {json.dumps(context, ensure_ascii=False)}"}
                ],
                temperature=0.3
            )

            content = response.choices[0].message.content
            logger.info(f"LLM raw response: {content}")

            # Handle potential markdown code blocks
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = json.loads(content)
            logger.info(f"LLM parsed successfully: {result}")
            return result

        except json.JSONDecodeError as e:
            logger.exception(f"JSON parsing error: {e}, content: {content}")
            return {"error": f"JSON parsing error: {e}"}
        except Exception as e:
            logger.exception(f"LLM parsing error: {e}")
            return {"error": str(e)}

    async def classify_message(self, message: str) -> str:
        """
        Classify message type: normal_question, change_request, security_question, escalation_needed
        """
        system_prompt = """
Classify the guest message into one of these categories:
- normal_question: general question about facilities, services, directions
- change_request: request to change booking details, dates, etc.
- security_question: questions about rules, fines, fireworks, prohibited items
- escalation_needed: anything that requires human administrator attention

Return ONLY the category name.
"""

        try:
            response = await self.client.chat.completions.create(
                model="meta-llama/llama-3.1-70b-instruct:free",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                temperature=0.1
            )

            return response.choices[0].message.content.strip().lower()

        except Exception as e:
            logger.exception(f"LLM classification error: {e}")
            return "normal_question"

# Global instance
llm_service = LLMService()
