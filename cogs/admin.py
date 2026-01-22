# DEPRECATED
from typing import Optional
# The functionality has moved to the package `cogs.admin` (see `cogs/admin/cog.py`).
# This shim is left temporarily for compatibility but can be removed.

raise ImportError("cogs.admin is deprecated; use cogs.admin.cog instead. Please update your load paths.")

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

class SearchUserModal(Modal):
    """Modal for searching guild members by name/username"""
    query = TextInput(
        label="Nombre o Usuario",
        placeholder="Escribe para filtrar...",
        required=True,
        max_length=100
    )
    
    def __init__(self, cog, user_type: str, selected_callback):
        # Definir el título basado en user_type
        from uniguard.localization import t
        titles = {
            "student": t('modal.search_student_title'),
            "sponsor": t('modal.search_sponsor_title'),
            "guest": t('modal.search_guest_title')
        }
        title = titles.get(user_type, t('modal.search_title'))
        super().__init__(title=title)
        
        # Cambiar placeholder según el tipo
        placeholders = {
            "student": "Escribe el nombre o username del alumno...",
            "sponsor": "Escribe el nombre o username del PADRINO...",
            "guest": "Escribe el nombre o username del INVITADO..."
        }
        self.query.placeholder = placeholders.get(user_type, "Escribe para filtrar...")
        
        self.cog = cog
        self.user_type = user_type
        self.selected_callback = selected_callback
    
    async def on_submit(self, interaction: discord.Interaction):
        # Primero responder a la interacción del modal
        await interaction.response.defer(ephemeral=True)
        
        query = self.query.value.lower().strip()
        guild = interaction.guild
        
        if not guild:
            await interaction.followup.send("❌ Este comando solo funciona en servidores.", ephemeral=True)
            return
        
        if not query:
            await interaction.followup.send("❌ Debes escribir algo para buscar.", ephemeral=True)
            return
        
        # Filter members by name or username
        matches = []
        for member in guild.members:
            if (query in member.display_name.lower() or 
                query in member.name.lower() or
                query in str(member.id)):
                matches.append(member)
        
        if not matches:
            await interaction.followup.send(f"❌ No encontré usuarios que coincidan con '{query}'.", ephemeral=True)
            return
        
        # Create select menu with matches (max 25 options)
        options = [
            discord.SelectOption(
                label=member.display_name[:100],
                description=f"@{member.name} (ID: {member.id})"[:100],
                value=str(member.id)
            )
            for member in matches[:25]
        ]
        
        # Usar una clase anidada para el View del select
        class UserSelectView(View):
            def __init__(self, cog, guild, options, callback, user_type: str):
                super().__init__(timeout=120)
                self.cog = cog
                self.guild = guild
                self.callback_fn = callback
                self.user_type = user_type
                
                # Crear el select dinámicamente
                placeholder_text = {
                    "student": "Selecciona un alumno...",
                    "sponsor": "Selecciona un padrino...",
                    "guest": "Selecciona un invitado..."
                }
                placeholder = placeholder_text.get(user_type, "Selecciona un usuario...")
                
                select = discord.ui.Select(
                    placeholder=placeholder,
                    options=options,
                    min_values=1,
                    max_values=1
                )
                select.callback = self.on_select
                self.add_item(select)
            
            async def on_select(self, interaction: discord.Interaction):
                user_id = int(interaction.data['values'][0])
                member = self.guild.get_member(user_id)
                if not member:
                    # Intentar fetch si no está en cache
                    try:
                        member = await self.guild.fetch_member(user_id)
                    except discord.NotFound:
                        await interaction.response.send_message("❌ Usuario no encontrado.", ephemeral=True)
                        return
                
                # IMPORTANTE: Aquí se maneja la interacción del select
                await self.callback_fn(member, interaction)
        
        # Mensaje descriptivo según el tipo
        messages = {
            "student": f"✅ Encontré {len(matches)} alumno(s). Selecciona uno:",
            "sponsor": f"✅ Encontré {len(matches)} posible(s) padrino(s). Selecciona uno:",
            "guest": f"✅ Encontré {len(matches)} posible(s) invitado(s). Selecciona uno:"
        }
        message = messages.get(self.user_type, f"✅ Encontré {len(matches)} usuario(s). Selecciona uno:")
        
        # Enviar el view con el select
        await interaction.followup.send(
            message,
            view=UserSelectView(self.cog, guild, options, self.selected_callback, self.user_type),
            ephemeral=True
        )

class SearchModal(Modal, title="🔎 Buscar en Lista"):
    query = TextInput(label="Término", placeholder="ID, Email, Nombre, Padrino...", required=False)
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
    async def on_submit(self, interaction: discord.Interaction):
        query = str(self.query.value or "").strip()
        if not query:
            await interaction.response.send_message("❌ Debes escribir algo para buscar.", ephemeral=True)
            return
        self.cog.query = query
        self.cog.page = 0
        await interaction.response.defer()
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res

class AddGuestModal(Modal, title="🤝 Registrar Invitado"):
    guest_mc = TextInput(label="Minecraft (Java)", placeholder="NombreExacto", required=True, max_length=16)
    real_name = TextInput(label="Nombre Real", placeholder="Juan Pérez", required=True, max_length=100)

    def __init__(self, cog, sponsor_user: discord.Member, guest_user: discord.Member):
        super().__init__()
        self.cog = cog
        self.sponsor_user = sponsor_user
        self.guest_user = guest_user

    async def on_submit(self, interaction: discord.Interaction):
        # Validate both sponsor and guest are in the guild
        if not interaction.guild:
            await interaction.response.send_message("❌ Este comando solo funciona en servidores.", ephemeral=True)
            return
        
        # Check if sponsor is still in guild
        if not interaction.guild.get_member(self.sponsor_user.id):
            await interaction.response.send_message("❌ El padrino no está en el servidor.", ephemeral=True)
            return
        
        # Check if guest is still in guild
        if not interaction.guild.get_member(self.guest_user.id):
            await interaction.response.send_message("❌ El invitado no está en el servidor.", ephemeral=True)
            return
        
        mc_name = self.guest_mc.value.strip()

        # 1. Base de Datos
        ok, msg = await db.add_guest_user(
            self.guest_user.id, mc_name, self.real_name.value, self.sponsor_user.id
        )
        
        if ok:
            # 2. Gestión de Discord (Centralizada)
            discord_log = await self.cog.manage_discord_user(
                guild=interaction.guild,
                user_id=self.guest_user.id,
                action="add_guest",
                mc_name=mc_name
            )
            await interaction.response.send_message(f"✅ {msg}\n{discord_log}", ephemeral=True)
            res = self.cog.render_panel(interaction)
            if inspect.isawaitable(res):
                await res
        else:
            await interaction.response.send_message(f"❌ Error DB: {msg}", ephemeral=True)

