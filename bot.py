import os
import time
import logging
import asyncio
import requests
from typing import Dict, List, Tuple
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
BOT_TOKEN = os.getenv("BOT_TOKEN", "8763822196:AAHKqkJr7fRfcz0dcFXK7ntnRTGVr2nwejc")
SESSION_ID = 1457825
EVENT_URL = f"https://ticketon.kz/event/tckt2-fk-kayrat-fk-ordabasy-2026/session/{SESSION_ID}"
CHECK_INTERVAL = 10  # Check every 10 seconds

BASE_API_URL = f"https://api-gw.ticketon.kz/event-widget/v1/session/{SESSION_ID}"

# Subscribed chats
subscribed_chats = set()

# Cache for sector static seat data: sector_id -> dict of seat_id -> (row, num)
sector_static_cache: Dict[int, Dict[int, Tuple[str, int]]] = {}
sector_names_cache: Dict[int, str] = {}


def fetch_hall_static():
    """Fetch sector names and static layout"""
    url = f"{BASE_API_URL}/hall/static"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for s in data.get("sectors", []):
                sector_names_cache[s["id"]] = s.get("name", f"Сектор {s['id']}")
            logger.info(f"Loaded {len(sector_names_cache)} sector names from static layout")
    except Exception as e:
        logger.error(f"Error fetching hall static layout: {e}")


def fetch_sector_static(sector_id: int) -> Dict[int, Tuple[str, int]]:
    """Fetch and cache seat row/num details for a given sector"""
    if sector_id in sector_static_cache:
        return sector_static_cache[sector_id]

    url = f"{BASE_API_URL}/sector/{sector_id}/static"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    seats_map = {}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for seat in data.get("seats", []):
                try:
                    s_id = int(seat["id"])
                    row = str(seat.get("row", "?"))
                    num = int(seat.get("num", 0))
                    seats_map[s_id] = (row, num)
                except (ValueError, KeyError):
                    continue
            sector_static_cache[sector_id] = seats_map
            logger.info(f"Cached {len(seats_map)} seats for sector {sector_id}")
    except Exception as e:
        logger.error(f"Error fetching sector {sector_id} static layout: {e}")

    return seats_map


