"""LLM (Large Language Model) service."""
import os
from typing import Dict, Any, Optional
import structlog
from openai import OpenAI

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class LLMService:
    """Service for LLM text generation."""
    
    def __init__(self):
        """Initialize LLM service."""
        self.mode = settings.llm_mode
        self.client = None
        
        # Initialize based on mode
        if self.mode == "cloud" or (self.mode == "auto" and settings.openai_api_key):
            self._init_openai()
        elif self.mode == "local" or self.mode == "auto":
            self._init_local()
        else:
            logger.warning("No LLM backend available")
    
    def _init_openai(self):
        """Initialize OpenAI client."""
        if settings.openai_api_key:
            self.client = OpenAI(api_key=settings.openai_api_key)
            self.model = settings.openai_model
            logger.info(f"Initialized OpenAI with model: {self.model}")
        else:
            logger.warning("OpenAI API key not configured")
    
    def _init_local(self):
        """Initialize local LLM."""
        try:
            # For now, use OpenAI-compatible API with local server
            # You can run local models with tools like:
            # - Ollama (ollama serve)
            # - llama.cpp server
            # - vLLM
            # - text-generation-webui
            
            # Example for Ollama (default port 11434)
            self.client = OpenAI(
                base_url="http://localhost:11434/v1",
                api_key="not-needed"  # Ollama doesn't need API key
            )
            self.model = "llama2"  # or any model you have in Ollama
            logger.info(f"Initialized local LLM: {self.model}")
        except Exception as e:
            logger.warning(f"Failed to initialize local LLM: {e}")
            self.client = None
    
    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 512,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate text using LLM.
        
        Args:
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            
        Returns:
            Generated text and metadata
        """
        if not self.client:
            # Fallback response when no LLM is available
            return self._fallback_response(prompt)
        
        try:
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": prompt})
            
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # Extract response
            generated_text = response.choices[0].message.content
            
            # Format response
            result = {
                "text": generated_text,
                "model": self.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                }
            }
            
            logger.info(
                "LLM generation completed",
                model=self.model,
                tokens=result["usage"]["total_tokens"]
            )
            
            return result
            
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            # Return fallback response
            return self._fallback_response(prompt)
    
    def _fallback_response(self, prompt: str) -> Dict[str, Any]:
        """Generate a fallback response when LLM is not available.
        
        Args:
            prompt: User prompt
            
        Returns:
            Fallback response
        """
        # Extract context and question from RAG prompt
        if "Context:" in prompt and "Question:" in prompt:
            # This is a RAG query
            context_start = prompt.find("Context:") + len("Context:")
            question_start = prompt.find("Question:")
            context = prompt[context_start:question_start].strip()
            
            # Simple extractive approach: return first few sentences from context
            sentences = context.split(". ")[:3]
            response_text = ". ".join(sentences) + "."
            
            if "[Source" in response_text:
                response_text = (
                    "Based on the provided documents:\n\n" + 
                    response_text + 
                    "\n\n(Note: This is a simplified response. Configure an LLM for better answers.)"
                )
        else:
            # Generic response
            response_text = (
                "I understand you're asking about this topic. "
                "However, I need an LLM service configured to provide detailed answers. "
                "Please configure OpenAI API or a local LLM server."
            )
        
        return {
            "text": response_text,
            "model": "fallback",
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
    
    def is_available(self) -> bool:
        """Check if LLM service is available.
        
        Returns:
            True if LLM is available
        """
        return self.client is not None
    
    def get_info(self) -> Dict[str, Any]:
        """Get LLM service information.
        
        Returns:
            Service information
        """
        return {
            "available": self.is_available(),
            "mode": self.mode,
            "model": self.model if hasattr(self, "model") else None,
            "backend": "OpenAI" if isinstance(self.client, OpenAI) else "Local"
        }
