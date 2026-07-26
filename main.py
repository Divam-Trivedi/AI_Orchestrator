import os
import os
import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, validator
from typing import List, Optional, Optional
from providers import get_provider, ProviderPool
import database as db
import uuid
import json
import logging
import asyncio
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="AI Orchestrator")
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS configuration - restrict to specific origins
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,  # Changed from True for security
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],  # Specific methods only
    allow_headers=["Content-Type"],  # Specific headers only
)

# Initialize database
db.init_db()

# Initialize provider pool
provider_pool = ProviderPool()

# ============ Pydantic Models ============

class Message(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=100000)
    images: Optional[List[str]] = None  # Base64 encoded images
    search_results: Optional[List[dict]] = None  # Web search results
    
    @validator('content')
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Content cannot be empty or whitespace only')
        return v.strip()

class ChatRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=200)
    messages: List[Message] = Field(..., min_items=1, max_items=100)
    conversation_id: Optional[str] = None
    context_mode: str = Field(default="all", pattern="^(all|last_n|first_m_last_n)$")
    context_param_m: int = Field(default=0, ge=0, le=50)
    context_param_n: int = Field(default=10, ge=1, le=50)
    system_prompt: Optional[str] = None
    enable_web_search: bool = Field(default=False)
    
    @validator('messages')
    def validate_messages(cls, v):
        if not v:
            raise ValueError('At least one message is required')
        # Ensure last message is from user
        if v[-1].role != 'user':
            raise ValueError('Last message must be from user')
        return v

class SettingRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., max_length=1000000)

class ProviderConfig(BaseModel):
    provider: str = Field(..., pattern="^(OpenAI|Anthropic|Ollama|DeepSeek|Gemini)$")
    api_key: str = Field(default="", min_length=0)
    models: List[str] = Field(..., min_items=1)
    max_tokens: int = Field(default=4096, ge=256, le=128000)
    
    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v, info):
        """Validate API key based on provider"""
        provider = info.data.get('provider')
        if provider in ['OpenAI', 'Anthropic', 'DeepSeek', 'Gemini'] and not v:
            raise ValueError(f"{provider} requires an API key")
        return v

# ============ Request/Response Models ============

class ChatResponse(BaseModel):
    conversation_id: str
    content: str

class ConversationInfo(BaseModel):
    id: str
    name: str
    created_at: str
    message_count: int = 0

# ============ Endpoints ============

@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serve the main HTML interface"""
    try:
        with open("static/index.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.error("static/index.html not found")
        raise HTTPException(status_code=500, detail="UI file not found")
    except Exception as e:
        logger.error(f"Error reading static/index.html: {e}")
        raise HTTPException(status_code=500, detail="Error loading UI")

@app.post("/settings")
async def save_setting(req: SettingRequest):
    """Save a setting key-value pair"""
    try:
        # Validate provider_configs if it's being set
        if req.key == "provider_configs":
            try:
                configs = json.loads(req.value)
                # Validate each provider config
                for cfg in configs:
                    ProviderConfig(**cfg)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON in provider_configs")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid provider configuration: {str(e)}")
        
        db.set_setting(req.key, req.value)
        logger.info(f"Setting saved: {req.key}")
        return {"status": "success", "key": req.key}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving setting: {e}")
        raise HTTPException(status_code=500, detail="Error saving setting")

@app.get("/settings/{key}")
async def get_setting(key: str):
    """Retrieve a setting by key"""
    try:
        val = db.get_setting(key)
        if val is None:
            return {"value": None}
        return {"value": val}
    except Exception as e:
        logger.error(f"Error retrieving setting {key}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving setting")

# ============ Default System Prompts ============

DEFAULT_PROMPTS = {
    "Programmer": """You are an expert software developer. Provide:
1. Clean, well-commented code
2. Explanation of the approach
3. Edge cases and error handling
4. Performance considerations
Use best practices and modern syntax.""",
    
    "Resume Maker": """You are a professional resume writer and career coach. Help users:
1. Structure their resume effectively
2. Use strong action verbs and metrics
3. Tailor content to job descriptions
4. Improve clarity and impact
Focus on making them stand out to recruiters.""",
    
    "Lawyer": """You are a knowledgeable legal advisor. When discussing legal matters:
1. Explain concepts in understandable terms
2. Discuss relevant laws and precedents
3. Identify potential issues and risks
4. Suggest practical approaches
Note: This is general information, not legal advice. Consult a licensed attorney.""",
    
    "Teacher": """You are an excellent educator. When teaching:
