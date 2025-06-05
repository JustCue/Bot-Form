# Discord Ban Management Bot

A Python-based Discord bot for streamlined player lookups, ban submission forms, and ban history tracking. This bot connects to a MySQL player database (for “find player” functionality) and a ban-history database (for storing and querying bans/unbans). It offers slash commands to search players, build ban forms, view ban history, and more—complete with transcript integration and customizable punishment flows.

---

## Table of Contents

1. [Features](#features)  
2. [Prerequisites](#prerequisites)  
3. [Installation](#installation)  
4. [Configuration](#configuration)  
5. [Usage](#usage)  
   - [Slash Commands](#slash-commands)  
   - [Ban Form Workflow](#ban-form-workflow)  
6. [Project Structure](#project-structure)  
7. [Customizing Punishments](#customizing-punishments)  
8. [Ban History Module](#ban-history-module)  
9. [Development & Contribution](#development--contribution)  
10. [License](#license)  

---

## Features

- **Player Search**  
  • `/find_player`  
  • Queries a MySQL “PlayerProfiles” table by partial name match (up to 15 results).  
  • Falls back to searching recent channel messages for “Name = … | Level = … | Last Played = … | BohemiaUID = …” if the database query returns no hits.  

- **Ban Form / Build Ban Form**  
  • `/ban_player` (formerly `/buildbanform`)  
  • Displays a modal to input a player name → dropdown of matching players → offense selection → strike level/sanction selection → transcript type → transcript selection or “add later” → final preview → confirmation button.  
  • Custom “Custom Punishment” modal for free-form reason/length entries.  
  • Unban workflow: choose an existing ban (removing or keeping the strike), then select transcript and confirm.  

- **Ban History & Recent Bans**  
  • `/banhistory <BUID>` → Displays the last 10 bans/unbans for a given BohemiaUID (with strike count and total records).  
  • `/recentbans [limit]` → Shows the most recent ban submissions (default 10, max 25).  
  • `/searchban <ban_number>` → Looks up a single ban by its ban number, showing all details (offense, strike, sanction, transcript, timestamps, unban status).  

- **Transcript Integration**  
  • Automatically scans a designated “report” or “ticket” channel (by name substring) for the most recent 5 `.html` attachments.  
  • Formats transcript links as `[Report-0001](<URL>)` or `[Ticket-0002](<URL>)` based on filename and channel.  
  • Falls back to “N/A” preview if no transcripts are found.  

- **User-Friendly Navigation**  
  • “← Back” buttons in each step of the ban/unban form to revisit the previous choice without losing form state.  
  • “Cancel” button at any time to abort the form and clear partial entries.  

---

## Prerequisites

1. **Python 3.8+**  
   - The code uses asyncio, `discord.py` v2.x, `aiomysql`, and `python-dotenv`.  
2. **MySQL 5.7+ or MariaDB** (or compatible)  
   - Two separate schemas:  
     1. **Player Profiles** (table: `PlayerProfiles`)  
     2. **Ban History** (managed by `ban_history.py` / `ban_tracker`)  
   - Ensure both schemas exist, and you have a user with read/write permissions.  
3. **Discord Bot Application**  
   - A bot token with the following privileged intents enabled:  
     - Server Members Intent  
     - Message Content Intent (if channel message fallback is used)  
     - All other intents as needed (e.g., to read attachments in history).  
4. **Permissions**  
   - The bot must have “Read Message History” and “Attach Files” (for generating links to transcripts) in the desired channels.  

---

## Installation

1. **Clone the repository**  
   ```bash
   git clone https://github.com/<your-username>/discord-ban-management-bot.git
   cd discord-ban-management-bot
   ```

2. **Create (or activate) a virtual environment**  
   ```bash
   python3 -m venv venv
   source venv/bin/activate        # (Linux/macOS)
   venv\Scripts\activate.bat       # (Windows)
   ```

3. **Install Python dependencies**  
   ```bash
   pip install -r requirements.txt
   ```
   - `requirements.txt` should include:
     ```
     discord.py>=2.0.0
     aiomysql>=0.0.21
     python-dotenv>=0.21.0
     ```

4. **Prepare your MySQL databases**  
   - **Player Database** (example schema):
     ```sql
     CREATE DATABASE IF NOT EXISTS game_database CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

     USE game_database;
     CREATE TABLE IF NOT EXISTS PlayerProfiles (
       BohemiaUID VARCHAR(64) PRIMARY KEY,
       Name VARCHAR(100) NOT NULL,
       Level INT NOT NULL,
       LastPlayed DATETIME,
       -- any other columns…
       INDEX idx_name_lower (Name(50))
     );
     ```
   - **Ban History Database** (example schema—refer to `ban_history.py` for table definitions):
     ```sql
     CREATE DATABASE IF NOT EXISTS ban_history CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

     USE ban_history;
     CREATE TABLE IF NOT EXISTS bans (
       ban_number BIGINT AUTO_INCREMENT PRIMARY KEY,
       player_name VARCHAR(100) NOT NULL,
       buid VARCHAR(64) NOT NULL,
       offense TEXT NOT NULL,
       strike VARCHAR(50) NOT NULL,
       sanction VARCHAR(100) NOT NULL,
       transcript VARCHAR(255),
       timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       is_unban BOOLEAN DEFAULT FALSE,
       related_ban_id BIGINT,
       strike_removed BOOLEAN DEFAULT FALSE
     );
     CREATE INDEX idx_buid ON bans(buid);
     CREATE INDEX idx_timestamp ON bans(timestamp);
     ```

5. **Create & configure `.env`**  
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to include your credentials:
   ```
   DISCORD_TOKEN=your_bot_token_here

   PLAYER_DB_HOST=127.0.0.1
   PLAYER_DB_PORT=3306
   PLAYER_DB_USER=<player_db_username>
   PLAYER_DB_PASSWORD=<player_db_password>
   PLAYER_DB_NAME=game_database

   BAN_DB_HOST=127.0.0.1
   BAN_DB_PORT=3306
   BAN_DB_USER=<ban_db_username>
   BAN_DB_PASSWORD=<ban_db_password>
   BAN_DB_NAME=ban_history
   ```

6. **Run the bot**  
   ```bash
   python main.py
   ```
   You should see:
   ```
   ✅ Player database connection established
   ✅ Ban history connection established
   ✅ Synced slash commands globally as BotName#1234
   ```

---

## Configuration

All configuration is driven by environment variables (loaded via `python-dotenv`).  
Be sure to set:

- `DISCORD_TOKEN` → Your bot’s token from the Discord Developer Portal.  
- **Player DB settings**:
  - `PLAYER_DB_HOST`
  - `PLAYER_DB_PORT`
  - `PLAYER_DB_USER`
  - `PLAYER_DB_PASSWORD`
  - `PLAYER_DB_NAME`
- **Ban History DB settings** (referenced by `ban_history.py` / `ban_tracker`):
  - `BAN_DB_HOST`
  - `BAN_DB_PORT`
  - `BAN_DB_USER`
  - `BAN_DB_PASSWORD`
  - `BAN_DB_NAME`

If you need to change channel names or transcript-search criteria, open `settings.py` (or modify the hardcoded `"transcript"` substring in `get_transcript_options`). By default, it looks for any text channel whose name contains `report` or `ticket` (case-insensitive) and scans the last 50 messages for `.html` attachments.

---

## Usage

### Slash Commands

| Command       | Description                                                  |
| ------------- | ------------------------------------------------------------ |
| `/find_player`  | Launch a modal to search players by partial name (database or fallback). |
| `/ban_player`   | Launch a modal to build and submit a full ban (same as `/buildbanform`). |
| `/banhistory <BUID>` | Display recent ban/unban history for a given BohemiaUID.   |
| `/recentbans [limit]` | List the most recent ban submissions (default 10, max 25).      |
| `/searchban <ban_number>` | Retrieve a specific ban’s full details by ban number.       |

#### Example: `/ban_player`
1. **Modal appears**: “Search for Player” → enter at least 2 characters.  
2. **Dropdown of matching players** (up to 15), showing `Name (Level X, Last: YH)`.  
3. **Select a player** → embed preview with that player’s info → “Select offense…”  
4. **Offense selection** dropdown:
   - Standard punishments (loaded from `punishments.py`), e.g. “Spamming → Strike 2 → 1 Day Ban.”  
   - “Custom Punishment” → opens a modal to enter free-form reason + ban length.  
   - “UNBAN (Strike Remains)” / “UNBAN (Remove Strike)” → skips strike selection and goes directly to unban report selection.  
5. **Strike selection** (if not unban):
   - Dropdown of “Strike 1, Strike 2, …” → either automatically assign a single sanction (string) or open a sub-dropdown if multiple ban durations exist.  
6. **Transcript Type**  
   - “Report Transcript” or “Ticket Transcript.”  
   - Bot fetches up to 5 most recent `.html` attachments from the corresponding channel.  
   - If found, a dropdown lists `[Report-0001](<url>)`, `[Report-0002](<url>)`, etc.  
   - Otherwise, proceeds with “N/A” transcript.  
7. **Final Preview**  
   - Shows:  
     ```markdown
     Transcript link: [Report-0001](<url>)  
     Player(s) being reported: PlayerName  
     BUID: 123456  
     Verdict/Reason for ban: Spamming  
     Ban Length: (Strike 2) 1 Day Ban  
     ⚠️ **Previous Strikes:** 2  
     ```  
   - Buttons: **Confirm** | **← Back** | **Cancel**.  
   - On **Confirm**, the ban is written to the ban history database, and a final channel message (ephemeral or public depending on your logic) displays “Ban submitted … Ban ID: 42.”  

### Ban Form Workflow

```text
/ban_player
   ↓
[Modal] “Search for Player” → type “player”
   ↓
[Ephemeral Embed + Dropdown] Found X players matching…
   ↓
[Dropdown selection] → “Player Selected for Ban”
   ↓
[OffenseView] → pick an item from `punishments.py` (“Custom” or “Unban” options included)
   ↓
[StrikeView] (unless unban) → pick “Strike X”
   ↓
[SanctionSelect] (if multiple durations per strike) → pick “1d, 1w, 1m, etc.”
   ↓
[TranscriptTypeView] → “Report” or “Ticket”
   ↓
[TranscriptView, if attachments exist] → choose from “Report-0001” … “add later” / “witness”
   ↓
[ConfirmationView] → preview + Confirm/Back/Cancel
   ↓
(If confirmed) `ban_tracker.add_ban(...)` → message with Ban ID
```

- **Back** buttons preserve any partially filled state in `user_form_state`, so you can revise a previous selection without starting over.
- **Cancel** clears the form at any stage.

---

## Project Structure

```
.
├── main.py                  # Entry point: defines commands, views, modals, and event handlers
├── punishments.py           # Dictionary of offenses → strikes → sanctions
├── ban_history.py           # Async ban tracker class (add_ban, get_player_history, get_recent_bans, etc.)
├── requirements.txt         # Python dependencies
├── .env.example             # Template for environment-variable settings
├── README.md                # This file
└── LICENSE                  # MIT License (if applicable)
```

- **main.py**  
  • Creates a `PlayerDatabaseConnection` instance (connects via aiomysql).  
  • Imports `ban_tracker` from `ban_history.py` (manages a separate ban-history pool).  
  • Defines modals/views for the full ban/unban workflow.  
  • Registers slash commands via `tree.command`.  

- **punishments.py**  
  • A nested dictionary mapping offense names to strike levels and sanctions.  
  • Example:
    ```python
    punishments = {
        "Spamming": {
            "Strike 1": ["30-Min Timeout"],
            "Strike 2": ["1 Day Ban"],
            "Strike 3": ["1 Week Ban", "1 Month Ban"],  # multiple durations → SanctionSelect
            "Strike 4": ["Permanent Ban"],
        },
        "Prohibited Messages & Links": {
            "Strike 1": ["1 Hour Timeout"],
            "Strike 2": ["24 Hour Timeout"],
            "Strike 3": ["7 Day Ban"],
            "Strike 4": ["Permanent Ban"],
        },
        "Custom Punishment": {"Custom": "Manual Entry"},  # handled by CustomPunishmentModal
    }
    ```

- **ban_history.py**  
  • Defines a `BanTracker` class with methods:
    - `initialize()`: opens a MySQL connection pool to the ban history database.  
    - `add_ban(...)`: inserts a new row for ban or unban.  
    - `get_player_history(buid)`: returns a list of ban records for that BUID.  
    - `get_recent_bans(limit)`: returns the most recent ban submissions.  
    - `get_ban_by_number(ban_number)`: fetch a single ban’s detail.  
    - `get_player_strikes(buid)`: counts active strikes (excluding unbans where strike_removed=True).  
    - `remove_strike(ban_number)`: marks a ban’s strike as removed (used during “Remove Strike” unban).  

---

## Customizing Punishments

1. **Open `punishments.py`**.  
2. **Add/edit offenses**:  
   ```python
   punishments = {
       "Spamming": {
           "Strike 1": ["30-Min Timeout"],
           "Strike 2": ["1 Day Ban"],
           "Strike 3": ["1 Week Ban"],  # Single sanction → skip SanctionSelect
           "Strike 4": ["Permanent Ban"],
       },
       "Harassment": {
           "Strike 1": ["1 Day Ban"],
           "Strike 2": ["1 Week Ban", "2 Week Ban"],  # Multiple options → shows SanctionSelect
           "Strike 3": ["1 Month Ban"],
       },
       "Custom Punishment": {"Custom": "Manual Entry"},
   }
   ```
3. **Rename “Custom Punishment”** if you prefer a different label—just keep `"Custom"` as the nested key.  
4. **Adding Unban Behavior**  
   - You don’t need to add unban options here; the code automatically appends two unban (“Strike Remains” / “Remove Strike”) options at runtime.

---

## Ban History Module

- **Initialization**  
  In `main.py`, we call:
  ```python
  await ban_tracker.initialize()
  ```
  This opens a MySQL pool (credentials taken from your `.env`).

- **Adding a Ban/Unban**  
  - **Ban**: `await ban_tracker.add_ban(player_name, buid, offense, strike, sanction, transcript, submitted_by)`  
  - **Unban**: `await ban_tracker.add_ban(..., is_unban=True, related_ban_id=<original_ban_number>)`  
    - If “Remove Strike,” the code also calls `ban_tracker.remove_strike(original_ban_number)`.

- **Querying History**  
  - `/banhistory <BUID>` → `ban_tracker.get_player_history(buid)` → returns a list of dictionaries with keys:  
    ```json
    [
      {
        "ban_number": 42,
        "player_name": "PlayerOne",
        "buid": "123456",
        "offense": "Spamming",
        "strike": "Strike 2",
        "sanction": "1 Day Ban",
        "transcript": "[Report-0001](<url>)",
        "timestamp": "2025-06-04T14:22:00",
        "is_unban": false,
        "related_ban_id": null,
        "strike_removed": false
      },
      { … }
    ]
    ```
  - `/searchban <ban_number>` → `ban_tracker.get_ban_by_number(ban_number)` → a single ban dictionary.  
  - `/recentbans [limit]` → `ban_tracker.get_recent_bans(limit)` → list of the latest ban dicts.

---

## Development & Contribution

1. **Fork & Clone**  
   ```bash
   git clone https://github.com/<your-username>/discord-ban-management-bot.git
   cd discord-ban-management-bot
   ```

2. **Branching**  
   - Create a feature branch:
     ```bash
     git checkout -b feature/your-feature-name
     ```

3. **Dependencies**  
   - Install or update with:
     ```bash
     pip install -r requirements.txt
     ```
   - If adding a new package, update `requirements.txt`:
     ```bash
     pip freeze > requirements.txt
     ```

4. **Linting & Formatting**  
   - The project adheres to PEP 8. You can use `flake8` or `black` for consistent style:
     ```bash
     pip install black flake8
     black .
     flake8 .
     ```

5. **Testing**  
   - (Optional) If you add unit tests, you can use `pytest`.  
   - Example:
     ```
     pip install pytest
     pytest tests/
     ```

6. **Pull Request**  
   - Push your changes to your fork:
     ```bash
     git push origin feature/your-feature-name
     ```
   - Open a Pull Request against `main`. Include a clear description of your changes, any schema updates required, and how to test the new behavior.

---

## License

Distributed under the MIT License. See `LICENSE` for more information.  

---

### Contact & Acknowledgements

- Created and maintained by **Your Name / Your Team**.  
- Special thanks to contributors, testers, and community members who help improve this project.  

Enjoy streamlining your server’s ban workflow! If you run into any issues or have feature requests, feel free to open an issue or pull request on GitHub.
