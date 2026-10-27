import time, random, os, json, threading
from urllib.parse import urlparse, parse_qs, urlencode
from flask import Flask
import html

SEARCH_TEXT = os.getenv("SEARCH_TEXT", "nintendo switch")
DOMAIN = os.getenv("DOMAIN", "it")
VINTED_URL = os.getenv("VINTED_URL", "")  # es: https://www.vinted.it/catalog?catalog[]=3025&price_from=10&price_to=80&order=newest_first
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK", "")
STORAGE_FILE = "/tmp/vinted_first.json"

try:
    from curl_cffi import requests as c_requests
    USE_CURL = True
    print("✅ Usando curl_cffi per bypassare blocco Vinted")
except Exception as e:
    import requests as c_requests
    USE_CURL = False
    print(f"⚠️ curl_cffi non disponibile ({e})")

import requests as std_requests

app = Flask(__name__)

last_check_info = {"last_id": None, "last_title": "", "last_check": "", "current_filter": ""}

def build_api_url():
    ts = int(time.time())
    base = f"https://www.vinted.{DOMAIN}/api/v2/catalog/items"
    
    # Se hai messo VINTED_URL completo, lo parsiamo
    if VINTED_URL:
        parsed = urlparse(VINTED_URL)
        qs = parse_qs(parsed.query)
        # parse_qs ritorna liste
        api_params = {}
        # Converti catalog[] -> catalog_ids
        if "catalog[]" in qs:
            api_params["catalog_ids"] = ",".join(qs["catalog[]"])
        if "catalog_ids" in qs:
            api_params["catalog_ids"] = ",".join(qs["catalog_ids"])
        if "catalog" in qs:
            api_params["catalog_ids"] = ",".join(qs["catalog"])
        # Altri filtri comuni
        for key in ["price_from", "price_to", "currency", "search_text", "order", "brand_ids", "size_ids", "status_ids", "color_ids"]:
            if key in qs:
                api_params[key] = qs[key][0]
        # Forza newest_first e per_page
        api_params["order"] = "newest_first"
        api_params["per_page"] = "5"
        api_params["time"] = str(ts)
        # Se VINTED_URL è impostato, NON aggiungere search_text di fallback
        # L'utente vuole filtrare solo per categoria/prezzo. Aggiungi search_text solo se è già nel VINTED_URL
        # Se invece vuoi anche search_text, mettilo direttamente nel VINTED_URL: &search_text=nintendo+switch
        
        query = urlencode(api_params, doseq=True)
        url = f"{base}?{query}"
        referer = VINTED_URL
        print(f"[{time.strftime('%H:%M:%S')}] 🔗 Uso filtro CUSTOM da VINTED_URL")
        print(f"   API URL: {url}")
        return url, referer
    else:
        # Vecchio metodo solo search_text
        params = {
            "search_text": SEARCH_TEXT,
            "order": "newest_first",
            "per_page": "5",
            "time": str(ts)
        }
        query = urlencode(params)
        url = f"{base}?{query}"
        referer = f"https://www.vinted.{DOMAIN}/catalog?search_text={SEARCH_TEXT.replace(' ','+')}&order=newest_first"
        print(f"[{time.strftime('%H:%M:%S')}] 🔗 Uso filtro semplice SEARCH_TEXT='{SEARCH_TEXT}'")
        return url, referer

def fetch_first():
    url, referer = build_api_url()
    last_check_info["current_filter"] = url
    
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "it-IT,it;q=0.9",
        "Referer": referer,
        "Origin": f"https://www.vinted.{DOMAIN}",
    }
    try:
        kw = {"headers": h, "timeout": 20}
        if USE_CURL:
            kw["impersonate"] = "chrome124"
        r = c_requests.get(url, **kw)
        print(f"[{time.strftime('%H:%M:%S')}] 🌐 Status {r.status_code}")
        if r.status_code != 200:
            print(f"   Body: {r.text[:400]}")
            return None
        data = r.json()
        items = data.get('items') or []
        if not items:
            print(f"⚠️ Nessun risultato con questo filtro!")
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
            "photo": photo,
            "api_url": url
        }
    except Exception as e:
        print(f"❌ Errore fetch: {e}")
        import traceback; traceback.print_exc()
        return None

