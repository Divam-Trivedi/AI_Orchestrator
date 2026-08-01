import sqlite3
import logging
import json
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
import os

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.expanduser("~"), "ai_orchestrator_history.db")
DB_TIMEOUT = 10  # 10 seconds timeout for database locks

def set_db_path(path):
    global DB_PATH
    DB_PATH = path
    logger.info(f"Database path set to: {DB_PATH}")
    
# ============ Connection Management ============

@contextmanager
def get_db_connection():
    """
    Context manager for database connections.
    Ensures proper cleanup and timeout handling.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
    except sqlite3.OperationalError as e:
        logger.error(f"Database operational error: {e}")
        raise
    except sqlite3.DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"Error closing database connection: {e}")

# ============ Database Initialization ============

def init_db():
    """
    Initialize database schema.
    Creates tables if they don't exist.
    Enables WAL mode for concurrent access.
    Handles migration of existing databases.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Settings table for storing configuration
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    tokens_used TEXT DEFAULT '{}',
                    group_name TEXT DEFAULT NULL
                )
            """)
            
            # Migrate existing conversations table if needed
            cursor.execute("PRAGMA table_info(conversations)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'updated_at' not in columns:
                logger.info("Migrating conversations table: adding updated_at column")
                try:
                    cursor.execute("ALTER TABLE conversations ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Migration skipped (column may already exist): {e}")
            if 'tokens_used' not in columns:
                logger.info("Migrating conversations table: adding tokens_used column")
                try:
                    cursor.execute("ALTER TABLE conversations ADD COLUMN tokens_used TEXT DEFAULT '{}'")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Migration skipped (column may already exist): {e}")
            if 'group_name' not in columns:
                logger.info("Migrating conversations table: adding group_name column")
                try:
                    cursor.execute("ALTER TABLE conversations ADD COLUMN group_name TEXT DEFAULT NULL")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Migration skipped (column may already exist): {e}")
            
            # Create index on conversations.created_at for faster sorting
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_created_at
                ON conversations(created_at DESC)
            """)
            
            # System Prompts table (custom user behaviors)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    is_custom INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Groups table (for persistent group storage)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    name TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations (id)
                )
            """)
            
            # Create indexes for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages(conversation_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp
                ON messages(timestamp DESC)
            """)
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

# ============ Settings Management ============

def set_setting(key: str, value: str) -> None:
    """
    Save a setting key-value pair.
    Uses INSERT OR REPLACE for idempotency.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, datetime.now().isoformat())
            )
            conn.commit()
            logger.debug(f"Setting saved: {key}")
    except Exception as e:
        logger.error(f"Error setting {key}: {e}")
        raise

def get_setting(key: str) -> str | None:
    """
    Retrieve a setting value by key.
    Returns None if key doesn't exist.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            result = row[0] if row else None
            logger.debug(f"Retrieved setting: {key}")
            return result
    except Exception as e:
        logger.error(f"Error retrieving setting {key}: {e}")
        raise

def get_all_settings() -> dict:
    """Retrieve all settings as a dictionary"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            return dict(cursor.fetchall())
    except Exception as e:
        logger.error(f"Error retrieving all settings: {e}")
        raise

def delete_setting(key: str) -> None:
    """Delete a setting by key"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            logger.debug(f"Setting deleted: {key}")
    except Exception as e:
        logger.error(f"Error deleting setting {key}: {e}")
        raise

# ============ Conversation Management ============

