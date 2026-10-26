
import time, random, os, json, sys
try:
    from curl_cffi import requests
    USE_CURL=True
except:
    import requests
    USE_CURL=False

# --- CONFIG ---
SEARCH_TEXT = os.getenv("SEARCH_TEXT", "nintendo switch")
DOMAIN = os.getenv("DOMAIN", "it")
BASE_INTERVAL = int(os.getenv("INTERVAL", "30"))
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK", "")  # <--- metti qui il webhook su Render > Environment
STORAGE_FILE = "/tmp/vinted_first.json"  # su Render /tmp è scrivibile

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
            print(f"Status {r.status_code}, riprovo...")
            return None
        data = r.json()
        items = data.get('items') or []
        if not items:
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
        print(f"Errore fetch: {e}")
        return None

def load():
    if os.path.exists(STORAGE_FILE):
        try:
            return json.load(open(STORAGE_FILE))
        except: pass
    return None

def save(o):
    json.dump(o, open(STORAGE_FILE,'w'))

def send_discord(cur, prev):
    if not WEBHOOK_URL:
        print("⚠️ WEBHOOK non configurato - setta DISCORD_WEBHOOK su Render")
        return
    embed = {
        "title": "🔔 NUOVO IN ALTO SU VINTED!",
        "description": f"**{cur['title']}**\n💰 {cur['price']}€\n\n🔗 [CLICCA QUI PER COMPRARE]({cur['url']})\n\nPrima: {prev['title'][:80] if prev else 'N/A'}",
        "color": 0x09B1BA,
        "url": cur['url'],
        "footer": {"text": f"vinted.{DOMAIN} | filtro: {SEARCH_TEXT}"}
    }
    if cur['photo']:
        embed["thumbnail"] = {"url": cur['photo']}
    try:
        r = requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print(f"Discord inviato: {r.status_code}")
    except Exception as e:
        print(f"Errore Discord: {e}")

print(f"Avvio monitor Vinted - filtro: '{SEARCH_TEXT}' su vinted.{DOMAIN} ogni ~{BASE_INTERVAL}s")
stored = load()
if stored:
    print(f"Riprendo da: {stored['title'][:60]}")

while True:
    time.sleep(random.randint(max(5,BASE_INTERVAL-5), BASE_INTERVAL+5))
    cur = fetch_first()
    if not cur:
        continue
    print(f"[{time.strftime('%H:%M:%S')}] Check: {cur['id']} - {cur['title'][:50]}")
    if not stored:
        print("Salvo primo riferimento")
        save(cur)
        stored = cur
        continue
    if stored['id'] != cur['id'] or stored['title'].strip().lower() != cur['title'].strip().lower():
        print(f"🚨 CAMBIO RILEVATO!")
        print(f"  Prima: {stored['title']}")
        print(f"  Ora: {cur['title']}")
        send_discord(cur, stored)
        save(cur)
        stored = cur
