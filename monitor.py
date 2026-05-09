"""
匯璽 Cullinan West 350呎成交監察
來源：中原地產 → 美聯物業 → 差估署（備用）
有 $8,300萬或以上成交即發 Telegram 通知
每日早上9點自動執行
"""

import requests
import json
import os
import re
from datetime import datetime, timedelta

# ─── 設定 ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
ALERT_PRICE        = int(os.environ.get("ALERT_PRICE", "83000000"))

SEEN_FILE  = "/data/seen_transactions.json"
SQF_MIN    = 320
SQF_MAX    = 380
# ────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
}


# ─── 工具函數 ─────────────────────────────────────────────

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


def format_price(price: float) -> str:
    if price >= 1e8:
        return f"${price/1e8:.2f}億"
    return f"${price/1e6:.0f}百萬"


def make_tx_id(source: str, date: str, floor: str, unit: str, price: float) -> str:
    return f"{source}-{date}-{floor}-{unit}-{price}"


def build_alert_msg(date, floor, unit, sqft, price, source) -> str:
    try:
        psf = f"${round(price / float(sqft)):,}"
    except (ZeroDivisionError, TypeError, ValueError):
        psf = "N/A"
    return (
        f"🔔 <b>匯璽 Cullinan West 成交警報</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📅 成交日期：{date}\n"
        f"🏢 樓層／單位：{floor}樓 {unit}室\n"
        f"📐 實用面積：{sqft} 呎\n"
        f"💰 成交價：<b>{format_price(price)}</b>\n"
        f"📊 呎價：{psf} / 呎\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚠️ 超過警報閾值 {format_price(ALERT_PRICE)}\n"
        f"📌 來源：{source}"
    )


# ─── 中原地產 ─────────────────────────────────────────────

