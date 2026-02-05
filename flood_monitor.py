#!/usr/bin/env python3
"""
Flood Monitoring System for Ping River, Chiang Mai
Combines:
- Open-Meteo Flood API for discharge forecasts
- ThaiWater API for actual water level measurements
- Chiang Mai ThaiWater Website scraping for real-time data
Sends Telegram alerts with both forecast and real data
"""

import os
import sys
import requests
from datetime import datetime, timedelta
import json
import re
from bs4 import BeautifulSoup

# Configuration
LOCATIONS = [
    {
        "name": "แม่น้ำปิง เชียงใหม่ (สะพานนวรัฐ)",
        "latitude": 18.7374624,
        "longitude": 98.9131759,
        "station_link": "http://www.thaiwater.net/web/index.php/water/waterstation/46",
        "station_code": "P.1",  # รหัสสถานี
        "agency_code": "G07003",  # กรมชลประทาน
        "web_station_id": "P.1"  # รหัสสถานีสำหรับเว็บ Chiang Mai ThaiWater
    }
]

# Threshold levels (m³/s)
THRESHOLDS = {
    "watch": 400,      # เฝ้าระวัง
    "warning": 500,    # เตือนภัย
    "critical": 600    # วิกฤต
}

# API Configuration
# ThaiWater API
THAIWATER_API_BASE = os.environ.get("THAIWATER_API_BASE", "https://api.thaiwater.net/v1")
THAIWATER_API_KEY = os.environ.get("THAIWATER_API_KEY")

# Chiang Mai ThaiWater Website
CHIANGMAI_THAIWATER_URL = "https://chiangmai.thaiwater.net/wl"

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Send summary report even when no alerts
ALWAYS_SEND_REPORT = True


