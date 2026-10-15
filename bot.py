# -*- coding: utf-8 -*-
"""
TurkPronim Yapay — sade bot
- Sadece: AI sohbet (yapay / bota yanit) + fiyat
- Komut yok, mute/ban/karsilama yok
- Render keep-alive dahil
"""
import asyncio
import html
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from groq import Groq
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
SAHIP_KULLANICI = (
    os.environ.get("SAHIP_KULLANICI") or os.environ.get("SAHIP_USERNAME") or ""
).lower().lstrip("@")

TR = timezone(timedelta(hours=3))


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
    "Sen grubun samimi, esprili asistanısın. Adın Yapay. Türkçe konuş. "
    "CEVAPLAR ÇOK KISA: en fazla 1-2 kısa cümle, 150 karakteri geçme. Uzun paragraf YASAK. "
    "Samimi ol, gerekirse hafif küfür (amk, lan) ama abartma. "
    "Önceki konuşmayı unutma, konu dışına çıkma. "
    "Kişiye SADECE verilen ismiyle hitap et. Asla 'Telegram' diye hitap etme. "
    "Model/şirket adı söyleme. Yatırım/siyaset yok. Bilmediğini uydurma. "
    "Sahip talimatlarına uy."
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

for _k, _v in (("sahip", None), ("talimat", []), ("ayar", {})):
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


def tanidiklar(chat_id):
    k = uyeler.get(str(chat_id), {})
    en = sorted(k.values(), key=lambda u: u.get("mesaj", 0), reverse=True)[:12]
    parcalar = []
    for u in en:
        s = u.get("ad") or "?"
        if u.get("kullanici"):
            s += " (@" + u["kullanici"] + ")"
        parcalar.append(s + " " + str(u.get("mesaj", 0)) + " mesaj")
    return ", ".join(parcalar) if parcalar else "henuz yok"


def groq_sor(m, sistem):
    son = None
    # 2026: llama self-serve kalkti; gpt-oss / qwen aktif
    for model in (
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ):
        try:
            r = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sistem}] + m,
                max_tokens=180,
                temperature=0.7,
            )
            c = r.choices[0].message.content
            if c:
                log.info("Groq OK: %s", model)
                return c
        except Exception as e:
            son = e
            log.warning("Groq %s: %s", model, e)
    if son:
        raise son
    return None


def _gemini_icerik(m):
    return [
        {
            "role": "model" if x["role"] == "assistant" else "user",
            "parts": [{"text": x["content"]}],
        }
        for x in m
    ]


def gemini_sor(m, sistem):
    son = None
    for model in (
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-flash-latest",
    ):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=_gemini_icerik(m),
                config={"system_instruction": sistem, "max_output_tokens": 180},
            )
            txt = getattr(r, "text", None)
            if txt:
                return txt
        except Exception as e:
            son = e
            log.warning("Gemini %s: %s", model, e)
    if son:
        raise son
    return None


def gemini_arama(m, sistem):
    son = None
    for model in ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=_gemini_icerik(m),
                config=types.GenerateContentConfig(
                    system_instruction=sistem,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    max_output_tokens=180,
                ),
            )
            txt = getattr(r, "text", None)
            if txt:
                return txt
        except Exception as e:
            son = e
            log.warning("Gemini arama %s: %s", model, e)
    if son:
        raise son
    return None


