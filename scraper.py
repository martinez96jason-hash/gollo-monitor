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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ----------------------------- Configuración ------------------------------

BASE_URL = "https://www.gollo.com/c"
PAGE_SIZE = 36           # productos por página (el máximo que ofrece el sitio)
MIN_DISCOUNT = 50        # % mínimo de descuento para alertar
STATE_FILE = "state.json"
REQUEST_DELAY = 1.2      # segundos entre requests, para no golpear el sitio
MAX_PAGES = 100          # tope de seguridad
TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# ------------------------------- Utilidades --------------------------------


def parse_price(text):
    """'₡279.915' -> 279915"""
    cleaned = text.replace("₡", "").replace(".", "").replace(",", "").strip()
    m = re.search(r"\d+", cleaned)
    return int(m.group()) if m else None


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
    Extrae productos de una página de listado.
    Estrategia: todos los links de producto en Gollo terminan en '/p'.
    Para cada uno, se sube por el árbol DOM hasta encontrar el contenedor
    de la tarjeta (el que tiene el precio y el % de descuento) y de ahí
    se extrae todo por texto/regex. Esto es más robusto que depender de
    nombres de clases CSS que Gollo puede cambiar con el tiempo.
    """
    soup = BeautifulSoup(html, "html.parser")
    products = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.rstrip("/").endswith("/p"):
            continue
        if href in seen:
            continue
        seen.add(href)

        container = a
        card_text = None
        for _ in range(6):
            if container.parent is None:
                break
            container = container.parent
            text = container.get_text(" ", strip=True)
            if "₡" in text and "%" in text:
                card_text = text
                break

        if not card_text:
            continue

        name = a.get("title") or a.get_text(strip=True)
        if not name:
            continue

        prices = re.findall(r"₡\s?[\d.,]+", card_text)
        discount_match = re.search(r"(\d{1,3})\s?%", card_text)

        if len(prices) < 2 or not discount_match:
            continue

        special_price = parse_price(prices[0])
        regular_price = parse_price(prices[1])
        discount = int(discount_match.group(1))

        if not special_price or not regular_price or regular_price <= special_price:
            continue

        computed_discount = round((1 - special_price / regular_price) * 100)

        products.append({
            "name": name.strip(),
            "url": href if href.startswith("http") else f"https://www.gollo.com{href}",
            "special_price": special_price,
            "regular_price": regular_price,
            "discount": max(discount, computed_discount),
        })

    return products


def fetch_page(page_num):
    params = {"p": page_num, "product_list_limit": PAGE_SIZE}
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def scrape_all_products():
    all_products = {}

    first_html = fetch_page(1)
    soup = BeautifulSoup(first_html, "html.parser")
    total_pages = min(get_total_pages(soup), MAX_PAGES)
    print(f"[info] Paginas detectadas: {total_pages}")

    for prod in extract_products_from_page(first_html):
        all_products[prod["url"]] = prod

    for page in range(2, total_pages + 1):
        try:
            html = fetch_page(page)
        except Exception as e:
            print(f"[warn] Error en pagina {page}: {e}")
            continue
        for prod in extract_products_from_page(html):
            all_products[prod["url"]] = prod
        time.sleep(REQUEST_DELAY)

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

    # Solo se mantienen en "alertados" las que siguen activas como oferta.
    # Si una oferta desaparece y vuelve a aparecer despues, se vuelve a alertar.
    current_deal_urls = {p["url"] for p in deals}
    alerted = (alerted & current_deal_urls) | {p["url"] for p in new_deals}

    state["alerted_urls"] = sorted(alerted)
    save_state(state)


if __name__ == "__main__":
    main()