def fetch_centaline() -> list:
    print("[i] 查詢中原地產...")
    results = []

    # 嘗試中原 API
    try:
        url = "https://hk.centanet.com/api/transaction/v2/list"
        params = {
            "estate_id": "1823",   # 匯璽 Cullinan West
            "page": 1,
            "page_size": 50,
            "trans_type": "S",
        }
        r = requests.get(url, headers={**HEADERS, "Referer": "https://hk.centanet.com/"}, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        raw = data.get("data", {}).get("list", [])
        print(f"[i] 中原 API：取得 {len(raw)} 筆")
        for tx in raw:
            parsed = parse_centaline(tx)
            if parsed:
                results.append(parsed)
    except Exception as e:
        print(f"[!] 中原 API 失敗：{e}")

    # 備用：中原網頁搜尋
    if not results:
        try:
            url = "https://hk.centanet.com/api/transaction/search"
            payload = {"keyword": "匯璽", "trans_type": "S", "page": 1, "page_size": 30}
            r = requests.post(url, headers={**HEADERS, "Referer": "https://hk.centanet.com/"}, json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            raw = data.get("data", {}).get("list", [])
            print(f"[i] 中原搜尋備用：取得 {len(raw)} 筆")
            for tx in raw:
                parsed = parse_centaline(tx)
                if parsed:
                    results.append(parsed)
        except Exception as e:
            print(f"[!] 中原備用都失敗：{e}")

    return results


def parse_centaline(tx: dict) -> dict | None:
    try:
        sqft = float(tx.get("saleable_area") or tx.get("saleableArea") or 0)
        if not (SQF_MIN <= sqft <= SQF_MAX):
            return None
        price_raw = tx.get("price") or tx.get("trans_price") or 0
        price = float(str(price_raw).replace(",", ""))
        if price < 1000:
            price *= 10000
        return {
            "date":   tx.get("trans_date") or tx.get("transDate") or "N/A",
            "floor":  tx.get("floor") or tx.get("floor_name") or "N/A",
            "unit":   tx.get("unit") or tx.get("unit_name") or "N/A",
            "sqft":   sqft,
            "price":  price,
            "source": "中原地產",
        }
    except (ValueError, TypeError):
        return None


# ─── 美聯物業 ─────────────────────────────────────────────

def fetch_midland() -> list:
    print("[i] 查詢美聯物業...")
    results = []

    # 美聯成交 API
    # estate_no 係匯璽嘅代碼，用搜尋先搵
    try:
        # 搜尋匯璽 estate code
        search_url = "https://www.midland.com.hk/api/property/estate/search"
        sr = requests.get(search_url, headers={**HEADERS, "Referer": "https://www.midland.com.hk/"},
                          params={"keyword": "匯璽", "lang": "zh"}, timeout=10)
        sr.raise_for_status()
        estates = sr.json().get("data", [])
        estate_code = None
        for e in estates:
            name = e.get("name_tc", "") + e.get("name_en", "")
            if "匯璽" in name or "CULLINAN WEST" in name.upper():
                estate_code = e.get("estate_no") or e.get("code")
                break

        if estate_code:
            tx_url = "https://www.midland.com.hk/api/transaction/list"
            r = requests.get(tx_url, headers={**HEADERS, "Referer": "https://www.midland.com.hk/"},
                             params={"estate_no": estate_code, "type": "S", "page": 1, "limit": 50}, timeout=15)
            r.raise_for_status()
            raw = r.json().get("data", {}).get("list", [])
            print(f"[i] 美聯 API：取得 {len(raw)} 筆")
            for tx in raw:
                parsed = parse_midland(tx)
                if parsed:
                    results.append(parsed)
        else:
            print("[!] 美聯：找不到匯璽 estate code，嘗試直接查詢")
            raise ValueError("No estate code")

    except Exception as e:
        print(f"[!] 美聯 API 失敗：{e}，嘗試備用...")
        # 備用：直接查美聯成交頁
        try:
            url = "https://www.midland.com.hk/zh-hk/transaction/buy/cullinan-west"
            r = requests.get(url, headers={**HEADERS, "Referer": "https://www.midland.com.hk/"}, timeout=15)
            r.raise_for_status()
            # 抽 JSON-LD 或 next data
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                tx_list = []
                def find_tx(obj):
                    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                        if any(k in obj[0] for k in ["saleableArea", "price", "transDate"]):
                            tx_list.extend(obj)
                    elif isinstance(obj, dict):
                        for v in obj.values():
                            find_tx(v)
                find_tx(data)
                print(f"[i] 美聯網頁備用：取得 {len(tx_list)} 筆")
                for tx in tx_list:
                    parsed = parse_midland(tx)
                    if parsed:
                        results.append(parsed)
        except Exception as e2:
            print(f"[!] 美聯備用都失敗：{e2}")

    return results


def parse_midland(tx: dict) -> dict | None:
    try:
        sqft = float(
            tx.get("saleable_area") or tx.get("saleableArea") or
            tx.get("net_area") or tx.get("netArea") or 0
        )
        if not (SQF_MIN <= sqft <= SQF_MAX):
            return None
        price_raw = (
            tx.get("price") or tx.get("trans_price") or
            tx.get("transPrice") or 0
        )
        price = float(str(price_raw).replace(",", ""))
        if price < 1000:
            price *= 10000
        return {
            "date":   (tx.get("trans_date") or tx.get("transDate") or
                       tx.get("date") or "N/A"),
            "floor":  (tx.get("floor") or tx.get("floorName") or
                       tx.get("floor_name") or "N/A"),
            "unit":   (tx.get("unit") or tx.get("unitName") or
                       tx.get("unit_name") or "N/A"),
            "sqft":   sqft,
            "price":  price,
            "source": "美聯物業",
        }
    except (ValueError, TypeError):
        return None


# ─── 差估署（最終備用）────────────────────────────────────

def fetch_rvd() -> list:
    print("[i] 查詢差估署（備用）...")
    results = []
    date_from = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")
    try:
        r = requests.get("https://www.rvd.gov.hk/datagovhk/transaction_records_en.json", timeout=30)
        r.raise_for_status()
        records = r.json()
        for record in records:
            name = record.get("Building Name", "") + record.get("Estate Name", "")
            if "匯璽" not in name and "CULLINAN" not in name.upper():
                continue
            try:
                sqft = float(record.get("Saleable Area (sq. ft.)", 0))
            except (ValueError, TypeError):
                continue
            if not (SQF_MIN <= sqft <= SQF_MAX):
                continue
            if record.get("Contract Date", "") < date_from:
                continue
            try:
                price = float(str(record.get("Price", "0")).replace(",", ""))
            except (ValueError, TypeError):
                continue
            results.append({
                "date":   record.get("Contract Date", "N/A"),
                "floor":  record.get("Floor", "N/A"),
                "unit":   record.get("Unit", "N/A"),
                "sqft":   sqft,
                "price":  price,
                "source": "差估署",
            })
        print(f"[i] 差估署：取得 {len(results)} 筆匯璽350呎記錄")
    except Exception as e:
        print(f"[!] 差估署失敗：{e}")
    return results


# ─── 主程式 ───────────────────────────────────────────────

def check_and_notify():
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M}] ══ 開始檢查匯璽成交 ══")
    seen = load_seen()

    # 收集三個來源，去重後合併
    all_tx = []
    dedup = set()

    for tx in fetch_centaline() + fetch_midland() + fetch_rvd():
        key = f"{tx['date']}-{tx['floor']}-{tx['unit']}-{tx['price']}"
        if key not in dedup:
            dedup.add(key)
            all_tx.append(tx)

    print(f"[i] 合併後共 {len(all_tx)} 筆350呎記錄")

    new_alerts = []
    for tx in all_tx:
        if tx["price"] < ALERT_PRICE:
            continue
        tx_id = make_tx_id(tx["source"], tx["date"], tx["floor"], tx["unit"], tx["price"])
        if tx_id in seen:
            continue
        new_alerts.append((tx, tx_id))

    if not new_alerts:
        print("[✓] 無新的觸發警報成交")
        save_seen(seen)
        return

    for tx, tx_id in new_alerts:
        msg = build_alert_msg(
            tx["date"], tx["floor"], tx["unit"],
            tx["sqft"], tx["price"], tx["source"]
        )
        send_telegram(msg)
        seen.add(tx_id)
        print(f"[✓] 警報（{tx['source']}）：{tx['date']} {tx['floor']}樓 {format_price(tx['price'])}")

    save_seen(seen)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] ══ 完成 ══\n")


if __name__ == "__main__":
    check_and_notify()
