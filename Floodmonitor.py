#!/usr/bin/env python3
"""
Flood Monitoring System for Ping River, Chiang Mai
Uses Open-Meteo Flood API to forecast river discharge and sends Telegram alerts
"""

import os
import sys
import requests
from datetime import datetime, timedelta
import json

# Configuration
LOCATIONS = [
    {
        "name": "แม่น้ำปิง เชียงใหม่ (สะพานนวรัฐ)",
        "latitude": 18.7374624,
        "longitude": 98.9131759,
        "station_link": "http://www.thaiwater.net/web/index.php/water/waterstation/46"
    }
]

# Threshold levels (m³/s)
THRESHOLDS = {
    "watch": 400,      # เฝ้าระวัง
    "warning": 500,    # เตือนภัย
    "critical": 600    # วิกฤต
}

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Note: TELEGRAM_CHAT_ID can be:
# - Personal chat: positive number (e.g., "123456789")
# - Group chat: negative number starting with -100 (e.g., "-1001234567890")
# - Channel: negative number starting with -100 (e.g., "-1001234567890")


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
        print(f"❌ Error fetching data from API: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None


def analyze_forecast(data, location_name):
    """
    Analyze forecast data and check for threshold violations in next 24 hours
    
    Args:
        data: API response data
        location_name: Name of the monitoring location
        
    Returns:
        dict: Alert information or None if no alert needed
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
        
        # Check next 24 hours (today and tomorrow)
        current_time = datetime.now()
        next_24h = current_time + timedelta(hours=24)
        
        alerts = []
        
        for i, (time_str, discharge) in enumerate(zip(times[:2], discharges[:2])):
            forecast_time = datetime.fromisoformat(time_str)
            
            if forecast_time > next_24h:
                continue
            
            # Check thresholds
            alert_level = None
            if discharge >= THRESHOLDS["critical"]:
                alert_level = "critical"
                alert_emoji = "🔴"
                alert_text = "วิกฤต (Critical)"
            elif discharge >= THRESHOLDS["warning"]:
                alert_level = "warning"
                alert_emoji = "🟠"
                alert_text = "เตือนภัย (Warning)"
            elif discharge >= THRESHOLDS["watch"]:
                alert_level = "watch"
                alert_emoji = "🟡"
                alert_text = "เฝ้าระวัง (Watch)"
            
            if alert_level:
                alerts.append({
                    "level": alert_level,
                    "emoji": alert_emoji,
                    "text": alert_text,
                    "discharge": discharge,
                    "time": forecast_time,
                    "time_str": time_str
                })
        
        if alerts:
            # Return the highest severity alert
            priority = {"critical": 3, "warning": 2, "watch": 1}
            highest_alert = max(alerts, key=lambda x: priority[x["level"]])
            highest_alert["all_alerts"] = alerts
            return highest_alert
        
        return None
    
    except Exception as e:
        print(f"❌ Error analyzing forecast: {e}")
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
        return False


def create_alert_message(location, alert):
    """
    Create formatted alert message for Telegram
    
    Args:
        location: Location information dict
        alert: Alert information dict
        
    Returns:
        str: Formatted message
    """
    message_lines = [
        f"{alert['emoji']} <b>แจ้งเตือนระดับน้ำแม่น้ำปิง</b> {alert['emoji']}",
        "",
        f"📍 <b>พื้นที่:</b> {location['name']}",
        f"⚠️ <b>ระดับ:</b> {alert['text']}",
        f"💧 <b>ปริมาณน้ำ:</b> {alert['discharge']:.1f} m³/s",
        f"📅 <b>วันที่คาดการณ์:</b> {format_thai_datetime(alert['time'])}",
        "",
        "<b>เกณฑ์มาตรฐาน:</b>",
        f"🟡 เฝ้าระวัง: > {THRESHOLDS['watch']} m³/s",
        f"🟠 เตือนภัย: > {THRESHOLDS['warning']} m³/s",
        f"🔴 วิกฤต: > {THRESHOLDS['critical']} m³/s",
        "",
        "📊 <b>ตรวจสอบข้อมูลทางราชการ:</b>",
        f"🔗 <a href='{location['station_link']}'>สถานี P.1 สะพานนวรัฐ (ThaiWater)</a>",
        "",
        f"🕐 <i>ข้อมูล ณ {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "⚠️ <i>กรุณาติดตามข่าวสารจากหน่วยงานท้องถิ่นและเตรียมความพร้อมรับมือ</i>"
    ]
    
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
        
        # Fetch forecast data
        data = get_flood_forecast(location["latitude"], location["longitude"])
        
        if data is None:
            print(f"   ❌ Failed to fetch data")
            any_errors = True
            error_msg = create_error_message(location["name"])
            send_telegram_message(error_msg)
            continue
        
        # Analyze forecast
        alert = analyze_forecast(data, location["name"])
        
        if alert:
            print(f"   ⚠️ ALERT: {alert['text']}")
            print(f"   💧 Discharge: {alert['discharge']:.1f} m³/s")
            print(f"   📅 Time: {alert['time_str']}")
            
            # Send Telegram alert
            message = create_alert_message(location, alert)
            send_telegram_message(message)
            any_alerts = True
        else:
            print(f"   ✅ No alerts - levels within normal range")
    
    print("\n" + "=" * 60)
    if any_alerts:
        print("🚨 Alerts were triggered and sent")
        sys.exit(0)  # Exit successfully even with alerts
    elif any_errors:
        print("⚠️ Completed with errors")
        sys.exit(0)  # Don't fail the workflow, just log the error
    else:
        print("✅ Monitoring completed - all clear")
        sys.exit(0)


if __name__ == "__main__":
    main()
