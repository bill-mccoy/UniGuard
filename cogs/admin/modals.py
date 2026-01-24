import discord
from typing import Optional
import inspect
from discord.ui import Modal, TextInput
from uniguard import db, config
from uniguard.localization import t


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
            await interaction.followup.send(t('errors.only_in_server'), ephemeral=True)
            return
        
        if not query:
            await interaction.followup.send(t('errors.must_provide_query'), ephemeral=True)
            return
        
        # Filter members by name or username
        matches = []
        for member in guild.members:
            if (query in member.display_name.lower() or 
                query in member.name.lower() or
                query in str(member.id)):
                matches.append(member)
        
        if not matches:
            await interaction.followup.send(t('search.no_matches', query=query), ephemeral=True)
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
        class UserSelectView(discord.ui.View):
            def __init__(self, cog, guild, options, callback, user_type: str):
                super().__init__(timeout=120)
                self.cog = cog
                self.guild = guild
                self.callback_fn = callback
                self.user_type = user_type
                
                # Crear el select dinámicamente
                placeholder_text = {
                    "student": t('select.student_placeholder'),
                    "sponsor": t('select.sponsor_placeholder'),
                    "guest": t('select.guest_placeholder')
                }
                placeholder = placeholder_text.get(user_type, t('select.student_placeholder'))
                
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
                        await interaction.response.send_message(t('errors.user_not_found'), ephemeral=True)
                        return
                
                # IMPORTANTE: Aquí se maneja la interacción del select
                await self.callback_fn(member, interaction)
        
        # Mensaje descriptivo según el tipo
        messages = {
            "student": t('search.found_students', count=len(matches)),
            "sponsor": t('search.found_sponsors', count=len(matches)),
            "guest": t('search.found_guests', count=len(matches))
        }
        message = messages.get(self.user_type, t('search.found_students', count=len(matches)))
        
        # Enviar el view con el select
        await interaction.followup.send(
            message,
            view=UserSelectView(self.cog, guild, options, self.selected_callback, self.user_type),
            ephemeral=True
        )


class SearchModal(Modal, title=t('modal.search_list')):
    query = TextInput(label=t('modal.search_term_label'), placeholder=t('modal.search_term_placeholder'), required=False)
    def __init__(self, cog, user_type: Optional[str] = None, selected_callback=None):
        super().__init__()
        self.cog = cog
        # Optional context used by callers (e.g., SearchModal(self.cog, "guest", on_guest_selected))
        self.user_type = user_type
        self.selected_callback = selected_callback
    async def on_submit(self, interaction: discord.Interaction):
        query = str(self.query.value or "").strip()
        if not query:
            await interaction.response.send_message(t('errors.must_provide_query'), ephemeral=True)
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
            await interaction.response.send_message(t('errors.only_in_server'), ephemeral=True)
            return
        
        # Check if sponsor is still in guild
        if not interaction.guild.get_member(self.sponsor_user.id):
            await interaction.response.send_message(t('errors.sponsor_not_in_server') if hasattr(__import__('uniguard.localization'), 't') else "❌ El padrino no está en el servidor.", ephemeral=True)
            return
        
        # Check if guest is still in guild
        if not interaction.guild.get_member(self.guest_user.id):
            await interaction.response.send_message(t('errors.guest_not_in_server') if hasattr(__import__('uniguard.localization'), 't') else "❌ El invitado no está en el servidor.", ephemeral=True)
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
            await interaction.response.send_message(t('admin.operation_result', msg=msg, log=discord_log), ephemeral=True)

            # Enviar registro al canal de logs si está configurado
            try:
                channel_id = self.cog.bot.config.get('channels', {}).get('log', 0)
                if channel_id:
                    ch = self.cog.bot.get_channel(int(channel_id))
                    if ch:
                        log_msg = t('admin.log.add_guest', admin=interaction.user.mention, user=self.guest_user.mention, mc=mc_name)
                        await ch.send(log_msg)
            except Exception:
                # No interrumpir el flujo si el canal de logs falla
                pass

            res = self.cog.render_panel(interaction)
            if inspect.isawaitable(res):
                await res

