
import time, random, os, json, threading
from flask import Flask
try:
    from curl_cffi import requests
    USE_CURL=True
except:
    import requests
    USE_CURL=False

SEARCH_TEXT = os.getenv("SEARCH_TEXT", "nintendo switch")
DOMAIN = os.getenv("DOMAIN", "it")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK", "")
STORAGE_FILE = "/tmp/vinted_first.json"

app = Flask(__name__)

@app.route("/")
def home():
    return "Vinted bot online - monitoring: " + SEARCH_TEXT

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
        kw = {"headers": h, "timeout": 20}
        if USE_CURL:
            kw["impersonate"] = "chrome124"
        r = requests.get(url, **kw)
        if r.status_code != 200:
            print(f"Status {r.status_code}")
            return None
        data = r.json()
        items = data.get('items') or []
        if not items: return None
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
        print(f"Errore fetch: {e}")
        return None

def send_discord(item):
    if not WEBHOOK_URL: return
    embed = {
        "title": f"🔔 NUOVO IN ALTO SU VINTED!\n{item['title'][:200]}",
        "url": item['url'],
        "description": f"**Prezzo:** {item['price']}\n**Ricerca:** `{SEARCH_TEXT}`\n[Apri su Vinted]({item['url']})",
        "color": 0x09B1BA,
        "image": {"url": item['photo']} if item['photo'] else None,
        "footer": {"text": f"ID {item['id']} | vinted.{DOMAIN}"}
    }
    try:
        requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print(f"Inviato {item['id']}")
    except Exception as e:
        print(f"Discord error {e}")

def loop_monitor():
    print(f"Avvio monitor Vinted - filtro: '{SEARCH_TEXT}' su vinted.{DOMAIN}")
    # carica ultimo id
    last_id = None
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE) as f:
                last_id = json.load(f).get('id')
        except: pass
    
    # invio avvio
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": f"✅ Bot avviato! Monitoro **{SEARCH_TEXT}** su vinted.{DOMAIN} - ti avviso solo se cambia il primo annuncio."}, timeout=10)
        except: pass

    while True:
        first = fetch_first()
        if first and first['id'] != last_id:
            print(f"Cambio rilevato: {last_id} -> {first['id']}")
            send_discord(first)
            last_id = first['id']
            try:
                with open(STORAGE_FILE,'w') as f:
                    json.dump({"id": last_id}, f)
            except: pass
        time.sleep(random.randint(25,40))

# Avvia monitor in background
threading.Thread(target=loop_monitor, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
