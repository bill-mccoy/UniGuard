# cogs/admin.py
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

# Configuración
PANEL_STATE_FILE = "admin_panel_state.json"
PAGE_SIZE = 10
HISTORY_MAX = 50
_save_lock = threading.Lock()

# -----------------------------
# Helpers
# -----------------------------
def _safe_lower(s) -> str:
    try:
        return str(s or "").strip().lower()
    except Exception:
        return ""

def _count_stats(rows: List[Tuple[str, str, Optional[str]]]) -> Tuple[int, int, int]:
    """Count total, verified and pending users"""
    try:
        total = len(rows)
        verified = sum(1 for _, _, username in rows if username)
        pending = sum(1 for email, _, username in rows if email and not username)
        return total, verified, pending
    except Exception as e:
        logger.error(f"Error in _count_stats: {e}")
        return 0, 0, 0

def _filter_rows(rows: List[Tuple[str, str, Optional[str]]], query: str) -> List[Tuple[str, str, Optional[str]]]:
    """Filter rows based on query (email, user_id or username)"""
    q = _safe_lower(query)
    if not q:
        return rows
        
    filtered = []
    for row in rows:
        try:
            email, user_id, username = row
            if (q in _safe_lower(email) or 
                q in _safe_lower(user_id) or 
                (username and q in _safe_lower(username))):
                filtered.append(row)
        except Exception as e:
            logger.warning(f"Error procesando fila {row}: {e}")
    return filtered

