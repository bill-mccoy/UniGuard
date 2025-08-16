import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, List

logger = logging.getLogger("db")
logger.addHandler(logging.NullHandler())

# Try to import aiomysql
try:
    import aiomysql
    HAVE_AIOMYSQL = True
except ImportError:
    aiomysql = None
    HAVE_AIOMYSQL = False

# Configuration from env
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "")
MYSQL_PASS = os.getenv("MYSQL_PASS", "")
MYSQL_DB = os.getenv("MYSQL_DB", "")
VERIFICATION_TOKEN_TTL = int(os.getenv("VERIFICATION_TOKEN_TTL", 600))

# Global pool and lock
_POOL: Optional["aiomysql.Pool"] = None
_pool_lock = asyncio.Lock()

async def init_pool(minsize: int = 1, maxsize: int = 5, retry: int = 3, retry_delay: float = 1.0) -> bool:
    """Initialize the MySQL connection pool"""
    global _POOL
    if not HAVE_AIOMYSQL:
        logger.error("aiomysql not installed. Install with: pip install aiomysql")
        return False

    async with _pool_lock:
        if _POOL is not None:
            return True

        attempt = 0
        while attempt < retry:
            attempt += 1
            try:
                _POOL = await aiomysql.create_pool(
                    host=MYSQL_HOST,
                    port=MYSQL_PORT,
                    user=MYSQL_USER,
                    password=MYSQL_PASS,
                    db=MYSQL_DB,
                    autocommit=True,
                    minsize=minsize,
                    maxsize=maxsize,
                    charset='utf8mb4',
                    use_unicode=True
                )
                logger.info("MySQL pool initialized successfully")
                await _ensure_tables()
                return True
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{retry} failed: {e}")
                if attempt < retry:
                    await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))
                else:
                    logger.exception("Failed to initialize MySQL pool")
                    _POOL = None
                    return False
    return False