class AddStudentModal(Modal, title="🎓 Registrar Alumno Manual"):
    email = TextInput(label="Email PUCV", placeholder="nombre@mail.pucv.cl", required=True)
    mc = TextInput(label="Minecraft", required=True, max_length=16)

    def __init__(self, cog, student_user: discord.Member):
        super().__init__()
        self.cog = cog
        self.student_user = student_user

    async def on_submit(self, interaction):
        if not validate_university_email(self.email.value):
            return await interaction.response.send_message("❌ Email inválido.", ephemeral=True)

        mc_name = self.mc.value.strip()

        # 1. Base de Datos
        ok = await db.update_or_insert_user(self.email.value, self.student_user.id, mc_name, None, u_type='student')
        
        if ok:
            # 2. Gestión de Discord
            discord_log = await self.cog.manage_discord_user(
                guild=interaction.guild,
                user_id=self.student_user.id,
                action="add_student",
                mc_name=mc_name
            )
            await interaction.response.send_message(f"✅ Alumno agregado.\n{discord_log}", ephemeral=True)
            await self.cog.render_panel(interaction)
        else:
            await interaction.response.send_message("❌ Error guardando en DB.", ephemeral=True)

class SuspensionReasonModal(Modal, title="⛔ Razón de Suspensión"):
    """Modal for entering suspension reason"""
    reason = TextInput(
        label="Razón de la suspensión",
        placeholder="Ej: Comportamiento inapropiado, uso de cheats, etc.",
        required=True,
        max_length=256,
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, cog, uid):
        super().__init__()
        self.cog = cog
        self.uid = uid
    
    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value.strip()
        if not reason:
            await interaction.response.send_message("❌ Debes proporcionar una razón.", ephemeral=True)
            return
        
        # Save suspension reason to database
        reason_ok = await db.set_suspension_reason(int(self.uid), reason)
        flag_ok = await db.set_whitelist_flag(int(self.uid), False)  # Suspend the player
        
        if not (reason_ok and flag_ok):
            await interaction.response.send_message("❌ Error al guardar suspensión. Verifica logs.", ephemeral=True)
            return
        
        await interaction.response.send_message(
            f"⛔ **Jugador suspendido**\n**Razón:** {reason}",
            ephemeral=True
        )
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res

class ConfirmDeleteModal(Modal, title="⚠️ Confirmar Eliminación"):
    """Modal para confirmar la eliminación de un usuario"""
    confirmation = TextInput(
        label="Escribe 'sí' o 'yes' para confirmar eliminación",
        placeholder="sí",
        required=True,
        max_length=10
    )

    def __init__(self, cog, uid, user_display: str):
        super().__init__()
        self.cog = cog
        self.uid = uid
        self.user_display = user_display

    async def on_submit(self, interaction: discord.Interaction):
        import unicodedata
        value = self.confirmation.value or ""
        norm = ''.join(c for c in unicodedata.normalize('NFD', value) if unicodedata.category(c) != 'Mn').strip().lower()
        allowed = {'si', 's', 'yes', 'y'}
        if norm not in allowed:
            await interaction.response.send_message(t('errors.cancelled_confirm', confirm="sí"), ephemeral=True)
            return
        
        if not interaction.guild:
            await interaction.response.send_message("❌ Error: No hay servidor disponible.", ephemeral=True)
            return
        
        # 1. DB Delete
        db_success = await db.full_user_delete(self.uid)
        if not db_success:
            await interaction.response.send_message("❌ Error al eliminar del BD. Verifica logs.", ephemeral=True)
            return
        
        # 2. Discord Cleanup
        log = await self.cog.manage_discord_user(
            guild=interaction.guild,
            user_id=int(self.uid),
            action="delete"
        )
        
        await interaction.response.send_message(
            f"🗑 **Usuario eliminado completamente**\n{self.user_display}\n{log}", 
            ephemeral=True
        )
        self.cog.mode = "list"
        self.cog.selected_uid = None
        await self.cog.render_panel(interaction)

class EditMCModal(Modal, title="✏️ Editar Minecraft"):
    new_name = TextInput(label="Nuevo Nombre", required=True, max_length=16)

    def __init__(self, cog, uid):
        super().__init__()
        self.cog = cog
        self.uid = uid

    async def on_submit(self, interaction):
        # Actualiza solo el nombre, mantiene lo demás
        mc_name = self.new_name.value.strip()
        await db.update_or_insert_user(None, int(self.uid), mc_name)
        
        # Intentar actualizar nick en discord
        log = await self.cog.manage_discord_user(
            guild=interaction.guild,
            user_id=int(self.uid),
            action="update_nick",
            mc_name=mc_name
        )
        
        await interaction.response.send_message(f"✅ Nombre actualizado.\n{log}", ephemeral=True)
        await self.cog.render_panel(interaction)

# --- CONFIGURACIÓN ---

class ConfigNumberModal(Modal, title="⚙️ Editar Valor"):
    """Modal para editar valores numéricos en configuración"""
    value_input = TextInput(
        label="Nuevo Valor",
        placeholder="0",
        required=True,
        max_length=20
    )
    
    def __init__(self, cog, config_path: str, label: str):
        super().__init__()
        self.cog = cog
        self.config_path = config_path
        self.label = label
        self.value_input.label = label
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.value_input.value.strip())
            config.set(self.config_path, value)
            await interaction.response.send_message(
                f"✅ {self.label} actualizado a: **{value}**",
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ El valor debe ser un número entero.",
                ephemeral=True
            )

