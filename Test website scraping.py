#!/usr/bin/env python3
"""
Test script for scraping Chiang Mai ThaiWater website
ใช้สำหรับทดสอบและตรวจสอบโครงสร้างข้อมูลจากเว็บไซต์
"""

import requests
from bs4 import BeautifulSoup
import json
import re

CHIANGMAI_THAIWATER_URL = "https://chiangmai.thaiwater.net/wl"

def test_website_scraping():
    """Test scraping the Chiang Mai ThaiWater website"""
    
    print("=" * 70)
    print("🧪 Testing Chiang Mai ThaiWater Website Scraping")
    print("=" * 70)
    print(f"\n🔗 URL: {CHIANGMAI_THAIWATER_URL}\n")
    
    try:
        # Fetch the page
        print("📡 Fetching webpage...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(CHIANGMAI_THAIWATER_URL, headers=headers, timeout=30)
        response.raise_for_status()
        
        print(f"✅ HTTP {response.status_code} - Content received ({len(response.content)} bytes)")
        print(f"📄 Content-Type: {response.headers.get('Content-Type', 'Unknown')}\n")
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # ======================================================================
        # Method 1: Look for tables
        # ======================================================================
        print("=" * 70)
        print("METHOD 1: Searching for <table> elements")
        print("=" * 70)
        
        tables = soup.find_all('table')
        print(f"\n📊 Found {len(tables)} table(s)\n")
        
        for idx, table in enumerate(tables, 1):
            print(f"\n--- Table #{idx} ---")
            rows = table.find_all('tr')
            print(f"Rows: {len(rows)}")
            
            # Show first few rows
            for row_idx, row in enumerate(rows[:5], 1):
                cells = row.find_all(['td', 'th'])
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                
                if cell_texts:
                    print(f"  Row {row_idx}: {cell_texts}")
                    
                    # Check for station codes
                    for text in cell_texts:
                        if re.match(r'^P\.\d+', text):
                            print(f"    ⭐ Found station code: {text}")
        
        # ======================================================================
        # Method 2: Look for divs with specific classes
        # ======================================================================
        print("\n" + "=" * 70)
        print("METHOD 2: Searching for common data container elements")
        print("=" * 70)
        
        # Common class names for data containers
        common_classes = [
            'station', 'water-level', 'waterlevel', 'data',
            'table', 'content', 'info', 'monitoring'
        ]
        
        for class_name in common_classes:
            elements = soup.find_all(class_=re.compile(class_name, re.I))
            if elements:
                print(f"\n🔍 Elements with class containing '{class_name}': {len(elements)}")
                for elem in elements[:3]:  # Show first 3
                    print(f"  - {elem.name}: {elem.get('class')}")
        
        # ======================================================================
        # Method 3: Look for JSON data in script tags
        # ======================================================================
        print("\n" + "=" * 70)
        print("METHOD 3: Searching for JSON data in <script> tags")
        print("=" * 70)
        
        scripts = soup.find_all('script')
        print(f"\n📜 Found {len(scripts)} script tag(s)\n")
        
        json_found = False
        for idx, script in enumerate(scripts, 1):
            if script.string:
                # Look for JSON arrays or objects
                json_matches = re.findall(
                    r'(?:var|let|const)\s+\w+\s*=\s*(\[.*?\]|\{.*?\});',
                    script.string,
                    re.DOTALL
                )
                
                if json_matches:
                    print(f"\n--- Script #{idx} contains potential JSON data ---")
                    for match in json_matches[:2]:  # Show first 2
                        # Truncate if too long
                        display = match[:200] + "..." if len(match) > 200 else match
                        print(f"  {display}")
                        
                        # Try to parse
                        try:
                            data = json.loads(match)
                            print(f"  ✅ Valid JSON! Type: {type(data).__name__}")
                            
                            if isinstance(data, list) and len(data) > 0:
                                print(f"  📊 Array length: {len(data)}")
                                print(f"  🔍 First item preview: {str(data[0])[:150]}")
                                json_found = True
                            elif isinstance(data, dict):
                                print(f"  🔑 Keys: {list(data.keys())[:10]}")
                                json_found = True
                        except json.JSONDecodeError:
                            print(f"  ⚠️ Not valid JSON or incomplete")
        
        if not json_found:
            print("  ℹ️ No valid JSON data found in script tags")
        
        # ======================================================================
        # Method 4: Look for specific IDs
        # ======================================================================
        print("\n" + "=" * 70)
        print("METHOD 4: Searching for elements with IDs")
        print("=" * 70)
        
        elements_with_id = soup.find_all(id=True)
        print(f"\n🆔 Found {len(elements_with_id)} elements with ID attribute\n")
        
        relevant_ids = []
        for elem in elements_with_id[:20]:  # Check first 20
            elem_id = elem.get('id', '')
            if any(keyword in elem_id.lower() for keyword in 
                   ['station', 'water', 'level', 'data', 'table', 'monitoring']):
                relevant_ids.append((elem.name, elem_id))
        
        if relevant_ids:
            print("Potentially relevant IDs:")
            for name, elem_id in relevant_ids:
                print(f"  - <{name} id='{elem_id}'>")
        else:
            print("  ℹ️ No obviously relevant IDs found")
        
        # ======================================================================
        # Method 5: Full text search for station codes
        # ======================================================================
        print("\n" + "=" * 70)
        print("METHOD 5: Full text search for station codes (P.1, P.2, etc.)")
        print("=" * 70)
        
        full_text = soup.get_text()
        station_codes = re.findall(r'P\.\d+', full_text)
        
        if station_codes:
            unique_codes = sorted(set(station_codes))
            print(f"\n✅ Found station codes: {unique_codes}\n")
        else:
            print("\n⚠️ No station codes found in page text\n")
        
        # ======================================================================
        # Summary
        # ======================================================================
        print("=" * 70)
        print("📋 SUMMARY & RECOMMENDATIONS")
        print("=" * 70)
        
        print("\n✅ Data successfully fetched from website")
        print("📌 Next steps:")
        print("   1. Review the output above to understand the page structure")
        print("   2. Identify which method successfully finds water level data")
        print("   3. Update the get_chiangmai_thaiwater_data() function accordingly")
        print("   4. Test with actual data extraction\n")
        
        # Save HTML for manual inspection
        output_file = "chiangmai_thaiwater_page.html"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"💾 Full HTML saved to: {output_file}")
        print(f"   (You can open this file in a browser to inspect manually)\n")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error fetching webpage: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_website_scraping()
