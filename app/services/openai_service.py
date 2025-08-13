import openai
from typing import Dict, Any
import logging
from app.core.config import settings
from app.schemas.text_schemas import TextProcessingType

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key is required")
        
        self.client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self.prompts = self._get_prompts()
    
    def _get_prompts(self) -> Dict[TextProcessingType, str]:
        return {
            TextProcessingType.HUMANIZE: """
                Transform the following text to make it sound more human, natural, and engaging while preserving the original meaning and key information. 
                Make it conversational and relatable without losing professionalism where appropriate.
                
                Text to humanize: {text}
            """,
            TextProcessingType.IMPROVE: """
                Improve the following text by enhancing clarity, flow, grammar, and overall readability. 
                Maintain the original tone and meaning while making it more polished and professional.
                
                Text to improve: {text}
            """,
            TextProcessingType.SIMPLIFY: """
                Simplify the following text to make it easier to understand for a general audience. 
                Use simpler vocabulary and shorter sentences while retaining all important information.
                
                Text to simplify: {text}
            """,
            TextProcessingType.PROFESSIONAL: """
                Transform the following text to sound more professional and formal while maintaining clarity and engagement. 
                Use appropriate business language and structure.
                
                Text to make professional: {text}
            """,
            TextProcessingType.CASUAL: """
                Transform the following text to sound more casual and friendly while preserving the core message. 
                Make it conversational and approachable.
                
                Text to make casual: {text}
            """
        }
    
    async def process_text(
        self, 
        text: str, 
        processing_type: TextProcessingType, 
        options: Dict[str, Any] = None
    ) -> str:
        """Process text using OpenAI API"""
        try:
            prompt = self.prompts[processing_type].format(text=text)
            
            # Add custom options to the prompt if provided
            if options:
                if "tone" in options:
                    prompt += f"\nTone: {options['tone']}"
                if "style" in options:
                    prompt += f"\nStyle: {options['style']}"
                if "target_audience" in options:
                    prompt += f"\nTarget audience: {options['target_audience']}"
            
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",  # Use gpt-4 for better results if budget allows
                messages=[
                    {
                        "role": "system", 
                        "content": "You are an expert text editor and writer. Provide only the processed text without additional explanations or meta-commentary."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                max_tokens=len(text.split()) * 2,  # Roughly double the input length
                temperature=0.7,  # Some creativity but not too much
                top_p=1.0,
            )
            
            processed_text = response.choices[0].message.content.strip()
            
            # Log usage for monitoring
            logger.info(f"OpenAI API call successful. Input tokens: ~{len(text.split())}, Processing type: {processing_type}")
            
            return processed_text
            
        except openai.RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {e}")
            raise Exception("API rate limit exceeded. Please try again later.")
        
        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise Exception(f"Text processing failed: {str(e)}")
        
        except Exception as e:
            logger.error(f"Unexpected error in text processing: {e}")
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
            "estimated_processing_time": max(2, word_count // 100),  # Rough estimate
        }

# Global service instance
openai_service = OpenAIService()