"""
STREAMSCOUT - TWITCH STREAMING OPPORTUNITY ANALYZER
====================================================
v3.0 - Background Worker Architecture

Key change: Data fetching happens on a schedule in the background.
User requests ALWAYS hit pre-computed cache = instant responses.
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
import threading
import fcntl
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

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

# Refresh interval in minutes
REFRESH_INTERVAL_MINUTES = 10

# ============================================================================
# CACHE - File-based storage for multi-process support
# ============================================================================

CACHE_FILE = '/tmp/streamscout_cache.json'
STATUS_FILE = '/tmp/streamscout_status.json'

_cache_lock = threading.Lock()

def get_cached_data():
    """Get cached analysis from file (shared across all processes)"""
    try:
        if not os.path.exists(CACHE_FILE):
            return None
        
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        if cache_data.get("data") is None:
            return None
        
        # Calculate time until next scheduled refresh
        age = time.time() - cache_data.get("timestamp", 0)
        next_refresh_in = max(0, (REFRESH_INTERVAL_MINUTES * 60) - age)
        
        # Get refresh status
        status = get_refresh_status()
        
        # Return a copy with timing info
        result = cache_data["data"].copy()
        result["cache_age_seconds"] = int(age)
        result["next_refresh_in_seconds"] = int(next_refresh_in)
        result["is_refreshing"] = status.get("is_refreshing", False)
        return result
    except Exception as e:
        logger.error(f"Error reading cache: {e}")
        return None

def set_cached_data(data, duration):
    """Store analysis results in cache file"""
    try:
        with _cache_lock:
            # Read existing status
            status = get_refresh_status()
            refresh_count = status.get("refresh_count", 0) + 1
            
            cache_data = {
                "data": data,
                "timestamp": time.time(),
                "last_refresh_duration": duration,
                "refresh_count": refresh_count
            }
            
            with open(CACHE_FILE, 'w') as f:
                json.dump(cache_data, f)
            
            # Update status
            set_refresh_status(False)
            
            logger.info(f"Cache written to {CACHE_FILE}")
    except Exception as e:
        logger.error(f"Error writing cache: {e}")

def get_refresh_status():
    """Get refresh status from file"""
    try:
        if not os.path.exists(STATUS_FILE):
            return {"is_refreshing": False, "last_error": None, "refresh_count": 0}
        
        with open(STATUS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"is_refreshing": False, "last_error": None, "refresh_count": 0}

def set_refresh_status(is_refreshing, error=None):
    """Update refresh status in file"""
    try:
        status = get_refresh_status()
        status["is_refreshing"] = is_refreshing
        if error:
            status["last_error"] = str(error)
        elif not is_refreshing:
            status["last_error"] = None
        
        with open(STATUS_FILE, 'w') as f:
            json.dump(status, f)
    except Exception as e:
        logger.error(f"Error writing status: {e}")

# ============================================================================
# AFFILIATE LINK DATABASE
# ============================================================================

def get_purchase_links(game_name):
    """Get affiliate purchase links for a game"""
    normalized = game_name.lower().replace(' ', '-').replace(':', '').replace("'", '')
    
    links = {
        "steam": None,
        "epic": None,
        "free": False
    }
    
    free_games = [
        "league of legends", "valorant", "fortnite", "apex legends",
        "dota 2", "counter-strike 2", "team fortress 2", "warframe",
        "path of exile", "lost ark", "marvel rivals"
    ]
    
    if game_name.lower() in free_games:
        links["free"] = True
        return links
    
    steam_search = f"https://store.steampowered.com/search/?term={game_name.replace(' ', '+')}"
    epic_search = f"https://store.epicgames.com/en-US/browse?q={game_name.replace(' ', '%20')}"
    
    links["steam"] = steam_search
    links["epic"] = epic_search
    
    return links

# ============================================================================
# SCORING ALGORITHM
# ============================================================================

def calculate_discoverability_score(viewers, channels):
    """Measures how likely a new streamer can get discovered"""
    if channels == 0 or viewers == 0:
        return 0.0
    
    avg_viewers_per_channel = viewers / channels
    
    if channels < 20 and avg_viewers_per_channel > 1000:
        top_heavy_penalty = min(channels / 20, 0.4)
        return top_heavy_penalty * 0.3
    
    if channels > HARD_LIMIT_CHANNELS:
        excess = channels - HARD_LIMIT_CHANNELS
        penalty = max(0.15 - (excess / 1000), 0.01)
        return penalty
    
    if viewers > HARD_LIMIT_VIEWERS:
        return 0.05
    
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

async def perform_analysis():
    """
    Perform the Twitch analysis asynchronously
    Called by background worker, not by user requests
    """
    
    logger.info("=" * 60)
    logger.info("BACKGROUND REFRESH: Starting data fetch...")
    logger.info("=" * 60)
    
    start_time = time.time()
    
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
    
    # Load 150 games from JSON file
    logger.info("Loading top 150 games from top_games.json...")
    try:
        with open('top_games.json', 'r', encoding='utf-8') as f:
            game_data = json.load(f)
            game_names = [g['name'] for g in game_data['games'][:500]]
        logger.info(f"Loaded {len(game_names)} games from file")
    except FileNotFoundError:
        logger.warning("top_games.json not found, falling back to API")
        game_names = []
        async for game in twitch.get_top_games(first=100):
            game_names.append(game.name)
        logger.info(f"Fetched {len(game_names)} games from API as fallback")
    
    # Validate games in chunks
    logger.info("Validating games with Twitch API...")
    games = []
    chunk_size = 100
    
    for i in range(0, len(game_names), chunk_size):
        chunk = game_names[i:i+chunk_size]
        chunk_num = (i // chunk_size) + 1
        total_chunks = (len(game_names) + chunk_size - 1) // chunk_size
        
        logger.info(f"Validating chunk {chunk_num}/{total_chunks} ({len(chunk)} games)")
        
        try:
            async for game in twitch.get_games(names=chunk):
                games.append(game)
            
            if i + chunk_size < len(game_names):
                await asyncio.sleep(1.0)
                
        except Exception as e:
            logger.warning(f"Error validating chunk {chunk_num}: {e}")
            continue
    
    logger.info(f"Validated {len(games)} active games from {len(game_names)} total")
    
    # PARALLEL FETCH: Fetch streams for games in batches
    logger.info(f"Fetching stream data for all {len(games)} games in parallel batches...")
    
    streams_by_game = {}
    batch_size = 10
    
    for i in range(0, len(games), batch_size):
        batch = games[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(games) + batch_size - 1) // batch_size
        
        logger.info(f"Fetching streams: batch {batch_num}/{total_batches} ({len(batch)} games)...")
        
        async def fetch_game_streams(game):
            try:
                streams = []
                async for stream in twitch.get_streams(game_id=game.id, first=100):
                    streams.append(stream)
                
                if streams:
                    return (game.id, {'game': game, 'streams': streams})
                return None
            except Exception as e:
                logger.warning(f"Error fetching streams for {game.name}: {e}")
                return None
        
        results = await asyncio.gather(*[fetch_game_streams(g) for g in batch], return_exceptions=True)
        
        for result in results:
            if result and not isinstance(result, Exception):
                game_id, data = result
                streams_by_game[game_id] = data
    
    logger.info(f"Fetched stream data for {len(streams_by_game)} games")
    
    await twitch.close()
    logger.info("Closed Twitch connection - processing locally now")
    
    # Process each game locally
    opportunities = []
    processed_count = 0
    skipped_count = 0
    
    for game_id, data in streams_by_game.items():
        game = data['game']
        streams = data['streams']
        
        try:
            if not streams:
                continue
            
            streams.sort(key=lambda x: x.viewer_count, reverse=True)
            
            total_viewers = sum(s.viewer_count for s in streams)
            channel_count = len(streams)
            
            if channel_count == 0 or total_viewers == 0:
                continue
            
            # FILTER: Skip games with >15k viewers
            if total_viewers > 15000:
                skipped_count += 1
                continue
            
            # FILTER: Skip games dominated by one streamer (70%+)
            top_streamer_viewers = streams[0].viewer_count
            dominance_ratio = top_streamer_viewers / total_viewers
            
            if dominance_ratio > 0.70:
                skipped_count += 1
                continue
            
            avg_viewers_per_channel = total_viewers / channel_count
            
            # Calculate scores
            channel_penalty = min(channel_count / 500, 1.0)
            disc = max(0.3, 1.0 - channel_penalty)
            
            if avg_viewers_per_channel < 10:
                viab = 0.3
            elif 10 <= avg_viewers_per_channel < 50:
                viab = 0.5 + ((avg_viewers_per_channel - 10) / 40) * 0.3
            elif 50 <= avg_viewers_per_channel <= 500:
                viab = 0.8 + ((500 - avg_viewers_per_channel) / 450) * 0.2
            else:
                excess = avg_viewers_per_channel - 500
                penalty = max(0.15 - (excess / 1000), 0.01)
                viab = max(0.3, 0.8 - penalty)
            
            if avg_viewers_per_channel >= 100:
                eng = 1.0
            elif avg_viewers_per_channel >= 50:
                eng = 0.6 + ((avg_viewers_per_channel - 50) / 50) * 0.4
            elif avg_viewers_per_channel >= 20:
                eng = 0.4 + ((avg_viewers_per_channel - 20) / 30) * 0.2
            else:
                eng = max(0.2, avg_viewers_per_channel / 50)
            
            overall = (disc * 0.45) + (viab * 0.35) + (eng * 0.20)
            
            purchase_links = get_purchase_links(game.name)
            box_art_url = game.box_art_url.format(width=285, height=380) if game.box_art_url else ""
            
            opportunities.append({
                "game_name": game.name,
                "game_id": game.id,
                "total_viewers": total_viewers,
                "channels": channel_count,
                "avg_viewers_per_channel": round(avg_viewers_per_channel, 1),
                "discoverability_score": round(disc, 3),
                "viability_score": round(viab, 3),
                "engagement_score": round(eng, 3),
                "overall_score": round(overall, 3),
                "recommendation": get_recommendation(overall, channel_count),
                "trend": get_trend_indicator(overall),
                "purchase_links": purchase_links,
                "box_art_url": box_art_url
            })
            
            processed_count += 1
            
        except Exception as e:
            logger.error(f"Error processing game {game.name}: {e}")
            continue
    
    logger.info(f"Local processing complete! Processed {processed_count} games, skipped {skipped_count}")
    
    # Sort by overall score
    opportunities.sort(key=lambda x: x["overall_score"], reverse=True)
    
    # Assign ranks
    for idx, opp in enumerate(opportunities):
        opp["rank"] = idx + 1
    
    duration = time.time() - start_time
    
    # Create response
    response = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "total_games_analyzed": len(opportunities),
        "top_opportunities": opportunities,
        "refresh_interval_minutes": REFRESH_INTERVAL_MINUTES,
        "fetch_duration_seconds": round(duration, 2)
    }
    
    logger.info("=" * 60)
    logger.info(f"BACKGROUND REFRESH: Complete in {duration:.1f}s")
    logger.info(f"Total opportunities: {len(opportunities)}")
    logger.info("=" * 60)
    
    return response, duration

# ============================================================================
# BACKGROUND WORKER
# ============================================================================

# File lock to prevent duplicate schedulers across processes
_lock_file = None

def acquire_scheduler_lock():
    """Try to acquire exclusive lock for scheduler. Returns True if acquired."""
    global _lock_file
    try:
        _lock_file = open('/tmp/streamscout_scheduler.lock', 'w')
        fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        return True
    except (IOError, OSError):
        return False

def background_refresh():
    """
    Called by scheduler every REFRESH_INTERVAL_MINUTES.
    Fetches fresh data and updates the cache.
    """
    status = get_refresh_status()
    if status.get("is_refreshing", False):
        logger.info("Refresh already in progress, skipping...")
        return
    
    set_refresh_status(True)
    
    try:
        # Run the async analysis
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            response, duration = loop.run_until_complete(perform_analysis())
            set_cached_data(response, duration)
            logger.info(f"Cache updated successfully")
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Background refresh failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        set_refresh_status(False, error=e)
        return
    
    set_refresh_status(False)

# Initialize scheduler
scheduler = BackgroundScheduler()

def start_background_worker():
    """Start the background refresh scheduler"""
    
    # Try to acquire lock - only one process should run the scheduler
    if not acquire_scheduler_lock():
        logger.info("Another process owns the scheduler lock - skipping scheduler start")
        return
    
    logger.info(f"Acquired scheduler lock (PID: {os.getpid()})")
    logger.info(f"Starting background worker (refresh every {REFRESH_INTERVAL_MINUTES} minutes)")
    
    # Schedule recurring refresh
    scheduler.add_job(
        background_refresh,
        trigger=IntervalTrigger(minutes=REFRESH_INTERVAL_MINUTES),
        id='twitch_refresh',
        name='Refresh Twitch data',
        replace_existing=True
    )
    
    scheduler.start()
    
    # Do initial fetch immediately (in background thread)
    logger.info("Triggering initial data fetch...")
    threading.Thread(target=background_refresh, daemon=True).start()

# ============================================================================
# API ROUTES
# ============================================================================

@app.route("/")
def root():
    """Health check endpoint"""
    return jsonify({
        "status": "online",
        "service": "StreamScout - Twitch Streaming Opportunity Analyzer",
        "version": "3.0.0 - Background Worker Architecture",
        "architecture": "Pre-computed cache, instant responses",
        "refresh_interval_minutes": REFRESH_INTERVAL_MINUTES,
        "endpoints": {
            "analysis": "/api/v1/analyze",
            "health": "/api/v1/health",
            "status": "/api/v1/status"
        }
    })

@app.route("/api/v1/health")
def health():
    """Health check for monitoring"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            cache_age = time.time() - cache_data.get("timestamp", 0) if cache_data.get("data") else None
            has_data = cache_data.get("data") is not None
            refresh_count = cache_data.get("refresh_count", 0)
            last_duration = cache_data.get("last_refresh_duration", 0)
        else:
            cache_age = None
            has_data = False
            refresh_count = 0
            last_duration = 0
        
        status = get_refresh_status()
        
        return jsonify({
            "status": "healthy",
            "cache_active": has_data,
            "cache_age_seconds": int(cache_age) if cache_age else None,
            "is_refreshing": status.get("is_refreshing", False),
            "refresh_count": refresh_count,
            "last_refresh_duration": last_duration,
            "last_error": status.get("last_error"),
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/status")
def status():
    """Detailed status for debugging"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            cache_age = time.time() - cache_data.get("timestamp", 0) if cache_data.get("data") else None
            has_data = cache_data.get("data") is not None
            next_refresh = max(0, (REFRESH_INTERVAL_MINUTES * 60) - cache_age) if cache_age else 0
            refresh_count = cache_data.get("refresh_count", 0)
            last_duration = cache_data.get("last_refresh_duration", 0)
        else:
            cache_age = None
            has_data = False
            next_refresh = 0
            refresh_count = 0
            last_duration = 0
        
        refresh_status = get_refresh_status()
        
        return jsonify({
            "service": "StreamScout",
            "version": "3.0.0",
            "architecture": "background_worker",
            "cache": {
                "has_data": has_data,
                "age_seconds": int(cache_age) if cache_age else None,
                "next_refresh_seconds": int(next_refresh),
                "total_refreshes": refresh_count,
                "last_duration_seconds": last_duration
            },
            "worker": {
                "is_refreshing": refresh_status.get("is_refreshing", False),
                "interval_minutes": REFRESH_INTERVAL_MINUTES,
                "last_error": refresh_status.get("last_error")
            },
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/v1/analyze")
def analyze_opportunities():
    """
    Get streaming opportunities - INSTANT from cache
    
    Query params:
        limit: Number of top opportunities to return (default 100, max 200)
    
    Returns:
        JSON with top streaming opportunities (from pre-computed cache)
    """
    
    limit = request.args.get('limit', default=100, type=int)
    limit = min(max(limit, 1), 200)
    
    # Get from cache (instant!)
    cached = get_cached_data()
    
    if cached is None:
        # Cache not ready yet (server just started)
        status = get_refresh_status()
        return jsonify({
            "status": "warming_up",
            "message": "StreamScout is fetching initial data. Please retry in 30-60 seconds.",
            "is_refreshing": status.get("is_refreshing", False),
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }), 202  # 202 Accepted - request received, processing
    
    # Return cached data with limit applied
    cached["top_opportunities"] = cached["top_opportunities"][:limit]
    return jsonify(cached)

@app.route("/api/v1/force-refresh", methods=["POST"])
def force_refresh():
    """Force an immediate data refresh (admin use)"""
    status = get_refresh_status()
    if status.get("is_refreshing", False):
        return jsonify({
            "status": "already_refreshing",
            "message": "A refresh is already in progress"
        }), 409
    
    # Trigger refresh in background
    threading.Thread(target=background_refresh, daemon=True).start()
    
    return jsonify({
        "status": "refresh_started",
        "message": "Background refresh triggered"
    })

# ============================================================================
# STARTUP - Works with both direct run AND gunicorn
# ============================================================================

# Track if scheduler has been started (prevent duplicates)
_scheduler_started = False

def initialize_app():
    """Initialize the app - called once on startup"""
    global _scheduler_started
    
    if _scheduler_started:
        return
    
    # Prevent duplicate schedulers in gunicorn multi-process environments
    # Only start scheduler if we're the main process or first worker
    import os
    worker_id = os.environ.get('GUNICORN_WORKER_ID', '0')
    
    # Check for credentials
    if not TWITCH_APP_ID or not TWITCH_APP_SECRET:
        logger.warning("WARNING: Twitch API credentials not found!")
        logger.warning("   Set TWITCH_APP_ID and TWITCH_APP_SECRET environment variables")
    else:
        logger.info("Twitch API credentials loaded")
    
    logger.info("=" * 60)
    logger.info("STREAMSCOUT v3.0 - Background Worker Architecture")
    logger.info("=" * 60)
    logger.info(f"Refresh interval: {REFRESH_INTERVAL_MINUTES} minutes")
    logger.info("User requests served from pre-computed cache (instant!)")
    logger.info(f"Worker ID: {worker_id}")
    logger.info("=" * 60)
    
    # Start background worker
    start_background_worker()
    _scheduler_started = True

# Only initialize if this is the main module load (not on import by workers)
# Use --preload in gunicorn so this runs once before forking
initialize_app()

if __name__ == "__main__":
    # Direct run (for local testing)
    app.run(host="0.0.0.0", port=5000, debug=False)
