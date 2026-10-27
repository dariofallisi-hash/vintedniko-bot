import time, random, os, json, threading
from urllib.parse import urlparse, parse_qs, urlencode
from flask import Flask
import html

SEARCH_TEXT = os.getenv("SEARCH_TEXT", "")
DOMAIN = os.getenv("DOMAIN", "it")
VINTED_URL = os.getenv("VINTED_URL", "")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK", "")
STORAGE_FILE = "/tmp/vinted_first.json"

try:
    from curl_cffi import requests as c_requests
    USE_CURL = True
    print("✅ Usando curl_cffi")
except Exception as e:
    import requests as c_requests
    USE_CURL = False
    print(f"⚠️ curl_cffi non disponibile {e}")

import requests as std_requests

app = Flask(__name__)
last_check_info = {"last_id": None, "last_title": "", "last_check": "", "current_filter": "", "debug": ""}

# Sessione globale per mantenere i cookie di Vinted
session = None

def get_session():
    global session
    if session is None:
        try:
            session = c_requests.Session()
            # Prendi i cookie prima - fondamentale per Vinted
            print("🍪 Prendo cookie da vinted.it...")
            kw = {"timeout": 20}
            if USE_CURL:
                kw["impersonate"] = "chrome131"
            # Visita homepage per ottenere cookie anonimi
            session.get(f"https://www.vinted.{DOMAIN}/", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml"
            }, **kw)
            print(f"✅ Cookie ottenuti: {len(session.cookies)}")
        except Exception as e:
            print(f"❌ Errore cookie: {e}")
            session = c_requests.Session()
    return session

def build_api_url():
    ts = int(time.time())
    base = f"https://www.vinted.{DOMAIN}/api/v2/catalog/items"
    
    if VINTED_URL:
        parsed = urlparse(VINTED_URL)
        qs = parse_qs(parsed.query)
        api_params = {}
        if "catalog[]" in qs:
            api_params["catalog_ids"] = ",".join(qs["catalog[]"])
        if "catalog_ids" in qs:
            api_params["catalog_ids"] = ",".join(qs["catalog_ids"])
        for key in ["price_from", "price_to", "currency", "search_text", "order", "brand_ids", "size_ids"]:
            if key in qs:
                api_params[key] = qs[key][0]
        api_params["order"] = "newest_first"
        api_params["per_page"] = "20"
        api_params["time"] = str(ts)
        # Vinted vuole almeno search_text o catalog_ids, altrimenti da 404
        # Se l'utente ha messo solo price_from/to senza categoria e senza testo, aggiungiamo search_text generico
        if "search_text" not in api_params and "catalog_ids" not in api_params:
            api_params["search_text"] = "nike"
        # NON aggiungere search_text se non c'è nel link
        query = urlencode(api_params, doseq=True)
        url = f"{base}?{query}"
        referer = VINTED_URL
        print(f"🔗 Filtro CUSTOM: {url}")
        return url, referer
    else:
        params = {
            "search_text": SEARCH_TEXT or "nike",
            "order": "newest_first",
            "per_page": "20",
            "time": str(ts)
        }
        query = urlencode(params)
        url = f"{base}?{query}"
        referer = f"https://www.vinted.{DOMAIN}/catalog?order=newest_first"
        print(f"🔗 Filtro fallback SEARCH_TEXT='{SEARCH_TEXT}'")
        return url, referer

