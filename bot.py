import time, random, os, json, threading
from flask import Flask
import requests

SEARCH_TEXT = os.getenv("SEARCH_TEXT", "nintendo switch")
DOMAIN = os.getenv("DOMAIN", "it")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK", "")
STORAGE_FILE = "/tmp/vinted_first.json"

app = Flask(__name__)

@app.route("/")
def home():
    return f"Vinted bot online - monitoring: {SEARCH_TEXT} - last check {time.strftime('%H:%M:%S')}"

@app.route("/health")
def health():
    return "OK", 200

def fetch_first():
    ts = int(time.time())
    url = f"https://www.vinted.{DOMAIN}/api/v2/catalog/items?search_text={SEARCH_TEXT}&order=newest_first&per_page=5&time={ts}"
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": f"https://www.vinted.{DOMAIN}/catalog?search_text={SEARCH_TEXT.replace(' ','+')}&order=newest_first"
    }
    try:
        r = requests.get(url, headers=h, timeout=20)
        if r.status_code != 200:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Status {r.status_code}")
            return None
        data = r.json()
        items = data.get('items') or []
        if not items:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Nessun risultato per '{SEARCH_TEXT}'")
            return None
        f = items[0]
        price = f.get('price') or f.get('price_numeric') or ""
        if isinstance(price, dict):
            price = price.get('amount') or price.get('text') or ""
        photo = (f.get('photo') or {}).get('url')
        if not photo and f.get('photos'):
            photo = f['photos'][0].get('url')
        return {
            "id": str(f.get('id')),
            "title": f.get('title','Senza titolo'),
            "url": f.get('url') or f"https://www.vinted.{DOMAIN}/items/{f.get('id')}",
            "price": price,
            "photo": photo
        }
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Errore fetch: {e}")
        return None

def send_discord(item):
    if not WEBHOOK_URL:
        return
    embed = {
        "title": f"\u0001f514 NUOVO IN ALTO SU VINTED!\n{item['title'][:200]}",
        "url": item['url'],
        "description": f"**Prezzo:** {item['price']}\n**Ricerca:** `{SEARCH_TEXT}`\n[Apri su Vinted]({item['url']})",
        "color": 0x09B1BA,
        "image": {"url": item['photo']} if item['photo'] else None,
        "footer": {"text": f"ID {item['id']} | vinted.{DOMAIN}"}
    }
    try:
        requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print(f"[{time.strftime('%H:%M:%S')}] \u2705 Inviato su Discord ID {item['id']} - {item['title'][:50]}")
    except Exception as e:
        print(f"Discord error {e}")

def loop_monitor():
    print(f"[{time.strftime('%H:%M:%S')}] \u0001f680 Avvio monitor Vinted - filtro: '{SEARCH_TEXT}' su vinted.{DOMAIN}")
    last_id = None
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE) as f:
                last_id = json.load(f).get('id')
                print(f"Ultimo ID salvato: {last_id}")
        except: pass

    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": f"\u2705 Bot avviato! Monitoro **{SEARCH_TEXT}** su vinted.{DOMAIN} - ti avviso solo se cambia il primo annuncio. Controllo ogni ~30s."}, timeout=10)
        except: pass

    while True:
        first = fetch_first()
        now = time.strftime('%H:%M:%S')
        if first:
            print(f"[{now}] \u0001f50d Check: primo ID {first['id']} | {first['title'][:60]} | {first['price']}")
            if first['id'] != last_id:
                print(f"[{now}] \u0001f6a8 CAMBIO RILEVATO! {last_id} -> {first['id']}")
                send_discord(first)
                last_id = first['id']
                try:
                    with open(STORAGE_FILE,'w') as f:
                        json.dump({"id": last_id}, f)
                except: pass
            else:
                print(f"[{now}] \U0001f634 Nessun cambio, dormo 30s...")
        else:
            print(f"[{now}] \u26a0\ufe0f Nessun dato, riprovo tra poco")

        time.sleep(random.randint(25,40))

threading.Thread(target=loop_monitor, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
