import anthropic
import asyncio
import os
import json
import logging
from datetime import datetime
import pytz
import httpx
import re
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

CHANNELS = {
    "ai": {
        "emoji": "🤖",
        "title": "Все новости ИИ",
        "prompt": "Найди 5 самых актуальных новостей за последние 48 часов по теме 'Искусственный интеллект': новые модели, исследования, продуктовые запуски, регуляция, конкуренция OpenAI/Anthropic/Google/Meta/Mistral, кейсы внедрения ИИ в бизнесе и менеджменте. Микс русских и английских источников."
    },
    "merch": {
        "emoji": "👑",
        "title": "Premium Merch",
        "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Premium Merch & Brand Experience': лимитированные коллекции, fashion-коллаборации, дизайнерский мерч, luxury merch, creator merch, VIP merch, коллекционные предметы. Источники: Hypebeast, HighSnobiety, WWD, Business of Fashion."
    },
    "loyalty": {
        "emoji": "❤️",
        "title": "Brand Loyalty",
        "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Brand Loyalty через мерч': кейсы использования физических продуктов для повышения узнаваемости, формирования сообщества, удержания клиентов, роста LTV, NPS, фанатизации аудитории. Источники: HBR, Marketing Week, Campaign, AdAge, FastCompany."
    },
    "fashion": {
        "emoji": "🛍️",
        "title": "Fashion",
        "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Fashion': Nike, Adidas, Supreme, Aimé Leon Dore, Kith, Stone Island, Jacquemus, Loewe, Rimowa, Gentle Monster, Fear of God — коллекции, коллаборации, pop-up, drops, limited editions. Источники: Hypebeast, Vogue Business, BoF, Highsnobiety."
    },
    "igaming": {
        "emoji": "🎰",
        "title": "iGaming Merch",
        "prompt": "Найди 4 актуальных новости за последние 2 недели по теме 'iGaming мерч': Stake, Duelbits, Shuffle, Rollbit, Parimatch, Pin-Up, 1xBet, BC.Game, Roobet, Melbet, GG.BET — мерч, одежда, коллаборации, VIP gifts, welcome kits, influencer kits, ивенты."
    },
    "auto": {
        "emoji": "⚙️",
        "title": "Автоматизация",
        "prompt": "Найди 4 актуальных новости за последние 72 часа по теме 'Автоматизация в мерч-индустрии': ИИ для проектирования мерча, управления производством, поставщиками, прогнозирования спроса, автоматизации закупок и логистики."
    }
}

IMP_LABELS = {"high": "🔴 Важно", "mid": "🟡 Средне", "low": "🔵 Слежу"}


async def fetch_news(channel_key: str) -> list:
    cfg = CHANNELS[channel_key]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today = datetime.now().strftime("%-d %B %Y")

    prompt = f"""Сегодня {today}. {cfg['prompt']}

Верни ТОЛЬКО валидный JSON-массив без markdown:
[{{"title":"до 80 символов","summary":"2 предложения: что произошло и почему важно","source":"издание","url":"https://реальная-ссылка","lang":"ru или en","importance":"high|mid|low"}}]

Только реальные новости и реальные URL."""

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
