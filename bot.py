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

# Varsayilan grup ayarlari — GroupHelpBot / video bire bir
DEFAULT_G = {
    # Hos geldin / hoscaakal
    "hosgeldin": False,
    "hosgeldin_metin": (
        "⛔ **{ad}** Hoşgeldiniz\n"
        "⚠️ Katıldığı andan itibaren 15 dakika boyunca mesaj gönderemez\n"
        "✅ 15 dakika sonra sohbeti başlatabilirsiniz. 🚀"
    ),
    "hosgeldin_sil": 15,
    "hosgeldin_mute": 15,
    "hosgeldin_mod": "her",  # her | ilk
    "hoscaakal": False,
    "hoscaakal_metin": "👋 {ad} gruptan ayrıldı.",
    "hoscaakal_sil": 10,
    "hoscaakal_ozel": False,
    # Servis
    "servis_sil": True,
    "servis_katilim": True,
    "servis_cikis": True,
    "servis_foto": False,
    "servis_baslik": False,
    "servis_pin": False,
    # Kurallar / uyari
    "kurallar": "Grup kurallarına uyun. Spam, küfür abartısı ve reklam yasak.",
    "warn_limit": 3,
    "warn_ceza": "mute",
    "warn_mute_dk": 60,
    # Medya (tur bazli)
    "medya_engel": False,
    "medya_foto": True,
    "medya_video": True,
    "medya_gif": True,
    "medya_sticker": True,
    "medya_dosya": True,
    "medya_ses": False,
    "medya_ceza": "sil",
    # Link / flood
    "link_engel": False,
    "link_izin": [],
    "flood_adet": 0,
    "flood_sn": 5,
    # Log / gece / sessizlik
    "log_kanal": None,
    "gece_mod": False,
    "gece_bas": 0,
    "gece_bit": 7,
    "sessizlik": False,
    # Engellemeler / zorunluluk
    "zorunlu_username": False,
    "zorunlu_foto": False,
    "zorunlu_soyisim": False,
    "engel_arap": False,
    "engel_cin": False,
    "engel_rus": False,
    "bot_engel": True,
    # Mesaj uzunlugu
    "mesaj_min": 0,
    "mesaj_max": 0,
    # Alfabeler
    "alfa_kiril": False,
    "alfa_cin": False,
    "alfa_latin": False,
    "alfa_arap": False,
    "alfa_hint": False,
    "alfa_bengali": False,
    # Diger
    "yasakli_kelimeler": [],
    "anti_spam": False,
    "porno_engel": False,
    "admin_etiket": True,  # @admin yazinca yoneticilere bildir
    "grup_link": "",
    "onay_modu": False,
    "tekrar_engel": False,
    "tag_acik": False,
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


# ---------- panel (ozel sohbette acilir) ----------
def _ok(v):
    return "✅" if v else "❌"


def panel_ana(chat_id, baslik=""):
    """Ana panel — GroupHelpBot video bire bir duzen."""
    hg = _ok(cget(chat_id, "hosgeldin"))
    hc = _ok(cget(chat_id, "hoscaakal"))
    fl = _ok(int(cget(chat_id, "flood_adet") or 0) > 0)
    md = _ok(cget(chat_id, "medya_engel"))
    gm = _ok(cget(chat_id, "gece_mod"))
    po = _ok(cget(chat_id, "porno_engel"))
    om = _ok(cget(chat_id, "onay_modu"))
    kb = [
        [
            InlineKeyboardButton(f"💬 Hoş Geldin {hg}", callback_data="p:hg"),
            InlineKeyboardButton(f"🌊 Flood {fl}", callback_data="p:flood"),
        ],
        [
            InlineKeyboardButton(f"👋 Hoşçakal {hc}", callback_data="p:hc"),
            InlineKeyboardButton("🕉 Alfabeler", callback_data="p:alfa"),
        ],
        [
            InlineKeyboardButton("🧠 Doğrulama", callback_data="p:dogrula"),
            InlineKeyboardButton("🔦 Kontroller", callback_data="p:kontrol"),
        ],
        [
            InlineKeyboardButton("🆘 @admin", callback_data="p:adminet"),
            InlineKeyboardButton("🔒 Engellemeler", callback_data="p:engel"),
        ],
        [
            InlineKeyboardButton(f"📷 Medya {md}", callback_data="p:medya"),
            InlineKeyboardButton(f"🔞 Porno {po}", callback_data="p:porno"),
        ],
        [
            InlineKeyboardButton("⚠️ Uyarılar", callback_data="p:uyari"),
            InlineKeyboardButton(f"🌙 Gece {gm}", callback_data="p:gece"),
        ],
        [
            InlineKeyboardButton("🔔 Tag", callback_data="p:tag"),
            InlineKeyboardButton("🔗 Grup Linki", callback_data="p:gruplink"),
        ],
        [
            InlineKeyboardButton(f"📋 Onay Modu {om}", callback_data="p:onay"),
            InlineKeyboardButton("🗑 Servis/Silme", callback_data="p:servis"),
        ],
        [
            InlineKeyboardButton("▶️ Diğerleri", callback_data="p:diger"),
            InlineKeyboardButton("✅ Kapat", callback_data="p:kapat"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


def panel_diger(chat_id):
    """Videodaki 'Diğerleri' alt menusu."""
    lk = _ok(cget(chat_id, "link_engel"))
    ss = _ok(cget(chat_id, "sessizlik"))
    logk = _ok(cget(chat_id, "log_kanal"))
    as_ = _ok(cget(chat_id, "anti_spam"))
    kb = [
        [
            InlineKeyboardButton("📜 Kurallar", callback_data="p:kurallar"),
            InlineKeyboardButton(f"🛡 Anti-Spam {as_}", callback_data="p:antispam"),
        ],
        [
            InlineKeyboardButton(f"🔗 Link engeli {lk}", callback_data="p:link"),
            InlineKeyboardButton(f"🔇 Sessizlik {ss}", callback_data="p:sessizlik"),
        ],
        [
            InlineKeyboardButton("📏 Mesaj uzunluğu", callback_data="p:uzunluk"),
            InlineKeyboardButton("🚫 Yasaklı kelimeler", callback_data="p:yasakli"),
        ],
        [
            InlineKeyboardButton(f"📋 Log {logk}", callback_data="p:log"),
            InlineKeyboardButton("👥 Üye yönetimi", callback_data="p:uye"),
        ],
        [
            InlineKeyboardButton("🔁 Tekrarlanan mesaj", callback_data="p:tekrar"),
            InlineKeyboardButton("🔧 Mute/Ban yardım", callback_data="p:modhelp"),
        ],
        [InlineKeyboardButton("« Ana menü", callback_data="p:geri")],
    ]
    return InlineKeyboardMarkup(kb)


def panel_metin(chat_id, baslik=""):
    title = baslik or f"Grup {chat_id}"
    return (
        f"⚙️ <b>Ayarlar</b>\n"
        f"Grup: <b>{html.escape(str(title))}</b>\n"
        f"Değiştirmek istediğin ayarı seç.\n"
        f"<i>Panel sadece sana özel açılır.</i>"
    )


async def ayarlar_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/panel /ayarlar — grupta yazilir, panel OZEL sohbette acilir."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    try:
        await msg.delete()
    except Exception:
        pass

    # Ozel sohbette: son secilen grubu goster veya bilgi ver
    if chat.type == ChatType.PRIVATE:
        gid = context.user_data.get("panel_gid")
        gtitle = context.user_data.get("panel_gtitle") or ""
        if gid and await admin_mi(gid, user, context.bot):
            text = panel_metin(gid, gtitle)
            await context.bot.send_message(
                user.id, text, parse_mode="HTML", reply_markup=panel_ana(gid, gtitle)
            )
            return
        await context.bot.send_message(
            user.id,
            "⚙️ <b>Yönetim paneli</b>\n\n"
            "Bir gruba git → <code>/panel</code> veya <code>/ayarlar</code> yaz.\n"
            "Panel burada (özel sohbette) açılır.\n"
            "Botu özelde en az bir kez <code>/start</code> ile başlatmış olmalısın.",
            parse_mode="HTML",
        )
        return

    # Grupta: admin kontrol + ozel sohbete panel gonder
    if not await admin_mi(chat.id, user, context.bot):
        return

    context.user_data["panel_gid"] = chat.id
    context.user_data["panel_gtitle"] = chat.title or str(chat.id)
    text = panel_metin(chat.id, chat.title)

    try:
        await context.bot.send_message(
            user.id,
            text,
            parse_mode="HTML",
            reply_markup=panel_ana(chat.id, chat.title),
        )
    except Exception as e:
        # Bot ozelde yazamiyorsa gruba kisa uyari
        log.warning("panel ozel gonderilemedi: %s", e)
        m = await context.bot.send_message(
            chat.id,
            f"{user.mention_html()}, paneli açmak için bota özelden <code>/start</code> yaz, "
            f"sonra gruba tekrar <code>/panel</code> yaz.",
            parse_mode="HTML",
        )
        asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 12))


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
        chat.id,
        f"📜 <b>Grup Kuralları</b>\n\n{html.escape(str(kurallar))}",
        parse_mode="HTML",
    )
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 60))


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("p:"):
        return
    user = q.from_user
    if not user:
        return

    # Panel ozel sohbette; grup id user_data'dan
    cid = context.user_data.get("panel_gid")
    gtitle = context.user_data.get("panel_gtitle") or ""
    if not cid:
        await q.answer("Önce grupta /panel yaz", show_alert=True)
        return
    if not await admin_mi(cid, user, context.bot):
        await q.answer("Yetkin yok", show_alert=True)
        return

    await q.answer()
    data = q.data[2:]

    async def yenile(ek=""):
        t = panel_metin(cid, gtitle)
        if ek:
            t = ek + "\n\n" + t
        try:
            await q.edit_message_text(
                t, parse_mode="HTML", reply_markup=panel_ana(cid, gtitle)
            )
        except Exception:
            pass

    if data == "kapat":
        try:
            await q.message.delete()
        except Exception:
            pass
        return

    if data == "geri":
        await yenile()
        return

    # --- Hos geldin ---
    if data == "hg":
        cur = bool(cget(cid, "hosgeldin"))
        cset(cid, "hosgeldin", not cur)
        durum = "AÇIK ✅" if not cur else "KAPALI ❌"
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Sil: 5sn", callback_data="p:hgs5"),
                    InlineKeyboardButton("Sil: 15sn", callback_data="p:hgs15"),
                    InlineKeyboardButton("Sil: 30sn", callback_data="p:hgs30"),
                ],
                [
                    InlineKeyboardButton("Mute: 0", callback_data="p:hgm0"),
                    InlineKeyboardButton("Mute: 15dk", callback_data="p:hgm15"),
                    InlineKeyboardButton("Mute: 60dk", callback_data="p:hgm60"),
                ],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]
        )
        await q.edit_message_text(
            f"👋 Hoş geldin: <b>{durum}</b>\n"
            f"Silme: {cget(cid, 'hosgeldin_sil')} sn | Mute: {cget(cid, 'hosgeldin_mute')} dk\n\n"
            f"Metin değiştir (grupta):\n"
            f"<code>/setwelcome metin {{ad}} ...</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data.startswith("hgs"):
        cset(cid, "hosgeldin_sil", int(data[3:]))
        await q.answer(f"Silme {data[3:]} sn")
        await yenile(f"✅ Hoş geldin silme: {data[3:]} sn")
        return

    if data.startswith("hgm"):
        cset(cid, "hosgeldin_mute", int(data[3:]))
        await q.answer(f"Mute {data[3:]} dk")
        await yenile(f"✅ Hoş geldin mute: {data[3:]} dk")
        return

    # --- Hoscaakal ---
    if data == "hc":
        cur = bool(cget(cid, "hoscaakal"))
        cset(cid, "hoscaakal", not cur)
        await yenile(f"👋 Hoşçakal: {'AÇIK ✅' if not cur else 'KAPALI ❌'}")
        return

    # --- Servis ---
    if data == "servis":
        cur = bool(cget(cid, "servis_sil"))
        cset(cid, "servis_sil", not cur)
        await yenile(f"🧹 Servis sil: {'AÇIK ✅' if not cur else 'KAPALI ❌'}")
        return

    # --- Medya (genel + alt turler) ---
    if data == "medya":
        cur = bool(cget(cid, "medya_engel"))
        cset(cid, "medya_engel", not cur)
        acik = not cur
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Foto {_ok(cget(cid, 'medya_foto'))}", callback_data="p:mf"
                    ),
                    InlineKeyboardButton(
                        f"Video {_ok(cget(cid, 'medya_video'))}", callback_data="p:mv"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"GIF {_ok(cget(cid, 'medya_gif'))}", callback_data="p:mg"
                    ),
                    InlineKeyboardButton(
                        f"Sticker {_ok(cget(cid, 'medya_sticker'))}", callback_data="p:ms"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Dosya {_ok(cget(cid, 'medya_dosya'))}", callback_data="p:md"
                    ),
                    InlineKeyboardButton(
                        f"Ses {_ok(cget(cid, 'medya_ses'))}", callback_data="p:me"
                    ),
                ],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]
        )
        await q.edit_message_text(
            f"📷 Medya engeli: <b>{'AÇIK ✅' if acik else 'KAPALI ❌'}</b>\n"
            f"Açıkken seçili türler normal üyelerde silinir.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    medya_map = {
        "mf": "medya_foto",
        "mv": "medya_video",
        "mg": "medya_gif",
        "ms": "medya_sticker",
        "md": "medya_dosya",
        "me": "medya_ses",
    }
    if data in medya_map:
        k = medya_map[data]
        cset(cid, k, not bool(cget(cid, k)))
        await q.answer(f"{k}: {_ok(cget(cid, k))}")
        # alt menuyu yenile
        q.data = "p:medya"
        # basit yenileme
        await yenile(f"📷 {k} = {_ok(cget(cid, k))}")
        return

    # --- Link ---
    if data == "link":
        cur = bool(cget(cid, "link_engel"))
        cset(cid, "link_engel", not cur)
        await yenile(
            f"🔗 Link engeli: {'AÇIK ✅' if not cur else 'KAPALI ❌'}\n"
            f"İzinli ekle (grupta): <code>/izinlink ornek.com</code>"
        )
        return

    # --- Uyari ---
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
            f"⚠️ <b>Uyarılar</b>\nLimit: {limit} | Ceza: {ceza}\n"
            f"Grupta yanıtla: <code>/warn sebep</code>",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data.startswith("wl"):
        cset(cid, "warn_limit", int(data[2:]))
        await q.answer(f"Limit {data[2:]}")
        await yenile(f"⚠️ Uyarı limiti: {data[2:]}")
        return

    if data.startswith("wc_"):
        cset(cid, "warn_ceza", data[3:])
        await q.answer(f"Ceza: {data[3:]}")
        await yenile(f"⚠️ Uyarı cezası: {data[3:]}")
        return

    # --- Kurallar ---
    if data == "kurallar":
        kurallar = cget(cid, "kurallar") or DEFAULT_G["kurallar"]
        await q.edit_message_text(
            f"📜 <b>Kurallar</b>\n\n{html.escape(str(kurallar))}\n\n"
            f"Değiştir (grupta): <code>/setrules metin...</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return

    # --- Log ---
    if data == "log":
        mevcut = cget(cid, "log_kanal")
        await q.edit_message_text(
            f"📋 <b>Log kanalı</b>\n"
            f"Şu an: <code>{mevcut or 'yok'}</code>\n\n"
            f"1) Botu log kanalına admin ekle\n"
            f"2) O kanalda <code>/setlog {cid}</code> yaz\n"
            f"Kaldır: grupta <code>/unsetlog</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return

    # --- Flood ---
    if data == "flood":
        adet = int(cget(cid, "flood_adet") or 0)
        sn = int(cget(cid, "flood_sn") or 5)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Kapalı", callback_data="p:fl0"),
                    InlineKeyboardButton("5 / 5sn", callback_data="p:fl5"),
                    InlineKeyboardButton("8 / 5sn", callback_data="p:fl8"),
                ],
                [
                    InlineKeyboardButton("10 / 10sn", callback_data="p:fl10"),
                    InlineKeyboardButton("« Geri", callback_data="p:geri"),
                ],
            ]
        )
        await q.edit_message_text(
            f"🌊 <b>Flood önleyici</b>\n"
            f"Şu an: {adet or 'kapalı'} mesaj / {sn} sn\n"
            f"Aşınca mesaj silinir + uyarı.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data.startswith("fl"):
        n = int(data[2:])
        cset(cid, "flood_adet", n)
        if n > 0:
            cset(cid, "flood_sn", 5 if n < 10 else 10)
        await q.answer(f"Flood: {n or 'kapalı'}")
        await yenile(f"🌊 Flood: {n or 'kapalı'}")
        return

    # --- Gece mod ---
    if data == "gece":
        cur = bool(cget(cid, "gece_mod"))
        cset(cid, "gece_mod", not cur)
        await yenile(
            f"🌙 Gece modu: {'AÇIK ✅' if not cur else 'KAPALI ❌'}\n"
            f"(00:00–07:00 sadece admin yazabilir — ileride aktif)"
        )
        return

    # --- Sessizlik ---
    if data == "sessizlik":
        cur = bool(cget(cid, "sessizlik"))
        cset(cid, "sessizlik", not cur)
        await yenile(
            f"🔇 Sessizlik: {'AÇIK ✅' if not cur else 'KAPALI ❌'}\n"
            f"(açıkken normal üyeler yazamaz)"
        )
        return

    # --- Engellemeler (video) ---
    if data == "engel":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Username {_ok(cget(cid, 'zorunlu_username'))}",
                        callback_data="p:zu",
                    ),
                    InlineKeyboardButton(
                        f"Profil foto {_ok(cget(cid, 'zorunlu_foto'))}",
                        callback_data="p:zf",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Soyisim {_ok(cget(cid, 'zorunlu_soyisim'))}",
                        callback_data="p:zs",
                    ),
                    InlineKeyboardButton(
                        f"Bot engeli {_ok(cget(cid, 'bot_engel'))}",
                        callback_data="p:be",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Arapça isim {_ok(cget(cid, 'engel_arap'))}",
                        callback_data="p:ea",
                    ),
                    InlineKeyboardButton(
                        f"Çince isim {_ok(cget(cid, 'engel_cin'))}",
                        callback_data="p:ec",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Rusça isim {_ok(cget(cid, 'engel_rus'))}",
                        callback_data="p:er",
                    ),
                ],
                [InlineKeyboardButton("« Ana menü", callback_data="p:geri")],
            ]
        )
        await q.edit_message_text(
            "🔒 <b>Engellemeler</b>\n"
            "Zorunluluklar + isim engelleri.\n"
            "Açık kurallar gruba girişte / mesajda uygulanır.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data == "zu":
        cset(cid, "zorunlu_username", not bool(cget(cid, "zorunlu_username")))
        await q.answer("Username")
        await yenile(f"Username zorunlu: {_ok(cget(cid, 'zorunlu_username'))}")
        return
    if data == "zf":
        cset(cid, "zorunlu_foto", not bool(cget(cid, "zorunlu_foto")))
        await q.answer("Profil foto")
        await yenile(f"Profil foto zorunlu: {_ok(cget(cid, 'zorunlu_foto'))}")
        return
    if data == "zs":
        cset(cid, "zorunlu_soyisim", not bool(cget(cid, "zorunlu_soyisim")))
        await q.answer("Soyisim")
        await yenile(f"Soyisim zorunlu: {_ok(cget(cid, 'zorunlu_soyisim'))}")
        return
    if data == "be":
        cset(cid, "bot_engel", not bool(cget(cid, "bot_engel")))
        await q.answer("Bot engeli")
        await yenile(f"Bot engeli: {_ok(cget(cid, 'bot_engel'))}")
        return
    if data == "ea":
        cset(cid, "engel_arap", not bool(cget(cid, "engel_arap")))
        await q.answer("Arapça isim")
        await yenile(f"Arapça isim engeli: {_ok(cget(cid, 'engel_arap'))}")
        return
    if data == "ec":
        cset(cid, "engel_cin", not bool(cget(cid, "engel_cin")))
        await q.answer("Çince isim")
        await yenile(f"Çince isim engeli: {_ok(cget(cid, 'engel_cin'))}")
        return
    if data == "er":
        cset(cid, "engel_rus", not bool(cget(cid, "engel_rus")))
        await q.answer("Rusça isim")
        await yenile(f"Rusça isim engeli: {_ok(cget(cid, 'engel_rus'))}")
        return

    # --- Alfabeler ---
    if data == "alfa":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Kiril {_ok(cget(cid, 'alfa_kiril'))}", callback_data="p:ak"
                    ),
                    InlineKeyboardButton(
                        f"Çince {_ok(cget(cid, 'alfa_cin'))}", callback_data="p:ac"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Latince {_ok(cget(cid, 'alfa_latin'))}", callback_data="p:al"
                    ),
                    InlineKeyboardButton(
                        f"Arapça {_ok(cget(cid, 'alfa_arap'))}", callback_data="p:aa"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Hint {_ok(cget(cid, 'alfa_hint'))}", callback_data="p:ah"
                    ),
                    InlineKeyboardButton(
                        f"Bengali {_ok(cget(cid, 'alfa_bengali'))}", callback_data="p:ab"
                    ),
                ],
                [InlineKeyboardButton("« Ana menü", callback_data="p:geri")],
            ]
        )
        await q.edit_message_text(
            "🕉 <b>Alfabeler</b>\n"
            "Açık olan alfabe ile yazılan mesajlar silinir.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    alfa_map = {
        "ak": "alfa_kiril",
        "ac": "alfa_cin",
        "al": "alfa_latin",
        "aa": "alfa_arap",
        "ah": "alfa_hint",
        "ab": "alfa_bengali",
    }
    if data in alfa_map:
        k = alfa_map[data]
        cset(cid, k, not bool(cget(cid, k)))
        await q.answer(k)
        await yenile(f"{k}: {_ok(cget(cid, k))}")
        return

    # --- Digerleri ---
    if data == "diger":
        await q.edit_message_text(
            panel_metin(cid, gtitle) + "\n\n<b>Diğer ayarlar</b>",
            parse_mode="HTML",
            reply_markup=panel_diger(cid),
        )
        return

    # --- Porno ---
    if data == "porno":
        cur = bool(cget(cid, "porno_engel"))
        cset(cid, "porno_engel", not cur)
        await yenile(
            f"🔞 Porno engeli: {'AÇIK ✅' if not cur else 'KAPALI ❌'}\n"
            f"(açıkken NSFW anahtar kelimeli mesajlar silinir)"
        )
        return

    # --- @admin ---
    if data == "adminet":
        cur = bool(cget(cid, "admin_etiket"))
        cset(cid, "admin_etiket", not cur)
        await yenile(
            f"🆘 @admin etiketi: {'AÇIK ✅' if not cur else 'KAPALI ❌'}\n"
            f"Üye @admin yazınca yöneticilere özel bildirim gider."
        )
        return

    # --- Tag ---
    if data == "tag":
        cur = bool(cget(cid, "tag_acik"))
        cset(cid, "tag_acik", not cur)
        await yenile(f"🔔 Tag sistemi: {'AÇIK ✅' if not cur else 'KAPALI ❌'}")
        return

    # --- Grup linki ---
    if data == "gruplink":
        link = cget(cid, "grup_link") or "ayarlanmamış"
        await q.edit_message_text(
            f"🔗 <b>Grup linki</b>\nŞu an: <code>{html.escape(str(link))}</code>\n\n"
            f"Ayarlamak için gruba yaz:\n"
            f"<code>/setlink https://t.me/...</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Ana menü", callback_data="p:geri")]]
            ),
        )
        return

    # --- Onay modu ---
    if data == "onay":
        cur = bool(cget(cid, "onay_modu"))
        cset(cid, "onay_modu", not cur)
        await yenile(
            f"📋 Onay modu: {'AÇIK ✅' if not cur else 'KAPALI ❌'}\n"
            f"(açıkken yeni üyeler onaylanana kadar susturulur)"
        )
        return

    # --- Dogrulama ---
    if data == "dogrula":
        await q.edit_message_text(
            "🧠 <b>Doğrulama</b>\n"
            "Basit doğrulama: yeni üye 15 dk mute (Hoş Geldin mute ile aynı).\n"
            "Gelişmiş captcha için Hoş Geldin + Mute kullan.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Ana menü", callback_data="p:geri")]]
            ),
        )
        return

    # --- Kontroller (servis detay) ---
    if data == "kontrol":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Katılım {_ok(cget(cid, 'servis_katilim'))}",
                        callback_data="p:sk",
                    ),
                    InlineKeyboardButton(
                        f"Çıkış {_ok(cget(cid, 'servis_cikis'))}",
                        callback_data="p:sc",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Foto değişti {_ok(cget(cid, 'servis_foto'))}",
                        callback_data="p:sf",
                    ),
                    InlineKeyboardButton(
                        f"Başlık {_ok(cget(cid, 'servis_baslik'))}",
                        callback_data="p:sb",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"Pin {_ok(cget(cid, 'servis_pin'))}",
                        callback_data="p:sp",
                    ),
                ],
                [InlineKeyboardButton("« Ana menü", callback_data="p:geri")],
            ]
        )
        await q.edit_message_text(
            "🔦 <b>Kontroller / Servis mesajları</b>\n"
            "Açık olanlar otomatik silinir.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    servis_map = {
        "sk": "servis_katilim",
        "sc": "servis_cikis",
        "sf": "servis_foto",
        "sb": "servis_baslik",
        "sp": "servis_pin",
    }
    if data in servis_map:
        k = servis_map[data]
        cset(cid, k, not bool(cget(cid, k)))
        await q.answer(k)
        await yenile(f"{k}: {_ok(cget(cid, k))}")
        return

    # --- Anti spam ---
    if data == "antispam":
        cur = bool(cget(cid, "anti_spam"))
        cset(cid, "anti_spam", not cur)
        await yenile(f"🛡 Anti-Spam: {'AÇIK ✅' if not cur else 'KAPALI ❌'}")
        return

    # --- Tekrar ---
    if data == "tekrar":
        cur = bool(cget(cid, "tekrar_engel"))
        cset(cid, "tekrar_engel", not cur)
        await yenile(
            f"🔁 Tekrarlanan mesaj engeli: {'AÇIK ✅' if not cur else 'KAPALI ❌'}"
        )
        return

    # --- Yasakli kelimeler ---
    if data == "yasakli":
        lst = cget(cid, "yasakli_kelimeler") or []
        await q.edit_message_text(
            f"🚫 <b>Yasaklı kelimeler</b>\n"
            f"Liste: {html.escape(', '.join(lst) if lst else 'boş')}\n\n"
            f"Ekle (grupta):\n<code>/yasak kelime1 kelime2</code>\n"
            f"Temizle: <code>/yasaktemiz</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Diğerleri", callback_data="p:diger")]]
            ),
        )
        return

    # --- Uye yonetimi ---
    if data == "uye":
        await q.edit_message_text(
            "👥 <b>Üye yönetimi</b>\n"
            "Grupta yanıtlayarak kullan:\n"
            "<code>/mute 30</code> <code>/unmute</code>\n"
            "<code>/ban</code> <code>/unban</code> <code>/kick</code>\n"
            "<code>/warn</code> <code>/unwarn</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Diğerleri", callback_data="p:diger")]]
            ),
        )
        return

    # --- Mesaj uzunlugu ---
    if data == "uzunluk":
        mn = int(cget(cid, "mesaj_min") or 0)
        mx = int(cget(cid, "mesaj_max") or 0)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Min kapalı", callback_data="p:umin0"),
                    InlineKeyboardButton("Min 5", callback_data="p:umin5"),
                    InlineKeyboardButton("Min 10", callback_data="p:umin10"),
                ],
                [
                    InlineKeyboardButton("Max kapalı", callback_data="p:umax0"),
                    InlineKeyboardButton("Max 500", callback_data="p:umax500"),
                    InlineKeyboardButton("Max 1000", callback_data="p:umax1000"),
                ],
                [InlineKeyboardButton("« Diğerleri", callback_data="p:diger")],
            ]
        )
        await q.edit_message_text(
            f"📏 <b>Mesaj uzunluğu</b>\nMin: {mn or 'kapalı'} | Max: {mx or 'kapalı'}",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data.startswith("umin"):
        cset(cid, "mesaj_min", int(data[4:]))
        await q.answer(f"Min {data[4:]}")
        await yenile(f"📏 Min uzunluk: {data[4:] or 'kapalı'}")
        return

    if data.startswith("umax"):
        cset(cid, "mesaj_max", int(data[4:]))
        await q.answer(f"Max {data[4:]}")
        await yenile(f"📏 Max uzunluk: {data[4:] or 'kapalı'}")
        return

    # --- Mod yardim ---
    if data == "modhelp":
        await q.edit_message_text(
            "🔧 <b>Moderasyon komutları</b> (grupta, yanıtla)\n"
            "<code>/mute 30</code> — 30 dk sustur\n"
            "<code>/unmute</code>\n"
            "<code>/ban</code> / <code>/unban</code>\n"
            "<code>/kick</code>\n"
            "<code>/warn sebep</code> / <code>/unwarn</code>\n"
            "<code>/setwelcome metin</code>\n"
            "<code>/setrules metin</code>\n"
            "<code>/izinlink domain.com</code>\n"
            "<code>/setlink https://t.me/...</code>\n"
            "<code>/yasak kelime1 kelime2</code>\n"
            "Komutlar birkaç saniye sonra silinir.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Ana menü", callback_data="p:geri")]]
            ),
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