def _slice_page(rows: List[Tuple[str, str, Optional[str]]], page: int) -> Tuple[List[Tuple[str, str, Optional[str]]], bool, bool, int, int]:
    total = len(rows)
    max_page = max(0, (total - 1) // PAGE_SIZE)
    page = max(0, min(page, max_page))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_rows = rows[start:end]
    has_prev = page > 0
    has_next = end < total
    return page_rows, has_prev, has_next, page + 1, max_page + 1

def _fmt_user_line(email: str, user_id: str, username: Optional[str]) -> str:
    """Format user line for display (preserve underscores using code formatting)"""
    username_display = f"`{username}`" if username else "—"
    email_display = f"`{email}`" if email else "—"
    return f"- {username_display} • Email: {email_display} • ID: {user_id}"

def _chunk_history(history: List[str], limit: int = 10) -> List[str]:
    return history[-limit:][::-1]

def _load_panel_state() -> dict:
    if os.path.exists(PANEL_STATE_FILE):
        try:
            with open(PANEL_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.exception("Error leyendo estado del panel")
    return {}

def _save_panel_state(state: dict):
    with _save_lock:
        try:
            temp_file = f"{PANEL_STATE_FILE}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(temp_file, PANEL_STATE_FILE)
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")

def _utcnow() -> datetime:
    return datetime.utcnow()

# -----------------------------
# Panel State
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
# Vistas y Modales
# -----------------------------
class ErrorView(View):
    def __init__(self, cog_ref: "AdminPanelCog"):
        super().__init__(timeout=300)
        self.cog_ref = cog_ref

    @button(label="🔄 Recargar Panel", style=discord.ButtonStyle.primary)
    async def reload(self, interaction: discord.Interaction, button: Button):
        try:
            self.cog_ref.state.mode = "list"
            self.cog_ref.state.selected_user_id = None
            self.cog_ref.state.page = 0
            _save_panel_state(self.cog_ref.state.to_dict())
            await interaction.response.edit_message(content="🔄 Recargando...", embed=None, view=None)
            await self.cog_ref.render_panel(interaction=interaction)
        except Exception as e:
            logger.error(f"Error al recargar panel: {e}")
            await interaction.followup.send("❌ No se pudo recargar. Intenta nuevamente.", ephemeral=True)

class SearchModal(Modal, title="Buscar jugadores"):
    query = TextInput(
        label="Texto de búsqueda",
        placeholder="Discord ID, email o nombre de Minecraft",
        max_length=100,
        required=False,
    )

    def __init__(self, cog_ref: "AdminPanelCog"):
        super().__init__(timeout=300)
        self.cog_ref = cog_ref

    async def on_submit(self, interaction: discord.Interaction):
        self.cog_ref.state.query = str(self.query.value or "").strip()
        self.cog_ref.state.page = 0
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

class PlayerSelect(Select):
    def __init__(self, cog_ref: "AdminPanelCog", rows_page: List[Tuple[str, str, Optional[str]]]):
        options = []
        for email, user_id, username in rows_page:
            label = (username or "—")[:100] or "—"
            desc = (email or "Sin email")[:100]
            options.append(discord.SelectOption(
                label=label,
                description=desc,
                value=str(user_id)
            ))
        
        if not options:
            options = [discord.SelectOption(
                label="Sin resultados",
                description="Ajusta el filtro",
                value="__none__",
                default=True
            )]
            
        super().__init__(
            placeholder="Selecciona un jugador para editar…",
            min_values=1,
            max_values=1,
            options=options
        )
        self.cog_ref = cog_ref

    async def callback(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
            
        if self.values and self.values[0] != "__none__":
            self.cog_ref.state.mode = "detail"
            self.cog_ref.state.selected_user_id = str(self.values[0])
            _save_panel_state(self.cog_ref.state.to_dict())
            await self.cog_ref.render_panel(interaction=interaction)
class AddUserModal(Modal, title="Agregar usuario manualmente"):
    discord_id = TextInput(
        label="Discord ID",
        placeholder="123456789012345678",
        max_length=20,
        required=True,
    )
    email = TextInput(
        label="Correo institucional",
        placeholder="usuario@mail.pucv.cl",
        max_length=255,
        required=True,
    )
    minecraft_username = TextInput(
        label="Nombre de Minecraft",
        placeholder="Ej: Juanito_123",
        max_length=16,
        required=True,
    )

    def __init__(self, cog_ref: "AdminPanelCog"):
        super().__init__(timeout=300)
        self.cog_ref = cog_ref

    async def on_submit(self, interaction: discord.Interaction):
        discord_id = str(self.discord_id.value).strip()
        email = str(self.email.value).strip().lower()
        mc_username = str(self.minecraft_username.value).strip()

        # Validaciones
        if not discord_id.isdigit() or len(discord_id) < 17:
            return await interaction.response.send_message(
                "❌ Discord ID inválido. Debe ser un número de 17-18 dígitos.",
                ephemeral=True
            )
            
        if not validate_university_email(email):
            return await interaction.response.send_message(
                "❌ Correo inválido (debe terminar en `@mail.pucv.cl`).", 
                ephemeral=True
            )
            
        if not validate_minecraft_username(mc_username):
            return await interaction.response.send_message(
                "❌ Nombre de Minecraft inválido. Usa letras, números y guion bajo (3-16 caracteres).",
                ephemeral=True
            )
            
        try:
            # Actualizar base de datos
            success = await db.update_or_insert_user(
                email=email,
                user_id=int(discord_id),
                username=mc_username
            )
            
            if not success:
                raise RuntimeError("Error en la base de datos")
                
            # Asignar rol de verificado si el usuario está en el servidor
            guild = self.cog_ref.bot.get_guild(self.cog_ref.bot.config.get('GUILD_ID'))
            if guild:
                try:
                    member = await guild.fetch_member(int(discord_id))
                    verified_role = guild.get_role(self.cog_ref.bot.config.get('ROLE_ID_VERIFIED'))
                    not_verified_role = guild.get_role(self.cog_ref.bot.config.get('ROLE_ID_NOT_VERIFIED'))
                    
                    if verified_role:
                        await member.add_roles(verified_role)
                    if not_verified_role and not_verified_role in member.roles:
                        await member.remove_roles(not_verified_role)
                        
                except discord.NotFound:
                    pass  # Usuario no está en el servidor
                except Exception as e:
                    logger.error(f"Error asignando roles: {e}")
            
            await interaction.response.send_message(
                f"✅ Usuario agregado exitosamente:\n"
                f"- Discord ID: {discord_id}\n"
                f"- Email: {email}\n"
                f"- Minecraft: {mc_username}",
                ephemeral=True
            )
            
            # Actualizar panel
            self.cog_ref.push_history(f"Usuario agregado manualmente: {discord_id} ({email}, {mc_username})")
            await self.cog_ref.render_panel(interaction=interaction)
            
        except Exception as e:
            logger.error(f"Error agregando usuario manualmente: {e}")
            await interaction.response.send_message(
                "❌ Error al agregar usuario. Revisa logs.",
                ephemeral=True
            )
            
class ListView(View):
    def __init__(self, cog_ref: "AdminPanelCog", rows_page: List[Tuple[str, str, Optional[str]]], has_prev: bool, has_next: bool):
        # Keep the view alive until explicitly replaced to avoid post-resume dead UI
        super().__init__(timeout=None)
        self.cog_ref = cog_ref
        self.add_item(PlayerSelect(cog_ref, rows_page))
        
        self.prev_page.disabled = not has_prev
        self.next_page.disabled = not has_next
        
        self.reload_button.disabled = False

    @button(label="🔄 Recargar", style=discord.ButtonStyle.secondary, row=2)
    async def reload_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await self.cog_ref.render_panel(interaction=interaction)
        
    @button(label="◀ Página anterior", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: Button):
        if self.cog_ref.state.page > 0:
            self.cog_ref.state.page -= 1
            _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="Siguiente página ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        self.cog_ref.state.page += 1
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="🔎 Buscar", style=discord.ButtonStyle.primary, row=1)
    async def search(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SearchModal(self.cog_ref))

    @button(label="🧹 Limpiar búsqueda", style=discord.ButtonStyle.secondary, row=1)
    async def clear_search(self, interaction: discord.Interaction, button: Button):
        self.cog_ref.state.query = ""
        self.cog_ref.state.page = 0
        _save_panel_state(self.cog_ref.state.to_dict())
        await interaction.response.defer()
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="📊 Resumen", style=discord.ButtonStyle.success, row=1)
    async def summary(self, interaction: discord.Interaction, button: Button):
        self.cog_ref.state.query = ""
        self.cog_ref.state.page = 0
        self.cog_ref.state.mode = "list"
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

    @button(label="➕ Agregar usuario", style=discord.ButtonStyle.success, row=2)
    async def add_user(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddUserModal(self.cog_ref))
        
class EditEmailModal(Modal, title="Editar correo institucional"):
    new_email = TextInput(
        label="Nuevo correo",
        placeholder="usuario@mail.pucv.cl",
        max_length=255,
        required=True,
    )

    def __init__(self, target_user_id: str, current_email: str = ""):
        super().__init__(timeout=300)
        self.target_user_id = str(target_user_id)
        self.new_email.default = current_email

    async def on_submit(self, interaction: discord.Interaction):
        email = str(self.new_email.value).strip().lower()
        
        if not validate_university_email(email):
            return await interaction.response.send_message(
                "❌ Correo inválido (debe terminar en `@mail.pucv.cl`).", 
                ephemeral=True
            )
            
        try:
            ok = await db.update_or_insert_user(
                email=email,
                user_id=self.target_user_id,
                minecraft_username=None
            )
            
            if not ok:
                raise RuntimeError("DB no devolvió éxito")
                
            await interaction.response.send_message("✅ Correo actualizado correctamente", ephemeral=True)
            await interaction.message.edit(view=await self.get_updated_view(interaction))
            
        except Exception as e:
            logger.error(f"Error actualizando email: {e}")
            await interaction.response.send_message(
                "❌ Error al actualizar el correo. Revisa logs.",
                ephemeral=True
            )
    
    async def get_updated_view(self, interaction: discord.Interaction) -> View:
        # Recargar la vista de detalle con los datos actualizados
        cog = interaction.client.get_cog("AdminPanelCog")
        if not cog:
            return ErrorView(cog)
            
        return await cog.get_detail_view(self.target_user_id)

class EditMCModal(Modal, title="Editar nombre de Minecraft"):
    new_mc = TextInput(
        label="Nuevo nombre",
        placeholder="Ej: Juanito_123",
        max_length=16,
        required=True,
    )

    def __init__(self, target_user_id: str, current_mc: str = ""):
        super().__init__(timeout=300)
        self.target_user_id = str(target_user_id)
        self.new_mc.default = current_mc

    async def on_submit(self, interaction: discord.Interaction):
        mc = str(self.new_mc.value).strip()
        
        if not validate_minecraft_username(mc):
            return await interaction.response.send_message(
                "❌ Nombre inválido. Usa letras, números y guion bajo.",
                ephemeral=True
            )
            
        try:
            ok = await db.update_or_insert_user(
                email=None,
                user_id=self.target_user_id,
                username=mc
            )
            
            if not ok:
                raise RuntimeError("DB no devolvió éxito")
                
            await interaction.response.send_message("✅ Nombre de Minecraft actualizado", ephemeral=True)
            await interaction.message.edit(view=await self.get_updated_view(interaction))
            
        except Exception as e:
            logger.error(f"Error actualizando MC: {e}")
            await interaction.response.send_message(
                "❌ Error al actualizar el nombre. Revisa logs.",
                ephemeral=True
            )
    
    async def get_updated_view(self, interaction: discord.Interaction) -> View:
        # Recargar la vista de detalle con los datos actualizados
        cog = interaction.client.get_cog("AdminPanelCog")
        if not cog:
            return ErrorView(cog)
            
        return await cog.get_detail_view(self.target_user_id)

class DetailView(View):
    def __init__(self, cog_ref: "AdminPanelCog", record: Tuple[str, str, Optional[str]], member: Optional[discord.Member], verified_role: Optional[discord.Role], suspended_role: Optional[discord.Role]):
        # Keep the view alive until explicitly replaced to avoid post-resume dead UI
        super().__init__(timeout=None)
        self.cog_ref = cog_ref
        self.record = record
        self.member = member
        self.verified_role = verified_role
        self.suspended_role = suspended_role

        already_verified = bool(member and verified_role and verified_role in member.roles)
        is_suspended = bool(member and suspended_role and suspended_role in member.roles)

        self.verify.label = "✅ Ya verificado" if already_verified else "✅ Asignar Alumno"
        self.verify.disabled = already_verified
        self.suspend.label = "🔓 Reactivar" if is_suspended else "⛔ Suspender"

    @button(label="✏️ Editar correo", style=discord.ButtonStyle.primary, row=0)
    async def edit_email(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditEmailModal(self.record[1], self.record[0]))

    @button(label="🎮 Editar Minecraft", style=discord.ButtonStyle.primary, row=0)
    async def edit_mc(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditMCModal(self.record[1], self.record[2] or ""))

    @button(label="✅ Asignar Alumno", style=discord.ButtonStyle.success, row=1)
    async def verify(self, interaction: discord.Interaction, button: Button):
        if not self.member or not self.verified_role:
            return await interaction.response.send_message(
                "❌ No se pudo verificar al usuario. Faltan datos.",
                ephemeral=True
            )
            
        try:
            await self.member.add_roles(
                self.verified_role,
                reason=f"Verificado por {interaction.user}"
            )
            await interaction.response.send_message("✅ Rol de Alumno asignado", ephemeral=True)
            await interaction.message.edit(view=self)  # Actualizar vista
            
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ No tengo permisos para asignar roles.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error asignando rol: {e}")
            await interaction.response.send_message(
                "❌ Error al asignar rol. Revisa logs.",
                ephemeral=True
            )

    @button(label="⛔ Suspender", style=discord.ButtonStyle.danger, row=1)
    async def suspend(self, interaction: discord.Interaction, button: Button):
        try:
            discord_id = str(self.record[1])
            # Leer estado actual
            current = await db.get_whitelist_flag(discord_id)
            enabled = False if current in (1, True) else True  # Toggle: 1->0, 0/None->1
            ok = await db.set_whitelist_flag(discord_id, enabled)
            if not ok:
                raise RuntimeError("DB toggle failed")
            msg = "🔓 Usuario reactivado (whitelist=1)" if enabled else "⛔ Usuario suspendido (whitelist=0)"
            # Actualizar label del botón acorde
            self.suspend.label = "🔓 Reactivar" if not enabled else "⛔ Suspender"
            await interaction.response.send_message(msg, ephemeral=True)
            await interaction.message.edit(view=self)
        except Exception as e:
            logger.error(f"Error en suspender: {e}")
            try:
                await interaction.response.send_message(
                    "❌ Error al suspender/reactivar usuario. Revisa logs.",
                    ephemeral=True
                )
            except Exception:
                pass

    @button(label="🗑 Eliminar usuario", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction: discord.Interaction, button: Button):
        confirm_view = ConfirmDeleteView(self.cog_ref, self.record[1])
        await interaction.response.send_message(
            "⚠️ ¿Estás seguro de eliminar TODOS los datos de este usuario? (Verificación + Whitelist)",
            view=confirm_view,
            ephemeral=True
        )

    @button(label="⬅ Volver", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: Button):
        self.cog_ref.state.mode = "list"
        self.cog_ref.state.selected_user_id = None
        _save_panel_state(self.cog_ref.state.to_dict())
        await self.cog_ref.render_panel(interaction=interaction)

class ConfirmDeleteView(View):
    def __init__(self, cog_ref: "AdminPanelCog", user_id: str):
        super().__init__(timeout=30)
        self.cog_ref = cog_ref
        self.user_id = user_id

    @button(label="✅ Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        try:
            success = await db.full_user_delete(self.user_id)

            # Ajustar roles en Discord: quitar verificado y poner no verificado
            try:
                guild = self.cog_ref.bot.get_guild(self.cog_ref.bot.config.get('GUILD_ID'))
                member = await guild.fetch_member(int(self.user_id)) if guild else None
                role_verified_id = self.cog_ref.bot.config.get('ROLE_ID_VERIFIED')
                role_not_verified_id = self.cog_ref.bot.config.get('ROLE_ID_NOT_VERIFIED')
                role_verified = guild.get_role(role_verified_id) if guild and role_verified_id else None
                role_not_verified = guild.get_role(role_not_verified_id) if guild and role_not_verified_id else None
                if member:
                    try:
                        # Quitar rol verificado si lo tiene
                        if role_verified and role_verified in member.roles:
                            await member.remove_roles(role_verified, reason="Eliminado desde panel")
                        # Poner rol no verificado si existe
                        if role_not_verified and role_not_verified not in member.roles:
                            await member.add_roles(role_not_verified, reason="Eliminado desde panel")
                    except discord.Forbidden:
                        logger.warning("Sin permisos para modificar roles del usuario al eliminar")
                    except Exception as rex:
                        logger.error(f"Error ajustando roles al eliminar: {rex}")
            except discord.NotFound:
                # Miembro no está en el guild; continuar
                pass
            except Exception as ex:
                logger.error(f"Error obteniendo miembro/roles al eliminar: {ex}")

            if success:
                toast = "✅ Usuario eliminado completamente"
                self.cog_ref.state.mode = "list"
                self.cog_ref.state.selected_user_id = None
                _save_panel_state(self.cog_ref.state.to_dict())
            else:
                toast = "❌ Error al eliminar usuario"
            
            await interaction.response.edit_message(content=toast, view=None)
            await self.cog_ref.render_panel(interaction=interaction)
        except Exception as e:
            logger.error(f"Error en confirmación de eliminación: {e}")
            await interaction.response.edit_message(
                content="❌ Error crítico al eliminar. Ver logs.",
                view=None
            )

    @button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="Operación cancelada", view=None)

# -----------------------------
# Cog principal
# -----------------------------
class AdminPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.state = PanelState.from_dict(_load_panel_state())
        self._message = None
        self.logger = logging.getLogger("AdminPanel")
        self.verified_role = None
        self.suspended_role = None
        self._weekly_task = None  # Inicializar como None
        
        # Resetear estado si estaba en modo detalle
        if self.state.mode == "detail":
            self.state.mode = "list"
            self.state.selected_user_id = None
            _save_panel_state(self.state.to_dict())
    
    async def cog_load(self):
        """Llamado cuando el cog se carga"""
        self.bot.loop.create_task(self.initialize_panel())
        # Ensure we refresh UI on ready/resume events
        try:
            self.bot.add_listener(self._on_ready_refresh, name="on_ready")
            self.bot.add_listener(self._on_shard_resumed, name="on_shard_resumed")
        except Exception:
            self.logger.exception("No se pudieron registrar listeners de reanudación")

    async def render_panel(self, interaction: Optional[discord.Interaction] = None):
        """Método principal para renderizar el panel"""
        try:
            if not await self._ensure_message():
                error_embed = discord.Embed(
                    title="❌ Error del sistema",
                    description="No se pudo acceder al canal de administración",
                    color=0xe74c3c
                )
                if interaction:
                    try:
                        await interaction.response.send_message(embed=error_embed, view=ErrorView(self))
                    except Exception:
                        pass
                return

            # Obtener datos
            rows = await self._compute_rows()
            
            # Modo detalle
            if self.state.mode == "detail" and self.state.selected_user_id:
                # Crear embed
                user_id = self.state.selected_user_id
                rec = next((r for r in rows if str(r[1]) == user_id), None)
                
                if not rec:
                    embed = discord.Embed(
                        title="⚠️ Usuario no encontrado",
                        description="El usuario seleccionado ya no existe en la base de datos",
                        color=0xe67e22
                    )
                    view = ErrorView(self)
                else:
                    email, user_id, username = rec
                    embed = discord.Embed(
                        title=f"✏️ Ficha de usuario - {username or 'Sin nombre'}",
                        color=0x3498db
                    )
                    embed.add_field(name="🆔 Discord ID", value=f"`{user_id}`", inline=False)
                    embed.add_field(name="📧 Email", value=f"`{email or 'No registrado'}`", inline=False)
                    embed.add_field(name="🎮 Minecraft", value=f"`{username or 'No registrado'}`", inline=False)
                    
                    # Obtener vista de detalle (usar el registro ya encontrado)
                    view = await self.get_detail_view(user_id, rec)
            
            # Modo lista
            else:
                filtered = _filter_rows(rows, self.state.query)
                page_rows, has_prev, has_next, cur, total_pages = _slice_page(filtered, self.state.page)
                total, verified, pending = _count_stats(rows)

                title = "📋 Panel de administración" if not self.state.query else f"📋 Panel de administración — Filtro: {self.state.query}"
                embed = discord.Embed(
                    title=title,
                    color=0x2ecc71
                )
                embed.add_field(name="Total usuarios", value=str(total), inline=True)
                embed.add_field(name="✅ Verificados", value=str(verified), inline=True)
                embed.add_field(name="⏳ Pendientes", value=str(pending), inline=True)
                
                user_list = "\n".join(_fmt_user_line(*row) for row in page_rows) if page_rows else "Sin resultados."
                embed.add_field(
                    name=f"Usuarios (Página {cur}/{total_pages})",
                    value=user_list,
                    inline=False
                )
                
                view = ListView(self, page_rows, has_prev, has_next)

            # Actualizar mensaje (asegurando que la vista siempre se adjunte)
            if interaction:
                try:
                    if interaction.response.is_done():
                        await interaction.edit_original_response(embed=embed, view=view)
                    else:
                        await interaction.response.edit_message(embed=embed, view=view)
                except (discord.NotFound, discord.Forbidden):
                    # Fallback a editar el mensaje del panel directamente
                    if await self._ensure_message():
                        await self._message.edit(embed=embed, view=view)
                except Exception as ex:
                    self.logger.error(f"Error actualizando mensaje por interacción: {ex}")
                    if await self._ensure_message():
                        await self._message.edit(embed=embed, view=view)
            else:
                if await self._ensure_message():
                    await self._message.edit(embed=embed, view=view)
                
        except Exception as e:
            self.logger.error(f"Error en render_panel: {e}")
            if interaction:
                try:
                    await interaction.response.send_message(
                        f"❌ Error al mostrar el panel: {str(e)}",
                        ephemeral=True
                    )
                except Exception:
                    pass

    async def initialize_panel(self):
        """Inicialización completa del panel"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(10)
        
        try:
            # Iniciar tarea semanal (evitar duplicados)
            if self._weekly_task is None:
                # Create a task loop using the decorator style factory
                try:
                    loop_factory = tasks.loop(hours=24)
                    self._weekly_task = loop_factory(self._send_weekly_report)
                except Exception:
                    self.logger.exception("No se pudo crear la tarea semanal")
            if self._weekly_task and not self._weekly_task.is_running():
                try:
                    self._weekly_task.start()
                except Exception:
                    self.logger.exception("No se pudo iniciar la tarea semanal")

            # Limpiar canal de administración y crear mensaje inicial fresco
            admin_channel_id = self.bot.config.get("ADMIN_CHANNEL_ID")
            channel = None
            if admin_channel_id:
                channel = self.bot.get_channel(int(admin_channel_id))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(admin_channel_id))
                    except Exception:
                        self.logger.exception(f"No se pudo acceder al canal ADMIN_CHANNEL_ID={admin_channel_id}")
                if channel is not None:
                    # Eliminar solo el mensaje anterior del panel si existe, sin purgar otros mensajes
                    try:
                        prev_id = getattr(self.state, "message_id", None)
                        if prev_id:
                            try:
                                prev_msg = await channel.fetch_message(int(prev_id))
                                await prev_msg.delete()
                            except discord.NotFound:
                                pass
                            except discord.Forbidden:
                                self.logger.warning("Sin permisos para eliminar el mensaje anterior del panel")
                            except Exception:
                                self.logger.exception("Error eliminando mensaje anterior del panel")
                    except Exception:
                        self.logger.exception("Fallo al intentar borrar el mensaje anterior del panel")

                    # Crear mensaje inicial
                    try:
                        init_embed = discord.Embed(
                            title="🔄 Inicializando Panel de Administración",
                            description="Cargando datos...",
                            color=0x3498db,
                        )
                        new_message = await channel.send(embed=init_embed)
                        self._message = new_message
                        self.state.message_id = new_message.id
                        _save_panel_state(self.state.to_dict())
                    except Exception:
                        self.logger.exception("No se pudo crear el mensaje inicial del panel")

            # Renderizar panel inicial con diagnóstico y timeout
            self.logger.info("Renderizando panel de administración...")
            await asyncio.wait_for(self.render_panel(), timeout=30)
            self.logger.info("Panel renderizado con éxito")
            self.logger.info("Panel de administración inicializado")
        except Exception:
            # Registrar traza completa para facilitar el diagnóstico
            self.logger.exception("Error inicializando panel")

    async def _on_ready_refresh(self):
        """Refresca la UI cuando el bot entra en ready (incluye después de un RESUME en la mayoría de casos)."""
        try:
            # Pequeño delay para estabilizar cache y canales
            await asyncio.sleep(2)
            await self.render_panel()
        except Exception:
            self.logger.exception("Fallo al refrescar panel en on_ready")

    async def _on_shard_resumed(self, shard_id: int):
        """Refresca la UI cuando un shard se reanuda."""
        try:
            self.logger.info(f"Shard {shard_id} reanudado, refrescando panel de administración...")
            await asyncio.sleep(2)
            await self.render_panel()
        except Exception:
            self.logger.exception("Fallo al refrescar panel en on_shard_resumed")

    async def get_detail_view(self, user_id: str, rec: Tuple[str, str, Optional[str]]) -> View:
        """Obtiene la vista de detalle para un usuario específico usando el registro ya seleccionado"""
        try:
            member = None
            guild = self.bot.get_guild(int(self.bot.config.get('GUILD_ID', 0)))
            if guild:
                try:
                    member = await guild.fetch_member(int(user_id))
                except discord.NotFound:
                    pass
            return DetailView(self, rec, member, self.verified_role, self.suspended_role)
        except Exception as e:
            self.logger.error(f"Error obteniendo vista de detalle: {e}")
            return ErrorView(self)

    async def _send_weekly_report(self, *args, **kwargs):
        """Tarea para enviar reportes semanales"""
        try:
            channel_id = self.bot.config.get("LOG_CHANNEL_ID")
            if not channel_id:
                return
                
            channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
            
            rows = await db.list_verified_players()
            total, verified, pending = _count_stats(rows or [])
            
            now = _utcnow()
            last_post = (
                datetime.fromisoformat(self.state.last_weekly_post) 
                if self.state.last_weekly_post 
                else None
            )
            
            if not last_post or (now - last_post) >= timedelta(days=7):
                embed = discord.Embed(
                    title="📊 Estado semanal de verificaciones",
                    color=0x95a5a6,
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Total registros", value=str(total), inline=True)
                embed.add_field(name="✅ Verificados", value=str(verified), inline=True)
                embed.add_field(name="⏳ Pendientes", value=str(pending), inline=True)
                
                hist = "\n".join(_chunk_history(self.state.history, 5)) or "—"
                embed.add_field(
                    name="Actividad reciente",
                    value=f"```\n{hist}\n```",
                    inline=False
                )
                
                await channel.send(embed=embed)
                self.state.last_weekly_post = now.isoformat()
                _save_panel_state(self.state.to_dict())
        except Exception as e:
            self.logger.error(f"Error en tarea semanal: {e}")

    def push_history(self, line: str):
        ts = _utcnow().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {escape_markdown(line)}"
        self.state.history.append(entry)
        self.state.history = self.state.history[-HISTORY_MAX:]
        _save_panel_state(self.state.to_dict())

    async def _ensure_message(self) -> bool:
        """Garantiza que tenemos un mensaje válido para el panel"""
        try:
            if self._message is None:
                await self._fetch_message()
            
            if self._message:
                try:
                    await self._message.channel.fetch_message(self._message.id)
                    return True
                except discord.NotFound:
                    self.logger.warning("Mensaje del panel no encontrado, recreando...")
                    self._message = await self._fetch_message()
                    return self._message is not None
                except discord.Forbidden:
                    self.logger.error("Sin permisos para recuperar mensaje del panel")
                    return False
            
            return False
        except Exception as e:
            self.logger.error(f"Error en _ensure_message: {e}")
            return False

    async def _fetch_message(self) -> Optional[discord.Message]:
        """Obtiene el mensaje del panel desde Discord"""
        try:
            channel_id = self.bot.config.get("ADMIN_CHANNEL_ID")
            if not channel_id:
                self.logger.error("ADMIN_CHANNEL_ID no configurado")
                return None

            # Obtener canal
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except (discord.NotFound, discord.Forbidden):
                    self.logger.error(f"No se pudo acceder al canal: {channel_id}")
                    return None
            
            # Intentar obtener mensaje existente
            if self.state.message_id:
                try:
                    return await channel.fetch_message(self.state.message_id)
                except discord.NotFound:
                    self.logger.warning("Mensaje anterior no encontrado")
                except discord.Forbidden:
                    self.logger.error("Sin permisos para acceder al mensaje")
                    return None
                except Exception as e:
                    self.logger.error(f"Error obteniendo mensaje: {e}")

            # Crear nuevo mensaje si no existe
            embed = discord.Embed(
                title="🔄 Inicializando Panel de Administración",
                description="Cargando datos...",
                color=0x3498db
            )
            try:
                new_message = await channel.send(embed=embed)
            except discord.Forbidden:
                self.logger.error("Sin permisos para enviar mensajes al canal de administración")
                return None
            self.state.message_id = new_message.id
            _save_panel_state(self.state.to_dict())
            return new_message

        except Exception as e:
            self.logger.error(f"Error en _fetch_message: {e}", exc_info=True)
            return None

    async def _compute_rows(self) -> List[Tuple[str, str, Optional[str]]]:
        try:
            return await db.list_verified_players() or []
        except Exception as e:
            self.logger.error(f"Error en _compute_rows: {e}")
            return []



    def cog_unload(self):
        """Cancelar tareas al descargar el cog"""
        try:
            if self._weekly_task and self._weekly_task.is_running():
                self._weekly_task.cancel()
        finally:
            try:
                self.bot.remove_listener(self._on_ready_refresh, name="on_ready")
            except Exception:
                pass
            try:
                self.bot.remove_listener(self._on_shard_resumed, name="on_shard_resumed")
            except Exception:
                pass

async def setup(bot):
    try:
        await bot.add_cog(AdminPanelCog(bot))
        logging.info("Cog AdminPanel cargado correctamente")
    except Exception as e:
        logging.error(f"Error cargando AdminPanel: {e}")
        raise
        raise