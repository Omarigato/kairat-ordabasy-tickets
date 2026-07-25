import os
import json
import requests
from http.server import BaseHTTPRequestHandler
from typing import Dict, List, Tuple

BOT_TOKEN = os.getenv("BOT_TOKEN", "8763822196:AAHKqkJr7fRfcz0dcFXK7ntnRTGVr2nwejc")
SESSION_ID = 1457825
EVENT_URL = f"https://ticketon.kz/event/tckt2-fk-kayrat-fk-ordabasy-2026/session/{SESSION_ID}"
BASE_API_URL = f"https://api-gw.ticketon.kz/event-widget/v1/session/{SESSION_ID}"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_subscribed_chats() -> set:
    """Get active chat IDs from recent Telegram updates"""
    chats = set()
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            for result in data.get("result", []):
                if "message" in result and "chat" in result["message"]:
                    chats.add(result["message"]["chat"]["id"])
    except Exception as e:
        print(f"Error fetching updates: {e}")
    return chats

def fetch_sector_names() -> Dict[int, str]:
    names = {}
    try:
        res = requests.get(f"{BASE_API_URL}/hall/static", headers=headers, timeout=5)
        if res.status_code == 200:
            for s in res.json().get("sectors", []):
                names[s["id"]] = s.get("name", f"Сектор {s['id']}")
    except Exception:
        pass
    return names

def fetch_sector_static(sector_id: int) -> Dict[int, Tuple[str, int]]:
    seats_map = {}
    try:
        res = requests.get(f"{BASE_API_URL}/sector/{sector_id}/static", headers=headers, timeout=5)
        if res.status_code == 200:
            for seat in res.json().get("seats", []):
                try:
                    s_id = int(seat["id"])
                    row = str(seat.get("row", "?"))
                    num = int(seat.get("num", 0))
                    seats_map[s_id] = (row, num)
                except Exception:
                    continue
    except Exception:
        pass
    return seats_map

def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send to {chat_id}: {e}")

def run_check():
    sector_names = fetch_sector_names()
    try:
        res = requests.get(f"{BASE_API_URL}/hall/dynamic", headers=headers, timeout=5)
        if res.status_code != 200:
            return "Ticketon hall dynamic status error"

        active_sectors = [s["id"] for s in res.json().get("sectors", []) if s.get("total_count", 0) > s.get("total_busy", 0)]
        if not active_sectors:
            return "No tickets available (All sold out)"

        pairs_found = []
        singles_found = []

        for sector_id in active_sectors:
            sec_name = sector_names.get(sector_id, f"Сектор {sector_id}")
            res_sec = requests.get(f"{BASE_API_URL}/sector/{sector_id}/dynamic", headers=headers, timeout=5)
            if res_sec.status_code != 200:
                continue

            avail_seats = res_sec.json().get("seats", [])
            if not avail_seats:
                continue

            seat_map = fetch_sector_static(sector_id)
            row_to_seats: Dict[str, List[int]] = {}
            for seat_obj in avail_seats:
                s_id = int(seat_obj["id"])
                if s_id in seat_map:
                    row, num = seat_map[s_id]
                    row_to_seats.setdefault(row, []).append(num)

            sector_pairs = []
            for row, nums in row_to_seats.items():
                sorted_nums = sorted(set(nums))
                for i in range(len(sorted_nums) - 1):
                    if sorted_nums[i+1] == sorted_nums[i] + 1:
                        sector_pairs.append({
                            "sector": sec_name,
                            "row": row,
                            "seat1": sorted_nums[i],
                            "seat2": sorted_nums[i+1]
                        })

            if sector_pairs:
                pairs_found.extend(sector_pairs)
            else:
                singles_found.append({"sector": sec_name, "count": len(avail_seats)})

        chats = get_subscribed_chats()
        if (pairs_found or singles_found) and chats:
            if pairs_found:
                msg = "🚨 **ВНИМАНИЕ! НАЙДЕНЫ 2 МЕСТА РЯДОМ!** 🚨\n\n"
                for p in pairs_found:
                    msg += f"✅ **{p['sector']}** — Ряд **{p['row']}**, Места **{p['seat1']}** и **{p['seat2']}**\n"
                msg += f"\n🔗 **[ОТКРЫТЬ TICKETON ПРЯМО СЕЙЧАС]({EVENT_URL})**"
            else:
                msg = "⚡ **ПОЯВИЛИСЬ СВОБОДНЫЕ БИЛЕТЫ!**\n\n"
                for s in singles_found:
                    msg += f"📍 **{s['sector']}**: {s['count']} мест\n"
                msg += f"\n🔗 **[ОТКРЫТЬ TICKETON]({EVENT_URL})**"

            for cid in chats:
                send_telegram_message(cid, msg)

        return f"Check completed. Pairs: {len(pairs_found)}, Singles: {len(singles_found)}"

    except Exception as e:
        return f"Error: {e}"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = run_check()
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {"status": "ok", "message": result}
        self.wfile.write(json.dumps(response).encode('utf-8'))
