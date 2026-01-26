"""AdminPanel Cog: glue that wires helpers, modals, and views together."""
from typing import Optional
import discord
from discord.ext import commands
import io
import csv
import datetime
import asyncio
import os
from uniguard import db
from uniguard.localization import t
import logging
from .helpers import _filter_rows, _slice_page, _fmt_user_line, PAGE_SIZE
from .views import ListView, DetailView

logger = logging.getLogger("cogs.admin")


class AdminPanelCog(commands.Cog):
    def _get_language_message(self, guild: Optional[discord.Guild]) -> str:
        """Return a localized message describing current language settings for a guild.
        This is a small helper to make testing straightforward.
        """
        from uniguard.localization import t, get_guild_lang, get_lang
        # System default
        system_lang = get_lang()
        if guild:
            guild_lang = get_guild_lang(guild.id)
        else:
            guild_lang = None

        if guild_lang:
            return t('language.current_guild', guild=guild.id, lang=guild_lang, system=system_lang)
        else:
            return t('language.current_system', lang=system_lang)

    @commands.hybrid_command(name='show_language')
    @commands.has_guild_permissions(administrator=True)
    async def show_language(self, ctx: commands.Context):
        """Show current language for this guild (admin-only)."""
        msg = self._get_language_message(ctx.guild)
        await ctx.send(msg)

    @commands.hybrid_command(name='i18n_check')
    @commands.has_guild_permissions(administrator=True)
    async def i18n_check(self, ctx: commands.Context):
        """Diagnostic command: shows resolved language and sample translations for this guild."""
        from uniguard.localization import get_guild_lang, get_lang, translate_for_lang
        guild = ctx.guild
        guild_id = guild.id if guild else None
        guild_lang = get_guild_lang(guild_id)
        system_lang = get_lang()
        resolved = guild_lang or system_lang or 'en'
        # Build a small embed with details
        embed = discord.Embed(title="I18n Check", color=0x3498db)
        embed.add_field(name="Guild ID", value=str(guild_id))
        embed.add_field(name="Guild lang", value=str(guild_lang))
        embed.add_field(name="System lang", value=str(system_lang))
        embed.add_field(name="Resolved", value=str(resolved))
        # Sample messages
        embed.add_field(name="dm_embed_title", value=translate_for_lang('verification.dm_embed_title', resolved), inline=False)
        embed.add_field(name="dm_sent", value=translate_for_lang('verification.dm_sent', resolved), inline=False)
        await ctx.send(embed=embed)

    async def export_csv(self, interaction: discord.Interaction):
        """Exporta la base de datos a CSV y la envía como archivo adjunto con timestamp."""
        try:
            rows = await db.list_verified_players()
            if not rows:
                await interaction.followup.send(t('export.no_data'), ephemeral=True)
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
                content=t('export.completed', filename=filename),
                file=file,
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(t('export.error', error=str(e)), ephemeral=True)

    async def export_audit(self, interaction: discord.Interaction):
        """Exporta los registros de auditoría y los envía al admin como JSON y CSV."""
        try:
            from uniguard import audit
            entries = audit.read_entries()
            if not entries:
                await interaction.followup.send(t('audit.no_data'), ephemeral=True)
                return False

            json_path = audit.export_json()
            csv_path = audit.export_csv()

            await interaction.followup.send(content=t('audit.export_completed', filename=os.path.basename(json_path)), files=[discord.File(json_path), discord.File(csv_path)], ephemeral=True)
            return True
        except Exception as e:
            await interaction.followup.send(t('export.error', error=str(e)), ephemeral=True)
            return False

    async def import_csv(self, interaction: discord.Interaction, attachment: discord.Attachment, mode: str):
        """Importa datos desde un archivo CSV adjunto, validando formato y columnas. Modo: 'add' o 'overwrite'"""
        try:
            if not attachment.filename.endswith('.csv'):
                await interaction.followup.send(t('import.must_be_csv'), ephemeral=True)
                return
            data = await attachment.read()
            content = data.decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            if not rows or len(rows) < 2:
                await interaction.followup.send(t('import.empty_csv'), ephemeral=True)
                return
            header = rows[0]
            expected = ["email", "user_id", "user", "type", "sponsor_id", "real_name"]
            if header != expected:
                await interaction.followup.send(t('import.bad_format', expected=expected), ephemeral=True)
                return
            # Validar tipos básicos
            parsed = []
            for i, row in enumerate(rows[1:], start=2):
                if len(row) != len(expected):
                    await interaction.followup.send(t('import.row_incorrect_columns', row=i), ephemeral=True)
                    return
                try:
                    user_id = int(row[1])
                except Exception as e:
                    await interaction.followup.send(t('import.row_invalid_userid', row=i, error=str(e)[:100]), ephemeral=True)
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
            await db._ensure_pool_or_log()
            pool = db._POOL
            if pool is None:
                await interaction.followup.send(t('errors.db_not_initialized'), ephemeral=True)
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
                    await interaction.followup.send(t('errors.generic', msg=str(e)), ephemeral=True)
                    return
            # Insertar registros (delegado a la misma lógica que DM importer)
            # Reuse _import_csv_dm implementation by building a fake message-like object
            # but for simplicity we just reuse the DM helper directly here.
            added, skipped, failed = 0, 0, 0
            failures = []
            for rec in parsed:
                try:
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

            await interaction.followup.send(
                f"✅ Importación finalizada. Agregados: {added}, Saltados: {skipped}, Fallidos: {failed}.\n\n" + ("Errores:\n" + "\n".join(failures)[:1500] if failures else ""),
                ephemeral=True
            )
            # Registrar auditoría de importación exitosa
            try:
                from uniguard.audit import append_entry
                user = getattr(interaction, 'user', None)
                append_entry(action='import_completed', admin_id=None, user_id=getattr(user, 'id', None), user_repr=getattr(user, 'mention', None), guild_id=getattr(interaction.guild, 'id', None), details={'added': added, 'skipped': skipped, 'failed': failed})
            except Exception:
                pass
        except Exception as e:
            try:
                from uniguard.audit import append_entry
                user = getattr(interaction, 'user', None)
                append_entry(action='import_failed', admin_id=None, user_id=getattr(user, 'id', None), guild_id=getattr(interaction.guild, 'id', None), details={'error': str(e)[:200]})
            except Exception:
                pass
            await interaction.followup.send(t('import.processing_error', error=str(e)[:200]), ephemeral=True)

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
                await message.channel.send(t('import.specify_mode'))
                return
            
            # Verificar que tenga un archivo adjunto
            if message.attachments:
                attachment = message.attachments[0]
                # Registrar auditoría de que se recibió un archivo en canal
                try:
                    from uniguard.audit import append_entry
                    append_entry(action='import_channel_received', admin_id=None, user_id=message.author.id, user_repr=message.author.mention, guild_id=getattr(message.guild, 'id', None), details={'message_id': message.id, 'reference_id': message.reference.message_id})
                except Exception:
                    pass
                # Limpiar el estado de espera
                del self.pending_imports[message.reference.message_id]
                await self.process_csv_import_channel(message, attachment, mode)

    async def process_csv_import_dm(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Procesar un archivo CSV adjunto en DM"""
        try:
            # Notificar que estamos procesando
            processing_msg = await message.channel.send(t('import.processing'))
            
            # Llamar a la función de importación
            await self._import_csv_dm(message, attachment, mode)
            
            # Eliminar mensaje de procesamiento
            await processing_msg.delete()
            
        except Exception as e:
            await message.channel.send(t('import.processing_error', error=str(e)[:100]))

    async def process_csv_import_channel(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Procesar un archivo CSV adjunto en canal"""
        try:
            # Registrar auditoría: procesamiento iniciado en canal
            try:
                from uniguard.audit import append_entry
                append_entry(action='import_channel_processing_started', admin_id=None, user_id=message.author.id, user_repr=message.author.mention, guild_id=getattr(message.guild, 'id', None), details={'message_id': message.id, 'mode': mode})
            except Exception:
                pass

            # Notificar que estamos procesando
            processing_msg = await message.channel.send(t('import.processing_in_channel', user=message.author.mention))
            
            # Llamar a la función de importación
            await self._import_csv_channel(message, attachment, mode)
            
            # Eliminar mensaje de procesamiento
            await processing_msg.delete()

            # Registrar auditoría: procesamiento finalizado exitosamente
            try:
                from uniguard.audit import append_entry
                append_entry(action='import_channel_completed', admin_id=None, user_id=message.author.id, user_repr=message.author.mention, guild_id=getattr(message.guild, 'id', None), details={'message_id': message.id, 'mode': mode})
            except Exception:
                pass
            
        except Exception as e:
            try:
                from uniguard.audit import append_entry
                append_entry(action='import_channel_failed', admin_id=None, user_id=message.author.id, user_repr=message.author.mention, guild_id=getattr(message.guild, 'id', None), details={'message_id': message.id, 'mode': mode, 'error': str(e)[:200]})
            except Exception:
                pass
            await message.channel.send(t('import.processing_error_in_channel', user=message.author.mention, error=str(e)[:100]))

    async def _import_csv_dm(self, message: discord.Message, attachment: discord.Attachment, mode: str):
        """Versión de import_csv para DM"""
        try:
            if not attachment.filename.endswith('.csv'):
                await message.channel.send(t('import.must_be_csv'))
                return
            
            data = await attachment.read()
            content = data.decode("utf-8")
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            
            if not rows or len(rows) < 2:
                await message.channel.send(t('import.empty_csv'))
                return
            
            header = rows[0]
            expected = ["email", "user_id", "user", "type", "sponsor_id", "real_name"]
            if header != expected:
                await message.channel.send(t('import.bad_format', expected=expected))
                return
            
            # Validar tipos básicos
            parsed = []
            for i, row in enumerate(rows[1:], start=2):
                if len(row) != len(expected):
                    await message.channel.send(t('import.row_incorrect_columns', row=i))
                    return
                try:
                    user_id = int(row[1])
                except Exception as e:
                    await message.channel.send(t('import.row_invalid_userid', row=i, error=str(e)[:100]))
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
                    # Si modo add, saltar si ya exista user_id
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
            
            await message.channel.send(
                f"✅ **Importación finalizada**\n\n"
                f"📊 **Resultados:**\n"
                f"• ✅ Agregados: **{added}**\n"
                f"• ⏭️ Saltados: **{skipped}**\n"
                f"• ❌ Fallidos: **{failed}**" + ("\n\nErrores:\n" + "\n".join(failures)[:1500] if failures else "")
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
                    if role:
                        break
            return role

        # LOGICA SEGUN ACCION
        try:
            # --- BORRAR USUARIO ---
            if action == "delete":
                # Quitar roles de privilegio
                r_ver = get_role_smart(rid_verified, ["Alumno", "Verificado"])
                r_guest = get_role_smart(rid_guest, ["Invitado", "Apadrinado", "🤝 Invitado"])
                
                if r_ver and r_ver in member.roles:
                    await member.remove_roles(r_ver)
                if r_guest and r_guest in member.roles:
                    await member.remove_roles(r_guest)
                
                # Devolver rol no verificado
                r_not = get_role_smart(rid_not_ver, ["No Verificado"])
                if r_not:
                    await member.add_roles(r_not)
                log.append("Roles retirados.")

            # --- AGREGAR ALUMNO ---
            elif action == "add_student":
                # Nickname
                try:
                    await member.edit(nick=f"[EST] {mc_name}"[:32])
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
                    
                    if r_not:
                        await member.remove_roles(r_not)
                except Exception as e:
                    logger.error(f"Error assigning student roles to {user_id}: {e}")
                    log.append(f"⚠️ Error asignando roles: {e}")

            # --- AGREGAR INVITADO ---
            elif action == "add_guest":
                # Nickname
                try:
                    await member.edit(nick=f"[INV] {mc_name}"[:32])
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
                    
                    if r_not:
                        await member.remove_roles(r_not)
                except Exception as e:
                    logger.error(f"Error assigning guest roles to {user_id}: {e}")
                    log.append(f"⚠️ Error asignando roles: {e}")

            # --- ACTUALIZAR NICK ---
            elif action == "update_nick":
                # Detectar prefijo actual o poner uno por defecto
                curr_nick = member.display_name
                prefix = "[EST]"
                if "[INV]" in curr_nick or "[Ap]" in curr_nick:
                    prefix = "[INV]"
                
                try:
                    await member.edit(nick=f"{prefix} {mc_name}"[:32])
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
        if not cid:
            return

        channel = self.bot.get_channel(int(cid))
        if not channel:
            return

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
                if not interaction.response.is_done():
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.edit_original_response(embed=embed, view=view)
            elif self._msg:
                await self._msg.edit(content=None, embed=embed, view=view)
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
        if self.query:
            embed.description = f"🔎 `{self.query}` ({len(filtered)})"
        else:
            embed.description = f"👥 Total: {tot} | 🎓 Alumnos: {tot - gst} | 🤝 Invitados: {gst}"

        lines = [_fmt_user_line(r) for r in page_rows]
        embed.add_field(name=f"Lista ({cur_p}/{tot_p})", value="\n".join(lines) or "Vacío", inline=False)
        
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