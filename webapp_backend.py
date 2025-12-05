"""
TWITCH STREAMING OPPORTUNITY ANALYZER - WEB APP BACKEND
========================================================

Flask API that serves top streaming opportunities with affiliate links.
Updated every 15 minutes, serves top 100 games.

"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
from twitchAPI.twitch import Twitch
import os
from dotenv import load_dotenv
import time
import math
from datetime import datetime, timezone
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path="twitch.key.ring.env")
TWITCH_APP_ID = os.getenv("TWITCH_APP_ID")
TWITCH_APP_SECRET = os.getenv("TWITCH_APP_SECRET")

# Initialize Flask
app = Flask(__name__)
CORS(app)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ============================================================================
# ALGORITHM CONFIGURATION
# ============================================================================

IDEAL_VIEWERS_MIN = 800
IDEAL_VIEWERS_MAX = 30000
IDEAL_CHANNELS_MIN = 5
IDEAL_CHANNELS_MAX = 150
SATURATION_THRESHOLD = 250
HARD_LIMIT_CHANNELS = 400
HARD_LIMIT_VIEWERS = 80000

WEIGHT_DISCOVERABILITY = 0.45
WEIGHT_VIABILITY = 0.35
WEIGHT_ENGAGEMENT = 0.20

# ============================================================================
# CACHING
# ============================================================================

_cache = {
    "data": None,
    "timestamp": 0,
    "expires_in": 900  # 15 minutes
}

def get_cached_data():
    """Get cached analysis if still valid"""
    if _cache["data"] is None:
        return None
    
    age = time.time() - _cache["timestamp"]
    if age > _cache["expires_in"]:
        return None
    
    _cache["data"]["cache_expires_in_seconds"] = int(_cache["expires_in"] - age)
    return _cache["data"]

def set_cached_data(data):
    """Cache the analysis results"""
    _cache["data"] = data
    _cache["timestamp"] = time.time()

# ============================================================================
# AFFILIATE LINK DATABASE
# ============================================================================

def get_purchase_links(game_name):
    """Get affiliate purchase links for a game"""
    # This would ideally be a database, but for MVP we'll use a simple mapping
    # You'll need to register for Steam/Epic affiliate programs and get your IDs
    
    # Normalize game name for URL
    normalized = game_name.lower().replace(' ', '-').replace(':', '').replace("'", '')
    
    links = {
        "steam": None,
        "epic": None,
        "free": False
    }
    
    # Common free-to-play games
    free_games = [
        "league of legends", "valorant", "fortnite", "apex legends",
        "dota 2", "counter-strike 2", "team fortress 2", "warframe",
        "path of exile", "lost ark", "marvel rivals"
    ]
    
    if game_name.lower() in free_games:
        links["free"] = True
        return links
    
    # For now, return generic search links
    # TODO: Replace with actual affiliate links from your accounts
    steam_search = f"https://store.steampowered.com/search/?term={game_name.replace(' ', '+')}"
    epic_search = f"https://store.epicgames.com/en-US/browse?q={game_name.replace(' ', '%20')}"
    
    links["steam"] = steam_search
    links["epic"] = epic_search
    
    return links

# ============================================================================
# SCORING ALGORITHM (Same as desktop version)
# ============================================================================

def calculate_discoverability_score(viewers, channels):
    """Measures how likely a new streamer can get discovered"""
    if channels == 0 or viewers == 0:
        return 0.0
    
    avg_viewers_per_channel = viewers / channels
    
    # Top-heavy detection
    if channels < 20 and avg_viewers_per_channel > 1000:
        top_heavy_penalty = min(channels / 20, 0.4)
        return top_heavy_penalty * 0.3
    
    # Hard limits
    if channels > HARD_LIMIT_CHANNELS:
        excess = channels - HARD_LIMIT_CHANNELS
        penalty = max(0.15 - (excess / 1000), 0.01)
        return penalty
    
    if viewers > HARD_LIMIT_VIEWERS:
        return 0.05
    
    # Channel competition score
    competition_score = 0
    
    if IDEAL_CHANNELS_MIN <= channels <= IDEAL_CHANNELS_MAX:
        range_position = (channels - IDEAL_CHANNELS_MIN) / (IDEAL_CHANNELS_MAX - IDEAL_CHANNELS_MIN)
        competition_score = 1.0 - (range_position * 0.3)
    elif channels < IDEAL_CHANNELS_MIN:
        competition_score = (channels / IDEAL_CHANNELS_MIN) * 0.6
    else:
        if channels <= SATURATION_THRESHOLD:
            excess = (channels - IDEAL_CHANNELS_MAX) / (SATURATION_THRESHOLD - IDEAL_CHANNELS_MAX)
            competition_score = 0.7 - (excess * 0.4)
        else:
            excess = (channels - SATURATION_THRESHOLD) / (HARD_LIMIT_CHANNELS - SATURATION_THRESHOLD)
            competition_score = 0.3 - (excess * 0.25)
    
    # Viewer-to-channel ratio
    ratio_score = 0
    if 50 <= avg_viewers_per_channel <= 500:
        ratio_score = 1.0
    elif avg_viewers_per_channel < 50:
        ratio_score = avg_viewers_per_channel / 50
    else:
        ratio_score = max(0.6 - math.log10(avg_viewers_per_channel / 500), 0.3)
    
    discoverability = (competition_score * 0.60) + (ratio_score * 0.40)
    return max(min(discoverability, 1.0), 0.0)

def calculate_viability_score(viewers, channels):
    """Measures if there's a viable audience for the game"""
    if channels == 0 or viewers == 0:
        return 0.0
    
    # Viewer count score
    viewer_score = 0
    
    if IDEAL_VIEWERS_MIN <= viewers <= IDEAL_VIEWERS_MAX:
        midpoint = (IDEAL_VIEWERS_MIN + IDEAL_VIEWERS_MAX) / 2
        distance = abs(viewers - midpoint) / (IDEAL_VIEWERS_MAX - IDEAL_VIEWERS_MIN)
        viewer_score = 1.0 - (distance * 0.3)
    elif viewers < IDEAL_VIEWERS_MIN:
        viewer_score = (viewers / IDEAL_VIEWERS_MIN) * 0.5
    else:
        if viewers <= HARD_LIMIT_VIEWERS:
            excess = (viewers - IDEAL_VIEWERS_MAX) / (HARD_LIMIT_VIEWERS - IDEAL_VIEWERS_MAX)
            viewer_score = 0.7 - (excess * 0.4)
        else:
            viewer_score = 0.1
    
    # Market saturation
    saturation_score = 0
    
    if channels <= IDEAL_CHANNELS_MAX:
        saturation_score = 1.0
    elif channels <= SATURATION_THRESHOLD:
        excess = (channels - IDEAL_CHANNELS_MAX) / (SATURATION_THRESHOLD - IDEAL_CHANNELS_MAX)
        saturation_score = 1.0 - (excess * 0.6)
    elif channels <= HARD_LIMIT_CHANNELS:
        excess = (channels - SATURATION_THRESHOLD) / (HARD_LIMIT_CHANNELS - SATURATION_THRESHOLD)
        saturation_score = 0.4 - (excess * 0.35)
    else:
        saturation_score = 0.01
    
    # Audience stability
    stability_score = min(channels / 10, 1.0)
    
    viability = (viewer_score * 0.50) + (saturation_score * 0.30) + (stability_score * 0.20)
    return max(min(viability, 1.0), 0.0)

