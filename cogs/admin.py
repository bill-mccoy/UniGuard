import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
import logging
import asyncio
import os
from typing import List, Tuple, Optional
from datetime import datetime, timedelta

import db
from utils import validate_university_email, validate_minecraft_username

logger = logging.getLogger("cogs.admin")

# Configuración
PAGE_SIZE = 10 # Cantidad de usuarios por página

# -----------------------------
# Helpers & Formateo
# -----------------------------
def _safe_lower(s) -> str:
    try: return str(s or "").strip().lower()
    except: return ""

def _fmt_user_line(row) -> str:
    # Desempaquetamos la tupla de 6 elementos de la DB
    try:
        email, user_id, username, u_type, sponsor, real_name = row
    except ValueError:
        return "⚠️ Error de datos en fila"

    mc_display = f"🎮 `{username}`" if username else "—"
    
    if u_type == 'guest':
        # Formato para invitados
        return f"🤝 **{real_name or 'Invitado'}** ({mc_display})\n   ↳ ID: `{user_id}` | Padrino: `{sponsor}`"
    else:
        # Formato para alumnos
        return f"🎓 **Alumno** ({mc_display})\n   ↳ ID: `{user_id}` | 📧 `{email}`"

def _filter_rows(rows, query: str):
    q = _safe_lower(query)
    if not q: return rows
    
    filtered = []
    for row in rows:
        # Busqueda bruta en todos los campos convertidos a string
        full_text = " ".join([str(x) for x in row if x])
        if q in _safe_lower(full_text):
            filtered.append(row)
    return filtered

def _slice_page(rows, page: int):
    total = len(rows)
    max_page = max(0, (total - 1) // PAGE_SIZE)
    page = max(0, min(page, max_page))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    return rows[start:end], (page > 0), (end < total), page + 1, max_page + 1

# -----------------------------
# MODALES (Formularios de Entrada)
# -----------------------------

class SearchModal(Modal, title="🔎 Buscar Usuario"):
    query = TextInput(label="Término de búsqueda", placeholder="Nombre, ID, Email, Padrino...", required=False)
    
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        
    async def on_submit(self, interaction: discord.Interaction):
        self.cog.query = str(self.query.value or "").strip()
        self.cog.page = 0
        await self.cog.render_panel(interaction)

class AddGuestModal(Modal, title="🤝 Registrar Invitado"):
    sponsor_id = TextInput(label="ID del Padrino (Discord)", placeholder="Ej: 123456789", required=True, max_length=20)
    guest_id = TextInput(label="ID del Invitado (Discord)", placeholder="Ej: 987654321", required=True, max_length=20)
    guest_mc = TextInput(label="Minecraft (Java)", placeholder="NombreExacto", required=True, max_length=16)
    real_name = TextInput(label="Nombre Real", placeholder="Juan Pérez", required=True, max_length=100)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        # Validar IDs numéricos
        if not self.sponsor_id.value.isdigit() or not self.guest_id.value.isdigit():
            return await interaction.response.send_message("❌ Los IDs deben ser números.", ephemeral=True)

        ok, msg = await db.add_guest_user(
            int(self.guest_id.value),
            self.guest_mc.value,
            self.real_name.value,
            int(self.sponsor_id.value)
        )
        
        if ok:
            # Intentar dar rol y nick
            guild = interaction.guild
            if guild:
                member = guild.get_member(int(self.guest_id.value))
                if member:
                    try: await member.edit(nick=f"[INV] {self.guest_mc.value}"[:32])
                    except: pass
                    
                    rid = self.cog.bot.config.get('ROLE_ID_GUEST')
                    if rid:
                        r = guild.get_role(int(rid))
                        if r: await member.add_roles(r)
            
            await interaction.response.send_message(f"✅ {msg}", ephemeral=True)
            await self.cog.render_panel(interaction)
        else:
            await interaction.response.send_message(f"❌ Error: {msg}", ephemeral=True)

class AddStudentModal(Modal, title="🎓 Registrar Alumno Manual"):
    did = TextInput(label="Discord ID", required=True, max_length=20)
    email = TextInput(label="Email PUCV", placeholder="nombre@mail.pucv.cl", required=True)
    mc = TextInput(label="Minecraft", required=True, max_length=16)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction):
        if not validate_university_email(self.email.value):
            return await interaction.response.send_message("❌ Email inválido.", ephemeral=True)

        ok = await db.update_or_insert_user(self.email.value, int(self.did.value), self.mc.value)
        if ok:
            # Intentar dar rol verificado
            guild = interaction.guild
            if guild:
                mem = guild.get_member(int(self.did.value))
                if mem:
                    try: await mem.edit(nick=f"[EST] {self.mc.value}"[:32])
                    except: pass
                    rid = self.cog.bot.config.get('ROLE_ID_VERIFIED')
                    if rid:
                        r = guild.get_role(int(rid))
                        if r: await mem.add_roles(r)

            await interaction.response.send_message("✅ Alumno agregado manual.", ephemeral=True)
            await self.cog.render_panel(interaction)
        else:
            await interaction.response.send_message("❌ Error guardando en DB.", ephemeral=True)

