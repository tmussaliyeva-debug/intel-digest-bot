import anthropic
import asyncio
import os
import json
import logging
import re
import hashlib
from datetime import datetime, timedelta
import pytz
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SEEN_FILE = "/app/seen_news.json"

CHANNELS = {
    "ai": {"emoji": "🤖", "title": "Все новости ИИ", "prompt": "Найди 5 самых актуальных новостей за последние 48 часов по теме 'Искусственный интеллект': новые модели, исследования, продуктовые запуски, регуляция, конкуренция OpenAI/Anthropic/Google/Meta/Mistral, кейсы внедрения ИИ в бизнесе и менеджменте."},
    "merch": {"emoji": "👑", "title": "Premium Merch", "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Premium Merch & Brand Experience': лимитированные коллекции, fashion-коллаборации, дизайнерский мерч, luxury merch, creator merch, VIP merch."},
    "loyalty": {"emoji": "❤️", "title": "Brand Loyalty", "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Brand Loyalty через мерч': кейсы использования физических продуктов для повышения узнаваемости, формирования сообщества, удержания клиентов, роста LTV и NPS."},
    "fashion": {"emoji": "🛍️", "title": "Fashion", "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Fashion': Nike, Adidas, Supreme, Kith, Stone Island, Jacquemus, Loewe, Rimowa, Gentle Monster, Fear of God — коллекции, коллаборации, pop-up, drops."},
    "igaming": {"emoji": "🎰", "title": "iGaming Merch", "prompt": "Найди 4 актуальных новости за последние 2 недели по теме 'iGaming мерч': Stake, Parimatch, Pin-Up, 1xBet, BC.Game, Roobet, GG.BET — мерч, коллаборации, VIP gifts, influencer kits, ивенты."},
    "auto": {"emoji": "⚙️", "title": "Автоматизация", "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Автоматизация в мерч-индустрии': ИИ для проектирования мерча, управления производством, поставщиками, прогнозирования спроса."}
}

IMP_LABELS = {"high": "🔴 Важно", "mid": "🟡 Средне", "low": "🔵 Слежу"}


def load_seen() -> dict:
    try:
        with open(SEEN_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen: dict):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(seen, f)
    except Exception as e:
        logger.error(f"Failed to save seen: {e}")


def news_hash(item: dict) -> str:
    # Hash based on URL + title to detect duplicates
    key = (item.get("url", "") + item.get("title", "")).lower().strip()
    return hashlib.md5(key.encode()).hexdigest()


def filter_new(items: list, seen: dict) -> list:
    new_items = []
    for item in items:
        h = news_hash(item)
        if h not in seen:
            new_items.append(item)
    return new_items


def mark_seen(items: list, seen: dict) -> dict:
    # Keep seen history for 30 days max
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    # Clean old entries
    seen = {k: v for k, v in seen.items() if v > cutoff}
    # Add new
    now = datetime.now().isoformat()
    for item in items:
        seen[news_hash(item)] = now
    return seen


async def fetch_news(channel_key: str) -> list:
    cfg = CHANNELS[channel_key]
    today = datetime.now().strftime("%-d %B %Y")
    prompt = f"""Сегодня {today}. {cfg['prompt']}

Верни ТОЛЬКО валидный JSON-массив без markdown:
[{{"title":"до 80 символов","summary":"2 предложения: что произошло и почему важно","source":"издание","url":"https://реальная-ссылка","lang":"ru или en","importance":"high|mid|low"}}]

Только реальные новости и реальные URL."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": prompt}]
    final_text = ""
    iterations = 0

    while iterations < 10:
        iterations += 1
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages
        )
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        if response.stop_reason == "end_turn":
            break
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": "[]"}
                for b in response.content if b.type == "tool_use"
            ]
            if not tool_results:
                break
            messages.append({"role": "user", "content": tool_results})
            final_text = ""
        else:
            break

    clean = final_text.replace("```json", "").replace("```", "").strip()
    m = re.search(r'\[[\s\S]*\]', clean)
    if not m:
        return []
    return json.loads(m.group())


async def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
        logger.info(f"Telegram: {r.status_code}")


def format_message(channel_key: str, items: list) -> str:
    cfg = CHANNELS[channel_key]
    lines = [f"{cfg['emoji']} *{cfg['title']}*\n"]
    for item in items[:5]:
        imp = IMP_LABELS.get(item.get("importance", "low"), "🔵 Слежу")
        lang = "🇷🇺" if item.get("lang") == "ru" else "🇬🇧"
        title = item.get("title", "").replace("*", "").replace("[", "").replace("]", "")
        summary = item.get("summary", "").replace("*", "")
        url = item.get("url", "")
        source = item.get("source", "")
        lines.append(f"{imp} {lang} [{title}]({url})")
        lines.append(f"_{summary}_")
        lines.append(f"📰 {source}\n")
    return "\n".join(lines)


async def send_digest():
    logger.info("Starting digest...")
    seen = load_seen()
    cyprus_tz = pytz.timezone("Asia/Nicosia")
    now = datetime.now(cyprus_tz).strftime("%d.%m.%Y")

    await send_telegram(
        f"📋 *Intel Digest — {now}*\n"
        f"Только новые новости\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    total_new = 0
    for ch_key in CHANNELS:
        try:
            logger.info(f"Fetching {ch_key}...")
            items = await fetch_news(ch_key)
            new_items = filter_new(items, seen)
            logger.info(f"{ch_key}: {len(items)} total, {len(new_items)} new")

            if new_items:
                await send_telegram(format_message(ch_key, new_items))
                seen = mark_seen(new_items, seen)
                total_new += len(new_items)
                await asyncio.sleep(2)
            else:
                logger.info(f"{ch_key}: no new news, skipping")
        except Exception as e:
            logger.error(f"Error {ch_key}: {e}")
            await send_telegram(f"⚠️ Ошибка *{CHANNELS[ch_key]['title']}*: {str(e)[:100]}")

    save_seen(seen)

    if total_new == 0:
        await send_telegram("📭 Новых новостей сегодня нет. До завтра!")
    else:
        await send_telegram(f"✅ Готово! Новых новостей: {total_new}")

    logger.info("Digest sent.")


async def main():
    logger.info("Bot starting...")
    if os.environ.get("SEND_ON_START", "false").lower() == "true":
        await send_digest()

    scheduler = AsyncIOScheduler(timezone="Asia/Nicosia")
    scheduler.add_job(send_digest, "cron", hour=14, minute=0)
    scheduler.start()
    logger.info("Scheduler started. Waiting for 14:00 Cyprus time...")

    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