async def _ensure_tables() -> None:
    """Ensure required tables exist"""
    if _POOL is None:
        raise RuntimeError("Pool not initialized")
    
    tables_sql = [
        """
        CREATE TABLE IF NOT EXISTS verifications (
            user_id BIGINT PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            code VARCHAR(128),
            user VARCHAR(100),
            UUID VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """,
        """
        CREATE TABLE IF NOT EXISTS noble_whitelist (
            ID INT AUTO_INCREMENT PRIMARY KEY,
            Name VARCHAR(40) NOT NULL,
            UUID VARCHAR(36),
            Discord VARCHAR(40) NOT NULL,
            Whitelisted TINYINT(1) NOT NULL DEFAULT 1,
            UNIQUE KEY discord_idx (Discord),
            UNIQUE KEY name_idx (Name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    ]

    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                for sql in tables_sql:
                    await cur.execute(sql)
        logger.info("Tables verified/created")
    except Exception:
        logger.exception("Error creating tables")

async def _ensure_pool_or_log() -> bool:
    """Ensure connection pool is available"""
    if not HAVE_AIOMYSQL:
        return False
    if _POOL is not None:
        return True
    return await init_pool()

async def is_mysql_connected() -> bool:
    """Check if MySQL connection is active"""
    try:
        ok = await asyncio.wait_for(_ensure_pool_or_log(), timeout=3)
    except asyncio.TimeoutError:
        logger.error("_ensure_pool_or_log timed out in is_mysql_connected")
        return False
    if not ok:
        return False
    
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                return True
    except Exception as e:
        logger.error(f"Error checking MySQL connection: {e}")
        return False

async def store_verification_code(email: str, hashed_code: str, user_id: int) -> bool:
    """Store verification code"""
    # Ensure pool with timeout and logging
    try:
        ok = await asyncio.wait_for(_ensure_pool_or_log(), timeout=3)
    except asyncio.TimeoutError:
        logger.error("_ensure_pool_or_log timed out")
        return False
    if not ok:
        logger.error("_ensure_pool_or_log returned False (no DB)")
        return False

    sql = """
    INSERT INTO verifications (user_id, email, code, created_at)
    VALUES (%s, %s, %s, UTC_TIMESTAMP())
    ON DUPLICATE KEY UPDATE
        email = VALUES(email),
        code = VALUES(code),
        created_at = VALUES(created_at)
    """
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (int(user_id), email, hashed_code))
                await conn.commit()
        return True
    except Exception:
        logger.exception("Error storing verification code")
        return False
        
async def is_minecraft_username_available(username: str) -> bool:
    """Check if Minecraft username is already in use"""
    if not await _ensure_pool_or_log():
        return False

    sql = "SELECT Name FROM noble_whitelist WHERE Name = %s"
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (username,))
                return await cur.fetchone() is None
    except Exception as e:
        logger.error(f"Error checking username availability: {e}")
        return False
        
async def validate_token(user_id: int, token_hash: str, ttl_seconds: Optional[int] = None) -> Tuple[bool, str]:
    """Validate verification token"""
    if not await _ensure_pool_or_log():
        return False, "no_db"

    sql = "SELECT code, created_at FROM verifications WHERE user_id = %s"
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (int(user_id),))
                row = await cur.fetchone()
        
        if not row or row[0] is None:
            return False, "no_code"
        if row[0] != token_hash:
            return False, "mismatch"
        
        created_at = row[1].replace(tzinfo=timezone.utc) if row[1].tzinfo is None else row[1].astimezone(timezone.utc)
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        
        if age > (ttl_seconds or VERIFICATION_TOKEN_TTL):
            return False, "expired"
            
        return True, "ok"
    except Exception:
        logger.exception("Error validating token")
        return False, "error"

async def add_to_noble_whitelist(minecraft_name: str, discord_id: int) -> bool:
    """Add player to Minecraft whitelist"""
    if not await _ensure_pool_or_log():
        return False

    sql = """
    INSERT INTO noble_whitelist (Name, Discord, Whitelisted)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE
        Name = VALUES(Name),
        Whitelisted = VALUES(Whitelisted)
    """
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (minecraft_name, str(discord_id), 1))
                await conn.commit()
        logger.info(f"Successfully whitelisted {minecraft_name} (Discord ID: {discord_id})")
        return True
    except Exception as e:
        logger.error(f"Failed to whitelist {minecraft_name}: {str(e)}")
        return False

async def update_or_insert_user(email: Optional[str], user_id: int, username: Optional[str]) -> bool:
    """Update or insert user data in verifications and upsert noble_whitelist.Name.
    - email: if provided, update verifications.email
    - username: if provided, update verifications.user and noble_whitelist.Name
    """
    if not await _ensure_pool_or_log():
        return False

    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                # Upsert verifications
                ver_sql = """
                INSERT INTO verifications (user_id, email, user, created_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP())
                ON DUPLICATE KEY UPDATE
                    email = VALUES(email),
                    user = VALUES(user),
                    created_at = VALUES(created_at)
                """
                await cur.execute(ver_sql, (int(user_id), email, username))

                # If username provided, upsert noble_whitelist Name (preserve Whitelisted)
                if username:
                    wl_sql = """
                    INSERT INTO noble_whitelist (Name, Discord, Whitelisted)
                    VALUES (%s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        Name = VALUES(Name)
                    """
                    await cur.execute(wl_sql, (username, str(user_id)))
                await conn.commit()
        logger.info(f"Updated user {user_id}: email={email}, username={username}")
        return True
    except Exception:
        logger.exception("Error updating user")
        return False

async def delete_verification(user_id: str) -> bool:
    """Elimina registro de verificación por user_id"""
    if not await _ensure_pool_or_log():
        return False

    sql = "DELETE FROM verifications WHERE user_id = %s"
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (int(user_id),))
                await conn.commit()
        logger.info(f"Verificación eliminada para user_id {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error eliminando verificación: {e}")
        return False

async def delete_from_whitelist(discord_id: str) -> bool:
    """Elimina registro de noble_whitelist por Discord ID"""
    if not await _ensure_pool_or_log():
        return False

    sql = "DELETE FROM noble_whitelist WHERE Discord = %s"
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (str(discord_id),))
                await conn.commit()
        logger.info(f"Registro whitelist eliminado para Discord ID {discord_id}")
        return True
    except Exception as e:
        logger.error(f"Error eliminando de whitelist: {e}")
        return False

async def get_whitelist_flag(discord_id: str) -> Optional[int]:
    """Obtiene el valor de Whitelisted (0/1) para un Discord ID, o None si no existe"""
    if not await _ensure_pool_or_log():
        return None
    sql = "SELECT Whitelisted FROM noble_whitelist WHERE Discord = %s"
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (str(discord_id),))
                row = await cur.fetchone()
                return None if not row else int(row[0])
    except Exception:
        logger.exception("Error obteniendo flag de whitelist")
        return None

async def set_whitelist_flag(discord_id: str, enabled: bool) -> bool:
    """Ajusta Whitelisted a 1 (enabled) o 0 (disabled). Si no existe, inserta con Name tomado de verifications.user si está disponible."""
    if not await _ensure_pool_or_log():
        return False
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                # Intentar actualizar primero
                upd_sql = "UPDATE noble_whitelist SET Whitelisted = %s WHERE Discord = %s"
                await cur.execute(upd_sql, (1 if enabled else 0, str(discord_id)))
                if cur.rowcount == 0:
                    # Insertar usando nombre de verifications si existe
                    name = None
                    try:
                        await cur.execute("SELECT user FROM verifications WHERE user_id = %s", (int(discord_id),))
                        row = await cur.fetchone()
                        if row and row[0]:
                            name = row[0]
                    except Exception:
                        pass
                    ins_sql = "INSERT INTO noble_whitelist (Name, Discord, Whitelisted) VALUES (%s, %s, %s)"
                    await cur.execute(ins_sql, (name, str(discord_id), 1 if enabled else 0))
                await conn.commit()
        return True
    except Exception:
        logger.exception("Error ajustando flag de whitelist")
        return False

async def full_user_delete(discord_id: str) -> bool:
    """Elimina ambos registros (verificación y whitelist)"""
    verification_deleted = await delete_verification(discord_id)
    whitelist_deleted = await delete_from_whitelist(discord_id)
    return verification_deleted and whitelist_deleted

async def list_verified_players() -> List[Tuple[str, str, Optional[str]]]:
    """List all verified players (email, user_id, minecraft_username)"""
    if not await _ensure_pool_or_log():
        return []

    sql = """
    SELECT 
        email,
        user_id,
        user
    FROM verifications
    WHERE email IS NOT NULL
    ORDER BY created_at DESC
    """
    
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"Error listing verified players: {e}")
        return []
        
async def periodic_sync_task(interval_seconds: int = 300):
    """Background connection maintenance"""
    prev_connected = None
    while True:
        try:
            connected = await is_mysql_connected()
            if connected != prev_connected:
                logger.info(f"MySQL connection state: {connected}")
            prev_connected = connected
            if not connected:
                await init_pool()
        except Exception:
            logger.exception("Error in periodic_sync_task")
        await asyncio.sleep(interval_seconds)

async def close_pool():
    """Cleanup connection pool"""
    global _POOL
    if _POOL:
        try:
            _POOL.close()
            await _POOL.wait_closed()
        except Exception:
            logger.exception("Error closing pool")
        finally:
            _POOL = None