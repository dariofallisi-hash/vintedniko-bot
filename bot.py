import time, random, os, json, threading
from flask import Flask

SEARCH_TEXT = os.getenv("SEARCH_TEXT", "nintendo switch")
DOMAIN = os.getenv("DOMAIN", "it")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK", "")
STORAGE_FILE = "/tmp/vinted_first.json"

# Prova a usare curl_cffi per bypassare blocco Vinted
try:
    from curl_cffi import requests as c_requests
    USE_CURL = True
    print("✅ Usando curl_cffi per bypassare blocco Vinted")
except Exception as e:
    import requests as c_requests
    USE_CURL = False
    print(f"⚠️ curl_cffi non disponibile ({e}), uso requests normale")
    import requests

import requests as std_requests

app = Flask(__name__)

@app.route("/")
def home():
    return f"Vinted bot online - monitoring: {SEARCH_TEXT} - {time.strftime('%H:%M:%S')} - curl={USE_CURL}"

@app.route("/health")
def health():
    return "OK", 200

def fetch_first():
    ts = int(time.time())
    # Prova 2 URL diversi, quello nuovo di vinted a volte blocca
    urls = [
        f"https://www.vinted.{DOMAIN}/api/v2/catalog/items?search_text={SEARCH_TEXT}&order=newest_first&per_page=5&time={ts}",
        f"https://www.vinted.{DOMAIN}/api/v2/catalog/items?search_text={SEARCH_TEXT}&order=newest_first&page=1&per_page=10"
    ]
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"https://www.vinted.{DOMAIN}/catalog?search_text={SEARCH_TEXT.replace(' ','+')}&order=newest_first",
        "Origin": f"https://www.vinted.{DOMAIN}",
    }
    for url in urls:
        try:
            kw = {"headers": h, "timeout": 20}
            if USE_CURL:
                kw["impersonate"] = "chrome124"
            r = c_requests.get(url, **kw)
            print(f"[{time.strftime('%H:%M:%S')}] 🌐 GET {url[:70]}... -> Status {r.status_code}")
            if r.status_code != 200:
                print(f"   Body preview: {r.text[:300]}")
                continue
            try:
                data = r.json()
            except:
                print(f"   Non JSON: {r.text[:300]}")
                continue
            items = data.get('items') or data.get('data') or []
            # Alcune API ritornano items dentro data
            if isinstance(items, dict):
                items = items.get('items') or []
            if not items:
                print(f"[{time.strftime('%H:%M:%S')}] ⚠️ Nessun risultato")
                continue
            f = items[0]
            price = f.get('price') or f.get('price_numeric') or f.get('price_amount') or ""
            if isinstance(price, dict):
                price = price.get('amount') or price.get('text') or ""
            photo = (f.get('photo') or {}).get('url')
            if not photo and f.get('photos'):
                try:
                    photo = f['photos'][0].get('url')
                except: pass
            item = {
                "id": str(f.get('id')),
                "title": f.get('title','Senza titolo'),
                "url": f.get('url') or f"https://www.vinted.{DOMAIN}/items/{f.get('id')}",
                "price": price,
                "photo": photo
            }
            return item
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ Errore fetch: {e}")
            import traceback; traceback.print_exc()
            continue
    return None

def send_discord(item):
    if not WEBHOOK_URL:
        print("⚠️ WEBHOOK non impostato")
        return
    embed = {
        "title": f"🔔 NUOVO IN ALTO SU VINTED!\n{item['title'][:200]}",
        "url": item['url'],
        "description": f"**Prezzo:** {item['price']}\n**Ricerca:** `{SEARCH_TEXT}`\n[Apri su Vinted]({item['url']})",
        "color": 0x09B1BA,
        "image": {"url": item['photo']} if item['photo'] else None,
        "footer": {"text": f"ID {item['id']} | vinted.{DOMAIN}"}
    }
    try:
        std_requests.post(WEBHOOK_URL, json={"embeds":[embed]}, timeout=15)
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Inviato su Discord ID {item['id']}")
    except Exception as e:
        print(f"Discord error {e}")

def loop_monitor():
    print(f"[{time.strftime('%H:%M:%S')}] 🚀 Avvio monitor Vinted - filtro: '{SEARCH_TEXT}' su vinted.{DOMAIN} - USE_CURL={USE_CURL}")
    last_id = None
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE) as f:
                last_id = json.load(f).get('id')
                print(f"Ultimo ID salvato: {last_id}")
        except: pass

    if WEBHOOK_URL:
        try:
            std_requests.post(WEBHOOK_URL, json={"content": f"✅ Bot avviato! Monitoro **{SEARCH_TEXT}** su vinted.{DOMAIN} - controllo ogni ~30s. (fix anti-blocco attivo)"}, timeout=10)
            print("Messaggio avvio inviato su Discord")
        except Exception as e:
            print(f"Errore invio avvio: {e}")

    while True:
        try:
            first = fetch_first()
            now = time.strftime('%H:%M:%S')
            if first:
                print(f"[{now}] 🔍 Check: primo ID {first['id']} | {first['title'][:60]} | {first['price']}")
                if first['id'] != last_id:
                    print(f"[{now}] 🚨 CAMBIO RILEVATO! {last_id} -> {first['id']}")
                    send_discord(first)
                    last_id = first['id']
                    try:
                        with open(STORAGE_FILE,'w') as f:
                            json.dump({"id": last_id}, f)
                    except: pass
                else:
                    print(f"[{now}] 😴 Nessun cambio, dormo 30s...")
            else:
                print(f"[{now}] ⚠️ Nessun dato, riprovo tra 30s (Vinted potrebbe bloccare, riprovo con curl_cffi)")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] 🔥 Errore nel loop: {e}")
            import traceback; traceback.print_exc()

        time.sleep(random.randint(25,40))

threading.Thread(target=loop_monitor, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
