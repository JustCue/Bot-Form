import os
from dotenv import load_dotenv
import re
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
from typing import List, Optional

import aiomysql

from punishments import punishments
from ban_history import ban_tracker

load_dotenv()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Store form state for back navigation
user_form_state = {}


class PlayerDatabaseConnection:
    """Connection to the player/game server database"""

    def __init__(self):
        # Game server database connection details
        self.host = os.getenv("PLAYER_DB_HOST", "localhost")
        self.port = int(os.getenv("PLAYER_DB_PORT", 3306))
        self.user = os.getenv("PLAYER_DB_USER", "root")
        self.password = os.getenv("PLAYER_DB_PASSWORD", "")
        self.database = os.getenv("PLAYER_DB_NAME", "game_database")
        self.pool = None

        print(f"DEBUG: Player DB using connection to {self.host}/{self.database}")

    async def initialize(self):
        """Initialize the player database connection pool"""
        try:
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                charset="utf8mb4",
                autocommit=True,
            )
            print("✅ Player database connection established")
        except Exception as e:
            print(f"❌ Player database connection failed: {e}")

    async def close(self):
        """Close the player database connection pool"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def find_players(self, search_term: str) -> List[dict]:
        """Find players by name (partial match) - READ ONLY"""
        if not self.pool:
            print("⚠️ Player database not connected, skipping database search")
            return []

        query = """
            SELECT Name, Level, LastPlayed, BohemiaUID
            FROM PlayerProfiles
            WHERE LOWER(Name) LIKE LOWER(%s)
            ORDER BY LastPlayed DESC
            LIMIT 15
        """
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, (f"%{search_term}%",))
                    rows = await cursor.fetchall()

            players = []
            for row in rows:
                # Calculate hours since last played
                if row["LastPlayed"]:
                    time_diff = datetime.utcnow() - row["LastPlayed"]
                    hours_since = int(time_diff.total_seconds() / 3600)
                else:
                    hours_since = 0

                players.append(
                    {
                        "Name": row["Name"],
                        "Level": row["Level"],
                        "Last Played": f"{hours_since}H",
                        "BohemiaUID": str(row["BohemiaUID"]),
                    }
                )

            return players
        except Exception as e:
            print(f"Player database error: {e}")
            return []


# Initialize player database connection
player_db = PlayerDatabaseConnection()


async def search_channels_for_players(
    guild: discord.Guild, search_term: str
) -> List[dict]:
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
                        if (
                            all(
                                k in player
                                for k in ("Name", "Level", "Last Played", "BohemiaUID")
                            )
                            and search_term_lower in player["Name"].lower()
                        ):
                            # Avoid duplicates
                            if not any(
                                p["BohemiaUID"] == player["BohemiaUID"] for p in players
                            ):
                                players.append(player)

                            # Limit results
                            if len(players) >= 15:
                                break
        except (discord.Forbidden, discord.HTTPException):
            continue

        if len(players) >= 15:
            break

    return players


class PlayerSearchModal(discord.ui.Modal, title="Search for Player"):
    search_term = discord.ui.TextInput(
        label="Player Name",
        style=discord.TextStyle.short,
        placeholder="Enter player name or partial name...",
        required=True,
        min_length=2,
        max_length=50,
    )

    def __init__(self, from_buildbanform: bool = False):
        super().__init__()
        self.from_buildbanform = from_buildbanform

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            # Search database first
            players = await player_db.find_players(self.search_term.value)

            # If no database results, try channel search as fallback
            if not players:
                players = await search_channels_for_players(
                    interaction.guild, self.search_term.value
                )

            if not players:
                embed = discord.Embed(
                    title="No Players Found",
                    description=f"No players found matching '{self.search_term.value}'",
                    color=discord.Color.red(),
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Store players in form state
            user_form_state[interaction.user.id] = {"players": players}

            if self.from_buildbanform:
                # For buildbanform, go directly to player selection
                embed = discord.Embed(
                    title="Build Ban Form - Select Player",
                    description=(
                        f"Found {len(players)} player(s) matching "
                        f"'{self.search_term.value}'. Select a player to generate the ban form:"
                    ),
                    color=discord.Color.blue(),
                )
                preview_lines = []
                for player in players:
                    line = (
                        f"**{player['Name']}** "
                        f"(Level {player['Level']}, Last: {player['Last Played']})"
                    )
                    preview_lines.append(line)

                if len(preview_lines) <= 10:
                    embed.add_field(
                        name="Found Players",
                        value="\n".join(preview_lines),
                        inline=False,
                    )
                else:
                    for i in range(0, len(preview_lines), 10):
                        chunk = preview_lines[i : i + 10]
                        field_num = (i // 10) + 1
                        total_fields = (len(preview_lines) + 9) // 10
                        embed.add_field(
                            name=f"Found Players ({field_num}/{total_fields})",
                            value="\n".join(chunk),
                            inline=False,
                        )

                view = PlayerView(players)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            else:
                # For ban_player, show detailed search results first
                embed = discord.Embed(
                    title="Ban Process - Step 1: Select Player",
                    description=(
                        f"Found {len(players)} player(s) matching "
                        f"'{self.search_term.value}'. Please select the player you want to ban "
                        "from the dropdown below."
                    ),
                    color=discord.Color.orange(),
                )
                preview_lines = []
                for player in players:
                    line = (
                        f"**{player['Name']}** "
                        f"(Level {player['Level']}, Last: {player['Last Played']})"
                    )
                    preview_lines.append(line)

                if len(preview_lines) <= 10:
                    embed.add_field(
                        name="Found Players",
                        value="\n".join(preview_lines),
                        inline=False,
                    )
                else:
                    for i in range(0, len(preview_lines), 10):
                        chunk = preview_lines[i : i + 10]
                        field_num = (i // 10) + 1
                        total_fields = (len(preview_lines) + 9) // 10
                        embed.add_field(
                            name=f"Found Players ({field_num}/{total_fields})",
                            value="\n".join(chunk),
                            inline=False,
                        )

                view = PlayerSearchView(players, self.search_term.value)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            embed = discord.Embed(
                title="Search Error",
                description=f"An error occurred while searching for players: {str(e)}",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def get_transcript_options(
    guild: discord.Guild, channel_name_contains: str = "transcript"
) -> List[str]:
    transcript_channel = next(
        (c for c in guild.text_channels if channel_name_contains in c.name.lower()),
        None,
    )
    if not transcript_channel:
        return []

    transcripts = []
    index = 1
    async for message in transcript_channel.history(limit=50):
        if message.attachments:
            if any(att.filename.endswith(".html") for att in message.attachments):
                transcripts.append(
                    generate_transcript_link(message, transcript_channel.name, index)
                )
                index += 1

        if len(transcripts) >= 5:
            break

    return transcripts


def generate_transcript_link(
    message: discord.Message, channel_name: str, *args
) -> str:
    for attachment in message.attachments:
        if attachment.filename.endswith(".html"):
            match = re.search(r"(\d+)", attachment.filename)
            if match:
                number = int(match.group(1))
                if "ticket" in channel_name.lower():
                    return f"[Ticket-{number:04d}](<{message.jump_url}>)"
                else:
                    return f"[Report-{number:04d}](<{message.jump_url}>)"

    return f"[Transcript](<{message.jump_url}>)"


@bot.event
async def on_ready():
    # Initialize both database connections
    await player_db.initialize()
    await ban_tracker.initialize()
    try:
        await tree.sync()
        print(f"✅ Synced slash commands globally as {bot.user}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")


@bot.event
async def on_close():
    """Clean up both database connections when bot shuts down"""
    await player_db.close()
    await ban_tracker.close()


class PlayerView(discord.ui.View):
    def __init__(self, players: List[dict]):
        super().__init__(timeout=300)  # 5 minute timeout
        self.players = players

        player_select = PlayerSelect(players)
        self.add_item(player_select)

        # Add a button to search for a different player
        search_again_button = discord.ui.Button(
            label="🔍 Search Again", style=discord.ButtonStyle.secondary
        )
        search_again_button.callback = self.search_again
        self.add_item(search_again_button)

    async def search_again(self, interaction: discord.Interaction):
        """Allow user to search for a different player"""
        modal = PlayerSearchModal(from_buildbanform=True)
        await interaction.response.send_modal(modal)


class PlayerSelect(discord.ui.Select):
    def __init__(self, players: List[dict]):
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

            options.append(
                discord.SelectOption(label=label, description=description, value=player["Name"])
            )

        super().__init__(
            placeholder="Choose a player...", min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass

        # Find the selected player by name
        player = next(p for p in self.players if p["Name"] == self.values[0])

        # Update form state
        user_form_state[interaction.user.id]["player"] = player

        # Show selected player info
        embed = discord.Embed(
            title="Player Selected for Ban Form", color=discord.Color.green()
        )
        embed.add_field(name="Name", value=player["Name"], inline=True)
        embed.add_field(name="Level", value=player["Level"], inline=True)
        embed.add_field(name="Last Played", value=player["Last Played"], inline=True)
        embed.add_field(name="Bohemia UID", value=player["BohemiaUID"], inline=False)

        await interaction.response.send_message(
            embed=embed, view=OffenseView(player), ephemeral=True
        )


class PlayerSearchView(discord.ui.View):
    def __init__(self, players: List[dict], search_term: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.players = players
        self.search_term = search_term
        self.selected_player = None

        # Show detailed results button
        show_results_button = discord.ui.Button(
            label="📋 Show Detailed Results", style=discord.ButtonStyle.primary
        )
        show_results_button.callback = self.show_detailed_results
        self.add_item(show_results_button)

        # Create select menu with player options
        options = []
        for i, player in enumerate(players[:25]):  # Discord limit of 25 options
            label = f"{player['Name']} (Level {player['Level']})"
            description = f"Last played: {player['Last Played']}"

            # Truncate if needed
            if len(label) > 100:
                label = label[:97] + "..."
            if len(description) > 100:
                description = description[:97] + "..."

            options.append(
                discord.SelectOption(label=label, description=description, value=str(i))
            )

        if options:
            self.player_select = discord.ui.Select(
                placeholder="Select a player to proceed with ban...",
                options=options,
            )
            self.player_select.callback = self.player_selected
            self.add_item(self.player_select)

        # Add search again button
        search_again_button = discord.ui.Button(
            label="🔍 Search Again", style=discord.ButtonStyle.secondary
        )
        search_again_button.callback = self.search_again
        self.add_item(search_again_button)

    async def show_detailed_results(self, interaction: discord.Interaction):
        """Show the detailed search results in the requested format"""
        result_lines = []
        for player in self.players:
            line = (
                f"Name = {player['Name']} | Level = {player['Level']} | "
                f"Last Played = {player['Last Played']} | BohemiaUID = {player['BohemiaUID']}"
            )
            result_lines.append(line)

        embed = discord.Embed(
            title=f"Detailed Search Results for '{self.search_term}'",
            description=f"Found {len(self.players)} player(s)",
            color=discord.Color.blue(),
        )

        result_text = "\n".join(result_lines)
        if len(result_text) <= 4000:
            # Leave some room for the title
            embed.description = f"Found {len(self.players)} player(s)\n\n```\n{result_text}\n```"
        else:
            # Split into multiple fields
            chunks = [result_lines[i : i + 8] for i in range(0, len(result_lines), 8)]
            for i, chunk in enumerate(chunks):
                field_name = f"Results {i*8 + 1}-{min((i+1)*8, len(result_lines))}"
                field_value = "```\n" + "\n".join(chunk) + "\n```"
                embed.add_field(name=field_name, value=field_value, inline=False)

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
            "players": self.players,
            "player": self.selected_player,
        }

        # Show selected player details and proceed to offense selection
        embed = discord.Embed(
            title="Player Selected for Ban", color=discord.Color.green()
        )
        embed.add_field(name="Name", value=self.selected_player["Name"], inline=True)
        embed.add_field(name="Level", value=self.selected_player["Level"], inline=True)
        embed.add_field(
            name="Last Played", value=self.selected_player["Last Played"], inline=True
        )
        embed.add_field(
            name="Bohemia UID", value=self.selected_player["BohemiaUID"], inline=False
        )

        await interaction.response.send_message(
            embed=embed, view=OffenseView(self.selected_player), ephemeral=True
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
        all_offenses = list(punishments.keys()) + [
            "UNBAN (Strike Remains)",
            "UNBAN (Remove Strike)",
        ]
        options = [discord.SelectOption(label=o) for o in all_offenses]

        super().__init__(
            placeholder="Select offense...", min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass

        offense = self.values[0]
        # Update form state
        user_form_state[interaction.user.id]["offense"] = offense

        if offense == "Custom Punishment":
            await interaction.response.send_modal(CustomPunishmentModal(self.player))
            return

        if offense in ["UNBAN (Strike Remains)", "UNBAN (Remove Strike)"]:
            # Go directly to report selection for unbans
            await interaction.response.send_message(
                "Select which report to unban:",
                view=UnbanReportView(self.player["BohemiaUID"], offense),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Select the strike level:", view=StrikeView(self.player, offense), ephemeral=True
        )


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

        super().__init__(
            placeholder="Select strike level...", min_values=1, max_values=1, options=options
        )

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
                        options=[discord.SelectOption(label=d) for d in sanctions],
                    )

                async def callback(self3, interaction3: discord.Interaction):
                    try:
                        await interaction3.message.delete()
                    except:
                        pass

                    chosen = self3.values[0]
                    # Update form state and go to transcript type selection
                    user_form_state[interaction3.user.id]["strike"] = strike
                    user_form_state[interaction3.user.id]["sanction"] = chosen
                    await interaction3.response.send_message(
                        "Select transcript type:",
                        view=TranscriptTypeView(self.player, self.offense, strike, chosen),
                        ephemeral=True,
                    )

            class SanctionView(discord.ui.View):
                def __init__(self):
                    super().__init__()
                    self.add_item(SanctionSelect())

            await interaction.response.send_message(
                "Select a ban duration:", view=SanctionView(), ephemeral=True
            )

        else:
            # Update form state and go to transcript type selection
            user_form_state[interaction.user.id]["strike"] = strike
            user_form_state[interaction.user.id]["sanction"] = sanctions
            await interaction.response.send_message(
                "Select transcript type:",
                view=TranscriptTypeView(self.player, self.offense, strike, sanctions),
                ephemeral=True,
            )


class CustomPunishmentModal(discord.ui.Modal, title="Custom Punishment Entry"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.long,
        placeholder="Enter custom reason...",
        required=True,
    )
    length = discord.ui.TextInput(
        label="Ban Length",
        placeholder="Enter ban length (e.g., 3 days)",
        required=True,
    )

    def __init__(self, player: dict):
        super().__init__()
        self.player = player

    async def on_submit(self, interaction: discord.Interaction):
        # Update form state for custom punishment
        user_form_state[interaction.user.id]["offense"] = self.reason.value
        user_form_state[interaction.user.id]["strike"] = "Custom"
        user_form_state[interaction.user.id]["sanction"] = self.length.value

        # Go to transcript type selection
        await interaction.response.send_message(
            "Select transcript type:",
            view=TranscriptTypeView(self.player, self.reason.value, "Custom", self.length.value),
            ephemeral=True,
        )


class UnbanReportSelect(discord.ui.Select):
    def __init__(self, player_buid: str, unban_type: str):
        self.player_buid = player_buid
        self.unban_type = unban_type
        self.remove_strike = unban_type == "UNBAN (Remove Strike)"

        super().__init__(
            placeholder="Loading ban history...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Loading...", value="loading")],
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "loading":
            await self.load_and_update(interaction)
            return

        if self.values[0] == "none":
            await interaction.response.send_message(
                "❌ No valid bans found to unban.", ephemeral=True
            )
            return

        try:
            await interaction.message.delete()
        except:
            pass

        ban_number = self.values[0]
        user_id = interaction.user.id
        state = user_form_state[user_id]

        # Store unban data and proceed to transcript type selection
        unban_data = {"ban_number": ban_number, "remove_strike": self.remove_strike}
        user_form_state[user_id]["unban_data"] = unban_data
        user_form_state[user_id]["strike"] = "UNBAN"
        user_form_state[user_id]["sanction"] = "Player Unbanned"

        await interaction.response.send_message(
            "Select transcript type:",
            view=TranscriptTypeView(state["player"], self.unban_type, "UNBAN", "Player Unbanned", unban_data),
            ephemeral=True,
        )

    async def load_and_update(self, interaction: discord.Interaction):
        """Load ban history and update the view"""
        history = await ban_tracker.get_player_history(self.player_buid)
        options = []

        if history:
            for ban in history[-10:]:  # Last 10 bans
                if not ban.get("is_unban", False):
                    status = " ❌" if ban.get("strike_removed", False) else ""
                    options.append(
                        discord.SelectOption(
                            label=f"{ban['ban_number']} - {ban['offense'][:50]}{status}",
                            description=f"{ban['timestamp'][:10]} - ({ban['strike']}) {ban['sanction'][:50]}",
                            value=ban["ban_number"],
                        )
                    )

        if not options:
            options.append(
                discord.SelectOption(label="No bans found for this player", value="none", description="Cannot proceed")
            )

        # Update the select menu
        self.options = options
        self.placeholder = (
            f"Select report to unban {'(remove strike)' if self.remove_strike else '(keep strike)'}..."
        )

        new_view = UnbanReportView(self.player_buid, self.unban_type)
        new_select = new_view.children[0]  # The select in the new view
        new_select.options = options
        new_select.placeholder = self.placeholder

        await interaction.response.edit_message(view=new_view)


class UnbanReportView(discord.ui.View):
    def __init__(self, player_buid: str, unban_type: str):
        super().__init__()
        self.add_item(UnbanReportSelect(player_buid, unban_type))
        self.add_item(BackButton("offense"))


class TranscriptTypeSelect(discord.ui.Select):
    def __init__(
        self,
        player: dict,
        offense: str,
        strike: str,
        sanction: str,
        unban_data: dict = None,
    ):
        self.player = player
        self.offense = offense
        self.strike = strike
        self.sanction = sanction
        self.unban_data = unban_data

        # Report transcripts appear first (on top)
        options = [
            discord.SelectOption(
                label="Report Transcript", value="report-transcripts", description="Transcripts from report investigations"
            ),
            discord.SelectOption(
                label="Ticket Transcript", value="ticket-transcripts", description="Transcripts from player appeals/tickets"
            ),
        ]

        super().__init__(placeholder="Select transcript type...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass

        transcript_type = self.values[0]
        transcripts = await get_transcript_options(interaction.guild, transcript_type)

        if transcripts:
            await interaction.response.send_message(
                f"Select a transcript from {transcript_type}:",
                view=TranscriptView(transcripts, self.player, self.offense, self.strike, self.sanction, self.unban_data),
                ephemeral=True,
            )
        else:
            response = (
                f"Transcript link: N/A\n"
                f"Player(s) being reported: {self.player['Name']}\n"
                f"BUID: {self.player['BohemiaUID']}\n"
                f"Verdict/Reason for ban: {self.offense}\n"
                f"Ban Length: ({self.strike}) {self.sanction}"
            )

            if self.unban_data:
                response += f"\nRelated to Ban {self.unban_data['ban_number']}"

            if not self.unban_data:
                previous_strikes = await ban_tracker.get_player_strikes(self.player["BohemiaUID"])
                if previous_strikes > 0:
                    response += f"\n⚠️ **Previous Strikes:** {previous_strikes}"

            await interaction.response.send_message(
                content=f"No transcripts found in {transcript_type}.\n\nPreview:\n{response}",
                view=ConfirmationView(response, self.player, self.offense, self.strike, self.sanction, "N/A", self.unban_data),
                ephemeral=True,
            )


class TranscriptTypeView(discord.ui.View):
    def __init__(
        self,
        player: dict,
        offense: str,
        strike: str,
        sanction: str,
        unban_data: dict = None,
    ):
        super().__init__()
        self.add_item(TranscriptTypeSelect(player, offense, strike, sanction, unban_data))

        if unban_data:
            self.add_item(BackButton("offense"))
        else:
            self.add_item(BackButton("strike"))


class TranscriptSelect(discord.ui.Select):
    def __init__(
        self,
        transcripts: List[str],
        player: dict,
        offense: str,
        strike: str,
        sanction: str,
        unban_data: dict = None,
    ):
        self.transcript_map = {}
        self.unban_data = unban_data

        options = [
            discord.SelectOption(label="Will add later", value="add_later"),
            discord.SelectOption(label="Witness", value="witness"),
        ]

        for link in transcripts:
            match = re.match(r"\[(.*?)\]\(<(.*?)>\)", link)
            if match:
                label, url = match.groups()
                if url not in self.transcript_map:
                    self.transcript_map[url] = label
                    options.append(discord.SelectOption(label=label, value=url))

        super().__init__(
            placeholder="Select a transcript or option...", min_values=1, max_values=1, options=options
        )

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

        history_note = ""
        if not self.unban_data:
            previous_strikes = await ban_tracker.get_player_strikes(self.player["BohemiaUID"])
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
            response += f"\nRelated to Ban {self.unban_data['ban_number']}"

        await interaction.response.send_message(
            content=f"Preview:\n{response}",
            view=ConfirmationView(response, self.player, self.offense, self.strike, self.sanction, link, self.unban_data),
            ephemeral=True,
        )


class TranscriptBackButton(discord.ui.Button):
    def __init__(
        self,
        player: dict,
        offense: str,
        strike: str,
        sanction: str,
        unban_data: dict = None,
    ):
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
            "player": self.player,
            "offense": self.offense,
            "strike": self.strike,
            "sanction": self.sanction,
            "unban_data": self.unban_data,
            "players": user_form_state.get(interaction.user.id, {}).get("players", []),
        }

        await interaction.response.send_message(
            "Select transcript type:",
            view=TranscriptTypeView(self.player, self.offense, self.strike, self.sanction, self.unban_data),
            ephemeral=True,
        )


class TranscriptView(discord.ui.View):
    def __init__(
        self,
        transcripts: List[str],
        player: dict,
        offense: str,
        strike: str,
        sanction: str,
        unban_data: dict = None,
    ):
        super().__init__()
        self.add_item(TranscriptSelect(transcripts, player, offense, strike, sanction, unban_data))
        self.add_item(TranscriptBackButton(player, offense, strike, sanction, unban_data))


class ConfirmationButton(discord.ui.Button):
    def __init__(
        self,
        response_text: str,
        player_data: dict,
        offense: str,
        strike: str,
        sanction: str,
        transcript: str,
        unban_data: dict = None,
    ):
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
            if self.unban_data["remove_strike"]:
                success = await ban_tracker.remove_strike(self.unban_data["ban_number"])
                if success:
                    strike_note = f" (Strike removed from Ban {self.unban_data['ban_number']})"
                else:
                    strike_note = f" (Failed to remove strike from Ban {self.unban_data['ban_number']})"
            else:
                strike_note = f" (Strike remains from Ban {self.unban_data['ban_number']})"

            ban_number = await ban_tracker.add_ban(
                player_name=self.player_data["Name"],
                buid=self.player_data["BohemiaUID"],
                offense=self.offense + strike_note,
                strike="UNBAN",
                sanction=self.sanction,
                transcript=self.transcript,
                submitted_by=str(interaction.user.id),
                is_unban=True,
                related_ban_id=self.unban_data.get("ban_id"),
            )
        else:
            ban_number = await ban_tracker.add_ban(
                player_name=self.player_data["Name"],
                buid=self.player_data["BohemiaUID"],
                offense=self.offense,
                strike=self.strike,
                sanction=self.sanction,
                transcript=self.transcript,
                submitted_by=str(interaction.user.id),
            )

        final_response = (
            f"{self.response_text}\n"
            f"Submitted by: {interaction.user.mention}\n"
            f"Ban ID: {ban_number}"
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
            await interaction.response.send_message(
                "❌ Form state lost. Please start over.", ephemeral=True
            )
            return

        state = user_form_state[user_id]

        try:
            await interaction.message.delete()
        except:
            pass

        if self.back_to == "player":
            await interaction.response.send_message(
                "Select a player to generate the ban form:",
                view=PlayerView(state.get("players", [])),
                ephemeral=True,
            )
        elif self.back_to == "offense":
            await interaction.response.send_message(
                "Select the offense:",
                view=OffenseView(state["player"]),
                ephemeral=True,
            )
        elif self.back_to == "strike":
            await interaction.response.send_message(
                "Select the strike level:",
                view=StrikeView(state["player"], state["offense"]),
                ephemeral=True,
            )
        elif self.back_to == "transcript_type":
            await interaction.response.send_message(
                "Select transcript type:",
                view=TranscriptTypeView(
                    state["player"],
                    state["offense"],
                    state["strike"],
                    state["sanction"],
                    state.get("unban_data"),
                ),
                ephemeral=True,
            )


class ConfirmationView(discord.ui.View):
    def __init__(
        self,
        response_text: str,
        player_data: dict,
        offense: str,
        strike: str,
        sanction: str,
        transcript: str,
        unban_data: dict = None,
    ):
        super().__init__()
        self.add_item(
            ConfirmationButton(response_text, player_data, offense, strike, sanction, transcript, unban_data)
        )
        self.add_item(BackButton("transcript_type"))
        self.add_item(CancelButton())


# Slash Commands
@tree.command(name="find_player", description="Search for a player in the database")
async def find_player(interaction: discord.Interaction):
    """Find players by name using a search modal"""
    modal = PlayerSearchModal(from_buildbanform=False)
    await interaction.response.send_modal(modal)


@tree.command(name="ban_player", description="Start the ban process by searching for a player")
async def ban_player(interaction: discord.Interaction):
    """Start the ban process with player search"""
    modal = PlayerSearchModal(from_buildbanform=True)
    await interaction.response.send_modal(modal)


#@tree.command(name="buildbanform", description="Build a formatted ban form by searching for a player")
#async def buildbanform(interaction: discord.Interaction):
#    """Build a formatted ban form - starts with player search"""
#    modal = PlayerSearchModal(from_buildbanform=True)
#    await interaction.response.send_modal(modal)


@tree.command(name="banhistory", description="View ban history for a player")
async def banhistory(interaction: discord.Interaction, buid: str):
    """View complete ban history for a player by BUID"""
    history = await ban_tracker.get_player_history(buid)

    if not history:
        embed = discord.Embed(
            title="No History Found",
            description=f"No ban history found for BUID: {buid}",
            color=discord.Color.yellow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Ban History for {history[0]['player_name']}",
        description=f"BUID: {buid}",
        color=discord.Color.blue(),
    )
    history_text = ""
    for ban in history[-10:]:
        unban_marker = "🔓 " if ban.get("is_unban", False) else ""
        strike_marker = " ❌" if ban.get("strike_removed", False) else ""
        history_text += f"**{unban_marker}{ban['ban_number']}** - {ban['timestamp'][:10]}{strike_marker}\n"
        history_text += f"Offense: {ban['offense']}\n"
        history_text += f"Punishment: ({ban['strike']}) {ban['sanction']}\n\n"

    if len(history_text) <= 1024:
        embed.add_field(name="Recent History", value=history_text, inline=False)
    else:
        chunks = [history_text[i : i + 1020] for i in range(0, len(history_text), 1020)]
        for i, chunk in enumerate(chunks[:3]):
            field_name = f"History {i+1}" if i > 0 else "Recent History"
            embed.add_field(name=field_name, value=chunk, inline=False)

    strike_count = await ban_tracker.get_player_strikes(buid)
    embed.add_field(name="Active Strikes", value=str(strike_count), inline=True)
    embed.add_field(name="Total Records", value=str(len(history)), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="recentbans", description="View recent ban submissions")
async def recentbans(interaction: discord.Interaction, limit: int = 10):
    """View recent ban submissions (default: 10, max: 25)"""
    if limit > 25:
        limit = 25
    elif limit < 1:
        limit = 10

    recent = await ban_tracker.get_recent_bans(limit)

    if not recent:
        embed = discord.Embed(
            title="No Recent Bans",
            description="No recent ban submissions found.",
            color=discord.Color.yellow(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Recent Ban Submissions (Last {len(recent)})",
        color=discord.Color.red(),
    )
    recent_text = ""
    for ban in recent:
        unban_marker = "🔓 " if ban.get("is_unban", False) else ""
        recent_text += f"**{unban_marker}{ban['ban_number']}** - {ban['player_name']}\n"
        recent_text += f"Offense: {ban['offense'][:60]}{'...' if len(ban['offense']) > 60 else ''}\n"
        recent_text += f"Punishment: ({ban['strike']}) {ban['sanction']}\n"
        recent_text += f"Date: {ban['timestamp'][:10]}\n\n"

    if len(recent_text) <= 1024:
        embed.add_field(name="Recent Submissions", value=recent_text, inline=False)
    else:
        chunks = [recent_text[i : i + 1020] for i in range(0, len(recent_text), 1020)]
        for i, chunk in enumerate(chunks[:3]):
            field_name = f"Recent Submissions {i+1}" if i > 0 else "Recent Submissions"
            embed.add_field(name=field_name, value=chunk, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="searchban", description="Search for a specific ban by ban number")
async def searchban(interaction: discord.Interaction, ban_number: str):
    """Search for a specific ban by ban number"""
    ban = await ban_tracker.get_ban_by_number(ban_number)

    if not ban:
        embed = discord.Embed(
            title="Ban Not Found",
            description=f"No ban found with number: {ban_number}",
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Ban Details - {ban['ban_number']}",
        color=discord.Color.orange() if ban["is_unban"] else discord.Color.red(),
    )

    if ban["is_unban"]:
        embed.add_field(name="🔓 Type", value="UNBAN", inline=True)

    embed.add_field(name="Player", value=ban["player_name"], inline=True)
    embed.add_field(name="BUID", value=ban["buid"], inline=True)
    embed.add_field(name="Offense", value=ban["offense"], inline=False)
    embed.add_field(name="Strike Level", value=ban["strike"], inline=True)
    embed.add_field(name="Sanction", value=ban["sanction"], inline=True)
    embed.add_field(name="Date", value=ban["timestamp"][:10], inline=True)

    if ban.get("transcript") and ban["transcript"].lower() not in ["n/a", "none"]:
        embed.add_field(name="Transcript", value=ban["transcript"], inline=False)

    if ban.get("strike_removed"):
        embed.add_field(name="⚠️ Status", value="Strike Removed", inline=True)

    strike_count = await ban_tracker.get_player_strikes(ban["buid"])
    embed.add_field(name="Player's Active Strikes", value=str(strike_count), inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    """Handle application command errors"""
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        embed = discord.Embed(
            title="Command on Cooldown",
            description=f"Try again in {error.retry_after:.2f} seconds.",
            color=discord.Color.yellow(),
        )
    else:
        embed = discord.Embed(
            title="Command Error",
            description="An error occurred while executing this command.",
            color=discord.Color.red(),
        )
        print(f"Command error: {error}")

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except:
        pass


if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