class AddStudentModal(Modal, title="🎓 Registrar Alumno Manual"):
    email = TextInput(label="Email PUCV", placeholder="nombre@mail.pucv.cl", required=True)
    mc = TextInput(label="Minecraft", required=True, max_length=16)

    def __init__(self, cog, student_user: discord.Member):
        super().__init__()
        self.cog = cog
        self.student_user = student_user

    async def on_submit(self, interaction):
        if not config:
            pass
        if not self.email.value:
            pass
        if '@' not in self.email.value or 'pucv' not in self.email.value:
            return await interaction.response.send_message(t('errors.invalid_email'), ephemeral=True)

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
            await interaction.response.send_message(t('admin.student_added', log=discord_log), ephemeral=True)

            # Enviar registro al canal de logs si está configurado
            try:
                channel_id = self.cog.bot.config.get('channels', {}).get('log', 0)
                if channel_id:
                    ch = self.cog.bot.get_channel(int(channel_id))
                    if ch:
                        log_msg = t('admin.log.add_student', admin=interaction.user.mention, user=self.student_user.mention, mc=mc_name)
                        await ch.send(log_msg)
            except Exception:
                pass

            res = self.cog.render_panel(interaction)
            if inspect.isawaitable(res):
                await res
        else:
            await interaction.response.send_message(t('errors.db_save_error'), ephemeral=True)


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
            await interaction.response.send_message(t('errors.must_provide_reason'), ephemeral=True)
            return
        
        # Save suspension reason to database
        reason_ok = await db.set_suspension_reason(int(self.uid), reason)
        flag_ok = await db.set_whitelist_flag(int(self.uid), False)  # Suspend the player
        
        if not (reason_ok and flag_ok):
            await interaction.response.send_message(t('errors.suspend_save_error'), ephemeral=True)
            return
        
        await interaction.response.send_message(
            t('suspension.success', reason=reason),
            ephemeral=True
        )
        # Log the suspension to the configured log channel (if any)
        try:
            channel_id = self.cog.bot.config.get('channels', {}).get('log', 0)
            if channel_id:
                ch = self.cog.bot.get_channel(int(channel_id))
                if ch:
                    # Try to resolve a member mention; fallback to uid string if not available
                    user_repr = f"`{self.uid}`"
                    try:
                        if interaction and getattr(interaction, 'guild', None):
                            member = None
                            gm = getattr(interaction.guild, 'get_member', None)
                            if gm:
                                member = gm(int(self.uid))
                            if not member and getattr(interaction.guild, 'fetch_member', None):
                                try:
                                    member = await interaction.guild.fetch_member(int(self.uid))
                                except Exception:
                                    member = None
                            if member:
                                user_repr = member.mention
                    except Exception:
                        # If anything goes wrong resolving member, continue with uid fallback
                        pass

                    log_msg = t('admin.log.suspend', admin=interaction.user.mention, user=user_repr, reason=reason)
                    await ch.send(log_msg)
        except Exception:
            # Do not fail the flow if logging fails
            pass

        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res


class ConfirmDeleteModal(Modal, title="⚠️ Confirmar Eliminación"):
    """Modal para confirmar la eliminación de un usuario"""
    confirmation = TextInput(
        label="Confirmación (si/yes)",
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
        # Accept several confirmation forms to account for different keyboards/locales.
        import unicodedata
        value = self.confirmation.value or ""
        norm = ''.join(c for c in unicodedata.normalize('NFD', value) if unicodedata.category(c) != 'Mn').strip().lower()
        allowed = {'si', 's', 'yes', 'y'}
        if norm not in allowed:
            await interaction.response.send_message(t('errors.cancelled_confirm', confirm="sí"), ephemeral=True)
            return
        
        if not interaction.guild:
            await interaction.response.send_message(t('errors.no_guild'), ephemeral=True)
            return
        
        # 1. DB Delete
        db_success = await db.full_user_delete(self.uid)
        if not db_success:
            await interaction.response.send_message(t('errors.delete_db_error'), ephemeral=True)
            return
        
        # 2. Discord Cleanup
        log = await self.cog.manage_discord_user(
            guild=interaction.guild,
            user_id=int(self.uid),
            action="delete"
        )
        
        await interaction.response.send_message(
            t('delete.success', user=self.user_display, log=log), 
            ephemeral=True
        )
        # Log de la eliminación en canal de logs (si está configurado)
        try:
            channel_id = self.cog.bot.config.get('channels', {}).get('log', 0)
            if channel_id:
                ch = self.cog.bot.get_channel(int(channel_id))
                if ch:
                    log_msg = t('admin.log.delete', admin=interaction.user.mention, user=self.user_display)
                    await ch.send(log_msg)
        except Exception:
            pass
        self.cog.mode = "list"
        self.cog.selected_uid = None
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res


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
        
        await interaction.response.send_message(t('admin.name_updated', log=log), ephemeral=True)
        await self.cog.render_panel(interaction)


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
                t('config.value_updated', label=self.label, value=value),
                ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                t('errors.invalid_integer'),
                ephemeral=True
            )


class AddEmailDomainModal(Modal, title="➕ Agregar Dominio de Email"):
    """Modal para agregar dominios permitidos para emails universitarios"""
    domain = TextInput(label="Dominio (ej: pucv.cl)", placeholder="pucv.cl", required=True, max_length=100)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        d = (self.domain.value or "").strip().lower()
        # Simple validation: letters, numbers, hyphens and dots
        import re
        if not re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', d):
            await interaction.response.send_message(t('emails.invalid_domain'), ephemeral=True)
            return

        try:
            from uniguard.utils import add_allowed_email_domain, get_allowed_email_domains
            add_allowed_email_domain(d)
            domains, allow = get_allowed_email_domains()
            await interaction.response.send_message(t('emails.domain_added_details', domain=d, domains=", ".join(domains), allow=("✅" if allow else "⛔")), ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(t('emails.domain_add_error', error=str(e)), ephemeral=True)