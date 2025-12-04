#!/usr/bin/env python3
"""
Twitch Top Games Fetcher
Fetches the top 300+ games from Twitch and saves them to a JSON file
Run this separately to generate a master game list for your web app
"""

import asyncio
import json
import os
from datetime import datetime
from twitchAPI.twitch import Twitch
from dotenv import load_dotenv

# Load environment variables
load_dotenv('twitch.key.ring.env')

TWITCH_APP_ID = os.getenv("TWITCH_APP_ID")
TWITCH_APP_SECRET = os.getenv("TWITCH_APP_SECRET")

OUTPUT_FILE = "top_games.json"


async def fetch_top_games(target_count=300):
    """
    Fetch top games from Twitch using pagination
    
    Args:
        target_count: How many games to fetch (default 300)
    
    Returns:
        List of game dictionaries with id, name, and metadata
    """
    
    print(f"[*] Fetching top {target_count} games from Twitch...")
    print(f"[*] Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Initialize Twitch API
    print("[*] Authenticating with Twitch...")
    twitch = await Twitch(TWITCH_APP_ID, TWITCH_APP_SECRET)
    print("[+] Authentication successful!")
    print()
    
    games = []
    cursor = None
    batch_num = 0
    
    # Fetch games in batches of 100 (Twitch API limit)
    while len(games) < target_count:
        batch_num += 1
        batch_size = min(100, target_count - len(games))
        
        print(f"[*] Fetching batch {batch_num} ({batch_size} games)...")
        
        try:
            # Fetch games with pagination
            batch_games = []
            if cursor:
                async for game in twitch.get_top_games(first=batch_size, after=cursor):
                    batch_games.append({
                        'id': game.id,
                        'name': game.name
                    })
            else:
                async for game in twitch.get_top_games(first=batch_size):
                    batch_games.append({
                        'id': game.id,
                        'name': game.name
                    })
            
            if not batch_games:
                print("    [!] No more games available from Twitch")
                break
            
            games.extend(batch_games)
            print(f"    [+] Fetched {len(batch_games)} games (total: {len(games)})")
            
            # Get cursor for next page (from last game's pagination)
            # Note: TwitchAPI library handles this automatically in the iterator
            # If we got fewer games than requested, we've reached the end
            if len(batch_games) < batch_size:
                print("    [!] Reached end of available games")
                break
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"    [-] Error fetching batch: {e}")
            break
    
    await twitch.close()
    
    print()
    print(f"[+] Successfully fetched {len(games)} games!")
    return games


async def main():
    """Main function to fetch and save games"""
    
    # Check credentials
    if not TWITCH_APP_ID or not TWITCH_APP_SECRET:
        print("[-] ERROR: Missing Twitch credentials!")
        print("    Please set TWITCH_APP_ID and TWITCH_APP_SECRET in twitch.key.ring.env")
        return
    
    try:
        # Fetch games
        games = await fetch_top_games(target_count=300)
        
        if not games:
            print("[-] No games were fetched!")
            return
        
        # Prepare output data
        output_data = {
            'fetched_at': datetime.now().isoformat(),
            'total_games': len(games),
            'games': games
        }
        
        # Save to JSON file
        print(f"[*] Saving to {OUTPUT_FILE}...")
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"[+] Saved {len(games)} games to {OUTPUT_FILE}")
        print()
        print("[*] Sample games:")
        for i, game in enumerate(games[:10], 1):
            print(f"    {i}. {game['name']}")
        print(f"    ... and {len(games) - 10} more")
        print()
        print("[+] You can now use this game list in your web app!")
        
    except Exception as e:
        print(f"[-] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
