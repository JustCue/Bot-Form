import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio

# Enable all intents to guarantee privileged access
intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Sync slash commands to all guilds globally
@bot.event
async def on_ready():
    try:
        await tree.sync()
        print(f"✅ Synced slash commands globally as {bot.user}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

# Full punishment dictionary from spreadsheet
punishments = {
    "Spamming": {
        "Strike 1": "30-Min /timeout",
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
    "In-Game": {
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
        "Strike 2": "6-12 Month Ban",
        "Strike 3": "1-2 Year Ban",
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
    "Stream-Sniping": {
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
    # ... include more updated rules here if needed

@tree.command(name="buildbanform", description="Build a formatted ban form from latest player info")
async def buildbanform(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    players = []

    # Search recent messages from all text channels
    for channel in interaction.guild.text_channels:
        try:
            async for message in channel.history(limit=20):
                print(f"📥 Scanning message in #{channel.name}:", message.content)
                if "Name = " in message.content:
                    lines = message.content.replace(",", "\n").splitlines()
                    for line in lines:
                        parts = line.strip().split(" | ")
                        player = {}
                        for part in parts:
                            if " = " in part:
                                key, value = part.split(" = ", 1)
                                player[key.strip()] = value.strip()
                        if all(k in player for k in ("Name", "Level", "Last Played", "BohemiaUID")):
                            print("✅ Parsed player:", player)
                            players.append(player)
                    if players:
                        break
        except (discord.Forbidden, discord.HTTPException):
            continue
        if players:
            break

    if not players:
        await interaction.followup.send("No valid player data found.", ephemeral=True)
        return

    class PlayerSelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label=p["Name"], description=f"Level {p['Level']} - {p['Last Played']}")
                for p in players
            ]
            super().__init__(placeholder="Choose a player...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            await interaction2.response.defer(ephemeral=True)
            selected = self.values[0]
            player = next(p for p in players if p["Name"] == selected)
            await show_offense_menu(interaction2, player)

    class PlayerView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(PlayerSelect())

    await interaction.followup.send("Select a player to generate the ban form:", view=PlayerView(), ephemeral=True)

async def show_offense_menu(interaction: discord.Interaction, player):
    class OffenseSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=o) for o in punishments.keys()]
            super().__init__(placeholder="Select offense...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            await interaction2.response.defer(ephemeral=True)
            offense = self.values[0]
            await show_strike_menu(interaction2, player, offense)

    class OffenseView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(OffenseSelect())

    await interaction.followup.send("Select the offense:", view=OffenseView(), ephemeral=True)

async def show_strike_menu(interaction: discord.Interaction, player, offense):
    class StrikeSelect(discord.ui.Select):
        def __init__(self):
            self.strikes = punishments[offense]
            options = [discord.SelectOption(label=strike) for strike in self.strikes.keys()]
            super().__init__(placeholder="Select strike level...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            await interaction2.response.defer(ephemeral=True)
            strike = self.values[0]
            sanctions = self.strikes[strike]

            if isinstance(sanctions, list):
                # Send a second dropdown for multiple sanction options
                class SanctionSelect(discord.ui.Select):
                    def __init__(self):
                        super().__init__(
                            placeholder="Select ban duration...",
                            min_values=1,
                            max_values=1,
                            options=[discord.SelectOption(label=s) for s in sanctions]
                        )

                    async def callback(self2, interaction3: discord.Interaction):
                        await interaction3.response.defer(ephemeral=True)
                        sanction = self2.values[0]
                        response = (
                            f"Transcript link: \n"
                            f"Player(s) being reported: {player['Name']}\n"
                            f"BUID: {player['BohemiaUID']}\n"
                            f"Verdict/Reason for ban: {offense}\n"
                            f"Ban Length: ({strike}) {sanction}"
                        )
                        await interaction3.followup.send(
                            content="Please confirm the ban form below:",
                            view=ConfirmationView(response),
                            ephemeral=True
                        )

                class SanctionView(discord.ui.View):
                    def __init__(self):
                        super().__init__()
                        self.add_item(SanctionSelect())

                await interaction2.followup.send("Select a ban duration:", view=SanctionView(), ephemeral=True)
                return
            else:
                sanction = sanctions

            response = (
                f"Transcript link: \n"
                f"Player(s) being reported: {player['Name']}\n"
                f"BUID: {player['BohemiaUID']}\n"
                f"Verdict/Reason for ban: {offense}\n"
                f"Ban Length: ({strike}) {sanction}"
            )
            await interaction2.followup.send(response, ephemeral=True)

    class StrikeView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(StrikeSelect())

    await interaction.followup.send("Select the strike level:", view=StrikeView(), ephemeral=True)


class ConfirmationView(discord.ui.View):
    def __init__(self, response_text):
        super().__init__()
        self.response_text = response_text
        self.add_item(ConfirmationButton(response_text))

class ConfirmationButton(discord.ui.Button):
    def __init__(self, response_text):
        super().__init__(label="Confirm", style=discord.ButtonStyle.green)
        self.response_text = response_text

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            content=f"✅ Confirmed:\n\n{self.response_text}",
            ephemeral=True
        )

# Run the bot
bot.run(os.getenv("DISCORD_TOKEN"))
