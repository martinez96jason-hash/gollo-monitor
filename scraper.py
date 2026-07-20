"""
Monitor de rebajas de Gollo.com
--------------------------------
Recorre TODO el catálogo (https://www.gollo.com/c), detecta productos con
descuento >= MIN_DISCOUNT % y envía un correo cuando aparece una oferta NUEVA
(no repite alertas de productos ya notificados mientras sigan en oferta).

No requiere navegador (Chrome/Selenium): el HTML de Gollo ya trae los precios
y el % de descuento en texto plano, así que basta con requests + BeautifulSoup.
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import os
import time
import random
import html as html_lib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ----------------------------- Configuración ------------------------------

BASE_URL = "https://www.gollo.com/c"
PAGE_SIZE = 36           # productos por página (el máximo que ofrece el sitio)
MIN_DISCOUNT = 71        # % mínimo de descuento para alertar
STATE_FILE = "state.json"
REQUEST_DELAY = 2.5      # segundos base entre requests, para no golpear el sitio
MAX_PAGES = 100          # tope de seguridad
TIMEOUT = 30
MAX_RETRIES = 4          # reintentos por página si nos bloquean (429) o hay error

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CR,es;q=0.9,en;q=0.8",
    "Referer": "https://www.gollo.com/",
    "Connection": "keep-alive",
}

session = requests.Session()
session.headers.update(HEADERS)

# Patrones para extraer info directamente del HTML crudo, en una "ventana" de
# texto alrededor de cada link de producto. Esto es más robusto que depender
# de la profundidad exacta del árbol DOM (que puede variar).
LINK_RE = re.compile(r'<a\b[^>]*?href="([^"]+?/p)"[^>]*>', re.IGNORECASE)
TITLE_RE = re.compile(r'title="([^"]*)"', re.IGNORECASE)
PRICE_RE = re.compile(r'₡\s?[\d.,]+')
DISCOUNT_RE = re.compile(r'(\d{1,3})\s?%')
TAG_RE = re.compile(r'<[^>]+>')
WS_RE = re.compile(r'\s+')

WINDOW_BEFORE = 400
WINDOW_AFTER = 2500

# ------------------------------- Utilidades --------------------------------


def parse_price(text):
    """'₡279.915' -> 279915"""
    cleaned = text.replace("₡", "").replace(".", "").replace(",", "").strip()
    m = re.search(r"\d+", cleaned)
    return int(m.group()) if m else None


def clean_text(raw_html_fragment):
    text = TAG_RE.sub(" ", raw_html_fragment)
    text = html_lib.unescape(text)
    text = WS_RE.sub(" ", text).strip()
    return text


def get_total_pages(soup):
    """Busca el texto '23 de 2349 resultados' para saber cuántas páginas hay."""
    text = soup.get_text(" ", strip=True)
    m = re.search(r"de\s+([\d.,]+)\s+resultados", text)
    if m:
        total = int(re.sub(r"[.,]", "", m.group(1)))
        return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return 1


def extract_products_from_page(html):
    """
    Extrae productos buscando cada link que termina en '/p' (así son todas
    las URLs de producto en Gollo) y mirando el texto que aparece justo
    alrededor de ese link en el HTML crudo (antes y después), sin depender
    de nombres de clases CSS ni de la estructura exacta del árbol DOM.
    """
    products = {}

    for m in LINK_RE.finditer(html):
        href = m.group(1)
        if href in products:
            continue

        tag_text = m.group(0)
        title_match = TITLE_RE.search(tag_text)
        name = html_lib.unescape(title_match.group(1)).strip() if title_match else None

        window_start = max(0, m.start() - WINDOW_BEFORE)
        window_end = min(len(html), m.end() + WINDOW_AFTER)
        window_html = html[window_start:window_end]
        window_text = clean_text(window_html)

        if not name:
            after_text = clean_text(html[m.end():m.end() + 200])
            name = after_text[:120].strip() if after_text else None

        if not name:
            continue

        prices = PRICE_RE.findall(window_text)
        discount_match = DISCOUNT_RE.search(window_text)

        if len(prices) < 2 or not discount_match:
            continue

        special_price = parse_price(prices[0])
        regular_price = parse_price(prices[1])
        discount = int(discount_match.group(1))

        if not special_price or not regular_price or regular_price <= special_price:
            continue

        computed_discount = round((1 - special_price / regular_price) * 100)
        if abs(discount - computed_discount) > 15:
            discount = computed_discount

        full_url = href if href.startswith("http") else f"https://www.gollo.com{href}"

        products[href] = {
            "name": name,
            "url": full_url,
            "special_price": special_price,
            "regular_price": regular_price,
            "discount": discount,
        }

    return list(products.values())


def fetch_page(page_num):
    params = {"p": page_num, "product_list_limit": PAGE_SIZE}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(BASE_URL, params=params, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            wait = 5 * attempt
            print(f"[warn] Fallo de red en pagina {page_num} (intento {attempt}): {e}. Esperando {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else 8 * attempt
            print(f"[warn] 429 en pagina {page_num} (intento {attempt}). Esperando {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = 5 * attempt
            print(f"[warn] Error {resp.status_code} en pagina {page_num} (intento {attempt}). Esperando {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp.text

    raise RuntimeError(f"No se pudo obtener la pagina {page_num} tras {MAX_RETRIES} intentos")


def scrape_all_products():
    all_products = {}

    first_html = fetch_page(1)
    soup = BeautifulSoup(first_html, "html.parser")
    total_pages = min(get_total_pages(soup), MAX_PAGES)
    print(f"[info] Paginas detectadas: {total_pages}")

    for prod in extract_products_from_page(first_html):
        all_products[prod["url"]] = prod
    print(f"[info] Pagina 1/{total_pages}: {len(all_products)} productos acumulados")

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY + random.uniform(0, 1.0))
        try:
            html = fetch_page(page)
        except Exception as e:
            print(f"[warn] Se omite pagina {page} tras varios intentos: {e}")
            continue

        found = extract_products_from_page(html)
        for prod in found:
            all_products[prod["url"]] = prod

        if page % 10 == 0 or page == total_pages:
            print(f"[info] Pagina {page}/{total_pages}: {len(all_products)} productos acumulados")

    return list(all_products.values())


# --------------------------------- Estado -----------------------------------


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"alerted_urls": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------- Correo -----------------------------------


def send_email(new_deals):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("ALERT_EMAIL", "martinez96jason@gmail.com")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔥 {len(new_deals)} nueva(s) rebaja(s) +{MIN_DISCOUNT}% en Gollo"
    msg["From"] = gmail_user
    msg["To"] = recipient

    text_lines = []
    html_items = []
    for p in sorted(new_deals, key=lambda x: -x["discount"]):
        text_lines.append(
            f"- {p['name']}\n"
            f"  {p['discount']}% OFF -> ₡{p['special_price']:,} (antes ₡{p['regular_price']:,})\n"
            f"  {p['url']}\n"
        )
        html_items.append(
            f"<li style='margin-bottom:14px'>"
            f"<b>{p['name']}</b><br>"
            f"<span style='color:#c0392b;font-weight:bold'>{p['discount']}% OFF</span> "
            f"&mdash; ₡{p['special_price']:,} <span style='text-decoration:line-through;color:#888'>"
            f"₡{p['regular_price']:,}</span><br>"
            f"<a href='{p['url']}'>Ver producto</a></li>"
        )

    text_body = "Nuevas rebajas de mas de " + str(MIN_DISCOUNT) + "% en Gollo:\n\n" + "\n".join(text_lines)
    html_body = (
        f"<h2>🔥 Nuevas rebajas de más de {MIN_DISCOUNT}% en Gollo</h2>"
        f"<ul style='list-style:none;padding:0'>{''.join(html_items)}</ul>"
    )

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipient, msg.as_string())


# ---------------------------------- Main -------------------------------------


def main():
    state = load_state()
    alerted = set(state.get("alerted_urls", []))

    products = scrape_all_products()
    print(f"[info] Productos totales escaneados: {len(products)}")

    deals = [p for p in products if p["discount"] >= MIN_DISCOUNT]
    print(f"[info] Ofertas >= {MIN_DISCOUNT}%: {len(deals)}")

    new_deals = [p for p in deals if p["url"] not in alerted]

    if new_deals:
        print(f"[info] Enviando correo por {len(new_deals)} oferta(s) nueva(s)")
        send_email(new_deals)
    else:
        print("[info] No hay ofertas nuevas que alertar")

    current_deal_urls = {p["url"] for p in deals}
    alerted = (alerted & current_deal_urls) | {p["url"] for p in new_deals}

    state["alerted_urls"] = sorted(alerted)
    save_state(state)


if __name__ == "__main__":
    main()