def fetch_first():
    url, referer = build_api_url()
    last_check_info["current_filter"] = url
    
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Origin": f"https://www.vinted.{DOMAIN}",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        sess = get_session()
        kw = {"headers": h, "timeout": 25}
        if USE_CURL:
            kw["impersonate"] = "chrome131"
        
        r = sess.get(url, **kw)
        print(f"[{time.strftime('%H:%M:%S')}] 🌐 Status {r.status_code} - URL: {url[:100]}")
        
        if r.status_code != 200:
            print(f"   Body preview: {r.text[:500]}")
            last_check_info["debug"] = f"Status {r.status_code}: {r.text[:200]}"
            if r.status_code in [401, 403, 429]:
                global session
                session = None
            # Se 404, prova senza filtri prezzo (Vinted blocca price-only)
            if r.status_code == 404 and ("price_from" in url or "price_to" in url):
                print("   ⚠️ 404 con filtri prezzo, riprovo senza prezzo...")
                try:
                    # Rimuovi price_from/to e riprova
                    from urllib.parse import urlencode, parse_qs, urlparse
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    qs.pop("price_from", None)
                    qs.pop("price_to", None)
                    # Assicura search_text
                    if "search_text" not in qs:
                        qs["search_text"] = ["nike"]
                    new_qs = urlencode({k: v[0] if isinstance(v, list) else v for k, v in qs.items()}, doseq=True)
                    new_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_qs}"
                    print(f"   🔁 Retry URL: {new_url[:120]}")
                    r2 = sess.get(new_url, headers=h, timeout=25, impersonate="chrome131" if USE_CURL else None)
                    print(f"   Retry status {r2.status_code}")
                    if r2.status_code == 200:
                        try:
                            data2 = r2.json()
                            items2 = data2.get('items') or []
                            if items2:
                                print(f"   ✅ Retry trovato {len(items2)} items!")
                                # usa questo risultato
                                data = data2
                                items = items2
                                # vai avanti, non ritornare None
                                r = r2
                            else:
                                last_check_info["debug"] = f"Retry 0 items dopo 404"
                                return None
                        except:
                            pass
                    else:
                        return None
                except Exception as e:
                    print(f"   Retry errore: {e}")
                    return None
            else:
                if r.status_code == 404:
                    last_check_info["debug"] = f"Status 404 - endpoint cambiato, prova SEARCH_TEXT= nike senza prezzo"
                return None
        
        try:
            data = r.json()
        except Exception as e:
            print(f"   Non è JSON! Body: {r.text[:500]}")
            last_check_info["debug"] = f"Non JSON: {r.text[:200]}"
            return None
        
        # Debug struttura
        print(f"   Chiavi JSON: {list(data.keys())[:10]}")
        
        items = data.get('items') or data.get('data') or []
        if isinstance(items, dict):
            items = items.get('items') or items.get('data') or []
        
        print(f"   Trovati {len(items)} items")
        
        if not items:
            print(f"⚠️ 0 risultati - risposta completa: {str(data)[:800]}")
            last_check_info["debug"] = f"0 items. Keys: {list(data.keys())} - data: {str(data)[:400]}"
            return None
        
        f = items[0]
        price = f.get('price') or f.get('price_numeric') or f.get('total_item_price') or ""
        if isinstance(price, dict):
            price = price.get('amount') or price.get('text') or ""
        
        photo = (f.get('photo') or {}).get('url')
        if not photo and f.get('photos'):
            try:
                photo = f['photos'][0].get('url') or f['photos'][0].get('thumbnails', [{}])[0].get('url')
            except: pass
        
        # URL prodotto
        prod_url = f.get('url') or f"https://www.vinted.{DOMAIN}/items/{f.get('id')}"
        
        return {
            "id": str(f.get('id')),
            "title": f.get('title','Senza titolo'),
            "url": prod_url,
            "price": price,
            "photo": photo,
            "api_url": url
        }
    except Exception as e:
        print(f"❌ Errore fetch: {e}")
        import traceback; traceback.print_exc()
        last_check_info["debug"] = f"Errore: {e}"
        return None

def send_discord(item):
    if not WEBHOOK_URL:
        return
    embed = {
        "title": f"🔔 NUOVO! {item['title'][:180]}",
        "url": item['url'],
        "description": f"**Prezzo:** {item['price']}€\n**Filtro:** {VINTED_URL[:70] if VINTED_URL else SEARCH_TEXT}\n\n🔗 [COMPRA ORA]({item['url']})",
        "color": 0x09B1BA,
        "image": {"url": item['photo']} if item['photo'] else None,
        "footer": {"text": f"ID {item['id']}"}
    }
    try:
        std_requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print(f"✅ Discord inviato {item['id']}")
    except Exception as e:
        print(f"Discord err {e}")

@app.route("/")
def home():
    filtro_display = html.escape(VINTED_URL if VINTED_URL else SEARCH_TEXT or "nessuno")
    api_display = html.escape(last_check_info['current_filter'])
    title_display = html.escape(last_check_info['last_title'] or "")
    debug_display = html.escape(last_check_info.get('debug','')[:500])
    stato = "✅ OK - Trovato prodotto" if last_check_info['last_id'] else f"❌ {debug_display or 'Nessun risultato - Vinted sta bloccando, riprovo con cookie'}"
    
    return f"""
    <h1>Vinted Bot Online ✅</h1>
    <p><b>Filtro attivo:</b> {filtro_display}</p>
    <p><b>Domain:</b> {html.escape(DOMAIN)}</p>
    <p><b>Ultimo check:</b> {html.escape(last_check_info['last_check'])}</p>
    <p><b>Ultimo ID:</b> {html.escape(str(last_check_info['last_id']))} - {title_display}</p>
    <p><b>API URL:</b> {api_display}</p>
    <p><b>Stato:</b> {stato}</p>
    <p><b>Debug:</b> {debug_display}</p>
    <p><a href="/health">health</a> | <a href="/">refresh</a></p>
    <hr>
    <p>Se vedi sempre None, Vinted blocca Render. Prova link più semplice: <code>?order=newest_first</code></p>
    """

@app.route("/health")
def health():
    return "OK", 200

def loop_monitor():
    print(f"🚀 Avvio monitor - VINTED_URL={VINTED_URL or SEARCH_TEXT}")
    last_id = None
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE) as f:
                last_id = json.load(f).get('id')
        except: pass

    if WEBHOOK_URL:
        try:
            msg = f"✅ Bot avviato! Filtro: {VINTED_URL or SEARCH_TEXT or 'default'}"
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
                print(f"[{now}] 🔍 {first['id']} | {first['title'][:60]} | {first['price']}€")
                if first['id'] != last_id:
                    print(f"[{now}] 🚨 NUOVO! {last_id} -> {first['id']}")
                    send_discord(first)
                    last_id = first['id']
                    try:
                        with open(STORAGE_FILE,'w') as f:
                            json.dump({"id": last_id}, f)
                    except: pass
                else:
                    print(f"[{now}] 😴 uguale")
            else:
                print(f"[{now}] ⚠️ Nessun dato")
        except Exception as e:
            print(f"🔥 Loop err: {e}")
        time.sleep(random.randint(25,40))

threading.Thread(target=loop_monitor, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
