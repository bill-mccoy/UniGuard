import os
import asyncio
import logging
import warnings
from typing import Optional, Tuple, TYPE_CHECKING
import uniguard.config as config
if TYPE_CHECKING:
    import aiomysql

logger = logging.getLogger("db")
logger.addHandler(logging.NullHandler())

# si no tienes aiomysql instalado fuiste bueno
try:
    import aiomysql
    HAVE_AIOMYSQL = True
except ImportError:
    aiomysql = None
    HAVE_AIOMYSQL = False

# sacamos las credenciales del .env, si no estan explota
MYSQL_HOST = os.getenv("MYSQL_HOST", "db") 
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "")
MYSQL_PASS = os.getenv("MYSQL_PASS", "")
MYSQL_DB = os.getenv("MYSQL_DB", "")
VERIFICATION_TOKEN_TTL = int(os.getenv("VERIFICATION_TOKEN_TTL", 600))

_POOL: Optional["aiomysql.Pool"] = None
_pool_lock = asyncio.Lock()

async def init_pool(minsize: int = 1, maxsize: int = 5, suppress_logs: bool = False) -> bool:
    """Initialize the aiomysql pool with optional retries and exponential backoff.

    Reads retry settings from config under `system.db_retry_attempts` and
    `system.db_retry_backoff_base` / `system.db_retry_backoff_factor`.

    If `suppress_logs` is True, logging will be minimized (useful for background retries).
    """
    global _POOL, _LAST_DB_WARNING, _DB_WARNING_INTERVAL
    if not HAVE_AIOMYSQL:
        return False

    # Fetch retry settings from config (allows runtime tuning)
    attempts = int(config.get('system.db_retry_attempts', 3) or 3)
    backoff_base = float(config.get('system.db_retry_backoff_base', 1.0) or 1.0)
    backoff_factor = float(config.get('system.db_retry_backoff_factor', 2.0) or 2.0)

    # rate limit for warning messages (seconds)
    _DB_WARNING_INTERVAL = int(config.get('system.db_warning_interval', 300) or 300)

    async with _pool_lock:
        if _POOL is not None:
            return True

        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                # Read DB env vars lazily so load_dotenv() can occur before this function is called
                host = os.getenv("MYSQL_HOST", MYSQL_HOST)
                port = int(os.getenv("MYSQL_PORT", MYSQL_PORT))
                user = os.getenv("MYSQL_USER", MYSQL_USER)
                password = os.getenv("MYSQL_PASS", MYSQL_PASS)
                db_name = os.getenv("MYSQL_DB", MYSQL_DB)
                logger.debug("Attempting DB connection to %s:%s db=%s", host, port, db_name)
                _POOL = await aiomysql.create_pool(
                    host=host, port=port, user=user, password=password,
                    db=db_name, autocommit=False, minsize=minsize, maxsize=maxsize
                )
                await _ensure_tables()
                if attempt > 1 and not suppress_logs:
                    try:
                        from uniguard import localization
                        logger.info(localization.t('db.pool_initialized'))
                    except Exception:
                        logger.info("Database pool initialized.")
                return True
            except Exception as e:
                last_exc = e
                sleep_time = backoff_base * (backoff_factor ** (attempt - 1))
                # Minimize logging unless explicitly allowed
                if not suppress_logs:
                    if attempt < attempts:
                        logger.debug("DB init attempt %d/%d failed: %s. Retrying in %.1fs", attempt, attempts, e, sleep_time)
                    else:
                        # Rate-limited warning for final failure
                        import time
                        now = int(time.time())
                        if now - (getattr(globals(), '_LAST_DB_WARNING', 0)) > _DB_WARNING_INTERVAL:
                            globals()['_LAST_DB_WARNING'] = now
                            try:
                                from uniguard import localization
                                logger.warning(localization.t('db.background_retry', attempts=attempt, error=e))
                            except Exception:
                                logger.warning("DB init failed after %d attempts: %s. Will continue retrying in background.", attempt, e)
                        else:
                            logger.debug("DB init failed after %d attempts (suppressed warning): %s", attempt, e)
                else:
                    # suppress_logs == True -> only debug
                    logger.debug("DB init background attempt %d failed: %s", attempt, e)
                await asyncio.sleep(sleep_time)
        # All attempts exhausted
        if last_exc:
            logger.debug("Final DB init exception: %s", last_exc)
        return False

