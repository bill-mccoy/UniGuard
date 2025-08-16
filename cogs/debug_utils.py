import discord
from discord.ext import commands
import psutil
import platform
import json
import time
import io  # for BytesIO

class Debug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.command_count = 0
        self.start_time = time.time()

    def cog_check(self, ctx):
        # Solo para administradores
        return ctx.author.guild_permissions.administrator

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        self.command_count += 1

    @commands.command(name="debug_stats")
    async def debug_stats(self, ctx):
        """Muestra estadísticas básicas del bot."""
        uptime = time.time() - self.start_time
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        embed = discord.Embed(title="Debug Stats", color=discord.Color.blue())
        embed.add_field(name="Uptime", value=f"{uptime:.2f} seg")
        embed.add_field(name="Comandos ejecutados", value=str(self.command_count))
        embed.add_field(name="Memoria usada", value=f"{mem.percent}% de {round(mem.total / (1024 ** 3), 2)} GB")
        embed.add_field(name="CPU", value=f"{cpu}%")
        embed.add_field(name="Python", value=platform.python_version())
        embed.add_field(name="Discord.py", value=discord.__version__)
        await ctx.send(embed=embed)

    @commands.command(name="debug_dump")
    async def debug_dump(self, ctx):
        """Envía dump del estado interno del bot en JSON."""
        data = {
            "uptime_seconds": time.time() - self.start_time,
            "command_count": self.command_count,
            "guilds": [g.name for g in self.bot.guilds],
            "users": sum(g.member_count for g in self.bot.guilds),
            "commands": [c.name for c in self.bot.commands],
            "debug_mode": getattr(self.bot, "debug_mode", False)
        }
        json_str = json.dumps(data, indent=2)
        # Enviar como archivo para evitar límite de caracteres
        await ctx.send(file=discord.File(fp=io.BytesIO(json_str.encode("utf-8")), filename="debug_dump.json"))

    @commands.command(name="debug_restart")
    async def debug_restart(self, ctx):
        """Reinicia el bot (requiere setup en host)."""
        await ctx.send("Reiniciando bot...")
        await self.bot.close()
        # El reinicio real depende de tu entorno (systemd, pm2, etc)

    @commands.command(name="debug_ping")
    async def debug_ping(self, ctx):
        """Mide latencia y tiempo de respuesta."""
        before = time.monotonic()
        message = await ctx.send("Pinging...")
        latency = (time.monotonic() - before) * 1000
        await message.edit(content=f"Pong! Latencia: {self.bot.latency*1000:.2f} ms, Respuesta: {latency:.2f} ms")

    @commands.command(name="debug_users")
    async def debug_users(self, ctx):
        """Lista usuarios y roles en el servidor."""
        guild = ctx.guild
        users = [f"{member.display_name} (ID: {member.id})" for member in guild.members[:20]]  # Limite para no saturar
        roles = [role.name for role in guild.roles]
        embed = discord.Embed(title=f"Usuarios y Roles de {guild.name}", color=discord.Color.green())
        embed.add_field(name="Usuarios (max 20)", value="\n".join(users) or "Ninguno")
        embed.add_field(name="Roles", value=", ".join(roles))
        await ctx.send(embed=embed)

    @commands.command(name="debug_verif_state")
    async def debug_verif_state(self, ctx, user_id: int = None):
        """Muestra el estado de verificación del usuario dado (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("Solo administradores.")
            return
        if user_id is None:
            await ctx.send("Uso: !debug_verif_state <user_id>")
            return
        verif_cog = self.bot.get_cog("Verification")
        if not verif_cog:
            await ctx.send("Verification cog no cargado")
            return
        async with verif_cog.lock:
            state = verif_cog.user_states.get(user_id)
        await ctx.send(f"state for {user_id}: {state}")

    @commands.command(name="debug_panel_info")
    async def debug_panel_info(self, ctx):
        """Muestra información de dónde y cómo se está renderizando el panel de administración."""
        admin_id = self.bot.config.get("ADMIN_CHANNEL_ID")
        channel = self.bot.get_channel(int(admin_id)) if admin_id else None
        channel_found = channel is not None
        fetched = None
        try:
            if not channel and admin_id:
                fetched = await self.bot.fetch_channel(int(admin_id))
        except Exception as e:
            fetched = f"fetch_channel error: {e}"

        admin_cog = self.bot.get_cog("AdminPanelCog")
        message_info = {}
        if admin_cog:
            try:
                msg = getattr(admin_cog, "_message", None)
                message_id = getattr(admin_cog.state, "message_id", None) if getattr(admin_cog, "state", None) else None
                if msg and isinstance(msg, discord.Message):
                    message_info = {
                        "_message_present": True,
                        "_message_id": msg.id,
                        "jump_url": msg.jump_url,
                        "channel_id": getattr(msg.channel, "id", None),
                    }
                else:
                    message_info = {
                        "_message_present": False,
                        "state_message_id": message_id,
                    }
            except Exception as e:
                message_info = {"error": str(e)}
        else:
            message_info = {"error": "AdminPanelCog no encontrado"}

        desc_lines = [
            f"ADMIN_CHANNEL_ID: {admin_id}",
            f"get_channel found: {channel_found}",
            f"fetch_channel result: {getattr(fetched, 'id', fetched)}",
            f"panel_message: {message_info}",
        ]
        embed = discord.Embed(title="Debug Panel Info", description="\n".join(desc_lines), color=discord.Color.orange())
        await ctx.send(embed=embed)
        
async def setup(bot):
    await bot.add_cog(Debug(bot))
