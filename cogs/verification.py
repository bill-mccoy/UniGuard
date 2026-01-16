import discord
from discord.ext import commands
from discord.ui import View, Select, Button
import logging
import asyncio
import os
from utils import generate_verification_code, hash_code, validate_university_email, validate_minecraft_username, FACULTIES
import db
from emailer import send_verification_email_async

logger = logging.getLogger("verification")

# ---------------------------------------------------
# COMPONENTES DE UI (Vistas y Selectores)
# ---------------------------------------------------

class CareerSelect(Select):
    def __init__(self, faculty_name, cog, user_id):
        self.cog = cog
        self.user_id = user_id
        careers = FACULTIES.get(faculty_name, {})
        
        options = []
        for name, code in careers.items():
            # El value es el CODIGO (ej: ICI), el label es el NOMBRE (ej: Ing. Civil Informática)
            options.append(discord.SelectOption(label=name, description=f"Código: {code}", value=code))
        
        super().__init__(placeholder="Selecciona tu Carrera...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        code = self.values[0]
        
        # Guardar carrera y avanzar estado
        async with self.cog.lock:
            if self.user_id in self.cog.user_states:
                self.cog.user_states[self.user_id]["career_code"] = code
                self.cog.user_states[self.user_id]["stage"] = "awaiting_mc"
        
        await interaction.response.send_message(
            f"✅ Carrera guardada: **{code}**\n\n📝 **Último paso:** Escribe tu **Nombre de Minecraft** (Java Edition) exacto.", 
            ephemeral=True
        )
        self.view.stop()

class FacultySelect(Select):
    def __init__(self, cog, user_id):
        self.cog = cog
        self.user_id = user_id
        options = [discord.SelectOption(label=fac) for fac in FACULTIES.keys()]
        super().__init__(placeholder="¿De qué Facultad eres?...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        faculty = self.values[0]
        # Lanzar siguiente menu
        view = View()
        view.add_item(CareerSelect(faculty, self.cog, self.user_id))
        await interaction.response.send_message(f"🏛️ Facultad: **{faculty}**\nBusca tu carrera en la lista:", view=view, ephemeral=True)

class VerificationView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🎓 Comenzar Verificación", style=discord.ButtonStyle.success, custom_id="verify_start")
    async def verify(self, interaction: discord.Interaction, button: Button):
        uid = interaction.user.id
        
        # 1. Anti-Spam: ¿Ya tiene una sesión abierta?
        async with self.cog.lock:
            if uid in self.cog.user_states:
                await interaction.response.send_message("⚠️ Ya tienes un proceso activo. Revisa tus mensajes privados (DMs).", ephemeral=True)
                return

        # 2. Check DB: ¿Ya está verificado?
        if await db.check_existing_user(uid):
            await interaction.response.send_message("✅ Ya estás registrado en el sistema.", ephemeral=True)
            return

        # 3. Check Discord: ¿Tiene el rol pero no está en DB? (Inconsistencia)
        role_id = self.cog.bot.config.get('ROLE_ID_VERIFIED')
        if role_id and isinstance(interaction.user, discord.Member):
            if interaction.user.get_role(int(role_id)):
                await interaction.response.send_message("🤔 Ya tienes el rol de alumno en Discord.", ephemeral=True)
                return

        # 4. Iniciar Proceso DM
        try:
            embed = discord.Embed(
                title="🔐 Verificación PUCV", 
                description="Para verificar que eres alumno, escribe tu correo institucional:\n`usuario@mail.pucv.cl`"
            )
            await interaction.user.send(embed=embed)
            
            async with self.cog.lock:
                self.cog.user_states[uid] = {
                    "stage": "awaiting_email", 
                    "attempts": 0,
                    "career_code": None
                }
            
            await interaction.response.send_message("📩 Te envié un mensaje privado. Revisa tus DMs.", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ **Error:** No puedo enviarte mensajes privados.\nActiva los DMs en: `Ajustes de Servidor > Privacidad`.", ephemeral=True)

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
        cid = self.bot.config.get('VERIFICATION_CHANNEL_ID')
        if cid:
            ch = self.bot.get_channel(int(cid))
            if ch:
                # Limpiar canal para que se vea prolijo
                try:
                    async for msg in ch.history(limit=5):
                        if msg.author == self.bot.user: await msg.delete()
                except: pass
                
                await ch.send(
                    embed=discord.Embed(
                        title="🛡️ Acceso UniGuard", 
                        description="Sistema exclusivo para alumnos de la **PUCV**.\nHaz clic abajo para verificar tu cuenta y entrar al servidor.",
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
        except Exception:
            pass

        # 2. Roles Base (Verificado / No Verificado)
        try:
            rid_ver = int(self.bot.config.get('ROLE_ID_VERIFIED', 0))
            rid_not = int(self.bot.config.get('ROLE_ID_NOT_VERIFIED', 0))
            
            r_ver = guild.get_role(rid_ver)
            r_not = guild.get_role(rid_not)
            
            if r_ver: await member.add_roles(r_ver)
            if r_not: await member.remove_roles(r_not)
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
            if career_role_name: break
        
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
        if message.author.bot or not isinstance(message.channel, discord.DMChannel): return
        
        uid = message.author.id
        content = message.content.strip()
        
        # Recuperar estado
        async with self.lock:
            state = self.user_states.get(uid)
        
        if not state: return # Usuario no está verificándose

        # Cancelación global
        if content.lower() in ["cancelar", "salir", "exit"]:
            async with self.lock: del self.user_states[uid]
            await message.channel.send("❌ Proceso cancelado.")
            return

        stage = state['stage']

        # --- ETAPA 1: VALIDAR EMAIL ---
        if stage == "awaiting_email":
            email = content.lower()
            if not validate_university_email(email):
                await message.channel.send("❌ Correo inválido. Debe ser `@mail.pucv.cl`.\nIntenta de nuevo o escribe `cancelar`.")
                return
            
            # Anti-Multicuenta: Correo ya usado?
            if await db.check_existing_email(email):
                await message.channel.send("⚠️ Este correo ya está registrado en el sistema con otro usuario Discord.")
                async with self.lock: del self.user_states[uid]
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
                await message.channel.send(f"✅ Código enviado a `{email}`.\nRevisa tu bandeja (y spam) y escríbelo aquí:")
            else:
                await message.channel.send("🔥 Error enviando el correo. El servicio de mail falló. Intenta más tarde.")
                logger.error(f"Mailjet error: {sent}")
                async with self.lock: del self.user_states[uid]

        # --- ETAPA 2: VALIDAR CÓDIGO ---
        elif stage == "awaiting_code":
            if hash_code(content) == state['code_hash']:
                async with self.lock:
                    self.user_states[uid]["stage"] = "selecting_career"
                
                # Lanzar UI de Facultad
                view = View()
                view.add_item(FacultySelect(self, uid))
                await message.channel.send("🎉 ¡Código correcto!\nSelecciona tu **Facultad** en el menú de abajo:", view=view)
            else:
                # Contador de intentos
                async with self.lock:
                    self.user_states[uid]["attempts"] += 1
                    att = self.user_states[uid]["attempts"]
                
                if att >= 3:
                    await message.channel.send("⛔ Demasiados intentos fallidos. Proceso cancelado.")
                    async with self.lock: del self.user_states[uid]
                else:
                    await message.channel.send(f"❌ Código incorrecto. Intento {att}/3.")

        # --- ETAPA 3: MINECRAFT (Final) ---
        elif stage == "awaiting_mc":
            if not validate_minecraft_username(content):
                await message.channel.send("❌ Nombre inválido. Solo letras (A-Z), números y guion bajo (_). Sin espacios.")
                return

            career = state.get("career_code", "EST")
            email = state['email']
            
            # 1. Guardar en Base de Datos (Prioridad Maxima)
            db_success = await db.update_or_insert_user(email, uid, content, career)
            
            if not db_success:
                await message.channel.send("💀 Error fatal guardando en la base de datos. Contacta a un admin.")
                return
            
            # 2. Gestionar Discord (Si falla, no importa tanto, ya está en la DB)
            discord_msg = ""
            guild = self.bot.get_guild(int(self.bot.config['GUILD_ID']))
            
            if guild:
                member = guild.get_member(uid)
                if not member:
                    try: member = await guild.fetch_member(uid)
                    except: pass
                
                if member:
                    logs = await self._safe_assign_roles(guild, member, career, content)
                    if logs: discord_msg = "\nNote: " + " ".join(logs)
                else:
                    discord_msg = "\n(No te encontré en el servidor para darte roles, pero ya estás en la whitelist)"
            
            # 3. Confirmación Final
            embed = discord.Embed(
                title="✅ ¡Verificación Exitosa!",
                description=f"Bienvenido/a, **{content}**.\nYa tienes acceso al servidor de Minecraft.",
                color=0x2ecc71
            )
            if discord_msg:
                embed.set_footer(text=discord_msg)
            
            await message.channel.send(embed=embed)
            
            # Limpiar estado
            async with self.lock: del self.user_states[uid]

async def setup(bot):
    await bot.add_cog(Verification(bot))