async def _ensure_tables() -> None:
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
    sql_verif = """
        CREATE TABLE IF NOT EXISTS verifications (
            user_id BIGINT PRIMARY KEY,
            email VARCHAR(255),
            code VARCHAR(128),
            user VARCHAR(100),
            type VARCHAR(20) DEFAULT 'student',
            career_code VARCHAR(5),
            real_name VARCHAR(100),
            sponsor_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    sql_wl = """
        CREATE TABLE IF NOT EXISTS noble_whitelist (
            ID INT AUTO_INCREMENT PRIMARY KEY,
            Name VARCHAR(40) NOT NULL UNIQUE,
            UUID VARCHAR(36) DEFAULT NULL,
            Discord VARCHAR(40) NOT NULL UNIQUE,
            Whitelisted TINYINT(1) DEFAULT 1,
            suspension_reason VARCHAR(256) DEFAULT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute("SET SESSION sql_notes = 0")
                except Exception:
                    logger.debug("Could not set SESSION sql_notes; continuing without suppression")

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    await cur.execute(sql_verif)
                    await cur.execute(sql_wl)

                try:
                    await cur.execute("SET SESSION sql_notes = 1")
                except Exception:
                    logger.debug("Could not reset SESSION sql_notes; continuing")

            await conn.commit()
    except Exception as e:
        logger.error(f"Error creating tables: {e}")

async def _ensure_pool_or_log() -> bool:
    if _POOL:
        return True
    # Suppress logs for normal background checks to avoid spamming
    return await init_pool(suppress_logs=True)

async def is_mysql_connected() -> bool:
    try:
        if not await _ensure_pool_or_log():
            return False
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                return True
    except Exception as e:
        # Avoid noisy ERROR logs for transient DB connectivity issues; use DEBUG so periodic checks don't spam.
        logger.debug(f"is_mysql_connected error (transient): {e}")
        return False

# --- VALIDACIONES DE SEGURIDAD (NUEVO) ---

async def check_existing_user(user_id: int) -> bool:
    """Revisa si el usuario de Discord ya esta verificado"""
    if not await _ensure_pool_or_log():
        return False
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM verifications WHERE user_id=%s", (user_id,))
            return (await cur.fetchone()) is not None

async def check_existing_email(email: str) -> bool:
    """Revisa si el correo ya fue usado por otra persona"""
    if not await _ensure_pool_or_log():
        return False
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM verifications WHERE email=%s", (email,))
            return (await cur.fetchone()) is not None

async def check_duplicate_minecraft(minecraft_name: str) -> bool:
    """Revisa si el nombre de Minecraft ya existe en la whitelist"""
    if not await _ensure_pool_or_log():
        return False
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM noble_whitelist WHERE Name=%s", (minecraft_name,))
            return (await cur.fetchone()) is not None

# --- LOGICA DE USUARIOS ---

async def store_verification_code(email: str, hashed_code: str, user_id: int) -> bool:
    if not await _ensure_pool_or_log():
        return False
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO verifications (user_id, email, code, created_at)
                    VALUES (%s, %s, %s, UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE email=VALUES(email), code=VALUES(code), created_at=VALUES(created_at)
                """, (user_id, email, hashed_code))
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error storing verification code: {e}")
        return False

async def update_or_insert_user(email: Optional[str], user_id: int, username: Optional[str], career_code: Optional[str] = None, u_type: Optional[str] = None) -> bool:
    """Insert or update a verification record.
    - If `u_type` is provided, it will be applied/updated (e.g., 'student' or 'guest').
    - If `u_type` is None, the function will NOT overwrite the existing `type` on duplicate keys (avoids accidentally converting guests to students).
    """
    if not await _ensure_pool_or_log():
        return False
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                if u_type is None:
                    await cur.execute("""
                        INSERT INTO verifications (user_id, email, user, type, career_code, created_at)
                        VALUES (%s, %s, %s, 'student', %s, UTC_TIMESTAMP())
                        ON DUPLICATE KEY UPDATE 
                            email=VALUES(email), user=VALUES(user), 
                            career_code=VALUES(career_code), created_at=VALUES(created_at)
                    """, (user_id, email, username, career_code))
                else:
                    await cur.execute("""
                        INSERT INTO verifications (user_id, email, user, type, career_code, created_at)
                        VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP())
                        ON DUPLICATE KEY UPDATE 
                            email=VALUES(email), user=VALUES(user), type=VALUES(type), 
                            career_code=VALUES(career_code), created_at=VALUES(created_at)
                    """, (user_id, email, username, u_type, career_code))

                if username:
                    await cur.execute("""
                        INSERT INTO noble_whitelist (Name, Discord, Whitelisted, UUID)
                        VALUES (%s, %s, 1, NULL)
                        ON DUPLICATE KEY UPDATE Name=VALUES(Name), Whitelisted=1
                    """, (username, str(user_id)))
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"error guardando user: {e}")
        return False

async def add_guest_user(discord_id: int, mc_username: str, real_name: str, sponsor_id: int) -> Tuple[bool, str]:
    if not await _ensure_pool_or_log():
        return False, "DB muerta"
    
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")

    try:
        max_guests = int(config.get('limits.max_guests_per_sponsor', 1) or 1)
    except Exception as e:
        logger.warning(f"Error reading max_guests_per_sponsor config, falling back to 1: {e}")
        max_guests = 1

    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT type FROM verifications WHERE user_id = %s FOR UPDATE", (sponsor_id,))
            row = await cur.fetchone()
            if not row:
                return False, "El Padrino no existe."
            if row[0] != 'student':
                return False, "Solo estudiantes pueden apadrinar."

            await cur.execute("SELECT count(*) FROM verifications WHERE sponsor_id = %s FOR UPDATE", (sponsor_id,))
            cnt = await cur.fetchone()
            current = cnt[0] if cnt else 0
            if current >= max_guests:
                return False, f"Este padrino ya tiene cupo lleno ({max_guests})."

            try:
                await cur.execute("""
                    INSERT INTO verifications (user_id, user, type, real_name, sponsor_id, created_at)
                    VALUES (%s, %s, 'guest', %s, %s, UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE 
                        user=VALUES(user), type='guest', real_name=VALUES(real_name), sponsor_id=VALUES(sponsor_id)
                """, (discord_id, mc_username, real_name, sponsor_id))
                
                await cur.execute("""
                    INSERT INTO noble_whitelist (Name, Discord, Whitelisted, UUID) 
                    VALUES (%s, %s, 1, NULL)
                    ON DUPLICATE KEY UPDATE Name=VALUES(Name), Whitelisted=1
                """, (mc_username, str(discord_id)))
                
                await conn.commit()
                return True, "Invitado agregado."
            except Exception as e:
                return False, f"Error SQL: {e}"


async def list_verified_players():
    if not await _ensure_pool_or_log():
        return []
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    SELECT email, user_id, user, type, sponsor_id, real_name 
                    FROM verifications ORDER BY created_at DESC
                """)
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"Error fetching verified players: {e}")
        return []

