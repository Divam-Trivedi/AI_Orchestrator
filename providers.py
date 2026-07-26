import httpx
import json
import logging
import tiktoken
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# ============ Constants ============

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
OLLAMA_LOCAL_URL = "http://localhost:11434/api/chat"

# API versions - kept current
ANTHROPIC_VERSION = "2023-06-01"

MODEL_OUTPUT_LIMITS = {
    "gpt-4o": 4096,
    "gpt-4o-mini": 16384,
    "gpt-3.5-turbo": 4096,
    "claude-3-5-sonnet": 8192,
    "claude-3-opus": 8192,
    "claude-haiku-4-5": 8192,
    "deepseek-chat": 8192,
    "gemini-2.0-flash": 8192,
    "gemini-1.5-pro": 8192,
}

# Timeout settings (in seconds)
STREAM_TIMEOUT = 300  # 5 minutes for streaming
CONNECT_TIMEOUT = 10  # 10 seconds for initial connection

# ============ Exceptions ============

class ProviderError(Exception):
    """Base exception for provider errors"""
    pass

class APIError(ProviderError):
    """Raised when API returns an error"""
    pass

class StreamError(ProviderError):
    """Raised when streaming fails"""
    pass

class ConfigError(ProviderError):
    """Raised when configuration is invalid"""
    pass

# ============ Base Provider ============