class EditMCModal(Modal, title="✏️ Editar Minecraft"):
    new_name = TextInput(label="Nuevo Nombre Minecraft", required=True, max_length=16)

    def __init__(self, cog, uid):
        super().__init__()
        self.cog = cog
        self.uid = uid

    async def on_submit(self, interaction):
        # Actualizamos solo el usuario, manteniendo el resto (email=None asume no cambio)
        # OJO: DB update_or_insert es inteligente
        await db.update_or_insert_user(None, int(self.uid), self.new_name.value)
        await interaction.response.send_message("✅ Nombre actualizado.", ephemeral=True)
        await self.cog.render_panel(interaction)

# -----------------------------
# VISTAS (UI del Panel)
# -----------------------------

class SelectUser(Select):
    def __init__(self, cog, rows):
        options = []
        for row in rows:
            email, uid, user, u_type, sponsor, r_name = row
            
            label = user or "Sin Nombre"
            if u_type == 'guest':
                emoji = "🤝"
                desc = f"Inv: {r_name}"[:100]
            else:
                emoji = "🎓"
                desc = f"{email}"[:100]
                
            options.append(discord.SelectOption(label=label, description=desc, value=str(uid), emoji=emoji))
            
        if not options:
            options.append(discord.SelectOption(label="Lista vacía", value="none", default=True))

        super().__init__(placeholder="Selecciona un usuario para gestionar...", options=options, min_values=1, max_values=1)
        self.cog = cog

    async def callback(self, interaction):
        if self.values[0] == "none": return
        self.cog.selected_uid = str(self.values[0])
        self.cog.mode = "detail"
        await self.cog.render_panel(interaction)