1. Explain concepts clearly and progressively
2. Use analogies and real-world examples
3. Ask clarifying questions to check understanding
4. Provide practice problems and feedback
5. Adapt to different learning levels
Make complex topics accessible.""",
}

def initialize_default_prompts():
    """Initialize default system prompts on startup"""
    try:
        for name, content in DEFAULT_PROMPTS.items():
            try:
                existing = db.get_system_prompt(name)
                if not existing:
                    db.create_system_prompt(name, name, content, is_custom=0)
            except Exception as e:
                logger.warning(f"Default prompt '{name}' initialization: {e}")
    except Exception as e:
        logger.error(f"Error initializing default prompts: {e}")

@app.get("/system-prompts")
async def list_system_prompts():
    """List all available system prompts"""
    try:
        prompts = db.get_all_system_prompts()
        return prompts
    except Exception as e:
        logger.error(f"Error listing system prompts: {e}")
        raise HTTPException(status_code=500, detail="Error listing system prompts")

@app.get("/system-prompts/{name}")
async def get_system_prompt(name: str):
    """Get a specific system prompt"""
    try:
        prompt = db.get_system_prompt(name)
        if not prompt:
            raise HTTPException(status_code=404, detail="System prompt not found")
        return prompt
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving system prompt: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving system prompt")

@app.post("/system-prompts")
async def create_system_prompt(name: str, category: str, content: str):
    """Create a new custom system prompt"""
    try:
        db.create_system_prompt(name, category, content, is_custom=1)
        return {"status": "created", "name": name}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail=f"System prompt '{name}' already exists")
    except Exception as e:
        logger.error(f"Error creating system prompt: {e}")
        raise HTTPException(status_code=500, detail="Error creating system prompt")

@app.put("/system-prompts/{name}")
async def update_system_prompt(name: str, content: str):
    """Update a system prompt"""
    try:
        db.update_system_prompt(name, content)
        return {"status": "updated", "name": name}
    except Exception as e:
        logger.error(f"Error updating system prompt: {e}")
        raise HTTPException(status_code=500, detail="Error updating system prompt")

@app.post("/system-prompts/{name}/reset")
async def reset_system_prompt(name: str):
    """Reset a preset system prompt to default"""
    try:
        if name not in DEFAULT_PROMPTS:
            raise HTTPException(status_code=400, detail="Only preset prompts can be reset")
        db.reset_system_prompt(name, DEFAULT_PROMPTS[name])
        return {"status": "reset", "name": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting system prompt: {e}")
        raise HTTPException(status_code=500, detail="Error resetting system prompt")

@app.delete("/system-prompts/{name}")
async def delete_system_prompt(name: str):
    """Delete a custom system prompt"""
    try:
        db.delete_system_prompt(name)
        return {"status": "deleted", "name": name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting system prompt: {e}")
        raise HTTPException(status_code=500, detail="Error deleting system prompt")

@app.get("/models")
async def list_models():
    """List all available models from configured providers"""
    try:
        config_str = db.get_setting("provider_configs")
        if not config_str:
            return []
        
        configs = json.loads(config_str)
        all_models = []
        
        for p in configs:
            try:
                ProviderConfig(**p)  # Validate config
                for m in p.get('models', []):
                    all_models.append({
                        "model": m,
                        "provider": p['provider']
                    })
            except Exception as e:
                logger.warning(f"Skipping invalid provider config: {e}")
                continue
        
        return all_models
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail="Error listing models")

@app.get("/conversations")
async def list_conversations():
    """List all conversations"""
    try:
        conversations = db.get_all_conversations()
        # Add message count to each conversation
        for conv in conversations:
            try:
                message_count = db.get_message_count(conv['id'])
                conv['message_count'] = message_count
            except Exception as e:
                logger.warning(f"Error getting message count for {conv['id']}: {e}")
                conv['message_count'] = 0
        return conversations
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail="Error listing conversations")

@app.get("/groups")
async def list_groups():
    """List all groups"""
    try:
        groups = db.get_all_groups()
        return {"groups": groups}
    except Exception as e:
        logger.error(f"Error listing groups: {e}")
        raise HTTPException(status_code=500, detail="Error listing groups")

@app.post("/groups")
async def create_group(name: str):
    """Create a new group"""
    try:
        if not name or not name.strip():
            raise HTTPException(status_code=400, detail="Group name cannot be empty")
        
        db.create_group(name.strip())
        return {"status": "created", "name": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating group: {e}")
        raise HTTPException(status_code=500, detail="Error creating group")

@app.put("/groups/{old_name}")
async def rename_group(old_name: str, new_name: str):
    """Rename a group"""
    try:
        if not new_name or not new_name.strip():
            raise HTTPException(status_code=400, detail="Group name cannot be empty")
        
        db.rename_group(old_name, new_name.strip())
        return {"status": "renamed", "old_name": old_name, "new_name": new_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming group: {e}")
        raise HTTPException(status_code=500, detail="Error renaming group")

@app.delete("/groups/{group_name}")
async def delete_group(group_name: str, action: str = "delete"):
    """Delete a group. action: 'delete' (delete chats) or 'move' (move chats outside)"""
    try:
        if action == "move":
            count = db.move_group_chats_outside(group_name)
            return {"status": "moved", "chats_moved": count}
        else:
            count = db.delete_group(group_name)
            return {"status": "deleted", "chats_deleted": count}
    except Exception as e:
        logger.error(f"Error deleting group: {e}")
        raise HTTPException(status_code=500, detail="Error deleting group")

@app.post("/conversations/{conversation_id}/move-to-group")
async def move_conversation_to_group(conversation_id: str, group_name: str = None):
    """Move conversation to a group or outside groups"""
    try:
        db.move_conversation_to_group(conversation_id, group_name)
        return {"status": "moved", "conversation_id": conversation_id, "group": group_name}
    except Exception as e:
        logger.error(f"Error moving conversation: {e}")
        raise HTTPException(status_code=500, detail="Error moving conversation")

@app.get("/history/{conversation_id}")
async def get_history(conversation_id: str):
    """Get message history for a conversation"""
    try:
        # Validate conversation exists
        if not db.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        messages = db.get_messages(conversation_id)
        return messages
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving history for {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving conversation history")

@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Send a message and get a streaming response.
    Returns the conversation ID and streams the response content.
    """
    conv_id = request.conversation_id
    
    try:
        # Get provider configurations
        config_str = db.get_setting("provider_configs")
        if not config_str:
            raise HTTPException(status_code=400, detail="No providers configured. Please configure providers in settings.")
        
        try:
            configs = json.loads(config_str)
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Invalid provider configuration")
        
        # Find the config for the requested model
        current_config = next(
            (p for p in configs if request.model in p.get('models', [])),
            None
        )
        
        if not current_config:
            logger.warning(f"Model {request.model} not found in configurations")
            raise HTTPException(
                status_code=404,
                detail=f"Model '{request.model}' not configured. Please add it in settings."
            )
        
        # Validate API key (Ollama doesn't need one)
        api_key = current_config.get('api_key', '').strip()
        provider_name = current_config['provider']
        
        if not api_key and provider_name not in ['Ollama', 'DeepSeek', 'Gemini']:
            logger.error(f"Missing API key for provider {provider_name}")
            raise HTTPException(
                status_code=400,
                detail=f"Missing API key for {provider_name}. Please configure in settings."
            )
        
        # Create new conversation if needed
        if not conv_id:
            conv_id = str(uuid.uuid4())
            # Create conversation name from first user message
            first_message = next(m.content for m in request.messages if m.role == 'user')
            title = _generate_conversation_title(first_message)
            
            try:
                db.create_conversation(conv_id, title)
                logger.info(f"Created conversation {conv_id}")
            except Exception as e:
                logger.error(f"Error creating conversation: {e}")
                raise HTTPException(status_code=500, detail="Error creating conversation")
        else:
            # Verify conversation exists
            if not db.conversation_exists(conv_id):
                logger.warning(f"Conversation {conv_id} does not exist")
                raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Save user message
        user_msg = request.messages[-1]
        try:
            db.save_message(conv_id, user_msg.role, user_msg.content, request.model)
        except Exception as e:
            logger.error(f"Error saving user message: {e}")
            raise HTTPException(status_code=500, detail="Error saving message")
        
        # Handle web search if enabled
        search_context = ""
        if request.enable_web_search:
            last_user_message = next(
                (m for m in reversed(request.messages) if m.role == 'user'),
                None
            )
            if last_user_message:
                try:
                    search_results = await web_search(last_user_message.content, num_results=3)
                    if search_results['results']:
                        search_context = "\n\n[Web Search Results]\n"
                        for i, result in enumerate(search_results['results'], 1):
                            search_context += f"{i}. {result['title']}\n   {result['snippet']}\n"
                        logger.info(f"Web search injected {len(search_results['results'])} results")
                except Exception as e:
                    logger.warning(f"Web search failed: {e}")
        
        # Vision-capable models
        vision_models = {'gpt-4o', 'gpt-4o-mini', 'claude-3-5-sonnet', 'claude-opus', 'llava'}
        has_vision = any(vm in request.model.lower() for vm in vision_models)
        
        # Prepare formatted messages
        formatted_messages = []
        for m in request.messages:
            msg_dict = {"role": m.role, "content": m.content}
            
            # Handle images
            if hasattr(m, 'images') and m.images and has_vision:
                from providers import format_message_with_images
                msg_dict = format_message_with_images(msg_dict, provider_name)
            elif hasattr(m, 'images') and m.images:
                logger.warning(f"Model {request.model} doesn't support images. Ignoring.")
            
            # Append web search results to last user message
            if m.role == 'user' and search_context and m == request.messages[-1]:
                if isinstance(msg_dict['content'], str):
                    msg_dict['content'] = msg_dict['content'] + search_context
            
            formatted_messages.append(msg_dict)
        
        # Apply context window limit
        if request.context_mode == "last_n":
            formatted_messages = formatted_messages[-request.context_param_n:]
            logger.info(f"Context mode: last_n ({request.context_param_n} messages). Sending {len(formatted_messages)} messages to AI")
        elif request.context_mode == "first_m_last_n":
            if len(formatted_messages) > (request.context_param_m + request.context_param_n):
                formatted_messages = (
                    formatted_messages[:request.context_param_m] +
                    formatted_messages[-request.context_param_n:]
                )
            logger.info(f"Context mode: first_m_last_n (M={request.context_param_m}, N={request.context_param_n}). Sending {len(formatted_messages)} messages to AI")
        else:
            logger.info(f"Context mode: all. Sending {len(formatted_messages)} messages to AI")
        
        # Get provider instance (pooled/reused)
        try:
            provider_obj = provider_pool.get(provider_name)
        except Exception as e:
            logger.error(f"Error initializing provider {provider_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Error initializing provider {provider_name}")
        
        # Stream response
        async def event_generator():
            full_response = ""
            error_occurred = False
            
            try:
                max_tokens = current_config.get('max_tokens', 4096)
                
                from providers import MODEL_OUTPUT_LIMITS
                model_limit = MODEL_OUTPUT_LIMITS.get(request.model, 8192)
                max_tokens = min(max_tokens, model_limit)
                
                async for chunk in provider_obj.stream_chat(
                    request.model,
                    formatted_messages,
                    api_key,
                    max_tokens,
                    system_prompt=request.system_prompt
                ):
                    if chunk:
                        full_response += chunk
                        yield chunk
                
                # Calculate tokens and save
                input_tokens = sum(provider_obj.count_tokens(m["content"], request.model) for m in formatted_messages)
                output_tokens = provider_obj.count_tokens(full_response, request.model)
                total_tokens = input_tokens + output_tokens
                
                try:
                    db.save_message(conv_id, "assistant", full_response, request.model)
                    db.update_token_count(conv_id, request.model, total_tokens)
                    logger.info(f"Saved assistant response for conversation {conv_id} - {total_tokens} tokens")
                except Exception as e:
                    logger.error(f"Error saving assistant response: {e}")
            
            except Exception as e:
                error_occurred = True
                error_msg = str(e)
                logger.error(f"Error during streaming from {provider_name}: {error_msg}")
                yield f"\n\n[ERROR] Failed to get response from {provider_name}: {error_msg}"
                
                if full_response:
                    try:
                        error_response = f"{full_response}\n\n[Incomplete due to error: {error_msg}]"
                        db.save_message(conv_id, "assistant", error_response, request.model)
                    except Exception as db_error:
                        logger.error(f"Error saving error response: {db_error}")
        
        return StreamingResponse(
            event_generator(),
            media_type="text/plain",
            headers={
                "X-Conversation-ID": conv_id,
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.put("/conversations/{conversation_id}/name")
async def update_conversation_name(conversation_id: str, name: str):
    """Update conversation name"""
    try:
        if not db.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        db.update_conversation_name(conversation_id, name)
        logger.info(f"Updated conversation name: {conversation_id}")
        return {"status": "updated", "name": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating conversation name: {e}")
        raise HTTPException(status_code=500, detail="Error updating conversation name")

@app.post("/admin/cleanup-orphaned")
async def cleanup_orphaned():
    """Clean up orphaned messages (manual trigger)"""
    try:
        deleted = db.cleanup_orphaned_messages()
        return {"status": "cleaned", "deleted_messages": deleted}
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise HTTPException(status_code=500, detail="Cleanup failed")

@app.post("/search")
async def web_search(query: str, num_results: int = 5):
    try:
        from ddgs import DDGS
        
        results = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=num_results):
                    results.append({
                        "title": r.get('title', ''),
                        "url": r.get('href', ''),
                        "snippet": r.get('body', '')
                    })
        except Exception as search_error:
            logger.warning(f"DuckDuckGo search error: {search_error}")
            # Return empty results instead of crashing
            results = []
        
        logger.info(f"Web search completed for: {query} ({len(results)} results)")
        return {"query": query, "results": results}
    except Exception as e:
        logger.error(f"Error performing web search: {e}")
        raise HTTPException(status_code=500, detail="Web search failed")


@app.get("/admin/stats")
async def get_system_stats():
    """Get system resource usage stats"""
    try:
        import psutil
        db_size = db.get_database_size()
        
        return {
            "database": db_size,
            "memory_percent": psutil.virtual_memory().percent,
            "cpu_percent": psutil.cpu_percent(interval=1),
            "disk_percent": psutil.disk_usage('/').percent
        }
    except ImportError:
        # psutil not installed, return basic stats
        db_size = db.get_database_size()
        return {"database": db_size, "note": "Install psutil for detailed stats"}
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {"error": str(e)}

@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a specific conversation"""
    try:
        if not db.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        db.delete_conversation(conversation_id)
        logger.info(f"Deleted conversation: {conversation_id}")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(status_code=500, detail="Error deleting conversation")

@app.post("/settings/auto-cleanup")
async def set_auto_cleanup(enabled: bool = True, days: int = 30):
    """Enable auto-cleanup of old conversations"""
    try:
        db.save_setting("auto_cleanup_enabled", str(enabled))
        db.save_setting("auto_cleanup_days", str(days))
        return {"status": "configured", "enabled": enabled, "days": days}
    except Exception as e:
        logger.error(f"Error configuring auto-cleanup: {e}")
        raise HTTPException(status_code=500, detail="Error configuring auto-cleanup")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages"""
    try:
        # Validate conversation exists
        if not db.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        db.delete_conversation(conversation_id)
        logger.info(f"Deleted conversation {conversation_id}")
        return Response(status_code=204)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Error deleting conversation")

# ============ Helper Functions ============

def _generate_conversation_title(first_message: str) -> str:
    """
    Generate a conversation title from the first user message.
    Takes first line, truncates to 50 chars, removes special chars.
    """
    try:
        # Get first line
        title = first_message.split('\n')[0].strip()
        
        # Truncate to 50 characters
        if len(title) > 50:
            title = title[:47] + "..."
        
        # Remove leading/trailing whitespace
        title = title.strip()
        
        # Fallback if empty
        if not title:
            title = "New Conversation"
        
        return title
    except Exception as e:
        logger.warning(f"Error generating conversation title: {e}")
        return "New Conversation"

# ============ Startup/Shutdown ============

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("AI Orchestrator starting up")
    logger.info(f"Allowed origins: {ALLOWED_ORIGINS}")
    initialize_default_prompts()
    
    # Start background cleanup task
    asyncio.create_task(background_cleanup_task())

async def background_cleanup_task():
    """Run cleanup every 6 hours - remove orphaned messages only"""
    while True:
        try:
            # Sleep for 6 hours
            await asyncio.sleep(6 * 60 * 60)
            
            logger.info("Running scheduled orphaned message cleanup...")
            db.cleanup_orphaned_messages()
            logger.info("Orphaned message cleanup complete")
        except Exception as e:
            logger.error(f"Error in background cleanup: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("AI Orchestrator shutting down")
    provider_pool.shutdown()

# ============ Health Check ============

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db.get_setting("health_check")
        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.get("/conversations/{conversation_id}/tokens")
async def get_conversation_tokens(conversation_id: str):
    """Retrieve token breakdown for a specific conversation"""
    try:
        # Verify conversation exists
        if not db.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conv = db.get_conversation(conversation_id)
        # tokens_used is already parsed into a dict by db.get_conversation
        return {
            "conversation_id": conversation_id,
            "tokens_used": conv.get("tokens_used", {}) 
        }
    except Exception as e:
        logger.error(f"Error retrieving tokens for {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving token data")

# ============ Run Application ============

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)