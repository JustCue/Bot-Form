import os
import re
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime

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
        # Defer the interaction from the button click
        await interaction.response.defer(thinking=False) 
        try:
            # Edit the message that contained the button
            await interaction.edit_original_response(content="✔️ Submitted.", view=None) 
        except discord.HTTPException:
            # Fallback if original message can't be edited (e.g., already deleted, or different interaction type)
            try:
                await interaction.followup.send(content="✔️ Submitted.", ephemeral=True) # Send a new ephemeral message
            except discord.HTTPException:
                pass # If all else fails, just proceed
        
        # Send the final response as a new, non-ephemeral message
        target_channel = interaction.channel # Or a specific channel if needed
        if target_channel:
            await target_channel.send(final_response)
        else: # Fallback if channel is not available for some reason
             await interaction.followup.send(final_response, ephemeral=False)


class ConfirmationView(discord.ui.View):
    def __init__(self, response_text: str):
        super().__init__()
        self.add_item(ConfirmationButton(response_text))

class TranscriptSelect(discord.ui.Select):
    def __init__(self, transcripts: list[str], player: dict, offense: str, strike: str, sanction: str):
        self.transcript_map = {}
        options = []
        options.append(discord.SelectOption(label="Will add later", value="add_later"))
        for link in transcripts:
            match = re.match(r"\[(.*?)\]\(<(.*?)>\)", link)
            if match:
                label, url = match.groups()
                if url not in self.transcript_map:
                    self.transcript_map[url] = label
                    options.append(discord.SelectOption(label=label, value=url))
        super().__init__(placeholder="Select a transcript or 'Will add later'...", min_values=1, max_values=1, options=options)
        self.player = player
        self.offense = offense
        self.strike = strike
        self.sanction = sanction

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
        await interaction.response.defer(ephemeral=True)
        chosen_value = self.values[0]
        if chosen_value == "add_later":
            link = "Will add later"
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
        await interaction.followup.send(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

class TranscriptView(discord.ui.View):
    def __init__(self, transcripts, player, offense, strike, sanction):
        super().__init__()
        self.add_item(TranscriptSelect(transcripts, player, offense, strike, sanction))

punishments = {
    "Custom Punishment": {},
    "Spamming": {"Strike 1": "30‑Min /timeout", "Strike 2": "1 Day Ban", "Strike 3": "1 Month Ban", "Strike 4": "Permanent Ban"},
    "Prohibited Messages & Links": {"Strike 1": "1 Hour /timeout", "Strike 2": "24 Hour /timeout", "Strike 3": "7 Day Ban", "Strike 4": "Permanent Ban"},
    "Advertising": {"Strike 1": "3 Hour /timeout", "Strike 2": "24 Hour /timeout", "Strike 3": "7 Day Ban", "Strike 4": "Permanent Ban"},
    "Staff Disrespect": {"Strike 1": "4 Hour /timeout", "Strike 2": "25 Hour /timeout", "Strike 3": "7 Day Ban", "Strike 4": "Permanent Ban"},
    "Team Killing": {"Strike 1": ["3 Day Ban", "4 Day Ban", "5 Day Ban", "6 Day Ban", "7 Day Ban"], "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "In‑Game": {"Strike 1": "Warning", "Strike 2": "Strike 2", "Strike 3": "Strike 3", "Strike 4": "Strike 4"},
    "Prohibited Messages & Links (Severe)": {"Strike 1": "3 Month Ban", "Strike 2": "1 Year Ban", "Strike 3": "Permanent Ban", "Strike 4": "Permanent Ban"},
    "Prohibited Messages & Links (Minor)": {"Strike 1": "1 Week Ban", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Exploiting": {"Strike 1": "3 Month Ban", "Strike 2": "6‑12 Month Ban", "Strike 3": "1‑2 Year Ban", "Strike 4": "Permanent Ban"},
    "Cheating": {"Strike 1": "Permanent Ban", "Strike 2": "Permanent Ban", "Strike 3": "Permanent Ban", "Strike 4": "Permanent Ban"},
    "Damaging Team Vehicles": {"Strike 1": "3 Day Ban", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Air to Air Ramming / Air to Enemy": {"Strike 1": "3 Day Ban", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Trolling / Griefing / Minging": {"Strike 1": "7 Day Ban", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Spawncamping with LOS": {"Strike 1": "Warning", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Spawncamping without LOS": {"Strike 1": "Warning", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Abusing spawnprotection": {"Strike 1": "Warning", "Strike 2": "1 Month Ban", "Strike 3": "1 Year Ban", "Strike 4": "Permanent Ban"},
    "Stream‑Sniping": {"Strike 1": "Warning", "Strike 2": "3 Week Ban", "Strike 3": "3 Month Ban", "Strike 4": "Permanent Ban"},
    "Ghosting": {"Strike 1": "Warning", "Strike 2": "3 Week Ban", "Strike 3": "3 Month Ban", "Strike 4": "Permanent Ban"},
    "Going AFK": {"Strike 1": "Warning", "Strike 2": "Kick from Server", "Strike 3": "Kick from Server", "Strike 4": "Kick from Server"},
    "Ban Evading": {"Strike 1": "Warning", "Strike 2": "Permanent Ban", "Strike 3": "Permanent Ban", "Strike 4": "Permanent Ban"}
}

class CustomPunishmentModal(discord.ui.Modal):
    def __init__(self, player: dict):
        super().__init__(title="Custom Punishment")
        self.player = player
        self.reason = discord.ui.TextInput(label="Reason", placeholder="Enter ban reason", style=discord.TextStyle.short)
        self.duration = discord.ui.TextInput(label="Duration", placeholder="Enter ban duration (e.g., 7 days)", style=discord.TextStyle.short)
        self.add_item(self.reason)
        self.add_item(self.duration)

    async def callback(self, interaction: discord.Interaction):
        # print(f"CustomPunishmentModal callback triggered by {interaction.user}") # Uncomment for debugging
        reason_text = self.reason.value
        duration_text = self.duration.value
        response = (
            f"Transcript link: N/A\n"
            f"Player(s) being reported: {self.player['Name']}\n"
            f"BUID: {self.player['BohemiaUID']}\n"
            f"Verdict/Reason for ban: {reason_text}\n"
            f"Ban Length: (Custom) {duration_text}"
        )
        # print(f"Modal response to be sent: {response}") # Uncomment for debugging
        try:
            await interaction.response.send_message(
                content=f"Preview:\n{response}",
                view=ConfirmationView(response),
                ephemeral=True
            )
            # print("Modal preview message sent successfully.") # Uncomment for debugging
        except Exception as e:
            print(f"Error in CustomPunishmentModal.callback: {e}") # Uncomment for debugging
            # await interaction.followup.send("An error occurred while processing your custom punishment.", ephemeral=True)


async def show_strike_menu(interaction: discord.Interaction, player: dict, offense: str):
    class StrikeSelect(discord.ui.Select):
        def __init__(self):
            self.strikes = punishments[offense]
            options = [discord.SelectOption(label=s) for s in self.strikes.keys()]
            super().__init__(placeholder="Select strike level...", min_values=1, max_values=1, options=options)

        async def callback(self, interaction2: discord.Interaction):
            try:
                await interaction2.message.delete()
            except: pass
            await interaction2.response.defer(ephemeral=True)
            strike = self.values[0]
            sanctions = self.strikes[strike]

            if isinstance(sanctions, list):
                class SanctionSelect(discord.ui.Select):
                    def __init__(self):
                        super().__init__(placeholder="Select ban duration...", min_values=1, max_values=1, options=[discord.SelectOption(label=d) for d in sanctions])
                    async def callback(self3, interaction3: discord.Interaction):
                        try: await interaction3.message.delete()
                        except: pass
                        await interaction3.response.defer(ephemeral=True)
                        chosen = self3.values[0]
                        transcripts = await get_transcript_options(interaction3.guild)
                        if transcripts: # Includes "Will add later" if get_transcript_options adds it or if TranscriptSelect handles it
                            await interaction3.followup.send("Select a transcript:", view=TranscriptView(transcripts, player, offense, strike, chosen), ephemeral=True)
                        else:
                            link = "N/A"
                            response = (f"Transcript link: {link}\n"
                                        f"Player(s) being reported: {player['Name']}\n"
                                        f"BUID: {player['BohemiaUID']}\n"
                                        f"Verdict/Reason for ban: {offense}\n"
                                        f"Ban Length: ({strike}) {chosen}")
                            await interaction3.followup.send(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)
                class SanctionView(discord.ui.View):
                    def __init__(self):
                        super().__init__()
                        self.add_item(SanctionSelect())
                await interaction2.followup.send("Select a ban duration:", view=SanctionView(), ephemeral=True)
            else: # Sanction is a direct string
                transcripts = await get_transcript_options(interaction2.guild)
                if transcripts:
                    await interaction2.followup.send("Select a transcript:", view=TranscriptView(transcripts, player, offense, strike, sanctions), ephemeral=True)
                else: # No transcripts found
                    link = "N/A" # Corrected
                    response = (f"Transcript link: {link}\n"
                                f"Player(s) being reported: {player['Name']}\n"
                                f"BUID: {player['BohemiaUID']}\n"
                                f"Verdict/Reason for ban: {offense}\n"
                                f"Ban Length: ({strike}) {sanctions}")
                    await interaction2.followup.send(content=f"Preview:\n{response}", view=ConfirmationView(response), ephemeral=True)

    class StrikeView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(StrikeSelect())
    await interaction.followup.send("Select the strike level:", view=StrikeView(), ephemeral=True)


async def show_offense_menu(interaction: discord.Interaction, player: dict):
    class OffenseSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=o) for o in punishments.keys()]
            super().__init__(placeholder="Select offense...", min_values=1, max_values=1, options=options)
        async def callback(self, interaction2: discord.Interaction):
            try: await interaction2.message.delete()
            except: pass
            offense = self.values[0]
            if offense == "Custom Punishment":
                modal = CustomPunishmentModal(player)
                await interaction2.response.send_modal(modal)
                return 
            await interaction2.response.defer(ephemeral=True)
            await show_strike_menu(interaction2, player, offense)
    class OffenseView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(OffenseSelect())
    await interaction.followup.send("Select the offense:", view=OffenseView(), ephemeral=True)


@tree.command(name="buildbanform", description="Build a formatted ban form from latest player info")
async def buildbanform(interaction: discord.Interaction):
    players = []
    # Simplified player fetching for brevity, assuming it works as intended by user
    for channel in interaction.guild.text_channels:
        try:
            async for message in channel.history(limit=20): # Check more messages if needed
                if "Name = " in message.content and "BohemiaUID = " in message.content : # Basic check
                    lines = message.content.replace(",", "\n").splitlines()
                    for line_content in lines: # Each line could be a player string
                        parts = line_content.strip().split(" | ")
                        player_data = {}
                        for part in parts:
                            if " = " in part:
                                k, v = part.split(" = ", 1)
                                player_data[k.strip()] = v.strip()
                        
                        # Ensure all required keys are present before adding
                        if all(k in player_data for k in ("Name", "Level", "Last Played", "BohemiaUID")):
                            # Avoid duplicates based on BohemiaUID
                            if not any(p['BohemiaUID'] == player_data['BohemiaUID'] for p in players):
                                players.append(player_data)
                    if players : break # Found players in this message
            if players: break # Found players in this channel
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"Skipping channel {channel.name} due to error: {e}")
            continue
        if players: break # Exit outer loop if players found

    if not players:
        await interaction.response.send_message("No valid player data found in recent messages.", ephemeral=True)
        return

    # Sort players by "Last Played" if possible, otherwise by name.
    # This requires parsing "Last Played" to datetime, which can be complex.
    # For simplicity, we'll sort by name for now.
    players.sort(key=lambda p: p.get("Name", "").lower())


    class PlayerSelect(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=p["Name"], description=f"Level {p.get('Level','N/A')} - {p.get('Last Played','N/A')}") for p in players[:25]] # Limit to 25 options
            super().__init__(placeholder="Choose a player...", min_values=1, max_values=1, options=options)
        async def callback(self, interaction2: discord.Interaction):
            try: await interaction2.message.delete()
            except: pass
            await interaction2.response.defer(ephemeral=True)
            # Find player from the full 'players' list, not just the potentially sliced one in options
            selected_player_name = self.values[0]
            player = next((p for p in players if p["Name"] == selected_player_name), None)
            if player:
                await show_offense_menu(interaction2, player)
            else:
                await interaction2.followup.send("Could not find player data. Please try again.",ephemeral=True)


    class PlayerView(discord.ui.View):
        def __init__(self):
            super().__init__()
            self.add_item(PlayerSelect())
    await interaction.response.send_message("Select a player to generate the ban form:", view=PlayerView(), ephemeral=True)

# Get the token from environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not set.")