def deepseek_sor(m, sistem):
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": "Bearer " + DEEPSEEK_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": sistem}] + m,
            "temperature": 0.7,
            "max_tokens": 180,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def mistral_sor(m, sistem):
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + MISTRAL_KEY},
        json={
            "model": "mistral-small-latest",
            "messages": [{"role": "system", "content": sistem}] + m,
            "max_tokens": 180,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def openrouter_sor(m, sistem):
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer " + OPENROUTER_KEY},
        json={
            "model": "meta-llama/llama-3.3-70b-instruct:free",
            "messages": [{"role": "system", "content": sistem}] + m,
            "max_tokens": 180,
        },
        timeout=25,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


SAGLAYICILAR = [("Gemini", gemini_sor), ("Groq", groq_sor)]
if DEEPSEEK_KEY:
    SAGLAYICILAR.append(("DeepSeek", deepseek_sor))
if OPENROUTER_KEY:
    SAGLAYICILAR.append(("OpenRouter", openrouter_sor))
if MISTRAL_KEY:
    SAGLAYICILAR.append(("Mistral", mistral_sor))


def arama_gerek(metin):
    k = kucult(metin)
    return any(
        x in k
        for x in (
            "haber", "bugun", "bugün", "fiyat", "kac", "kaç",
            "ne oldu", "son durum", "guncel", "güncel",
        )
    )


def sor(mesajlar, ek="", arama=False):
    sistem = SISTEM + ek
    zincir = list(SAGLAYICILAR)
    if arama:
        zincir = [("Gemini+Arama", gemini_arama)] + zincir
    for ad, fonk in zincir:
        try:
            cevap = fonk(mesajlar, sistem)
            if cevap:
                cevap = re.sub(
                    r"(?i)(tabii ki|anladim\.|anladım\.|baska bir konuda|"
                    r"size yardimci olmaya hazirim\.?)\s*",
                    "",
                    cevap,
                ).strip()
                if len(cevap.split()) > 55:
                    cevap = " ".join(cevap.split()[:45]) + "..."
                return cevap
        except Exception as e:
            log.warning("%s coktu: %s", ad, e)
            log.warning("%s detay: %s", ad, str(e)[:400])
    log.error("Tum AI saglayicilar basarisiz — GROQ_KEY / GEMINI_KEY kontrol et")
    return None


# ---------- FIYAT ----------
KISA_FIYAT = re.compile(
    r"^\s*(?:(\d+(?:[.,]\d+)?)\s*)?([a-zA-Z][a-zA-Z0-9]{1,12})\s*$"
)
SAYI_KELIME = {
    "tl", "try", "usd", "eur", "gb", "mb", "kg", "tane", "adet",
    "saat", "gun", "dk", "sn", "lira", "dolar", "euro",
}

TOKEN_MAP = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
    "bnb": "binancecoin", "xrp": "ripple", "ton": "the-open-network",
    "doge": "dogecoin", "ada": "cardano", "avax": "avalanche-2",
    "dot": "polkadot", "link": "chainlink", "matic": "matic-network",
    "near": "near", "atom": "cosmos", "ltc": "litecoin",
    "shib": "shiba-inu", "pepe": "pepe", "trx": "tron",
    "sui": "sui", "apt": "aptos", "sei": "sei-network",
    "inj": "injective-protocol", "op": "optimism", "arb": "arbitrum",
    "gram": "gram-2", "not": "notcoin",
}


def kisa_token(metin):
    m = KISA_FIYAT.match(metin.strip())
    if not m:
        return None
    miktar_s, sembol = m.group(1), m.group(2).lower()
    if sembol in SAYI_KELIME:
        return None
    if len(sembol) < 2:
        return None
    miktar = 1.0
    if miktar_s:
        try:
            miktar = float(miktar_s.replace(",", "."))
        except Exception:
            miktar = 1.0
    return (miktar, sembol)


def fiyat_cek(sembol):
    try:
        cid = TOKEN_MAP.get(sembol.lower())
        name = sembol.upper()
        sym = sembol.upper()
        if not cid:
            r = requests.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": sembol},
                timeout=10,
            )
            coins = (r.json().get("coins") or [])
            if not coins:
                return None
            cid = coins[0]["id"]
            name = coins[0].get("name") or name
            sym = (coins[0].get("symbol") or sym).upper()

        r2 = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": cid,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        d = r2.json().get(cid) or {}
        usd = d.get("usd")
        chg = d.get("usd_24h_change")
        if usd is None:
            return None
        return {
            "id": cid,
            "name": name,
            "symbol": sym,
            "usd": float(usd),
            "change": float(chg) if chg is not None else None,
        }
    except Exception as e:
        log.warning("fiyat_cek: %s", e)
        return None


async def fiyat_gonder(update, ctx, sembol, miktar=1.0):
    msg = update.effective_message
    if not msg:
        return False
    data = await asyncio.to_thread(fiyat_cek, sembol)
    if not data:
        return False
    toplam = data["usd"] * float(miktar)
    chg = data.get("change")
    if chg is None:
        chg_txt = ""
    elif chg >= 0:
        chg_txt = f"\n📈 24s: +%{chg:.2f}"
    else:
        chg_txt = f"\n📉 24s: %{chg:.2f}"
    if miktar == 1 or miktar == 1.0:
        metin = (
            f"⚠️ <b>1 {data['symbol']}</b>\n"
            f"✅ ${data['usd']:,.4f}".rstrip("0").rstrip(".")
            + chg_txt
        )
    else:
        metin = (
            f"⚠️ <b>{miktar:g} {data['symbol']}</b>\n"
            f"✅ ${toplam:,.4f}".rstrip("0").rstrip(".")
            + f"\n(1 {data['symbol']} = ${data['usd']:,.4f})"
            + chg_txt
        )
    try:
        await msg.reply_text(metin, parse_mode="HTML", do_quote=True)
        return True
    except Exception as e:
        log.warning("fiyat reply: %s", e)
        return False


async def sahip_yakala(update, ctx):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or chat.type != "private":
        return
    if durum.get("sahip"):
        return
    if SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI:
        durum["sahip"] = user.id
        durum_kaydet()
        log.info("Sahip otomatik: %s", user.id)
        try:
            await ctx.bot.send_message(chat.id, "Sahip olarak kaydedildin.")
        except Exception:
            pass


