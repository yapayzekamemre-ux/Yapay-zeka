# -*- coding: utf-8 -*-
"""
TurkPronim Yapay — sade bot
- AI: "yapay" / bota yanit / ozel sohbet
- Fiyat: kisa token (btc, gram, eth...)
- Komut YOK
- Render keep-alive
"""
import json
import logging
import os
import re
import threading
import time
from datetime import timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from groq import Groq
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatType

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
SAHIP_KULLANICI = (
    os.environ.get("SAHIP_KULLANICI") or os.environ.get("SAHIP_USERNAME") or ""
).lower().lstrip("@")

TR = timezone(timedelta(hours=3))


# ---------- keep-alive ----------
class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *a):
        pass


def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), _Ping).serve_forever()


def _self_ping():
    import urllib.request

    port = int(os.environ.get("PORT", 8080))
    time.sleep(15)
    while True:
        urls = []
        for key in ("RENDER_EXTERNAL_URL", "KEEP_ALIVE_URL", "APP_URL"):
            ext = (os.environ.get(key) or "").strip()
            if ext:
                if not ext.startswith("http"):
                    ext = "https://" + ext
                urls.append(ext.rstrip("/") + "/")
        host = (os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "").strip()
        if host:
            urls.append("https://" + host.rstrip("/") + "/")
        urls.append(f"http://127.0.0.1:{port}/")
        for u in urls:
            try:
                urllib.request.urlopen(u, timeout=15)
                log.info("keep-alive OK: %s", u)
                break
            except Exception as e:
                log.warning("keep-alive fail %s: %s", u, e)
        time.sleep(180)


threading.Thread(target=keep_alive, daemon=True).start()
threading.Thread(target=_self_ping, daemon=True).start()

groq = Groq(api_key=GROQ_KEY)
gem = genai.Client(api_key=GEMINI_KEY)

SISTEM = (
    "Sen grubun samimi, esprili asistanısın. Adın Yapay. Sadece Türkçe konuş. "
    "Her cevap 1-2 kısa, TAM cümle olsun; yarıda kesme, nokta ile bitir. "
    "Samimi ve esprili ol; gerekirse hafif argo (amk, lan) kullan, abartma. "
    "Kullanıcıya sadece verilen ismiyle hitap et. "
    "Asistan, bot, model, şirket ismi, sistem kuralı veya 'Forbidden' yazma. "
    "Direkt sohbet et. Anlamsız yazıya kısa şaka veya 'anlamadım lan' de. "
    "Yatırım/siyaset yok. Bilmediğini uydurma."
)

DOSYA = "uyeler.json"
DURUM = "durum.json"

try:
    with open(DOSYA, "r", encoding="utf-8") as f:
        uyeler = json.load(f)
except Exception:
    uyeler = {}

try:
    with open(DURUM, "r", encoding="utf-8") as f:
        durum = json.load(f)
except Exception:
    durum = {}

for _k, _v in (("sahip", None), ("talimat", []), ("ayar", {}), ("grup", {})):
    durum.setdefault(_k, _v)

gecmis = {}