def calculate_engagement_score(viewers, channels):
    """Measures audience engagement"""
    if channels == 0 or viewers == 0:
        return 0.0
    
    avg_viewers_per_channel = viewers / channels
    engagement = min(math.log10(avg_viewers_per_channel + 1) / math.log10(500), 1.0)
    return engagement

def calculate_all_scores(viewers, channels):
    """Calculate all scores and return tuple"""
    discoverability = calculate_discoverability_score(viewers, channels)
    viability = calculate_viability_score(viewers, channels)
    engagement = calculate_engagement_score(viewers, channels)
    
    overall = (
        discoverability * WEIGHT_DISCOVERABILITY +
        viability * WEIGHT_VIABILITY +
        engagement * WEIGHT_ENGAGEMENT
    )
    
    return discoverability, viability, engagement, overall

def get_recommendation(overall_score, channels):
    """Generate recommendation text based on score"""
    if overall_score >= 0.80:
        return "🔥 EXCELLENT OPPORTUNITY"
    elif overall_score >= 0.65:
        return "✅ GOOD OPPORTUNITY"
    elif overall_score >= 0.50:
        return "⚠️ MODERATE OPPORTUNITY"
    elif overall_score >= 0.35:
        return "🔻 CHALLENGING"
    else:
        return "❌ HIGHLY SATURATED"

def get_trend_indicator(overall_score):
    """Get trend arrow based on score"""
    if overall_score >= 0.80:
        return "⬆️"
    elif overall_score >= 0.65:
        return "↗️"
    elif overall_score >= 0.50:
        return "➡️"
    elif overall_score >= 0.35:
        return "↘️"
    else:
        return "⬇️"

