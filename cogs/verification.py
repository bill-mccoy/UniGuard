import discord
from discord.ext import commands
from discord.ui import View, Button
import logging
import asyncio
import os
from typing import Optional

from utils import generate_verification_code, hash_code, validate_university_email, validate_minecraft_username
import db
from emailer import send_verification_email_async

logger = logging.getLogger("verification")

TOKEN_TTL = int(os.getenv("VERIFICATION_TOKEN_TTL", 600))  # 10 minutes
MAX_TOKEN_ATTEMPTS = int(os.getenv("VERIFICATION_MAX_ATTEMPTS", 5))
MC_USERNAME_CONFIRM_TIMEOUT = 300  # 5 minutes

# --- Role helpers ---

def _get_verified_role_id(bot) -> int:
    rid = bot.config.get("ROLE_ID_VERIFIED") if hasattr(bot, "config") else (os.getenv("ROLE_ID_VERIFIED") or 0)
    try:
        return int(rid) or 0
    except Exception:
        return 0


def is_verified_by_role(bot, member: Optional[discord.Member]) -> bool:
    role_id = _get_verified_role_id(bot)
    if not role_id or member is None:
        return False
    try:
        return any(r.id == role_id for r in getattr(member, "roles", []))
    except Exception:
        return False


class VerificationView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Verificar", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: Button):
        try:
            guild = interaction.guild or self.cog.bot.get_guild(self.cog.bot.config.get('GUILD_ID'))
            member = interaction.user if isinstance(interaction.user, discord.Member) else (guild.get_member(interaction.user.id) if guild else None)
            if is_verified_by_role(self.cog.bot, member):
                await interaction.response.send_message(
                    "Ya estás verificado. Si necesitas reiniciar el proceso, contacta a un administrador. Si necesitas ayuda, dirígete al canal #soporte.",
                    ephemeral=True
                )
                return

            await interaction.response.send_message(
                "Te he enviado un mensaje privado con instrucciones.",
                ephemeral=True
            )
            dm = await interaction.user.create_dm()

            embed = discord.Embed(
                title="Verificación - Universidad",
                description="¡Hola! Para comenzar la verificación, por favor responde con tu correo universitario (@mail.pucv.cl).",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Escribe 'cancelar' en cualquier momento para salir del proceso.")

            await dm.send(embed=embed)

            async with self.cog.lock:
                logger.info("[verify_button] start flow for user=%s", interaction.user.id)
                self.cog.user_states[interaction.user.id] = {
                    "stage": "awaiting_email",
                    "email": None,
                    "mc_username": None,
                    "attempts": 0,
                    "task": None,
                    "token_hash": None,
                    "token_created": None,
                }
                self.cog.user_states[interaction.user.id]["task"] = asyncio.create_task(
                    self.cog._expire_state(interaction.user.id, 300))
        except discord.Forbidden:
            await interaction.response.send_message(
                "No puedo enviarte mensajes privados. Por favor habilita los DMs para este servidor y vuelve a intentar.",
                ephemeral=True
            )


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.user_states = {}

    async def reset_verification_channel(self):
        channel_id = int(self.bot.config['VERIFICATION_CHANNEL_ID'])
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.error(f"No se encontró el canal de verificación con ID {channel_id}")
            return

        try:
            await channel.purge(limit=100)
        except Exception as e:
            logger.error(f"Error al purgar el canal: {e}")

        view = VerificationView(self)
        self.bot.add_view(view)

        embed = discord.Embed(
            title="Verificación de Usuario",
            description="Para acceder al servidor, necesitas verificar tu identidad como estudiante.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Proceso de Verificación",
            value="1. Haz clic en el botón 'Verificar'\n"
                  "2. Sigue las instrucciones en mensajes privados\n"
                  "3. Ingresa tu correo universitario (@mail.pucv.cl)\n"
                  "4. Ingresa el código de verificación\n"
                  "5. Proporciona tu nombre de Minecraft",
            inline=False
        )

        await channel.send(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Cog Verification listo.")
        try:
            await self.reset_verification_channel()
        except Exception as e:
            logger.error(f"Error reseteando canal verificación: {e}")

    async def _expire_state(self, user_id: int, ttl: int):
        await asyncio.sleep(ttl)
        async with self.lock:
            state = self.user_states.get(user_id)
            if not state:
                return
            stage = state.get("stage")
            if stage in ("awaiting_email", "awaiting_token", "awaiting_mc", "confirming_mc"):
                try:
                    await db.delete_verification(str(user_id))
                except Exception:
                    pass
                try:
                    user = await self.bot.fetch_user(user_id)
                    await user.send(embed=discord.Embed(
                        title="Verificación Expirada",
                        description="Tu proceso de verificación ha expirado por inactividad.",
                        color=discord.Color.red()
                    ))
                except Exception:
                    pass
                task = state.get("task")
                if task and not task.done():
                    task.cancel()
                self.user_states.pop(user_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return

        user_id = message.author.id
        content_raw = message.content.strip()
        content = content_raw.lower()

        # Fetch state
        async with self.lock:
            state = self.user_states.get(user_id)
        if not state:
            # allow only if they click the button first
            try:
                guild = self.bot.get_guild(self.bot.config['GUILD_ID'])
                member = guild.get_member(user_id) if guild else None
                if is_verified_by_role(self.bot, member):
                    await message.channel.send("Ya estás verificado. Si necesitas reiniciar, contacta a un administrador.")
                    return
            except Exception:
                pass
            await message.channel.send(embed=discord.Embed(
                title="Verificación no iniciada",
                description="Haz clic en el botón 'Verificar' en el canal correspondiente.",
                color=discord.Color.orange()))
            return

        # Global cancel
        if content in ("cancel", "cancelar", "salir"):
            try:
                await db.delete_verification(str(user_id))
                await db.delete_from_whitelist(str(user_id))
            except Exception:
                pass
            await message.channel.send("Proceso cancelado. Puedes iniciar nuevamente cuando quieras.")
            async with self.lock:
                t = state.get("task")
                if t and not t.done():
                    t.cancel()
                self.user_states.pop(user_id, None)
            return

        stage = state.get("stage")

        # Stage: awaiting_email
        if stage == "awaiting_email":
            email = content_raw  # preserve case
            normalized = email.strip().lower()
            ok = False
            try:
                ok = validate_university_email(email)
            except Exception as e:
                logger.warning(f"validator raised: {e}")
            if not ok:
                ok = normalized.endswith("@mail.pucv.cl")
            logger.info("[awaiting_email] validator result for '%s': %s", email, ok)
            if not ok:
                try:
                    await message.channel.send(embed=discord.Embed(
                        title="Correo Inválido",
                        description="El correo debe ser una dirección @mail.pucv.cl válida.",
                        color=discord.Color.red()))
                except Exception:
                    await message.channel.send("Correo inválido. Debe terminar en @mail.pucv.cl")
                return

            # generate code and store in-memory
            code = generate_verification_code()
            hashed = hash_code(code)

            async with self.lock:
                t = state.get("task")
                if t and not t.done():
                    t.cancel()
                state.update({
                    "stage": "awaiting_token",
                    "email": email,
                    "attempts": 0,
                    "token_hash": hashed,
                    "token_created": asyncio.get_event_loop().time(),
                })
                state["task"] = asyncio.create_task(self._expire_state(user_id, TOKEN_TTL))

            # best-effort DB write (non-blocking)
            async def _bg_store():
                try:
                    await asyncio.wait_for(db.store_verification_code(email, hashed, str(user_id)), timeout=3)
                except Exception as e:
                    logger.warning(f"[bg] store_verification_code failed: {e}")
            asyncio.create_task(_bg_store())

            # send email (timeout)
            try:
                res = await asyncio.wait_for(send_verification_email_async(email, code), timeout=15)
                if not res.get("success"):
                    await message.channel.send(embed=discord.Embed(
                        title="Error al Enviar Correo",
                        description="No se pudo enviar el correo de verificación. Intenta nuevamente.",
                        color=discord.Color.red()))
                    return
                await message.channel.send(embed=discord.Embed(
                    title="Código Enviado",
                    description=f"Se ha enviado un código de verificación a {email}",
                    color=discord.Color.green()).add_field(
                        name="Tienes 10 minutos",
                        value="Responde con el código recibido. Escribe 'cancelar' para salir.",
                        inline=False))
                if self.bot.config.get("DEBUG_MODE"):
                    await message.channel.send(f"[MODO DEBUG] Código: `{code}`")
            except asyncio.TimeoutError:
                await message.channel.send(embed=discord.Embed(
                    title="Tiempo de espera agotado",
                    description="No se pudo enviar el correo a tiempo. Intenta más tarde.",
                    color=discord.Color.red()))
            except Exception as e:
                logger.error(f"Error enviando correo: {e}")
                await message.channel.send(embed=discord.Embed(
                    title="Error del Sistema",
                    description="Ocurrió un error al enviar el correo.",
                    color=discord.Color.red()))
            return

        # Stage: awaiting_token
        if stage == "awaiting_token":
            token = content_raw
            hashed_input = hash_code(token)
            token_hash = state.get("token_hash")
            token_created = state.get("token_created") or 0
            age = asyncio.get_event_loop().time() - token_created if token_created else TOKEN_TTL + 1
            ok = token_hash and (hashed_input == token_hash) and (age <= TOKEN_TTL)

            if ok:
                async with self.lock:
                    t = state.get("task")
                    if t and not t.done():
                        t.cancel()
                    state["stage"] = "awaiting_mc"
                    state["task"] = asyncio.create_task(self._expire_state(user_id, MC_USERNAME_CONFIRM_TIMEOUT))
                await message.channel.send(embed=discord.Embed(
                    title="¡Correo Verificado!",
                    description="Ahora necesitamos tu nombre de Minecraft para la whitelist del servidor.",
                    color=discord.Color.green()).add_field(
                        name="Requisitos del nombre:",
                        value="- Entre 3 y 16 caracteres\n- Solo letras (a-z), números (0-9) y guión bajo (_)\n- No usar caracteres especiales ni espacios",
                        inline=False))
            else:
                async with self.lock:
                    state["attempts"] = state.get("attempts", 0) + 1
                    attempts = state["attempts"]
                if attempts >= MAX_TOKEN_ATTEMPTS:
                    await message.channel.send(embed=discord.Embed(
                        title="Demasiados Intentos",
                        description=f"Has agotado el número máximo de intentos ({MAX_TOKEN_ATTEMPTS}). El proceso se cancela.",
                        color=discord.Color.red()))
                    async with self.lock:
                        t = state.get("task")
                        if t and not t.done():
                            t.cancel()
                        self.user_states.pop(user_id, None)
                else:
                    await message.channel.send(embed=discord.Embed(
                        title="Código Incorrecto",
                        description=f"El código ingresado no es válido. Intentos: {attempts}/{MAX_TOKEN_ATTEMPTS}",
                        color=discord.Color.orange()).add_field(
                            name="¿Qué hacer?",
                            value="Verifica el código en tu correo o escribe 'cancelar' para salir.",
                            inline=False))
            return

        # Stage: awaiting_mc
        if stage == "awaiting_mc":
            username = content_raw.strip()
            if not validate_minecraft_username(username):
                await message.channel.send(embed=discord.Embed(
                    title="Nombre Inválido",
                    description="El nombre de Minecraft debe tener entre 3-16 caracteres y solo puede contener letras, números y guión bajo (_).",
                    color=discord.Color.red()))
                return

            # optional: check availability via DB, but don't block success
            try:
                avail = await asyncio.wait_for(db.is_minecraft_username_available(username), timeout=3)
                if not avail:
                    await message.channel.send(embed=discord.Embed(
                        title="Nombre en Uso",
                        description=f"El nombre '{username}' ya está registrado en nuestra whitelist.",
                        color=discord.Color.red()).add_field(
                            name="Por favor elige otro nombre",
                            value="Si crees que esto es un error, contacta a un administrador.",
                            inline=False))
                    return
            except Exception:
                logger.warning("Username availability check failed; allowing proceed")

            async with self.lock:
                t = state.get("task")
                if t and not t.done():
                    t.cancel()
                state.update({
                    "stage": "confirming_mc",
                    "mc_username": username,
                })
                state["task"] = asyncio.create_task(self._expire_state(user_id, MC_USERNAME_CONFIRM_TIMEOUT))

            await message.channel.send(embed=discord.Embed(
                title="Confirmar Nombre de Minecraft",
                description=f"¿Confirmas que tu nombre de Minecraft es **{username}**?",
                color=discord.Color.blue()).add_field(
                    name="Responde:",
                    value="✅ 'si' para confirmar\n❌ 'no' para corregir",
                    inline=False))
            return

        # Stage: confirming_mc
        if stage == "confirming_mc":
            if content not in ('si', 'sí', 'yes'):
                async with self.lock:
                    state["stage"] = "awaiting_mc"
                await message.channel.send(embed=discord.Embed(
                    title="Corregir Nombre",
                    description="Por favor ingresa tu nombre de Minecraft nuevamente.",
                    color=discord.Color.blue()))
                return

            username = state.get("mc_username")
            email = state.get("email")

            # Best-effort DB updates; do not block success
            async def _bg_finalize():
                try:
                    await asyncio.wait_for(db.update_or_insert_user(email, str(user_id), username), timeout=3)
                    await asyncio.wait_for(db.add_to_noble_whitelist(username, user_id), timeout=3)
                except Exception as e:
                    logger.warning(f"[bg] finalize DB failed: {e}")
            asyncio.create_task(_bg_finalize())

            # Assign roles regardless of DB success
            try:
                guild = self.bot.get_guild(self.bot.config['GUILD_ID'])
                member = guild.get_member(user_id) if guild else None
                role_verified = guild.get_role(self.bot.config['ROLE_ID_VERIFIED']) if guild else None
                role_not_verified = guild.get_role(self.bot.config.get('ROLE_ID_NOT_VERIFIED')) if guild else None
                if member and role_verified:
                    await member.add_roles(role_verified)
                    if role_not_verified:
                        await member.remove_roles(role_not_verified)
            except Exception as e:
                logger.error(f"Error asignando roles al final para {user_id}: {e}")

            await message.channel.send(embed=discord.Embed(
                title="¡Verificación Completa!",
                description=f"Tu nombre **{username}** ha sido procesado.",
                color=discord.Color.green()).add_field(
                    name="¿Qué sigue?",
                    value="Ahora puedes unirte al servidor Minecraft con este nombre.",
                    inline=False).set_footer(text="¡Bienvenido/a a la comunidad!"))

            # Welcome message
            try:
                guild = self.bot.get_guild(self.bot.config['GUILD_ID'])
                channel = guild.get_channel(self.bot.config.get('WELCOME_CHANNEL_ID'))
                if channel:
                    welcome_msg = f"¡Bienvenido <@{user_id}> a la comunidad! Su nombre de Minecraft es `{username}`"
                    await channel.send(welcome_msg)
            except Exception:
                pass

            # cleanup
            async with self.lock:
                t = state.get("task")
                if t and not t.done():
                    t.cancel()
                self.user_states.pop(user_id, None)
            return


async def setup(bot):
    await bot.add_cog(Verification(bot))
    logger.info("Cog Verification agregado.")