async def mesaj(update, ctx):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not chat:
        return
    if user and user.is_bot:
        return
    metin = msg.text or msg.caption
    if not metin:
        return
    if (msg.text or "").lstrip().startswith("/"):
        return

    ozel = chat.type == "private"
    cid = chat.id

    if user:
        kayit = uye_kaydi(cid, user)
    else:
        kayit = {"mesaj": 0}

    # Sahip ozelden gruba
    if ozel and sahip_mi(user):
        if not durum.get("sahip") and user:
            durum["sahip"] = user.id
            durum_kaydet()
        t0 = kucult(metin)
        temiz = re.sub(r"(?i)\byapay\b", "", metin).strip()
        gonderilecek = None
        m = re.search(
            r"(?:gruba|grupta)\s+(?:sunu\s+|bunu\s+)?"
            r"(?:soyle|yaz|at|paylas|gonder)?\s*[:=]?\s*(.+)",
            temiz,
            re.IGNORECASE | re.DOTALL,
        )
        if m and m.group(1).strip():
            gonderilecek = m.group(1).strip()
        if not gonderilecek and re.search(r"(gruba|grupta).*(saat|saati)", t0):
            gonderilecek = datetime.now(TR).strftime("Su an saat %H:%M")
        if gonderilecek:
            sayac = 0
            for gcid in list(uyeler.keys()):
                try:
                    if int(gcid) < 0:
                        await ctx.bot.send_message(int(gcid), gonderilecek)
                        sayac += 1
                except Exception as e:
                    log.warning("Gruba gonderilemedi %s: %s", gcid, e)
            if sayac == 0:
                await msg.reply_text("Henuz kayitli grup yok. Botu gruba ekle.")
            else:
                await msg.reply_text(f"{sayac} gruba gonderildi:\n{gonderilecek}")
            return

    # Fiyat (yapay olmadan)
    kt = kisa_token(metin)
    if kt:
        ok = await fiyat_gonder(update, ctx, kt[1], kt[0])
        if ok:
            return

    # AI cagrisi?
    bot_un = (ctx.bot.username or "").lower()
    met_k = kucult(metin)
    rt = msg.reply_to_message
    bota_yanit = bool(rt and rt.from_user and rt.from_user.id == ctx.bot.id)
    cagrildi = (
        "yapay" in met_k
        or (bot_un and f"@{bot_un}" in met_k)
        or bota_yanit
        or ozel
    )
    for e in getattr(msg, "entities", None) or []:
        et = getattr(e, "type", None)
        if et == "mention" and bot_un and bot_un in met_k:
            cagrildi = True
        if et == "text_mention" and getattr(e, "user", None) and e.user.id == ctx.bot.id:
            cagrildi = True

    if not cagrildi:
        return

    log.info("AI: chat=%s user=%s text=%r", cid, getattr(user, "id", None), metin[:80])
    await ctx.bot.send_chat_action(cid, "typing")

    ad_kisi = None
    if user:
        ad_kisi = (user.first_name or user.full_name or user.username or "").strip()
    if not ad_kisi or ad_kisi.lower() in ("telegram", "bot", "channel", "kanal"):
        ad_kisi = "dostum"

    ek = (
        f"\nSu an yazan kisinin adi: {ad_kisi}. "
        f"Ona sadece '{ad_kisi}' diye hitap et. 'Telegram' deme."
    )
    if user:
        ek += f" Grupta {kayit.get('mesaj', 0)} mesaji var."
    if user and sahip_mi(user):
        ek += " Bu kisi SAHIP; samimi ol."
    if durum.get("talimat"):
        ek += (
            "\nSahibinin kalici talimatlari: "
            + " | ".join(x.get("t", "") for x in durum["talimat"][-8:])
        )
    if not ozel:
        ek += "\nGrubun bilinen uyeleri: " + tanidiklar(cid)
        if (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == ctx.bot.id
        ):
            onceki = (
                msg.reply_to_message.text or msg.reply_to_message.caption or ""
            ).strip()
            if onceki:
                ek += f'\nOnceki bot mesaji: "{onceki[:250]}". Konuyu surdur.'

    uid = user.id if user else (getattr(msg.sender_chat, "id", None) or 0)
    anahtar = (cid, uid)
    h = gecmis.setdefault(anahtar, [])
    h.append({"role": "user", "content": metin})

    yanit = await asyncio.to_thread(sor, h[-16:], ek, arama_gerek(metin))
    if not yanit:
        yanit = "Bir saniye, tekrar dene"
    else:
        yanit = yanit.strip()
        if len(yanit) > 200:
            kes = yanit[:200]
            if " " in kes:
                kes = kes.rsplit(" ", 1)[0]
            yanit = kes + "..."
        h.append({"role": "assistant", "content": yanit})
    gecmis[anahtar] = h[-30:]

    try:
        await msg.reply_text(yanit, do_quote=True)
    except Exception as e:
        log.warning("AI reply: %s", e)
        try:
            await ctx.bot.send_message(cid, yanit)
        except Exception as e2:
            log.warning("AI send: %s", e2)


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

log.info("Bot basliyor (sadece AI + fiyat)...")
app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