class ConfigChannelSelectView(View):
    """Vista para seleccionar un canal por búsqueda"""
    def __init__(self, cog, config_path: str, guild: discord.Guild, label: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.config_path = config_path
        self.guild = guild
        self.label = label
        
        # Crear select con todos los canales de texto
        channels = [
            discord.SelectOption(
                label=channel.name[:100],
                description=f"ID: {channel.id}",
                value=str(channel.id)
            )
            for channel in guild.text_channels[:25]
        ]
        
        if not channels:
            return
        
        select = discord.ui.Select(
            placeholder=f"Selecciona {label}...",
            options=channels,
            min_values=1,
            max_values=1
        )
        select.callback = self.on_select
        self.add_item(select)
    
    async def on_select(self, interaction: discord.Interaction):
        try:
            # For Select components, values are in interaction data
            if interaction.data and "values" in interaction.data:
                values = interaction.data["values"]
                if values:
                    channel_id = int(values[0])
                    config.set(self.config_path, channel_id)
                    channel = self.guild.get_channel(channel_id)
                    if channel:
                        await interaction.response.send_message(
                            f"✅ {self.label} actualizado a: **#{channel.name}**",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message("Error: Channel not found", ephemeral=True)
                else:
                    await interaction.response.send_message("Error: No value selected", ephemeral=True)
            else:
                await interaction.response.send_message("Error: No data in interaction", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in on_select: {e}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class ConfigRoleSelectView(View):
    """Vista para seleccionar un rol por búsqueda"""
    def __init__(self, cog, config_path: str, guild: discord.Guild, label: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.config_path = config_path
        self.guild = guild
        self.label = label
        
        # Crear select con todos los roles
        roles = [
            discord.SelectOption(
                label=role.name[:100],
                description=f"ID: {role.id}",
                value=str(role.id)
            )
            for role in guild.roles[1:][:25]  # Saltar @everyone
        ]
        
        if not roles:
            return
        
        select = discord.ui.Select(
            placeholder=f"Selecciona {label}...",
            options=roles,
            min_values=1,
            max_values=1
        )
        select.callback = self.on_select
        self.add_item(select)
    
    async def on_select(self, interaction: discord.Interaction):
        try:
            # For Select components, values are in interaction data
            if interaction.data and "values" in interaction.data:
                values = interaction.data["values"]
                if values:
                    role_id = int(values[0])
                    config.set(self.config_path, role_id)
                    role = self.guild.get_role(role_id)
                    if role:
                        await interaction.response.send_message(
                            f"✅ {self.label} actualizado a: **{role.name}**",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message("Error: Role not found", ephemeral=True)
                else:
                    await interaction.response.send_message("Error: No value selected", ephemeral=True)
            else:
                await interaction.response.send_message("Error: No data in interaction", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in on_select: {e}")
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

# -----------------------------
# VISTAS (Botones)
# -----------------------------

class SelectUser(Select):
    def __init__(self, cog, rows):
        options = []
        for row in rows:
            try:
                email, uid, user, u_type, sponsor, r_name = row
            except ValueError:
                logger.warning(f"Invalid row structure in SelectUser: {row}")
                continue
            
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

        # Navegación - Fila 1 (3 botones)
        self.add_item(Button(label="◀", style=discord.ButtonStyle.secondary, disabled=not has_prev, row=1, custom_id="prev_btn")).children[-1].callback = self.prev_cb
        self.add_item(Button(label="🔄 Refrescar", style=discord.ButtonStyle.secondary, row=1, custom_id="reload_btn")).children[-1].callback = self.reload_cb
        self.add_item(Button(label="▶", style=discord.ButtonStyle.secondary, disabled=not has_next, row=1, custom_id="next_btn")).children[-1].callback = self.next_cb
        
        # Herramientas - Fila 2 (3 botones)
        self.add_item(Button(label="🔎 Buscar", style=discord.ButtonStyle.primary, row=2, custom_id="search_btn")).children[-1].callback = self.search_cb
        self.add_item(Button(label="🧹 Limpiar", style=discord.ButtonStyle.secondary, row=2, custom_id="clear_btn")).children[-1].callback = self.clear_cb
        self.add_item(Button(label="⚙️ Configuración", style=discord.ButtonStyle.primary, row=2, custom_id="config_btn")).children[-1].callback = self.config_cb

        # Acciones - Fila 3 (2 botones)
        self.add_item(Button(label="🎓 +Alumno", style=discord.ButtonStyle.success, row=3, custom_id="add_s_btn")).children[-1].callback = self.add_student_cb
        self.add_item(Button(label="🤝 +Invitado", style=discord.ButtonStyle.success, row=3, custom_id="add_g_btn")).children[-1].callback = self.add_guest_cb
    
    async def prev_cb(self, interaction):
        await interaction.response.defer()
        self.cog.page -= 1
        await self.cog.render_panel(interaction)
    
    async def next_cb(self, interaction):
        await interaction.response.defer()
        self.cog.page += 1
        await self.cog.render_panel(interaction)
    
    async def reload_cb(self, interaction):
        await interaction.response.defer()
        await self.cog.render_panel(interaction)
    
    async def search_cb(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo administradores pueden buscar.", ephemeral=True)
            return
        await interaction.response.send_modal(SearchModal(self.cog))
    
    async def clear_cb(self, interaction):
        await interaction.response.defer()
        self.cog.query = ""
        self.cog.page = 0
        await self.cog.render_panel(interaction)
    
    async def config_cb(self, interaction):
        """Abrir menú de configuración"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo administradores pueden acceder a configuración.", ephemeral=True)
            return
        
        if not interaction.guild:
            await interaction.response.send_message("❌ No hay servidor disponible.", ephemeral=True)
            return
        
        # Crear embed con opciones
        embed = discord.Embed(
            title="⚙️ Panel de Configuración",
            description="Selecciona qué quieres configurar:\n\n" +
                       "**Roles** - IDs de roles para diferentes estados\n" +
                       "**Canales** - IDs de canales importantes\n" +
                       "**Límites** - Máximos de padrinos, intentos, etc.\n" +
                       "**Sistema** - Configuración del bot",
            color=0x3498db
        )
        
        view = ConfigMenu(self.cog, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    async def add_student_cb(self, interaction: discord.Interaction):
        """Search for student to register"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo administradores pueden agregar alumnos.", ephemeral=True)
            return
        
        async def on_student_selected(student_user: discord.Member, select_interaction: discord.Interaction):
            # IMPORTANTE: Siempre verificar si ya se respondió
            if select_interaction.response.is_done():
                await select_interaction.followup.send(
                    "⚠️ Ya estás en proceso de registro. Cierra el modal actual.",
                    ephemeral=True
                )
                return
            
            # Enviar el modal de registro de alumno
            await select_interaction.response.send_modal(
                AddStudentModal(self.cog, student_user)
            )
        
        # Abrir modal de búsqueda
        await interaction.response.send_modal(
            SearchUserModal(self.cog, "student", on_student_selected)
        )
    
    async def add_guest_cb(self, interaction: discord.Interaction):
        """Search for sponsor first, then guest"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo administradores pueden agregar invitados.", ephemeral=True)
            return
        
        async def on_sponsor_selected(sponsor_user: discord.Member, select_interaction: discord.Interaction):
            # Primero mostrar información del padrino seleccionado
            await select_interaction.response.send_message(
                f"✅ **Padrino seleccionado:** {sponsor_user.mention} ({sponsor_user.name})\n\n"
                "Ahora busca al **invitado** que quieres registrar:",
                ephemeral=True
            )
            
            async def on_guest_selected(guest_user: discord.Member, guest_select_interaction: discord.Interaction):
                if guest_select_interaction.response.is_done():
                    await guest_select_interaction.followup.send(
                        "⚠️ Ya estás en proceso de registro. Cierra el modal actual.",
                        ephemeral=True
                    )
                    return
                
                # Mostrar resumen antes de abrir el formulario final
                embed = discord.Embed(
                    title="🤝 Confirmar Registro de Invitado",
                    description=f"**Padrino:** {sponsor_user.mention}\n"
                              f"**Invitado:** {guest_user.mention}\n\n"
                              "Ahora ingresa los datos del invitado:",
                    color=0x3498db
                )
                
                await guest_select_interaction.response.send_message(
                    embed=embed,
                    ephemeral=True
                )
                
                # Abrir modal para datos del invitado
                await guest_select_interaction.followup.send_modal(
                    AddGuestModal(self.cog, sponsor_user, guest_user)
                )
            
            # Buscar al invitado
            await select_interaction.followup.send_modal(
                SearchUserModal(self.cog, "guest", on_guest_selected)
            )
        
        # Abrir modal de búsqueda del padrino
        await interaction.response.send_modal(
            SearchUserModal(self.cog, "sponsor", on_sponsor_selected)
        )

# --- Vistas para importación por DM ---

class ImportDMView(View):
    """Vista para manejar importación por DM"""
    def __init__(self, cog):
        super().__init__(timeout=180)  # 3 minutos de timeout
        self.cog = cog
        self.mode = None
    
    @discord.ui.button(label="📝 Agregar nuevos", style=discord.ButtonStyle.success)
    async def add_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "add"
        self.cog.waiting_for_csv[interaction.user.id] = self.mode
        await interaction.response.send_message(
            "✅ **Modo: Agregar nuevos**\n\n"
            "Por favor, adjunta el archivo CSV a este mensaje.\n"
            "Solo se agregarán registros que no existan en la base de datos.\n\n"
            "⏱️ **Tienes 3 minutos** para adjuntar el archivo.",
            ephemeral=False
        )
        self.stop()
    
    @discord.ui.button(label="⚠️ Sobrescribir todo", style=discord.ButtonStyle.danger)
    async def overwrite_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "overwrite"
        self.cog.waiting_for_csv[interaction.user.id] = self.mode
        await interaction.response.send_message(
            "⚠️ **Modo: Sobrescribir todo**\n\n"
            "¡ATENCIÓN! Esto borrará **todos los registros actuales** y los reemplazará con los del archivo.\n\n"
            "Por favor, adjunta el archivo CSV a este mensaje.\n"
            "⏱️ **Tienes 3 minutos** para adjuntar el archivo.",
            ephemeral=False
        )
        self.stop()
    
    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.cog.waiting_for_csv:
            del self.cog.waiting_for_csv[interaction.user.id]
        await interaction.response.send_message("❌ Importación cancelada.", ephemeral=False)
        self.stop()

class ImportFallbackView(View):
    """Vista alternativa cuando no hay DMs disponibles"""
    def __init__(self, cog, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel = channel
    
    @discord.ui.button(label="📁 Importar CSV en canal", style=discord.ButtonStyle.primary)
    async def import_in_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Enviar mensaje en el canal (no efímero)
        await interaction.response.defer(ephemeral=True)
        
        # Enviar mensaje normal en el canal
        message = await self.channel.send(
            f"{interaction.user.mention} está importando un CSV.\n\n"
            "**Modos disponibles:**\n"
            "• `add` - Agregar solo registros nuevos\n"
            "• `overwrite` - Borrar todo y reemplazar\n\n"
            "Responde a este mensaje con el archivo CSV y escribe el modo (ej: `add` o `overwrite`).",
        )
        
        # Guardar referencia
        self.cog.pending_imports[message.id] = {
            'user_id': interaction.user.id,
            'channel_id': self.channel.id,
            'original_interaction': interaction  # Guardar referencia
        }
        
        await interaction.followup.send(
            f"✅ He creado un mensaje en {self.channel.mention} para que adjuntes el archivo.",
            ephemeral=True
        )
        self.stop()

class ConfigMenu(View):
    """Menú principal de configuración"""
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
    
    @discord.ui.button(label="👤 Roles", style=discord.ButtonStyle.primary, row=0)
    async def roles_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigRolesMenu(self.cog, self.guild)
        embed = discord.Embed(
            title="⚙️ Configuración de Roles",
            description="Selecciona qué rol quieres cambiar",
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="📢 Canales", style=discord.ButtonStyle.primary, row=0)
    async def channels_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigChannelsMenu(self.cog, self.guild)
        embed = discord.Embed(
            title="⚙️ Configuración de Canales",
            description="Selecciona qué canal quieres cambiar",
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="📊 Límites", style=discord.ButtonStyle.primary, row=1)
    async def limits_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigLimitsMenu(self.cog)
        embed = discord.Embed(
            title="⚙️ Configuración de Límites",
            description="Selecciona qué límite quieres cambiar",
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🔧 Sistema", style=discord.ButtonStyle.primary, row=1)
    async def system_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigSystemMenu(self.cog)
        embed = discord.Embed(
            title="⚙️ Configuración de Sistema",
            description="Selecciona qué opción de sistema quieres cambiar",
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="⬇️ Exportar CSV", style=discord.ButtonStyle.success, row=2)
    async def export_csv_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Confirmación antes de exportar
        member = getattr(interaction, 'user', None)
        if not (isinstance(member, discord.Member) and member.guild_permissions.administrator):
            await interaction.response.send_message("❌ Solo administradores pueden exportar.", ephemeral=True)
            return
        await interaction.response.send_message(
            "¿Estás seguro que quieres exportar la base de datos a CSV?",
            view=ExportConfirmView(self.cog), ephemeral=True
        )

    @discord.ui.button(label="⬆️ Importar CSV", style=discord.ButtonStyle.danger, row=2)
    async def import_csv_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Confirmación antes de importar
        member = getattr(interaction, 'user', None)
        if not (isinstance(member, discord.Member) and member.guild_permissions.administrator):
            await interaction.response.send_message("❌ Solo administradores pueden importar.", ephemeral=True)
            return
        
        # Primero responder que vamos a enviar un DM
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Intentar enviar DM
            await member.send(
                "📁 **Importar CSV**\n\n"
                "Por favor selecciona el modo de importación:\n\n"
                "• **📝 Agregar nuevos**: Solo se agregarán registros que no existan\n"
                "• **⚠️ Sobrescribir todo**: Se borrarán todos los registros actuales\n\n"
                "Luego podrás adjuntar el archivo CSV directamente en este chat.",
                view=ImportDMView(self.cog)
            )
            
            await interaction.followup.send("📩 Te he enviado un mensaje privado para continuar con la importación.", ephemeral=True)
            
        except discord.Forbidden:
            # Si no se pueden enviar DMs, usar un canal temporal
            await interaction.followup.send(
                "❌ No puedo enviarte mensajes privados.\n\n"
                "**Habilita los DMs en:**\n"
                "1. Ajustes de Usuario → Privacidad\n"
                "2. Ajustes del Servidor → Privacidad\n\n"
                "O usa el botón 'Importar CSV en canal' si ya tienes un archivo listo.",
                view=ImportFallbackView(self.cog, interaction.channel),
                ephemeral=True
            )

# --- Vistas de confirmación para exportar/importar ---
class ExportConfirmView(View):
    def __init__(self, cog):
        super().__init__(timeout=30)
        self.cog = cog
    @discord.ui.button(label="✅ Sí, exportar", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.export_csv(interaction)
        self.stop()
    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Exportación cancelada.", ephemeral=True)
        self.stop()

# Vista para recibir el archivo y llamar a import_csv con el modo seleccionado
class ImportFileView(View):
    def __init__(self, cog, mode):
        super().__init__(timeout=120)
        self.cog = cog
        self.mode = mode
    @discord.ui.button(label="Procesar archivo adjunto", style=discord.ButtonStyle.primary)
    async def process(self, interaction: discord.Interaction, button: discord.ui.Button):
        attachments = []
        msg = getattr(interaction, 'message', None)
        if msg and hasattr(msg, 'attachments') and msg.attachments:
            attachments = msg.attachments
        if not attachments:
            await interaction.response.send_message("❌ Debes adjuntar un archivo CSV a este mensaje.", ephemeral=True)
            return
        attachment = attachments[0]
        await self.cog.import_csv(interaction, attachment, self.mode)

class ConfigRolesMenu(View):
    """Menú para configurar roles"""
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
    
    @discord.ui.button(label="✅ Verificado", style=discord.ButtonStyle.success)
    async def verified_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigRoleSelectView(self.cog, "roles.verified", self.guild, "Rol Verificado")
        await interaction.followup.send("Selecciona el rol para usuarios **verificados**:", view=view, ephemeral=True)
    
    @discord.ui.button(label="❌ No Verificado", style=discord.ButtonStyle.danger)
    async def not_verified_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigRoleSelectView(self.cog, "roles.not_verified", self.guild, "Rol No Verificado")
        await interaction.followup.send("Selecciona el rol para usuarios **no verificados**:", view=view, ephemeral=True)
    
    @discord.ui.button(label="🤝 Invitado", style=discord.ButtonStyle.blurple)
    async def guest_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigRoleSelectView(self.cog, "roles.guest", self.guild, "Rol Invitado")
        await interaction.followup.send("Selecciona el rol para **invitados**:", view=view, ephemeral=True)

class ConfigChannelsMenu(View):
    """Menú para configurar canales"""
    def __init__(self, cog, guild: discord.Guild):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
    
    @discord.ui.button(label="🎓 Verificación", style=discord.ButtonStyle.success)
    async def verification_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigChannelSelectView(self.cog, "channels.verification", self.guild, "Canal de Verificación")
        await interaction.followup.send("Selecciona el canal de **verificación**:", view=view, ephemeral=True)
    
    @discord.ui.button(label="🛠️ Administración", style=discord.ButtonStyle.blurple)
    async def admin_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigChannelSelectView(self.cog, "channels.admin", self.guild, "Canal de Admin")
        await interaction.followup.send("Selecciona el canal de **administración**:", view=view, ephemeral=True)

class ConfigLimitsMenu(View):
    """Menú para configurar límites"""
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog
    
    @discord.ui.button(label="🤝 Guests por Padrino", style=discord.ButtonStyle.primary)
    async def max_guests(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ConfigNumberModal(self.cog, "limits.max_guests_per_sponsor", "Máximo de Invitados por Padrino")
        )
    
    @discord.ui.button(label="❌ Intentos de Verificación", style=discord.ButtonStyle.danger)
    async def max_attempts(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ConfigNumberModal(self.cog, "limits.verification_max_attempts", "Máximo de Intentos de Verificación")
        )

class ConfigSystemMenu(View):
    """Menú para configurar opciones del sistema"""
    def __init__(self, cog):
        super().__init__(timeout=60)
        self.cog = cog
    
    @discord.ui.button(label="📊 Activar/Desactivar Status", style=discord.ButtonStyle.blurple)
    async def toggle_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = config.get("system.enable_status_msg", True)
        new_value = not current
        config.set("system.enable_status_msg", new_value)
        status_text = "🟢 ACTIVADO" if new_value else "🔴 DESACTIVADO"
        await interaction.response.send_message(
            f"✅ Status de sistema: **{status_text}**",
            ephemeral=True
        )
    
    @discord.ui.button(label="⏱️ Intervalo del Status", style=discord.ButtonStyle.blurple)
    async def status_interval(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ConfigNumberModal(self.cog, "system.status_interval", "Intervalo del Status (segundos)")
        )

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
        
        if flag == 1:  # Currently active - show suspension reason modal
            await interaction.response.send_modal(SuspensionReasonModal(self.cog, self.uid))
        else:  # Currently suspended - reactivate without reason
            flag_ok = await db.set_whitelist_flag(self.uid, True)
            reason_ok = await db.set_suspension_reason(self.uid, None)  # Clear suspension reason
            if not (flag_ok and reason_ok):
                await interaction.response.send_message("❌ Error al activar usuario. Verifica logs.", ephemeral=True)
                return
            await interaction.response.send_message("🔓 **Jugador activado**", ephemeral=True)
            await self.cog.render_panel(interaction)

    @discord.ui.button(label="🗑 ELIMINAR TOTALMENTE", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction, button):
        # Obtener datos del usuario para mostrar en confirmación
        rows = await db.list_verified_players()
        user_display = "Usuario desconocido"
        
        for row in rows:
            try:
                email, uid, user, u_type, sponsor, r_name = row
                if str(uid) == str(self.uid):
                    user_display = f"**{user}** ({email})" if user else f"**{email}**"
                    break
            except (ValueError, TypeError):
                continue
        
        # Mostrar modal de confirmación
        await interaction.response.send_modal(ConfirmDeleteModal(self.cog, self.uid, user_display))

# -----------------------------
# COG PRINCIPAL
# -----------------------------
class AdminPanelCog(commands.Cog):
    async def export_csv(self, interaction: discord.Interaction):
        """Exporta la base de datos a CSV y la envía como archivo adjunto con timestamp."""
        import io, csv, datetime
        try:
            rows = await db.list_verified_players()
            if not rows:
                await interaction.followup.send("No hay datos para exportar.", ephemeral=True)
                return
            # Definir columnas
            header = ["email", "user_id", "user", "type", "sponsor_id", "real_name"]
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
            output.seek(0)
            # Timestamp
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"uniguard_export_{ts}.csv"
            file = discord.File(fp=io.BytesIO(output.getvalue().encode("utf-8")), filename=filename)
            await interaction.followup.send(
                content=f"✅ Exportación completada. Archivo generado: `{filename}`",
                file=file,
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error exportando CSV: {e}", ephemeral=True)

    async def import_csv(self, interaction: discord.Interaction, attachment: discord.Attachment, mode: str):
        """Importa datos desde un archivo CSV adjunto, validando formato y columnas. Modo: 'add' o 'overwrite'"""
        import io, csv
        try:
            if not attachment.filename.endswith('.csv'):
                await interaction.followup.send("❌ El archivo debe ser .csv", ephemeral=True)
                return
            data = await attachment.read()
            content = data.decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            if not rows or len(rows) < 2:
                await interaction.followup.send("❌ El archivo CSV está vacío o incompleto.", ephemeral=True)
                return
            header = rows[0]
            expected = ["email", "user_id", "user", "type", "sponsor_id", "real_name"]
            if header != expected:
                await interaction.followup.send(f"❌ Formato incorrecto. Se esperaban columnas: {expected}", ephemeral=True)
                return
            # Validar tipos básicos
            parsed = []
            for i, row in enumerate(rows[1:], start=2):
                if len(row) != len(expected):
                    await interaction.followup.send(f"❌ Fila {i} tiene columnas incorrectas.", ephemeral=True)
                    return
                try:
                    user_id = int(row[1])
                except Exception as e:
                    await interaction.followup.send(f"❌ Fila {i}: user_id inválido ({e})", ephemeral=True)
                    return
                parsed.append({
                    "email": row[0],
                    "user_id": user_id,
                    "user": row[2],
                    "type": row[3],
                    "sponsor_id": int(row[4]) if row[4] else None,
                    "real_name": row[5]
                })
            # --- Lógica real de importación ---
            from uniguard import db
            await db._ensure_pool_or_log()
            pool = db._POOL
            if pool is None:
                await interaction.followup.send("❌ Error: la base de datos no está inicializada.", ephemeral=True)
                return
            if mode == "overwrite":
                # Borrar todas las filas de verifications y noble_whitelist
                try:
                    async with pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("DELETE FROM verifications")
                            await cur.execute("DELETE FROM noble_whitelist")
                        await conn.commit()
                except Exception as e:
                    await interaction.followup.send(f"❌ Error al limpiar tablas: {e}", ephemeral=True)
                    return
            # Insertar registros
            added, skipped, failed = 0, 0, 0
            failures = []
            for rec in parsed:
                try:
                    # Si modo add, saltar si ya existe user_id
                    if mode == "add":
                        exists = await db.check_existing_user(rec["user_id"])
                        if exists:
                            skipped += 1
                            continue

                    # Si es invitado, validar campos necesarios y usar la rutina que valida padrino y límites
                    if rec["type"] == "guest":
                        if not rec.get("user"):
                            failed += 1
                            failures.append(f"{rec.get('user_id', 'unknown')}: missing guest username")
                            continue
                        if rec.get("sponsor_id") is None:
                            failed += 1
                            failures.append(f"{rec.get('user_id', 'unknown')}: missing sponsor_id")
                            continue
                        ok, msg = await db.add_guest_user(rec["user_id"], rec["user"], rec["real_name"], rec["sponsor_id"])
                        if not ok:
                            failed += 1
                            failures.append(f"{rec['user_id']}: {msg}")
                            continue
                    else:
                        # Insertar o actualizar alumno (tipo student)
                        await db.update_or_insert_user(
                            rec["email"] if rec["type"] == "student" else None,
                            rec["user_id"],
                            rec["user"],
                            rec.get("career_code", None),
                            u_type='student'
                        )
                    added += 1
                except Exception as e:
                    failed += 1
                    failures.append(f"{rec.get('user_id', 'unknown')}: {e}")

            summary = f"✅ Importación finalizada. Agregados: {added}, Saltados: {skipped}, Fallidos: {failed}."
            if failures:
                # Truncate details to avoid very long messages
                details = "\n".join(failures)[:1500]
                summary += "\n\nErrores:\n" + details
            await interaction.followup.send(summary, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error procesando CSV: {e}", ephemeral=True)
    
    def __init__(self, bot):
        self.bot = bot
        self.query = ""
        self.page = 0
        self.mode = "list"
        self.selected_uid = None
        self._msg = None
        # Nuevo: Para rastrear importaciones pendientes
        self.waiting_for_csv = {}  # {user_id: mode}
        self.pending_imports = {}  # {message_id: {user_id, channel_id}}
    
    async def cog_load(self):
        self.bot.loop.create_task(self.init_panel())

    # --- LISTENER para manejar archivos CSV en DMs y canales ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Manejar archivos CSV adjuntos en DMs o canales"""
        
        # Ignorar mensajes de bots
        if message.author.bot:
            return
        
        # 1. Verificar si es un DM y el usuario está esperando un CSV
        if isinstance(message.channel, discord.DMChannel):
            if message.author.id in self.waiting_for_csv and message.attachments:
                mode = self.waiting_for_csv[message.author.id]
                attachment = message.attachments[0]
                
                # Limpiar el estado de espera
                del self.waiting_for_csv[message.author.id]
                
                # Procesar el archivo
                await self.process_csv_import_dm(message, attachment, mode)
        
        # 2. Verificar si es un mensaje en un canal con importación pendiente
        elif message.reference and message.reference.message_id in self.pending_imports:
            pending = self.pending_imports[message.reference.message_id]
            
            # Verificar que sea el usuario correcto
            if message.author.id != pending['user_id']:
                return
            
            # Buscar el modo en el contenido del mensaje
            content = message.content.lower()
            mode = None
            if 'add' in content:
                mode = 'add'
            elif 'overwrite' in content:
                mode = 'overwrite'
            else:
                await message.channel.send("❌ Por favor especifica el modo: `add` o `overwrite`")
                return
            
            # Verificar que tenga un archivo adjunto
            if message.attachments:
                attachment = message.attachments[0]
                # Limpiar el estado de espera
                del self.pending_imports[message.reference.message_id]
                await self.process_csv_import_channel(message, attachment, mode)
    
    async def process_csv_import_dm(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Procesar un archivo CSV adjunto en DM"""
        try:
            # Notificar que estamos procesando
            processing_msg = await message.channel.send("📥 Procesando archivo...")
            
            # Llamar a la función de importación
            await self._import_csv_dm(message, attachment, mode)
            
            # Eliminar mensaje de procesamiento
            await processing_msg.delete()
            
        except Exception as e:
            error_msg = f"❌ Error al procesar el archivo: {str(e)[:100]}"
            await message.channel.send(error_msg)
    
    async def process_csv_import_channel(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Procesar un archivo CSV adjunto en canal"""
        try:
            # Notificar que estamos procesando
            processing_msg = await message.channel.send(f"{message.author.mention} Procesando archivo...")
            
            # Llamar a la función de importación
            await self._import_csv_channel(message, attachment, mode)
            
            # Eliminar mensaje de procesamiento
            await processing_msg.delete()
            
        except Exception as e:
            error_msg = f"❌ Error al procesar el archivo: {str(e)[:100]}"
            await message.channel.send(f"{message.author.mention} {error_msg}")
    
    async def _import_csv_dm(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Versión de import_csv para DM"""
        import io, csv
        try:
            if not attachment.filename.endswith('.csv'):
                await message.channel.send("❌ El archivo debe ser .csv")
                return
            
            data = await attachment.read()
            content = data.decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            
            if not rows or len(rows) < 2:
                await message.channel.send("❌ El archivo CSV está vacío o incompleto.")
                return
            
            header = rows[0]
            expected = ["email", "user_id", "user", "type", "sponsor_id", "real_name"]
            if header != expected:
                await message.channel.send(f"❌ Formato incorrecto. Se esperaban columnas: {expected}")
                return
            
            # Validar tipos básicos
            parsed = []
            for i, row in enumerate(rows[1:], start=2):
                if len(row) != len(expected):
                    await message.channel.send(f"❌ Fila {i} tiene columnas incorrectas.")
                    return
                try:
                    user_id = int(row[1])
                except Exception as e:
                    await message.channel.send(f"❌ Fila {i}: user_id inválido ({e})")
                    return
                parsed.append({
                    "email": row[0],
                    "user_id": user_id,
                    "user": row[2],
                    "type": row[3],
                    "sponsor_id": int(row[4]) if row[4] else None,
                    "real_name": row[5]
                })
            
            # Lógica real de importación
            from uniguard import db
            await db._ensure_pool_or_log()
            pool = db._POOL
            if pool is None:
                await message.channel.send("❌ Error: la base de datos no está inicializada.")
                return
            
            if mode == "overwrite":
                # Borrar todas las filas de verifications y noble_whitelist
                try:
                    async with pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute("DELETE FROM verifications")
                            await cur.execute("DELETE FROM noble_whitelist")
                        await conn.commit()
                except Exception as e:
                    await message.channel.send(f"❌ Error al limpiar tablas: {e}")
                    return
            
            # Insertar registros
            added, skipped, failed = 0, 0, 0
            failures = []
            for rec in parsed:
                try:
                    # Si modo add, saltar si ya existe user_id
                    if mode == "add":
                        exists = await db.check_existing_user(rec["user_id"])
                        if exists:
                            skipped += 1
                            continue

                    if rec["type"] == "guest":
                        if not rec.get("user"):
                            failed += 1
                            failures.append(f"{rec.get('user_id', 'unknown')}: missing guest username")
                            continue
                        if rec.get("sponsor_id") is None:
                            failed += 1
                            failures.append(f"{rec.get('user_id', 'unknown')}: missing sponsor_id")
                            continue
                        ok, msg = await db.add_guest_user(rec["user_id"], rec["user"], rec["real_name"], rec["sponsor_id"])
                        if not ok:
                            failed += 1
                            failures.append(f"{rec['user_id']}: {msg}")
                            continue
                    else:
                        # Insertar/actualizar alumno como 'student'
                        await db.update_or_insert_user(
                            rec["email"] if rec["type"] == "student" else None,
                            rec["user_id"],
                            rec["user"],
                            None,
                            u_type='student'
                        )
                    added += 1
                except Exception as e:
                    failed += 1
                    failures.append(f"{rec.get('user_id', 'unknown')}: {e}")

            summary = (
                f"✅ **Importación finalizada**\n\n"
                f"📊 **Resultados:**\n"
                f"• ✅ Agregados: **{added}**\n"
                f"• ⏭️ Saltados: **{skipped}**\n"
                f"• ❌ Fallidos: **{failed}**"
            )
            if failures:
                details = "\n".join(failures)[:1500]
                summary += "\n\nErrores:\n" + details
            await message.channel.send(summary)
            
            await message.channel.send(
                f"✅ **Importación finalizada**\n\n"
                f"📊 **Resultados:**\n"
                f"• ✅ Agregados: **{added}**\n"
                f"• ⏭️ Saltados: **{skipped}**\n"
                f"• ❌ Fallidos: **{failed}**"
            )
            
        except Exception as e:
            await message.channel.send(f"❌ Error procesando CSV: {str(e)[:200]}")
    
    async def _import_csv_channel(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Versión de import_csv para canal"""
        # Reutilizamos la misma lógica que _import_csv_dm pero con menciones
        await self._import_csv_dm(message, attachment, mode)

    # --- FUNCIÓN MAESTRA DE DISCORD ---
    async def manage_discord_user(self, guild: discord.Guild, user_id: int, action: str, mc_name: Optional[str] = None) -> str:
        """
        Maneja roles y nicks de forma centralizada y segura.
        action: 'add_student', 'add_guest', 'delete', 'update_nick'
        """
        if not guild:
            logger.error("manage_discord_user called without guild")
            return "⚠️ Error: No hay servidor de Discord."
        
        # 1. Obtener Miembro
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                return "⚠️ Usuario no está en el servidor de Discord."
            except Exception as e:
                logger.error(f"Error fetching member {user_id}: {e}")
                return f"⚠️ Error al obtener usuario: {e}"

        log = []
        
        # IDs de Roles desde Config
        rid_verified = int(self.bot.config.get('roles', {}).get('verified', 0))
        rid_not_ver = int(self.bot.config.get('roles', {}).get('not_verified', 0))
        rid_guest = int(self.bot.config.get('roles', {}).get('guest', 0))

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
                except Exception as e:
                    logger.warning(f"Could not change nickname for {user_id}: {e}")
                    log.append("(No pude cambiar nick)")
                
                # Roles
                try:
                    r_ver = get_role_smart(rid_verified, ["Alumno", "Verificado"])
                    r_not = get_role_smart(rid_not_ver, ["No Verificado"])
                    
                    if r_ver: 
                        await member.add_roles(r_ver)
                        log.append("Rol Alumno asignado.")
                    else: 
                        log.append("⚠️ ERROR: No encontré rol Alumno.")
                    
                    if r_not: await member.remove_roles(r_not)
                except Exception as e:
                    logger.error(f"Error assigning student roles to {user_id}: {e}")
                    log.append(f"⚠️ Error asignando roles: {e}")

            # --- AGREGAR INVITADO ---
            elif action == "add_guest":
                # Nickname
                try: await member.edit(nick=f"[INV] {mc_name}"[:32])
                except Exception as e:
                    logger.warning(f"Could not change nickname for {user_id}: {e}")
                    log.append("(No pude cambiar nick)")
                
                # Roles
                try:
                    r_guest = get_role_smart(rid_guest, ["Invitado", "Apadrinado", "🤝 Invitado"])
                    r_not = get_role_smart(rid_not_ver, ["No Verificado"])
                    
                    if r_guest: 
                        await member.add_roles(r_guest)
                        log.append(f"Rol Invitado ({r_guest.name}) asignado.")
                    else: 
                        log.append(f"⚠️ ERROR: No encontré rol Invitado (ID buscado: {rid_guest}).")
                    
                    if r_not: await member.remove_roles(r_not)
                except Exception as e:
                    logger.error(f"Error assigning guest roles to {user_id}: {e}")
                    log.append(f"⚠️ Error asignando roles: {e}")

            # --- ACTUALIZAR NICK ---
            elif action == "update_nick":
                # Detectar prefijo actual o poner uno por defecto
                curr_nick = member.display_name
                prefix = "[EST]"
                if "[INV]" in curr_nick or "[Ap]" in curr_nick: prefix = "[INV]"
                
                try: await member.edit(nick=f"{prefix} {mc_name}"[:32])
                except Exception as e:
                    logger.warning(f"Could not change nickname for {user_id}: {e}")
                    log.append("(No pude cambiar nick)")

        except discord.Forbidden:
            return "⚠️ Error de Permisos: El bot no tiene jerarquía suficiente."
        except Exception as e:
            return f"⚠️ Error desconocido: {e}"

        return " ".join(log)

    async def init_panel(self):
        """Reinicia el panel visual"""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)
        
        cid = self.bot.config.get('channels', {}).get('admin')
        if not cid: return

        channel = self.bot.get_channel(int(cid))
        if not channel: return

        try:
            async for msg in channel.history(limit=10):
                if msg.author == self.bot.user:
                    await msg.delete()
        except Exception as e:
            logger.warning(f"Error cleaning up channel history: {e}")

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
            
            # Show suspension reason if suspended
            if wl == 0:
                reason = await db.get_suspension_reason(uid)
                if reason:
                    embed.add_field(name="Razón de Suspensión", value=f"```{reason}```", inline=False)

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