def send_discord(item):
    if not WEBHOOK_URL:
        print("⚠️ WEBHOOK non impostato")
        return
    embed = {
        "title": f"🔔 NUOVO IN ALTO!\n{item['title'][:200]}",
        "url": item['url'],
        "description": f"**Prezzo:** {item['price']}€\n**Filtro:** `{VINTED_URL[:80] if VINTED_URL else SEARCH_TEXT}`\n\n🔗 [CLICCA QUI PER COMPRARE]({item['url']})",
        "color": 0x09B1BA,
        "image": {"url": item['photo']} if item['photo'] else None,
        "footer": {"text": f"ID {item['id']} | {item['api_url'][:60]}"}
    }
    try:
        std_requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print(f"✅ Inviato su Discord {item['id']}")
    except Exception as e:
        print(f"Discord error {e}")

@app.route("/")
def home():
    filtro_display = html.escape(VINTED_URL if VINTED_URL else SEARCH_TEXT)
    api_display = html.escape(last_check_info['current_filter'])
    title_display = html.escape(last_check_info['last_title'] or "")
    return f"""
    <h1>Vinted Bot Online ✅</h1>
    <p><b>Filtro attivo:</b> {filtro_display}</p>
    <p><b>Domain:</b> {html.escape(DOMAIN)}</p>
    <p><b>Ultimo check:</b> {html.escape(last_check_info['last_check'])}</p>
    <p><b>Ultimo ID:</b> {html.escape(str(last_check_info['last_id']))} - {title_display}</p>
    <p><b>API URL:</b> {api_display}</p>
    <p><b>Stato:</b> {"❌ Nessun risultato per questo filtro! Prova a togliere catalog o prezzo" if last_check_info['last_id'] is None and last_check_info['last_check'] else "✅ OK"}</p>
    <p><a href="/health">health</a></p>
    <hr>
    <h3>Come cambiare filtro:</h3>
    <p>Vai su Vinted, filtra per prezzo, categoria, ecc., copia l'URL tipo:<br>
    <code>https://www.vinted.it/catalog?price_from=10&price_to=80&order=newest_first</code><br>
    Incollalo in Render > Environment > VINTED_URL > Save</p>
    <p><b>Se vedi None:</b> il filtro è troppo restrittivo, prova senza catalog[]=3025</p>
    """

@app.route("/health")
def health():
    return "OK", 200

def loop_monitor():
    print(f"🚀 Avvio monitor - DOMAIN=vinted.{DOMAIN} VINTED_URL={VINTED_URL or SEARCH_TEXT}")
    last_id = None
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE) as f:
                last_id = json.load(f).get('id')
                print(f"Riprendo da ID salvato: {last_id}")
        except: pass

    if WEBHOOK_URL:
        try:
            msg = f"✅ Bot avviato!\n**Filtro:** {VINTED_URL if VINTED_URL else SEARCH_TEXT}\nSu vinted.{DOMAIN} - controllo ogni 30s"
            std_requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10)
        except: pass

    while True:
        try:
            first = fetch_first()
            now = time.strftime('%H:%M:%S')
            last_check_info["last_check"] = now
            if first:
                last_check_info["last_id"] = first["id"]
                last_check_info["last_title"] = first["title"]
                print(f"[{now}] 🔍 Primo: {first['id']} | {first['title'][:60]} | {first['price']}€")
                if first['id'] != last_id:
                    print(f"[{now}] 🚨 CAMBIO RILEVATO! {last_id} -> {first['id']}")
                    send_discord(first)
                    last_id = first['id']
                    try:
                        with open(STORAGE_FILE,'w') as f:
                            json.dump({"id": last_id}, f)
                    except: pass
                else:
                    print(f"[{now}] 😴 Nessun cambio")
            else:
                print(f"[{now}] ⚠️ Nessun dato")
        except Exception as e:
            print(f"🔥 Errore loop: {e}")
        time.sleep(random.randint(25,40))

threading.Thread(target=loop_monitor, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
