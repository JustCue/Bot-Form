import aiomysql
import os
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

class BanTracker:
    def __init__(self):
        # Ban tracking database connection details (Sparked Host)
        self.host = os.getenv('BAN_DB_HOST', 'db-mfl-01.sparkedhost.us')
        self.port = int(os.getenv('BAN_DB_PORT', 3306))
        self.user = os.getenv('BAN_DB_USER', 'u176355_SL273gExDt')
        self.password = os.getenv('BAN_DB_PASSWORD', 'j+Z6UFX1L@B6gDhOru1jqeEo')
        self.database = os.getenv('BAN_DB_NAME', 's176355_ban-history')
        self.pool = None
        
        print(f"DEBUG: Ban tracker using connection to {self.host}/{self.database}")
    
    async def initialize(self):
        """Initialize the database connection pool and create tables"""
        try:
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                charset='utf8mb4',
                autocommit=True,
                minsize=1,
                maxsize=10
            )
            await self._create_tables()
            print("✅ Ban tracker database connection established")
        except Exception as e:
            print(f"❌ Ban tracker database connection failed: {e}")
            raise e
    
    async def close(self):
        """Close the database connection pool"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            print("✅ Ban tracker database connection closed")
    
    async def _create_tables(self):
        """Create the ban tracking tables if they don't exist"""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS ban_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            ban_number VARCHAR(20) UNIQUE NOT NULL,
            player_name VARCHAR(255) NOT NULL,
            buid VARCHAR(50) NOT NULL,
            offense TEXT NOT NULL,
            strike VARCHAR(50) NOT NULL,
            sanction TEXT NOT NULL,
            transcript TEXT,
            submitted_by VARCHAR(50) NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_unban BOOLEAN DEFAULT FALSE,
            related_ban_id INT,
            strike_removed BOOLEAN DEFAULT FALSE,
            INDEX idx_buid (buid),
            INDEX idx_ban_number (ban_number),
            INDEX idx_timestamp (timestamp),
            INDEX idx_is_unban (is_unban),
            INDEX idx_strike_removed (strike_removed)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(create_table_query)
                    print("✅ Ban history table created/verified")
        except Exception as e:
            print(f"❌ Failed to create ban history table: {e}")
            raise e
    
    async def _get_next_number(self, is_unban: bool = False) -> str:
        """Get the next ban or unban number"""
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    if is_unban:
                        # Get highest UNBAN number
                        query = """
                        SELECT ban_number FROM ban_history 
                        WHERE ban_number LIKE 'UNBAN-%' 
                        ORDER BY CAST(SUBSTRING(ban_number, 7) AS UNSIGNED) DESC 
                        LIMIT 1
                        """
                        await cursor.execute(query)
                        result = await cursor.fetchone()
                        
                        if result:
                            # Extract number from UNBAN-XXXX format
                            number = int(result[0].split('-')[1]) + 1
                        else:
                            number = 1
                        
                        return f"UNBAN-{number:04d}"
                    else:
                        # Get highest regular ban number (excluding UNBAN entries)
                        query = """
                        SELECT ban_number FROM ban_history 
                        WHERE ban_number NOT LIKE 'UNBAN-%' 
                        ORDER BY CAST(ban_number AS UNSIGNED) DESC 
                        LIMIT 1
                        """
                        await cursor.execute(query)
                        result = await cursor.fetchone()
                        
                        if result:
                            number = int(result[0]) + 1
                        else:
                            number = 1
                        
                        return f"{number:04d}"
        
        except Exception as e:
            print(f"❌ Error generating ban number: {e}")
            # Fallback to timestamp-based number
            import time
            timestamp = int(time.time())
            if is_unban:
                return f"UNBAN-{timestamp}"
            else:
                return str(timestamp)
    
    async def add_ban(self, player_name: str, buid: str, offense: str, strike: str, 
                     sanction: str, transcript: str, submitted_by: str, 
                     is_unban: bool = False, related_ban_id: int = None) -> str:
        """Add a ban record and return the ban number"""
        if not self.pool:
            raise Exception("Database not initialized")
        
        try:
            ban_number = await self._get_next_number(is_unban)
            
            query = """
            INSERT INTO ban_history 
            (ban_number, player_name, buid, offense, strike, sanction, transcript, 
             submitted_by, is_unban, related_ban_id, strike_removed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        query, (ban_number, player_name, buid, offense, strike, 
                               sanction, transcript, submitted_by, is_unban, 
                               related_ban_id, False)
                    )
                    
            print(f"✅ {'Unban' if is_unban else 'Ban'} {ban_number} added for {player_name}")
            return ban_number
            
        except Exception as e:
            print(f"❌ Error adding ban record: {e}")
            raise e
    
    async def remove_strike(self, ban_number: str) -> bool:
        """Remove/mark a strike as removed for a specific ban number"""
        if not self.pool:
            return False
        
        try:
            query = "UPDATE ban_history SET strike_removed = TRUE WHERE ban_number = %s"
            
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, (ban_number,))
                    success = cursor.rowcount > 0
                    
            if success:
                print(f"✅ Strike removed for ban {ban_number}")
            else:
                print(f"⚠️ No ban found with number {ban_number}")
                
            return success
            
        except Exception as e:
            print(f"❌ Error removing strike for ban {ban_number}: {e}")
            return False
    
    async def get_player_history(self, buid: str) -> List[Dict]:
        """Get all ban history for a player"""
        if not self.pool:
            return []
        
        try:
            query = """
            SELECT * FROM ban_history 
            WHERE buid = %s 
            ORDER BY timestamp DESC
            """
            
            async with self.pool.acquire() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, (buid,))
                    rows = await cursor.fetchall()
                    
                    history = []
                    for row in rows:
                        history.append({
                            'id': row['id'],
                            'ban_number': row['ban_number'],
                            'player_name': row['player_name'],
                            'buid': row['buid'],
                            'offense': row['offense'] or '',
                            'strike': row['strike'] or '',
                            'sanction': row['sanction'] or '',
                            'transcript': row['transcript'] or '',
                            'submitted_by': row['submitted_by'] or '',
                            'timestamp': row['timestamp'].isoformat() if row['timestamp'] else '',
                            'is_unban': bool(row['is_unban']),
                            'related_ban_id': row['related_ban_id'],
                            'strike_removed': bool(row['strike_removed'])
                        })
                    
                    return history
                    
        except Exception as e:
            print(f"❌ Error getting player history for {buid}: {e}")
            return []
    
    async def get_player_strikes(self, buid: str) -> int:
        """Count active strikes for a player (excluding unbans and removed strikes)"""
        if not self.pool:
            return 0
        
        try:
            query = """
            SELECT COUNT(*) as strike_count 
            FROM ban_history 
            WHERE buid = %s 
            AND is_unban = FALSE 
            AND strike_removed = FALSE 
            AND strike != 'Custom'
            AND strike != 'UNBAN'
            """
            
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, (buid,))
                    result = await cursor.fetchone()
                    return result[0] if result else 0
                    
        except Exception as e:
            print(f"❌ Error counting strikes for {buid}: {e}")
            return 0
    
    async def get_recent_bans(self, limit: int = 10) -> List[Dict]:
        """Get recent ban submissions"""
        if not self.pool:
            return []
        
        try:
            query = """
            SELECT * FROM ban_history 
            ORDER BY timestamp DESC 
            LIMIT %s
            """
            
            async with self.pool.acquire() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, (limit,))
                    rows = await cursor.fetchall()
                    
                    recent = []
                    for row in rows:
                        recent.append({
                            'id': row['id'],
                            'ban_number': row['ban_number'],
                            'player_name': row['player_name'],
                            'buid': row['buid'],
                            'offense': row['offense'] or '',
                            'strike': row['strike'] or '',
                            'sanction': row['sanction'] or '',
                            'transcript': row['transcript'] or '',
                            'submitted_by': row['submitted_by'] or '',
                            'timestamp': row['timestamp'].isoformat() if row['timestamp'] else '',
                            'is_unban': bool(row['is_unban']),
                            'related_ban_id': row['related_ban_id'],
                            'strike_removed': bool(row['strike_removed'])
                        })
                    
                    return recent
                    
        except Exception as e:
            print(f"❌ Error getting recent bans: {e}")
            return []
    
    async def get_ban_by_number(self, ban_number: str) -> Optional[Dict]:
        """Get a ban record by ban number"""
        if not self.pool:
            return None
        
        try:
            query = "SELECT * FROM ban_history WHERE ban_number = %s"
            
            async with self.pool.acquire() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, (ban_number,))
                    row = await cursor.fetchone()
                    
                    if row:
                        return {
                            'id': row['id'],
                            'ban_number': row['ban_number'],
                            'player_name': row['player_name'],
                            'buid': row['buid'],
                            'offense': row['offense'] or '',
                            'strike': row['strike'] or '',
                            'sanction': row['sanction'] or '',
                            'transcript': row['transcript'] or '',
                            'submitted_by': row['submitted_by'] or '',
                            'timestamp': row['timestamp'].isoformat() if row['timestamp'] else '',
                            'is_unban': bool(row['is_unban']),
                            'related_ban_id': row['related_ban_id'],
                            'strike_removed': bool(row['strike_removed'])
                        }
                    return None
                    
        except Exception as e:
            print(f"❌ Error getting ban by number {ban_number}: {e}")
            return None
    
    async def get_ban_statistics(self) -> Dict[str, int]:
        """Get general ban statistics"""
        if not self.pool:
            return {}
        
        try:
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    stats = {}
                    
                    # Total bans (excluding unbans)
                    await cursor.execute("SELECT COUNT(*) FROM ban_history WHERE is_unban = FALSE")
                    result = await cursor.fetchone()
                    stats['total_bans'] = result[0] if result else 0
                    
                    # Total unbans
                    await cursor.execute("SELECT COUNT(*) FROM ban_history WHERE is_unban = TRUE")
                    result = await cursor.fetchone()
                    stats['total_unbans'] = result[0] if result else 0
                    
                    # Active strikes (not removed)
                    await cursor.execute("""
                        SELECT COUNT(*) FROM ban_history 
                        WHERE is_unban = FALSE AND strike_removed = FALSE 
                        AND strike != 'Custom' AND strike != 'UNBAN'
                    """)
                    result = await cursor.fetchone()
                    stats['active_strikes'] = result[0] if result else 0
                    
                    # Unique players banned
                    await cursor.execute("SELECT COUNT(DISTINCT buid) FROM ban_history WHERE is_unban = FALSE")
                    result = await cursor.fetchone()
                    stats['unique_players_banned'] = result[0] if result else 0
                    
                    # Bans this month
                    await cursor.execute("""
                        SELECT COUNT(*) FROM ban_history 
                        WHERE is_unban = FALSE 
                        AND timestamp >= DATE_SUB(NOW(), INTERVAL 1 MONTH)
                    """)
                    result = await cursor.fetchone()
                    stats['bans_this_month'] = result[0] if result else 0
                    
                    return stats
                    
        except Exception as e:
            print(f"❌ Error getting ban statistics: {e}")
            return {}
    
    async def search_bans(self, search_term: str, limit: int = 20) -> List[Dict]:
        """Search bans by player name, BUID, or ban number"""
        if not self.pool:
            return []
        
        try:
            query = """
            SELECT * FROM ban_history 
            WHERE player_name LIKE %s 
            OR buid LIKE %s 
            OR ban_number LIKE %s 
            OR offense LIKE %s
            ORDER BY timestamp DESC 
            LIMIT %s
            """
            
            search_pattern = f"%{search_term}%"
            
            async with self.pool.acquire() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, (search_pattern, search_pattern, search_pattern, search_pattern, limit))
                    rows = await cursor.fetchall()
                    
                    results = []
                    for row in rows:
                        results.append({
                            'id': row['id'],
                            'ban_number': row['ban_number'],
                            'player_name': row['player_name'],
                            'buid': row['buid'],
                            'offense': row['offense'] or '',
                            'strike': row['strike'] or '',
                            'sanction': row['sanction'] or '',
                            'timestamp': row['timestamp'].isoformat() if row['timestamp'] else '',
                            'is_unban': bool(row['is_unban']),
                            'strike_removed': bool(row['strike_removed'])
                        })
                    
                    return results
                    
        except Exception as e:
            print(f"❌ Error searching bans for '{search_term}': {e}")
            return []
    
    async def get_players_with_multiple_bans(self, min_bans: int = 2) -> List[Dict]:
        """Get players who have multiple bans"""
        if not self.pool:
            return []
        
        try:
            query = """
            SELECT buid, player_name, COUNT(*) as ban_count,
                   SUM(CASE WHEN is_unban = FALSE AND strike_removed = FALSE THEN 1 ELSE 0 END) as active_strikes
            FROM ban_history 
            WHERE is_unban = FALSE
            GROUP BY buid, player_name
            HAVING ban_count >= %s
            ORDER BY ban_count DESC, active_strikes DESC
            """
            
            async with self.pool.acquire() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, (min_bans,))
                    rows = await cursor.fetchall()
                    
                    repeat_offenders = []
                    for row in rows:
                        repeat_offenders.append({
                            'buid': row['buid'],
                            'player_name': row['player_name'],
                            'total_bans': row['ban_count'],
                            'active_strikes': row['active_strikes']
                        })
                    
                    return repeat_offenders
                    
        except Exception as e:
            print(f"❌ Error getting repeat offenders: {e}")
            return []
    
    async def health_check(self) -> Dict[str, any]:
        """Check database connection and basic functionality"""
        health = {
            'status': 'unknown',
            'database_connected': False,
            'tables_exist': False,
            'can_read': False,
            'can_write': False,
            'error': None
        }
        
        try:
            if not self.pool:
                health['error'] = 'Database pool not initialized'
                return health
            
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
                    # Check if we can connect
                    health['database_connected'] = True
                    
                    # Check if tables exist
                    await cursor.execute("SHOW TABLES LIKE 'ban_history'")
                    result = await cursor.fetchone()
                    health['tables_exist'] = bool(result)
                    
                    if health['tables_exist']:
                        # Check if we can read
                        await cursor.execute("SELECT COUNT(*) FROM ban_history LIMIT 1")
                        await cursor.fetchone()
                        health['can_read'] = True
                        
                        # We assume write access if read works and tables exist
                        health['can_write'] = True
                        health['status'] = 'healthy'
                    else:
                        health['status'] = 'tables_missing'
                        
        except Exception as e:
            health['error'] = str(e)
            health['status'] = 'error'
        
        return health

# Create global instance
ban_tracker = BanTracker()