def create_conversation(conv_id: str, name: str) -> None:
    """
    Create a new conversation.
    
    Args:
        conv_id: Unique conversation identifier
        name: Display name for the conversation
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO conversations (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conv_id, name, datetime.now().isoformat(), datetime.now().isoformat())
            )
            conn.commit()
            logger.info(f"Conversation created: {conv_id}")
    except sqlite3.IntegrityError as e:
        logger.error(f"Conversation {conv_id} already exists: {e}")
        raise
    except Exception as e:
        logger.error(f"Error creating conversation {conv_id}: {e}")
        raise

def conversation_exists(conv_id: str) -> bool:
    """Check if a conversation exists"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM conversations WHERE id = ?", (conv_id,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking conversation {conv_id}: {e}")
        raise

def get_all_conversations() -> list:
    """
    Get all conversations sorted by group and modification date.
    Returns list of dicts with id, name, created_at, tokens_used, group_name.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, created_at, tokens_used, group_name 
                FROM conversations 
                ORDER BY 
                    CASE WHEN group_name IS NULL THEN 1 ELSE 0 END,
                    group_name ASC,
                    updated_at DESC
                """
            )
            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "created_at": row[2],
                    "tokens_used": json.loads(row[3]) if row[3] else {},
                    "group_name": row[4]
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        logger.error("Error retrieving conversations: {e}")
        raise

def get_conversation(conv_id: str) -> dict | None:
    """Get a specific conversation"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, created_at, updated_at, tokens_used FROM conversations WHERE id = ?",
                (conv_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "tokens_used": json.loads(row[4]) if row[4] else {}
            }
    except Exception as e:
        logger.error(f"Error retrieving conversation {conv_id}: {e}")
        raise

def update_conversation_name(conv_id: str, name: str) -> None:
    """Update a conversation's name"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE conversations SET name = ?, updated_at = ? WHERE id = ?",
                (name, datetime.now().isoformat(), conv_id)
            )
            conn.commit()
            logger.debug(f"Conversation name updated: {conv_id}")
    except Exception as e:
        logger.error(f"Error updating conversation {conv_id}: {e}")
        raise

def delete_conversation(conv_id: str) -> None:
    """
    Delete a conversation and all its messages.
    Uses transaction for atomicity.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Delete all messages first (respects foreign key constraint)
            cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            
            # Then delete the conversation
            cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            
            conn.commit()
            logger.info(f"Conversation deleted: {conv_id}")
    except Exception as e:
        logger.error(f"Error deleting conversation {conv_id}: {e}")
        raise

# ============ Message Management ============

def save_message(
    conv_id: str,
    role: str,
    content: str,
    model: str = None
) -> int:
    """
    Save a message to a conversation.
    
    Args:
        conv_id: Conversation ID
        role: Message role ('user', 'assistant', 'system')
        content: Message content
        model: Model used (optional)
    
    Returns:
        Message ID
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Verify conversation exists
            cursor.execute("SELECT 1 FROM conversations WHERE id = ?", (conv_id,))
            if not cursor.fetchone():
                raise ValueError(f"Conversation {conv_id} does not exist")
            
            # Insert message
            cursor.execute(
                """
                INSERT INTO messages (conversation_id, role, content, model, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conv_id, role, content, model, datetime.now().isoformat())
            )
            
            # Update conversation's updated_at timestamp
            cursor.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), conv_id)
            )
            
            conn.commit()
            message_id = cursor.lastrowid
            logger.debug(f"Message saved: {message_id} to {conv_id}")
            return message_id
    
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error saving message to {conv_id}: {e}")
        raise

def get_messages(conv_id: str) -> list:
    """
    Get all messages in a conversation, ordered by timestamp.
    
    Returns:
        List of dicts with role and content
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
                (conv_id,)
            )
            return [
                {
                    "role": row[0],
                    "content": row[1]
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        logger.error(f"Error retrieving messages for {conv_id}: {e}")
        raise

def get_message_count(conv_id: str) -> int:
    """Get the number of messages in a conversation"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conv_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"Error getting message count for {conv_id}: {e}")
        raise

def get_messages_paginated(
    conv_id: str,
    limit: int = 50,
    offset: int = 0
) -> tuple[list, int]:
    """
    Get messages with pagination.
    
    Returns:
        Tuple of (messages list, total count)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conv_id,)
            )
            total = cursor.fetchone()[0]
            
            # Get paginated messages
            cursor.execute(
                """
                SELECT role, content FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (conv_id, limit, offset)
            )
            
            messages = [
                {
                    "role": row[0],
                    "content": row[1]
                }
                for row in cursor.fetchall()
            ]
            
            return messages, total
    except Exception as e:
        logger.error(f"Error getting paginated messages for {conv_id}: {e}")
        raise

def update_token_count(conv_id: str, model: str, tokens: int) -> None:
    """Update token count for a model in a conversation"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tokens_used FROM conversations WHERE id = ?", (conv_id,))
            row = cursor.fetchone()
            tokens_used = json.loads(row[0]) if row and row[0] else {}
            
            # Add tokens to model (accumulate)
            if model not in tokens_used:
                tokens_used[model] = 0
            tokens_used[model] += tokens
            
            cursor.execute(
                "UPDATE conversations SET tokens_used = ?, updated_at = ? WHERE id = ?",
                (json.dumps(tokens_used), datetime.now().isoformat(), conv_id)
            )
            conn.commit()
            logger.debug(f"Updated token count for {conv_id}: {model} += {tokens}")
    except Exception as e:
        logger.error(f"Error updating token count: {e}")
        raise

