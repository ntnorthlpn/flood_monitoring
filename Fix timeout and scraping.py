#!/usr/bin/env python3
"""
แก้ไขปัญหา Timeout และ Web Scraping
เพิ่มความยืดหยุ่นให้กับระบบ
"""

# ======================================================================
# แก้ไขที่ 1: เพิ่ม Retry Logic สำหรับ API Timeout
# ======================================================================

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

def create_retry_session(
    retries=3,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504),
    session=None
):
    """
    สร้าง requests session ที่มี retry logic
    
    Args:
        retries: จำนวนครั้งที่จะลองใหม่
        backoff_factor: เวลารอระหว่างการลอง (0.3, 0.6, 1.2 วินาที)
        status_forcelist: HTTP status codes ที่ต้องการ retry
        session: existing session (optional)
    
    Returns:
        requests.Session: Session พร้อม retry logic
    """
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def get_thaiwater_data_with_retry(station_code, agency_code, max_attempts=2):
    """
    ดึงข้อมูลจาก ThaiWater API พร้อม retry logic
    
    Args:
        station_code: รหัสสถานี
        agency_code: รหัสหน่วยงาน
        max_attempts: จำนวนครั้งที่จะลองสูงสุด
    
    Returns:
        dict: ข้อมูลระดับน้ำ หรือ None
    """
    THAIWATER_API_BASE = "https://api.thaiwater.net/v1"
    THAIWATER_API_KEY = None  # ใส่ API key ถ้ามี
    
    url = f"{THAIWATER_API_BASE}/WaterlevelObservation"
    params = {
        "latest": "true",
        "agencyCode": agency_code,
        "stationCode": station_code
    }
    
    headers = {"Accept": "application/json"}
    if THAIWATER_API_KEY:
        headers["Authorization"] = f"Bearer {THAIWATER_API_KEY}"
    
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"   🔄 Attempt {attempt}/{max_attempts}...")
            
            # สร้าง session พร้อม retry
            session = create_retry_session()
            
            # ลด timeout เป็น 15 วินาที แทน 30
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 404:
                print(f"   ⚠️ Station not found (404)")
                return None
            elif response.status_code == 401:
                print(f"   ⚠️ Unauthorized (401)")
                return None
            
            response.raise_for_status()
            print(f"   ✅ Success on attempt {attempt}")
            return response.json()
            
        except requests.exceptions.Timeout:
            print(f"   ⏱️ Timeout on attempt {attempt}")
            if attempt < max_attempts:
                wait_time = 2 * attempt  # รอ 2, 4 วินาที
                print(f"   ⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                print(f"   ❌ All attempts failed")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error on attempt {attempt}: {e}")
            if attempt < max_attempts:
                time.sleep(2)
            else:
                return None
        
        finally:
            if 'session' in locals():
                session.close()
    
    return None


# ======================================================================
# แก้ไขที่ 2: ปรับปรุง Web Scraping ให้ยืดหยุ่นขึ้น
# ======================================================================

from bs4 import BeautifulSoup
import re
import json

