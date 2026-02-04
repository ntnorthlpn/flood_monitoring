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

# Send summary report even when no alerts (set to True to always get updates)
ALWAYS_SEND_REPORT = True

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
        print(f"   💧 Current discharge: {current_discharge:.1f} m³/s - {current_emoji} {current_text}")
        
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


def create_alert_message(location, analysis):
    """
    Create formatted alert message for Telegram when alerts are present
    
    Args:
        location: Location information dict
        analysis: Analysis result dict with alert information
        
    Returns:
        str: Formatted message
    """
    alert = analysis["highest_alert"]
    
    message_lines = [
        f"{alert['emoji']} <b>⚠️ แจ้งเตือนระดับน้ำแม่น้ำปิง ⚠️</b> {alert['emoji']}",
        "",
        f"📍 <b>พื้นที่:</b> {location['name']}",
        f"⚠️ <b>ระดับเตือน:</b> {alert['text']}",
        "",
        f"💧 <b>ปริมาณน้ำปัจจุบัน:</b> {analysis['current_discharge']:.1f} m³/s {analysis['current_emoji']}",
        "",
        "<b>📊 พยากรณ์ 7 วันข้างหน้า:</b>"
    ]
    
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
        "",
        f"🕐 <i>อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "⚠️ <i>กรุณาติดตามข่าวสารจากหน่วยงานท้องถิ่นและเตรียมความพร้อมรับมือ</i>"
    ])
    
    return "\n".join(message_lines)


def create_summary_message(location, analysis):
    """
    Create formatted summary message for regular monitoring (no alerts)
    
    Args:
        location: Location information dict
        analysis: Analysis result dict
        
    Returns:
        str: Formatted message
    """
    message_lines = [
        f"🌊 <b>รายงานสถานการณ์น้ำแม่น้ำปิง</b>",
        "",
        f"📍 <b>พื้นที่:</b> {location['name']}",
        f"💧 <b>ปริมาณน้ำปัจจุบัน:</b> {analysis['current_discharge']:.1f} m³/s",
        f"📊 <b>สถานะ:</b> {analysis['current_emoji']} {analysis['current_text']}",
        "",
        "<b>📈 พยากรณ์ 7 วันข้างหน้า:</b>"
    ]
    
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
        
        # Fetch forecast data
        data = get_flood_forecast(location["latitude"], location["longitude"])
        
        if data is None:
            print(f"   ❌ Failed to fetch data")
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
            
            # Send alert message
            message = create_alert_message(location, analysis)
            send_telegram_message(message, disable_notification=False)
            any_alerts = True
        else:
            print(f"   ✅ No alerts - levels within normal range")
            
            # Send summary report if configured
            if ALWAYS_SEND_REPORT:
                print(f"   📤 Sending summary report...")
                message = create_summary_message(location, analysis)
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
