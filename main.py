import os 
import re
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
from punishments import punishments
from ban_history import ban_tracker
import asyncpg
from typing import List, Optional

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Store form state for back navigation
user_form_state = {}

class DatabaseConnection:
    def __init__(self):
        self.connection_string = os.getenv('DATABASE_CONNECTION_STRING')
        self.pool = None
    
    async def initialize(self):
        """Initialize the database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(self.connection_string)
            print("✅ Database connection established")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
    
    async def close(self):
        """Close the database connection pool"""
        if self.pool:
            await self.pool.close()
    
    async def find_players(self, search_term: str) -> List[dict]:
        """Find players by name (partial match)"""
        if not self.pool:
            return []
        
        query = """
        SELECT pp."Name", pp."Level", pp."LastPlayed", pp."BohemiaUID"
        FROM "PlayerProfiles" pp
        WHERE LOWER(pp."Name") LIKE LOWER($1)
        ORDER BY pp."LastPlayed" DESC
        LIMIT 15
        """
        
        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(query, f'%{search_term}%')
                
                players = []
                for row in rows:
                    # Calculate hours since last played
                    if row['LastPlayed']:
                        time_diff = datetime.utcnow() - row['LastPlayed']
                        hours_since = int(time_diff.total_seconds() / 3600)
                    else:
                        hours_since = 0
                    
                    players.append({
                        'Name': row['Name'],
                        'Level': row['Level'],
                        'Last Played': f"{hours_since}H",
                        'BohemiaUID': str(row['BohemiaUID'])
                    })
                
                return players
        except Exception as e:
            print(f"Database error: {e}")
            return []

# Initialize database connection
db = DatabaseConnection()

class PlayerSearchModal(discord.ui.Modal, title="Search for Player"):
    search_term = discord.ui.TextInput(
        label="Player Name",
        style=discord.TextStyle.short,
        placeholder="Enter player name or partial name...",
        required=True,
        min_length=2,
        max_length=50
    )

    def __init__(self, from_buildbanform=False):
        super().__init__()
        self.from_buildbanform = from_buildbanform

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Search database first
            players = await db.find_players(self.search_term.value)
            
            # If no database results, try channel search as fallback
            if not players:
                players = await search_channels_for_players(interaction.guild, self.search_term.value)
            
            if not players:
                embed = discord.Embed(
                    title="No Players Found",
                    description=f"No players found matching '{self.search_term.value}'",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Store players in form state
            user_form_state[interaction.user.id] = {'players': players}
            
            if self.from_buildbanform:
                # For buildbanform, go directly to player selection
                embed = discord.Embed(
                    title="Build Ban Form - Select Player",
                    description=f"Found {len(players)} player(s) matching '{self.search_term.value}'. Select a player to generate the ban form:",
                    color=discord.Color.blue()
                )
                
                # Show ALL results in preview - break into multiple fields if needed
                preview_lines = []
                for player in players:
                    line = f"**{player['Name']}** (Level {player['Level']}, Last: {player['Last Played']})"
                    preview_lines.append(line)
                
                # Split into multiple fields if too many players (Discord has field limits)
                if len(preview_lines) <= 10:
                    # If 10 or fewer, show in one field
                    embed.add_field(
                        name="Found Players",
                        value="\n".join(preview_lines),
                        inline=False
                    )
                else:
                    # Split into multiple fields of 10 each
                    for i in range(0, len(preview_lines), 10):
                        chunk = preview_lines[i:i+10]
                        field_num = (i // 10) + 1
                        total_fields = (len(preview_lines) + 9) // 10
                        
                        embed.add_field(
                            name=f"Found Players ({field_num}/{total_fields})",
                            value="\n".join(chunk),
                            inline=False
                        )
                
                view = PlayerView(players)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                # For ban_player, show detailed search results first
                embed = discord.Embed(
                    title="Ban Process - Step 1: Select Player",
                    description=f"Found {len(players)} player(s) matching '{self.search_term.value}'. Please select the player you want to ban from the dropdown below.",
                    color=discord.Color.orange()
                )
                
                # Show ALL results in preview - break into multiple fields if needed
                preview_lines = []
                for player in players:
                    line = f"**{player['Name']}** (Level {player['Level']}, Last: {player['Last Played']})"
                    preview_lines.append(line)
                
                # Split into multiple fields if too many players
                if len(preview_lines) <= 10:
                    # If 10 or fewer, show in one field
                    embed.add_field(
                        name="Found Players",
                        value="\n".join(preview_lines),
                        inline=False
                    )
                else:
                    # Split into multiple fields of 10 each
                    for i in range(0, len(preview_lines), 10):
                        chunk = preview_lines[i:i+10]
                        field_num = (i // 10) + 1
                        total_fields = (len(preview_lines) + 9) // 10
                        
                        embed.add_field(
                            name=f"Found Players ({field_num}/{total_fields})",
                            value="\n".join(chunk),
                            inline=False
                        )
                
                view = PlayerSearchView(players, self.search_term.value)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                
        except Exception as e:
            embed = discord.Embed(
                title="Search Error",
                description=f"An error occurred while searching for players: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

async def search_channels_for_players(guild: discord.Guild, search_term: str) -> list:
    """Fallback method to search channels for player data"""
    players = []
    search_term_lower = search_term.lower()
    
    for channel in guild.text_channels:
        try:
            async for message in channel.history(limit=50):
                if "Name = " in message.content:
                    lines = message.content.replace(",", "\n").splitlines()
                    for line in lines:
                        parts = line.strip().split(" | ")
                        player = {}
                        for part in parts:
                            if " = " in part:
                                k, v = part.split(" = ", 1)
                                player[k.strip()] = v.strip()
                        
                        # Check if this player matches our search and has all required fields
                        if (all(k in player for k in ("Name", "Level", "Last Played", "BohemiaUID")) and 
                            search_term_lower in player["Name"].lower()):
                            # Avoid duplicates
                            if not any(p["BohemiaUID"] == player["BohemiaUID"] for p in players):
                                players.append(player)
                    
                # Limit results
                if len(players) >= 15:
                    break
        except (discord.Forbidden, discord.HTTPException):
            continue
        
        if len(players) >= 15:
            break
    
    return players

@bot.event
async def on_ready():
    # Initialize database connection
    await db.initialize()
    
    try:
        await tree.sync()
        print(f"✅ Synced slash commands globally as {bot.user}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

@bot.event
async def on_close():
    """Clean up database connection when bot shuts down"""
    await db.close()

def generate_transcript_link(message: discord.Message, channel_name: str, *args) -> str:
    for attachment in message.attachments:
        if attachment.filename.endswith(".html"):
            match = re.search(r"(\d+)", attachment.filename)
            if match:
                number = int(match.group(1))
                # Determine prefix based on channel name
                if "ticket" in channel_name.lower():
                    return f"[Ticket-{number:04d}](<{message.jump_url}>)"
                else:
                    return f"[Report-{number:04d}](<{message.jump_url}>)"
    return f"[Transcript](<{message.jump_url}>)"

async def get_transcript_options(guild: discord.Guild, channel_name_contains="transcript") -> list[str]:
    transcript_channel = next((c for c in guild.text_channels if channel_name_contains in c.name.lower()), None)
    if not transcript_channel:
        return []
    transcripts = []
    index = 1
    async for message in transcript_channel.history(limit=50):
        if message.attachments:
            if any(att.filename.endswith(".html") for att in message.attachments):
                # Pass channel name to generate_transcript_link
                transcripts.append(generate_transcript_link(message, transcript_channel.name, index))
                index += 1
        if len(transcripts) >= 5:
            break
    return transcripts

class PlayerSearchView(discord.ui.View):
    def __init__(self, players: List[dict], search_term: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.players = players
        self.search_term = search_term
        self.selected_player = None
        
        # Show detailed results first
        show_results_button = discord.ui.Button(
            label="📋 Show Detailed Results",
            style=discord.ButtonStyle.primary
        )
        show_results_button.callback = self.show_detailed_results
        self.add_item(show_results_button)
        
        # Create select menu with players
        options = []
        for i, player in enumerate(players[:25]):  # Discord limit of 25 options
            label = f"{player['Name']} (Level {player['Level']})"
            description = f"Last played: {player['Last Played']}"
            
            # Truncate if needed
            if len(label) > 100:
                label = label[:97] + "..."
            if len(description) > 100:
                description = description[:97] + "..."
                
            options.append(discord.SelectOption(
                label=label,
                description=description,
                value=str(i)
            ))
        
        if options:
            self.player_select = discord.ui.Select(
                placeholder="Select a player to proceed with ban...",
                options=options
            )
            self.player_select.callback = self.player_selected
            self.add_item(self.player_select)
        
        # Add search again button
        search_again_button = discord.ui.Button(
            label="🔍 Search Again",
            style=discord.ButtonStyle.secondary
        )
        search_again_button.callback = self.search_again
        self.add_item(search_again_button)
    
    async def show_detailed_results(self, interaction: discord.Interaction):
        """Show the detailed search results in the requested format"""
        # Create the formatted results as requested
        result_lines = []
        for player in self.players:
            line = f"Name = {player['Name']} | Level = {player['Level']} | Last Played = {player['Last Played']} | BohemiaUID = {player['BohemiaUID']}"
            result_lines.append(line)
        
        # Create embed with results
        embed = discord.Embed(
            title=f"Detailed Search Results for '{self.search_term}'",
            description=f"Found {len(self.players)} player(s)",
            color=discord.Color.blue()
        )
        
        # Split results into chunks for Discord's limits
        result_text = "\n".join(result_lines)
        
        # If the full text is short enough, show it all in description
        if len(result_text) <= 4000:  # Leave some room for the title
            embed.description = f"Found {len(self.players)} player(s)\n\n```\n{result_text}\n```"
        else:
            # Split into multiple fields if too long
            chunks = [result_lines[i:i+8] for i in range(0, len(result_lines), 8)]  # 8 lines per field to stay under limits
            for i, chunk in enumerate(chunks):
                field_name = f"Results {i*8+1}-{min((i+1)*8, len(result_lines))}"
                field_value = "```\n" + "\n".join(chunk) + "\n```"
                embed.add_field(
                    name=field_name,
                    value=field_value,
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def search_again(self, interaction: discord.Interaction):
        """Allow user to search again"""
        modal = PlayerSearchModal(from_buildbanform=False)
        await interaction.response.send_modal(modal)
    
    async def player_selected(self, interaction: discord.Interaction):
        """Called when a player is selected from the dropdown"""
        selected_index = int(self.player_select.values[0])
        self.selected_player = self.players[selected_index]
        
        try:
            await interaction.message.delete()
        except:
            pass
        
        # Store players and selected player in form state
        user_form_state[interaction.user.id] = {
            'players': self.players,
            'player': self.selected_player
        }
        
        # Show selected player details and proceed to offense selection
        embed = discord.Embed(
            title="Player Selected for Ban",
            color=discord.Color.green()
        )
        embed.add_field(name="Name", value=self.selected_player["Name"], inline=True)
        embed.add_field(name="Level", value=self.selected_player["Level"], inline=True)
        embed.add_field(name="Last Played", value=self.selected_player["Last Played"], inline=True)
        embed.add_field(name="Bohemia UID", value=self.selected_player["BohemiaUID"], inline=False)
        
        # Proceed to offense selection
        await interaction.response.send_message(
            embed=embed,
            view=OffenseView(self.selected_player), 
            ephemeral=True
        )

class ConfirmationButton(discord.ui.Button):
    def __init__(self, response_text: str, player_data: dict, offense: str, strike: str, sanction: str, transcript: str, unban_data: dict = None):
        super().__init__(label="Confirm", style=discord.ButtonStyle.green)
        self.response_text = response_text
        self.player_data = player_data
        self.offense = offense
        self.strike = strike
        self.sanction = sanction
        self.transcript = transcript
        self.unban_data = unban_data

    async def callback(self, interaction: discord.Interaction):
        # Handle unban logic
        if self.unban_data:
            if self.unban_data['remove_strike']:
                # Remove the strike from history
                success = ban_tracker.remove_strike(self.unban_data['ban_id'])
                if success:
                    strike_note = f" (Strike removed from Ban #{self.unban_data['ban_id']:04d})"
                else:
                    strike_note = f" (Failed to remove strike from Ban #{self.unban_data['ban_id']:04d})"
            else:
                strike_note = f" (Strike remains from Ban #{self.unban_data['ban_id']:04d})"
            
            # Save unban record
            ban_id = ban_tracker.add_ban(
                player_name=self.player_data['Name'],
                buid=self.player_data['BohemiaUID'],
                offense=self.offense + strike_note,
                strike="UNBAN",
                sanction=self.sanction,
                transcript=self.transcript,
                submitted_by=str(interaction.user.id),
                is_unban=True,
                related_ban_id=self.unban_data['ban_id']
            )
        else:
            # Regular ban
            ban_id = ban_tracker.add_ban(
                player_name=self.player_data['Name'],
                buid=self.player_data['BohemiaUID'],
                offense=self.offense,
                strike=self.strike,
                sanction=self.sanction,
                transcript=self.transcript,
                submitted_by=str(interaction.user.id)
            )
        
        final_response = (
            f"{self.response_text}\n"
            f"Submitted by: {interaction.user.mention}\n"
            f"Ban ID: #{ban_id:04d}"
        )
        
        try:
            await interaction.message.delete()
        except:
            pass
        
        # Clear form state
        if interaction.user.id in user_form_state:
            del user_form_state[interaction.user.id]
        
        await interaction.response.send_message(final_response, ephemeral=False)

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        
        # Clear form state
        if interaction.user.id in user_form_state:
            del user_form_state[interaction.user.id]
        
        await interaction.response.send_message("❌ Ban form cancelled.", ephemeral=True)

class BackButton(discord.ui.Button):
    def __init__(self, back_to: str):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary)
        self.back_to = back_to

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id not in user_form_state:
            await interaction.response.send_message("❌ Form state lost. Please start over.", ephemeral=True)
            return
        
        state = user_form_state[user_id]
        
        # Delete the current message and respond with new menu
        try:
            await interaction.message.delete()
        except:
            pass
        
        if self.back_to == "player":
            await interaction.response.send_message("Select a player to generate the ban form:", view=PlayerView(state.get('players', [])), ephemeral=True)
        elif self.back_to == "offense":
            await interaction.response.send_message("Select the offense:", view=OffenseView(state['player']), ephemeral=True)
        elif self.back_to == "strike":
            await interaction.response.send_message("Select the strike level:", view=StrikeView(state['player'], state['offense']), ephemeral=True)
        elif self.back_to == "transcript_type":
            await interaction.response.send_message("Select transcript type:", view=TranscriptTypeView(state['player'], state['offense'], state['strike'], state['sanction'], state.get('unban_data')), ephemeral=True)

class TranscriptTypeSelect(discord.ui.Select):
    def __init__(self, player: dict, offense: str, strike: str, sanction: str, unban_data: dict = None):
        self.player = player
        self.offense = offense
        self.strike = strike
        self.sanction = sanction
        self.unban_data = unban_data
        
        # Report transcripts appear first (on top)
        options = [
            discord.SelectOption(
                label="Report Transcript", 
                value="report-transcripts",
                description="Transcripts from report investigations"
            ),
            discord.SelectOption(
                label="Ticket Transcript", 
                value="ticket-transcripts",
                description="Transcripts from player appeals/tickets"
            )
        ]
        
        super().__init__(placeholder="Select transcript type...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        
        transcript_type = self.values[0]
        
        # Get transcripts from the selected channel type
        transcripts = await get_transcript_options(interaction.guild, transcript_type)
        
        if transcripts:
            await interaction.response.send_message(
                f"Select a transcript from {transcript_type}:", 
                view=TranscriptView(transcripts, self.player, self.offense, self.strike, self.sanction, self.unban_data), 
                ephemeral=True
            )
        else:
            # No transcripts found, proceed without transcript
            response = (
                f"Transcript link: N/A\n"
                f"Player(s) being reported: {self.player['Name']}\n"
                f"BUID: {self.player['BohemiaUID']}\n"
                f"Verdict/Reason for ban: {self.offense}\n"
                f"Ban Length: ({self.strike}) {self.sanction}"
            )
            
            if self.unban_data:
                response += f"\nRelated to Ban #{self.unban_data['ban_id']:04d}"
                
                # Check for previous bans (skip for unbans)
                history_note = ""
            else:
                previous_strikes = ban_tracker.get_player_strikes(self.player['BohemiaUID'])
                if previous_strikes > 0:
                    response += f"\n⚠️ **Previous Strikes:** {previous_strikes}"
            
            await interaction.response.send_message(
                content=f"No transcripts found in {transcript_type}.\n\nPreview:\n{response}", 
                view=ConfirmationView(response, self.player, self.offense, self.strike, self.sanction, "N/A", self.unban_data), 
                ephemeral=True
            )

class TranscriptTypeView(discord.ui.View):
    def __init__(self, player: dict, offense: str, strike: str, sanction: str, unban_data: dict = None):
        super().__init__()
        self.add_item(TranscriptTypeSelect(player, offense, strike, sanction, unban_data))
        
        # Determine what to go back to
        if unban_data:
            self.add_item(BackButton("offense"))  # For unbans, go back to report selection (which goes back to offense)
        else:
            self.add_item(BackButton("strike"))   # For regular bans, go back to strike selection

class UnbanReportSelect(discord.ui.Select):
    def __init__(self, player_buid: str, unban_type: str):
        self.player_buid = player_buid
        self.unban_type = unban_type
        self.remove_strike = unban_type == "UNBAN (Remove Strike)"
        
        # Get player's ban history
        history = ban_tracker.get_player_history(player_buid)
        
        options = []
        if history:
            # Only show bans that aren't unbans and have strikes to remove
            for ban in history[-10:]:  # Last 10 bans
                if not ban.get('is_unban', False):
                    status = " ❌" if ban.get('strike_removed', False) else ""
                    options.append(discord.SelectOption(
                        label=f"Ban #{ban['id']:04d} - {ban['offense'][:50]}{status}",
                        description=f"{ban['timestamp'][:10]} - ({ban['strike']}) {ban['sanction'][:50]}",
                        value=str(ban['id'])
                    ))
        
        if not options:
            options.append(discord.SelectOption(label="No bans found for this player", value="none", description="Cannot proceed"))
        
        super().__init__(
            placeholder=f"Select report to unban {'(remove strike)' if self.remove_strike else '(keep strike)'}...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("❌ No valid bans found to unban.", ephemeral=True)
            return
        
        try:
            await interaction.message.delete()
        except:
            pass
        
        ban_id = int(self.values[0])
        user_id = interaction.user.id
        state = user_form_state[user_id]
        
        # Store unban data and proceed to transcript type selection
        unban_data = {
            'ban_id': ban_id,
            'remove_strike': self.remove_strike
        }
        
        # Update form state with unban data
        user_form_state[user_id]['unban_data'] = unban_data
        user_form_state[user_id]['strike'] = "UNBAN"
        user_form_state[user_id]['sanction'] = "Player Unbanned"
        
        # Go to transcript type selection
        await interaction.response.send_message(
            "Select transcript type:", 
            view=TranscriptTypeView(state['player'], self.unban_type, "UNBAN", "Player Unbanned", unban_data), 
            ephemeral=True
        )

class UnbanReportView(discord.ui.View):
    def __init__(self, player_buid: str, unban_type: str):
        super().__init__()
        self.add_item(UnbanReportSelect(player_buid, unban_type))
        self.add_item(BackButton("offense"))

class TranscriptBackButton(discord.ui.Button):
    def __init__(self, player: dict, offense: str, strike: str, sanction: str, unban_data: dict = None):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary)
        self.player = player
        self.offense = offense
        self.strike = strike
        self.sanction = sanction
        self.unban_data = unban_data

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        
        # Update form state to include current selections
        user_form_state[interaction.user.id] = {
            'player': self.player,
            'offense': self.offense,
            'strike': self.strike,
            'sanction': self.sanction,
            'unban_data': self.unban_data,
            'players': user_form_state.get(interaction.user.id, {}).get('players', [])
        }
        
        # Go back to transcript type selection
        await interaction.response.send_message(
            "Select transcript type:", 
            view=TranscriptTypeView(self.player, self.offense, self.strike, self.sanction, self.unban_data), 
            ephemeral=True
        )

class ConfirmationView(discord.ui.View):
    def __init__(self, response_text: str, player_data: dict, offense: str, strike: str, sanction: str, transcript: str, unban_data: dict = None):
        super().__init__()
        self.add_item(ConfirmationButton(response_text, player_data, offense, strike, sanction, transcript, unban_data))
        self.add_item(BackButton("transcript_type"))  # Back to transcript type selection
        self.add_item(CancelButton())

class TranscriptSelect(discord.ui.Select):
    def __init__(self, transcripts: list[str], player: dict, offense: str, strike: str, sanction: str, unban_data: dict = None):
        self.transcript_map = {}
        self.unban_data = unban_data
        options = []

        options.append(discord.SelectOption(label="Will add later", value="add_later"))
        options.append(discord.SelectOption(label="Witness", value="witness"))

        for link in transcripts:
            match = re.match(r"\[(.*?)\]\(<(.*?)>\)", link)
            if match:
                label, url = match.groups()
                if url not in self.transcript_map:
                    self.transcript_map[url] = label
                    options.append(discord.SelectOption(label=label, value=url))

        super().__init__(placeholder="Select a transcript or option...", min_values=1, max_values=1, options=options)
        self.player = player
        self.offense = offense
        self.strike = strike
        self.sanction = sanction

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass

        chosen_value = self.values[0]

        if chosen_value == "add_later":
            link = "Will add later"
        elif chosen_value == "witness":
            link = "Witness"
        else:
            label = self.transcript_map.get(chosen_value, "Transcript")
            link = f"[{label}](<{chosen_value}>)"

        # Check for previous bans (skip for unbans)
        history_note = ""
        if not self.unban_data:
            previous_strikes = ban_tracker.get_player_strikes(self.player['BohemiaUID'])
            if previous_strikes > 0:
                history_note = f"\n⚠️ **Previous Strikes:** {previous_strikes}"

        response = (
            f"Transcript link: {link}\n"
            f"Player(s) being reported: {self.player['Name']}\n"
            f"BUID: {self.player['BohemiaUID']}\n"
            f"Verdict/Reason for ban: {self.offense}\n"
            f"Ban Length: ({self.strike}) {self.sanction}{history_note}"
        )
        
        if self.unban_data:
            response += f"\nRelated to Ban #{self.unban_data['ban_id']:04d}"
        
        await interaction.response.send_message(
            content=f"Preview:\n{response}", 
            view=ConfirmationView(response, self.player, self.offense, self.strike, self.sanction, link, self.unban_data), 
            ephemeral=True
        )

class TranscriptView(discord.ui.View):
    def __init__(self, transcripts, player, offense, strike, sanction, unban_data: dict = None):
        super().__init__()
        self.add_item(TranscriptSelect(transcripts, player, offense, strike, sanction, unban_data))
        # Add back button to transcript selection
        self.add_item(TranscriptBackButton(player, offense, strike, sanction, unban_data))

class CustomPunishmentModal(discord.ui.Modal, title="Custom Punishment Entry"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.long,
        placeholder="Enter custom reason...",
        required=True
    )
    length = discord.ui.TextInput(
        label="Ban Length",
        placeholder="Enter ban length (e.g., 3 days)",
        required=True
    )

    def __init__(self, player: dict):
        super().__init__()
        self.player = player

    async def on_submit(self, interaction: discord.Interaction):
        # Update form state for custom punishment
        user_form_state[interaction.user.id]['offense'] = self.reason.value
        user_form_state[interaction.user.id]['strike'] = "Custom"
        user_form_state[interaction.user.id]['sanction'] = self.length.value
        
        # Go to transcript type selection
        await interaction.response.send_message(
            "Select transcript type:", 
            view=TranscriptTypeView(self.player, self.reason.value, "Custom", self.length.value), 
            ephemeral=True
        )

# Updated View classes to be standalone
class StrikeView(discord.ui.View):
    def __init__(self, player: dict, offense: str):
        super().__init__()
        self.player = player
        self.offense = offense
        
        # Handle unban types differently
        if offense in ["UNBAN (Strike Remains)", "UNBAN (Remove Strike)"]:
            # For unbans, skip strike selection and go to report selection
            pass
        else:
            # Store state
            strikes = punishments[offense]
            strike_select = StrikeSelect(player, offense, strikes)
            self.add_item(strike_select)
        
        self.add_item(BackButton("offense"))

class StrikeSelect(discord.ui.Select):
    def __init__(self, player: dict, offense: str, strikes: dict):
        self.player = player
        self.offense = offense
        self.strikes = strikes
        options = [discord.SelectOption(label=s) for s in strikes.keys()]
        super().__init__(placeholder="Select strike level...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        
        strike = self.values[0]
        sanctions = self.strikes[strike]

        if isinstance(sanctions, list):
            class SanctionSelect(discord.ui.Select):
                def __init__(self):
                    super().__init__(
                        placeholder="Select ban duration...",
                        min_values=1,
                        max_values=1,
                        options=[discord.SelectOption(label=d) for d in sanctions]
                    )

                async def callback(self3, interaction3: discord.Interaction):
                    try:
                        await interaction3.message.delete()
                    except:
                        pass
                    
                    chosen = self3.values[0]
                    
                    # Update form state and go to transcript type selection
                    user_form_state[interaction3.user.id]['strike'] = strike
                    user_form_state[interaction3.user.id]['sanction'] = chosen
                    
                    await interaction3.response.send_message(
                        "Select transcript type:", 
                        view=TranscriptTypeView(self.player, self.offense, strike, chosen), 
                        ephemeral=True
                    )

            class SanctionView(discord.ui.View):
                def __init__(self):
                    super().__init__()
                    self.add_item(SanctionSelect())

            await interaction.response.send_message("Select a ban duration:", view=SanctionView(), ephemeral=True)
        else:
            # Update form state and go to transcript type selection
            user_form_state[interaction.user.id]['strike'] = strike
            user_form_state[interaction.user.id]['sanction'] = sanctions
            
            await interaction.response.send_message(
                "Select transcript type:", 
                view=TranscriptTypeView(self.player, self.offense, strike, sanctions), 
                ephemeral=True
            )

class OffenseView(discord.ui.View):
    def __init__(self, player: dict):
        super().__init__()
        self.player = player
        
        offense_select = OffenseSelect(player)
        self.add_item(offense_select)
        self.add_item(BackButton("player"))

class OffenseSelect(discord.ui.Select):
    def __init__(self, player: dict):
        self.player = player
        # Add unban options to the punishment list
        all_offenses = list(punishments.keys()) + ["UNBAN (Strike Remains)", "UNBAN (Remove Strike)"]
        options = [discord.SelectOption(label=o) for o in all_offenses]
        super().__init__(placeholder="Select offense...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        
        offense = self.values[0]
        
        # Update form state
        user_form_state[interaction.user.id]['offense'] = offense
        
        if offense == "Custom Punishment":
            await interaction.response.send_modal(CustomPunishmentModal(self.player))
            return
        elif offense in ["UNBAN (Strike Remains)", "UNBAN (Remove Strike)"]:
            # Go directly to report selection for unbans
            await interaction.response.send_message(
                "Select which report to unban:", 
                view=UnbanReportView(self.player['BohemiaUID'], offense), 
                ephemeral=True
            )
            return
        
        await interaction.response.send_message("Select the strike level:", view=StrikeView(self.player, offense), ephemeral=True)

class PlayerView(discord.ui.View):
    def __init__(self, players: list):
        super().__init__()
        self.players = players
        
        player_select = PlayerSelect(players)
        self.add_item(player_select)
        
        # Add a button to search for a different player
        search_again_button = discord.ui.Button(
            label="🔍 Search Again", 
            style=discord.ButtonStyle.secondary
        )
        search_again_button.callback = self.search_again
        self.add_item(search_again_button)
    
    async def search_again(self, interaction: discord.Interaction):
        """Allow user to search for a different player"""
        modal = PlayerSearchModal(from_buildbanform=True)
        await interaction.response.send_modal(modal)

class PlayerSelect(discord.ui.Select):
    def __init__(self, players: list):
        self.players = players
        options = []
        
        for player in players[:25]:  # Discord limit of 25 options
            label = player["Name"]
            description = f"Level {player['Level']} - Last played {player['Last Played']}"
            
            # Truncate if too long for Discord limits
            if len(label) > 100:
                label = label[:97] + "..."
            if len(description) > 100:
                description = description[:97] + "..."
                
            options.append(discord.SelectOption(
                label=label, 
                description=description,
                value=player["Name"]  # Use name as value since it should be unique in our search results
            ))
        
        super().__init__(placeholder="Choose a player...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        
        # Find the selected player by name
        player = next(p for p in self.players if p["Name"] == self.values[0])
        
        # Update form state
        user_form_state[interaction.user.id]['player'] = player
        
        # Show selected player info
        embed = discord.Embed(
            title="Player Selected for Ban Form",
            color=discord.Color.green()
        )
        embed.add_field(name="Name", value=player["Name"], inline=True)
        embed.add_field(name="Level", value=player["Level"], inline=True)
        embed.add_field(name="Last Played", value=player["Last Played"], inline=True)
        embed.add_field(name="Bohemia UID", value=player["BohemiaUID"], inline=False)
        
        await interaction.response.send_message(
            embed=embed,
            view=OffenseView(player), 
            ephemeral=True
        )

# New player search command
@tree.command(name="find_player", description="Search for a player in the database")
async def find_player(interaction: discord.Interaction):
    """Find players by name using a search modal"""
    modal = PlayerSearchModal(from_buildbanform=False)
    await interaction.response.send_modal(modal)

# Updated ban_player command to use modal  
@tree.command(name="ban_player", description="Start the ban process by searching for a player")
async def ban_player(interaction: discord.Interaction):
    """Start the ban process with player search"""
    modal = PlayerSearchModal(from_buildbanform=False)
    await interaction.response.send_modal(modal)

# Updated buildbanform command to immediately show search modal
@tree.command(name="buildbanform", description="Build a formatted ban form by searching for a player")
async def buildbanform(interaction: discord.Interaction):
    """Build a formatted ban form - starts with player search"""
    modal = PlayerSearchModal(from_buildbanform=True)
    await interaction.response.send_modal(modal)

# Ban history command
@tree.command(name="banhistory", description="View ban history for a player")
async def banhistory(interaction: discord.Interaction, buid: str):
    history = ban_tracker.get_player_history(buid)
    
    if not history:
        await interaction.response.send_message(f"No ban history found for BUID: {buid}", ephemeral=True)
        return
    
    history_text = f"**Ban History for BUID: {buid}**\n\n"
    
    for ban in history[-10:]:  # Last 10 bans
        unban_marker = "🔓 " if ban.get('is_unban', False) else ""
        strike_marker = " ❌" if ban.get('strike_removed', False) else ""
        
        history_text += f"**{unban_marker}Ban #{ban['id']:04d}** - {ban['timestamp'][:10]}{strike_marker}\n"
        history_text += f"Player: {ban['player_name']}\n"
        history_text += f"Offense: {ban['offense']}\n"
        history_text += f"Punishment: ({ban['strike']}) {ban['sanction']}\n\n"
    
    await interaction.response.send_message(history_text, ephemeral=True)

# Recent bans command
@tree.command(name="recentbans", description="View recent ban submissions")
async def recentbans(interaction: discord.Interaction):
    recent = ban_tracker.get_recent_bans(10)
    
    if not recent:
        await interaction.response.send_message("No recent bans found.", ephemeral=True)
        return
    
    recent_text = "**Recent Ban Submissions:**\n\n"
    
    for ban in recent:
        unban_marker = "🔓 " if ban.get('is_unban', False) else ""
        recent_text += f"**{unban_marker}#{ban['id']:04d}** - {ban['player_name']} ({ban['offense']})\n"
        recent_text += f"Punishment: ({ban['strike']}) {ban['sanction']}\n"
        recent_text += f"Date: {ban['timestamp'][:10]}\n\n"
    
    await interaction.response.send_message(recent_text, ephemeral=True)

# Run the bot
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    bot.run(os.getenv("DISCORD_TOKEN"))
