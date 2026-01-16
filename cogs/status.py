import discord
from discord.ext import commands
import asyncio
import logging
import psutil
import db
import os

class Status(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = int(bot.config.get('LOG_CHANNEL_ID') or 0)
        # por defecto activado, si quieres apagarlo pon 0 en el env
        self.enable_status = os.getenv("ENABLE_STATUS_MSG", "1") == "1"
        # 5 minutos para que respire
        self.interval = int(os.getenv("STATUS_INTERVAL", "300")) 
        self.message = None
        self.logger = logging.getLogger("Status")
        self.update_task = bot.loop.create_task(self.status_loop())
        
    async def ensure_message(self):
        if not self.enable_status: return

        # intentamos reciclar el mensaje anterior para no llenar el chat
        if self.message is not None:
            try:
                await self.message.channel.fetch_message(self.message.id)
                return
            except discord.NotFound:
                self.message = None
                
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                # borramos la data vieja de lchat por si acaso
                async for msg in channel.history(limit=10):
                    if msg.author == self.bot.user and "Estado del Sistema" in msg.embeds[0].title if msg.embeds else False:
                        await msg.delete()
                self.message = await channel.send("⏳ Calentando motores...")
            except Exception: pass

    async def status_loop(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)
        
        while not self.bot.is_closed():
            if self.enable_status:
                try:
                    await self.ensure_message()
                    if self.message:
                        mysql_ok = await db.is_mysql_connected()
                        cpu = psutil.cpu_percent()
                        mem = psutil.virtual_memory()
                        
                        # un embed bonito para que se vea pro (odio los emojis pero el estilo ya estaba así y estoy usando copilot asi q tambien se pone modo vibecoder con emojis xddxdxd)
                        embed = discord.Embed(
                            title="📊 Estado del Sistema", 
                            color=discord.Color.green() if mysql_ok else discord.Color.red()
                        )
                        embed.add_field(name="Base de Datos", value="✅ Conectado" if mysql_ok else "❌ Murió", inline=True)
                        embed.add_field(name="CPU / RAM", value=f"{cpu}% / {mem.percent}%", inline=True)
                        embed.set_footer(text=f"Refrescando cada {self.interval} segs | UniGuard Bot")
                        
                        await self.message.edit(content=None, embed=embed)
                except Exception as e:
                    self.logger.error(f"exploto el status: {e}")
            
            # a mimir
            await asyncio.sleep(self.interval)

    def cog_unload(self):
        if not self.update_task.cancelled():
            self.update_task.cancel()

async def setup(bot):
    await bot.add_cog(Status(bot))