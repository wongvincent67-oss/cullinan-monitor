"""
匯璽 Cullinan West 350呎成交監察
每日自動查差估署數據，有 $8,300萬或以上成交即發 Telegram 通知
"""

import requests
import json
import os
from datetime import datetime, timedelta

# ─── 設定（從環境變數讀取，唔好直接寫入代碼）──────────────
TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]

ESTATE_NAME    = "匯璽"
TARGET_SQF_MIN = 320
TARGET_SQF_MAX = 380
ALERT_PRICE    = int(os.environ.get("ALERT_PRICE", "83000000"))

SEEN_FILE = "/data/seen_transactions.json"   # Railway volume 持久存儲
# ────────────────────────────────────────────────────────


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }, timeout=10)
    r.raise_for_status()
    print("[✓] Telegram 通知已發送")


def load_seen() -> set:
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen: set):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def fetch_transactions() -> list:
    date_from = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")
    url = "https://www.rvd.gov.hk/datagovhk/transaction_records_en.json"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        all_records = r.json()
    except Exception as e:
        print(f"[!] 無法取得差估署數據：{e}")
        return []

    results = []
    for record in all_records:
        name = record.get("Building Name", "") + record.get("Estate Name", "")
        if ESTATE_NAME not in name:
            continue
        try:
            sqft = float(record.get("Saleable Area (sq. ft.)", 0))
        except (ValueError, TypeError):
            sqft = 0
        if not (TARGET_SQF_MIN <= sqft <= TARGET_SQF_MAX):
            continue
        if record.get("Contract Date", "") < date_from:
            continue
        results.append(record)

    return results


def format_price(price: float) -> str:
    if price >= 1e8:
        return f"${price/1e8:.2f}億"
    return f"${price/1e6:.0f}百萬"


def check_and_notify():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 開始檢查匯璽成交...")
    seen = load_seen()
    transactions = fetch_transactions()

    if not transactions:
        print("[!] 未找到相關成交記錄")
        return

    new_alerts = []
    for tx in transactions:
        try:
            price = float(str(tx.get("Price", "0")).replace(",", ""))
        except (ValueError, TypeError):
            continue
        if price < ALERT_PRICE:
            continue
        tx_id = f"{tx.get('Contract Date')}-{tx.get('Floor')}-{tx.get('Unit')}-{price}"
        if tx_id in seen:
            continue
        new_alerts.append((tx, price, tx_id))

    if not new_alerts:
        print("[✓] 無新的觸發警報成交")
        return

    for tx, price, tx_id in new_alerts:
        sqft = tx.get("Saleable Area (sq. ft.)", "N/A")
        try:
            psf = f"${round(price / float(sqft)):,}"
        except (ValueError, TypeError):
            psf = "N/A"

        msg = (
            f"🔔 <b>匯璽 Cullinan West 成交警報</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📅 成交日期：{tx.get('Contract Date', 'N/A')}\n"
            f"🏢 樓層／單位：{tx.get('Floor', 'N/A')}樓 {tx.get('Unit', 'N/A')}室\n"
            f"📐 實用面積：{sqft} 呎\n"
            f"💰 成交價：<b>{format_price(price)}</b>\n"
            f"📊 呎價：{psf} / 呎\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 超過警報閾值 {format_price(ALERT_PRICE)}"
        )

        send_telegram(msg)
        seen.add(tx_id)
        print(f"[✓] 警報：{tx.get('Contract Date')} {tx.get('Floor')}樓 {format_price(price)}")

    save_seen(seen)


if __name__ == "__main__":
    check_and_notify()
