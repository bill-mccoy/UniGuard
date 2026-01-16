import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput, button
import logging
import asyncio
import os
import json
import threading
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from discord.utils import escape_markdown

import db
from utils import validate_university_email, validate_minecraft_username

logger = logging.getLogger("cogs.admin")

# config basica para que esto no explote
PANEL_STATE_FILE = "admin_panel_state.json"
PAGE_SIZE = 10
HISTORY_MAX = 50
_save_lock = threading.Lock()

# -----------------------------
# Helpers 
# -----------------------------

def _safe_lower(s) -> str:
    try: return str(s or "").strip().lower()
    except: return ""

def _count_stats(rows) -> Tuple[int, int, int]:
    # cuenta rapida: total, verificados (tienen user de mc) y pendientes
    # ahora tambien podriamos contar invitados pero meh, dejemoslo simple
    try:
        total = len(rows)
        # en la query nueva: email=0, id=1, user=2, type=3...
        verified = sum(1 for r in rows if r[2]) 
        pending = sum(1 for r in rows if r[0] and not r[2] and r[3] == 'student')
        return total, verified, pending
    except Exception as e:
        return 0, 0, 0

def _filter_rows(rows, query: str):
    q = _safe_lower(query)
    if not q: return rows
        
    filtered = []
    for row in rows:
        try:
            # desempaquetamos la tupla de 6 elementos (la nueva estructura de la db)
            email, user_id, username, u_type, sponsor, r_name = row
            
            # buscamos texto en cualquier lado posible
            if (q in _safe_lower(email) or 
                q in _safe_lower(user_id) or 
                (username and q in _safe_lower(username)) or
                (r_name and q in _safe_lower(r_name))):
                filtered.append(row)
        except Exception:
            pass # si falla una fila, la ignoramos y seguimos con la vida
    return filtered

