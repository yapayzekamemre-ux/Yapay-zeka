# -*- coding: utf-8 -*-
"""
TurkPronimBot — AI + fiyat + moderasyon (tek bot, tek token)
Komutlar: /ban /unban /kick /mute /unmute /warn /unwarn /reload /id
AI: gruba "yapay ..." yaz veya bota yanitla / ozelde yaz
Fiyat: btc, 2 eth, gram ...
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
from telegram import Update, ChatPermissions, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatType, ChatMemberStatus
from telegram.error import BadRequest, Forbidden

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ.get("GROQ_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
SAHIP_KULLANICI = (
    os.environ.get("SAHIP_KULLANICI") or os.environ.get("SAHIP_USERNAME") or ""
).lower().lstrip("@")


# ---------- keep-alive (Render) ----------
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
    time.sleep(20)
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

groq = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
gem = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

SISTEM = (
    "Sen grubun samimi, esprili asistanısın. Adın Yapay. Sadece Türkçe konuş. "
    "Her cevap 1-2 kısa, TAM cümle olsun; yarıda kesme, nokta ile bitir. "
    "Samimi ol; gerekirse hafif argo kullan, abartma. "
    "Kullanıcıya sadece verilen ismiyle hitap et. "
    "Asistan, bot, model, şirket ismi yazma. Direkt sohbet et. "
    "Yatırım tavsiyesi verme. Bilmediğini uydurma."
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

for _k, _v in (("sahip", None), ("talimat", [])):
    durum.setdefault(_k, _v)

gecmis = {}
uyarilar = {}


def kaydet():
    try:
        with open(DOSYA, "w", encoding="utf-8") as f:
            json.dump(uyeler, f, ensure_ascii=False)
    except Exception as e:
        log.warning("kaydet: %s", e)


def durum_kaydet():
    try:
        with open(DURUM, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False)
    except Exception as e:
        log.warning("durum: %s", e)


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


async def admin_mi(chat_id, user, bot) -> bool:
    if not user:
        return False
    if sahip_mi(user):
        return True
    try:
        m = await bot.get_chat_member(chat_id, user.id)
        return m.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            "administrator",
            "creator",
        )
    except Exception:
        return False


def uye_kaydi(chat_id, user):
    k = uyeler.setdefault(str(chat_id), {})
    u = k.setdefault(
        str(user.id),
        {
            "ad": user.full_name or "",
            "kullanici": (user.username or "").lower(),
            "mesaj": 0,
        },
    )
    u["ad"] = user.full_name or u.get("ad", "")
    u["kullanici"] = (user.username or "").lower()
    u["mesaj"] = int(u.get("mesaj") or 0) + 1
    if u["mesaj"] == 1 or u["mesaj"] % 20 == 0:
        kaydet()
    return u


async def sil_sonra(bot, chat_id, mid, sn=8):
    if not sn or sn <= 0 or not mid:
        return
    await asyncio.sleep(sn)
    try:
        await bot.delete_message(chat_id, mid)
    except Exception:
        pass


async def komut_sil(msg, bot):
    try:
        await bot.delete_message(msg.chat_id, msg.message_id)
    except Exception:
        pass


async def kisa_cevap(bot, chat_id, text, sn=8):
    try:
        m = await bot.send_message(chat_id, text, parse_mode="HTML")
        asyncio.create_task(sil_sonra(bot, chat_id, m.message_id, sn))
        return m
    except Exception as e:
        log.warning("kisa_cevap: %s", e)
        return None


class _FakeUser:
    def __init__(self, uid, ad="", uname=""):
        self.id = int(uid)
        self.full_name = ad or str(uid)
        self.username = uname
        self.first_name = (ad or str(uid)).split()[0]


async def hedef_kullanici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        if not u.is_bot:
            return u
    args = list(context.args or [])
    if not args:
        return None
    a0 = args[0].lstrip("@")
    if a0.isdigit():
        return _FakeUser(a0)
    if chat:
        for uid, bil in (uyeler.get(str(chat.id)) or {}).items():
            if (bil.get("kullanici") or "") == a0.lower():
                return _FakeUser(uid, bil.get("ad") or a0, a0)
    try:
        c = await context.bot.get_chat("@" + a0)
        return _FakeUser(c.id, getattr(c, "full_name", None) or a0, a0)
    except Exception:
        pass
    return None


def groq_sor(m, sistem):
    if not groq:
        return None
    for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
        try:
            r = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sistem}] + m,
                temperature=0.7,
                max_tokens=200,
            )
            t = (r.choices[0].message.content or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Groq %s: %s", model, e)
    return None


def _gem_parts(m):
    out = []
    for x in m:
        role = "user" if x["role"] == "user" else "model"
        out.append(types.Content(role=role, parts=[types.Part(text=x["content"])]))
    return out


def gemini_sor(m, sistem):
    if not gem:
        return None
    for model in ("gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=_gem_parts(m),
                config=types.GenerateContentConfig(
                    system_instruction=sistem,
                    temperature=0.7,
                    max_output_tokens=200,
                ),
            )
            t = (getattr(r, "text", None) or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Gemini %s: %s", model, e)
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
                "max_tokens": 200,
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
                "max_tokens": 200,
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
                "max_tokens": 200,
            },
            timeout=30,
        )
        if r.ok:
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.warning("OpenRouter: %s", e)
    return None


def cevap_temizle(c):
    if not c:
        return None
    c = c.strip().replace("**", "").replace("__", "")
    low = c.lower()
    if any(x in low for x in ("forbidden", "as an ai", "i am an ai", "system prompt")) and len(c) < 100:
        return None
    return c


def sor(mesajlar, ek=""):
    sistem = SISTEM + (("\n" + ek) if ek else "")
    for fn in (groq_sor, gemini_sor, deepseek_sor, mistral_sor, openrouter_sor):
        t = cevap_temizle(fn(mesajlar, sistem))
        if t:
            return t
    return "Biraz yoğunum, sonra tekrar dene."


ANA = {
    "btc": "BTC", "bitcoin": "BTC", "eth": "ETH", "ethereum": "ETH",
    "sol": "SOL", "bnb": "BNB", "xrp": "XRP", "ton": "TON",
    "doge": "DOGE", "ada": "ADA", "avax": "AVAX", "dot": "DOT",
    "link": "LINK", "matic": "MATIC", "shib": "SHIB", "pepe": "PEPE",
    "sui": "SUI", "near": "NEAR", "ltc": "LTC", "uni": "UNI",
    "trx": "TRX", "gram": "GRAM", "pengu": "PENGU", "wif": "WIF", "bonk": "BONK",
}
CG = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "TON": "the-open-network", "DOGE": "dogecoin",
    "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
    "LINK": "chainlink", "MATIC": "matic-network", "SHIB": "shiba-inu",
    "PEPE": "pepe", "SUI": "sui", "NEAR": "near", "LTC": "litecoin",
    "UNI": "uniswap", "TRX": "tron", "GRAM": "gram-2",
    "PENGU": "pudgy-penguins", "WIF": "dogwifcoin", "BONK": "bonk",
}
KISA = re.compile(r"^\s*(?:(\d+(?:[.,]\d+)?)\s+)?([a-zA-Z][a-zA-Z0-9]{1,12})\s*$", re.I)


def kisa_token(metin):
    m = KISA.match((metin or "").strip())
    if not m:
        return None
    miktar = 1.0
    if m.group(1):
        try:
            miktar = float(m.group(1).replace(",", "."))
        except Exception:
            pass
    s = m.group(2).lower()
    if s in ANA:
        return miktar, s
    return None


def fiyat_cek(sembol):
    sym = ANA.get(sembol.lower(), sembol.upper())
    cid = CG.get(sym)
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
        if d.get("usd") is None:
            return None
        return {"s": sym, "usd": d["usd"], "try": d.get("try"), "ch": d.get("usd_24h_change")}
    except Exception as e:
        log.warning("fiyat: %s", e)
        return None


async def fiyat_gonder(update, miktar, sembol):
    bil = fiyat_cek(sembol)
    if not bil:
        return False
    usd = bil["usd"] * miktar
    try_p = (bil["try"] or 0) * miktar if bil.get("try") else None
    ch = bil.get("ch")
    ok = "📈" if ch is not None and ch >= 0 else "📉"
    ch_s = f"{ch:+.2f}%" if ch is not None else "—"
    adet = f"{miktar:g} " if miktar != 1 else ""
    fmt = f"{usd:,.4f}" if usd < 1 else f"{usd:,.2f}"
    text = f"{ok} <b>{adet}{bil['s']}</b>\n💵 ${fmt}"
    if try_p:
        text += f"\n🇹🇷 ₺{try_p:,.2f}"
    text += f"\n24s: {ch_s}"
    try:
        await update.effective_message.reply_text(text, parse_mode="HTML")
        return True
    except Exception as e:
        log.warning("fiyat gonder: %s", e)
        return False


MUTE_PERMS = ChatPermissions(can_send_messages=False)
FULL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)


def _ad(u):
    return html.escape(getattr(u, "full_name", None) or str(getattr(u, "id", "?")))


async def _mod_giris(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return None
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return None
    await komut_sil(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        await kisa_cevap(context.bot, chat.id, "❌ Bu komut sadece yöneticiler için.", 5)
        return None
    return msg, chat, user


async def ban_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: yanıtla <code>/ban</code> veya <code>/ban @user</code>")
        return
    if hedef.id == context.bot.id:
        return
    try:
        await context.bot.ban_chat_member(chat.id, hedef.id)
        await kisa_cevap(context.bot, chat.id, f"🚫 {_ad(hedef)} banlandı.")
    except (BadRequest, Forbidden) as e:
        await kisa_cevap(context.bot, chat.id, f"❌ Ban olamadı: {html.escape(str(e))}")
    except Exception as e:
        log.warning("ban: %s", e)
        await kisa_cevap(context.bot, chat.id, "❌ Ban başarısız. Bot admin mi?")


async def unban_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/unban @user</code>")
        return
    try:
        await context.bot.unban_chat_member(chat.id, hedef.id, only_if_banned=True)
        await kisa_cevap(context.bot, chat.id, f"✅ {_ad(hedef)} banı kaldırıldı.")
    except Exception as e:
        log.warning("unban: %s", e)
        await kisa_cevap(context.bot, chat.id, f"❌ Unban: {html.escape(str(e))}")


async def kick_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: yanıtla <code>/kick</code>")
        return
    if hedef.id == context.bot.id:
        return
    try:
        await context.bot.ban_chat_member(chat.id, hedef.id)
        await context.bot.unban_chat_member(chat.id, hedef.id)
        await kisa_cevap(context.bot, chat.id, f"👢 {_ad(hedef)} atıldı.")
    except Exception as e:
        log.warning("kick: %s", e)
        await kisa_cevap(context.bot, chat.id, f"❌ Kick: {html.escape(str(e))}")


def _mute_dk(update, context) -> int:
    args = list(context.args or [])
    msg = update.effective_message
    if msg and msg.reply_to_message:
        if args and args[0].isdigit():
            return max(1, min(int(args[0]), 43200))
        return 60
    if len(args) >= 2 and args[1].isdigit():
        return max(1, min(int(args[1]), 43200))
    return 60


async def mute_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: yanıtla <code>/mute 30</code>")
        return
    if hedef.id == context.bot.id:
        return
    dk = _mute_dk(update, context)
    until = datetime.now(timezone.utc) + timedelta(minutes=dk)
    try:
        await context.bot.restrict_chat_member(
            chat.id, hedef.id, permissions=MUTE_PERMS, until_date=until
        )
        await kisa_cevap(context.bot, chat.id, f"🔇 {_ad(hedef)} {dk} dk susturuldu.")
    except Exception as e:
        log.warning("mute: %s", e)
        await kisa_cevap(context.bot, chat.id, f"❌ Mute: {html.escape(str(e))}")


async def unmute_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: yanıtla <code>/unmute</code>")
        return
    try:
        await context.bot.restrict_chat_member(chat.id, hedef.id, permissions=FULL_PERMS)
        await kisa_cevap(context.bot, chat.id, f"🔊 {_ad(hedef)} konuşabilir.")
    except Exception as e:
        log.warning("unmute: %s", e)
        await kisa_cevap(context.bot, chat.id, f"❌ Unmute: {html.escape(str(e))}")


async def warn_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: yanıtla <code>/warn</code>")
        return
    if hedef.id == context.bot.id:
        return
    limit = 3
    gmap = uyarilar.setdefault(str(chat.id), {})
    say = int(gmap.get(str(hedef.id), 0)) + 1
    gmap[str(hedef.id)] = say
    text = f"⚠️ {_ad(hedef)} uyarı: <b>{say}/{limit}</b>"
    if say >= limit:
        try:
            until = datetime.now(timezone.utc) + timedelta(hours=1)
            await context.bot.restrict_chat_member(
                chat.id, hedef.id, permissions=MUTE_PERMS, until_date=until
            )
            text += " → 1 saat mute"
            gmap[str(hedef.id)] = 0
        except Exception as e:
            log.warning("warn mute: %s", e)
            text += " (mute başarısız)"
    await kisa_cevap(context.bot, chat.id, text, 12)


async def unwarn_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not getattr(hedef, "id", None):
        await kisa_cevap(context.bot, chat.id, "Kullanım: yanıtla <code>/unwarn</code>")
        return
    uyarilar.setdefault(str(chat.id), {})[str(hedef.id)] = 0
    await kisa_cevap(context.bot, chat.id, f"✅ {_ad(hedef)} uyarıları sıfırlandı.")


async def reload_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        lines = [f"• {html.escape(a.user.full_name or str(a.user.id))}" for a in admins[:20]]
        await kisa_cevap(context.bot, chat.id, "🔄 Admin listesi:\n" + "\n".join(lines), 15)
    except Exception as e:
        log.warning("reload: %s", e)
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def id_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat:
        return
    await komut_sil(msg, context.bot)
    parts = [
        f"<b>Chat</b>: {html.escape(chat.title or getattr(chat, 'full_name', None) or '—')}",
        f"ID: <code>{chat.id}</code>",
        f"Tür: {chat.type}",
    ]
    if user:
        parts.append(f"Sen: <code>{user.id}</code>")
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        parts.append(f"Yanıtlanan: <code>{u.id}</code> {html.escape(u.full_name or '')}")
    await kisa_cevap(context.bot, chat.id, "\n".join(parts), 20)


async def sahip_yakala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or durum.get("sahip"):
        return
    if SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI:
        durum["sahip"] = user.id
        durum_kaydet()
        log.info("Sahip: %s", user.id)


async def mesaj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    metin = (msg.text or msg.caption or "").strip()
    if not metin:
        return

    uye_kaydi(chat.id, user)
    ozel = chat.type == ChatType.PRIVATE

    if ozel and sahip_mi(user):
        low = kucult(metin)
        if low.startswith(("talimat ", "öğret ", "ogret ")):
            t = metin.split(None, 1)[1] if " " in metin else ""
            if t:
                durum.setdefault("talimat", []).append(
                    {"t": t, "ts": time.strftime("%Y-%m-%d %H:%M")}
                )
                durum["talimat"] = durum["talimat"][-30:]
                durum_kaydet()
                await msg.reply_text("Talimat kaydedildi.")
                return

    kt = kisa_token(metin)
    if kt:
        if await fiyat_gonder(update, kt[0], kt[1]):
            return

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

    soru = re.sub(r"(?i)\byapay\b", "", metin).strip() or metin
    ad = (user.first_name or user.full_name or "dostum").split()[0]
    key = f"{chat.id}:{user.id}"
    hist = gecmis.setdefault(key, [])
    hist.append({"role": "user", "content": f"{ad}: {soru}"})
    hist[:] = hist[-10:]

    ek = ""
    if durum.get("talimat"):
        ek = "Ek talimatlar: " + " | ".join(x["t"] for x in durum["talimat"][-5:])

    try:
        await context.bot.send_chat_action(chat.id, "typing")
    except Exception:
        pass

    yanit = sor(hist, ek=ek)
    if not yanit or "Forbidden" in yanit[:30]:
        yanit = "Anlamadım, tekrar söyler misin?"
    if len(yanit) > 350:
        kes = yanit[:350]
        yanit = (kes.rsplit(".", 1)[0] + ".") if "." in kes else kes.rsplit(" ", 1)[0] + "..."

    hist.append({"role": "assistant", "content": yanit})
    hist[:] = hist[-10:]

    try:
        await msg.reply_text(yanit)
    except Exception:
        try:
            await context.bot.send_message(chat.id, yanit)
        except Exception as e:
            log.warning("AI send: %s", e)


async def hata(update, ctx):
    err = str(ctx.error or "")
    if "Conflict" in err and "getUpdates" in err:
        log.error(
            "CONFLICT: Ayni token baska yerde (Group Help / 2. instance). Token sadece burada."
        )
    else:
        log.warning("Hata: %s", ctx.error)


async def baslat(app):
    me = await app.bot.get_me()
    log.info("Bot hazir @%s id=%s", me.username, me.id)
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("ban", "Banla (yanıt / @user)"),
                BotCommand("unban", "Ban kaldır"),
                BotCommand("kick", "Gruptan at"),
                BotCommand("mute", "Sustur — /mute 30"),
                BotCommand("unmute", "Susturma kaldır"),
                BotCommand("warn", "Uyarı ver"),
                BotCommand("unwarn", "Uyarı sıfırla"),
                BotCommand("reload", "Admin listesi"),
                BotCommand("id", "Chat / user ID"),
            ]
        )
    except Exception as e:
        log.warning("set_commands: %s", e)


def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(baslat)
        .build()
    )
    app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
    app.add_handler(CommandHandler("ban", ban_komut))
    app.add_handler(CommandHandler("unban", unban_komut))
    app.add_handler(CommandHandler("kick", kick_komut))
    app.add_handler(CommandHandler("mute", mute_komut))
    app.add_handler(CommandHandler("unmute", unmute_komut))
    app.add_handler(CommandHandler("warn", warn_komut))
    app.add_handler(CommandHandler("unwarn", unwarn_komut))
    app.add_handler(CommandHandler("reload", reload_komut))
    app.add_handler(CommandHandler("id", id_komut))
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION)
            & (~filters.COMMAND)
            & filters.UpdateType.MESSAGE,
            mesaj,
        )
    )
    app.add_error_handler(hata)
    log.info("Polling basliyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