# ============================================================================
# ASYNC ANALYSIS FUNCTION
# ============================================================================

async def perform_analysis(limit=100):
    """Perform the Twitch analysis asynchronously"""
    
    # Initialize Twitch API
    twitch = await asyncio.wait_for(
        Twitch(TWITCH_APP_ID, TWITCH_APP_SECRET),
        timeout=10.0
    )
    
    # Don't Shoot We Are Friendly - warmup call
    logger.info("DSWAF: Warming up API connection...")
    warmup_streams = []
    async for stream in twitch.get_streams(first=1):
        warmup_streams.append(stream)
        break
    await asyncio.sleep(2.0)
    logger.info("DSWAF: Connection established")
    
    # TEST: Load 200 games from JSON file
    logger.info("TEST: Loading top 200 games from top_games.json...")
    try:
        import json
        with open('top_games.json', 'r', encoding='utf-8') as f:
            game_data = json.load(f)
            game_names = [g['name'] for g in game_data['games'][:200]]
        logger.info(f"TEST: Loaded {len(game_names)} games from file")
    except FileNotFoundError:
        logger.warning("top_games.json not found, falling back to API")
        game_names = []
        async for game in twitch.get_top_games(first=100):
            game_names.append(game.name)
        logger.info(f"Fetched {len(game_names)} games from API as fallback")
    
    # Validate games in chunks
    logger.info("TEST: Validating games with Twitch API...")
    games = []
    chunk_size = 100
    
    for i in range(0, len(game_names), chunk_size):
        chunk = game_names[i:i+chunk_size]
        chunk_num = (i // chunk_size) + 1
        total_chunks = (len(game_names) + chunk_size - 1) // chunk_size
        
        logger.info(f"TEST: Validating chunk {chunk_num}/{total_chunks} ({len(chunk)} games)")
        
        try:
            async for game in twitch.get_games(names=chunk):
                games.append(game)
            
            # Delay between chunks
            if i + chunk_size < len(game_names):
                await asyncio.sleep(2.0)
                
        except Exception as e:
            logger.warning(f"Error validating chunk {chunk_num}: {e}")
            continue
    
    logger.info(f"TEST: Validated {len(games)} active games from {len(game_names)} total")
    
    # Analyze ALL validated games
    games_to_analyze = games
    logger.info(f"TEST: Will analyze {len(games_to_analyze)} games (filtering for <15k viewers)")
    
    # Process games in batches - smaller batches with delays
    opportunities = []
    batch_size = 10  # Smaller batches to avoid rate limits
    
    async def process_game(game):
        """Process a single game and return opportunity data"""
        try:
            # Get streams for this game
            streams = []
            async for stream in twitch.get_streams(game_id=game.id, first=100):
                streams.append(stream)
            
            if not streams:
                return None
            
            # Calculate metrics
            total_viewers = sum(s.viewer_count for s in streams)
            channel_count = len(streams)
            
            if channel_count == 0 or total_viewers == 0:
                return None
            
            # FILTER: Skip games with more than 15k viewers (too big for small streamers)
            if total_viewers > 15000:
                logger.info(f"Skipping {game.name} - too many viewers ({total_viewers})")
                return None
            
            # FILTER: Skip games where one streamer dominates (70%+ of viewership)
            if streams:
                top_streamer_viewers = streams[0].viewer_count  # Streams are sorted by viewers
                dominance_ratio = top_streamer_viewers / total_viewers if total_viewers > 0 else 0
                
                if dominance_ratio > 0.70:  # If top streamer has 70%+ of viewers
                    logger.info(f"Skipping {game.name} - dominated by one streamer ({top_streamer_viewers}/{total_viewers} = {dominance_ratio:.1%})")
                    return None
            
            # Calculate scores
            disc, viab, eng, overall = calculate_all_scores(total_viewers, channel_count)
            
            # Get purchase links
            purchase_links = get_purchase_links(game.name)
            
            # Get box art URL
            box_art_url = game.box_art_url.replace('{width}', '285').replace('{height}', '380') if game.box_art_url else None
            
            return {
                "rank": 0,
                "name": game.name,
                "viewers": total_viewers,
                "channels": channel_count,
                "avg_viewers_per_channel": round(total_viewers / channel_count, 1),
                "discoverability_score": round(disc, 3),
                "viability_score": round(viab, 3),
                "engagement_score": round(eng, 3),
                "overall_score": round(overall, 3),
                "recommendation": get_recommendation(overall, channel_count),
                "trend": get_trend_indicator(overall),
                "purchase_links": purchase_links,
                "box_art_url": box_art_url
            }
        except Exception as e:
            logger.error(f"Error processing game {game.name}: {e}")
            return None
    
    # Process in batches of 5
    for i in range(0, len(games_to_analyze), batch_size):
        batch = games_to_analyze[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(games_to_analyze) + batch_size - 1) // batch_size
        
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} games)")
        
        # Process batch concurrently
        results = await asyncio.gather(*[process_game(game) for game in batch])
        
        # Add successful results
        for result in results:
            if result:
                opportunities.append(result)
        
        # Small delay between batches
        # TEST: Longer delay between batches to avoid rate limits
        if i + batch_size < len(games_to_analyze):
            await asyncio.sleep(1.5)  # Increased from 0.5 to avoid rate limits
    
    logger.info(f"Analysis complete. Processed {len(opportunities)} out of {len(games_to_analyze)} games")
    
    # Close Twitch connection
    await twitch.close()
    
    # Sort by overall score
    opportunities.sort(key=lambda x: x["overall_score"], reverse=True)
    
    # Assign ranks
    for idx, opp in enumerate(opportunities):
        opp["rank"] = idx + 1
    
    # Create response
    response = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "total_games_analyzed": len(opportunities),
        "top_opportunities": opportunities,  # Return ALL opportunities
        "cache_expires_in_seconds": _cache["expires_in"],
        "next_update": datetime.fromtimestamp(time.time() + _cache["expires_in"]).isoformat() + "Z"
    }
    
    return response