class ListView(View):
    def __init__(self, cog, rows, has_prev, has_next):
        super().__init__(timeout=None)
        self.cog = cog
        
        # 1. Dropdown de Seleccion
        self.add_item(SelectUser(cog, rows))

        # 2. Navegacion
        b_prev = Button(label="◀", style=discord.ButtonStyle.secondary, disabled=not has_prev, row=1)
        b_prev.callback = self.prev_cb
        self.add_item(b_prev)

        b_reload = Button(label="🔄 Refrescar", style=discord.ButtonStyle.secondary, row=1)
        b_reload.callback = self.reload_cb
        self.add_item(b_reload)

        b_next = Button(label="▶", style=discord.ButtonStyle.secondary, disabled=not has_next, row=1)
        b_next.callback = self.next_cb
        self.add_item(b_next)
        
        # 3. Herramientas
        b_search = Button(label="🔎 Buscar", style=discord.ButtonStyle.primary, row=1)
        b_search.callback = self.search_cb
        self.add_item(b_search)

        b_clear = Button(label="🧹 Limpiar Filtro", style=discord.ButtonStyle.secondary, row=1)
        b_clear.callback = self.clear_cb
        self.add_item(b_clear)

        # 4. Acciones CRUD
        b_add_s = Button(label="🎓 +Alumno", style=discord.ButtonStyle.success, row=2)
        b_add_s.callback = self.add_student_cb
        self.add_item(b_add_s)

        b_add_g = Button(label="🤝 +Invitado", style=discord.ButtonStyle.success, row=2)
        b_add_g.callback = self.add_guest_cb
        self.add_item(b_add_g)

    # Callbacks
    async def prev_cb(self, interaction):
        self.cog.page -= 1
        await self.cog.render_panel(interaction)
    async def next_cb(self, interaction):
        self.cog.page += 1
        await self.cog.render_panel(interaction)
    async def reload_cb(self, interaction):
        await self.cog.render_panel(interaction)
    async def search_cb(self, interaction):
        await interaction.response.send_modal(SearchModal(self.cog))
    async def clear_cb(self, interaction):
        self.cog.query = ""
        self.cog.page = 0
        await self.cog.render_panel(interaction)
    async def add_student_cb(self, interaction):
        await interaction.response.send_modal(AddStudentModal(self.cog))
    async def add_guest_cb(self, interaction):
        await interaction.response.send_modal(AddGuestModal(self.cog))

