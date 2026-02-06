#!/usr/bin/env python3
"""
Flood Monitoring System for Ping River, Chiang Mai - ENHANCED VERSION
Combines multiple data sources with priority fallback:
1. RID HYDRO-1 (Primary) - Most reliable government source
2. ThaiWater API (Backup) - National standard API
3. Chiang Mai ThaiWater (Alternative) - Provincial website
4. Open-Meteo Flood API - For discharge forecasts

Features:
- Multi-source data fetching with automatic fallback
- Data validation and cross-verification
- Caching to reduce API calls
- Comprehensive error handling
- Telegram alerts with combined data
"""

import os
import sys
import requests
from datetime import datetime, timedelta
import json
import re
from bs4 import BeautifulSoup
import logging
from typing import Optional, Dict, List, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
LOCATIONS = [
    {
        "name": "แม่น้ำปิง เชียงใหม่ (สะพานนวรัฐ)",
        "latitude": 18.7374624,
        "longitude": 98.9131759,
        "station_link": "http://www.thaiwater.net/web/index.php/water/waterstation/46",
        "station_code": "P.1",  # รหัสสถานี
        "agency_code": "G07003",  # กรมชลประทาน
        "web_station_id": "P.1",  # รหัสสถานีสำหรับเว็บ Chiang Mai ThaiWater
        "province_code": "50"  # รหัสจังหวัดเชียงใหม่
    }
]

# Threshold levels (m³/s)
THRESHOLDS = {
    "watch": 400,      # เฝ้าระวัง
    "warning": 500,    # เตือนภัย
    "critical": 600    # วิกฤต
}

# Water level thresholds (meters MSL)
WATER_LEVEL_THRESHOLDS = {
    "normal": 2.5,     # ปกติ
    "watch": 3.0,      # เฝ้าระวัง
    "warning": 3.5,    # เตือนภัย
    "critical": 3.7    # วิกฤต - เริ่มท่วมเมือง
}

# API Configuration
# RID HYDRO-1 (Primary - Most Reliable)
RID_HYDRO1_BASE = "http://hydro-1.rid.go.th"
RID_HYDRO1_ALT = "http://www.hydro-1.net"

# ThaiWater API (Backup)
THAIWATER_API_BASE = os.environ.get("THAIWATER_API_BASE", "https://api.thaiwater.net/v1")
THAIWATER_API_KEY = os.environ.get("THAIWATER_API_KEY")

# Chiang Mai ThaiWater Website (Alternative)
CHIANGMAI_THAIWATER_URL = "https://chiangmai.thaiwater.net/wl"
CHIANGMAI_THAIWATER_API_ENDPOINTS = [
    "https://chiangmai.thaiwater.net/api/waterlevel",
    "https://chiangmai.thaiwater.net/api/getTCFloodData",
    "https://chiangmai.thaiwater.net/data/waterlevel",
]

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Send summary report even when no alerts
ALWAYS_SEND_REPORT = True

# Cache configuration
CACHE_TTL_MINUTES = 15
_cache = {}


def get_cached_data(key: str, ttl_minutes: int = CACHE_TTL_MINUTES) -> Optional[Any]:
    """Get data from cache if not expired"""
    if key in _cache:
        data, timestamp = _cache[key]
        if datetime.now() - timestamp < timedelta(minutes=ttl_minutes):
            logger.info(f"   ✓ Using cached data for {key}")
            return data
    return None


def set_cached_data(key: str, data: Any):
    """Store data in cache with timestamp"""
    _cache[key] = (data, datetime.now())


def validate_water_level(value: float, source: str = "") -> bool:
    """
    Validate water level reading for sanity
    
    Args:
        value: Water level in meters MSL
        source: Source name for logging
        
    Returns:
        bool: True if valid, False otherwise
    """
    # P.1 reasonable range: 0.5 - 10.0 meters
    if not (0.5 <= value <= 10.0):
        logger.warning(f"   ⚠️ Suspicious water level from {source}: {value} m")
        return False
    return True


