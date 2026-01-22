import discord
from discord.ext import commands
from discord.ui import View, Select, Button
import logging
import asyncio
from uniguard.utils import generate_verification_code, hash_code, validate_university_email, validate_minecraft_username, FACULTIES
from uniguard import db
from uniguard.emailer import send_verification_email_async
from uniguard.localization import t

logger = logging.getLogger("verification")

# ---------------------------------------------------
# COMPONENTES DE UI (Vistas y Selectores)
# ---------------------------------------------------

class CareerSelect(Select):
    def __init__(self, options, cog, user_id):
        """A lightweight Select that receives a pre-sliced list of options (max 25)."""
        self.cog = cog
        self.user_id = user_id
        super().__init__(placeholder=t('verification.select_career_placeholder'), min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        code = self.values[0]

        # Guardar carrera y avanzar estado
        async with self.cog.lock:
            if self.user_id in self.cog.user_states:
                self.cog.user_states[self.user_id]["career_code"] = code
                self.cog.user_states[self.user_id]["stage"] = "awaiting_mc"
                guild_ctx = self.cog.user_states[self.user_id].get('guild_id')

        embed = discord.Embed(title=t('verification.info_title', guild=guild_ctx), description=t('verification.career_saved', code=code, guild=guild_ctx), color=0x3498db)
        # Send to the same channel (usually DM), do not use ephemeral here
        await interaction.response.send_message(embed=embed)
        # Stop the whole pager view so buttons/selects are inactive
        if self.view and isinstance(self.view, View):
            self.view.stop()


class CareerPagerView(View):
    """Provides paginated career selects when a faculty has >25 careers.

    It slices the careers list into pages of 25 and exposes "Anterior"/"Siguiente" buttons
    to navigate pages. Each page contains a `CareerSelect` with a subset of options.
    """
    def __init__(self, faculty_name, cog, user_id):
        super().__init__(timeout=None)
        self.faculty_name = faculty_name
        self.cog = cog
        self.user_id = user_id
        self.careers = list(FACULTIES.get(faculty_name, {}).items())
        self.max_per = 25
        self.page = 0
        # Initialize first page
        self._refresh()

    def _refresh(self):
        # Remove previous select if present
        for child in list(self.children):
            if isinstance(child, Select):
                self.remove_item(child)
        # Compute slice
        start = self.page * self.max_per
        slice_items = self.careers[start:start + self.max_per]
        options = [discord.SelectOption(label=name, description=f"Código: {code}", value=code) for name, code in slice_items]
        # Add the select for this page
        self.add_item(CareerSelect(options, self.cog, self.user_id))

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: Button):
        if self.page > 0:
            self.page -= 1
            self._refresh()
            guild_ctx = (self.cog.user_states.get(self.user_id) or {}).get('guild_id')
            embed = discord.Embed(
                title=t('verification.select_faculty_title', guild=guild_ctx),
                description=f"🏛️ **{self.faculty_name}**\n\n{t('verification.select_career_prompt', guild=guild_ctx)}\n\n{t('verification.page_info', current=self.page+1, total=max(1, (len(self.careers)-1)//self.max_per+1), guild=guild_ctx)}",
                color=0x2ecc71
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Siguiente", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        if (self.page + 1) * self.max_per < len(self.careers):
            self.page += 1
            self._refresh()
            guild_ctx = (self.cog.user_states.get(self.user_id) or {}).get('guild_id')
            embed = discord.Embed(
                title=t('verification.select_faculty_title', guild=guild_ctx),
                description=f"🏛️ **{self.faculty_name}**\n\n{t('verification.select_career_prompt', guild=guild_ctx)}\n\n{t('verification.page_info', current=self.page+1, total=max(1, (len(self.careers)-1)//self.max_per+1), guild=guild_ctx)}",
                color=0x2ecc71
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()


class FacultySelect(Select):
    def __init__(self, cog, user_id):
        self.cog = cog
        self.user_id = user_id
        # Use explicit values (the faculty name) to avoid any ambiguity with labels
        options = [discord.SelectOption(label=fac, value=fac) for fac in FACULTIES.keys()]
        super().__init__(placeholder=t('verification.select_faculty_placeholder'), min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        faculty = self.values[0]
        # Lanzar siguiente menu
        careers = FACULTIES.get(faculty, {})
        guild_ctx = (self.cog.user_states.get(self.user_id) or {}).get('guild_id')

        embed = discord.Embed(
            title=t('verification.select_faculty_title', guild=guild_ctx),
            description=f"🏛️ **{faculty}**\n\n{t('verification.select_career_prompt', guild=guild_ctx)}",
            color=0x2ecc71
        )

        # If there are more careers than Discord allows in a single Select, use a pager view
        if len(careers) > 25:
            view = CareerPagerView(faculty, self.cog, self.user_id)
            # initial page info appended
            embed.description += f"\n\n{t('verification.page_info', current=view.page+1, total=(len(view.careers)-1)//view.max_per+1, guild=guild_ctx)}"
            await interaction.response.send_message(embed=embed, view=view)
            return

        # Otherwise send a simple select with all careers
        options = [discord.SelectOption(label=name, description=f"Código: {code}", value=code) for name, code in careers.items()]
        view = View()
        view.add_item(CareerSelect(options, self.cog, self.user_id))
        await interaction.response.send_message(embed=embed, view=view)

class VerificationView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label=t('verification.start_button'), style=discord.ButtonStyle.success, custom_id="verify_start")
    async def verify(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        
        # 1. Anti-Spam: ¿Ya tiene una sesión abierta?
        async with self.cog.lock:
            if uid in self.cog.user_states:
                await interaction.response.send_message(t('verification.already_active', guild=interaction.guild.id if interaction.guild else None), ephemeral=True)
                return

        # 2. Check DB: ¿Ya está verificado?
        if await db.check_existing_user(uid):
            await interaction.response.send_message(t('verification.already_registered', guild=interaction.guild.id if interaction.guild else None), ephemeral=True)
            return

        # 3. Check Discord: ¿Tiene el rol pero no está en DB? (Inconsistencia)
        # Usar config.json para roles
        role_id = self.cog.bot.config.get('roles', {}).get('verified')
        if role_id and isinstance(interaction.user, discord.Member):
            rid = int(role_id)
            if any(r.id == rid for r in interaction.user.roles):
                await interaction.response.send_message(t('verification.already_has_role', guild=interaction.guild.id if interaction.guild else None), ephemeral=True)
        # Store the guild context so subsequent DM steps can use the guild language
        async with self.cog.lock:
            self.cog.user_states[uid] = {
                "stage": "awaiting_email",
                "attempts": 0,
                "career_code": None,
                "guild_id": interaction.guild.id if interaction.guild else None
            }

        # Attempt to send DM to the user. If Forbidden, notify in channel (non-ephemeral) so staff can see.
        guild_ctx = interaction.guild.id if interaction.guild else None
        # Resolve language explicitly (guild override preferred)
        from uniguard.localization import translate_for_lang, get_guild_lang, get_lang
        lang = get_guild_lang(guild_ctx) or get_lang()
        logger.debug(f"Verification: resolved language for guild {guild_ctx} -> {lang}")
        try:
            embed = discord.Embed(
                title=translate_for_lang('verification.dm_embed_title', lang, guild=guild_ctx),
                description=translate_for_lang('verification.dm_embed_desc', lang, guild=guild_ctx),
                color=0x3498db
            )
            await interaction.user.send(embed=embed)
        except discord.Forbidden:
            # User has DMs disabled; inform user privately (ephemeral) and do not spam the public channel
            try:
                await interaction.response.send_message(translate_for_lang('verification.dm_forbidden_ephemeral', lang, guild=guild_ctx), ephemeral=True)
            except discord.NotFound:
                # If interaction is missing, attempt a DM fallback (best-effort)
                try:
                    await interaction.user.send(translate_for_lang('verification.dm_forbidden_ephemeral', lang, guild=guild_ctx))
                except Exception as e:
                    logger.error(f"Failed to send forbidden fallback DM to user {uid}: {e}")
        else:
            # DM successfully sent; acknowledge the interaction to the user in the guild (ephemeral).
            try:
                msg_text = translate_for_lang('verification.dm_sent', lang, guild=guild_ctx)
                logger.debug(f"Sent ephemeral verification confirmation to user {uid} in guild {guild_ctx} (lang={lang})")
                await interaction.response.send_message(msg_text, ephemeral=True)
            except discord.NotFound:
                logger.warning("Interaction not found when sending ephemeral DM confirmation; using DM fallback.")
                try:
                    fallback = discord.Embed(title=translate_for_lang('verification.info_title', lang, guild=guild_ctx), description=translate_for_lang('verification.dm_sent', lang, guild=guild_ctx), color=0x3498db)
                    await interaction.user.send(embed=fallback)
                except Exception as e:
                    logger.error(f"Failed to send fallback DM to user {uid}: {e}")

# ---------------------------------------------------
# LOGICA PRINCIPAL (COG)
# ---------------------------------------------------

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.user_states = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Monta el botón persistente al reiniciar"""
        cid = self.bot.config.get('channels', {}).get('verification')
        if cid:
            ch = self.bot.get_channel(int(cid))
            if ch:
                # Limpiar canal para que se vea prolijo
                try:
                    async for msg in ch.history(limit=5):
                        if msg.author == self.bot.user:
                            await msg.delete()
                except Exception as e:
                    logger.warning(f"Error cleaning verification channel history: {e}")
                
                guild_ctx = ch.guild.id if ch.guild else None
                await ch.send(
                    embed=discord.Embed(
                        title=t('verification.panel_title', guild=guild_ctx), 
                        description=t('verification.panel_desc', guild=guild_ctx),
                        color=0x2ecc71
                    ),
                    view=VerificationView(self)
                )

    # --- HELPER: ASIGNACIÓN DE ROLES BLINDADA ---
    async def _safe_assign_roles(self, guild, member, career_code, mc_name):
        """Maneja toda la logica de Discord sin crashear si faltan permisos"""
        logs = []
        
        # 1. Nickname (Manejo de Jerarquía)
        # Si el usuario es Admin o el Dueño, esto fallará. Lo capturamos.
        try:
            new_nick = f"[{career_code}] {mc_name}"[:32] # Discord limita a 32 chars
            await member.edit(nick=new_nick)
        except discord.Forbidden:
            logs.append("(No pude cambiar tu nick: Jerarquía insuficiente)")
        except Exception as e:
            logger.warning(f"Error cambiando nickname para {member.id}: {e}")

        # 2. Roles Base (Verificado / No Verificado)
        try:
            rid_ver = int(self.bot.config.get('roles', {}).get('verified', 0))
            rid_not = int(self.bot.config.get('roles', {}).get('not_verified', 0))
            
            r_ver = guild.get_role(rid_ver)
            r_not = guild.get_role(rid_not)
            
            if r_ver:
                await member.add_roles(r_ver)
            if r_not:
                await member.remove_roles(r_not)
        except discord.Forbidden:
            logs.append("(Error de permisos asignando roles base)")

        # 3. Rol de Carrera (Búsqueda Inversa)
        # Buscamos en utils.py qué nombre corresponde al código seleccionado
        career_role_name = None
        for faculty, careers in FACULTIES.items():
            for name, code in careers.items():
                if code == career_code:
                    career_role_name = name
                    break
            if career_role_name:
                break
        
        if career_role_name:
            role = discord.utils.get(guild.roles, name=career_role_name)
            if role:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    logs.append(f"(No pude darte el rol de carrera: {career_role_name})")
            else:
                logger.warning(f"Rol de carrera no encontrado en Discord: '{career_role_name}'")
        
        return logs

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Filtros básicos
        if message.author.bot or not isinstance(message.channel, discord.DMChannel):
            return
        
        uid = message.author.id
        content = message.content.strip()
        
        # Recuperar estado
        async with self.lock:
            state = self.user_states.get(uid)
        
        if not state:
            return # Usuario no está verificándose

        # Cancelación global
        if content.lower() in ["cancelar", "salir", "exit"]:
            async with self.lock:
                del self.user_states[uid]
            guild_ctx = state.get('guild_id') if state else None
            embed = discord.Embed(title=t('verification.info_title', guild=guild_ctx), description=t('verification.process_cancelled', guild=guild_ctx), color=0xf1c40f)
            await message.channel.send(embed=embed)
            return

        stage = state['stage']

        # --- ETAPA 1: VALIDAR EMAIL ---
        if stage == "awaiting_email":
            email = content.lower()
            guild_ctx = state.get('guild_id') if state else None

            if not validate_university_email(email):
                embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.invalid_email', guild=guild_ctx), color=0xe74c3c)
                await message.channel.send(embed=embed)
                return
            
            # Anti-Multicuenta: Correo ya usado?
            if await db.check_existing_email(email):
                embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.email_already_registered', guild=guild_ctx), color=0xe74c3c)
                await message.channel.send(embed=embed)
                async with self.lock:
                    if uid in self.user_states:
                        del self.user_states[uid]
                return

            # Generar y enviar
            code = generate_verification_code(6)
            async with self.lock:
                self.user_states[uid].update({
                    "email": email,
                    "code_hash": hash_code(code),
                    "stage": "awaiting_code",
                    "attempts": 0
                })
            
            sent = await send_verification_email_async(email, code)
            if sent.get('success'):
                embed = discord.Embed(title=t('verification.info_title', guild=guild_ctx), description=t('verification.code_sent', email=email, guild=guild_ctx), color=0x3498db)
                await message.channel.send(embed=embed)
            else:
                embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.mail_failed', guild=guild_ctx), color=0xe74c3c)
                await message.channel.send(embed=embed)
                logger.error(f"Mailjet error: {sent}")
                async with self.lock:
                    del self.user_states[uid]

        # --- ETAPA 2: VALIDAR CÓDIGO ---
        elif stage == "awaiting_code":
            if hash_code(content) == state['code_hash']:
                async with self.lock:
                    self.user_states[uid]["stage"] = "selecting_career"
                
                # Lanzar UI de Facultad
                view = View()
                view.add_item(FacultySelect(self, uid))
                guild_ctx = state.get('guild_id') if state else None
                embed = discord.Embed(title=t('verification.info_title', guild=guild_ctx), description=t('verification.code_correct', guild=guild_ctx), color=0x2ecc71)
                await message.channel.send(embed=embed, view=view)
            else:
                # Contador de intentos
                async with self.lock:
                    self.user_states[uid]["attempts"] += 1
                    att = self.user_states[uid]["attempts"]
                guild_ctx = state.get('guild_id') if state else None
                if att >= int(self.bot.config.get('limits', {}).get('verification_max_attempts', 3)):
                    async with self.lock:
                        if uid in self.user_states:
                            del self.user_states[uid]
                    embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.too_many_attempts', guild=guild_ctx), color=0xe74c3c)
                    await message.channel.send(embed=embed)
                    return
                
                if att >= 3:
                    embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.too_many_attempts', guild=guild_ctx), color=0xe74c3c)
                    await message.channel.send(embed=embed)
                    async with self.lock:
                        del self.user_states[uid]
                else:
                    embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.code_incorrect', attempt=att, attempts=3, guild=guild_ctx), color=0xe74c3c)
                    await message.channel.send(embed=embed)

        # --- ETAPA 3: MINECRAFT (Final) ---
        elif stage == "awaiting_mc":
            guild_ctx = state.get('guild_id') if state else None
            if not validate_minecraft_username(content):
                embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.invalid_mc_name', guild=guild_ctx), color=0xe74c3c)
                await message.channel.send(embed=embed)
                return
            
            # Anti-Multicuenta: Minecraft name ya usado?
            if await db.check_duplicate_minecraft(content):
                embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.mc_name_registered', guild=guild_ctx), color=0xe74c3c)
                await message.channel.send(embed=embed)
                async with self.lock:
                    if uid in self.user_states:
                        del self.user_states[uid]
                return

            career = state.get("career_code", "EST")
            email = state['email']
            
            # 1. Guardar en Base de Datos (Prioridad Maxima)
            db_success = await db.update_or_insert_user(email, uid, content, career, u_type='student')
            
            if not db_success:
                guild_ctx = state.get('guild_id') if state else None
                embed = discord.Embed(title=t('verification.error_title', guild=guild_ctx), description=t('verification.db_save_failed', guild=guild_ctx), color=0xe74c3c)
                await message.channel.send(embed=embed)
                return
            
            # 2. Gestionar Discord (Si falla, no importa tanto, ya está en la DB)
            discord_msg = ""
            guild_id = self.bot.config.get('GUILD_ID')
            guild = None
            if guild_id:
                try:
                    guild = self.bot.get_guild(int(guild_id))
                except Exception:
                    guild = None
            
            if guild:
                member = guild.get_member(uid)
                if not member:
                    try:
                        member = await guild.fetch_member(uid)
                    except Exception as e:
                        logger.warning(f"Could not fetch member {uid}: {e}")
                
                if member:
                    logs = await self._safe_assign_roles(guild, member, career, content)
                    if logs:
                        discord_msg = "\nNote: " + " ".join(logs)
                else:
                    discord_msg = "\n(No te encontré en el servidor para darte roles, pero ya estás en la whitelist)"
            
            # 3. Confirmación Final
            embed = discord.Embed(
                title=t('verification.success_title'),
                description=t('verification.success_desc', name=content),
                color=0x2ecc71
            )
            if discord_msg:
                embed.set_footer(text=discord_msg)
            
            await message.channel.send(embed=embed)
            
            # Limpiar estado
            async with self.lock:
                del self.user_states[uid]

async def setup(bot):
    await bot.add_cog(Verification(bot))