def delete_message(message_id: int) -> None:
    """Delete a specific message"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            conn.commit()
            logger.debug(f"Message deleted: {message_id}")
    except Exception as e:
        logger.error(f"Error deleting message {message_id}: {e}")
        raise

def delete_messages_from(conv_id: str, timestamp: str) -> None:
    """Delete all messages from a conversation after a given timestamp"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND timestamp >= ?",
                (conv_id, timestamp)
            )
            conn.commit()
            logger.debug(f"Messages deleted from {conv_id} after {timestamp}")
    except Exception as e:
        logger.error(f"Error deleting messages from {conv_id}: {e}")
        raise

# ============ Statistics & Analytics ============

def get_statistics() -> dict:
    """Get database statistics"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM conversations")
            conversation_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM messages")
            message_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT model) FROM messages WHERE model IS NOT NULL")
            model_count = cursor.fetchone()[0]
            
            # Get total tokens used (estimate based on content length)
            cursor.execute("SELECT SUM(LENGTH(content)) FROM messages")
            total_chars = cursor.fetchone()[0] or 0
            estimated_tokens = total_chars // 4  # Rough estimate: 1 token ≈ 4 chars
            
            return {
                "conversation_count": conversation_count,
                "message_count": message_count,
                "model_count": model_count,
                "estimated_tokens": estimated_tokens,
                "database_path": str(Path(DB_PATH).absolute())
            }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise

# ============ Database Maintenance ============

def vacuum_database() -> None:
    """
    Optimize and compact the database.
    Should be called periodically.
    """
    try:
        with get_db_connection() as conn:
            conn.execute("VACUUM")
            logger.info("Database vacuumed")
    except Exception as e:
        logger.error(f"Error vacuuming database: {e}")
        raise

def backup_database(backup_path: str = None) -> str:
    """
    Create a backup of the database.
    
    Args:
        backup_path: Path to save backup (default: chat_history.db.backup)
    
    Returns:
        Path to backup file
    """
    if backup_path is None:
        backup_path = f"{DB_PATH}.backup"
    
    try:
        with get_db_connection() as conn:
            backup_conn = sqlite3.connect(backup_path)
            conn.backup(backup_conn)
            backup_conn.close()
            logger.info(f"Database backed up to {backup_path}")
            return backup_path
    except Exception as e:
        logger.error(f"Error backing up database: {e}")
        raise

# ============ Search ============

# ============ System Prompts Management ============

def create_system_prompt(name: str, category: str, content: str, is_custom: int = 1) -> None:
    """Create a new system prompt"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO system_prompts (name, category, content, is_custom) VALUES (?, ?, ?, ?)",
                (name, category, content, is_custom)
            )
            conn.commit()
            logger.info(f"System prompt created: {name}")
    except sqlite3.IntegrityError:
        logger.error(f"System prompt '{name}' already exists")
        raise
    except Exception as e:
        logger.error(f"Error creating system prompt: {e}")
        raise

