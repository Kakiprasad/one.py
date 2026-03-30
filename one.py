import cloudscraper
import requests
import time
import re
import os
from datetime import datetime
from deep_translator import GoogleTranslator
import threading
import telebot
import feedparser
import google.generativeai as genai

# --- CONFIG ---
TOKEN = os.environ.get("TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "YOUR_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# --- LOG ---
def log(msg, level="INFO"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

# --- DATA ---
stock_news_store = []
rss_news_store = []
sent_links = set()
sent_stock = set()

# --- HELPERS ---
def clean(text):
    return re.sub(r'\s+', ' ', text.strip().lower())

def translate(text):
    try:
        return GoogleTranslator(source='auto', target='te').translate(text)
    except:
        return text

def send_long_message(chat_id, text):
    for i in range(0, len(text), 4000):
        try:
            bot.send_message(chat_id, text[i:i+4000])
        except Exception as e:
            log(f"❌ Telegram send error: {e}", "ERROR")

# --- RSS FEEDS ---
RSS_FEEDS = {
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "CNBC": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml",
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "NDTV News": "https://feeds.feedburner.com/ndtvnews-top-stories",
}

# --- FETCH RSS ---
def fetch_rss():
    log("🌍 RSS checking started...")

    for name, url in RSS_FEEDS.items():
        try:
            log(f"🔗 Fetching: {name}")

            # 🔥 ఇక్కడ add చేయాలి
            if name == "CNBC":
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/xml"
                }
            else:
                headers = {"User-Agent": "Mozilla/5.0"}

            res = requests.get(url, headers=headers, timeout=10)

            if res.status_code != 200:
                log(f"❌ HTTP Error {name}: {res.status_code}", "ERROR")
                continue

            feed = feedparser.parse(res.content)

            if not feed.entries:
                log(f"⚠️ Empty feed: {name}", "ERROR")
                continue

            log(f"📊 {name} entries: {len(feed.entries)}")

            new_count = 0

            for entry in feed.entries[:10]:
                link = entry.get("link", "")

                if not link or link in sent_links:
                    continue

                sent_links.add(link)
                new_count += 1

                title = entry.get("title", "")
                summary = (
                    entry.get("summary") or
                    entry.get("description") or
                    entry.get("content", [{}])[0].get("value", "")
                )

                clean_desc = re.sub('<[^>]+>', '', summary)
                clean_desc = clean_desc.replace("\n", " ").strip()

                rss_news_store.append(title + " " + clean_desc)

                msg = f"🌐 {name}\n\n{translate(title)}\n\n{translate(clean_desc[:300])}\n\n{link}"

                send_long_message(CHAT_ID, msg)

                log(f"✅ Sent: {title[:60]}")
                time.sleep(1)

            if new_count == 0:
                log(f"😴 No new news from {name}")
            else:
                log(f"🆕 {new_count} new from {name}")

        except Exception as e:
            log(f"❌ RSS Error {name}: {e}", "ERROR")

# --- SCANX ---
def fetch_scanx():
    log("🔍 ScanX checking...")

    scraper = cloudscraper.create_scraper()
    url = "https://scanx.trade/stock-market-news/news-feeds"

    try:
        res = scraper.get(url, timeout=15)
        matches = re.findall(r'>([^<>]{50,300})<', res.text)

        log(f"📊 ScanX found: {len(matches)}")

        new_count = 0

        for news in matches:
            text = news.strip()

            if len(text) < 80:
                continue

            key = clean(text)

            if key in sent_stock:
                continue

            sent_stock.add(key)
            stock_news_store.append(text)
            new_count += 1

            msg = f"🚀 ScanX\n\n{text}\n\n{translate(text)}"
            send_long_message(CHAT_ID, msg)

            log(f"✅ Sent ScanX: {text[:60]}")
            time.sleep(2)

        if new_count == 0:
            log("😴 No new ScanX news")
        else:
            log(f"🆕 {new_count} new ScanX news")

    except Exception as e:
        log(f"❌ ScanX Error: {e}", "ERROR")

# --- AI SUMMARY ---
@bot.message_handler(commands=['summary'])
def summary(message):
    if not stock_news_store and not rss_news_store:
        bot.reply_to(message, "❌ వార్తలు లేవు")
        return

    bot.send_message(CHAT_ID, "🔍 Gemini AI విశ్లేషణ జరుగుతోంది...")

    stock = "\n".join(stock_news_store[-70:])
    rss = "\n".join(rss_news_store[-70:])

    prompt = f"""
Structure the response into these 3 specific sections:

1. 🚀 Stock Market & Corporate Analysis (ScanX Data)
2. 🇮🇳 National Business & Policy News (RSS Data)
3. 🌍 International Market & Global Trends (RSS Data)

Provide detailed analysis in Telugu.
Give clear actionable insights and highlight important stocks if any.

DATA:
STOCK: {stock}
RSS: {rss}
"""

    try:
        response = model.generate_content(prompt)
        result = response.text

        send_long_message(CHAT_ID, result)

        log("✅ Summary sent")

    except Exception as e:
        log(f"❌ AI Error: {e}", "ERROR")

# --- LIST ---
@bot.message_handler(commands=['list'])
def list_news(message):
    if not stock_news_store:
        bot.reply_to(message, "❌ data లేదు")
        return

    msg = ""
    for i, n in enumerate(stock_news_store[-50:], 1):
        msg += f"{i}. {n}\n\n"

    send_long_message(CHAT_ID, msg)

# --- LOOP ---
def loop():
    while True:
        log("🔁 New cycle started")
        try:
            fetch_scanx()
            fetch_rss()
            log("✅ Cycle completed")
        except Exception as e:
            log(f"❌ Loop Error: {e}", "ERROR")
        time.sleep(120)

# --- BOT ---
def start_bot():
    while True:
        try:
            log("🤖 Bot polling...")
            bot.infinity_polling()
        except Exception as e:
            log(f"❌ Polling Error: {e}", "ERROR")
            time.sleep(5)

# --- MAIN ---
if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=start_bot, daemon=True).start()

    log("🚀 Bot Started Successfully")

    while True:
        time.sleep(60)