def get_rid_hydro1_data(station_code: str = "P.1") -> Optional[Dict]:
    """
    Fetch water level data from RID HYDRO-1 system
    This is the PRIMARY and most reliable source
    
    Args:
        station_code: Station code (e.g., "P.1")
        
    Returns:
        dict: Water level data or None if failed
    """
    cache_key = f"rid_hydro1_{station_code}"
    cached = get_cached_data(cache_key)
    if cached:
        return cached
    
    logger.info("   🔍 Fetching from RID HYDRO-1...")
    
    now = datetime.now()
    urls_to_try = [
        f"{RID_HYDRO1_BASE}/Data/HD-04/houly/water_today_search.php",
        f"{RID_HYDRO1_ALT}/Data/HD-04/houly/water_today_search.php"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    params = {
        'storage': station_code,
        'yy': now.year,
        'mm': f"{now.month:02d}"
    }
    
    for base_url in urls_to_try:
        try:
            logger.info(f"   🔍 Trying: {base_url}")
            response = requests.get(base_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse HTML table
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the data table
            table = soup.find('table')
            if not table:
                logger.warning("   ⚠️ No table found in response")
                continue
            
            rows = table.find_all('tr')
            data_points = []
            
            # Parse table rows (skip header)
            for row in rows[1:]:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 3:
                    continue
                
                try:
                    # Extract date, time, and water level
                    date_text = cells[0].get_text(strip=True)
                    time_text = cells[1].get_text(strip=True)
                    level_text = cells[2].get_text(strip=True)
                    
                    # Parse water level
                    # Remove any Thai text and extract number
                    level_match = re.search(r'(\d+\.?\d*)', level_text)
                    if level_match:
                        water_level = float(level_match.group(1))
                        
                        # Validate
                        if not validate_water_level(water_level, "RID HYDRO-1"):
                            continue
                        
                        data_points.append({
                            'date': date_text,
                            'time': time_text,
                            'water_level': water_level,
                            'datetime_str': f"{date_text} {time_text}"
                        })
                
                except (ValueError, IndexError, AttributeError) as e:
                    logger.debug(f"   Skipping row: {e}")
                    continue
            
            if data_points:
                # Get the latest reading (first row after header)
                latest = data_points[0]
                
                result = {
                    'station_code': station_code,
                    'station_name': f'สถานี {station_code}',
                    'water_level': latest['water_level'],
                    'datetime': latest['datetime_str'],
                    'source': 'RID HYDRO-1',
                    'quality': 'high',
                    'all_readings': data_points[:24]  # Last 24 hours
                }
                
                logger.info(f"   ✅ RID HYDRO-1: {result['water_level']} ม.(รทก.)")
                logger.info(f"   🕐 Time: {result['datetime']}")
                
                set_cached_data(cache_key, result)
                return result
            else:
                logger.warning("   ⚠️ No valid data points found")
        
        except requests.exceptions.RequestException as e:
            logger.warning(f"   ⚠️ Request failed: {e}")
            continue
        except Exception as e:
            logger.error(f"   ❌ Error parsing RID data: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    logger.warning("   ❌ All RID HYDRO-1 attempts failed")
    return None


def get_chiangmai_thaiwater_api(province_code=None, measure_datetime=None):
    """
    Try to fetch data from Chiang Mai ThaiWater API endpoints
    
    Args:
        province_code: Province code (e.g., "50" for Chiang Mai)
        measure_datetime: Optional datetime filter (YYYY-MM-DD format)
        
    Returns:
        dict: API response data or None if failed
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://chiangmai.thaiwater.net/wl'
        }
        
        # Try getTCFloodData endpoint first (most likely to have real-time data)
        if not measure_datetime:
            measure_datetime = datetime.now().strftime('%Y-%m-%d')
        
        endpoints_to_try = [
            f"https://chiangmai.thaiwater.net/api/getTCFloodData?measure_datetime={measure_datetime}",
            f"https://chiangmai.thaiwater.net/api/getTCFloodData",
            "https://chiangmai.thaiwater.net/api/waterlevel",
            f"https://chiangmai.thaiwater.net/api/waterlevel?province_code={province_code}" if province_code else None,
        ]
        
        for endpoint in endpoints_to_try:
            if endpoint is None:
                continue
                
            try:
                logger.debug(f"   🔍 Trying endpoint: {endpoint}")
                response = requests.get(endpoint, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"   ✅ Success! Got data from {endpoint}")
                    return data
                else:
                    logger.debug(f"   ⚠️ Status {response.status_code}")
                    
            except Exception as e:
                logger.debug(f"   ❌ Failed: {e}")
                continue
        
        return None
    
    except Exception as e:
        logger.warning(f"   ❌ Error in API fetch: {e}")
        return None


def parse_chiangmai_api_data(data, station_id=None):
    """
    Parse data from Chiang Mai ThaiWater API
    
    Args:
        data: API response data
        station_id: Optional station ID to filter (e.g., "P.1")
        
    Returns:
        list: List of parsed station data or None
    """
    try:
        if not data:
            return None
        
        stations = []
        
        # Handle different possible data structures
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Try common keys
            items = data.get('data', data.get('stations', data.get('waterlevel', [data])))
        else:
            return None
        
        for item in items:
            # Extract station info - handle various field names
            station_code = (item.get('station_code') or 
                          item.get('stationCode') or 
                          item.get('station_id') or 
                          item.get('id'))
            
            # Skip if not matching requested station
            if station_id and station_code != station_id:
                continue
            
            # Extract water level - try different field names
            water_level = (item.get('water_level') or 
                         item.get('waterlevel') or 
                         item.get('wl') or 
                         item.get('value'))
            
            # Extract other useful fields
            station_name = (item.get('station_name') or 
                          item.get('stationName') or 
                          item.get('name'))
            
            datetime_str = (item.get('datetime') or 
                          item.get('measure_datetime') or 
                          item.get('timestamp') or 
                          item.get('date'))
            
            if water_level is not None:
                try:
                    water_level = float(water_level)
                except (ValueError, TypeError):
                    continue
                
                if not validate_water_level(water_level, "Chiang Mai API"):
                    continue
                
                station_info = {
                    'station_code': station_code,
                    'station_name': station_name,
                    'water_level': water_level,
                    'datetime': datetime_str or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source': 'Chiang Mai ThaiWater API',
                    'quality': 'medium',
                    'raw_data': item
                }
                
                stations.append(station_info)
        
        return stations if stations else None
    
    except Exception as e:
        logger.warning(f"   ❌ Error parsing API data: {e}")
        return None


def get_chiangmai_thaiwater_data(station_id=None, province_code=None):
    """
    Get water level data from Chiang Mai ThaiWater website
    Tries both API endpoints and HTML scraping
    
    Args:
        station_id: Optional station ID to filter (e.g., "P.1")
        province_code: Province code for API calls (e.g., "50")
        
    Returns:
        list: List of station data dictionaries or None if failed
    """
    cache_key = f"chiangmai_{station_id}"
    cached = get_cached_data(cache_key)
    if cached:
        return [cached]
    
    logger.info(f"   🌐 Fetching from Chiang Mai ThaiWater...")
    
    # Method 1: Try API endpoints first
    logger.info(f"   📡 Attempting API fetch...")
    api_data = get_chiangmai_thaiwater_api(province_code)
    
    if api_data:
        parsed = parse_chiangmai_api_data(api_data, station_id)
        if parsed:
            logger.info(f"   ✅ Found {len(parsed)} station(s) from API")
            if parsed:
                set_cached_data(cache_key, parsed[0])
            return parsed
    
    # Method 2: Fall back to HTML scraping
    logger.info(f"   📄 Falling back to HTML scraping...")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(CHIANGMAI_THAIWATER_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        stations_data = []
        
        # Look for JSON data in script tags
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue
            
            # Try to find JSON arrays or objects
            json_patterns = [
                r'var\s+\w+\s*=\s*(\[.*?\]);',
                r'var\s+\w+\s*=\s*(\{.*?\});',
                r'data\s*:\s*(\[.*?\])',
                r'stations\s*:\s*(\[.*?\])',
            ]
            
            for pattern in json_patterns:
                matches = re.findall(pattern, script.string, re.DOTALL)
                for match in matches:
                    try:
                        data = json.loads(match)
                        parsed = parse_chiangmai_api_data(data, station_id)
                        if parsed:
                            stations_data.extend(parsed)
                    except:
                        continue
        
        # Also try table scraping
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) < 3:
                    continue
                
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                
                # Look for station codes
                station_match = None
                for text in cell_texts:
                    if re.match(r'^P\.\d+', text):
                        station_match = text
                        break
                
                if not station_match:
                    continue
                
                # Skip if not matching requested station
                if station_id and station_match != station_id:
                    continue
                
                # Extract water level
                water_level = None
                for text in cell_texts:
                    level_match = re.search(r'(\d+\.?\d*)', text)
                    if level_match:
                        try:
                            water_level = float(level_match.group(1))
                            # Sanity check
                            if validate_water_level(water_level, "Chiang Mai Table"):
                                break
                            else:
                                water_level = None
                        except ValueError:
                            continue
                
                if water_level is not None:
                    station_info = {
                        'station_code': station_match,
                        'water_level': water_level,
                        'raw_data': cell_texts,
                        'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'source': 'Chiang Mai ThaiWater Website (Table)',
                        'quality': 'medium'
                    }
                    stations_data.append(station_info)
        
        if stations_data:
            logger.info(f"   ✅ Found {len(stations_data)} station(s) from HTML")
            if stations_data:
                set_cached_data(cache_key, stations_data[0])
            return stations_data
        else:
            logger.info(f"   ⚠️ No data found in HTML")
            return None
    
    except Exception as e:
        logger.warning(f"   ❌ Error in HTML scraping: {e}")
        return None


def get_flood_forecast(latitude, longitude):
    """
    Fetch flood forecast data from Open-Meteo Flood API
    
    Args:
        latitude: Location latitude
        longitude: Location longitude
        
    Returns:
        dict: API response data or None if failed
    """
    cache_key = f"forecast_{latitude}_{longitude}"
    cached = get_cached_data(cache_key, ttl_minutes=60)  # Cache forecasts longer
    if cached:
        return cached
    
    try:
        url = "https://flood-api.open-meteo.com/v1/flood"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "river_discharge",
            "forecast_days": 7
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        set_cached_data(cache_key, data)
        return data
    
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error fetching data from Open-Meteo API: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return None


def get_thaiwater_data(station_code, agency_code):
    """
    Fetch actual water level data from ThaiWater API
    
    Args:
        station_code: Station code (e.g., "P.1")
        agency_code: Agency code (e.g., "G07003")
        
    Returns:
        dict: Water level data or None if failed
    """
    cache_key = f"thaiwater_{station_code}_{agency_code}"
    cached = get_cached_data(cache_key)
    if cached:
        return cached
    
    try:
        url = f"{THAIWATER_API_BASE}/WaterlevelObservation"
        
        params = {
            "latest": "true",
            "agencyCode": agency_code,
            "stationCode": station_code
        }
        
        headers = {
            "Accept": "application/json"
        }
        
        if THAIWATER_API_KEY:
            headers["Authorization"] = f"Bearer {THAIWATER_API_KEY}"
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 404:
            logger.warning(f"⚠️ ThaiWater API: Station not found (404)")
            return None
        elif response.status_code == 401:
            logger.warning(f"⚠️ ThaiWater API: Unauthorized (401) - API Key may be required")
            return None
        
        response.raise_for_status()
        data = response.json()
        logger.info(f"✅ ThaiWater API response received")
        
        set_cached_data(cache_key, data)
        return data
    
    except requests.exceptions.RequestException as e:
        logger.warning(f"⚠️ ThaiWater API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.debug(f"   Status: {e.response.status_code}")
            logger.debug(f"   Response: {e.response.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error accessing ThaiWater API: {e}")
        return None


def parse_thaiwater_data(data):
    """
    Parse ThaiWater API response to extract water level info
    
    Args:
        data: ThaiWater API response
        
    Returns:
        dict: Parsed water level information or None
    """
    try:
        if not data:
            return None
        
        if "waterlevel" not in data:
            logger.warning("⚠️ No waterlevel data in ThaiWater response")
            return None
        
        waterlevels = data.get("waterlevel", [])
        
        if not waterlevels:
            logger.warning("⚠️ Empty waterlevel array")
            return None
        
        latest = waterlevels[0]
        
        water_level = latest.get("observation", {}).get("waterlevel")
        
        if water_level and not validate_water_level(water_level, "ThaiWater API"):
            return None
        
        result = {
            "station_code": latest.get("stationMetadata", {}).get("stationCode"),
            "station_name": latest.get("stationMetadata", {}).get("stationName"),
            "datetime": latest.get("datetime"),
            "water_level": water_level,
            "discharge": latest.get("observation", {}).get("discharge"),
            "agency": data.get("metadata", {}).get("dataProviderName", "ThaiWater"),
            "source": "ThaiWater API",
            "quality": "medium"
        }
        
        return result
    
    except Exception as e:
        logger.error(f"❌ Error parsing ThaiWater data: {e}")
        return None


def get_water_level_alert_status(water_level: float) -> tuple:
    """
    Determine alert level based on water level
    
    Args:
        water_level: Water level in meters MSL
        
    Returns:
        tuple: (alert_level, emoji, text)
    """
    if water_level >= WATER_LEVEL_THRESHOLDS["critical"]:
        return "critical", "🔴", "วิกฤต (Critical) - เริ่มท่วม"
    elif water_level >= WATER_LEVEL_THRESHOLDS["warning"]:
        return "warning", "🟠", "เตือนภัย (Warning)"
    elif water_level >= WATER_LEVEL_THRESHOLDS["watch"]:
        return "watch", "🟡", "เฝ้าระวัง (Watch)"
    else:
        return "normal", "🟢", "ปกติ (Normal)"


def get_alert_level(discharge):
    """
    Determine alert level based on discharge value
    
    Args:
        discharge: River discharge in m³/s
        
    Returns:
        tuple: (alert_level, emoji, text)
    """
    if discharge >= THRESHOLDS["critical"]:
        return "critical", "🔴", "วิกฤต (Critical)"
    elif discharge >= THRESHOLDS["warning"]:
        return "warning", "🟠", "เตือนภัย (Warning)"
    elif discharge >= THRESHOLDS["watch"]:
        return "watch", "🟡", "เฝ้าระวัง (Watch)"
    else:
        return "normal", "🟢", "ปกติ (Normal)"


def analyze_forecast(data, location_name):
    """
    Analyze forecast data and check for threshold violations
    
    Args:
        data: API response data
        location_name: Name of the monitoring location
        
    Returns:
        dict: Complete forecast analysis with current status and alerts
    """
    try:
        if not data or "daily" not in data:
            return None
        
        daily_data = data["daily"]
        times = daily_data.get("time", [])
        discharges = daily_data.get("river_discharge", [])
        
        if not times or not discharges:
            logger.warning(f"⚠️ No discharge data available for {location_name}")
            return None
        
        current_discharge = discharges[0] if discharges else 0
        current_level, current_emoji, current_text = get_alert_level(current_discharge)
        
        logger.info(f"   💧 Forecast discharge: {current_discharge:.1f} m³/s - {current_emoji} {current_text}")
        
        forecast_data = []
        alerts = []
        
        for i, (time_str, discharge) in enumerate(zip(times, discharges)):
            forecast_time = datetime.fromisoformat(time_str)
            level, emoji, text = get_alert_level(discharge)
            
            forecast_item = {
                "date": time_str,
                "discharge": discharge,
                "level": level,
                "emoji": emoji,
                "text": text,
                "time": forecast_time
            }
            forecast_data.append(forecast_item)
            
            if level != "normal":
                alerts.append(forecast_item)
        
        logger.info(f"   📊 7-day forecast:")
        for item in forecast_data:
            logger.info(f"      {item['date']}: {item['discharge']:.1f} m³/s {item['emoji']}")
        
        result = {
            "current_discharge": current_discharge,
            "current_level": current_level,
            "current_emoji": current_emoji,
            "current_text": current_text,
            "forecast_data": forecast_data,
            "has_alerts": len(alerts) > 0,
            "alerts": alerts
        }
        
        if alerts:
            priority = {"critical": 3, "warning": 2, "watch": 1, "normal": 0}
            highest_alert = max(alerts, key=lambda x: priority[x["level"]])
            result["highest_alert"] = highest_alert
        
        return result
    
    except Exception as e:
        logger.error(f"❌ Error analyzing forecast: {e}")
        return None


def format_thai_datetime(dt):
    """Format datetime in Thai-friendly format"""
    thai_months = [
        "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
        "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."
    ]
    
    thai_year = dt.year + 543
    thai_month = thai_months[dt.month - 1]
    
    return f"{dt.day} {thai_month} {thai_year}"


def send_telegram_message(message, disable_notification=False):
    """
    Send message via Telegram Bot
    
    Args:
        message: Message text to send
        disable_notification: If True, sends message silently
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Telegram credentials not configured")
        logger.info(f"   TELEGRAM_BOT_TOKEN: {'✓ Set' if TELEGRAM_BOT_TOKEN else '✗ Not set'}")
        logger.info(f"   TELEGRAM_CHAT_ID: {'✓ Set' if TELEGRAM_CHAT_ID else '✗ Not set'}")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "disable_notification": disable_notification
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        logger.info("✅ Telegram message sent successfully")
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error sending Telegram message: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.debug(f"   Response: {e.response.text}")
        return False


def create_alert_message(location, analysis, rid_info=None, thaiwater_info=None, website_info=None):
    """
    Create formatted alert message for Telegram when alerts are present
    
    Args:
        location: Location information dict
        analysis: Analysis result dict with alert information
        rid_info: RID HYDRO-1 data (primary source)
        thaiwater_info: Actual water data from ThaiWater API (optional)
        website_info: Actual water data from website scraping (optional)
        
    Returns:
        str: Formatted message
    """
    alert = analysis["highest_alert"]
    
    message_lines = [
        f"{alert['emoji']} <b>⚠️ แจ้งเตือนระดับน้ำแม่น้ำปิง ⚠️</b> {alert['emoji']}",
        "",
        f"📍 <b>พื้นที่:</b> {location['name']}",
        f"⚠️ <b>ระดับเตือน:</b> {alert['text']}",
        ""
    ]
    
    # Add RID HYDRO-1 data (PRIMARY SOURCE)
    if rid_info:
        water_level = rid_info.get('water_level')
        level, emoji, text = get_water_level_alert_status(water_level)
        
        message_lines.extend([
            "<b>🏛️ ข้อมูลทางราชการ (RID HYDRO-1):</b>",
            f"  💧 ระดับน้ำ: <b>{water_level:.2f} ม.(รทก.)</b> {emoji}",
            f"  📊 สถานะ: {text}",
            f"  🕐 อัปเดตล่าสุด: {rid_info.get('datetime', 'N/A')}",
        ])
        
        # Show critical level warning
        if water_level >= WATER_LEVEL_THRESHOLDS["critical"]:
            message_lines.append(f"  ⚠️ <b>ระดับน้ำถึงเกณฑ์ท่วม ({WATER_LEVEL_THRESHOLDS['critical']} ม.)</b>")
        
        message_lines.append("")
    
    # Add website data if available
    if website_info:
        message_lines.extend([
            "<b>🌐 ข้อมูลจังหวัดเชียงใหม่:</b>",
            f"  💧 ระดับน้ำ: {website_info.get('water_level', 'N/A')} ม.(รทก.)",
            f"  🕐 อัปเดตล่าสุด: {website_info.get('datetime', 'N/A')}",
            ""
        ])
    
    # Add ThaiWater API data if available
    if thaiwater_info:
        message_lines.extend([
            "<b>📊 ข้อมูล ThaiWater API:</b>",
            f"  💧 ระดับน้ำ: {thaiwater_info.get('water_level', 'N/A')} ม.(รทก.)",
        ])
        if thaiwater_info.get('discharge'):
            message_lines.append(f"  🌊 ปริมาณน้ำ: {thaiwater_info['discharge']:.1f} m³/s")
        if thaiwater_info.get('datetime'):
            message_lines.append(f"  🕐 เวลาตรวจวัด: {thaiwater_info['datetime']}")
        message_lines.append("")
    
    message_lines.extend([
        f"<b>🔮 พยากรณ์ (Open-Meteo):</b>",
        f"  💧 ปริมาณน้ำปัจจุบัน: {analysis['current_discharge']:.1f} m³/s {analysis['current_emoji']}",
        "",
        "<b>📊 พยากรณ์ 7 วันข้างหน้า:</b>"
    ])
    
    for i, item in enumerate(analysis['forecast_data']):
        day_label = "วันนี้" if i == 0 else f"วันที่ {i+1}"
        date_str = format_thai_datetime(item['time'])
        message_lines.append(
            f"  {item['emoji']} {day_label} ({date_str}): {item['discharge']:.1f} m³/s"
        )
    
    message_lines.extend([
        "",
        "<b>⚠️ เกณฑ์ระดับน้ำ (ม.รทก.):</b>",
        f"🟢 ปกติ: &lt; {WATER_LEVEL_THRESHOLDS['watch']:.1f} ม.",
        f"🟡 เฝ้าระวัง: ≥ {WATER_LEVEL_THRESHOLDS['watch']:.1f} ม.",
        f"🟠 เตือนภัย: ≥ {WATER_LEVEL_THRESHOLDS['warning']:.1f} ม.",
        f"🔴 วิกฤต: ≥ {WATER_LEVEL_THRESHOLDS['critical']:.1f} ม. (เริ่มท่วม)",
        "",
        "<b>📊 ตรวจสอบข้อมูลทางราชการ:</b>",
        f"🔗 <a href='http://www.hydro-1.net/page1.php'>RID HYDRO-1 ภาคเหนือตอนบน</a>",
        f"🔗 <a href='{location['station_link']}'>สถานี P.1 สะพานนวรัฐ (ThaiWater)</a>",
        "",
        f"🕐 <i>อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "⚠️ <i>กรุณาติดตามข่าวสารจากหน่วยงานท้องถิ่นและเตรียมความพร้อมรับมือ</i>"
    ])
    
    return "\n".join(message_lines)


def create_summary_message(location, analysis, rid_info=None, thaiwater_info=None, website_info=None):
    """
    Create formatted summary message for regular monitoring (no alerts)
    
    Args:
        location: Location information dict
        analysis: Analysis result dict
        rid_info: RID HYDRO-1 data (primary source)
        thaiwater_info: Actual water data from ThaiWater API (optional)
        website_info: Actual water data from website scraping (optional)
        
    Returns:
        str: Formatted message
    """
    message_lines = [
        f"🌊 <b>รายงานสถานการณ์น้ำแม่น้ำปิง</b>",
        "",
        f"📍 <b>พื้นที่:</b> {location['name']}",
    ]
    
    # Add RID HYDRO-1 data (PRIMARY SOURCE)
    if rid_info:
        water_level = rid_info.get('water_level')
        level, emoji, text = get_water_level_alert_status(water_level)
        
        message_lines.extend([
            "",
            "<b>🏛️ ข้อมูลทางราชการ (RID HYDRO-1):</b>",
            f"  💧 ระดับน้ำ: <b>{water_level:.2f} ม.(รทก.)</b> {emoji}",
            f"  📊 สถานะ: {text}",
            f"  🕐 อัปเดตล่าสุด: {rid_info.get('datetime', 'N/A')}",
        ])
    
    # Add website data if available
    if website_info:
        message_lines.extend([
            "",
            "<b>🌐 ข้อมูลจังหวัดเชียงใหม่:</b>",
            f"  💧 ระดับน้ำ: {website_info.get('water_level', 'N/A')} ม.(รทก.)",
            f"  🕐 อัปเดตล่าสุด: {website_info.get('datetime', 'N/A')}",
        ])
    
    # Add ThaiWater API data if available
    if thaiwater_info:
        message_lines.extend([
            "",
            "<b>📊 ข้อมูล ThaiWater API:</b>",
            f"  💧 ระดับน้ำ: {thaiwater_info.get('water_level', 'N/A')} ม.(รทก.)",
        ])
        if thaiwater_info.get('discharge'):
            discharge = thaiwater_info['discharge']
            level, emoji, text = get_alert_level(discharge)
            message_lines.append(f"  🌊 ปริมาณน้ำ: {discharge:.1f} m³/s {emoji}")
            message_lines.append(f"  📊 สถานะ: {text}")
        if thaiwater_info.get('datetime'):
            message_lines.append(f"  🕐 เวลาตรวจวัด: {thaiwater_info['datetime']}")
    
    message_lines.extend([
        "",
        f"<b>🔮 พยากรณ์ (Open-Meteo):</b>",
        f"  💧 ปริมาณน้ำปัจจุบัน: {analysis['current_discharge']:.1f} m³/s",
        f"  📊 สถานะ: {analysis['current_emoji']} {analysis['current_text']}",
        "",
        "<b>📈 พยากรณ์ 7 วันข้างหน้า:</b>"
    ])
    
    for i, item in enumerate(analysis['forecast_data']):
        day_label = "วันนี้" if i == 0 else f"วันที่ {i+1}"
        date_str = format_thai_datetime(item['time'])
        message_lines.append(
            f"  {item['emoji']} {day_label} ({date_str}): {item['discharge']:.1f} m³/s"
        )
    
    message_lines.extend([
        "",
        "<b>⚠️ เกณฑ์ระดับน้ำ (ม.รทก.):</b>",
        f"🟢 ปกติ: &lt; {WATER_LEVEL_THRESHOLDS['watch']:.1f} ม.",
        f"🟡 เฝ้าระวัง: ≥ {WATER_LEVEL_THRESHOLDS['watch']:.1f} ม.",
        f"🟠 เตือนภัย: ≥ {WATER_LEVEL_THRESHOLDS['warning']:.1f} ม.",
        f"🔴 วิกฤต: ≥ {WATER_LEVEL_THRESHOLDS['critical']:.1f} ม. (เริ่มท่วม)",
        "",
        "📊 <b>ข้อมูลเพิ่มเติม:</b>",
        f"🔗 <a href='http://www.hydro-1.net/page1.php'>RID HYDRO-1 ภาคเหนือตอนบน</a>",
        f"🔗 <a href='{location['station_link']}'>สถานี P.1 สะพานนวรัฐ (ThaiWater)</a>",
        "",
        f"🕐 <i>อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>"
    ])
    
    return "\n".join(message_lines)


def create_error_message(location_name, error_type="api"):
    """
    Create error notification message
    
    Args:
        location_name: Name of the location
        error_type: Type of error (api, data, etc.)
        
    Returns:
        str: Formatted error message
    """
    message_lines = [
        "⚠️ <b>แจ้งเตือน: ไม่สามารถดึงข้อมูลได้</b>",
        "",
        f"📍 <b>พื้นที่:</b> {location_name}",
        f"❌ <b>สาเหตุ:</b> ระบบ API ไม่สามารถเข้าถึงได้ หรือข้อมูลไม่สมบูรณ์",
        "",
        "📌 <b>คำแนะนำ:</b>",
        "• ตรวจสอบข้อมูลจากแหล่งทางราชการโดยตรง",
        "• ระบบจะพยายามดึงข้อมูลใหม่ในรอบถัดไป",
        "",
        "🔗 <a href='http://www.hydro-1.net/page1.php'>ตรวจสอบ RID HYDRO-1</a>",
        "",
        f"🕐 <i>เวลา: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "⚠️ <i>โปรดอย่าถือว่าสถานการณ์ปลอดภัย กรุณาตรวจสอบจากหน่วยงานท้องถิ่น</i>"
    ]
    
    return "\n".join(message_lines)


def main():
    """Main execution function"""
    print("=" * 70)
    print("🌊 Flood Monitoring System - Ping River, Chiang Mai (ENHANCED)")
    print(f"⏰ Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    any_alerts = False
    any_errors = False
    
    for location in LOCATIONS:
        print(f"\n📍 Checking: {location['name']}")
        print(f"   Coordinates: {location['latitude']}, {location['longitude']}")
        
        # === PRIORITY 1: RID HYDRO-1 (Primary Source) ===
        rid_info = None
        if location.get("station_code"):
            print(f"\n🏛️ Fetching from RID HYDRO-1 (PRIMARY)...")
            rid_info = get_rid_hydro1_data(location["station_code"])
        
        # === PRIORITY 2: ThaiWater API (Backup) ===
        thaiwater_info = None
        if location.get("station_code") and location.get("agency_code"):
            print(f"\n📊 Fetching ThaiWater API data (BACKUP)...")
            thaiwater_data = get_thaiwater_data(
                location["station_code"],
                location["agency_code"]
            )
            
            if thaiwater_data:
                thaiwater_info = parse_thaiwater_data(thaiwater_data)
                if thaiwater_info:
                    logger.info(f"   ✅ ThaiWater API: {thaiwater_info.get('water_level', 'N/A')} ม.(รทก.)")
                    if thaiwater_info.get('discharge'):
                        logger.info(f"   💧 Discharge: {thaiwater_info['discharge']:.1f} m³/s")
        
        # === PRIORITY 3: Chiang Mai Website (Alternative) ===
        website_info = None
        if location.get("web_station_id"):
            print(f"\n🌐 Fetching from Chiang Mai ThaiWater (ALTERNATIVE)...")
            website_data = get_chiangmai_thaiwater_data(
                station_id=location["web_station_id"],
                province_code=location.get("province_code")
            )
            
            if website_data and len(website_data) > 0:
                website_info = website_data[0]
                logger.info(f"   ✅ Website: {website_info.get('water_level', 'N/A')} ม.(รทก.)")
                logger.info(f"   🕐 Time: {website_info.get('datetime', 'N/A')}")
        
        # === Data Quality Summary ===
        print(f"\n📊 Data Source Summary:")
        print(f"   RID HYDRO-1: {'✅ Available' if rid_info else '❌ Not available'}")
        print(f"   ThaiWater API: {'✅ Available' if thaiwater_info else '❌ Not available'}")
        print(f"   Chiang Mai Web: {'✅ Available' if website_info else '❌ Not available'}")
        
        # === Fetch forecast from Open-Meteo ===
        print(f"\n🔮 Fetching Open-Meteo forecast...")
        data = get_flood_forecast(location["latitude"], location["longitude"])
        
        if data is None:
            logger.error(f"   ❌ Failed to fetch forecast data")
            any_errors = True
            error_msg = create_error_message(location["name"])
            send_telegram_message(error_msg)
            continue
        
        # Analyze forecast
        analysis = analyze_forecast(data, location["name"])
        
        if analysis is None:
            logger.error(f"   ❌ Failed to analyze data")
            any_errors = True
            error_msg = create_error_message(location["name"], "data")
            send_telegram_message(error_msg)
            continue
        
        # === Check for alerts (from multiple sources) ===
        has_water_level_alert = False
        if rid_info:
            water_level = rid_info.get('water_level')
            if water_level >= WATER_LEVEL_THRESHOLDS['watch']:
                has_water_level_alert = True
                level, emoji, text = get_water_level_alert_status(water_level)
                logger.warning(f"   ⚠️ WATER LEVEL ALERT: {water_level:.2f} m - {text}")
        
        # Send appropriate message
        if analysis["has_alerts"] or has_water_level_alert:
            logger.warning(f"   ⚠️ ALERT DETECTED!")
            
            if analysis["has_alerts"]:
                logger.warning(f"   🔴 Forecast alert: {analysis['highest_alert']['text']}")
                logger.warning(f"   💧 Peak discharge: {analysis['highest_alert']['discharge']:.1f} m³/s")
                logger.warning(f"   📅 Date: {analysis['highest_alert']['date']}")
            
            if has_water_level_alert:
                logger.warning(f"   🔴 Water level alert: {water_level:.2f} m")
            
            message = create_alert_message(location, analysis, rid_info, thaiwater_info, website_info)
            send_telegram_message(message, disable_notification=False)
            any_alerts = True
        else:
            logger.info(f"   ✅ No alerts - levels within normal range")
            
            if ALWAYS_SEND_REPORT:
                logger.info(f"   📤 Sending summary report...")
                message = create_summary_message(location, analysis, rid_info, thaiwater_info, website_info)
                send_telegram_message(message, disable_notification=True)
    
    print("\n" + "=" * 70)
    if any_alerts:
        print("🚨 Alerts were triggered and sent")
        sys.exit(0)
    elif any_errors:
        print("⚠️ Completed with errors")
        sys.exit(0)
    else:
        print("✅ Monitoring completed - all clear")
        if ALWAYS_SEND_REPORT:
            print("📧 Summary report sent to Telegram")
        sys.exit(0)


if __name__ == "__main__":
    main()