def get_chiangmai_thaiwater_data_improved(station_id=None):
    """
    ดึงข้อมูลจากเว็บ Chiang Mai ThaiWater แบบยืดหยุ่น
    พยายามหลายวิธีจนกว่าจะเจอข้อมูล
    """
    url = "https://chiangmai.thaiwater.net/wl"
    
    try:
        print(f"   🌐 Fetching from {url}...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'th-TH,th;q=0.9,en;q=0.8',
        }
        
        # ลด timeout เป็น 20 วินาที
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        # บันทึกไฟล์เพื่อ debug
        with open('chiangmai_thaiwater_debug.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"   💾 Saved HTML to chiangmai_thaiwater_debug.html")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # ======================================================================
        # วิธีที่ 1: หา element ที่มี text "P.1" โดยตรง
        # ======================================================================
        print(f"   🔍 Method 1: Searching for text 'P.1'...")
        station_elements = soup.find_all(string=re.compile(r'P\.\d+'))
        
        if station_elements:
            print(f"   ✅ Found {len(station_elements)} station code(s)")
            for elem in station_elements[:3]:
                print(f"      - {elem.strip()}")
                parent = elem.parent
                # หาตัวเลขในบริเวณใกล้เคียง
                if parent:
                    nearby_numbers = re.findall(r'\d+\.?\d*', parent.get_text())
                    if nearby_numbers:
                        print(f"        Numbers nearby: {nearby_numbers}")
        
        # ======================================================================
        # วิธีที่ 2: หา JSON data ใน window variable
        # ======================================================================
        print(f"   🔍 Method 2: Looking for JavaScript data...")
        scripts = soup.find_all('script')
        
        for script in scripts:
            if script.string and ('var ' in script.string or 'let ' in script.string):
                # หา JSON arrays หรือ objects
                matches = re.finditer(
                    r'(?:var|let|const)\s+(\w+)\s*=\s*(\[[\s\S]*?\]|\{[\s\S]*?\});',
                    script.string
                )
                
                for match in matches:
                    var_name = match.group(1)
                    var_value = match.group(2)
                    
                    # ลองแปลงเป็น JSON
                    try:
                        data = json.loads(var_value)
                        
                        # ตรวจสอบว่ามีข้อมูลสถานีหรือไม่
                        if isinstance(data, list) and len(data) > 0:
                            first_item = data[0]
                            if isinstance(first_item, dict):
                                # ลอง print keys เพื่อดูโครงสร้าง
                                print(f"   ✅ Found variable '{var_name}' with {len(data)} items")
                                print(f"      Keys: {list(first_item.keys())[:10]}")
                                
                                # ตรวจสอบว่ามี station code หรือไม่
                                for key in first_item.keys():
                                    if 'station' in key.lower() or 'code' in key.lower():
                                        print(f"      Possible station field: {key} = {first_item[key]}")
                                
                                # ลองหาฟิลด์ที่เกี่ยวข้องกับระดับน้ำ
                                for key in first_item.keys():
                                    if any(w in key.lower() for w in ['level', 'water', 'depth', 'ระดับ']):
                                        print(f"      Possible water level field: {key} = {first_item[key]}")
                                
                                # บันทึก JSON เพื่อดู
                                with open('chiangmai_data.json', 'w', encoding='utf-8') as f:
                                    json.dump(data, f, indent=2, ensure_ascii=False)
                                print(f"      💾 Saved to chiangmai_data.json")
                                
                    except json.JSONDecodeError:
                        continue
        
        # ======================================================================
        # วิธีที่ 3: หาจาก API endpoint ที่ซ่อนอยู่
        # ======================================================================
        print(f"   🔍 Method 3: Looking for API endpoints...")
        
        # หา URL ที่อาจเป็น API
        for script in scripts:
            if script.string:
                api_urls = re.findall(
                    r'["\']([^"\']*(?:api|data)[^"\']*\.(?:json|php|aspx))["\']',
                    script.string
                )
                if api_urls:
                    print(f"   📡 Found potential API URLs:")
                    for api_url in set(api_urls):
                        print(f"      - {api_url}")
        
        # ======================================================================
        # วิธีที่ 4: หาจาก meta tags หรือ data attributes
        # ======================================================================
        print(f"   🔍 Method 4: Checking data attributes...")
        
        elements_with_data = soup.find_all(attrs={"data-station": True})
        if elements_with_data:
            print(f"   ✅ Found {len(elements_with_data)} elements with data-station")
            for elem in elements_with_data[:3]:
                print(f"      {elem.name}: {elem.attrs}")
        
        elements_with_data = soup.find_all(attrs={"data-level": True})
        if elements_with_data:
            print(f"   ✅ Found {len(elements_with_data)} elements with data-level")
            for elem in elements_with_data[:3]:
                print(f"      {elem.name}: {elem.attrs}")
        
        print(f"   💡 Check chiangmai_thaiwater_debug.html and chiangmai_data.json for more details")
        
        return None
        
    except requests.exceptions.Timeout:
        print(f"   ⏱️ Website timeout after 20 seconds")
        return None
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Error fetching website: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return None


# ======================================================================
# แก้ไขที่ 3: ปรับ Message ให้แสดงสถานะการดึงข้อมูล
# ======================================================================

def create_summary_message_improved(location, analysis, thaiwater_info=None, website_info=None):
    """
    สร้างข้อความสรุปที่แสดงสถานะการดึงข้อมูลจากแต่ละแหล่ง
    """
    message_lines = [
        f"🌊 <b>รายงานสถานการณ์น้ำแม่น้ำปิง</b>",
        "",
        f"📍 <b>พื้นที่:</b> {location['name']}",
        ""
    ]
    
    # แสดงสถานะการดึงข้อมูลจากแต่ละแหล่ง
    data_sources = []
    
    if website_info:
        data_sources.append("✅ เว็บไซต์ จ.เชียงใหม่")
        message_lines.extend([
            "<b>🌐 ข้อมูลจากเว็บไซต์:</b>",
            f"  💧 ระดับน้ำ: {website_info.get('water_level', 'N/A')} ม.(รทก.)",
            ""
        ])
    else:
        data_sources.append("⚠️ เว็บไซต์ จ.เชียงใหม่ (ไม่สามารถดึงข้อมูลได้)")
    
    if thaiwater_info:
        data_sources.append("✅ ThaiWater API")
        message_lines.extend([
            "<b>📊 ข้อมูลจาก ThaiWater API:</b>",
            f"  💧 ระดับน้ำ: {thaiwater_info.get('water_level', 'N/A')} ม.(รทก.)",
            ""
        ])
    else:
        data_sources.append("⚠️ ThaiWater API (Timeout/ไม่พร้อมใช้งาน)")
    
    if analysis:
        data_sources.append("✅ Open-Meteo พยากรณ์")
        message_lines.extend([
            f"<b>🔮 พยากรณ์ (Open-Meteo):</b>",
            f"  💧 ปริมาณน้ำปัจจุบัน: {analysis['current_discharge']:.1f} m³/s",
            f"  📊 สถานะ: {analysis['current_emoji']} {analysis['current_text']}",
            ""
        ])
    
    # แสดงสถานะแหล่งข้อมูล
    message_lines.extend([
        "<b>📡 สถานะแหล่งข้อมูล:</b>"
    ])
    for source in data_sources:
        message_lines.append(f"  {source}")
    
    message_lines.extend([
        "",
        f"🕐 <i>อัปเดต: {datetime.now().strftime('%d/%m/%Y %H:%M')} น.</i>",
        "",
        "<i>💡 หากข้อมูลไม่ครบถ้วน กรุณาตรวจสอบจากแหล่งทางราชการโดยตรง</i>"
    ])
    
    return "\n".join(message_lines)


# ======================================================================
# ตัวอย่างการใช้งาน
# ======================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 Testing Improved Functions")
    print("=" * 70)
    
    # ทดสอบ Web Scraping
    print("\n1️⃣ Testing Web Scraping...")
    get_chiangmai_thaiwater_data_improved("P.1")
    
    # ทดสอบ API with Retry
    print("\n2️⃣ Testing ThaiWater API with Retry...")
    result = get_thaiwater_data_with_retry("P.1", "G07003", max_attempts=2)
    if result:
        print("✅ API call successful")
    else:
        print("⚠️ API call failed after retries")
    
    print("\n" + "=" * 70)
    print("✅ Test complete")
    print("=" * 70)