def check_tickets() -> Tuple[List[dict], List[dict]]:
    """
    Checks ticket availability.
    Returns:
      - pairs_found: List of dicts with adjacent seat pairs
      - single_seats_found: List of dicts with any available seats
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # 1. Fetch dynamic hall overview
    url_dynamic = f"{BASE_API_URL}/hall/dynamic"
    try:
        res = requests.get(url_dynamic, headers=headers, timeout=10)
        if res.status_code != 200:
            logger.warning(f"Hall dynamic API returned status {res.status_code}")
            return [], []

        data = res.json()
        active_sectors = []
        for s in data.get("sectors", []):
            total_count = s.get("total_count", 0)
            total_busy = s.get("total_busy", 0)
            if total_count > total_busy:
                active_sectors.append(s["id"])

        if not active_sectors:
            return [], []

        logger.info(f"Found active sectors with available tickets: {active_sectors}")

        pairs_found = []
        single_seats_found = []

        # 2. Inspect each sector with available tickets
        for sector_id in active_sectors:
            sec_name = sector_names_cache.get(sector_id, f"Сектор {sector_id}")
            sec_dynamic_url = f"{BASE_API_URL}/sector/{sector_id}/dynamic"
            res_sec = requests.get(sec_dynamic_url, headers=headers, timeout=10)
            if res_sec.status_code != 200:
                continue

            sec_data = res_sec.json()
            avail_seats = sec_data.get("seats", [])
            if not avail_seats:
                continue

            # Load static mapping for this sector
            seat_map = fetch_sector_static(sector_id)

            # Group available seats by row
            row_to_seats: Dict[str, List[int]] = {}
            for seat_obj in avail_seats:
                s_id = int(seat_obj["id"])
                if s_id in seat_map:
                    row, num = seat_map[s_id]
                    row_to_seats.setdefault(row, []).append(num)

            # Search for adjacent seats (e.g. num and num+1)
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
                single_seats_found.append({
                    "sector": sec_name,
                    "count": len(avail_seats)
                })

        return pairs_found, single_seats_found

    except Exception as e:
        logger.error(f"Error during check_tickets: {e}")
        return [], []


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribed_chats.add(chat_id)
    msg = (
        "✅ **Подписка на уведомления включена!**\n\n"
        "⚽ **Матч:** ФК Кайрат — ФК Ордабасы\n"
        "📍 **Место:** Центральный Стадион, Алматы\n"
        "📅 **Дата:** 26 июля 19:00\n\n"
        "🔍 Я проверяю билеты каждые 10 секунд.\n"
        "Как только появятся **2 МЕСТА РЯДОМ в одном ряду**, я сразу пришлю тебе прямое сообщение со всеми деталями и ссылкой для покупки!\n\n"
        "Команды:\n"
        "/status — проверить статус работы\n"
        "/check — запустить мгновенную проверку вручную"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 Бот активно работает!\nПодписано чатов: {len(subscribed_chats)}\nИнтервал проверки: {CHECK_INTERVAL} сек.",
        parse_mode="Markdown"
    )


async def manual_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 Проверяю билеты прямо сейчас...")
    pairs, singles = check_tickets()
    if pairs:
        text = "🔥 **НАЙДЕНЫ МЕСТА РЯДОМ!** 🔥\n\n"
        for p in pairs:
            text += f"📍 **{p['sector']}** | Ряд **{p['row']}** | Места **{p['seat1']} и {p['seat2']}**\n"
        text += f"\n👉 [КУПИТЬ БИЛЕТЫ НА TICKETON]({EVENT_URL})"
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    elif singles:
        text = "⚡ **Появились билеты, но не рядом:**\n"
        for s in singles:
            text += f"• **{s['sector']}**: {s['count']} шт.\n"
        text += f"\n👉 [ОТКРЫТЬ TICKETON]({EVENT_URL})"
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text("❌ Пока свободных билетов нет (Аншлаг). Продолжаю мониторинг!")


async def monitor_task(bot: Bot):
    """Background task running continuous ticket checks"""
    logger.info("Starting background ticket monitor...")
    last_notify_time = 0

    while True:
        try:
            pairs, singles = check_tickets()
            current_time = time.time()

            # Send notification if pairs found, or if single tickets found (throttled to avoid spamming every 10s)
            if (pairs or singles) and (current_time - last_notify_time > 60):
                if subscribed_chats:
                    if pairs:
                        message = "🚨 **ВНИМАНИЕ! НАЙДЕНЫ 2 МЕСТА РЯДОМ!** 🚨\n\n"
                        message += "Скорее заходи и выкупай:\n"
                        for p in pairs:
                            message += f"✅ **{p['sector']}** — Ряд **{p['row']}**, Места **{p['seat1']}** и **{p['seat2']}**\n"
                        message += f"\n🔗 **[ОТКРЫТЬ TICKETON ПРЯМО СЕЙЧАС]({EVENT_URL})**"
                    else:
                        message = "⚡ **ПОЯВИЛИСЬ СВОБОДНЫЕ БИЛЕТЫ!**\n\n"
                        for s in singles:
                            message += f"📍 **{s['sector']}**: {s['count']} мест\n"
                        message += f"\n🔗 **[ОТКРЫТЬ TICKETON]({EVENT_URL})**"

                    for chat_id in list(subscribed_chats):
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode="Markdown",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logger.error(f"Failed to send alert to {chat_id}: {e}")

                    last_notify_time = current_time

        except Exception as e:
            logger.error(f"Error in monitor cycle: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


def main():
    # Pre-fetch sector static names
    fetch_hall_static()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("check", manual_check_command))

async def post_init(application: Application):
    asyncio.create_task(monitor_task(application.bot))

def main():
    # Pre-fetch sector static names
    fetch_hall_static()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("check", manual_check_command))

    logger.info("Bot starting polling...")
    app.run_polling()



if __name__ == "__main__":
    main()