def get_all_system_prompts() -> list:
    """Get all system prompts (presets + custom)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, category, content, is_custom, created_at FROM system_prompts ORDER BY is_custom DESC, category, name"
            )
            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "category": row[2],
                    "content": row[3],
                    "is_custom": row[4],
                    "created_at": row[5]
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        logger.error(f"Error retrieving system prompts: {e}")
        raise

def get_system_prompt(name: str) -> dict | None:
    """Get a specific system prompt by name"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, category, content, is_custom, created_at FROM system_prompts WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "category": row[2],
                "content": row[3],
                "is_custom": row[4],
                "created_at": row[5]
            }
    except Exception as e:
        logger.error(f"Error retrieving system prompt '{name}': {e}")
        raise

def update_system_prompt(name: str, content: str) -> None:
    """Update system prompt content"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE system_prompts SET content = ? WHERE name = ?",
                (content, name)
            )
            conn.commit()
            logger.info(f"System prompt updated: {name}")
    except Exception as e:
        logger.error(f"Error updating system prompt '{name}': {e}")
        raise

def delete_system_prompt(name: str) -> None:
    """Delete a system prompt (only custom ones)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Check if it's custom
            cursor.execute("SELECT is_custom FROM system_prompts WHERE name = ?", (name,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"System prompt '{name}' not found")
            if not row[0]:
                raise ValueError(f"Cannot delete preset system prompt '{name}'")
            
            cursor.execute("DELETE FROM system_prompts WHERE name = ?", (name,))
            conn.commit()
            logger.info(f"System prompt deleted: {name}")
    except Exception as e:
        logger.error(f"Error deleting system prompt '{name}': {e}")
        raise

def reset_system_prompt(name: str, default_content: str) -> None:
    """Reset a system prompt to default (for presets)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE system_prompts SET content = ? WHERE name = ?",
                (default_content, name)
            )
            conn.commit()
            logger.info(f"System prompt reset to default: {name}")
    except Exception as e:
        logger.error(f"Error resetting system prompt '{name}': {e}")
        raise

def search_messages(
    query: str,
    conv_id: str = None,
    limit: int = 50
) -> list:
    """
    Search for messages containing query text.
    
    Args:
        query: Search term
        conv_id: Limit search to specific conversation (optional)
        limit: Max results
    
    Returns:
        List of matching messages
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if conv_id:
                cursor.execute(
                    """
                    SELECT conversation_id, role, content, timestamp
                    FROM messages
                    WHERE conversation_id = ? AND content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (conv_id, f"%{query}%", limit)
                )
            else:
                cursor.execute(
                    """
                    SELECT conversation_id, role, content, timestamp
                    FROM messages
                    WHERE content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", limit)
                )
            
            return [
                {
                    "conversation_id": row[0],
                    "role": row[1],
                    "content": row[2],
                    "timestamp": row[3]
                }
                for row in cursor.fetchall()
            ]
    except Exception as e:
        logger.error(f"Error searching messages: {e}")
        raise

# ============ Memory/Database Cleanup ============

def cleanup_old_conversations(days: int = 30) -> int:
    """Delete conversations older than specified days"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            cursor.execute(
                "DELETE FROM conversations WHERE created_at < ?",
                (cutoff_date,)
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleanup: Deleted {deleted} conversations older than {days} days")
            return deleted
    except Exception as e:
        logger.error(f"Error cleaning up conversations: {e}")
        raise

def cleanup_orphaned_messages() -> int:
    """Delete messages from non-existent conversations"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)"
            )
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleanup: Deleted {deleted} orphaned messages")
            return deleted
    except Exception as e:
        logger.error(f"Error cleaning orphaned messages: {e}")
        raise

