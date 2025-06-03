import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime

# Enable all intents to guarantee privileged access
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

# Extract formatted transcript link
def extract_transcript_link(message: discord.Message) -> str:
    if message.attachments:
        html = next((a for a in message.attachments if a.filename.endswith(".html")), None)
        if html:
            for word in message.content.split():
                if word.lower().startswith("report-") and word[7:].isdigit():
                    report_id = word[7:]
                    return f"[Report-{report_id}](<{message.jump_url}>)"
            return f"[Transcript]({message.jump_url})"
    return ""

# Get list of up to 5 valid transcript links
async def get_transcript_options(guild: discord.Guild, channel_name_contains="transcript") -> list[str]:
    transcript_channel = next((c for c in guild.text_channels if channel_name_contains in c.name.lower()), None)
    if not transcript_channel:
        return []
    transcripts = []
    async for message in transcript_channel.history(limit=25):
        link = extract_transcript_link(message)
        if link:
            transcripts.append(link)
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
        await interaction.response.defer(thinking=False)
        try:
            await interaction.edit_original_response(content="✔️ Submitted.", view=None)
        except:
            pass
        await interaction.followup.send(final_response, ephemeral=False)

class ConfirmationView(discord.ui.View):
    def __init__(self, response_text: str):
        super().__init__()
        self.add_item(ConfirmationButton(response_text))