def get_chiangmai_thaiwater_data(station_id=None):
    """
    Scrape water level data from Chiang Mai ThaiWater website
    
    Args:
        station_id: Optional station ID to filter (e.g., "P.1")
        
    Returns:
        list: List of station data dictionaries or None if failed
    """
    try:
        print(f"   🌐 Fetching data from {CHIANGMAI_THAIWATER_URL}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(CHIANGMAI_THAIWATER_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the data - structure varies, try multiple approaches
        stations_data = []
        
        # Try to find tables with water level data
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            
            for row in rows:
                cells = row.find_all(['td', 'th'])
                
                if len(cells) >= 3:  # Assuming at least station, level, and time columns
                    # Extract text from cells
                    cell_texts = [cell.get_text(strip=True) for cell in cells]
                    
                    # Look for station codes like P.1, P.2, etc.
                    station_match = None
                    for text in cell_texts:
                        if re.match(r'^P\.\d+', text):
                            station_match = text
                            break
                    
                    if station_match:
                        # Try to extract water level (look for numbers with optional decimal)
                        water_level = None
                        for text in cell_texts:
                            # Match number with optional decimal
                            level_match = re.search(r'(\d+\.?\d*)', text)
                            if level_match:
                                try:
                                    water_level = float(level_match.group(1))
                                    break
                                except ValueError:
                                    continue
                        
                        if water_level is not None:
                            station_info = {
                                'station_code': station_match,
                                'water_level': water_level,
                                'raw_data': cell_texts,
                                'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'source': 'Chiang Mai ThaiWater Website'
                            }
                            
                            # If specific station requested, only add that one
                            if station_id is None or station_match == station_id:
                                stations_data.append(station_info)
        
        # Try alternative: look for JSON data in script tags
        if not stations_data:
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    # Look for JSON-like data
                    json_match = re.search(r'var\s+\w+\s*=\s*(\[.*?\]|\{.*?\});', script.string, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            print(f"   📊 Found JSON data in script tag")
                            # Process JSON data based on structure
                            # This will need adjustment based on actual data structure
                        except json.JSONDecodeError:
                            continue
        
        if stations_data:
            print(f"   ✅ Found {len(stations_data)} station(s) data from website")
            return stations_data
        else:
            print(f"   ⚠️ No station data found on website")
            return None
    
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Error fetching from Chiang Mai ThaiWater website: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Error parsing website data: {e}")
        import traceback
        traceback.print_exc()
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
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching data from Open-Meteo API: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
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
    try:
        # API Endpoint ตามเอกสาร ThaiWater Standard
        url = f"{THAIWATER_API_BASE}/WaterlevelObservation"
        
        # Parameters
        params = {
            "latest": "true",
            "agencyCode": agency_code,
            "stationCode": station_code
        }
        
        # Headers
        headers = {
            "Accept": "application/json"
        }
        
        # Add API Key if available
        if THAIWATER_API_KEY:
            headers["Authorization"] = f"Bearer {THAIWATER_API_KEY}"
        
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        # Check response
        if response.status_code == 404:
            print(f"⚠️ ThaiWater API: Station not found (404)")
            return None
        elif response.status_code == 401:
            print(f"⚠️ ThaiWater API: Unauthorized (401) - API Key may be required")
            return None
        
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ ThaiWater API response received")
        
        return data
    
    except requests.exceptions.RequestException as e:
        print(f"⚠️ ThaiWater API error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Status: {e.response.status_code}")
            print(f"   Response: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error accessing ThaiWater API: {e}")
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
        
        # ตามโครงสร้าง API ของ ThaiWater
        if "waterlevel" not in data:
            print("⚠️ No waterlevel data in ThaiWater response")
            return None
        
        waterlevels = data.get("waterlevel", [])
        
        if not waterlevels:
            print("⚠️ Empty waterlevel array")
            return None
        
        # Get latest reading (first item)
        latest = waterlevels[0]
        
        result = {
            "station_code": latest.get("stationMetadata", {}).get("stationCode"),
            "station_name": latest.get("stationMetadata", {}).get("stationName"),
            "datetime": latest.get("datetime"),
            "water_level": latest.get("observation", {}).get("waterlevel"),
            "discharge": latest.get("observation", {}).get("discharge"),
            "agency": data.get("metadata", {}).get("dataProviderName", "ThaiWater")
        }
        
        return result
    
    except Exception as e:
        print(f"❌ Error parsing ThaiWater data: {e}")
        import traceback
        traceback.print_exc()
        return None


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
            print(f"⚠️ No discharge data available for {location_name}")
            return None
        
        # Get current discharge (first value is today)
        current_discharge = discharges[0] if discharges else 0
        current_level, current_emoji, current_text = get_alert_level(current_discharge)
        
        # Print current status
        print(f"   💧 Forecast discharge: {current_discharge:.1f} m³/s - {current_emoji} {current_text}")
        
        # Collect all forecast data
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
            
            # Check for alerts in next 7 days
            if level != "normal":
                alerts.append(forecast_item)
        
        # Print all forecast data
        print(f"   📊 7-day forecast:")
        for item in forecast_data:
            print(f"      {item['date']}: {item['discharge']:.1f} m³/s {item['emoji']}")
        
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
            # Return the highest severity alert
            priority = {"critical": 3, "warning": 2, "watch": 1, "normal": 0}
            highest_alert = max(alerts, key=lambda x: priority[x["level"]])
            result["highest_alert"] = highest_alert
        
        return result
    
    except Exception as e:
        print(f"❌ Error analyzing forecast: {e}")
        import traceback
        traceback.print_exc()
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
        disable_notification: If True, sends message silently (no notification sound)
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram credentials not configured")
        print(f"   TELEGRAM_BOT_TOKEN: {'✓ Set' if TELEGRAM_BOT_TOKEN else '✗ Not set'}")
        print(f"   TELEGRAM_CHAT_ID: {'✓ Set' if TELEGRAM_CHAT_ID else '✗ Not set'}")
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
        
        print("✅ Telegram message sent successfully")
        return True
    
    except requests.exceptions.RequestException as e:
        print(f"❌ Error sending Telegram message: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text}")
        return False


def create_alert_message(location, analysis, thaiwater_info=None, website_info=None):
    """
    Create formatted alert message for Telegram when alerts are present
    
    Args:
        location: Location information dict
        analysis: Analysis result dict with alert information
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
    
    # Add website data if available (prioritize as it's most recent)
    if website_info:
        message_lines.extend([
            "<b>🌐 ข้อมูลเรียลไทม์จากเว็บไซต์:</b>",
            f"  💧 ระดับน้ำ: {website_info.get('water_level', 'N/A')} ม.(รทก.)",
            f"  🕐 อัปเดตล่าสุด: {website_info.get('datetime', 'N/A')}",
            f"  📡 แหล่งข้อมูล: {website_info.get('source', 'Chiang Mai ThaiWater')}",
            ""
        ])
    
    # Add ThaiWater API data if available
    if thaiwater_info:
        message_lines.extend([
            "<b>📊 ข้อมูลจาก ThaiWater API:</b>",
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
    
    # Add forecast for next 7 days
    for i, item in enumerate(analysis['forecast_data']):
        day_label = "วันนี้" if i == 0 else f"วันที่ {i+1}"
        date_str = format_thai_datetime(item['time'])
        message_lines.append(
            f"  {item['emoji']} {day_label} ({date_str}): {item['discharge']:.1f} m³/s"
        )
    
    message_lines.extend([
        "",
        "<b>เกณฑ์มาตรฐาน:</b>",
        f"🟢 ปกติ: &lt; {THRESHOLDS['watch']} m³/s",
        f"🟡 เฝ้าระวัง: ≥ {THRESHOLDS['watch']} m³/s",
        f"🟠 เตือนภัย: ≥ {THRESHOLDS['warning']} m³/s",
        f"🔴 วิกฤต: ≥ {THRESHOLDS['critical']} m³/s",
        "",
        "📊 <b>ตรวจสอบข้อมูลทางราชการ:</b>",
        f"🔗 <a href='{location['station_link']}'>สถานี P.1 สะพานนวรัฐ (ThaiWater)</a>",
        f"🔗 <a href='{CHIANGMAI_THAIWATER_URL}'>ศูนย์ข้อมูลน้ำ จ.เชียงใหม่</a>",
        "",
        f"🕐 <i>อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "⚠️ <i>กรุณาติดตามข่าวสารจากหน่วยงานท้องถิ่นและเตรียมความพร้อมรับมือ</i>"
    ])
    
    return "\n".join(message_lines)


def create_summary_message(location, analysis, thaiwater_info=None, website_info=None):
    """
    Create formatted summary message for regular monitoring (no alerts)
    
    Args:
        location: Location information dict
        analysis: Analysis result dict
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
    
    # Add website data if available (prioritize as it's most recent)
    if website_info:
        message_lines.extend([
            "",
            "<b>🌐 ข้อมูลเรียลไทม์จากเว็บไซต์:</b>",
            f"  💧 ระดับน้ำ: {website_info.get('water_level', 'N/A')} ม.(รทก.)",
            f"  🕐 อัปเดตล่าสุด: {website_info.get('datetime', 'N/A')}",
        ])
    
    # Add ThaiWater API data if available
    if thaiwater_info:
        message_lines.extend([
            "",
            "<b>📊 ข้อมูลจาก ThaiWater API:</b>",
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
    
    # Add forecast for next 7 days
    for i, item in enumerate(analysis['forecast_data']):
        day_label = "วันนี้" if i == 0 else f"วันที่ {i+1}"
        date_str = format_thai_datetime(item['time'])
        message_lines.append(
            f"  {item['emoji']} {day_label} ({date_str}): {item['discharge']:.1f} m³/s"
        )
    
    message_lines.extend([
        "",
        "<b>เกณฑ์มาตรฐาน:</b>",
        f"🟢 ปกติ: &lt; {THRESHOLDS['watch']} m³/s",
        f"🟡 เฝ้าระวัง: ≥ {THRESHOLDS['watch']} m³/s",
        f"🟠 เตือนภัย: ≥ {THRESHOLDS['warning']} m³/s",
        f"🔴 วิกฤต: ≥ {THRESHOLDS['critical']} m³/s",
        "",
        "📊 <b>ข้อมูลเพิ่มเติม:</b>",
        f"🔗 <a href='{location['station_link']}'>สถานี P.1 สะพานนวรัฐ (ThaiWater)</a>",
        f"🔗 <a href='{CHIANGMAI_THAIWATER_URL}'>ศูนย์ข้อมูลน้ำ จ.เชียงใหม่</a>",
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
        f"🕐 <i>เวลา: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "⚠️ <i>โปรดอย่าถือว่าสถานการณ์ปลอดภัย กรุณาตรวจสอบจากหน่วยงานท้องถิ่น</i>"
    ]
    
    return "\n".join(message_lines)


def main():
    """Main execution function"""
    print("=" * 60)
    print("🌊 Flood Monitoring System - Ping River, Chiang Mai")
    print(f"⏰ Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    any_alerts = False
    any_errors = False
    
    for location in LOCATIONS:
        print(f"\n📍 Checking: {location['name']}")
        print(f"   Coordinates: {location['latitude']}, {location['longitude']}")
        
        # 1. Fetch data from Chiang Mai ThaiWater Website (most recent)
        website_info = None
        if location.get("web_station_id"):
            print(f"\n🌐 Fetching data from Chiang Mai ThaiWater website...")
            website_data = get_chiangmai_thaiwater_data(location["web_station_id"])
            
            if website_data and len(website_data) > 0:
                website_info = website_data[0]  # Get first matching station
                print(f"   📊 Website: {website_info.get('water_level', 'N/A')} ม.(รทก.)")
                print(f"   🕐 Time: {website_info.get('datetime', 'N/A')}")
        
        # 2. Fetch ThaiWater API data (as backup/comparison)
        thaiwater_info = None
        if location.get("station_code") and location.get("agency_code"):
            print(f"\n🔍 Fetching ThaiWater API data...")
            thaiwater_data = get_thaiwater_data(
                location["station_code"],
                location["agency_code"]
            )
            
            if thaiwater_data:
                thaiwater_info = parse_thaiwater_data(thaiwater_data)
                if thaiwater_info:
                    print(f"   📊 ThaiWater API: {thaiwater_info.get('water_level', 'N/A')} ม.(รทก.)")
                    if thaiwater_info.get('discharge'):
                        print(f"   💧 Discharge: {thaiwater_info['discharge']:.1f} m³/s")
        
        # 3. Fetch forecast data from Open-Meteo
        print(f"\n🔍 Fetching Open-Meteo forecast...")
        data = get_flood_forecast(location["latitude"], location["longitude"])
        
        if data is None:
            print(f"   ❌ Failed to fetch forecast data")
            any_errors = True
            error_msg = create_error_message(location["name"])
            send_telegram_message(error_msg)
            continue
        
        # Analyze forecast
        analysis = analyze_forecast(data, location["name"])
        
        if analysis is None:
            print(f"   ❌ Failed to analyze data")
            any_errors = True
            error_msg = create_error_message(location["name"], "data")
            send_telegram_message(error_msg)
            continue
        
        # Send appropriate message
        if analysis["has_alerts"]:
            print(f"   ⚠️ ALERT DETECTED!")
            print(f"   🔴 Highest alert: {analysis['highest_alert']['text']}")
            print(f"   💧 Peak discharge: {analysis['highest_alert']['discharge']:.1f} m³/s")
            print(f"   📅 Date: {analysis['highest_alert']['date']}")
            
            # Send alert message with all available data
            message = create_alert_message(location, analysis, thaiwater_info, website_info)
            send_telegram_message(message, disable_notification=False)
            any_alerts = True
        else:
            print(f"   ✅ No alerts - levels within normal range")
            
            # Send summary report if configured
            if ALWAYS_SEND_REPORT:
                print(f"   📤 Sending summary report...")
                message = create_summary_message(location, analysis, thaiwater_info, website_info)
                # Use silent notification for normal reports
                send_telegram_message(message, disable_notification=True)
    
    print("\n" + "=" * 60)
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
