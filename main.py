import os 
import re
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime
from punishments import punishments  # Import punishments from the separate file

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    try:
        await tree.sync()
        print(f"✅ Synced slash commands globally as {bot.user}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

def generate_transcript_link(message: discord.Message, *args) -> str:
    for attachment in message.attachments:
        if attachment.filename.endswith(".html"):
            # Match any numeric value in the filename, regardless of prefix
            match = re.search(r"(\d+)", attachment.filename)
            if match:
                report_number = int(match.group(1))
                return f"[Report-{report_number:04d}](<{message.jump_url}>)"
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
                transcripts.append(generate_transcript_link(message, index))
                index += 1
        if len(transcripts) >= 5:
            break
    return transcripts

class ConfirmationButton(discord.ui.Button):
    def __init__(self, response_text: str):
        super().__init__(label="Confirm", style=discord.ButtonStyle.green)
        self.response_text = response_text

    async def callback(self, interaction: discord.Interaction):
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        final_response = (
            f"{self.response_text}\n"
            f"Submitted by: {interaction.user.mention}\n"
            f"Time Submitted: {timestamp}"
        )
        # Delete the confirmation message
        try:
            await interaction.message.delete()
        except:
            pass
        
        await interaction.response.send_message(final_response, ephemeral=False)

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction):
        # Delete the confirmation message
        try:
            await interaction.message.delete()
        except:
            pass
        
        await interaction.response.send_message("❌ Ban form cancelled.", ephemeral=True)

class ConfirmationView(discord.ui.View):
    def __init__(self, response_text: str):
        super().__init__()
        self.add_item(ConfirmationButton(response_text))
        self.add_item(CancelButton())

class TranscriptSelect(discord.ui.Select):
    def __init__(self, transcripts: list[str], player: dict, offense: str, strike: str, sanction: str):
        self.transcript_map = {}
        options = []

        # Add the "Will add later" and "Witness" options first
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
        # Delete the transcript selection message
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

        response = (
            f"Transcript link: {link}\n"
            f"Player(s) being reported: {self.player['Name']}\n"
            f"BUID: {self.player['BohemiaUID']}\n"
            f"Verdict/Reason for ban: {self.offense}\n"
            f"Ban Length: ({self.strike}) {self.sanction}"
        )
        await interaction.response.send_message(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

class TranscriptView(discord.ui.View):
    def __init__(self, transcripts, player, offense, strike, sanction):
        super().__init__()
        self.add_item(TranscriptSelect(transcripts, player, offense, strike, sanction))

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
        # Get transcripts for custom punishment
        transcripts = await get_transcript_options(interaction.guild)
        if transcripts:
            await interaction.response.send_message("Select a transcript:", view=TranscriptView(transcripts, self.player, self.reason.value, "Custom", self.length.value), ephemeral=True)
        else:
            # If no transcripts available, provide default preview
            response = (
                f"Transcript link: N/A\n"
                f"Player(s) being reported: {self.player['Name']}\n"
                f"BUID: {self.player['BohemiaUID']}\n"
                f"Verdict/Reason for ban: {self.reason.value}\n"
                f"Ban Length: (Custom) {self.length.value}"
            )
            await interaction.response.send_message(
                content=f"Preview:\n{response}",
                view=ConfirmationView(response),
                ephemeral=True
            )

# Strike selection
async def show_strike_menu(interaction: discord.Interaction, player: dict, offense: str):
    class StrikeSelect(discord.ui.Select):
        def __init__(self):
            self.strikes = punishments[offense]
            options = [discord.SelectOption(label=s) for s in self.strikes.keys()]
            super().__init__(placeholder="Select strike level...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            # Delete the strike selection message
            try:
                await interaction2.message.delete()
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
                        # Delete the sanction selection message
                        try:
                            await interaction3.message.delete()
                        except:
                            pass
                        
                        chosen = self3.values[0]
                        transcripts = await get_transcript_options(interaction3.guild)
                        if transcripts:
                            await interaction3.response.send_message("Select a transcript:", view=TranscriptView(transcripts, player, offense, strike, chosen), ephemeral=True)
                        else:
                            response = (
                                f"Transcript link: N/A\n"
                                f"Player(s) being reported: {player['Name']}\n"
                                f"BUID: {player['BohemiaUID']}\n"
                                f"Verdict/Reason for ban: {offense}\n"
                                f"Ban Length: ({strike}) {chosen}"
                            )
                            await interaction3.response.send_message(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

                class SanctionView(discord.ui.View):
                    def __init__(self):
                        super().__init__()
                        self.add_item(SanctionSelect())

                await interaction2.response.send_message("Select a ban duration:", view=SanctionView(), ephemeral=True)
            else:
                transcripts = await get_transcript_options(interaction2.guild)
                if transcripts:
                    await interaction2.response.send_message("Select a transcript:", view=TranscriptView(transcripts, player, offense, strike, sanctions), ephemeral=True)
                else:
                    response = (
                        f"Transcript link: N/A\n"
                        f"Player(s) being reported: {player['Name']}\n"
                        f"BUID: {player['BohemiaUID']}\n"
                        f"Verdict/Reason for ban: {offense}\n"
                        f"Ban Length: ({strike}) {sanctions}"
                    )
                    await interaction2.response.send_message(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

    class StrikeView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(StrikeSelect())

    await interaction.followup.send("Select the strike level:", view=StrikeView(), ephemeral=True)

# Offense selection
async def show_offense_menu(interaction: discord.Interaction, player: dict):
    class OffenseSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=o) for o in punishments.keys()]
            super().__init__(placeholder="Select offense...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            # Delete the offense selection message
            try:
                await interaction2.message.delete()
            except:
                pass
            
            offense = self.values[0]
            if offense == "Custom Punishment":
                await interaction2.response.send_modal(CustomPunishmentModal(player))
                return
            
            await interaction2.response.defer(ephemeral=True)
            await show_strike_menu(interaction2, player, offense)

    class OffenseView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(OffenseSelect())

    await interaction.followup.send("Select the offense:", view=OffenseView(), ephemeral=True)

# Slash command: /buildbanform
@tree.command(name="buildbanform", description="Build a formatted ban form from latest player info")
async def buildbanform(interaction: discord.Interaction):
    players = []
    for channel in interaction.guild.text_channels:
        try:
            async for message in channel.history(limit=20):
                if "Name = " in message.content:
                    lines = message.content.replace(",", "\n").splitlines()
                    for line in lines:
                        parts = line.strip().split(" | ")
                        player = {}
                        for part in parts:
                            if " = " in part:
                                k, v = part.split(" = ", 1)
                                player[k.strip()] = v.strip()
                        if all(k in player for k in ("Name", "Level", "Last Played", "BohemiaUID")):
                            players.append(player)
                    if players:
                        break
        except (discord.Forbidden, discord.HTTPException):
            continue
        if players:
            break

    if not players:
        await interaction.response.send_message("No valid player data found.", ephemeral=True)
        return

    class PlayerSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=p["Name"], description=f"Level {p['Level']} - {p['Last Played']}") for p in players]
            super().__init__(placeholder="Choose a player...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            # Delete the player selection message
            try:
                await interaction2.message.delete()
            except:
                pass
            
            await interaction2.response.defer(ephemeral=True)
            player = next(p for p in players if p["Name"] == self.values[0])
            await show_offense_menu(interaction2, player)

    class PlayerView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(PlayerSelect())

    await interaction.response.send_message("Select a player to generate the ban form:", view=PlayerView(), ephemeral=True)

# Run the bot
bot.run(os.getenv("DISCORD_TOKEN"))