class TranscriptSelect(discord.ui.Select):
    def __init__(self, transcripts: list[str], player: dict, offense: str, strike: str, sanction: str):
        options = [discord.SelectOption(label=link.split(']')[0][1:], value=link) for link in transcripts]
        super().__init__(placeholder="Select a transcript...", min_values=1, max_values=1, options=options)
        self.player = player
        self.offense = offense
        self.strike = strike
        self.sanction = sanction

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except:
            pass
        await interaction.response.defer(ephemeral=True)
        chosen_link = self.values[0]
        response = (
            f"Transcript link: {chosen_link}\n"
            f"Player(s) being reported: {self.player['Name']}\n"
            f"BUID: {self.player['BohemiaUID']}\n"
            f"Verdict/Reason for ban: {self.offense}\n"
            f"Ban Length: ({self.strike}) {self.sanction}"
        )
        await interaction.followup.send(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

class TranscriptView(discord.ui.View):
    def __init__(self, transcripts, player, offense, strike, sanction):
        super().__init__()
        self.add_item(TranscriptSelect(transcripts, player, offense, strike, sanction))

# Fetch latest transcript from a designated channel
async def get_latest_transcript(guild: discord.Guild, channel_name_contains="transcript") -> str:
    transcript_channel = next((c for c in guild.text_channels if channel_name_contains in c.name.lower()), None)
    if not transcript_channel:
        return "[Transcript Not Found]"

    async for message in transcript_channel.history(limit=10):
        link = extract_transcript_link(message)
        if link:
            return link
    return "[Transcript Not Found]"

# Slash command
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

# Show offense selection
async def show_offense_menu(interaction: discord.Interaction, player: dict):
    class OffenseSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=o) for o in punishments.keys()]
            super().__init__(placeholder="Select offense...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
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

# Define or import your punishment dictionary before running
punishments = {
    "Custom Punishment": { "Custom": "Manual Entry" },
    "Spamming": {
        "Strike 1": "30‑Min /timeout",
        "Strike 2": "1 Day Ban",
        "Strike 3": "1 Month Ban",
        "Strike 4": "Permanent Ban"
    },
    "Prohibited Messages & Links": {
        "Strike 1": "1 Hour /timeout",
        "Strike 2": "24 Hour /timeout",
        "Strike 3": "7 Day Ban",
        "Strike 4": "Permanent Ban"
    },
    "Advertising": {
        "Strike 1": "3 Hour /timeout",
        "Strike 2": "24 Hour /timeout",
        "Strike 3": "7 Day Ban",
        "Strike 4": "Permanent Ban"
    },
    "Staff Disrespect": {
        "Strike 1": "4 Hour /timeout",
        "Strike 2": "25 Hour /timeout",
        "Strike 3": "7 Day Ban",
        "Strike 4": "Permanent Ban"
    },
    "Team Killing": {
        "Strike 1": ["3 Day Ban", "4 Day Ban", "5 Day Ban", "6 Day Ban", "7 Day Ban"],
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "In‑Game": {
        "Strike 1": "Warning",
        "Strike 2": "Strike 2",
        "Strike 3": "Strike 3",
        "Strike 4": "Strike 4"
    },
    "Prohibited Messages & Links (Severe)": {
        "Strike 1": "3 Month Ban",
        "Strike 2": "1 Year Ban",
        "Strike 3": "Permanent Ban",
        "Strike 4": "Permanent Ban"
    },
    "Prohibited Messages & Links (Minor)": {
        "Strike 1": "1 Week Ban",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Exploiting": {
        "Strike 1": "3 Month Ban",
        "Strike 2": "6‑12 Month Ban",
        "Strike 3": "1‑2 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Cheating": {
        "Strike 1": "Permanent Ban",
        "Strike 2": "Permanent Ban",
        "Strike 3": "Permanent Ban",
        "Strike 4": "Permanent Ban"
    },
    "Damaging Team Vehicles": {
        "Strike 1": "3 Day Ban",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Air to Air Ramming / Air to Enemy": {
        "Strike 1": "3 Day Ban",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Trolling / Griefing / Minging": {
        "Strike 1": "7 Day Ban",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Spawncamping with LOS": {
        "Strike 1": "Warning",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Spawncamping without LOS": {
        "Strike 1": "Warning",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Abusing spawnprotection": {
        "Strike 1": "Warning",
        "Strike 2": "1 Month Ban",
        "Strike 3": "1 Year Ban",
        "Strike 4": "Permanent Ban"
    },
    "Stream‑Sniping": {
        "Strike 1": "Warning",
        "Strike 2": "3 Week Ban",
        "Strike 3": "3 Month Ban",
        "Strike 4": "Permanent Ban"
    },
    "Ghosting": {
        "Strike 1": "Warning",
        "Strike 2": "3 Week Ban",
        "Strike 3": "3 Month Ban",
        "Strike 4": "Permanent Ban"
    },
    "Going AFK": {
        "Strike 1": "Warning",
        "Strike 2": "Kick from Server",
        "Strike 3": "Kick from Server",
        "Strike 4": "Kick from Server"
    },
    "Ban Evading": {
        "Strike 1": "Warning",
        "Strike 2": "Permanent Ban",
        "Strike 3": "Permanent Ban",
        "Strike 4": "Permanent Ban"
    }
}


# Show strike menu
async def show_strike_menu(interaction: discord.Interaction, player: dict, offense: str):
    class StrikeSelect(discord.ui.Select):
        def __init__(self):
            self.strikes = punishments[offense]
            options = [discord.SelectOption(label=s) for s in self.strikes.keys()]
            super().__init__(placeholder="Select strike level...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            try:
                await interaction2.message.delete()
            except:
                pass
            await interaction2.response.defer(ephemeral=True)
            strike = self.values[0]
            sanctions = self.strikes[strike]
            transcript_link = await get_latest_transcript(interaction2.guild)

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
                        await interaction3.response.defer(ephemeral=True)
                        chosen = self3.values[0]
                        response = (
                            f"Transcript link: {transcript_link}\n"
                            f"Player(s) being reported: {player['Name']}\n"
                            f"BUID: {player['BohemiaUID']}\n"
                            f"Verdict/Reason for ban: {offense}\n"
                            f"Ban Length: ({strike}) {chosen}"
                        )
                        await interaction3.followup.send(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

                class SanctionView(discord.ui.View):
                    def __init__(self):
                        super().__init__()
                        self.add_item(SanctionSelect())

                await interaction2.followup.send("Select a ban duration:", view=SanctionView(), ephemeral=True)
                return
            else:
                response = (
                    f"Transcript link: {transcript_link}\n"
                    f"Player(s) being reported: {player['Name']}\n"
                    f"BUID: {player['BohemiaUID']}\n"
                    f"Verdict/Reason for ban: {offense}\n"
                    f"Ban Length: ({strike}) {sanctions}"
                )
                await interaction2.followup.send(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

    class StrikeView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(StrikeSelect())

    await interaction.followup.send("Select the strike level:", view=StrikeView(), ephemeral=True)

# Run the bot
bot.run(os.getenv("DISCORD_TOKEN"))