def _slice_page(rows, page: int):
    # matematica basica para cortar la lista en paginas
    total = len(rows)
    max_page = max(0, (total - 1) // PAGE_SIZE)
    page = max(0, min(page, max_page))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    return rows[start:end], (page > 0), (end < total), page + 1, max_page + 1

def _fmt_user_line(email, user_id, username, u_type, sponsor, real_name) -> str:
    # aqui formateamos como se ve cada linea en la lista
    username_display = f"`{username}`" if username else "—"
    
    # iconitos para diferenciar la plebe
    prefix = "🎓" if u_type == 'student' else "🤝"
    
    line = f"- {prefix} {username_display} • ID: {user_id}"
    
    if u_type == 'guest':
        # si es invitado mostramos su nombre real y quien lo trajo
        line += f"\n   ↳ 👤 {real_name or 'Sin Nombre'} | Padrino: `{sponsor}`"
    else:
        # si es alumno mostramos su correo
        email_display = f"`{email}`" if email else "—"
        line += f" | 📧 {email_display}"
        
    return line

def _chunk_history(history: List[str], limit: int = 10) -> List[str]:
    return history[-limit:][::-1]

# --- Manejo de Estado (Guardar JSON) ---
# esto es para que si reinicias el bot, el panel recuerde en que pagina estaba
def _load_panel_state() -> dict:
    if os.path.exists(PANEL_STATE_FILE):
        try:
            with open(PANEL_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def _save_panel_state(state: dict):
    with _save_lock:
        try:
            temp_file = f"{PANEL_STATE_FILE}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(temp_file, PANEL_STATE_FILE)
        except: pass

def _utcnow() -> datetime:
    return datetime.utcnow()

# -----------------------------
# Clase de Estado
# -----------------------------
class PanelState:
    def __init__(self):
        self.message_id: Optional[int] = None
        self.query: str = ""
        self.page: int = 0
        self.mode: str = "list"
        self.selected_user_id: Optional[str] = None
        self.history: List[str] = []
        self.last_weekly_post: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "query": self.query,
            "page": self.page,
            "mode": self.mode,
            "selected_user_id": self.selected_user_id,
            "history": self.history[-HISTORY_MAX:],
            "last_weekly_post": self.last_weekly_post,
        }

    @classmethod
    def from_dict(cls, d: dict):
        s = cls()
        s.message_id = d.get("message_id")
        s.query = d.get("query", "")
        s.page = max(0, int(d.get("page", 0)))
        s.mode = "list" if d.get("mode") != "detail" else "detail"
        s.selected_user_id = str(d.get("selected_user_id")) if d.get("selected_user_id") else None
        s.history = list(d.get("history", []))[-HISTORY_MAX:]
        s.last_weekly_post = d.get("last_weekly_post")
        return s

# -----------------------------
# Modales (Formularios)
# -----------------------------

class SearchModal(Modal, title="Buscar jugadores"):
    query = TextInput(label="Busqueda", placeholder="ID, email, nombre o padrino", required=False)
    def __init__(self, cog_ref):
        super().__init__(timeout=300)
        self.cog_ref = cog_ref
    async def on_submit(self, interaction):
        self.cog_ref.state.query = str(self.query.value or "").strip()
        self.cog_ref.state.page = 0
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

class AddUserModal(Modal, title="Agregar ALUMNO Manual"):
    discord_id = TextInput(label="Discord ID", placeholder="123456789...", max_length=20, required=True)
    email = TextInput(label="Correo PUCV", placeholder="user@mail.pucv.cl", max_length=255, required=True)
    minecraft_username = TextInput(label="Minecraft Java", placeholder="Steve", max_length=16, required=True)

    def __init__(self, cog_ref):
        super().__init__()
        self.cog_ref = cog_ref

    async def on_submit(self, interaction):
        # validaciones basicas
        did = str(self.discord_id.value).strip()
        mail = str(self.email.value).strip().lower()
        mc = str(self.minecraft_username.value).strip()

        if not did.isdigit() or len(did) < 17:
            return await interaction.response.send_message("❌ ID de Discord malo.", ephemeral=True)
        if not validate_university_email(mail):
            return await interaction.response.send_message("❌ Correo PUCV invalido.", ephemeral=True)
        
        # guardar en db como alumno
        if await db.update_or_insert_user(mail, int(did), mc):
            self.cog_ref.push_history(f"Alumno agregado manual: {mc}")
            
            # intentar dar roles
            guild = interaction.guild
            if guild:
                mem = guild.get_member(int(did))
                if mem:
                    r = guild.get_role(self.cog_ref.bot.config.get('ROLE_ID_VERIFIED'))
                    if r: await mem.add_roles(r)

            await interaction.response.send_message("✅ Alumno agregado.", ephemeral=True)
            await self.cog_ref.render_panel(interaction=interaction)
        else:
            await interaction.response.send_message("❌ Error guardando en DB.", ephemeral=True)

class AddGuestModal(Modal, title="Agregar INVITADO (Apadrinado)"):
    sponsor_id = TextInput(label="ID del Padrino", placeholder="Discord ID del alumno", required=True)
    guest_id = TextInput(label="ID del Invitado", placeholder="Discord ID del amigo", required=True)
    guest_mc = TextInput(label="Minecraft del Invitado", required=True)
    real_name = TextInput(label="Nombre Real", required=True)

    def __init__(self, cog_ref):
        super().__init__()
        self.cog_ref = cog_ref

    async def on_submit(self, interaction):
        # llamar a la funcion nueva de db
        ok, msg = await db.add_guest_user(
            int(self.guest_id.value),
            self.guest_mc.value,
            self.real_name.value,
            int(self.sponsor_id.value)
        )

        if ok:
            self.cog_ref.push_history(f"Invitado agregado: {self.guest_mc.value} (Padrino: {self.sponsor_id.value})")
            
            # dar roles de invitado
            guild = interaction.guild
            if guild:
                mem = guild.get_member(int(self.guest_id.value))
                if mem:
                    # poner prefijo [INV]
                    try: await mem.edit(nick=f"[INV] {self.guest_mc.value}"[:32])
                    except: pass
                    
                    r = guild.get_role(int(self.cog_ref.bot.config.get('ROLE_ID_GUEST', 0)))
                    if r: await mem.add_roles(r)
            
            await interaction.response.send_message(f"✅ {msg}", ephemeral=True)
            await self.cog_ref.render_panel(interaction=interaction)
        else:
            await interaction.response.send_message(f"❌ Error: {msg}", ephemeral=True)

# -----------------------------
# Vistas (Botones y Menus)
# -----------------------------

class PlayerSelect(Select):
    def __init__(self, cog_ref, rows_page):
        options = []
        for row in rows_page:
            # desempaquetar la tupla de 6
            email, user_id, username, u_type, sponsor, r_name = row
            
            label = (username or "—")[:100]
            if u_type == 'guest':
                desc = f"🤝 Invitado | {r_name}"[:100]
            else:
                desc = (email or "Sin Email")[:100]
                
            options.append(discord.SelectOption(label=label, description=desc, value=str(user_id)))
        
        if not options:
            options = [discord.SelectOption(label="Vacio", value="__none__", default=True)]
            
        super().__init__(placeholder="Selecciona para editar...", min_values=1, max_values=1, options=options)
        self.cog_ref = cog_ref

    async def callback(self, interaction):
        if self.values[0] != "__none__":
            self.cog_ref.state.mode = "detail"
            self.cog_ref.state.selected_user_id = str(self.values[0])
            _save_panel_state(self.cog_ref.state.to_dict())
            await self.cog_ref.render_panel(interaction=interaction)
        else:
            await interaction.defer()

class ListView(View):
    def __init__(self, cog_ref, rows_page, has_prev, has_next):
        super().__init__(timeout=None)
        self.cog_ref = cog_ref
        self.add_item(PlayerSelect(cog_ref, rows_page))
        self.prev_page.disabled = not has_prev
        self.next_page.disabled = not has_next

    @button(label="🔄 Recargar", style=discord.ButtonStyle.secondary, row=2)
    async def reload_btn(self, interaction, button):
        await interaction.defer()
        await self.cog_ref.render_panel(interaction=interaction)
        
    @button(label="◀ Atras", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction, button):
        if self.cog_ref.state.page > 0:
            self.cog_ref.state.page -= 1
            _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="Siguiente ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction, button):
        self.cog_ref.state.page += 1
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="🔎 Buscar", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction, button):
        await interaction.response.send_modal(SearchModal(self.cog_ref))

    @button(label="🧹 Limpiar", style=discord.ButtonStyle.secondary, row=1)
    async def clear_search(self, interaction, button):
        self.cog_ref.state.query = ""
        self.cog_ref.state.page = 0
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="📊 Volver al Inicio", style=discord.ButtonStyle.success, row=1)
    async def summary(self, interaction, button):
        self.cog_ref.state.query = ""
        self.cog_ref.state.page = 0
        self.cog_ref.state.mode = "list"
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="🎓 +Alumno", style=discord.ButtonStyle.success, row=2)
    async def add_user(self, interaction, button):
        await interaction.response.send_modal(AddUserModal(self.cog_ref))

    @button(label="🤝 +Invitado", style=discord.ButtonStyle.primary, row=2)
    async def add_guest(self, interaction, button):
        await interaction.response.send_modal(AddGuestModal(self.cog_ref))

