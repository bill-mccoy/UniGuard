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

# --- SELECTOR DE CARRERA (Paso 2) ---
class CareerSelect(Select):
    def __init__(self, faculty_name, cog, user_id):
        self.cog = cog
        self.user_id = user_id
        careers = FACULTIES.get(faculty_name, {})
        
        options = []
        for name, code in careers.items():
            options.append(discord.SelectOption(label=name, description=f"Código: {code}", value=code))
        
        super().__init__(placeholder="Busca tu Carrera...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        code = self.values[0]
        async with self.cog.lock:
            if self.user_id in self.cog.user_states:
                self.cog.user_states[self.user_id]["career_code"] = code
                self.cog.user_states[self.user_id]["stage"] = "awaiting_mc"
        
        await interaction.response.send_message(
            f"✅ Elegiste: **{code}**\n\nAhora lo último: Escribe tu **Nombre de Minecraft** (Java Edition).", 
            ephemeral=True
        )
        self.view.stop()

# --- SELECTOR DE FACULTAD (Paso 1) ---
class FacultySelect(Select):
    def __init__(self, cog, user_id):
        self.cog = cog
        self.user_id = user_id
        options = [discord.SelectOption(label=fac) for fac in FACULTIES.keys()]
        super().__init__(placeholder="¿De qué Facultad eres?...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        faculty = self.values[0]
        view = View()
        view.add_item(CareerSelect(faculty, self.cog, self.user_id))
        await interaction.response.send_message(f"Facultad: **{faculty}**. Busca tu carrera:", view=view, ephemeral=True)

# --- BOTON DE INICIO ---
class VerificationView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🎓 Comenzar Verificación", style=discord.ButtonStyle.success, custom_id="verify_start")
    async def verify(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        
        # 1. CHECKEO DE SEGURIDAD: ¿Ya está verificado?
        is_verified = await db.check_existing_user(user_id)
        if is_verified:
            await interaction.response.send_message("❌ Ya estás verificado en el sistema. Si necesitas ayuda, abre ticket.", ephemeral=True)
            return

        # Si tiene rol de verificado en discord pero no en la DB (raro, pero pasa), le avisamos
        guild = interaction.guild
        if guild:
            member = guild.get_member(user_id)
            role_ver_id = self.cog.bot.config.get('ROLE_ID_VERIFIED')
            if member and role_ver_id:
                has_role = discord.utils.get(member.roles, id=int(role_ver_id))
                if has_role:
                    await interaction.response.send_message("❌ Ya tienes el rol de alumno.", ephemeral=True)
                    return

        # Si pasa los filtros, empezamos
        try:
            embed = discord.Embed(title="Verificación PUCV", description="Escribe tu correo institucional **@mail.pucv.cl** para empezar.")
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("Revisa tus mensajes privados 👀", ephemeral=True)
            
            async with self.cog.lock:
                self.cog.user_states[user_id] = {
                    "stage": "awaiting_email", 
                    "attempts": 0,
                    "career_code": None
                }
        except discord.Forbidden:
            await interaction.response.send_message("❌ Abre tus DMs hermano, no soy adivino.", ephemeral=True)

# --- LOGICA PRINCIPAL ---
class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.user_states = {}

    @commands.Cog.listener()
    async def on_ready(self):
        cid = self.bot.config.get('VERIFICATION_CHANNEL_ID')
        if cid:
            ch = self.bot.get_channel(int(cid))
            if ch:
                async for msg in ch.history(limit=5):
                    if msg.author == self.bot.user: await msg.delete()
                await ch.send(
                    embed=discord.Embed(title="🔐 Sistema UniGuard", description="Verificación exclusiva para alumnos PUCV."),
                    view=VerificationView(self)
                )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not isinstance(message.channel, discord.DMChannel): return
        
        uid = message.author.id
        content = message.content.strip()
        
        async with self.lock:
            state = self.user_states.get(uid)
        
        if not state: return 

        if content.lower() == "cancelar":
            async with self.lock: del self.user_states[uid]
            await message.channel.send("❌ Cancelado.")
            return

        stage = state['stage']

        # ETAPA 1: EMAIL
        if stage == "awaiting_email":
            email = content.lower()
            if not validate_university_email(email):
                await message.channel.send("❌ Eso no es un correo PUCV válido.")
                return
            
            # 2. CHECKEO DE SEGURIDAD: ¿Correo usado?
            # Verifica si el correo ya existe en la base de datos asociado a OTRO usuario
            email_exists = await db.check_existing_email(email)
            if email_exists:
                await message.channel.send("❌ Ese correo ya está registrado por otro usuario. Si es un error, contacta a soporte.")
                async with self.lock: del self.user_states[uid]
                return
            
            code = generate_verification_code(6)
            async with self.lock:
                self.user_states[uid].update({
                    "email": email,
                    "code_hash": hash_code(code),
                    "stage": "awaiting_code"
                })
            
            sent = await send_verification_email_async(email, code)
            if sent.get('success'):
                await message.channel.send("✅ Código enviado. Revisa tu correo y pégalo aquí:")
            else:
                await message.channel.send("❌ Error enviando correo. Intenta más tarde.")

        # ETAPA 2: CODIGO
        elif stage == "awaiting_code":
            if hash_code(content) == state['code_hash']:
                async with self.lock:
                    self.user_states[uid]["stage"] = "selecting_career"
                
                view = View()
                view.add_item(FacultySelect(self, uid))
                await message.channel.send("✅ Correcto. Selecciona tu Facultad:", view=view)
            else:
                await message.channel.send("❌ Código incorrecto.")

        # ETAPA 3: MINECRAFT
        elif stage == "awaiting_mc":
            if not validate_minecraft_username(content):
                await message.channel.send("❌ Nombre inválido (solo letras, números y _).")
                return

            career = state.get("career_code", "EST")
            email = state['email']
            
            # GUARDAR EN DB
            success = await db.update_or_insert_user(email, uid, content, career)
            if not success:
                await message.channel.send("❌ Error critico en la DB. Avisa a un admin.")
                return
            
            # ASIGNAR ROLES EN DISCORD (Con manejo de errores robusto)
            try:
                guild = self.bot.get_guild(int(self.bot.config['GUILD_ID']))
                if guild:
                    member = guild.get_member(uid)
                    if not member:
                        # A veces el cache falla, intentamos fetch
                        member = await guild.fetch_member(uid)

                    if member:
                        # 1. Nickname
                        try: await member.edit(nick=f"[{career}] {content}"[:32])
                        except discord.Forbidden: logger.warning(f"No pude cambiar nick a {uid}")
                        
                        # 2. Roles Base
                        role_ver_id = int(self.bot.config.get('ROLE_ID_VERIFIED', 0))
                        role_not_id = int(self.bot.config.get('ROLE_ID_NOT_VERIFIED', 0))
                        
                        r_ver = guild.get_role(role_ver_id)
                        r_not = guild.get_role(role_not_id)
                        
                        if r_ver: 
                            await member.add_roles(r_ver)
                        else:
                            logger.error(f"ROL VERIFICADO NO ENCONTRADO ID: {role_ver_id}")

                        if r_not: 
                            await member.remove_roles(r_not)
                        
                        # 3. Rol de Carrera
                        career_name = None
                        for fac in FACULTIES.values():
                            for name, c_code in fac.items():
                                if c_code == career: career_name = name
                        
                        if career_name:
                            role_career = discord.utils.get(guild.roles, name=career_name)
                            if role_career:
                                await member.add_roles(role_career)
                            else:
                                logger.warning(f"No encontre el rol de carrera: {career_name}")
            except Exception as e:
                logger.error(f"Error asignando roles a {uid}: {e}")
                await message.channel.send("⚠️ Te verifiqué en la DB, pero hubo un error dándote los roles en Discord. Avisa a un admin.")

            await message.channel.send(f"🎉 **¡Listo!**\nEres **{content}** de **{career}**.\nYa estás en la whitelist.")
            async with self.lock: del self.user_states[uid]

async def setup(bot):
    await bot.add_cog(Verification(bot))