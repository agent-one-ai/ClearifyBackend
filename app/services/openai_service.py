import asyncio
import logging
from typing import Dict, Any, Optional

from openai import AsyncOpenAI, APIError, RateLimitError
from app.core.config import settings
from app.core.supabase_client import supabase_client
from fastapi import HTTPException
import httpx

logger = logging.getLogger(__name__)
# Mappa processing_type -> nome prompt DB
PROCESSING_TYPE_TO_PROMPT_NAME = {
    "HUMANIZER": "humanizer",
    "GRAMMAR": "grammar",
    "STYLE": "style",
    "PROFESSIONAL": "professional",
}

class OpenAIService:
    def __init__(self, max_retries: int = 3, request_timeout: int = 200):
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key is required")
        self.prompts_cache: Dict[str, str] = {}  # {name: prompt}
        self.max_retries = max_retries
        self.request_timeout = request_timeout
        logger.debug(
            "OpenAIService initialized (max_retries=%s, timeout=%s)",
            max_retries, request_timeout
        )

    async def _fetch_prompts_from_db(self) -> Dict[str, str]:
        """Fetch all prompts from DB and cache them."""
        try:
            logger.info("Fetching prompts from database...")
            response = supabase_client.table("prompts").select("name, prompt").execute()
            data = getattr(response, "data", None)
            if not data:
                logger.warning("No prompts found in database (empty response.data).")
                return {}

            prompts_dict = {row["name"]: row["prompt"] for row in data}
            self.prompts_cache = prompts_dict
            logger.info(
                "Cached %d prompts: %s",
                len(prompts_dict), list(prompts_dict.keys())
            )
            return prompts_dict

        except Exception as e:
            logger.exception("Failed to fetch prompts from database: %s", e)
            return {}

    async def _get_prompt(self, prompt_name: str) -> str:
        """Get a specific prompt by name from cache or DB."""
        logger.debug("Retrieving prompt name='%s'", prompt_name)

        if not self.prompts_cache:
            logger.debug("Prompts cache empty. Loading from DB...")
            await self._fetch_prompts_from_db()

        if prompt_name in self.prompts_cache:
            logger.debug("Prompt '%s' served from cache", prompt_name)
            return self.prompts_cache[prompt_name]

        try:
            logger.debug("Prompt '%s' not in cache. Querying DB...", prompt_name)
            response = supabase_client.table("prompts").select("name, prompt").eq("name", prompt_name).execute()
            data = getattr(response, "data", None)
            if data:
                prompt = data[0]["prompt"]
                self.prompts_cache[prompt_name] = prompt
                logger.debug("Prompt '%s' loaded from DB and cached", prompt_name)
                return prompt
        except Exception as e:
            logger.exception("Failed to fetch prompt '%s': %s", prompt_name, e)

        fallback = f"Process the following text according to the '{prompt_name}' requirements: {{text}}"
        logger.warning("Prompt '%s' not found. Using fallback.", prompt_name)
        return fallback

    async def _get_mapped_prompt(self, processing_type: str) -> str:
        """Restituisce il prompt corretto usando il mapping processing_type -> DB name."""
        prompt_name = PROCESSING_TYPE_TO_PROMPT_NAME.get(processing_type.upper(), processing_type)
        return await self._get_prompt(prompt_name)

    async def process_text(
        self,
        text: str,
        processing_type: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """Process text using OpenAI with DB-backed prompts, merging tone if provided."""
        logger.info("=== TEXT PROCESSING START ===")
        logger.info("Processing type: %s | Text length: %d chars", processing_type, len(text))

        # Se processing_type è humanizer, salta OpenAI e vai direttamente all'umanizzazione
        if processing_type.upper() == "HUMANIZER":
            logger.info("=== HUMANIZER MODE: Skipping OpenAI, going directly to humanization ===")
            result = await humanize_text(text, 'medium')
            logger.info("=== TEXT PROCESSING SUCCESS (HUMANIZER) ===")
            return result

        # 1) System instructions (agent_prompt)
        logger.debug("Loading agent_prompt...")
        agent_instructions = await self._get_prompt("agent_prompt")
        if not agent_instructions:
            logger.warning("agent_prompt not found. Using default fallback instructions.")
            agent_instructions = (
                "You are a professional text improvement assistant. Transform the provided text "
                "according to the given tone or template. Output only the transformed text."
            )
        logger.info("AGENT prompt:\n%s", agent_instructions)

        # 2) Prompt specifico per l’operazione (processing_type) con mapping
        logger.debug("Loading base prompt for processing_type='%s'...", processing_type)
        base_prompt = await self._get_mapped_prompt(processing_type)
        logger.debug("Base prompt: %s", base_prompt)

        # 3) Merge con prompt del tone se presente
        tone_prompt = ""
        if options and "tone" in options:
            tone_prompt = await self._get_prompt(options["tone"])
            logger.debug("Tone prompt: %s", tone_prompt)
        
        # 3) Merge con prompt del template
        template_prompt = ""
        if options and "template" in options:
            template_prompt = await self._get_prompt(options["template"])
            logger.debug("Template prompt: %s", template_prompt)

        # 4) Costruzione prompt finale
        final_prompt_parts = [part for part in [base_prompt, tone_prompt, template_prompt] if part]
        prompt = "\n\n".join(final_prompt_parts)

        if "{text}" in prompt or "[text]" in prompt:
            prompt = prompt.replace("{text}", text).replace("[text]", text)
        else:
            logger.debug("No {text} placeholder found. Appending text at the end.")
            prompt = f"{prompt}\n\n{text}"

        # Opzioni aggiuntive
        if options:
            for key in ["style", "target_audience"]:
                if key in options:
                    prompt += f"\n{key.replace('_',' ').title()}: {options[key]}"

        # 5) Chiamata OpenAI con retry
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info("OpenAI API call attempt %d/%d", attempt, self.max_retries)

                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": agent_instructions},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=max(500, len(text.split()) * 10),
                        temperature=0.7,
                        top_p=1.0
                    ),
                    timeout=self.request_timeout
                )

                processed_text = response.choices[0].message.content.strip()
                logger.debug("Raw OpenAI response: %s", processed_text)

                if "<TRANSFORMED_TEXT>" in processed_text and "</TRANSFORMED_TEXT>" in processed_text:
                    start_tag = "<TRANSFORMED_TEXT>"
                    end_tag = "</TRANSFORMED_TEXT>"
                    start_idx = processed_text.find(start_tag) + len(start_tag)
                    end_idx = processed_text.find(end_tag)
                    processed_text = processed_text[start_idx:end_idx].strip()

                logger.info("=== TEXT PROCESSING SUCCESS ===")

                # Ritorno il testo processato
                return processed_text

            except (RateLimitError, APIError, asyncio.TimeoutError) as e:
                logger.warning("OpenAI request failed on attempt %d: %s", attempt, e)
                if attempt == self.max_retries:
                    logger.error("Max retries reached. Failing...")
                    raise Exception(f"Text processing failed after {self.max_retries} attempts: {e}")
                sleep_time = 2 ** attempt
                logger.debug("Retrying in %d seconds...", sleep_time)
                await asyncio.sleep(sleep_time)

            except Exception as e:
                logger.exception("Unexpected error during text processing: %s", e)
                raise Exception("An unexpected error occurred during text processing.")

    async def get_available_prompts(self) -> Dict[str, str]:
        logger.debug("Retrieving available prompts for frontend")
        if not self.prompts_cache:
            await self._fetch_prompts_from_db()
        return self.prompts_cache

    async def refresh_prompts_cache(self) -> bool:
        logger.info("Refreshing prompts cache manually...")
        try:
            await self._fetch_prompts_from_db()
            logger.info("Prompts cache refreshed successfully.")
            return True
        except Exception as e:
            logger.exception("Failed to refresh prompts cache: %s", e)
            return False

    async def get_text_analysis(self, text: str) -> Dict[str, Any]:
        logger.debug("Performing text analysis...")
        word_count = len(text.split())
        char_count = len(text)
        sentence_count = len([s for s in text.split('.') if s.strip()])
        return {
            "word_count": word_count,
            "character_count": char_count,
            "sentence_count": sentence_count,
            "estimated_processing_time": max(2, word_count // 100),
        }

async def humanize_text(text: str, intensity: str):
    try:
        logger.info(f"=== STARTING HUMANIZE_TEXT ===")
        logger.info(f"Text length: {len(text)} chars, Intensity: {intensity}")

        # Preparo il JSON per n8n
        humanize_data = {
            'text': text,
            'intensity': intensity
        }

        logger.info("Sending POST request to n8n webhook...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://agentonesrl.app.n8n.cloud/webhook/humanize",
                json=humanize_data
            )

        logger.info(f"=== n8n response received - Status: {response.status_code} ===")
        logger.info(f"=== TESTO DA N8N: {response.json()} ===")

        if response.status_code >= 400:
            logger.warning(f"n8n responded with {response.status_code}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"n8n webhook failed with status {response.status_code}"
            )

        logger.info("Successfully received humanized text from n8n webhook")
        humanized_result = response.json().get("humanizedText")

        if not humanized_result:
            logger.error("n8n response missing 'humanizedText' field")
            raise HTTPException(
                status_code=500,
                detail="Invalid response from humanization service"
            )

        logger.info(f"Humanized text length: {len(humanized_result)} chars")
        return humanized_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating humanized text: {str(e)}")
        
        raise HTTPException(
            status_code=500, 
            detail="Failed to humanize text. Please try again later."
        )


# Global service instance
openai_service = OpenAIService()
