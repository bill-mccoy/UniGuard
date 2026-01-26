import discord
import inspect
from discord.ui import View, Button, Select
from uniguard import config, db
from .modals import (
    SearchModal,
    SearchUserModal,
    AddStudentModal,
    AddGuestModal,
    ConfigNumberModal,
    AddEmailDomainModal,
    ConfirmDeleteModal,
    EditMCModal,
    SuspensionReasonModal,
)
from uniguard.localization import t


class ConfigChannelSelectView(View):
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
            placeholder=t('select.for_label', label=label),
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
                            t('config.channel_updated', label=self.label, channel=channel.name),
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(t('errors.channel_not_found'), ephemeral=True)
                else:
                    await interaction.response.send_message("Error: No value selected", ephemeral=True)
            else:
                await interaction.response.send_message("Error: No data in interaction", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class ConfigRoleSelectView(View):
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
            placeholder=t('select.for_label', label=label),
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
                            t('config.role_updated', label=self.label, role=role.name),
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(t('errors.role_not_found'), ephemeral=True)
                else:
                    await interaction.response.send_message("Error: No value selected", ephemeral=True)
            else:
                await interaction.response.send_message("Error: No data in interaction", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)


class SelectUser(Select):
    def __init__(self, cog, rows):
        options = []
        for row in rows:
            try:
                email, uid, user, u_type, sponsor, r_name = row
            except ValueError:
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
        if self.values[0] == "none":
            return
        self.cog.selected_uid = str(self.values[0])
        self.cog.mode = "detail"
        await self.cog.render_panel(interaction)


class ListView(View):
    def __init__(self, cog, rows, has_prev, has_next):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(SelectUser(cog, rows))

        # Navegación - Fila 1 (3 botones)
        self.add_item(Button(label=t('buttons.prev'), style=discord.ButtonStyle.secondary, disabled=not has_prev, row=1, custom_id="prev_btn")).children[-1].callback = self.prev_cb
        self.add_item(Button(label=t('buttons.refresh'), style=discord.ButtonStyle.secondary, row=1, custom_id="reload_btn")).children[-1].callback = self.reload_cb
        self.add_item(Button(label=t('buttons.next'), style=discord.ButtonStyle.secondary, disabled=not has_next, row=1, custom_id="next_btn")).children[-1].callback = self.next_cb
        
        # Herramientas - Fila 2 (3 botones)
        self.add_item(Button(label=t('buttons.search'), style=discord.ButtonStyle.primary, row=2, custom_id="search_btn")).children[-1].callback = self.search_cb
        self.add_item(Button(label=t('buttons.clear'), style=discord.ButtonStyle.secondary, row=2, custom_id="clear_btn")).children[-1].callback = self.clear_cb
        self.add_item(Button(label=t('buttons.config'), style=discord.ButtonStyle.primary, row=2, custom_id="config_btn")).children[-1].callback = self.config_cb

        # Acciones - Fila 3 (2 botones)
        self.add_item(Button(label=t('buttons.add_student'), style=discord.ButtonStyle.success, row=3, custom_id="add_s_btn")).children[-1].callback = self.add_student_cb
        self.add_item(Button(label=t('buttons.add_guest'), style=discord.ButtonStyle.success, row=3, custom_id="add_g_btn")).children[-1].callback = self.add_guest_cb
    
    async def prev_cb(self, interaction):
        await interaction.response.defer()
        self.cog.page -= 1
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res
    
    async def next_cb(self, interaction):
        await interaction.response.defer()
        self.cog.page += 1
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res
    
    async def reload_cb(self, interaction):
        await interaction.response.defer()
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res
    
    async def search_cb(self, interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        await interaction.response.send_modal(SearchModal(self.cog))
    
    async def clear_cb(self, interaction):
        await interaction.response.defer()
        self.cog.query = ""
        self.cog.page = 0
        res = self.cog.render_panel(interaction)
        if inspect.isawaitable(res):
            await res
    
    async def config_cb(self, interaction):
        """Abrir menú de configuración"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        
        if not interaction.guild:
            await interaction.response.send_message(t('errors.no_guild'), ephemeral=True)
            return
        
        # Crear embed con opciones
        embed = discord.Embed(
            title=t('config.menu_title'),
            description=t('config.menu_description'),
            color=0x3498db
        )
        
        view = ConfigMenu(self.cog, interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    async def add_student_cb(self, interaction: discord.Interaction):
        """Search for student to register"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        
        async def on_student_selected(student_user: discord.Member, select_interaction: discord.Interaction):
            # IMPORTANTE: Siempre verificar si ya se respondió
            if select_interaction.response.is_done():
                await select_interaction.followup.send(t('errors.response_already_processed'), ephemeral=True)
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
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        
        async def on_sponsor_selected(sponsor_user: discord.Member, select_interaction: discord.Interaction):
            # Primero mostrar información del padrino seleccionado
            await select_interaction.response.send_message(
                f"✅ **Padrino seleccionado:** {sponsor_user.mention} ({sponsor_user.name})\n\n"
                "Ahora busca al **invitado** que quieres registrar:",
                ephemeral=True
            )
            
            async def on_guest_selected(guest_user: discord.Member, guest_select_interaction: discord.Interaction):
                # Enviar el modal final con padrino preseleccionado
                await guest_select_interaction.response.send_modal(
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
            t('import.add_mode', minutes=3),
            ephemeral=False
        )
        self.stop()
    
    @discord.ui.button(label="⚠️ Sobrescribir todo", style=discord.ButtonStyle.danger)
    async def overwrite_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "overwrite"
        self.cog.waiting_for_csv[interaction.user.id] = self.mode
        await interaction.response.send_message(
            t('import.overwrite_mode', minutes=3),
            ephemeral=False
        )
        self.stop()
    
    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.cog.waiting_for_csv:
            del self.cog.waiting_for_csv[interaction.user.id]
        await interaction.response.send_message(t('import.cancelled'), ephemeral=False)
        self.stop()


class ImportFallbackView(View):
    """Vista alternativa cuando no hay DMs disponibles"""
    def __init__(self, cog, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel = channel

    @discord.ui.button(label="📩 Solicitar Asistencia", style=discord.ButtonStyle.primary)
    async def request_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Inform user to enable DMs and direct them to contact an admin; do NOT allow channel attachments
        await interaction.response.send_message(
            "Por favor habilita los DMs e intenta de nuevo, o contacta a un administrador para que te asista.",
            ephemeral=True
        )
        try:
            from uniguard.audit import append_entry
            append_entry(action='import_fallback_requested', admin_id=None, user_id=interaction.user.id, user_repr=getattr(interaction.user, 'mention', None), guild_id=getattr(interaction.guild, 'id', None), details={})
        except Exception:
            pass
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
            title=t('config.roles_title'),
            description=t('config.roles_desc'),
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="📢 Canales", style=discord.ButtonStyle.primary, row=0)
    async def channels_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigChannelsMenu(self.cog, self.guild)
        embed = discord.Embed(
            title=t('config.channels_title'),
            description=t('config.channels_desc'),
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="📊 Límites", style=discord.ButtonStyle.primary, row=1)
    async def limits_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigLimitsMenu(self.cog)
        embed = discord.Embed(
            title=t('config.limits_title'),
            description=t('config.limits_desc'),
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🔧 Sistema", style=discord.ButtonStyle.primary, row=1)
    async def system_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigSystemMenu(self.cog)
        embed = discord.Embed(
            title=t('config.system_title'),
            description=t('config.system_desc'),
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    @discord.ui.button(label="📧 Emails", style=discord.ButtonStyle.primary, row=1)
    async def emails_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigEmailsMenu(self.cog)
        domains, allow = view.get_current()
        embed = discord.Embed(
            title="📧 Configuración de Emails",
            description=(f"Dominios permitidos: {domains}\nPermitir subdominios: {allow}"),
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    @discord.ui.button(label="🗄️ Base de Datos", style=discord.ButtonStyle.primary, row=2)
    async def database_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigDatabaseMenu(self.cog)
        embed = discord.Embed(
            title=t('config.database_title'),
            description=t('config.database_desc'),
            color=0x3498db
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


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
        await interaction.response.send_message(t('export.cancelled'), ephemeral=True)
        self.stop()





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
        await interaction.followup.send(t('config.select_role', label='verificados'), view=view, ephemeral=True)
    
    @discord.ui.button(label="❌ No Verificado", style=discord.ButtonStyle.danger)
    async def not_verified_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigRoleSelectView(self.cog, "roles.not_verified", self.guild, "Rol No Verificado")
        await interaction.followup.send(t('config.select_role', label='no verificados'), view=view, ephemeral=True)
    
    @discord.ui.button(label="🤝 Invitado", style=discord.ButtonStyle.blurple)
    async def guest_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigRoleSelectView(self.cog, "roles.guest", self.guild, "Rol Invitado")
        await interaction.followup.send(t('config.select_role', label='invitados'), view=view, ephemeral=True)


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
        await interaction.followup.send(t('config.select_channel', label='verificación'), view=view, ephemeral=True)
    
    @discord.ui.button(label="🛠️ Administración", style=discord.ButtonStyle.blurple)
    async def admin_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigChannelSelectView(self.cog, "channels.admin", self.guild, "Canal de Admin")
        await interaction.followup.send(t('config.select_channel', label='administración'), view=view, ephemeral=True)

    @discord.ui.button(label="📜 Logs", style=discord.ButtonStyle.secondary)
    async def log_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        view = ConfigChannelSelectView(self.cog, "channels.log", self.guild, "Canal de Logs")
        await interaction.followup.send(t('config.select_channel', label='logs'), view=view, ephemeral=True)


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

    @discord.ui.button(label="🌐 Idioma", style=discord.ButtonStyle.primary)
    async def language_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open a small menu to choose per-guild language or use system default."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return

        class LanguageSelect(discord.ui.View):
            def __init__(self, parent, guild):
                super().__init__(timeout=60)
                self.parent = parent
                self.guild = guild
                options = [
                    discord.SelectOption(label=t('language.use_system'), value='system'),
                    discord.SelectOption(label='Español (es)', value='es'),
                    discord.SelectOption(label='English (en)', value='en')
                ]
                select = discord.ui.Select(placeholder=t('language.select_placeholder'), options=options, min_values=1, max_values=1)
                select.callback = self.on_select
                self.add_item(select)

            async def on_select(self, select_interaction: discord.Interaction):
                choice = select_interaction.data['values'][0]
                if choice == 'system':
                    # Remove guild override
                    config.set(f'guilds.{self.guild.id}.language', None)
                    await select_interaction.response.send_message(t('language.use_system_confirm'), ephemeral=True)
                else:
                    config.set(f'guilds.{self.guild.id}.language', choice)
                    await select_interaction.response.send_message(t('language.changed_guild', lang=choice), ephemeral=True)

        await interaction.response.send_message(t('language.choose_for_guild'), view=LanguageSelect(self, interaction.guild), ephemeral=True)


class ConfigEmailsMenu(View):
    """Menú para configurar dominios de email"""
    def __init__(self, cog):
        super().__init__(timeout=120)
        self.cog = cog

    def get_current(self):
        from uniguard.utils import get_allowed_email_domains
        return get_allowed_email_domains()

    @discord.ui.button(label="➕ Agregar dominio", style=discord.ButtonStyle.success)
    async def add_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddEmailDomainModal(self.cog))

    @discord.ui.button(label="🔁 Alternar subdominios", style=discord.ButtonStyle.blurple)
    async def toggle_subdomains(self, interaction: discord.Interaction, button: discord.ui.Button):
        domains, allow = self.get_current()
        new_allow = not allow
        from uniguard.utils import set_allowed_email_domains
        set_allowed_email_domains(domains, allow_subdomains=new_allow)
        status_text = "🟢 ACTIVADO" if new_allow else "🔴 DESACTIVADO"
        await interaction.response.send_message(t('emails.subdomains_toggled', status=status_text), ephemeral=True)

    @discord.ui.button(label="🗑 Eliminar dominio", style=discord.ButtonStyle.danger)
    async def remove_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        domains, allow = self.get_current()
        if not domains:
            await interaction.response.send_message(t('emails.no_domains'), ephemeral=True)
            return

        # Build a select view for removal
        options = [discord.SelectOption(label=d, value=d) for d in domains[:25]]
        class RemoveSelectView(discord.ui.View):
            def __init__(self, parent):
                super().__init__(timeout=60)
                self.parent = parent
                select = discord.ui.Select(placeholder=t('emails.select_domain_to_remove'), options=options, min_values=1, max_values=1)
                select.callback = self.on_select
                self.add_item(select)

            async def on_select(self, interaction: discord.Interaction):
                chosen = interaction.data['values'][0]
                from uniguard.utils import get_allowed_email_domains, set_allowed_email_domains
                cur, allow = get_allowed_email_domains()
                new = [d for d in cur if d != chosen]
                set_allowed_email_domains(new, allow_subdomains=allow)
                await interaction.response.send_message(t('emails.domain_removed_details', domain=chosen, domains=", ".join(new)), ephemeral=True)
                self.stop()

        await interaction.response.send_message(t('emails.select_domain_to_remove'), view=RemoveSelectView(self), ephemeral=True)
    


class ConfigDatabaseMenu(View):
    """Submenu para operaciones de base de datos (export/import/audit)"""
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog

    @discord.ui.button(label="⬇️ Exportar CSV", style=discord.ButtonStyle.success)
    async def export_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = getattr(interaction, 'user', None)
        if not (isinstance(member, discord.Member) and member.guild_permissions.administrator):
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        await interaction.response.send_message(
            "¿Estás seguro que quieres exportar la base de datos a CSV?",
            view=ExportConfirmView(self.cog), ephemeral=True
        )

    @discord.ui.button(label="⬆️ Importar CSV", style=discord.ButtonStyle.danger)
    async def import_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = getattr(interaction, 'user', None)
        if not (isinstance(member, discord.Member) and member.guild_permissions.administrator):
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await member.send(
                t('import.dm_message'),
                view=ImportDMView(self.cog)
            )
            await interaction.followup.send(t('import.dm_sent'), ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                t('verification.dm_forbidden_ephemeral'),
                ephemeral=True
            )



    @discord.ui.button(label="🧾 Exportar Auditoría", style=discord.ButtonStyle.secondary)
    async def export_audit_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = getattr(interaction, 'user', None)
        if not (isinstance(member, discord.Member) and member.guild_permissions.administrator):
            await interaction.response.send_message(t('admin.only_admins'), ephemeral=True)
            return
        await interaction.response.defer()
        try:
            await self.cog.export_audit(interaction)
        except Exception as e:
            await interaction.followup.send(t('export.error', error=str(e)), ephemeral=True)


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