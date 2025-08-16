import discord
from discord.ext import commands, tasks
import asyncio
import logging
import psutil
import db

class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = int(bot.config.get('LOG_CHANNEL_ID') or 0)
        self.message = None
        self.logger = logging.getLogger("Status")
        self.update_task = bot.loop.create_task(self.status_loop())
        
    async def ensure_message(self):
        if self.message is not None:
            try:
                await self.message.channel.fetch_message(self.message.id)
                return
            except discord.NotFound:
                self.message = None
                
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            return
            
        try:
            self.message = await channel.send("⏳ Iniciando monitor de servicios...")
        except Exception as e:
            self.logger.error(f"Error creando mensaje de estado: {e}")

    async def status_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)
        
        while not self.bot.is_closed():
            try:
                await self.ensure_message()
                mysql_ok = await db.is_mysql_connected()
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                
                content = (
                    f"**Estado de servicios:**\n"
                    f"- MySQL: {'✅ Conectado' if mysql_ok else '❌ No conectado'}\n"
                    f"- CPU: {cpu}%\n"
                    f"- Memoria: {mem.used//(1024**2)} MB / {mem.total//(1024**2)} MB ({mem.percent}%)\n"
                )
                
                if self.message:
                    try:
                        await self.message.edit(content=content)
                    except discord.NotFound:
                        self.message = None
            except Exception as e:
                self.logger.error(f"Status loop error: {e}")
            finally:
                await asyncio.sleep(30)

    def cog_unload(self):
        if not self.update_task.cancelled():
            self.update_task.cancel()

async def setup(bot):
    await bot.add_cog(Status(bot))
    logging.info("Cog Status agregado.")
    