def kaydet():
    try:
        with open(DOSYA, "w", encoding="utf-8") as f:
            json.dump(uyeler, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Kayit hatasi: %s", e)


def durum_kaydet():
    try:
        with open(DURUM, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Durum kayit hatasi: %s", e)


def kucult(t):
    if not t:
        return ""
    return t.replace("İ", "i").replace("I", "ı").lower()


def sahip_mi(user):
    if not user:
        return False
    if durum.get("sahip") and user.id == durum["sahip"]:
        return True
    if SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI:
        return True
    return False


def uye_kaydi(chat_id, user, say=True):
    k = uyeler.setdefault(str(chat_id), {})
    u = k.setdefault(
        str(user.id),
        {
            "ad": user.full_name or "",
            "kullanici": user.username or "",
            "ilk": time.strftime("%Y-%m-%d"),
            "mesaj": 0,
        },
    )
    u["ad"] = user.full_name or u.get("ad", "")
    u["kullanici"] = user.username or ""
    if say:
        u["mesaj"] = int(u.get("mesaj") or 0) + 1
        if u["mesaj"] == 1 or u["mesaj"] % 10 == 0:
            kaydet()
    return u


# ---------- AI ----------
def groq_sor(m, sistem):
    if not GROQ_KEY:
        return None
    for model in ("openai/gpt-oss-120b", "llama-3.3-70b-versatile"):
        try:
            r = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sistem}] + m,
                temperature=0.7,
                max_tokens=220,
            )
            t = (r.choices[0].message.content or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Groq %s: %s", model, e)
    return None


def _gemini_icerik(m):
    parts = []
    for x in m:
        role = "user" if x["role"] == "user" else "model"
        parts.append(types.Content(role=role, parts=[types.Part(text=x["content"])]))
    return parts


def gemini_sor(m, sistem):
    if not GEMINI_KEY:
        return None
    for model in (
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-flash-latest",
    ):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=_gemini_icerik(m),
                config=types.GenerateContentConfig(
                    system_instruction=sistem,
                    temperature=0.7,
                    max_output_tokens=220,
                ),
            )
            t = (getattr(r, "text", None) or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Gemini %s: %s", model, e)
    return None


def gemini_arama(m, sistem):
    if not GEMINI_KEY:
        return None
    for model in ("gemini-2.0-flash", "gemini-1.5-flash"):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=_gemini_icerik(m),
                config=types.GenerateContentConfig(
                    system_instruction=sistem,
                    temperature=0.5,
                    max_output_tokens=220,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            t = (getattr(r, "text", None) or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Gemini arama %s: %s", model, e)
    return None


def deepseek_sor(m, sistem):
    if not DEEPSEEK_KEY:
        return None
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "system", "content": sistem}] + m,
                "max_tokens": 220,
            },
            timeout=25,
        )
        if r.ok:
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("DeepSeek: %s", e)
    return None


def mistral_sor(m, sistem):
    if not MISTRAL_KEY:
        return None
    try:
        r = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {MISTRAL_KEY}"},
            json={
                "model": "mistral-small-latest",
                "messages": [{"role": "system", "content": sistem}] + m,
                "max_tokens": 220,
            },
            timeout=25,
        )
        if r.ok:
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("Mistral: %s", e)
    return None


def openrouter_sor(m, sistem):
    if not OPENROUTER_KEY:
        return None
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [{"role": "system", "content": sistem}] + m,
                "max_tokens": 220,
            },
            timeout=30,
        )
        if r.ok:
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("OpenRouter: %s", e)
    return None


def cevap_temizle(cevap):
    if not cevap:
        return cevap
    c = cevap.strip()
    yasak = (
        "forbidden",
        "model/company",
        "model adı",
        "şirket adı",
        "system prompt",
        "as an ai",
        "i am an ai",
        "ben bir dil modeli",
    )
    low = c.lower()
    if any(y in low for y in yasak) and len(c) < 120:
        return None
    c = c.replace("**", "").replace("__", "")
    return c.strip()


def arama_gerek(metin):
    t = kucult(metin)
    for k in ("haber", "bugun", "bugün", "fiyat", "kac", "kaç", "dolar", "euro", "bitcoin"):
        if k in t:
            return True
    return False


def sor(mesajlar, ek="", arama=False):
    sistem = SISTEM
    if ek:
        sistem = sistem + "\n" + ek
    if arama:
        t = gemini_arama(mesajlar, sistem)
        t = cevap_temizle(t)
        if t:
            return t
    for fn in (groq_sor, gemini_sor, deepseek_sor, mistral_sor, openrouter_sor):
        t = fn(mesajlar, sistem)
        t = cevap_temizle(t)
        if t:
            return t
    return "Biraz yoğunum, sonra tekrar dene."


