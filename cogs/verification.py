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
        
        # llenamos el select con las carreras de esa facultad
        options = []
        for name, code in careers.items():
            options.append(discord.SelectOption(label=name, description=f"Código: {code}", value=code))
        
        # discord solo aguanta 25 opciones, si hay mas rip
        super().__init__(placeholder="Busca tu Carrera...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        code = self.values[0]
        # guardamos el codigo en memoria
        async with self.cog.lock:
            if self.user_id in self.cog.user_states:
                self.cog.user_states[self.user_id]["career_code"] = code
                self.cog.user_states[self.user_id]["stage"] = "awaiting_mc"
        
        await interaction.response.send_message(
            f"✅ Elegiste: **{code}**\n\nAhora lo último: Escribe tu **Nick de Minecraft** (Tal cual es).", 
            ephemeral=True
        )
        self.view.stop() # matamos la vista para que no le den click de nuevo

# --- SELECTOR DE FACULTAD (Paso 1) ---
class FacultySelect(Select):
    def __init__(self, cog, user_id):
        self.cog = cog
        self.user_id = user_id
        # sacamos las llaves del diccionario 
        options = [discord.SelectOption(label=fac) for fac in FACULTIES.keys()]
        super().__init__(placeholder="¿De qué Facultad eres?...", min_values=1, max_values=1, options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        faculty = self.values[0]
        # creamos una nueva vista con las carreras de esa facultad
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
        # intentamos abrir MD, si tiene los DMs cerrados F
        try:
            embed = discord.Embed(title="Verificación PUCV", description="Escribe tu correo institucional **@mail.pucv.cl** para empezar.")
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("Revisa tus mensajes privados 👀", ephemeral=True)
            
            async with self.cog.lock:
                self.cog.user_states[interaction.user.id] = {
                    "stage": "awaiting_email", 
                    "attempts": 0,
                    "career_code": None
                }
        except discord.Forbidden:
            await interaction.response.send_message("❌ Abre tus DMs .", ephemeral=True)

# --- LOGICA PRINCIPAL ---
class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.user_states = {} # aqui guardamos el estado temporal del usuario

    @commands.Cog.listener()
    async def on_ready(self):
        # ponemos el boton en el canal si no esta
        cid = self.bot.config.get('VERIFICATION_CHANNEL_ID')
        if cid:
            ch = self.bot.get_channel(int(cid))
            if ch:
                # borramos el spam anterior
                async for msg in ch.history(limit=5):
                    if msg.author == self.bot.user: await msg.delete()
                await ch.send(
                    embed=discord.Embed(title="🔐 Sistema UniGuard", description="Verificación exclusiva para alumnos PUCV."),
                    view=VerificationView(self)
                )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignoramos bots y mensajes que no sean DM
        if message.author.bot or not isinstance(message.channel, discord.DMChannel): return
        
        uid = message.author.id
        content = message.content.strip()
        
        async with self.lock:
            state = self.user_states.get(uid)
        
        if not state: return # si no esta en proceso, chao

        if content.lower() == "cancelar":
            async with self.lock: del self.user_states[uid]
            await message.channel.send("❌ Proceso cancelado. Vuelve cuando quieras.")
            return

        stage = state['stage']

        # ETAPA 1: Validar correo y enviar codigo
        if stage == "awaiting_email":
            if not validate_university_email(content):
                await message.channel.send("❌ Eso no es un correo PUCV. Intenta de nuevo.")
                return
            
            code = generate_verification_code(6)
            async with self.lock:
                self.user_states[uid].update({
                    "email": content,
                    "code_hash": hash_code(code),
                    "stage": "awaiting_code"
                })
            
            # enviamos el mail, si mailjet falla estamos fritos
            await send_verification_email_async(content, code)
            await message.channel.send("✅ Código enviado. Revisa tu correo (spam incluido) y pégalo aquí:")

        # ETAPA 2: Validar el codigo
        elif stage == "awaiting_code":
            if hash_code(content) == state['code_hash']:
                async with self.lock:
                    self.user_states[uid]["stage"] = "selecting_career"
                
                # Lanzamos el selector de facultades
                view = View()
                view.add_item(FacultySelect(self, uid))
                await message.channel.send("✅ Código correcto. Selecciona tu Facultad:", view=view)
            else:
                await message.channel.send("❌ Código incorrecto. Copia bien.")

        # ETAPA 3: Minecraft (Llega aqui despues de los selectores)
        elif stage == "awaiting_mc":
            if not validate_minecraft_username(content):
                await message.channel.send("❌ Nombre inválido (3-16 caracteres, sin espacios ni eñes).")
                return

            career = state.get("career_code", "EST")
            email = state['email']
            
            # Guardamos todo en la DB
            success = await db.update_or_insert_user(email, uid, content, career)
            if not success:
                await message.channel.send("❌ Error guardando en la DB. Llama a un admin D:.")
                return
            
            # Asignamos roles y nick en Discord
            guild = self.bot.get_guild(int(self.bot.config['GUILD_ID']))
            if guild:
                member = guild.get_member(uid)
                if member:
                    # Nick: [INF] Juanito
                    try: await member.edit(nick=f"[{career}] {content}"[:32])
                    except: pass # si es admin no le puedo cambiar el nombre, F
                    
                    # Roles base
                    r_ver = guild.get_role(int(self.bot.config['ROLE_ID_VERIFIED']))
                    r_not = guild.get_role(int(self.bot.config['ROLE_ID_NOT_VERIFIED']))
                    if r_ver: await member.add_roles(r_ver)
                    if r_not: await member.remove_roles(r_not)
                    
                    # Rol de Carrera (si existe)
                    # logica inversa para encontrar el nombre de la carrera xd
                    career_name = None
                    for fac in FACULTIES.values():
                        for name, c_code in fac.items():
                            if c_code == career: career_name = name
                    
                    if career_name:
                        role_career = discord.utils.get(guild.roles, name=career_name)
                        if role_career: await member.add_roles(role_career)

            await message.channel.send(f"🎉 **¡Listo!**\nEres **{content}** de **{career}**.\nYa estás en la whitelist.")
            async with self.lock: del self.user_states[uid]

async def setup(bot):
    await bot.add_cog(Verification(bot))