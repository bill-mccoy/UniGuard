import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, List

logger = logging.getLogger("db")
logger.addHandler(logging.NullHandler())

# check
try:
    import aiomysql
    HAVE_AIOMYSQL = True
except ImportError:
    aiomysql = None
    HAVE_AIOMYSQL = False

# info del env
MYSQL_HOST = os.getenv("MYSQL_HOST", "db") # ojo aqui con docker !!!!!!!!!!!!!!!!!!!!!!!!!
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "")
MYSQL_PASS = os.getenv("MYSQL_PASS", "")
MYSQL_DB = os.getenv("MYSQL_DB", "")
VERIFICATION_TOKEN_TTL = int(os.getenv("VERIFICATION_TOKEN_TTL", 600))

# pool global 
_POOL: Optional["aiomysql.Pool"] = None
_pool_lock = asyncio.Lock()

async def init_pool(minsize: int = 1, maxsize: int = 5) -> bool:
    global _POOL
    if not HAVE_AIOMYSQL: return False
    
    # bloqueo para que no se inicialice dos veces si el bot se marea
    async with _pool_lock:
        if _POOL is not None: return True
        try:
            _POOL = await aiomysql.create_pool(
                host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASS,
                db=MYSQL_DB, autocommit=True, minsize=minsize, maxsize=maxsize
            )
            # aqui chequeamos si las tablas existen, si no las crea
            await _ensure_tables()
            return True
        except Exception as e:
            logger.error(f"murio la pool de mysql: {e}")
            return False

async def _ensure_tables() -> None:
    if _POOL is None: return
    # tablas mas o menos decentes, ojala no haya que migrarlas despues xd
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
            Discord VARCHAR(40) NOT NULL UNIQUE,
            Whitelisted TINYINT(1) DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql_verif)
                await cur.execute(sql_wl)
    except Exception: pass

async def _ensure_pool_or_log() -> bool:
    if _POOL: return True
    return await init_pool()

async def is_mysql_connected() -> bool:
    try:
        if not await _ensure_pool_or_log(): return False
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                return True
    except: return False

# --- LOGICA DE USUARIOS ---

# guarda el codigo temporal
async def store_verification_code(email: str, hashed_code: str, user_id: int) -> bool:
    if not await _ensure_pool_or_log(): return False
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO verifications (user_id, email, code, created_at)
                    VALUES (%s, %s, %s, UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE email=VALUES(email), code=VALUES(code), created_at=VALUES(created_at)
                """, (user_id, email, hashed_code))
        return True
    except: return False

# actualiza o inserta alumno, ahora con carrera
async def update_or_insert_user(email: Optional[str], user_id: int, username: Optional[str], career_code: Optional[str] = None) -> bool:
    if not await _ensure_pool_or_log(): return False
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                # guardamos en la tabla principal
                await cur.execute("""
                    INSERT INTO verifications (user_id, email, user, type, career_code, created_at)
                    VALUES (%s, %s, %s, 'student', %s, UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE 
                        email=VALUES(email), user=VALUES(user), type='student', 
                        career_code=VALUES(career_code), created_at=VALUES(created_at)
                """, (user_id, email, username, career_code))

                # metemos a la whitelist :D
                if username:
                    await cur.execute("""
                        INSERT INTO noble_whitelist (Name, Discord, Whitelisted)
                        VALUES (%s, %s, 1)
                        ON DUPLICATE KEY UPDATE Name=VALUES(Name), Whitelisted=1
                    """, (username, str(user_id)))
        return True
    except Exception as e:
        logger.error(f"error guardando user: {e}")
        return False

# funcion para agregar al apadrinado, valida que el padrino sea de la pucv XD
async def add_guest_user(discord_id: int, mc_username: str, real_name: str, sponsor_id: int) -> Tuple[bool, str]:
    if not await _ensure_pool_or_log(): return False, "DB muerta"
    
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            # 1. vemos si el padrino existe y si es estudiante
            await cur.execute("SELECT type FROM verifications WHERE user_id = %s", (sponsor_id,))
            row = await cur.fetchone()
            if not row: return False, "El Padrino no existe en la DB."
            
            if row[0] != 'student': return False, "Solo estudiantes pueden apadrinar."

            # 2. vemos si ya tiene un ahijado (solo 1 permitido)
            await cur.execute("SELECT count(*) FROM verifications WHERE sponsor_id = %s", (sponsor_id,))
            cnt = await cur.fetchone()
            if cnt and cnt[0] >= 1: return False, "Este padrino ya tiene un bendecido (max 1)."

            # 3. insertamos al invitado
            try:
                await cur.execute("""
                    INSERT INTO verifications (user_id, user, type, real_name, sponsor_id, created_at)
                    VALUES (%s, %s, 'guest', %s, %s, UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE 
                        user=VALUES(user), type='guest', real_name=VALUES(real_name), sponsor_id=VALUES(sponsor_id)
                """, (discord_id, mc_username, real_name, sponsor_id))
                
                # whitelist
                await cur.execute("""
                    INSERT INTO noble_whitelist (Name, Discord, Whitelisted) VALUES (%s, %s, 1)
                    ON DUPLICATE KEY UPDATE Name=VALUES(Name), Whitelisted=1
                """, (mc_username, str(discord_id)))
                
                return True, "Invitado agregado joya."
            except Exception as e:
                return False, f"Error SQL: {e}"

# listado para el panel admin, ahora trae toda la data
async def list_verified_players():
    if not await _ensure_pool_or_log(): return []
    try:
        async with _POOL.acquire() as conn:
            async with conn.cursor() as cur:
                # traemos todo el choclo de datos
                await cur.execute("""
                    SELECT email, user_id, user, type, sponsor_id, real_name 
                    FROM verifications ORDER BY created_at DESC
                """)
                return await cur.fetchall()
    except: return []

# el resto de funciones auxiliares (delete, etc)
async def delete_verification(uid):
    if not await _ensure_pool_or_log(): return
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM verifications WHERE user_id=%s", (uid,))

async def delete_from_whitelist(uid):
    if not await _ensure_pool_or_log(): return
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM noble_whitelist WHERE Discord=%s", (str(uid),))

async def set_whitelist_flag(uid, enabled):
    if not await _ensure_pool_or_log(): return False
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE noble_whitelist SET Whitelisted=%s WHERE Discord=%s", (1 if enabled else 0, str(uid)))
    return True

async def get_whitelist_flag(uid):
    if not await _ensure_pool_or_log(): return None
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT Whitelisted FROM noble_whitelist WHERE Discord=%s", (str(uid),))
            r = await cur.fetchone()
            return r[0] if r else None
            
async def is_minecraft_username_available(name):
    if not await _ensure_pool_or_log(): return False
    async with _POOL.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT Name FROM noble_whitelist WHERE Name=%s", (name,))
            return (await cur.fetchone()) is None

async def periodic_sync_task():
    while True:
        await is_mysql_connected()
        await asyncio.sleep(300)