import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
import logging
import asyncio
import os
from typing import List, Tuple, Optional, Union

import db
from utils import validate_university_email, validate_minecraft_username

logger = logging.getLogger("cogs.admin")

# --- CONFIGURACIÓN ---
PAGE_SIZE = 8

# -----------------------------
# HELPERS VISUALES
# -----------------------------
def _safe_lower(s) -> str:
    return str(s or "").strip().lower()

def _fmt_user_line(row) -> str:
    try:
        email, user_id, username, u_type, sponsor, real_name = row
    except ValueError:
        return "⚠️ Error en estructura de datos"

    username_display = f"`{username}`" if username else "—"
    
    if u_type == 'guest':
        return f"🤝 **{real_name or 'Invitado'}** ({username_display})\n   ↳ ID: `{user_id}` | Padrino: `{sponsor}`"
    else:
        return f"🎓 **Alumno** ({username_display})\n   ↳ ID: `{user_id}` | 📧 `{email}`"

def _filter_rows(rows, query: str):
    q = _safe_lower(query)
    if not q: return rows
    
    filtered = []
    for row in rows:
        # Convierte toda la fila a string y busca coincidencias
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
# MODALES (Formularios)
# -----------------------------

class SearchModal(Modal, title="🔎 Buscar Usuario"):
    query = TextInput(label="Término", placeholder="ID, Email, Nombre, Padrino...", required=False)
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
    async def on_submit(self, interaction: discord.Interaction):
        self.cog.query = str(self.query.value or "").strip()
        self.cog.page = 0
        await self.cog.render_panel(interaction)

class AddGuestModal(Modal, title="🤝 Registrar Invitado"):
    sponsor_id = TextInput(label="ID Padrino (Discord)", placeholder="Ej: 123456789", required=True, max_length=20)
    guest_id = TextInput(label="ID Invitado (Discord)", placeholder="Ej: 987654321", required=True, max_length=20)
    guest_mc = TextInput(label="Minecraft (Java)", placeholder="NombreExacto", required=True, max_length=16)
    real_name = TextInput(label="Nombre Real", placeholder="Juan Pérez", required=True, max_length=100)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not self.sponsor_id.value.isdigit() or not self.guest_id.value.isdigit():
            return await interaction.response.send_message("❌ Los IDs deben ser números.", ephemeral=True)

        target_id = int(self.guest_id.value)
        mc_name = self.guest_mc.value.strip()

        # 1. Base de Datos
        ok, msg = await db.add_guest_user(
            target_id, mc_name, self.real_name.value, int(self.sponsor_id.value)
        )
        
        if ok:
            # 2. Gestión de Discord (Centralizada)
            discord_log = await self.cog.manage_discord_user(
                guild=interaction.guild,
                user_id=target_id,
                action="add_guest",
                mc_name=mc_name
            )
            await interaction.response.send_message(f"✅ {msg}\n{discord_log}", ephemeral=True)
            await self.cog.render_panel(interaction)
        else:
            await interaction.response.send_message(f"❌ Error DB: {msg}", ephemeral=True)

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

        target_id = int(self.did.value)
        mc_name = self.mc.value.strip()

        # 1. Base de Datos
        ok = await db.update_or_insert_user(self.email.value, target_id, mc_name)
        
        if ok:
            # 2. Gestión de Discord
            discord_log = await self.cog.manage_discord_user(
                guild=interaction.guild,
                user_id=target_id,
                action="add_student",
                mc_name=mc_name
            )
            await interaction.response.send_message(f"✅ Alumno agregado.\n{discord_log}", ephemeral=True)
            await self.cog.render_panel(interaction)
        else:
            await interaction.response.send_message("❌ Error guardando en DB.", ephemeral=True)

class EditMCModal(Modal, title="✏️ Editar Minecraft"):
    new_name = TextInput(label="Nuevo Nombre", required=True, max_length=16)

    def __init__(self, cog, uid):
        super().__init__()
        self.cog = cog
        self.uid = uid

    async def on_submit(self, interaction):
        # Actualiza solo el nombre, mantiene lo demás
        await db.update_or_insert_user(None, int(self.uid), self.new_name.value)
        
        # Intentar actualizar nick en discord
        log = await self.cog.manage_discord_user(
            guild=interaction.guild,
            user_id=int(self.uid),
            action="update_nick",
            mc_name=self.new_name.value
        )
        
        await interaction.response.send_message(f"✅ Nombre actualizado.\n{log}", ephemeral=True)
        await self.cog.render_panel(interaction)

# -----------------------------
# VISTAS (Botones)
# -----------------------------