def vacuum_database() -> None:
    """Optimize database by reclaiming space"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("VACUUM")
            conn.commit()
            logger.info("Database vacuumed and optimized")
    except Exception as e:
        logger.error(f"Error vacuuming database: {e}")
        raise

def get_database_size() -> dict:
    """Get current database usage stats"""
    try:
        import os
        db_path = "chat_history.db"
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            size_mb = size_bytes / (1024 * 1024)
            return {"size_bytes": size_bytes, "size_mb": round(size_mb, 2)}
        return {"size_bytes": 0, "size_mb": 0}
    except Exception as e:
        logger.error(f"Error getting database size: {e}")
        return {"error": str(e)}

# ============ Group Management ============

def create_group(name: str) -> None:
    """Create a new chat group"""
    try:
        if not name or not name.strip():
            raise ValueError("Group name cannot be empty")
        
        name = name.strip()
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Check if group already exists
            cursor.execute("SELECT name FROM groups WHERE name = ?", (name,))
            if cursor.fetchone():
                raise ValueError(f"Group '{name}' already exists")
            
            cursor.execute(
                "INSERT INTO groups (name) VALUES (?)",
                (name,)
            )
            conn.commit()
            logger.info(f"Group created: {name}")
    except Exception as e:
        logger.error(f"Error creating group: {e}")
        raise

def get_all_groups() -> list:
    """Get all group names"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM groups ORDER BY name"
            )
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error retrieving groups: {e}")
        raise

def move_conversation_to_group(conv_id: str, group_name: str = None) -> None:
    """Move conversation to a group or outside groups"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE conversations SET group_name = ? WHERE id = ?",
                (group_name, conv_id)
            )
            conn.commit()
            logger.info(f"Moved conversation {conv_id} to group: {group_name}")
    except Exception as e:
        logger.error(f"Error moving conversation: {e}")
        raise

def rename_group(old_name: str, new_name: str) -> None:
    """Rename a group"""
    try:
        new_name = new_name.strip()
        
        if new_name == old_name:
            return  # No change needed
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Check if new name already exists
            cursor.execute("SELECT name FROM groups WHERE name = ?", (new_name,))
            if cursor.fetchone():
                raise ValueError(f"Group '{new_name}' already exists")
            
            # Update conversations
            cursor.execute(
                "UPDATE conversations SET group_name = ? WHERE group_name = ?",
                (new_name, old_name)
            )
            # Update groups table
            cursor.execute(
                "UPDATE groups SET name = ? WHERE name = ?",
                (new_name, old_name)
            )
            conn.commit()
            logger.info(f"Group renamed: {old_name} -> {new_name}")
    except Exception as e:
        logger.error(f"Error renaming group: {e}")
        raise

def delete_group(group_name: str) -> int:
    """Delete a group and return count of chats in it"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM conversations WHERE group_name = ?",
                (group_name,)
            )
            count = cursor.fetchone()[0]
            
            cursor.execute(
                "DELETE FROM conversations WHERE group_name = ?",
                (group_name,)
            )
            cursor.execute(
                "DELETE FROM groups WHERE name = ?",
                (group_name,)
            )
            conn.commit()
            logger.info(f"Group deleted: {group_name} ({count} chats deleted)")
            return count
    except Exception as e:
        logger.error(f"Error deleting group: {e}")
        raise

def move_group_chats_outside(group_name: str) -> int:
    """Move all chats from group outside (to no group)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM conversations WHERE group_name = ?",
                (group_name,)
            )
            count = cursor.fetchone()[0]
            
            cursor.execute(
                "UPDATE conversations SET group_name = NULL WHERE group_name = ?",
                (group_name,)
            )
            cursor.execute(
                "DELETE FROM groups WHERE name = ?",
                (group_name,)
            )
            conn.commit()
            logger.info(f"Moved {count} chats from group {group_name} outside")
            return count
    except Exception as e:
        logger.error(f"Error moving group chats outside: {e}")
        raise

# ============ Groups Table (for persistent storage) ============

def init_groups_table():
    """Initialize groups table if it doesn't exist"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    name TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("Groups table initialized")
    except Exception as e:
        logger.error(f"Error initializing groups table: {e}")
        raise