async def delete_verification(uid):
    if not await _ensure_pool_or_log():
        return False
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM verifications WHERE user_id=%s", (uid,))
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting verification for {uid}: {e}")
        return False

async def delete_from_whitelist(uid):
    if not await _ensure_pool_or_log():
        return False
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM noble_whitelist WHERE Discord=%s", (str(uid),))
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting from whitelist for {uid}: {e}")
        return False

async def full_user_delete(uid):
    """Delete user from both verifications and whitelist tables. Returns True if both succeed."""
    try:
        del_verif = await delete_verification(uid)
        del_wlist = await delete_from_whitelist(uid)
        success = del_verif and del_wlist
        if not success:
            logger.warning(f"full_user_delete for {uid}: verify_ok={del_verif}, whitelist_ok={del_wlist}")
        return success
    except Exception as e:
        logger.error(f"Error in full_user_delete for {uid}: {e}")
        return False

async def set_whitelist_flag(uid, enabled):
    if not await _ensure_pool_or_log():
        return False
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE noble_whitelist SET Whitelisted=%s WHERE Discord=%s", (1 if enabled else 0, str(uid)))
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting whitelist flag for {uid}: {e}")
        return False

async def get_whitelist_flag(uid):
    if not await _ensure_pool_or_log():
        return None
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT Whitelisted FROM noble_whitelist WHERE Discord=%s", (str(uid),))
            r = await cur.fetchone()
            return r[0] if r else None

async def set_suspension_reason(uid, reason: Optional[str]):
    if not await _ensure_pool_or_log():
        return False
    try:
        if _POOL is None:
            raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE noble_whitelist SET suspension_reason=%s WHERE Discord=%s",
                    (reason, str(uid))
                )
            await conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting suspension reason for {uid}: {e}")
        return False

async def get_suspension_reason(uid) -> Optional[str]:
    if not await _ensure_pool_or_log():
        return None
    if _POOL is None:
        raise RuntimeError("MySQL pool no inicializada (_POOL is None)")
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT suspension_reason FROM noble_whitelist WHERE Discord=%s", (str(uid),))
            r = await cur.fetchone()
            return r[0] if r else None
# ... rest unchanged ...


async def periodic_sync_task(interval: Optional[int] = None):
    """Background task that periodically pings the database to keep the pool alive.

    The `interval` (in seconds) can be provided or read from `config.system.db_sync_interval`.
    This task will not raise on DB failures and logs only at DEBUG level to avoid spam.
    """
    while True:
        try:
            # read interval from config each loop to allow runtime changes
            cfg_interval = config.get('system.db_sync_interval', None)
            use_interval = interval if interval is not None else (int(cfg_interval) if cfg_interval is not None else 300)

            # ensure pool exists (this will retry init based on config settings)
            await init_pool(minsize=1, maxsize=2)

            # do a lightweight health check (non-raising)
            await is_mysql_connected()
        except Exception:
            logger.debug("periodic_sync_task encountered an exception (ignored)", exc_info=True)
        await asyncio.sleep(use_interval)