async def setlink_komut(update, context):
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
    cset(chat.id, "grup_link", context.args[0])
    m = await context.bot.send_message(chat.id, f"✅ Grup linki: {context.args[0]}")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 8))


async def yasak_komut(update, context):
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
    lst = list(cget(chat.id, "yasakli_kelimeler") or [])
    for a in context.args:
        a = a.strip()
        if a and a.lower() not in [x.lower() for x in lst]:
            lst.append(a)
    cset(chat.id, "yasakli_kelimeler", lst)
    m = await context.bot.send_message(
        chat.id, f"✅ Yasaklı: {', '.join(lst)}"
    )
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 10))


async def yasaktemiz_komut(update, context):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_gizle(msg, context.bot)
    if not await admin_mi(chat.id, user, context.bot):
        return
    cset(chat.id, "yasakli_kelimeler", [])
    m = await context.bot.send_message(chat.id, "✅ Yasaklı kelimeler temizlendi")
    asyncio.create_task(sil_sonra(context.bot, chat.id, m.message_id, 8))


# ---------- hosgeldin / ayrildi ----------
async def hosgeldin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or not msg.new_chat_members:
        return
    # servis sil (katilim)
    if cget(chat.id, "servis_sil") or cget(chat.id, "servis_katilim"):
        try:
            await msg.delete()
        except Exception:
            pass

    for u in msg.new_chat_members:
        # bot engeli
        if u.is_bot:
            if cget(chat.id, "bot_engel"):
                try:
                    await context.bot.ban_chat_member(chat.id, u.id)
                    await context.bot.unban_chat_member(chat.id, u.id)
                except Exception as e:
                    log.warning("bot engel: %s", e)
            continue

        ad = u.full_name or u.username or str(u.id)

        # isim engelleri
        if cget(chat.id, "engel_arap") and re.search(r"[\u0600-\u06FF]", ad):
            try:
                await context.bot.ban_chat_member(chat.id, u.id)
                await context.bot.unban_chat_member(chat.id, u.id)
            except Exception:
                pass
            continue
        if cget(chat.id, "engel_cin") and re.search(r"[\u4e00-\u9fff]", ad):
            try:
                await context.bot.ban_chat_member(chat.id, u.id)
                await context.bot.unban_chat_member(chat.id, u.id)
            except Exception:
                pass
            continue
        if cget(chat.id, "engel_rus") and re.search(r"[\u0400-\u04FF]", ad):
            try:
                await context.bot.ban_chat_member(chat.id, u.id)
                await context.bot.unban_chat_member(chat.id, u.id)
            except Exception:
                pass
            continue

        # zorunluluklar
        if cget(chat.id, "zorunlu_username") and not u.username:
            try:
                await mute_uye(context.bot, chat.id, u.id, 60)
            except Exception:
                pass
        if cget(chat.id, "zorunlu_soyisim"):
            parts = (u.full_name or "").split()
            if len(parts) < 2:
                try:
                    await mute_uye(context.bot, chat.id, u.id, 60)
                except Exception:
                    pass

        # onay modu -> mute
        if cget(chat.id, "onay_modu"):
            try:
                await mute_uye(context.bot, chat.id, u.id, 24 * 60)
            except Exception as e:
                log.warning("onay mute: %s", e)

        uye_kaydi(chat.id, u, say=False)

        if not cget(chat.id, "hosgeldin"):
            await log_gonder(
                context.bot, chat.id, f"➕ {html.escape(ad)} gruba katıldı"
            )
            continue

        metin_sablon = cget(chat.id, "hosgeldin_metin") or DEFAULT_G["hosgeldin_metin"]
        mute_dk = int(cget(chat.id, "hosgeldin_mute") or 0)
        sil_sn = int(cget(chat.id, "hosgeldin_sil") or 0)
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
        if mute_dk > 0 and not cget(chat.id, "onay_modu"):
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
_flood_sayac = {}  # (chat_id, user_id) -> [timestamps]


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

    # grup kurallari (admin haric)
    if not ozel and user and not await admin_mi(cid, user, context.bot):
        # sessizlik: normal uye yazamaz
        if cget(cid, "sessizlik"):
            try:
                await msg.delete()
            except Exception:
                pass
            return

        # medya engeli (tur bazli)
        if cget(cid, "medya_engel"):
            sil = False
            if msg.photo and cget(cid, "medya_foto"):
                sil = True
            elif msg.video and cget(cid, "medya_video"):
                sil = True
            elif msg.animation and cget(cid, "medya_gif"):
                sil = True
            elif msg.sticker and cget(cid, "medya_sticker"):
                sil = True
            elif msg.document and cget(cid, "medya_dosya"):
                sil = True
            elif (msg.voice or msg.audio) and cget(cid, "medya_ses"):
                sil = True
            if sil:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # link engeli
        if cget(cid, "link_engel") and metin and LINK_RE.search(metin):
            izin = [x.lower() for x in (cget(cid, "link_izin") or [])]
            ok = any(x in metin.lower() for x in izin) if izin else False
            if not ok:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # mesaj uzunlugu
        if metin:
            mn = int(cget(cid, "mesaj_min") or 0)
            mx = int(cget(cid, "mesaj_max") or 0)
            if (mn and len(metin) < mn) or (mx and len(metin) > mx):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # flood
        adet = int(cget(cid, "flood_adet") or 0)
        if adet > 0:
            sn = int(cget(cid, "flood_sn") or 5)
            key = (cid, user.id)
            now = time.time()
            lst = _flood_sayac.get(key, [])
            lst = [t for t in lst if now - t < sn]
            lst.append(now)
            _flood_sayac[key] = lst
            if len(lst) > adet:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # alfabe engeli
        if metin:
            if cget(cid, "alfa_kiril") and re.search(r"[\u0400-\u04FF]", metin):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            if cget(cid, "alfa_cin") and re.search(r"[\u4e00-\u9fff]", metin):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            if cget(cid, "alfa_arap") and re.search(r"[\u0600-\u06FF]", metin):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            if cget(cid, "alfa_hint") and re.search(r"[\u0900-\u097F]", metin):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            if cget(cid, "alfa_bengali") and re.search(r"[\u0980-\u09FF]", metin):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            if cget(cid, "alfa_latin") and re.search(r"[A-Za-z]", metin) and not re.search(
                r"[çğıöşüÇĞİÖŞÜ]", metin
            ):
                # sadece latin harf varsa ve turkce yoksa (kabaca)
                if not re.search(r"[ğüşıöçĞÜŞİÖÇ]", metin):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return

        # yasakli kelimeler
        yk = cget(cid, "yasakli_kelimeler") or []
        if metin and yk:
            low = metin.lower()
            if any(w.lower() in low for w in yk if w):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # porno engeli (basit anahtar kelime)
        if metin and cget(cid, "porno_engel"):
            porno_kw = (
                "porno", "sex", "xxx", "nsfw", "onlyfans", "nude", "naked",
                "amcık", "sikiş", "sikis", "orospu",
            )
            low = metin.lower()
            if any(k in low for k in porno_kw):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        # @admin bildirimi
        if metin and cget(cid, "admin_etiket") and re.search(
            r"(?i)@admin\b", metin
        ):
            try:
                admins = await context.bot.get_chat_administrators(cid)
                bildirim = (
                    f"🆘 <b>@admin çağrısı</b>\n"
                    f"Grup: {html.escape(chat.title or '')}\n"
                    f"Kim: {html.escape(user.full_name or str(user.id))}\n"
                    f"Mesaj: {html.escape(metin[:200])}"
                )
                for a in admins:
                    if a.user and not a.user.is_bot:
                        try:
                            await context.bot.send_message(
                                a.user.id, bildirim, parse_mode="HTML"
                            )
                        except Exception:
                            pass
            except Exception as e:
                log.warning("@admin bildirim: %s", e)

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
app.add_handler(CommandHandler("panel", ayarlar_komut))
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
app.add_handler(CommandHandler("setlink", setlink_komut))
app.add_handler(CommandHandler("yasak", yasak_komut))
app.add_handler(CommandHandler("yasaktemiz", yasaktemiz_komut))
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
