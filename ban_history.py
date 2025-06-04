import json
import os
from datetime import datetime
from typing import List, Dict, Optional

class BanTracker:
    def __init__(self, file_path: str = "ban_history.json"):
        self.file_path = file_path
        self.data = self._load_data()
    
    def _load_data(self) -> Dict:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {"bans": [], "next_id": 1}
        return {"bans": [], "next_id": 1}
    
    def _save_data(self):
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            print(f"Error saving ban data: {e}")
    
    def add_ban(self, player_name: str, buid: str, offense: str, strike: str, 
                sanction: str, transcript: str, submitted_by: str, 
                is_unban: bool = False, related_ban_id: int = None) -> int:
        ban_id = self.data["next_id"]
        
        ban_record = {
            "id": ban_id,
            "player_name": player_name,
            "buid": buid,
            "offense": offense,
            "strike": strike,
            "sanction": sanction,
            "transcript": transcript,
            "submitted_by": submitted_by,
            "timestamp": datetime.utcnow().isoformat(),
            "is_unban": is_unban,
            "related_ban_id": related_ban_id,
            "strike_removed": False  # Track if strike was removed
        }
        
        self.data["bans"].append(ban_record)
        self.data["next_id"] += 1
        self._save_data()
        
        return ban_id
    
    def remove_strike(self, ban_id: int) -> bool:
        """Remove/mark a strike as removed for a specific ban ID"""
        for ban in self.data["bans"]:
            if ban["id"] == ban_id:
                ban["strike_removed"] = True
                self._save_data()
                return True
        return False
    
    def get_player_history(self, buid: str) -> List[Dict]:
        return [ban for ban in self.data["bans"] if ban["buid"] == buid]
    
    def get_player_strikes(self, buid: str) -> int:
        """Count active strikes for a player (excluding unbans and removed strikes)"""
        strikes = 0
        for ban in self.data["bans"]:
            if (ban["buid"] == buid and 
                not ban.get("is_unban", False) and 
                not ban.get("strike_removed", False) and
                ban["strike"] != "Custom"):  # Don't count custom punishments as strikes
                strikes += 1
        return strikes
    
    def get_recent_bans(self, limit: int = 10) -> List[Dict]:
        return sorted(self.data["bans"], key=lambda x: x["timestamp"], reverse=True)[:limit]
    
    def get_ban_by_id(self, ban_id: int) -> Optional[Dict]:
        for ban in self.data["bans"]:
            if ban["id"] == ban_id:
                return ban
        return None

# Create global instance
ban_tracker = BanTracker()