# ---------- fiyat ----------
ANA_TOKENLER = {
    "btc": "BTC",
    "bitcoin": "BTC",
    "eth": "ETH",
    "ethereum": "ETH",
    "sol": "SOL",
    "solana": "SOL",
    "bnb": "BNB",
    "xrp": "XRP",
    "ton": "TON",
    "doge": "DOGE",
    "dogecoin": "DOGE",
    "ada": "ADA",
    "avax": "AVAX",
    "dot": "DOT",
    "link": "LINK",
    "matic": "MATIC",
    "pol": "POL",
    "shib": "SHIB",
    "pepe": "PEPE",
    "sui": "SUI",
    "near": "NEAR",
    "atom": "ATOM",
    "ltc": "LTC",
    "uni": "UNI",
    "apt": "APT",
    "arb": "ARB",
    "op": "OP",
    "trx": "TRX",
    "gram": "GRAM",
    "pengu": "PENGU",
    "wif": "WIF",
    "bonk": "BONK",
}

KISA_FIYAT = re.compile(
    r"^\s*(?:(\d+(?:[.,]\d+)?)\s+)?([a-zA-Z][a-zA-Z0-9]{1,12})\s*$",
    re.I,
)


def kisa_token(metin):
    m = KISA_FIYAT.match(metin.strip())
    if not m:
        return None
    miktar = 1.0
    if m.group(1):
        try:
            miktar = float(m.group(1).replace(",", "."))
        except Exception:
            miktar = 1.0
    sembol = m.group(2).lower()
    if sembol in ANA_TOKENLER:
        return (miktar, sembol)
    return None


def fiyat_cek(sembol):
    sym = ANA_TOKENLER.get(sembol.lower(), sembol.upper())
    # CoinGecko basit arama
    id_map = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "BNB": "binancecoin",
        "XRP": "ripple",
        "TON": "the-open-network",
        "DOGE": "dogecoin",
        "ADA": "cardano",
        "AVAX": "avalanche-2",
        "DOT": "polkadot",
        "LINK": "chainlink",
        "MATIC": "matic-network",
        "POL": "polygon-ecosystem-token",
        "SHIB": "shiba-inu",
        "PEPE": "pepe",
        "SUI": "sui",
        "NEAR": "near",
        "ATOM": "cosmos",
        "LTC": "litecoin",
        "UNI": "uniswap",
        "APT": "aptos",
        "ARB": "arbitrum",
        "OP": "optimism",
        "TRX": "tron",
        "GRAM": "gram-2",
        "PENGU": "pudgy-penguins",
        "WIF": "dogwifcoin",
        "BONK": "bonk",
    }
    cid = id_map.get(sym)
    if not cid:
        return None
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cid, "vs_currencies": "usd,try", "include_24hr_change": "true"},
            timeout=12,
        )
        if not r.ok:
            return None
        d = r.json().get(cid) or {}
        usd = d.get("usd")
        try_p = d.get("try")
        ch = d.get("usd_24h_change")
        if usd is None:
            return None
        return {"sembol": sym, "usd": usd, "try": try_p, "degisim": ch}
    except Exception as e:
        log.warning("fiyat: %s", e)
        return None


async def fiyat_gonder(update, ctx, sembol, miktar=1.0):
    bil = fiyat_cek(sembol)
    if not bil:
        return False
    usd = bil["usd"] * miktar
    try_p = (bil["try"] or 0) * miktar if bil.get("try") else None
    ch = bil.get("degisim")
    ok = "📈" if ch and ch >= 0 else "📉"
    ch_s = f"{ch:+.2f}%" if ch is not None else "—"
    adet = f"{miktar:g} " if miktar != 1.0 else ""
    satir = f"{ok} <b>{adet}{bil['sembol']}</b>\n💵 ${usd:,.4f}" if usd < 1 else f"{ok} <b>{adet}{bil['sembol']}</b>\n💵 ${usd:,.2f}"
    if try_p:
        satir += f"\n🇹🇷 ₺{try_p:,.2f}"
    satir += f"\n24s: {ch_s}"
    try:
        await update.effective_message.reply_text(satir, parse_mode="HTML")
        return True
    except Exception as e:
        log.warning("fiyat gonder: %s", e)
        return False