# Vista de detalle (cuando seleccionas un usuario)
class DetailView(View):
    def __init__(self, cog_ref, record, member, ver_role, guest_role):
        super().__init__(timeout=None)
        self.cog_ref = cog_ref
        self.record = record # tupla de 6
        self.member = member
        self.uid = record[1]
        
        # logica de roles para el boton de suspender
        # aqui asumimos que si esta en la DB tiene whitelist=1
        self.suspend.label = "⛔ Suspender / Banear"

    @button(label="🗑 ELIMINAR", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction, button):
        # confirmacion de borrado
        await db.full_user_delete(self.uid)
        await interaction.response.send_message("🗑 Usuario eliminado de la existencia.", ephemeral=True)
        self.cog_ref.state.mode = "list"
        self.cog_ref.state.selected_user_id = None
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="⛔ Suspender (Toggle)", style=discord.ButtonStyle.danger, row=1)
    async def suspend(self, interaction, button):
        # toggle del whitelist flag
        current = await db.get_whitelist_flag(self.uid)
        new_val = not (current == 1)
        await db.set_whitelist_flag(self.uid, new_val)
        
        msg = "🔓 Reactivado" if new_val else "⛔ Suspendido (No puede entrar a MC)"
        await interaction.response.send_message(msg, ephemeral=True)

    @button(label="⬅ Volver", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        self.cog_ref.state.mode = "list"
        self.cog_ref.state.selected_user_id = None
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

# -----------------------------
# El Cog Principal
# -----------------------------
class AdminPanelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.state = PanelState.from_dict(_load_panel_state())
        self._message = None
        
        # fix rapido por si quedo pegado en detail
        if self.state.mode == "detail":
            self.state.mode = "list"
            self.state.selected_user_id = None

    async def cog_load(self):
        self.bot.loop.create_task(self.init_panel())

    async def render_panel(self, interaction=None):
        if not await self._ensure_message(): return

        # obtener datos frescos
        rows = await db.list_verified_players()
        
        # MODO DETALLE
        if self.state.mode == "detail" and self.state.selected_user_id:
            # buscar el usuario en la lista
            rec = next((r for r in rows if str(r[1]) == self.state.selected_user_id), None)
            if not rec:
                # se borro o desaparecio
                self.state.mode = "list"
                await self.render_panel(interaction)
                return

            email, user_id, username, u_type, sponsor, r_name = rec
            
            embed = discord.Embed(title=f"👤 Detalle: {username}", color=0x3498db)
            embed.add_field(name="Tipo", value="🎓 Estudiante" if u_type == 'student' else "🤝 Invitado")
            embed.add_field(name="Minecraft", value=f"`{username}`")
            embed.add_field(name="Discord ID", value=f"`{user_id}`")
            
            if u_type == 'student':
                embed.add_field(name="Correo", value=f"`{email}`")
            else:
                embed.add_field(name="Nombre Real", value=f"{r_name}")
                embed.add_field(name="Padrino ID", value=f"`{sponsor}`")
            
            # obtener miembro de discord para roles
            guild = self.bot.get_guild(int(self.bot.config.get('GUILD_ID', 0)))
            mem = guild.get_member(int(user_id)) if guild else None
            
            view = DetailView(self, rec, mem, None, None)
            
            if interaction and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view)
            elif self._message:
                await self._message.edit(embed=embed, view=view)
            return

        # MODO LISTA
        filtered = _filter_rows(rows, self.state.query)
        page_rows, has_prev, has_next, cur, total_pages = _slice_page(filtered, self.state.page)
        
        # stats
        total, verified, pending = _count_stats(rows)
        guests = sum(1 for r in rows if r[3] == 'guest')

        title = "📋 Panel Admin"
        if self.state.query: title += f" (Filtro: {self.state.query})"
        
        embed = discord.Embed(title=title, color=0x2ecc71)
        embed.description = f"**Total:** {total} | **Alumnos:** {verified} | **Invitados:** {guests}"
        
        # renderizar lista
        lines = [_fmt_user_line(*r) for r in page_rows]
        embed.add_field(name=f"Pagina {cur}/{total_pages}", value="\n".join(lines) or "Vacio.", inline=False)
        
        view = ListView(self, page_rows, has_prev, has_next)
        
        # actualizar mensaje
        if interaction:
            try:
                if interaction.response.is_done():
                    await interaction.edit_original_response(embed=embed, view=view)
                else:
                    await interaction.response.edit_message(embed=embed, view=view)
            except: pass
        elif self._message:
            await self._message.edit(embed=embed, view=view)

    async def init_panel(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5) # esperar que discord respire
        
        # intentar recuperar o crear mensaje
        cid = self.bot.config.get("ADMIN_CHANNEL_ID")
        if not cid: return
        
        ch = self.bot.get_channel(int(cid))
        if not ch: return
        
        # buscar mensaje anterior o crear
        if self.state.message_id:
            try:
                self._message = await ch.fetch_message(self.state.message_id)
            except: self._message = None
            
        if not self._message:
            # limpiar canal
            async for m in ch.history(limit=5):
                if m.author == self.bot.user: await m.delete()
            self._message = await ch.send("Cargando Panel...")
            self.state.message_id = self._message.id
            _save_panel_state(self.state.to_dict())
            
        await self.render_panel()

    async def _ensure_message(self):
        if self._message: return True
        await self.init_panel()
        return self._message is not None

    def push_history(self, txt):
        self.state.history.append(f"{_utcnow()}: {txt}")
        _save_panel_state(self.state.to_dict())

async def setup(bot):
    await bot.add_cog(AdminPanelCog(bot))