# ============================================================================
# API ROUTES
# ============================================================================

@app.route("/")
def root():
    """Health check endpoint"""
    return jsonify({
        "status": "online",
        "service": "Twitch Streaming Opportunity Analyzer",
        "version": "2.0.0 - Web Edition",
        "endpoints": {
            "analysis": "/api/v1/analyze",
            "health": "/api/v1/health"
        }
    })

@app.route("/api/v1/health")
def health():
    """Health check for monitoring"""
    cache_age = time.time() - _cache["timestamp"] if _cache["data"] else None
    return jsonify({
        "status": "healthy",
        "cache_active": _cache["data"] is not None,
        "cache_age_seconds": cache_age,
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    })

@app.route("/api/v1/analyze")
def analyze_opportunities():
    """
    Analyze Twitch streaming opportunities
    
    Query params:
        limit: Number of top opportunities to return (default 100, max 100)
        force_refresh: Force fresh data instead of using cache (default false)
    
    Returns:
        JSON with top streaming opportunities
    """
    
    # Get query parameters
    limit = request.args.get('limit', default=100, type=int)
    force_refresh = request.args.get('force_refresh', default='false').lower() == 'true'
    
    # Validate limit
    limit = min(max(limit, 1), 100)
    
    # Check cache first
    if not force_refresh:
        cached = get_cached_data()
        if cached:
            logger.info("Returning cached data")
            cached["top_opportunities"] = cached["top_opportunities"][:limit]
            return jsonify(cached)
    
    # Validate credentials
    if not TWITCH_APP_ID or not TWITCH_APP_SECRET:
        return jsonify({
            "error": "Twitch API credentials not configured on server"
        }), 500
    
    logger.info("Fetching fresh data from Twitch API...")
    
    try:
        # Run async analysis
        response = asyncio.run(perform_analysis(limit))
        
        # Cache the results
        set_cached_data(response)
        
        logger.info(f"Analysis complete. Returning top {limit} opportunities.")
        
        return jsonify(response)
        
    except asyncio.TimeoutError:
        return jsonify({
            "error": "Twitch API connection timeout - please try again"
        }), 504
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            "error": f"Analysis failed: {str(e)}"
        }), 500

@app.route("/api/v1/clear-cache", methods=["POST"])
def clear_cache():
    """Clear the analysis cache (forces fresh data on next request)"""
    _cache["data"] = None
    _cache["timestamp"] = 0
    return jsonify({"status": "cache cleared"})

# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    # Check for credentials on startup
    if not TWITCH_APP_ID or not TWITCH_APP_SECRET:
        print("WARNING: Twitch API credentials not found!")
        print("   Set TWITCH_APP_ID and TWITCH_APP_SECRET environment variables")
    else:
        print("Twitch API credentials loaded")
    
    print("\nStarting Twitch Opportunity Analyzer API (Web Edition)...")
    print("API will be available at: http://localhost:5000")
    print("Ready for Next.js frontend")
    print("\n")
    
    app.run(host="0.0.0.0", port=5000, debug=False)