class DetailView(View):
    def __init__(self, cog, uid):
        super().__init__(timeout=None)
        self.cog = cog
        self.uid = uid

    @discord.ui.button(label="⬅ Volver a la Lista", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        self.cog.mode = "list"
        self.cog.selected_uid = None
        await self.cog.render_panel(interaction)

    @discord.ui.button(label="✏️ Editar Minecraft", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction, button):
        await interaction.response.send_modal(EditMCModal(self.cog, self.uid))

    @discord.ui.button(label="⛔ Suspender / Reactivar", style=discord.ButtonStyle.danger, row=1)
    async def suspend(self, interaction, button):
        flag = await db.get_whitelist_flag(self.uid)
        new_val = not (flag == 1)
        await db.set_whitelist_flag(self.uid, new_val)
        
        msg = "🔓 Usuario Reactivado (Puede entrar)" if new_val else "⛔ Usuario Suspendido (Whitelist OFF)"
        await interaction.response.send_message(msg, ephemeral=True)
        await self.cog.render_panel(interaction)

    @discord.ui.button(label="🗑 ELIMINAR BASE DE DATOS", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction, button):
        # Confirmacion rapida en modal o directo
        await db.full_user_delete(self.uid)
        
        # Intentar quitar roles
        guild = interaction.guild
        if guild:
            mem = guild.get_member(int(self.uid))
            if mem:
                # Quitar verificado y guest
                r1 = guild.get_role(int(self.cog.bot.config.get('ROLE_ID_VERIFIED', 0)))
                r2 = guild.get_role(int(self.cog.bot.config.get('ROLE_ID_GUEST', 0)))
                if r1: await mem.remove_roles(r1)
                if r2: await mem.remove_roles(r2)

        await interaction.response.send_message("🗑 Usuario eliminado permanentemente.", ephemeral=True)
        self.cog.mode = "list"
        self.cog.selected_uid = None
        await self.cog.render_panel(interaction)

# -----------------------------
# COG PRINCIPAL
# -----------------------------
class AdminPanelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Estado en memoria RAM (se borra al reiniciar, pero se regenera solo)
        self.query = ""
        self.page = 0
        self.mode = "list" # list | detail
        self.selected_uid = None
        self._msg = None # Referencia al mensaje del panel

    async def cog_load(self):
        self.bot.loop.create_task(self.init_panel())

    async def init_panel(self):
        """Borra todo lo viejo y crea un panel nuevo al iniciar"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5) 
        
        cid = self.bot.config.get("ADMIN_CHANNEL_ID")
        if not cid: return

        channel = self.bot.get_channel(int(cid))
        if not channel: return

        # 1. Limpieza: Borrar mensajes anteriores del bot para evitar confusion
        try:
            async for msg in channel.history(limit=10):
                if msg.author == self.bot.user:
                    await msg.delete()
        except: pass

        # 2. Mensaje nuevo
        self._msg = await channel.send("⏳ **Iniciando Sistema UniGuard...**")
        
        # 3. Renderizar
        await self.render_panel()

    async def render_panel(self, interaction=None):
        """Dibuja el panel segun el estado actual"""
        # Asegurar DB
        try:
            rows = await db.list_verified_players()
        except Exception as e:
            logger.error(f"DB Error: {e}")
            return

        # --- LOGICA DE DETALLE ---
        if self.mode == "detail" and self.selected_uid:
            rec = next((r for r in rows if str(r[1]) == self.selected_uid), None)
            
            if not rec:
                # Si el usuario no existe (se borro), volver a lista
                self.mode = "list"
                await self.render_panel(interaction)
                return

            email, uid, user, u_type, sponsor, r_name = rec
            
            # Embed de Detalle
            color = 0x3498db if u_type == 'student' else 0xf1c40f
            embed = discord.Embed(title=f"👤 Gestión de Usuario: {user}", color=color)
            
            embed.add_field(name="Minecraft", value=f"`{user}`", inline=True)
            embed.add_field(name="Discord ID", value=f"`{uid}`", inline=True)
            
            if u_type == 'guest':
                embed.add_field(name="Tipo", value="🤝 Invitado", inline=False)
                embed.add_field(name="Nombre Real", value=r_name, inline=True)
                embed.add_field(name="Padrino ID", value=f"`{sponsor}`", inline=True)
            else:
                embed.add_field(name="Tipo", value="🎓 Alumno Regular", inline=False)
                embed.add_field(name="Email", value=f"`{email}`", inline=False)
            
            # Estado Whitelist
            wl_stat = await db.get_whitelist_flag(uid)
            status_txt = "✅ **ACTIVO** (Puede entrar)" if wl_stat == 1 else "⛔ **SUSPENDIDO** (Bloqueado)"
            embed.add_field(name="Estado Servidor", value=status_txt, inline=False)

            view = DetailView(self, uid)
            
            if interaction:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.edit_original_response(embed=embed, view=view)
            elif self._msg:
                await self._msg.edit(content=None, embed=embed, view=view)
            return

        # --- LOGICA DE LISTA ---
        filtered = _filter_rows(rows, self.query)
        total_items = len(filtered)
        
        # Paginacion Matematica
        max_page = max(0, (total_items - 1) // PAGE_SIZE)
        self.page = max(0, min(self.page, max_page))
        
        page_rows, has_prev, has_next, cur_p, tot_p = _slice_page(filtered, self.page)
        
        # Stats para el header
        global_total = len(rows)
        global_guests = sum(1 for r in rows if r[3] == 'guest')
        
        embed = discord.Embed(title="🛡️ UniGuard - Panel de Administración", color=0x2ecc71)
        
        if self.query:
            embed.description = f"🔎 **Filtro:** `{self.query}`\nResultados: {total_items}"
        else:
            embed.description = f"👥 **Total:** {global_total} | 🎓 **Alumnos:** {global_total - global_guests} | 🤝 **Invitados:** {global_guests}"

        # Renderizar filas
        lines = [_fmt_user_line(r) for r in page_rows]
        list_text = "\n".join(lines) if lines else "📭 No hay usuarios aquí."
        
        embed.add_field(name=f"Usuarios (Página {cur_p}/{tot_p})", value=list_text, inline=False)
        
        view = ListView(self, page_rows, has_prev, has_next)

        if interaction:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                await interaction.edit_original_response(embed=embed, view=view)
        elif self._msg:
            await self._msg.edit(content=None, embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(AdminPanelCog(bot))