#!/usr/bin/env python3

import os
import logging
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# configuración simplificada
bot.config = {
    'TOKEN': os.getenv('DISCORD_TOKEN'),
    'GUILD_ID': int(os.getenv('GUILD_ID') or 0),
    'VERIFICATION_CHANNEL_ID': int(os.getenv('VERIFICATION_CHANNEL_ID') or 0),
    'VERIFICATION_EMOJI': os.getenv('VERIFICATION_EMOJI', '✅'),
    'ROLE_ID_VERIFIED': int(os.getenv('ROLE_ID_VERIFIED') or 0),
    'ROLE_ID_NOT_VERIFIED': int(os.getenv('ROLE_ID_NOT_VERIFIED') or 0),
    'ADMIN_CHANNEL_ID': int(os.getenv('ADMIN_CHANNEL_ID', 0)),  # Asegurar conversión a int
    'LOG_CHANNEL_ID': int(os.getenv('LOG_CHANNEL_ID') or 0),
    'MYSQL_HOST': os.getenv('MYSQL_HOST'),
    'MYSQL_PORT': int(os.getenv('MYSQL_PORT') or 3306),
    'MYSQL_USER': os.getenv('MYSQL_USER'),
    'MYSQL_PASS': os.getenv('MYSQL_PASS'),
    'MYSQL_DB': os.getenv('MYSQL_DB'),
    'DEBUG_MODE': os.getenv('DEBUG_MODE', '0') == '1'
}

log_manager = None  # instancia de LogManager (debe definirse luego)


class LogManager:
    def __init__(self, channel: discord.TextChannel):
        self.channel = channel
        self.log_queue = []
        self.log_message = None
        self.lock = asyncio.Lock()
        self._ready = asyncio.Event()

    async def start(self):
        try:
            # Limpiar mensajes antiguos
            try:
                await self.channel.purge(limit=5)
            except discord.Forbidden:
                pass
                
            # Crear nuevo mensaje
            self.log_message = await self.channel.send("```Iniciando sistema de logs...```")
            self._ready.set()
            logging.info("Sistema de logs inicializado")
        except Exception as e:
            logging.error(f"Error iniciando logs: {e}")
            self._ready.set()  # Marcar como listo incluso si falla

    async def add_log(self, message: str):
        await self._ready.wait()
        
        async with self.lock:
            try:
                # Mantener solo los últimos 20 logs
                self.log_queue.append(str(message))
                if len(self.log_queue) > 20:
                    self.log_queue.pop(0)
                
                content = "```\n" + "\n".join(self.log_queue) + "\n```"
                
                if self.log_message:
                    await self.log_message.edit(content=content)
                else:
                    self.log_message = await self.channel.send(content)
            except Exception as e:
                logging.error(f"Error actualizando logs: {e}")
            
class DiscordLogHandler(logging.Handler):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
        self.setLevel(logging.INFO)

    def emit(self, record):
        log_entry = self.format(record)
        if log_manager and log_manager._ready.is_set():
            asyncio.run_coroutine_threadsafe(log_manager.add_log(log_entry), self.loop)
            
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Comando no reconocido. Usa `!comandos`.")
    else:
        logging.exception(f"Error en comando: {error}")
        await ctx.send("Ocurrió un error. Revisa logs.")


async def load_cogs():
    for ext in ["cogs.verification", "cogs.admin", "cogs.status", "cogs.debug_utils"]:
        try:
            await bot.load_extension(ext)
            logging.info(f"Cog {ext} cargado.")
        except Exception as e:
            logging.error(f"No pude cargar {ext}: {e}")


@bot.event
async def setup_hook():
    # Se ejecuta antes de conectar
    await load_cogs()
    # Lanzar periodic sync (db.periodic_sync_task) en background
    import db
    bot.loop.create_task(db.periodic_sync_task())

# Comando para apagar el bot, solo usable por el dueño (owner)
@bot.command(name="shutdown")
@commands.is_owner()
async def shutdown(ctx):
    await ctx.send("Apagando el bot... Hasta luego 👋")
    await bot.close()
    
@bot.event
async def on_ready():
    global log_manager
    logging.info(f"Bot conectado como {bot.user}")
    
    try:
        # 1. Configurar LogManager primero
        log_channel = bot.get_channel(int(bot.config.get('LOG_CHANNEL_ID', 0)))
        if log_channel:
            log_manager = LogManager(log_channel)
            await log_manager.start()
            
            # Configurar handler de logs para Discord
            discord_handler = DiscordLogHandler(bot.loop)
            logging.getLogger().addHandler(discord_handler)
            logging.info("Handler de logs configurado")
        
        # 2. Inicializar el panel de administración
        admin_cog = bot.get_cog("AdminPanelCog")
        if admin_cog:
            # No necesitamos llamar a render_panel aquí, ya se llama en initialize_panel
            logging.info("AdminPanel cog cargado")
        
        # 3. El cog de status se inicia automáticamente
        if bot.get_cog("Status"):
            logging.info("Status cog cargado")
        
        logging.info("Inicialización completa")
    except Exception as e:
        logging.exception("Error crítico en on_ready:")
        
if __name__ == "__main__":
    TOKEN = bot.config['TOKEN']
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN no configurado en .env")
    asyncio.run(bot.start(TOKEN))
