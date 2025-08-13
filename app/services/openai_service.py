import openai
import asyncio
from typing import Dict, Any, Optional
import logging
from app.core.config import settings
from app.schemas.text_schemas import TextProcessingType

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self, max_retries: int = 3, request_timeout: int = 30):
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key is required")
        
        self.prompts = self._get_prompts()
        self.max_retries = max_retries
        self.request_timeout = request_timeout

    def _get_prompts(self) -> Dict[TextProcessingType, str]:
        return {
            TextProcessingType.HUMANIZE: "...",  # mantieni il tuo testo
            TextProcessingType.IMPROVE: "...",
            TextProcessingType.SIMPLIFY: "...",
            TextProcessingType.PROFESSIONAL: "...",
            TextProcessingType.CASUAL: "..."
        }

    async def process_text(
        self, 
        text: str, 
        processing_type: TextProcessingType, 
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """Process text using OpenAI API with async-safe retries and timeout"""
        prompt = self.prompts[processing_type].format(text=text)

        # Add custom options if provided
        if options:
            if "tone" in options:
                prompt += f"\nTone: {options['tone']}"
            if "style" in options:
                prompt += f"\nStyle: {options['style']}"
            if "target_audience" in options:
                prompt += f"\nTarget audience: {options['target_audience']}"

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"OpenAI request attempt {attempt} for processing type {processing_type}")

                # Creo un nuovo client per ogni chiamata (async context manager)
                async with openai.AsyncOpenAI(api_key=settings.openai_api_key, timeout=self.request_timeout) as client:
                    response = await asyncio.wait_for(
                        client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are an expert text editor and writer. Provide only the processed text without additional explanations or meta-commentary."
                                },
                                {"role": "user", "content": prompt}
                            ],
                            max_tokens=len(text.split()) * 10,
                            temperature=0.7,
                            top_p=1.0
                        ),
                        timeout=self.request_timeout
                    )

                processed_text = response.choices[0].message.content.strip()
                logger.info(f"OpenAI call successful on attempt {attempt}. Input tokens: ~{len(text.split())}")
                return processed_text

            except (openai.RateLimitError, openai.APIError, asyncio.TimeoutError) as e:
                logger.warning(f"OpenAI request failed on attempt {attempt}: {e}")
                if attempt == self.max_retries:
                    raise Exception(f"Text processing failed after {self.max_retries} attempts: {e}")
                sleep_time = 2 ** attempt
                logger.info(f"Retrying in {sleep_time} seconds...")
                await asyncio.sleep(sleep_time)  # async-safe sleep

            except Exception as e:
                logger.error(f"Unexpected error during text processing: {e}")
                raise Exception("An unexpected error occurred during text processing.")

    async def get_text_analysis(self, text: str) -> Dict[str, Any]:
        """Get analysis of text (word count, readability, etc.)"""
        word_count = len(text.split())
        char_count = len(text)
        sentence_count = len([s for s in text.split('.') if s.strip()])
        return {
            "word_count": word_count,
            "character_count": char_count,
            "sentence_count": sentence_count,
            "estimated_processing_time": max(2, word_count // 100),
        }

# Global service instance
openai_service = OpenAIService()
