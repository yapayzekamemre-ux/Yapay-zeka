# -*- coding: utf-8 -*-
"""
TurkPronim Yapay — AI sohbet + GroupHelp tarzi yonetim paneli
- AI: sadece "yapay" / bota yanit / ozel sohbet
- Panel: /ayarlar (admin) — hosgeldin, uyari, medya, engel, log...
- Fiyat: kisa token (btc, gram...)
- Render keep-alive
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
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatType, ChatMemberStatus

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
uyarilar = {}  # chat_id -> user_id -> count

# Varsayilan grup ayarlari (videodaki menuler)
DEFAULT_G = {
    "hosgeldin": False,
    "hosgeldin_metin": (
        "⛔ **{ad}** Hoşgeldiniz\n"
        "⚠️ Katıldığı andan itibaren 15 dakika boyunca mesaj gönderemez\n"
        "✅ 15 dakika sonra sohbeti başlatabilirsiniz. 🚀"
    ),
    "hosgeldin_sil": 15,  # saniye, 0=silme
    "hosgeldin_mute": 15,  # dakika mute, 0=yok
    "hoscaakal": False,
    "hoscaakal_metin": "👋 {ad} gruptan ayrıldı.",
    "hoscaakal_sil": 10,
    "servis_sil": True,  # katilim/cikis servis mesajlarini sil
    "kurallar": "Grup kurallarına uyun. Spam, küfür abartısı ve reklam yasak.",
    "warn_limit": 3,
    "warn_ceza": "mute",  # mute | kick | ban | none
    "warn_mute_dk": 60,
    "medya_engel": False,
    "medya_ceza": "sil",  # sil | warn | mute | ban
    "link_engel": False,
    "link_izin": [],  # serbest domain/link listesi
    "flood_adet": 0,  # 0=kapali
    "flood_sn": 5,
    "log_kanal": None,
    "gece_mod": False,
    "sessizlik": False,
}


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


def cget(chat_id, key, default=None):
    g = durum.setdefault("grup", {}).setdefault(str(chat_id), {})
    if key in g:
        return g[key]
    if default is not None:
        return default
    return DEFAULT_G.get(key)


def cset(chat_id, key, value):
    g = durum.setdefault("grup", {}).setdefault(str(chat_id), {})
    g[key] = value
    durum_kaydet()


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


async def admin_mi(chat_id, user, bot):
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
        s = (u.get("ad") or u.get("kullanici") or "?")[:20]
        parcalar.append(s + " " + str(u.get("mesaj", 0)) + " mesaj")
    return ", ".join(parcalar) if parcalar else "henuz yok"


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
    for model in ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"):
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
        "google",
        "gemini",
        "openai",
        "groq",
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


SAGLAYICILAR = [
    ("Groq", groq_sor),
    ("Gemini", gemini_sor),
    ("DeepSeek", deepseek_sor),
    ("Mistral", mistral_sor),
    ("OpenRouter", openrouter_sor),
]


def sor(mesajlar, ek="", arama=False):
    sistem = SISTEM + ek
    if arama:
        c = gemini_arama(mesajlar, sistem)
        if c:
            c = cevap_temizle(c)
            if c:
                return c
    for ad, fonk in SAGLAYICILAR:
        try:
            cevap = fonk(mesajlar, sistem)
            if cevap:
                cevap = cevap_temizle(cevap)
                if not cevap:
                    continue
                cevap = re.sub(r"\n{3,}", "\n\n", cevap).strip()
                if len(cevap) > 280:
                    kes = cevap[:260]
                    for sep in (". ", "! ", "? ", "\n"):
                        i = kes.rfind(sep)
                        if i > 80:
                            kes = kes[: i + 1]
                            break
                    else:
                        if " " in kes:
                            kes = kes.rsplit(" ", 1)[0]
                    cevap = kes.strip()
                return cevap
        except Exception as e:
            log.warning("%s coktu: %s", ad, e)
    return None


# ---------- fiyat ----------
KISA_FIYAT = re.compile(
    r"^\s*(?:(\d+(?:[.,]\d+)?)\s*)?([a-zA-ZğüşıöçĞÜŞİÖÇ]{2,12})\s*$",
    re.I,
)
ANA_TOKENLER = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ton": "the-open-network",
    "doge": "dogecoin",
    "ada": "cardano",
    "avax": "avalanche-2",
    "dot": "polkadot",
    "link": "chainlink",
    "matic": "matic-network",
    "shib": "shiba-inu",
    "pepe": "pepe",
    "sui": "sui",
    "gram": "the-open-network",
    "pengu": "pudgy-penguins",
}
SAYI_KELIME = {
    "tl",
    "try",
    "usd",
    "gb",
    "mb",
    "kg",
    "tane",
    "adet",
    "saat",
    "gun",
    "dk",
    "sn",
    "lira",
    "dolar",
    "euro",
}


def kisa_token(metin):
    m = KISA_FIYAT.match(metin or "")
    if not m:
        return None
    miktar_s, token = m.group(1), m.group(2)
    t = kucult(token)
    if t in SAYI_KELIME:
        return None
    if t not in ANA_TOKENLER and len(t) < 3:
        return None
    miktar = 1.0
    if miktar_s:
        try:
            miktar = float(miktar_s.replace(",", "."))
        except Exception:
            miktar = 1.0
    return (miktar, t)


def fiyat_cek(sembol):
    try:
        coin_id = ANA_TOKENLER.get(sembol, sembol)
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": "usd,try",
                "include_24hr_change": "true",
            },
            timeout=12,
        )
        if not r.ok:
            return None
        d = r.json().get(coin_id)
        if not d:
            return None
        return {
            "usd": d.get("usd"),
            "try": d.get("try"),
            "chg": d.get("usd_24h_change"),
            "id": coin_id,
        }
    except Exception as e:
        log.warning("fiyat_cek: %s", e)
        return None


async def fiyat_gonder(update, ctx, sembol, miktar=1.0):
    msg = update.effective_message
    data = await asyncio.to_thread(fiyat_cek, sembol)
    if not data or data.get("usd") is None:
        return False
    usd = data["usd"] * miktar
    try_p = (data.get("try") or 0) * miktar
    chg = data.get("chg")
    ok = "📈" if (chg or 0) >= 0 else "📉"
    chg_s = f"{chg:+.2f}%" if chg is not None else "?"
    metin = (
        f"💰 <b>{html.escape(sembol.upper())}</b>\n"
        f"💵 ${usd:,.4f}\n"
        f"₺ {try_p:,.2f}\n"
        f"{ok} 24s: {chg_s}"
    )
    if miktar != 1.0:
        metin = f"x{miktar:g} · " + metin
    try:
        await msg.reply_text(metin, parse_mode="HTML", do_quote=True)
        return True
    except Exception as e:
        log.warning("fiyat reply: %s", e)
        return False


# ---------- moderasyon yardimcilari ----------
async def log_gonder(bot, chat_id, metin):
    kid = cget(chat_id, "log_kanal")
    if not kid:
        return
    try:
        await bot.send_message(int(kid), metin, parse_mode="HTML")
    except Exception as e:
        log.warning("log: %s", e)


async def sil_sonra(bot, chat_id, message_id, sn):
    if not sn or sn <= 0:
        return
    await asyncio.sleep(sn)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def mute_uye(bot, chat_id, user_id, dakika):
    until = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(dakika)))
    perms = ChatPermissions(can_send_messages=False)
    await bot.restrict_chat_member(chat_id, user_id, permissions=perms, until_date=until)


async def unmute_uye(bot, chat_id, user_id):
    perms = ChatPermissions(
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
    await bot.restrict_chat_member(chat_id, user_id, permissions=perms)


async def warn_ekle(bot, chat_id, user, sebep=""):
    uid = str(user.id)
    ck = str(chat_id)
    uyarilar.setdefault(ck, {})
    uyarilar[ck][uid] = uyarilar[ck].get(uid, 0) + 1
    say = uyarilar[ck][uid]
    limit = int(cget(chat_id, "warn_limit") or 3)
    ad = html.escape(user.full_name or str(user.id))
    txt = f"⚠️ {ad} uyarı aldı ({say}/{limit})"
    if sebep:
        txt += f"\nSebep: {html.escape(sebep)}"
    if say >= limit:
        ceza = cget(chat_id, "warn_ceza") or "mute"
        if ceza == "mute":
            dk = int(cget(chat_id, "warn_mute_dk") or 60)
            try:
                await mute_uye(bot, chat_id, user.id, dk)
                txt += f"\n🔇 Limit aşıldı → {dk} dk mute"
            except Exception as e:
                txt += f"\nMute başarısız: {e}"
        elif ceza == "kick":
            try:
                await bot.ban_chat_member(chat_id, user.id)
                await bot.unban_chat_member(chat_id, user.id)
                txt += "\n👢 Limit aşıldı → gruptan atıldı"
            except Exception as e:
                txt += f"\nKick başarısız: {e}"
        elif ceza == "ban":
            try:
                await bot.ban_chat_member(chat_id, user.id)
                txt += "\n🚫 Limit aşıldı → ban"
            except Exception as e:
                txt += f"\nBan başarısız: {e}"
        uyarilar[ck][uid] = 0
    await log_gonder(bot, chat_id, txt)
    return txt


# ---------- panel ----------
def panel_ana(chat_id):
    hg = "✅" if cget(chat_id, "hosgeldin") else "❌"
    hc = "✅" if cget(chat_id, "hoscaakal") else "❌"
    md = "✅" if cget(chat_id, "medya_engel") else "❌"
    lk = "✅" if cget(chat_id, "link_engel") else "❌"
    sv = "✅" if cget(chat_id, "servis_sil") else "❌"
    logk = "✅" if cget(chat_id, "log_kanal") else "❌"
    kb = [
        [
            InlineKeyboardButton(f"👋 Hoş Geldin {hg}", callback_data="p:hg"),
            InlineKeyboardButton(f"👋 Hoşçakal {hc}", callback_data="p:hc"),
        ],
        [
            InlineKeyboardButton("📜 Kurallar", callback_data="p:kurallar"),
            InlineKeyboardButton("⚠️ Uyarılar", callback_data="p:uyari"),
        ],
        [
            InlineKeyboardButton(f"📷 Medya {md}", callback_data="p:medya"),
            InlineKeyboardButton(f"🔗 Link {lk}", callback_data="p:link"),
        ],
        [
            InlineKeyboardButton(f"🧹 Servis sil {sv}", callback_data="p:servis"),
            InlineKeyboardButton(f"📋 Log {logk}", callback_data="p:log"),
        ],
        [
            InlineKeyboardButton("🔇 Mute / Ban yardım", callback_data="p:modhelp"),
            InlineKeyboardButton("🔒 Kapat", callback_data="p:kapat"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


async def ayarlar_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat:
        return
    # komutu sil (gizli)
    try:
        await msg.delete()
    except Exception:
        pass
    if chat.type == ChatType.PRIVATE:
        # ozelde: global sahip paneli veya bilgi
        if not sahip_mi(user):
            return
        text = (
            "⚙️ <b>Yönetim</b>\n"
            "Grupta /ayarlar yazarak o grubun panelini aç.\n"
            "Özelde sadece sahip ayarları geçerlidir."
        )
        m = await context.bot.send_message(chat.id, text, parse_mode="HTML")
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 12))
        return
    if not await admin_mi(chat.id, user, context.bot):
        return
    text = (
        f"⚙️ <b>Ayarlar</b>\n"
        f"Grup: {html.escape(chat.title or '')}\n"
        f"Değiştirmek istediğin ayarı seç."
    )
    m = await context.bot.send_message(
        chat.id, text, parse_mode="HTML", reply_markup=panel_ana(chat.id)
    )
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 120))


async def rules_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.type == ChatType.PRIVATE:
        return
    try:
        await msg.delete()
    except Exception:
        pass
    kurallar = cget(chat.id, "kurallar") or DEFAULT_G["kurallar"]
    m = await context.bot.send_message(
        chat.id, f"📜 <b>Grup Kuralları</b>\n\n{html.escape(str(kurallar))}", parse_mode="HTML"
    )
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 60))


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("p:"):
        return
    await q.answer()
    chat = q.message.chat if q.message else None
    user = q.from_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    if not await admin_mi(chat.id, user, context.bot):
        await q.answer("Yetkin yok", show_alert=True)
        return
    data = q.data[2:]
    cid = chat.id

    if data == "kapat":
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    if data == "hg":
        cur = bool(cget(cid, "hosgeldin"))
        cset(cid, "hosgeldin", not cur)
        durum = "AÇIK ✅" if not cur else "KAPALI ❌"
        await q.edit_message_text(
            f"👋 Hoş geldin mesajı: <b>{durum}</b>\n"
            f"Süre (sil): {cget(cid, 'hosgeldin_sil')} sn\n"
            f"Mute: {cget(cid, 'hosgeldin_mute')} dk\n\n"
            f"Metni değiştirmek için gruba yaz:\n"
            f"<code>/setwelcome metin { '{ad}' } ...</code>",
            parse_mode="HTML",
            reply_markup=panel_ana(cid),
        )
        return

    if data == "hc":
        cur = bool(cget(cid, "hoscaakal"))
        cset(cid, "hoscaakal", not cur)
        durum = "AÇIK ✅" if not cur else "KAPALI ❌"
        await q.edit_message_text(
            f"👋 Hoşçakal: <b>{durum}</b>",
            parse_mode="HTML",
            reply_markup=panel_ana(cid),
        )
        return

    if data == "servis":
        cur = bool(cget(cid, "servis_sil"))
        cset(cid, "servis_sil", not cur)
        durum = "AÇIK ✅" if not cur else "KAPALI ❌"
        await q.edit_message_text(
            f"🧹 Servis mesajı silme: <b>{durum}</b>",
            parse_mode="HTML",
            reply_markup=panel_ana(cid),
        )
        return

    if data == "medya":
        cur = bool(cget(cid, "medya_engel"))
        cset(cid, "medya_engel", not cur)
        durum = "AÇIK ✅" if not cur else "KAPALI ❌"
        await q.edit_message_text(
            f"📷 Medya engeli: <b>{durum}</b>\n(açıkken normal üyelerin foto/video/sticker silinir)",
            parse_mode="HTML",
            reply_markup=panel_ana(cid),
        )
        return

    if data == "link":
        cur = bool(cget(cid, "link_engel"))
        cset(cid, "link_engel", not cur)
        durum = "AÇIK ✅" if not cur else "KAPALI ❌"
        await q.edit_message_text(
            f"🔗 Link engeli: <b>{durum}</b>\n"
            f"İzinli link ekle: <code>/izinlink ornek.com</code>",
            parse_mode="HTML",
            reply_markup=panel_ana(cid),
        )
        return

    if data == "uyari":
        limit = cget(cid, "warn_limit")
        ceza = cget(cid, "warn_ceza")
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Limit 2", callback_data="p:wl2"),
                    InlineKeyboardButton("Limit 3", callback_data="p:wl3"),
                    InlineKeyboardButton("Limit 5", callback_data="p:wl5"),
                ],
                [
                    InlineKeyboardButton("Ceza: Mute", callback_data="p:wc_mute"),
                    InlineKeyboardButton("Ceza: Kick", callback_data="p:wc_kick"),
                    InlineKeyboardButton("Ceza: Ban", callback_data="p:wc_ban"),
                ],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]
        )
        await q.edit_message_text(
            f"⚠️ <b>Uyarılar</b>\nLimit: {limit}\nCeza: {ceza}\n"
            f"Kullanım: birine yanıtla <code>/warn sebep</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data.startswith("wl"):
        cset(cid, "warn_limit", int(data[2:]))
        await q.answer(f"Limit {data[2:]}")
        await q.edit_message_reply_markup(reply_markup=panel_ana(cid))
        return

    if data.startswith("wc_"):
        cset(cid, "warn_ceza", data[3:])
        await q.answer(f"Ceza: {data[3:]}")
        await q.edit_message_reply_markup(reply_markup=panel_ana(cid))
        return

    if data == "kurallar":
        kurallar = cget(cid, "kurallar") or DEFAULT_G["kurallar"]
        await q.edit_message_text(
            f"📜 <b>Kurallar</b>\n\n{html.escape(str(kurallar))}\n\n"
            f"Değiştir: <code>/setrules metin...</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return

    if data == "log":
        await q.edit_message_text(
            "📋 Log kanalı ayarla:\n"
            "1) Botu log kanalına admin ekle\n"
            "2) Kanalda <code>/setlog</code> yaz\n"
            "Kaldır: <code>/unsetlog</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return

    if data == "modhelp":
        await q.edit_message_text(
            "🔇 <b>Moderasyon komutları</b> (yanıtla veya id)\n"
            "<code>/mute 30</code> — 30 dk sustur\n"
            "<code>/unmute</code>\n"
            "<code>/ban</code>\n"
            "<code>/unban</code>\n"
            "<code>/kick</code>\n"
            "<code>/warn sebep</code>\n"
            "<code>/unwarn</code>\n"
            "Komutlar 8 sn sonra silinir.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return

    if data == "geri":
        await q.edit_message_text(
            f"⚙️ <b>Ayarlar</b>\nGrup: {html.escape(chat.title or '')}",
            parse_mode="HTML",
            reply_markup=panel_ana(cid),
        )
        return


# ---------- admin komutlari ----------
async def _hedef_kullanici(update, context):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user
    if context.args:
        a = context.args[0]
        if a.isdigit():
            class U:
                id = int(a)
                full_name = a
                username = ""

            return U()
    return None


async def komut_gizle(msg, bot, sn=8):
    try:
        await msg.delete()
    except Exception:
        pass


async def mute_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    dk = 30
    if context.args:
        for a in context.args:
            if a.isdigit():
                dk = int(a)
                break
    try:
        await mute_uye(context.bot, chat.id, hedef.id, dk)
        t = f"🔇 {html.escape(hedef.full_name or str(hedef.id))} {dk} dk susturuldu"
        m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))
        await log_gonder(context.bot, chat.id, t)
    except Exception as e:
        log.warning("mute: %s", e)


async def unmute_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    try:
        await unmute_uye(context.bot, chat.id, hedef.id)
        t = f"🔊 {html.escape(hedef.full_name or str(hedef.id))} susturma kalktı"
        m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))
    except Exception as e:
        log.warning("unmute: %s", e)


async def ban_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    try:
        await context.bot.ban_chat_member(chat.id, hedef.id)
        t = f"🚫 {html.escape(hedef.full_name or str(hedef.id))} banlandı"
        m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))
        await log_gonder(context.bot, chat.id, t)
    except Exception as e:
        log.warning("ban: %s", e)


async def unban_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    try:
        await context.bot.unban_chat_member(chat.id, hedef.id)
        t = f"✅ Ban kaldırıldı: {html.escape(hedef.full_name or str(hedef.id))}"
        m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))
    except Exception as e:
        log.warning("unban: %s", e)


async def kick_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    try:
        await context.bot.ban_chat_member(chat.id, hedef.id)
        await context.bot.unban_chat_member(chat.id, hedef.id)
        t = f"👢 {html.escape(hedef.full_name or str(hedef.id))} atıldı"
        m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))
        await log_gonder(context.bot, chat.id, t)
    except Exception as e:
        log.warning("kick: %s", e)


async def warn_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    sebep = " ".join(context.args[1:] if context.args and context.args[0].isdigit() else context.args) if context.args else ""
    if msg.reply_to_message and context.args:
        sebep = " ".join(context.args)
    t = await warn_ekle(context.bot, chat.id, hedef, sebep)
    m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 12))


async def unwarn_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    hedef = await _hedef_kullanici(update, context)
    if not hedef:
        return
    ck, uid = str(chat.id), str(hedef.id)
    if ck in uyarilar and uid in uyarilar[ck]:
        uyarilar[ck][uid] = max(0, uyarilar[ck][uid] - 1)
    t = f"✅ Uyarı silindi: {html.escape(hedef.full_name or str(hedef.id))}"
    m = await context.bot.send_message(chat.id, t, parse_mode="HTML")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))


async def setwelcome_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    metin = msg.text.split(None, 1)
    if len(metin) < 2:
        return
    cset(chat.id, "hosgeldin_metin", metin[1])
    cset(chat.id, "hosgeldin", True)
    m = await context.bot.send_message(chat.id, "✅ Karşılama metni kaydedildi")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 8))


async def setrules_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    metin = msg.text.split(None, 1)
    if len(metin) < 2:
        return
    cset(chat.id, "kurallar", metin[1])
    m = await context.bot.send_message(chat.id, "✅ Kurallar kaydedildi")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 8))


async def setlog_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot) and not sahip_mi(user):
        return
    # log kanali: komutun yazildigi chat
    # grup icin log ayarlamak: hedef grup id arguman veya yanit
    hedef = chat.id
    if context.args and context.args[0].lstrip("-").isdigit():
        hedef = int(context.args[0])
    cset(hedef, "log_kanal", chat.id)
    m = await context.bot.send_message(
        chat.id, f"✅ Log kanalı ayarlandı (grup {hedef} → bu chat)"
    )
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))


async def unsetlog_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    cset(chat.id, "log_kanal", None)
    m = await context.bot.send_message(chat.id, "✅ Log kaldırıldı")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 8))


async def izinlink_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    if not context.args:
        return
    lst = list(cget(chat.id, "link_izin") or [])
    for a in context.args:
        a = a.lower().strip()
        if a and a not in lst:
            lst.append(a)
    cset(chat.id, "link_izin", lst)
    m = await context.bot.send_message(chat.id, f"✅ İzinli linkler: {', '.join(lst)}")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))


# ---------- hosgeldin / ayrildi ----------
async def hosgeldin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or not msg.new_chat_members:
        return
    if cget(chat.id, "servis_sil"):
        try:
            await msg.delete()
        except Exception:
            pass
    if not cget(chat.id, "hosgeldin"):
        return
    metin_sablon = cget(chat.id, "hosgeldin_metin") or DEFAULT_G["hosgeldin_metin"]
    mute_dk = int(cget(chat.id, "hosgeldin_mute") or 0)
    sil_sn = int(cget(chat.id, "hosgeldin_sil") or 0)
    for u in msg.new_chat_members:
        if u.is_bot:
            continue
        uye_kaydi(chat.id, u, say=False)
        ad = u.full_name or u.username or str(u.id)
        metin = (
            metin_sablon.replace("{ad}", ad)
            .replace("{KullanıcıAdı}", ad)
            .replace("{username}", f"@{u.username}" if u.username else ad)
        )
        try:
            gonder = await context.bot.send_message(
                chat.id, metin, parse_mode="Markdown"
            )
            if sil_sn > 0:
                asyncio.create_task(
                    sil_sonra(context.bot, chat.id, gonder.message_id, sil_sn)
                )
        except Exception:
            try:
                gonder = await context.bot.send_message(chat.id, metin)
                if sil_sn > 0:
                    asyncio.create_task(
                        sil_sonra(context.bot, chat.id, gonder.message_id, sil_sn)
                    )
            except Exception as e:
                log.warning("hosgeldin: %s", e)
        if mute_dk > 0:
            try:
                await mute_uye(context.bot, chat.id, u.id, mute_dk)
            except Exception as e:
                log.warning("hosgeldin mute: %s", e)
        await log_gonder(
            context.bot,
            chat.id,
            f"➕ {html.escape(ad)} gruba katıldı",
        )


async def ayrildi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or not msg.left_chat_member:
        return
    if cget(chat.id, "servis_sil"):
        try:
            await msg.delete()
        except Exception:
            pass
    u = msg.left_chat_member
    if u.is_bot:
        return
    ad = u.full_name or u.username or str(u.id)
    await log_gonder(
        context.bot, chat.id, f"➖ {html.escape(ad)} gruptan ayrıldı"
    )
    if not cget(chat.id, "hoscaakal"):
        return
    metin_sablon = cget(chat.id, "hoscaakal_metin") or DEFAULT_G["hoscaakal_metin"]
    metin = metin_sablon.replace("{ad}", ad)
    sil_sn = int(cget(chat.id, "hoscaakal_sil") or 0)
    try:
        gonder = await context.bot.send_message(chat.id, metin)
        if sil_sn > 0:
            asyncio.create_task(
                sil_sonra(context.bot, chat.id, gonder.message_id, sil_sn)
            )
    except Exception as e:
        log.warning("hoscaakal: %s", e)


# ---------- sahip yakala + mesaj ----------
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


LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)", re.I)


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

    # medya engeli
    if (
        not ozel
        and cget(cid, "medya_engel")
        and user
        and not await admin_mi(cid, user, context.bot)
    ):
        if msg.photo or msg.video or msg.animation or msg.sticker or msg.document:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # link engeli
    if (
        not ozel
        and cget(cid, "link_engel")
        and metin
        and user
        and not await admin_mi(cid, user, context.bot)
    ):
        if LINK_RE.search(metin):
            izin = [x.lower() for x in (cget(cid, "link_izin") or [])]
            ok = any(x in metin.lower() for x in izin) if izin else False
            if not ok:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

    if not metin:
        return

    if user:
        kayit = uye_kaydi(cid, user)
    else:
        kayit = {"mesaj": 0}

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

    # fiyat
    kt = kisa_token(metin)
    if kt and kt[1] in ANA_TOKENLER:
        ok = await fiyat_gonder(update, context, kt[1], kt[0])
        if ok:
            return

    # AI cagri
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

    try:
        await context.bot.send_chat_action(cid, "typing")
    except Exception:
        pass

    ad = (user.full_name if user else "") or "dostum"
    ek = f" Konusan kisi: {ad}."
    if sahip_mi(user):
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
            and msg.reply_to_message.from_user.id == context.bot.id
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
        if len(yanit) > 280:
            kes = yanit[:260]
            for sep in (". ", "! ", "? "):
                i = kes.rfind(sep)
                if i > 80:
                    kes = kes[: i + 1]
                    break
            else:
                if " " in kes:
                    kes = kes.rsplit(" ", 1)[0]
            yanit = kes.strip()
        h.append({"role": "assistant", "content": yanit})
    gecmis[anahtar] = h[-30:]

    try:
        await msg.reply_text(yanit, do_quote=True)
    except Exception as e:
        log.warning("AI reply: %s", e)
        try:
            await context.bot.send_message(cid, yanit)
        except Exception as e2:
            log.warning("AI send: %s", e2)


async def hata(update, ctx):
    log.warning("Hata: %s", ctx.error)


async def baslat(app):
    me = await app.bot.get_me()
    log.info("Bot hazir: @%s", me.username)
    try:
        # sadece adminlerin gorecegi komutlar; menuyu bos birak (gizli kalsin)
        await app.bot.set_my_commands([])
    except Exception:
        pass


app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(baslat).build()

app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
app.add_handler(CommandHandler("ayarlar", ayarlar_komut))
app.add_handler(CommandHandler("settings", ayarlar_komut))
app.add_handler(CommandHandler("rules", rules_komut))
app.add_handler(CommandHandler("kurallar", rules_komut))
app.add_handler(CommandHandler("mute", mute_komut))
app.add_handler(CommandHandler("unmute", unmute_komut))
app.add_handler(CommandHandler("ban", ban_komut))
app.add_handler(CommandHandler("unban", unban_komut))
app.add_handler(CommandHandler("kick", kick_komut))
app.add_handler(CommandHandler("warn", warn_komut))
app.add_handler(CommandHandler("unwarn", unwarn_komut))
app.add_handler(CommandHandler("setwelcome", setwelcome_komut))
app.add_handler(CommandHandler("setrules", setrules_komut))
app.add_handler(CommandHandler("setlog", setlog_komut))
app.add_handler(CommandHandler("unsetlog", unsetlog_komut))
app.add_handler(CommandHandler("izinlink", izinlink_komut))
app.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^p:"))
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, hosgeldin))
app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, ayrildi))
app.add_handler(
    MessageHandler(
        (filters.TEXT | filters.CAPTION)
        & (~filters.COMMAND)
        & filters.UpdateType.MESSAGE,
        mesaj,
    )
)
app.add_error_handler(hata)

log.info("Bot basliyor (AI + panel + moderasyon)...")
app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