class SelectUser(Select):
    def __init__(self, cog, rows):
        options = []
        for row in rows:
            try:
                email, uid, user, u_type, sponsor, r_name = row
            except: continue
            
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
        self.add_item(SelectUser(cog, rows))

        # Navegación
        self.add_item(Button(label="◀", style=discord.ButtonStyle.secondary, disabled=not has_prev, row=1, custom_id="prev_btn")).children[-1].callback = self.prev_cb
        self.add_item(Button(label="🔄 Refrescar", style=discord.ButtonStyle.secondary, row=1, custom_id="reload_btn")).children[-1].callback = self.reload_cb
        self.add_item(Button(label="▶", style=discord.ButtonStyle.secondary, disabled=not has_next, row=1, custom_id="next_btn")).children[-1].callback = self.next_cb
        
        # Herramientas
        self.add_item(Button(label="🔎 Buscar", style=discord.ButtonStyle.primary, row=1, custom_id="search_btn")).children[-1].callback = self.search_cb
        self.add_item(Button(label="🧹 Limpiar", style=discord.ButtonStyle.secondary, row=1, custom_id="clear_btn")).children[-1].callback = self.clear_cb

        # Acciones
        self.add_item(Button(label="🎓 +Alumno", style=discord.ButtonStyle.success, row=2, custom_id="add_s_btn")).children[-1].callback = self.add_student_cb
        self.add_item(Button(label="🤝 +Invitado", style=discord.ButtonStyle.success, row=2, custom_id="add_g_btn")).children[-1].callback = self.add_guest_cb

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

    @discord.ui.button(label="⬅ Volver", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        self.cog.mode = "list"
        self.cog.selected_uid = None
        await self.cog.render_panel(interaction)

    @discord.ui.button(label="✏️ Editar MC", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction, button):
        await interaction.response.send_modal(EditMCModal(self.cog, self.uid))

    @discord.ui.button(label="⛔ Suspender/Activar", style=discord.ButtonStyle.danger, row=1)
    async def suspend(self, interaction, button):
        flag = await db.get_whitelist_flag(self.uid)
        new_val = not (flag == 1)
        await db.set_whitelist_flag(self.uid, new_val)
        msg = "🔓 Activado" if new_val else "⛔ Suspendido"
        await interaction.response.send_message(msg, ephemeral=True)
        await self.cog.render_panel(interaction)

    @discord.ui.button(label="🗑 ELIMINAR TOTALMENTE", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction, button):
        # 1. DB Delete
        await db.full_user_delete(self.uid)
        
        # 2. Discord Cleanup
        log = await self.cog.manage_discord_user(
            guild=interaction.guild,
            user_id=int(self.uid),
            action="delete"
        )
        
        await interaction.response.send_message(f"🗑 Usuario eliminado.\n{log}", ephemeral=True)
        self.cog.mode = "list"
        self.cog.selected_uid = None
        await self.cog.render_panel(interaction)

# -----------------------------
# COG PRINCIPAL
# -----------------------------
class AdminPanelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.query = ""
        self.page = 0
        self.mode = "list" 
        self.selected_uid = None
        self._msg = None

    async def cog_load(self):
        self.bot.loop.create_task(self.init_panel())

    # --- FUNCIÓN MAESTRA DE DISCORD ---
    async def manage_discord_user(self, guild: discord.Guild, user_id: int, action: str, mc_name: str = None) -> str:
        """
        Maneja roles y nicks de forma centralizada y segura.
        action: 'add_student', 'add_guest', 'delete', 'update_nick'
        """
        if not guild: return "⚠️ Error: No hay servidor de Discord."
        
        # 1. Obtener Miembro
        member = guild.get_member(user_id)
        if not member:
            try: member = await guild.fetch_member(user_id)
            except: return "⚠️ Usuario no está en el servidor de Discord."

        log = []
        
        # IDs de Roles desde Config
        rid_verified = int(self.bot.config.get('ROLE_ID_VERIFIED', 0))
        rid_not_ver = int(self.bot.config.get('ROLE_ID_NOT_VERIFIED', 0))
        rid_guest = int(self.bot.config.get('ROLE_ID_GUEST', 0))

        # Helper para obtener rol por ID o Nombre (Fallback)
        def get_role_smart(rid, names):
            role = guild.get_role(rid)
            if not role:
                for n in names:
                    role = discord.utils.get(guild.roles, name=n)
                    if role: break
            return role

        # LOGICA SEGUN ACCION
        try:
            # --- BORRAR USUARIO ---
            if action == "delete":
                # Quitar roles de privilegio
                r_ver = get_role_smart(rid_verified, ["Alumno", "Verificado"])
                r_guest = get_role_smart(rid_guest, ["Invitado", "Apadrinado", "🤝 Invitado"])
                
                if r_ver and r_ver in member.roles: await member.remove_roles(r_ver)
                if r_guest and r_guest in member.roles: await member.remove_roles(r_guest)
                
                # Devolver rol no verificado
                r_not = get_role_smart(rid_not_ver, ["No Verificado"])
                if r_not: await member.add_roles(r_not)
                log.append("Roles retirados.")

            # --- AGREGAR ALUMNO ---
            elif action == "add_student":
                # Nickname
                try: await member.edit(nick=f"[EST] {mc_name}"[:32])
                except: log.append("(No pude cambiar nick)")
                
                # Roles
                r_ver = get_role_smart(rid_verified, ["Alumno", "Verificado"])
                r_not = get_role_smart(rid_not_ver, ["No Verificado"])
                
                if r_ver: 
                    await member.add_roles(r_ver)
                    log.append("Rol Alumno asignado.")
                else: 
                    log.append("⚠️ ERROR: No encontré rol Alumno.")
                
                if r_not: await member.remove_roles(r_not)

            # --- AGREGAR INVITADO ---
            elif action == "add_guest":
                # Nickname
                try: await member.edit(nick=f"[INV] {mc_name}"[:32])
                except: log.append("(No pude cambiar nick)")
                
                # Roles
                r_guest = get_role_smart(rid_guest, ["Invitado", "Apadrinado", "🤝 Invitado"])
                r_not = get_role_smart(rid_not_ver, ["No Verificado"])
                
                if r_guest: 
                    await member.add_roles(r_guest)
                    log.append(f"Rol Invitado ({r_guest.name}) asignado.")
                else: 
                    log.append(f"⚠️ ERROR: No encontré rol Invitado (ID buscado: {rid_guest}).")
                
                if r_not: await member.remove_roles(r_not)

            # --- ACTUALIZAR NICK ---
            elif action == "update_nick":
                # Detectar prefijo actual o poner uno por defecto
                curr_nick = member.display_name
                prefix = "[EST]"
                if "[INV]" in curr_nick or "[Ap]" in curr_nick: prefix = "[INV]"
                
                try: await member.edit(nick=f"{prefix} {mc_name}"[:32])
                except: log.append("(No pude cambiar nick)")

        except discord.Forbidden:
            return "⚠️ Error de Permisos: El bot no tiene jerarquía suficiente."
        except Exception as e:
            return f"⚠️ Error desconocido: {e}"

        return " ".join(log)

    async def init_panel(self):
        """Reinicia el panel visual"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5) 
        
        cid = self.bot.config.get("ADMIN_CHANNEL_ID")
        if not cid: return

        channel = self.bot.get_channel(int(cid))
        if not channel: return

        try:
            async for msg in channel.history(limit=10):
                if msg.author == self.bot.user:
                    await msg.delete()
        except: pass

        self._msg = await channel.send("⏳ **Cargando Panel UniGuard...**")
        await self.render_panel()

    async def render_panel(self, interaction=None):
        try:
            rows = await db.list_verified_players()
        except Exception as e:
            logger.error(f"DB Error: {e}")
            return

        if self.mode == "detail" and self.selected_uid:
            rec = next((r for r in rows if str(r[1]) == self.selected_uid), None)
            if not rec:
                self.mode = "list"
                await self.render_panel(interaction)
                return

            email, uid, user, u_type, sponsor, r_name = rec
            
            embed = discord.Embed(title=f"👤 Gestión: {user}", color=0xe67e22)
            embed.add_field(name="ID Discord", value=f"`{uid}`")
            embed.add_field(name="Tipo", value="🎓 Alumno" if u_type == 'student' else "🤝 Invitado")
            
            if u_type == 'guest':
                embed.add_field(name="Padrino", value=f"`{sponsor}`")
                embed.add_field(name="Real Name", value=r_name)
            else:
                embed.add_field(name="Email", value=email)
            
            wl = await db.get_whitelist_flag(uid)
            embed.add_field(name="Whitelist", value="✅ ON" if wl == 1 else "⛔ OFF", inline=False)

            view = DetailView(self, uid)
            if interaction:
                if not interaction.response.is_done(): await interaction.response.edit_message(embed=embed, view=view)
                else: await interaction.edit_original_response(embed=embed, view=view)
            elif self._msg: await self._msg.edit(content=None, embed=embed, view=view)
            return

        # List Mode
        filtered = _filter_rows(rows, self.query)
        
        # Paginacion
        max_p = max(0, (len(filtered) - 1) // PAGE_SIZE)
        self.page = max(0, min(self.page, max_p))
        page_rows, has_prev, has_next, cur_p, tot_p = _slice_page(filtered, self.page)
        
        # Stats
        tot = len(rows)
        gst = sum(1 for r in rows if r[3] == 'guest')
        
        embed = discord.Embed(title="🛡️ UniGuard Admin", color=0x2ecc71)
        if self.query: embed.description = f"🔎 `{self.query}` ({len(filtered)})"
        else: embed.description = f"👥 Total: {tot} | 🎓 Alumnos: {tot - gst} | 🤝 Invitados: {gst}"

        lines = [_fmt_user_line(r) for r in page_rows]
        embed.add_field(name=f"Lista ({cur_p}/{tot_p})", value="\n".join(lines) or "Vacío", inline=False)
        
        view = ListView(self, page_rows, has_prev, has_next)

        if interaction:
            if not interaction.response.is_done(): await interaction.response.edit_message(embed=embed, view=view)
            else: await interaction.edit_original_response(embed=embed, view=view)
        elif self._msg: await self._msg.edit(content=None, embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(AdminPanelCog(bot))