class BaseProvider(ABC):
    """Abstract base class for all providers"""
    
    def __init__(self, client: httpx.AsyncClient = None):
        self.client = client
        self._own_client = False
        
        # Create client if not provided
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    timeout=STREAM_TIMEOUT,
                    connect=CONNECT_TIMEOUT
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10
                )
            )
            self._own_client = True
    
    @abstractmethod
    async def stream_chat(
        self,
        model: str,
        messages: list,
        api_key: str,
        max_tokens: int = 4096,
        system_prompt: str = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion.
        
        Args:
            model: Model name/identifier
            messages: List of message dicts with 'role' and 'content'
            api_key: API key for authentication
            max_tokens: Maximum tokens in response
            system_prompt: System prompt to guide AI behavior
        
        Yields:
            Text chunks from the model response
        
        Raises:
            APIError: When API returns an error
            StreamError: When streaming fails
            ConfigError: When configuration is invalid
        """
        pass
    
    def count_tokens(self, text: str, model: str = "gpt-3.5-turbo") -> int:
        """Count tokens using tiktoken (accurate for OpenAI/Anthropic)"""
        try:
            # Use cl100k_base encoding for GPT-4, GPT-3.5, Claude models
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = encoding.encode(text)
            return len(tokens)
        except Exception as e:
            # Fallback to character-based estimation if tiktoken fails
            logger.warning(f"Tiktoken counting failed: {e}, using fallback")
            return max(1, len(text) // 4)
    
    async def close(self):
        """Close the client connection if we own it"""
        if self._own_client and self.client:
            await self.client.aclose()
    
    def __del__(self):
        """Ensure client is closed on deletion"""
        if self._own_client and self.client:
            try:
                logger.warning(f"{self.__class__.__name__} was not properly closed")
            except Exception as e:
                logger.error(f"Error in {self.__class__.__name__}.__del__: {e}")

# ============ OpenAI Provider ============

class OpenAIProvider(BaseProvider):
    """Provider for OpenAI models (GPT-4, GPT-3.5, etc.)"""
    
    async def stream_chat(
        self,
        model: str,
        messages: list,
        api_key: str,
        max_tokens: int = 4096,
        system_prompt: str = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion from OpenAI API with optional system prompt and caching."""
        if not api_key:
            raise ConfigError("OpenAI API key is required")
        
        if not api_key.startswith("sk-"):
            logger.warning("OpenAI API key does not start with 'sk-', may be invalid")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Build messages with system prompt as first message if provided
        request_messages = messages
        if system_prompt:
            request_messages = [{"role": "user", "content": system_prompt}] + messages
        
        payload = {
            "model": model,
            "messages": request_messages,
            "stream": True,
            "top_p": 1.0,
            "frequency_penalty": 0,
            "presence_penalty": 0,
        }
        
        if "gpt-5" not in model.lower():
            payload["temperature"] = 0.7
        
        if "gpt-5" in model.lower():
            payload["max_completion_tokens"] = min(max_tokens, 8192)
        else:
            payload["max_tokens"] = min(max_tokens, 8192)
        
        # Add cache control for prompt caching (ephemeral)
        if system_prompt:
            payload["messages"][0]["cache_control"] = {"type": "ephemeral"}
        
        try:
            logger.info(f"OpenAI: Streaming {model}")
            
            async with self.client.stream(
                "POST",
                OPENAI_API_URL,
                headers=headers,
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    try:
                        error_data = json.loads(error_text)
                        error_msg = error_data.get('error', {}).get('message', error_text.decode())
                    except:
                        error_msg = error_text.decode()
                    
                    logger.error(f"OpenAI API error ({response.status_code}): {error_msg}")
                    raise APIError(f"OpenAI API error: {error_msg}")
                
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    
                    data_str = line[6:].strip()
                    
                    if data_str == "[DONE]":
                        logger.debug("OpenAI: Stream completed")
                        break
                    
                    try:
                        chunk = json.loads(data_str)
                        content = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                        if content:
                            yield content
                    except json.JSONDecodeError as e:
                        logger.warning(f"OpenAI: Invalid JSON in stream: {e}")
                        continue
                    except (KeyError, IndexError, TypeError) as e:
                        logger.warning(f"OpenAI: Unexpected response structure: {e}")
                        continue
        
        except httpx.TimeoutException as e:
            logger.error(f"OpenAI: Request timeout: {e}")
            raise StreamError(f"OpenAI request timeout: {str(e)}")
        except httpx.RequestError as e:
            logger.error(f"OpenAI: Request failed: {e}")
            raise StreamError(f"OpenAI connection error: {str(e)}")
        except APIError:
            raise
        except Exception as e:
            logger.error(f"OpenAI: Unexpected error: {e}")
            raise StreamError(f"OpenAI unexpected error: {str(e)}")

# ============ Anthropic Provider ============

class AnthropicProvider(BaseProvider):
    """Provider for Anthropic Claude models"""
    
    async def stream_chat(
        self,
        model: str,
        messages: list,
        api_key: str,
        max_tokens: int = 4096,
        system_prompt: str = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion from Anthropic API with optional system prompt and caching."""
        if not api_key:
            raise ConfigError("Anthropic API key is required")
        
        headers = {
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": min(max_tokens, 8192),
            "temperature": 1.0,
        }
        
        # Add system prompt with cache control if provided
        if system_prompt:
            payload["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
        
        try:
            logger.info(f"Anthropic: Streaming {model} (API version: {ANTHROPIC_VERSION})")
            
            async with self.client.stream(
                "POST",
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    try:
                        error_data = json.loads(error_text)
                        error_msg = error_data.get('error', {}).get('message', error_text.decode())
                    except:
                        error_msg = error_text.decode()
                    
                    logger.error(f"Anthropic API error ({response.status_code}): {error_msg}")
                    raise APIError(f"Anthropic API error: {error_msg}")
                
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    
                    try:
                        chunk = json.loads(line[6:])
                        
                        if chunk.get('type') == 'content_block_delta':
                            text_delta = chunk.get('delta', {}).get('text', '')
                            if text_delta:
                                yield text_delta
                        
                        elif chunk.get('type') == 'message_stop':
                            logger.debug("Anthropic: Stream completed")
                            break
                    
                    except json.JSONDecodeError as e:
                        logger.warning(f"Anthropic: Invalid JSON in stream: {e}")
                        continue
                    except (KeyError, TypeError) as e:
                        logger.warning(f"Anthropic: Unexpected response structure: {e}")
                        continue
        
        except httpx.TimeoutException as e:
            logger.error(f"Anthropic: Request timeout: {e}")
            raise StreamError(f"Anthropic request timeout: {str(e)}")
        except httpx.RequestError as e:
            logger.error(f"Anthropic: Request failed: {e}")
            raise StreamError(f"Anthropic connection error: {str(e)}")
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Anthropic: Unexpected error: {e}")
            raise StreamError(f"Anthropic unexpected error: {str(e)}")

# ============ Ollama Provider ============

class OllamaProvider(BaseProvider):
    """Provider for local Ollama models"""
    
    async def stream_chat(
        self,
        model: str,
        messages: list,
        api_key: str = None,
        max_tokens: int = 4096,
        system_prompt: str = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion from local Ollama instance."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }
        
        try:
            logger.info(f"Ollama: Streaming {model} from {OLLAMA_LOCAL_URL}")
            
            async with self.client.stream(
                "POST",
                OLLAMA_LOCAL_URL,
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    try:
                        error_data = json.loads(error_text)
                        error_msg = error_data.get('error', error_text.decode())
                    except:
                        error_msg = error_text.decode()
                    
                    logger.error(f"Ollama error ({response.status_code}): {error_msg}")
                    raise APIError(f"Ollama error: {error_msg}")
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    try:
                        chunk = json.loads(line)
                        content = chunk.get('message', {}).get('content', '')
                        if content:
                            yield content
                        
                        if chunk.get('done'):
                            logger.debug("Ollama: Stream completed")
                            break
                    
                    except json.JSONDecodeError as e:
                        logger.warning(f"Ollama: Invalid JSON in stream: {e}")
                        continue
                    except (KeyError, TypeError) as e:
                        logger.warning(f"Ollama: Unexpected response structure: {e}")
                        continue
        
        except httpx.TimeoutException as e:
            logger.error(f"Ollama: Request timeout: {e}")
            raise StreamError(f"Ollama request timeout. Is Ollama running on {OLLAMA_LOCAL_URL}?")
        except httpx.ConnectError as e:
            logger.error(f"Ollama: Connection failed: {e}")
            raise StreamError(f"Cannot connect to Ollama on {OLLAMA_LOCAL_URL}. Is it running?")
        except httpx.RequestError as e:
            logger.error(f"Ollama: Request failed: {e}")
            raise StreamError(f"Ollama connection error: {str(e)}")
        except APIError:
            raise
        except Exception as e:
            logger.error(f"Ollama: Unexpected error: {e}")
            raise StreamError(f"Ollama unexpected error: {str(e)}")


class DeepSeekProvider(BaseProvider):
    """DeepSeek API Provider"""
    
    async def stream_chat(
        self,
        model: str,
        messages: list,
        api_key: str,
        max_tokens: int = 4096,
        system_prompt: str = None
    ) -> AsyncGenerator[str, None]:
        try:
            formatted_messages = messages
            if system_prompt:
                formatted_messages = [
                    {"role": "system", "content": system_prompt},
                    *messages
                ]
            
            payload = {
                "model": model,
                "messages": formatted_messages,
                "max_tokens": min(max_tokens, 8192),
                "stream": True
            }
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            async with self.client.stream(
                "POST",
                "https://api.deepseek.com/chat/completions",
                json=payload,
                headers=headers,
                timeout=30.0
            ) as response:
                if response.status_code != 200:
                    error_text = await response.atext()
                    logger.error(f"DeepSeek API error: {response.status_code} - {error_text}")
                    raise APIError(f"DeepSeek API error: {response.status_code}")
                
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    content = delta["content"]
                                    if content:
                                        yield content
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"DeepSeek streaming error: {e}")
            raise StreamError(f"DeepSeek streaming failed: {e}")
    
    def count_tokens(self, text: str, model: str) -> int:
        return len(text) // 4


class GeminiProvider(BaseProvider):
    """Google Gemini API Provider"""
    
    async def stream_chat(
        self,
        model: str,
        messages: list,
        api_key: str,
        max_tokens: int = 4096,
        system_prompt: str = None
    ) -> AsyncGenerator[str, None]:
        try:
            system_instruction = system_prompt or "You are a helpful assistant."
            
            contents = []
            for msg in messages:
                contents.append({
                    "role": "user" if msg["role"] == "user" else "model",
                    "parts": [{"text": msg["content"]}]
                })
            
            payload = {
                "contents": contents,
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "generationConfig": {
                    "maxOutputTokens": min(max_tokens, 8192),
                    "temperature": 0.7
                },
                "safetySettings": [
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "threshold": "BLOCK_NONE"
                    }
                ]
            }
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
            
            async with self.client.stream(
                "POST",
                url,
                json=payload,
                timeout=30.0
            ) as response:
                if response.status_code != 200:
                    error_text = await response.atext()
                    logger.error(f"Gemini API error: {response.status_code} - {error_text}")
                    raise APIError(f"Gemini API error: {response.status_code}")
                
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                            if "candidates" in data and len(data["candidates"]) > 0:
                                candidate = data["candidates"][0]
                                if "content" in candidate and "parts" in candidate["content"]:
                                    for part in candidate["content"]["parts"]:
                                        if "text" in part:
                                            yield part["text"]
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            raise StreamError(f"Gemini streaming failed: {e}")
    
    def count_tokens(self, text: str, model: str) -> int:
        return len(text) // 4

# ============ Provider Pool (Connection Pooling) ============

def format_message_with_images(message: dict, provider: str) -> dict:
    """Format message content with images for specific provider"""
    if 'images' not in message or not message['images']:
        return message
    
    images = message['images']
    text = message.get('content', '')
    
    if provider == 'OpenAI':
        # OpenAI uses content array
        content = [{"type": "text", "text": text}]
        for img_base64 in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": img_base64}
            })
        return {**message, 'content': content}
    
    elif provider == 'Anthropic':
        # Anthropic uses image blocks in content
        content = [{"type": "text", "text": text}]
        for img_base64 in images:
            media_type = "image/jpeg"
            if "data:image/png" in img_base64:
                media_type = "image/png"
            elif "data:image/gif" in img_base64:
                media_type = "image/gif"
            elif "data:image/webp" in img_base64:
                media_type = "image/webp"
            
            # Extract base64 data
            if "," in img_base64:
                img_data = img_base64.split(",")[1]
            else:
                img_data = img_base64
            
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": img_data
                }
            })
        return {**message, 'content': content}
    
    elif provider == 'Ollama':
        # Ollama uses images array
        formatted = {**message, 'content': text}
        if images:
            formatted['images'] = [img.split(",")[1] if "," in img else img for img in images]
        return formatted
    
    return message

class ProviderPool:
    """Singleton pool for provider instances with connection pooling."""
    
    _instance = None
    _providers = {}
    _shared_client = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=STREAM_TIMEOUT,
                connect=CONNECT_TIMEOUT
            ),
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20
            )
        )
        
        self._providers = {
            "OpenAI": OpenAIProvider(self._shared_client),
            "Anthropic": AnthropicProvider(self._shared_client),
            "Ollama": OllamaProvider(self._shared_client),
            "DeepSeek": DeepSeekProvider(self._shared_client),
            "Gemini": GeminiProvider(self._shared_client),
        }
        
        self._initialized = True
        logger.info("ProviderPool initialized with connection pooling")
    
    def get(self, provider_name: str) -> BaseProvider:
        """Get a provider instance by name."""
        if provider_name not in self._providers:
            raise ConfigError(f"Unknown provider: {provider_name}. Must be one of: {list(self._providers.keys())}")
        
        return self._providers[provider_name]
    
    def shutdown(self):
        """Shutdown all providers and close connections"""
        try:
            if self._shared_client:
                logger.info("Shared client should be closed (requires async context)")
            logger.info("ProviderPool shutdown complete")
        except Exception as e:
            logger.error(f"Error during ProviderPool shutdown: {e}")

# ============ Factory Function ============

def get_provider(provider_name: str) -> BaseProvider:
    """Get a provider instance from the pool."""
    pool = ProviderPool()
    return pool.get(provider_name)