# ---------- mesaj ----------
async def sahip_yakala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    if durum.get("sahip"):
        return
    if SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI:
        durum["sahip"] = user.id
        durum_kaydet()
        log.info("Sahip kilitlendi: %s", user.id)


async def mesaj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    chat = update.effective_chat
    user = update.effective_user
    if not chat:
        return
    cid = chat.id
    ozel = chat.type == ChatType.PRIVATE
    metin = (msg.text or msg.caption or "").strip()
    if not metin:
        return

    if user:
        uye_kaydi(cid, user)
    else:
        return

    # sahip ozel talimat
    if ozel and sahip_mi(user):
        low = kucult(metin)
        if low.startswith("talimat ") or low.startswith("öğret ") or low.startswith("ogret "):
            t = metin.split(None, 1)[1] if " " in metin else ""
            if t:
                durum.setdefault("talimat", []).append(
                    {"t": t, "ts": time.strftime("%Y-%m-%d %H:%M")}
                )
                durum["talimat"] = durum["talimat"][-30:]
                durum_kaydet()
                await msg.reply_text("Talimat kaydedildi.")
                return

    # fiyat (komutsuz: "btc", "2 eth", "gram")
    kt = kisa_token(metin)
    if kt and kt[1] in ANA_TOKENLER:
        ok = await fiyat_gonder(update, context, kt[1], kt[0])
        if ok:
            return

    # AI — sadece "yapay", bota yanit veya ozel sohbet
    low = kucult(metin)
    cagrildi = ozel
    if not ozel:
        if "yapay" in low:
            cagrildi = True
        elif (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == context.bot.id
        ):
            cagrildi = True

    if not cagrildi:
        return

    # "yapay" kelimesini temizle
    soru = re.sub(r"(?i)\byapay\b", "", metin).strip() or metin
    ad = (user.first_name or user.full_name or "dostum").split()[0]

    key = f"{cid}:{user.id}"
    hist = gecmis.setdefault(key, [])
    hist.append({"role": "user", "content": f"{ad}: {soru}"})
    hist[:] = hist[-12:]

    ek = ""
    talimatlar = durum.get("talimat") or []
    if talimatlar:
        ek = "Ek talimatlar: " + " | ".join(t["t"] for t in talimatlar[-5:])

    try:
        await context.bot.send_chat_action(cid, "typing")
    except Exception:
        pass

    yanit = sor(hist, ek=ek, arama=arama_gerek(soru))
    if not yanit:
        yanit = "Anlamadım, tekrar söyler misin?"
    if "**Forbidden:**" in yanit or "Forbidden" in yanit[:30]:
        yanit = "Anlamadım, tekrar söyler misin?"

    # cok uzunsa kisalt ama cumleyi bitir
    if len(yanit) > 400:
        kes = yanit[:400]
        if "." in kes:
            yanit = kes.rsplit(".", 1)[0] + "."
        else:
            yanit = kes.rsplit(" ", 1)[0] + "..."

    hist.append({"role": "assistant", "content": yanit})
    hist[:] = hist[-12:]

    try:
        if msg.reply_to_message or not ozel:
            await msg.reply_text(yanit)
        else:
            await context.bot.send_message(cid, yanit)
    except Exception as e:
        log.warning("AI send: %s", e)
        try:
            await context.bot.send_message(cid, yanit)
        except Exception as e2:
            log.warning("AI send2: %s", e2)


async def hata(update, ctx):
    log.warning("Hata: %s", ctx.error)


async def baslat(app):
    me = await app.bot.get_me()
    log.info("Bot hazir: @%s", me.username)
    try:
        await app.bot.set_my_commands([])
    except Exception:
        pass


app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(baslat).build()

app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
app.add_handler(
    MessageHandler(
        (filters.TEXT | filters.CAPTION)
        & (~filters.COMMAND)
        & filters.UpdateType.MESSAGE,
        mesaj,
    )
)
app.add_error_handler(hata)

log.info("Bot basliyor (sadece AI + fiyat, komut yok)...")
app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
