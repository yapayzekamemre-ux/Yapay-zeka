# -*- coding: utf-8 -*-
"""
TurkPronimBot — AI + fiyat + tam yonetim paneli (islevsel)
Panel: /panel veya /ayarlar (sadece admin, ozelde acilir)
"""
import asyncio
import html
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from groq import Groq
from google import genai
from google.genai import types
from telegram import (
    Update,
    ChatPermissions,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationHandlerStop,
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatType, ChatMemberStatus
from telegram.error import BadRequest, Forbidden

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ.get("GROQ_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
# --- KILIT: sadece sahip ---
SAHIP_ID = 8992444484
SAHIP_KULLANICI = (
    os.environ.get("SAHIP_KULLANICI") or os.environ.get("SAHIP_USERNAME") or "Turkpronim"
).lower().lstrip("@")
KILIT_MESAJ = (
    "🔒 Bu bot kilitlidir.\n"
    "Kullanmak için sahip ile iletişime geç:\n"
    "👉 @Turkpronim"
)
_sahip_grup_cache = {}  # chat_id -> (ok:bool, ts)

TR = timezone(timedelta(hours=3))

# Hazir egitici / uyari mesajlari (arkadas botu tarzi)
DEFAULT_IPUCU = [
    "💡 <b>Yatırım risklidir.</b> Ön satış / ödeme ile airdrop her zaman kazanç getirmez.",
    "💡 <b>DYOR:</b> Whitepaper, ekip, tokenomics ve kontrat adresini kontrol et.",
    "💡 <b>Seed / private key</b> asla paylaşma. “Destek ekibi” yazanlar dolandırıcı olabilir.",
    "💡 <b>Phishing:</b> Sahte site seed ister. Adresi hep resmi kaynaktan kopyala.",
    "💡 <b>Rugpull:</b> Likidite çekilip proje terk edilir. Audit ve kilitli likiditeye bak.",
    "💡 <b>Sybil:</b> Çok cüzdan = ban riski. Airdrop kurallarını oku.",
    "💡 <b>Slippage:</b> Büyük işlemde fiyat kayar. Parçala, limit kullan.",
    "💡 <b>FOMO</b> ile alım çoğu zaman zarardır. Plansız işlem açma.",
    "💡 <b>Gas:</b> Yoğun saatte ücret artar. Acil değilse sakin saat bekle.",
    "💡 <b>Vote escrow:</b> Uzun kilit = daha fazla oy / ödül. Erken çıkış cezası olabilir.",
    "💡 <b>2FA</b> borsa ve e-postada açık tut. SIM swap’a karşı dikkat.",
    "💡 <b>Revoke:</b> Kullanmadığın dApp izinlerini periyodik iptal et.",
    "💡 <b>Cold wallet:</b> Büyük birikimi hot cüzdanda tutma.",
    "💡 <b>Sözleşme:</b> Token kontratını explorer’da doğrula; taklit token alma.",
    "💡 <b>Likidite kilidi:</b> Unlocked LP = yüksek risk.",
    "💡 <b>Vesting:</b> Ekip token açılış takvimine bak; ani satış baskısı olabilir.",
    "💡 <b>Bridge:</b> Resmi köprü kullan; sahte bridge fonları yer.",
    "💡 <b>NFT airdrop:</b> “Free mint” linkleri çoğu zaman zararlı sözleşme.",
    "💡 <b>Destek DM:</b> Gerçek ekipler önce seed/cüzdan istemez.",
    "💡 <b>Stop-loss / plan:</b> Duyguyla değil kuralınla işlem yap.",
    "💡 <b>APY tuzak:</b> Aşırı yüksek getiri genelde sürdürülemez.",
    "💡 <b>Testnet ≠ mainnet:</b> Test coinleri gerçek para değildir.",
    "💡 <b>Multi-sig:</b> Ortak hazine için tek imza risklidir.",
    "💡 <b>On-chain takip:</b> Büyük cüzdan hareketlerini izle, kopyala körü körüne alma.",
    "💡 <b>Vergi / kayıt:</b> İşlem geçmişini sakla; ileride lazım olur.",
    "💡 <b>Topluluk:</b> Sadece şişirme vaat eden gruplardan uzak dur.",
    "💡 <b>Hardware güncelle:</b> Cüzdan firmware’ini resmi siteden güncelle.",
    "💡 <b>Adres kontrol:</b> Kopyala-yapıştır sonrası ilk-son karakterleri doğrula.",
    "💡 <b>MEV / sandwich:</b> Büyük swap’te private RPC veya limit emir düşün.",
    "💡 <b>Sakin kal:</b> Panik satış çoğu zaman dibi satmaktır.",
]




# ---------- keep-alive ----------
class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *a):
        pass


def keep_alive():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _Ping).serve_forever()


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
    "Adın Yapay. Grubun asistanısın. Sadece Türkçe konuş. "
    "Olgun ve net konuş: en fazla 1-2 kısa cümle. Sulu/flörtöz olma. "
    "Birisi seninle dalga geçerse veya takılırsa aynı tonda, zekice ve kısa karşılık ver; "
    "ezilme, küfür yağdırma, ama lazımsa iğneleyici ol. "
    "Birinin adını söyleyerek şaka yapılıyorsa duruma uygun, adil cevap ver. "
    "Grup üyelerini tanı; isimleriyle hitap et. "
    "Bot/model ismi yazma. Yatırım tavsiyesi verme. Bilmediğini uydurma."
    "Fiyat uydurma; borsaya gönderme. Kısa ve net kal."
)

DOSYA, DURUM = "uyeler.json", "durum.json"
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
for _k, _v in (("sahip", None), ("talimat", []), ("grup", {}), ("federations", {}), ("fed_bans", {})):
    durum.setdefault(_k, _v)

gecmis = {}
uyarilar = {}
flood_buf = defaultdict(lambda: deque())  # (chat,uid) -> timestamps
join_times = defaultdict(lambda: deque())  # chat_id -> join timestamps
pending_captcha = {}  # (chat_id, user_id) -> True
ceza_oylari = {}  # mid -> {chat, hedef, baslatan, evet:set, hayir:set, bitis}

DEFAULT_G = {
    "hosgeldin": False,
    "hosgeldin_metin": "👋 <b>{ad}</b> gruba hoş geldin!",
    "hosgeldin_sil": 15,
    "hosgeldin_mute": 0,
    "hoscaakal": False,
    "hoscaakal_metin": "👋 {ad} gruptan ayrıldı.",
    "hoscaakal_sil": 10,
    "kurallar": "Grup kurallarına uyun. Spam, aşırı küfür ve reklam yasak.",
    "warn_limit": 3,
    "warn_mute_dk": 60,
    "medya_engel": False,
    "medya_foto": True,
    "medya_video": True,
    "medya_gif": True,
    "medya_sticker": True,
    "medya_dosya": True,
    "medya_ses": False,
    "link_engel": False,
    "link_izin": [],
    "servis_sil": True,
    "log_kanal": None,
    "flood": False,
    "flood_adet": 5,
    "flood_sn": 5,
    "flood_ceza": "mute",
    "flood_mute_dk": 10,
    "gece": False,
    "gece_bas": 0,
    "gece_bit": 7,
    "sessizlik": False,
    "engel_bot": True,
    "engel_kanal": False,
    "mesaj_max": 0,
    # Rose tarzi ekler
    "captcha": False,
    "approval": False,
    "clean_cmd": True,
    "antiraid": False,
    "antiraid_adet": 5,
    "antiraid_sn": 10,
    "blocklist": [],
    "notes": {},
    "filters": {},
    "captcha_math": True,
    "purge_limit": 50,
    "auto_pin_welcome": False,
    "fed_id": None,
    "topic_mode": False,
    "disabled_cmds": [],
    "privacy_ai": False,
    "reports": True,
    "duyuru_kanal": None,
    "duyuru_aktif": False,
    "duyuru_saat": 5,
    "duyuru_posts": [],
    "ipucu_aktif": False,
    "ipucu_saat": 3,
    "ipucu_last": 0,
    "ipucu_liste": [],
}


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


def cget(chat_id, key, default=None):
    g = durum.setdefault("grup", {}).setdefault(str(chat_id), {})
    if key in g:
        return g[key]
    return DEFAULT_G.get(key, default)


def cset(chat_id, key, val):
    durum.setdefault("grup", {}).setdefault(str(chat_id), {})[key] = val
    durum_kaydet()


def kucult(t):
    return (t or "").replace("İ", "i").replace("I", "ı").lower()


def sahip_mi(user):
    """Sadece Turkpronim (8992444484)."""
    if not user:
        return False
    if user.id == SAHIP_ID:
        return True
    if durum.get("sahip") and user.id == durum["sahip"]:
        return True
    if SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI:
        return True
    return False


async def sahip_grupta_mi(bot, chat_id) -> bool:
    """Bot sadece sahibin yonetici oldugu gruplarda calisir."""
    now = time.time()
    cached = _sahip_grup_cache.get(chat_id)
    if cached and now - cached[1] < 300:
        return cached[0]
    ok = False
    try:
        m = await bot.get_chat_member(chat_id, SAHIP_ID)
        ok = m.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            "administrator",
            "creator",
            "member",
        )
        # uye de olsa grupta varsa calissin; tercihen admin
        # kullanici: nereye koyarsam calissin -> member yeterli
        ok = m.status not in ("left", "kicked", ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    except Exception:
        ok = False
    _sahip_grup_cache[chat_id] = (ok, now)
    return ok


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
        {"ad": user.full_name or "", "kullanici": (user.username or "").lower(), "mesaj": 0},
    )
    u["ad"] = user.full_name or u.get("ad", "")
    u["kullanici"] = (user.username or "").lower()
    u["mesaj"] = int(u.get("mesaj") or 0) + 1
    if u["mesaj"] == 1 or u["mesaj"] % 20 == 0:
        kaydet()
    return u


async def sil_sonra(bot, chat_id, mid, sn=8):
    if not sn or not mid:
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
        if sn:
            asyncio.create_task(sil_sonra(bot, chat_id, m.message_id, sn))
        return m
    except Exception as e:
        log.warning("kisa_cevap: %s", e)
        return None


async def log_gonder(bot, chat_id, metin):
    kid = cget(chat_id, "log_kanal")
    if not kid:
        return
    try:
        await bot.send_message(int(kid), metin, parse_mode="HTML")
    except Exception as e:
        log.warning("log: %s", e)


def _ok(v):
    return "✅" if v else "❌"


def komut_kapali(chat_id, isim: str) -> bool:
    d = cget(chat_id, "disabled_cmds") or []
    return isim.lower().lstrip("/") in [x.lower().lstrip("/") for x in d]


# ---------- AI ----------
def groq_sor(m, sistem):
    if not groq:
        return None
    for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
        try:
            r = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sistem}] + m,
                temperature=0.7,
                max_tokens=120,
            )
            t = (r.choices[0].message.content or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Groq %s: %s", model, e)
    return None


def _gem_parts(m):
    return [
        types.Content(
            role="user" if x["role"] == "user" else "model",
            parts=[types.Part(text=x["content"])],
        )
        for x in m
    ]


def gemini_sor(m, sistem):
    if not gem:
        return None
    for model in (
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-2.5-flash",
    ):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=_gem_parts(m),
                config=types.GenerateContentConfig(
                    system_instruction=sistem, temperature=0.7, max_output_tokens=120
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
            json={"model": "deepseek-chat", "messages": [{"role": "system", "content": sistem}] + m, "max_tokens": 200},
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
            json={"model": "mistral-small-latest", "messages": [{"role": "system", "content": sistem}] + m, "max_tokens": 200},
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
    for model in (
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "qwen/qwen-2.5-7b-instruct:free",
    ):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": sistem}] + m,
                    "max_tokens": 200,
                },
                timeout=30,
            )
            if r.ok:
                t = (r.json()["choices"][0]["message"]["content"] or "").strip()
                if t:
                    return t
            else:
                log.warning("OpenRouter %s: %s", model, r.status_code)
        except Exception as e:
            log.warning("OpenRouter %s: %s", model, e)
    return None


def cevap_temizle(c):
    if not c:
        return None
    c = c.strip().replace("**", "").replace("__", "")
    if any(x in c.lower() for x in ("forbidden", "as an ai", "i am an ai")) and len(c) < 100:
        return None
    return c


def sor(mesajlar, ek=""):
    sistem = SISTEM + (("\n" + ek) if ek else "")
    for fn in (groq_sor, gemini_sor, deepseek_sor, mistral_sor, openrouter_sor):
        t = cevap_temizle(fn(mesajlar, sistem))
        if t:
            return t
    return "Biraz yoğunum, sonra tekrar dene."


# ---------- fiyat (Claude mimari: snapshot + cooldown + rank) ----------
CG_BASE = "https://api.coingecko.com/api/v3"
CG_CACHE = "cg_snap.json"
CG_PAGES = 8
CG_STEP = 20  # sayfalar arasi sn (~3 istek/dk)

# kisa espri havuzu + tekrar onleme
_FIYAT_ESPRI_SON = []
_FIYAT_YUKSEL = [
    "boğa canlanıyor 🐂", "cüzdan gülümsedi", "yeşil ışık yandı", "pump sinyali mi?",
    "hafif hop aldı", "ayılar kaçıyor", "momentum geldi", "chart mutlu",
    "yeşile boyandı", "cüzdan şişiyor", "rocket yolda mı", "boğa uyanmış",
    "trend yukarı", "hop diye çıktı", "yeşil yağmur", "kazanç kokusu",
    "alım baskısı var", "yeşil mumlar", "cüzdan keyifli", "boğa dansı",
    "yükseliş devam", "fiyat koşuyor", "iyi gidiyor", "mini pump",
]
_FIYAT_DUS = [
    "cüzdan yanıyor 🔥", "ayı baskın", "su döküldü", "kırmızı alarm",
    "panik yok sakin", "düzeltme mi bu", "boğa yoruldu", "chart ağlıyor",
    "hold zamanı", "geçici diye umuyoruz", "kırmızı deniz", "cüzdan inceldi",
    "ayı dans ediyor", "nefes al", "düşüş var sakin", "kırmızı mumlar",
    "satış baskısı", "chart üzgün", "biraz geriledi", "soğuk duş",
    "dip mi geliyor", "sakin kal lan", "geçici kanama", "ayı gücü",
]
_FIYAT_YATAY = [
    "yatay sürünüyor", "ne boğa ne ayı", "sıkıcı chart", "bekle gör",
    "kimse kıpırdamıyor", "fısıltı bile yok", "donmuş gibi", "yan range",
    "sessiz piyasa", "ufak titreşim", "durgun su", "bekleyiş var",
    "hareket yok", "uykuda chart", "sabır zamanı", "düz çizgi",
    "ne yukarı ne aşağı", "sakin sakin", "fiyat uyuyor", "bekleyenler kazanır",
]

def _espri_sec(havuz):
    """Son 5 espriyi tekrar etme."""
    import random
    aday = [x for x in havuz if x not in _FIYAT_ESPRI_SON[-5:]]
    if not aday:
        aday = list(havuz)
    sec = random.choice(aday)
    _FIYAT_ESPRI_SON.append(sec)
    if len(_FIYAT_ESPRI_SON) > 20:
        del _FIYAT_ESPRI_SON[:-15]
    return sec

_CG_ALIAS = {"ton": "the-open-network", "gram": "the-open-network", "toncoin": "the-open-network"}
_cg_by_id = {}
_cg_by_symbol = {}  # symbol -> [coin, ...] rank sirali
_cg_miss = {}       # symbol -> miss_until
_cg_cooldown_until = 0.0
_cg_lock = threading.Lock()

KISA = re.compile(
    r"(?i)^\s*(?:(\d+(?:[.,]\d+)?)\s+)?"
    r"(?:\$|fiyat\s+|price\s+)?"
    r"([a-zA-Z][a-zA-Z0-9]{1,15})"
    r"(?:\s+(?:fiyat|price|ne kadar|kaç|kac))?$"
)
_ATLA = {
    "tl", "try", "gb", "mb", "kg", "tane", "adet", "saat", "gun", "dk", "sn",
    "lira", "fiyat", "price", "yapay", "ne", "naber", "merhaba", "selam", "sa",
    "as", "nbr", "iyi", "iyiyim", "nasilsin", "tamam", "ok", "evet", "hayir",
    "yok", "var", "lan", "abi", "knk", "bro", "anlamadim", "anlamadım",
    "etmiyorum", "belki", "ben", "sen", "biz", "bu", "su", "kim", "neden",
    "nasil", "ceza", "bot", "grup", "mesaj", "chat", "link", "amk", "aq",
}


def _re_sub_yapay(metin: str) -> str:
    return re.sub(r"(?i)\byapay\b", "", metin or "").strip()


def kisa_token(metin):
    t = (metin or "").strip()
    if not t or len(t) > 40 or len(t.split()) > 3:
        return None
    m = KISA.match(t)
    if not m:
        return None
    miktar = 1.0
    if m.group(1):
        try:
            miktar = float(m.group(1).replace(",", "."))
        except Exception:
            pass
    s = m.group(2).lower().strip(".")
    if s in _ATLA or any(c in s for c in "ğüşıöç") or len(s) > 15:
        return None
    return (miktar, s)


def _cg_index(coins):
    """Snapshot'tan by_id + by_symbol (market_cap_rank)."""
    global _cg_by_id, _cg_by_symbol
    now = time.time()
    with _cg_lock:
        for c in coins or []:
            if not c.get("id"):
                continue
            c = dict(c)
            c["_ts"] = now
            _cg_by_id[c["id"]] = c
        tmp = {}
        for c in _cg_by_id.values():
            sym = (c.get("symbol") or "").lower()
            if sym:
                tmp.setdefault(sym, []).append(c)
        for v in tmp.values():
            v.sort(key=lambda x: x.get("market_cap_rank") or 10**9)
        _cg_by_symbol = tmp


def _cg_http(path, **params):
    """Tek CG istegi. 429'da global cooldown — spam yok."""
    global _cg_cooldown_until
    if time.time() < _cg_cooldown_until:
        return None
    try:
        r = requests.get(
            CG_BASE + path,
            params=params,
            timeout=12,
            headers={"Accept": "application/json", "User-Agent": "TurkPronimBot/2.0"},
        )
    except Exception as e:
        log.warning("CG net: %s %s", path, e)
        return None
    if r.status_code == 429:
        wait = int(r.headers.get("Retry-After") or 60)
        _cg_cooldown_until = time.time() + wait
        log.warning("CG 429 cooldown %ss path=%s", wait, path)
        return None
    if r.status_code != 200:
        log.warning("CG %s -> %s %s", path, r.status_code, (r.text or "")[:120])
        return None
    try:
        return r.json()
    except Exception:
        return None


def _cg_load_disk():
    try:
        with open(CG_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            _cg_index(data)
            log.info("CG disk: %s coin", len(_cg_by_id))
            return True
    except Exception:
        pass
    return False


def _cg_save_disk():
    try:
        with _cg_lock:
            data = list(_cg_by_id.values())
        with open(CG_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        log.warning("CG save: %s", e)


def _cg_refresher():
    """Arka plan: sayfa 1 sik, digerleri seyrek. ~3 istek/dk."""
    _cg_load_disk()
    # order: 1,2,1,3,1,4... 
    order = [p for n in range(2, CG_PAGES + 1) for p in (1, n)]
    idx = 0
    while True:
        page = order[idx % len(order)]
        idx += 1
        if time.time() < _cg_cooldown_until:
            time.sleep(min(30, _cg_cooldown_until - time.time() + 1))
            continue
        data = _cg_http(
            "/coins/markets",
            vs_currency="usd",
            order="market_cap_desc",
            per_page=250,
            page=page,
            sparkline="false",
            price_change_percentage="24h",
        )
        if data:
            _cg_index(data)
            _cg_save_disk()
            log.info("CG refresh p%s toplam=%s", page, len(_cg_by_id))
        time.sleep(CG_STEP)


def _cg_lookup_tail(sym: str):
    """Snapshot'ta yoksa search + markets?ids=."""
    if _cg_miss.get(sym, 0) > time.time():
        return None
    if time.time() < _cg_cooldown_until:
        return None
    s = _cg_http("/search", query=sym)
    if s is None:
        return None
    hits = [c for c in (s.get("coins") or []) if (c.get("symbol") or "").lower() == sym]
    if not hits:
        # isim eslesmesi (toncoin vb.)
        hits = [c for c in (s.get("coins") or []) if sym in (c.get("id") or "").lower()]
    if not hits:
        _cg_miss[sym] = time.time() + 600
        return None
    best = min(hits, key=lambda c: c.get("market_cap_rank") or 10**9)
    cid = best.get("id")
    if not cid:
        return None
    p = _cg_http("/coins/markets", vs_currency="usd", ids=cid, price_change_percentage="24h")
    if p:
        _cg_index(p)
        return _cg_by_id.get(cid)
    return None


def _coingecko_fiyat(q: str):
    q = (q or "").strip().lower()
    if not q:
        return None
    # alias
    aid = _CG_ALIAS.get(q)
    if aid and aid in _cg_by_id:
        coin = _cg_by_id[aid]
    else:
        coin = None
        lst = _cg_by_symbol.get(q) or []
        if lst:
            coin = lst[0]
        if not coin:
            coin = _cg_lookup_tail(q)
    if not coin:
        return None
    price = coin.get("current_price")
    if price is None:
        return None
    return {
        "s": (coin.get("symbol") or q).upper(),
        "name": coin.get("name") or "",
        "usd": float(price),
        "try": None,
        "ch": coin.get("price_change_percentage_24h"),
        "src": "coingecko",
        "id": coin.get("id"),
        "link": f"https://www.coingecko.com/en/coins/{coin['id']}" if coin.get("id") else "",
        "_ts": coin.get("_ts") or time.time(),
    }


def _yahoo_ticker(q: str):
    q = (q or "").lower()
    if q in ("usd", "dolar", "usdt"):
        return "USDTRY=X", "USD"
    if q in ("eur", "euro"):
        return "EURTRY=X", "EUR"
    if q in ("gbp", "sterlin"):
        return "GBPTRY=X", "GBP"
    if q in ("altin", "gold", "ons"):
        return "GC=F", "ALTIN"
    if q in ("gumus", "silver"):
        return "SI=F", "GUMUS"
    if q.isalpha() and 3 <= len(q) <= 6:
        return q.upper() + ".IS", q.upper()
    return None, None


def _yahoo_fiyat(query: str):
    ticker, label = _yahoo_ticker(query)
    if not ticker:
        return None
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": "2d", "interval": "1d"},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if not r.ok:
            return None
        result = (r.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        if price is None:
            return None
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        ch = None
        if prev:
            ch = ((float(price) - float(prev)) / float(prev)) * 100
        currency = (meta.get("currency") or "").upper()
        price = float(price)
        out = {
            "s": label,
            "ch": ch,
            "src": "yahoo",
            "cur": currency,
            "link": f"https://finance.yahoo.com/quote/{ticker}",
        }
        if currency in ("TRY", "TL"):
            out["usd"] = None
            out["try"] = price
        else:
            out["usd"] = price
            out["try"] = None
        return out
    except Exception as e:
        log.warning("yahoo: %s", e)
        return None


def fiyat_cek(sembol: str):
    q = (sembol or "").strip().lower()
    if not q:
        return None
    # doviz / altin (gram coin CG'de TON; altin = "altin")
    if q in ("usd", "dolar", "usdt", "eur", "euro", "gbp", "sterlin", "altin", "gold", "ons", "gumus", "silver"):
        bil = _yahoo_fiyat(q)
        if bil:
            return bil
    bil = _coingecko_fiyat(q)
    if bil:
        return bil
    if q.isalpha() and 3 <= len(q) <= 6:
        bil = _yahoo_fiyat(q)
        if bil:
            return bil
    return None


async def fiyat_gonder(update, miktar, sembol):
    bil = fiyat_cek(sembol)
    if not bil:
        warming = (not _cg_by_id) or (time.time() < _cg_cooldown_until)
        if warming:
            msg = "⏳ Veri güncelleniyor, birazdan tekrar dene."
        else:
            msg = f"❌ <b>{html.escape(str(sembol).upper())}</b> bulunamadı."
        try:
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        except Exception:
            pass
        return True
    import random
    ch = bil.get("ch")
    name = str(bil.get("s") or sembol).upper()
    link = bil.get("link") or ""
    adet = f"{miktar:g} " if miktar != 1 else ""
    usd = bil.get("usd")
    try_p = bil.get("try")
    if usd is not None:
        u = float(usd) * miktar
        if u < 0.0001:
            fiyat_satir = f"${u:.8f}"
        elif u < 1:
            fiyat_satir = f"${u:.4f}"
        else:
            fiyat_satir = f"${u:,.2f}"
    elif try_p is not None:
        fiyat_satir = f"₺{float(try_p) * miktar:,.2f}"
    else:
        fiyat_satir = "—"
    try_line = ""
    if usd is not None and try_p is not None:
        try_line = f"\n🇹🇷 ₺{float(try_p) * miktar:,.2f}"

    if ch is not None and float(ch) >= 0.3:
        ikon = "📈"
        espri = f"%{float(ch):.2f} · {_espri_sec(_FIYAT_YUKSEL)}"
    elif ch is not None and float(ch) <= -0.3:
        ikon = "📉"
        espri = f"%{abs(float(ch)):.2f} · {_espri_sec(_FIYAT_DUS)}"
    else:
        ikon = "💬"
        ch_s = f"{float(ch):+.2f}" if ch is not None else "0.00"
        espri = f"{ch_s}% · {_espri_sec(_FIYAT_YATAY)}"

    if link:
        baslik = f'<a href="{html.escape(link)}"><b>{adet}{html.escape(name)}</b></a>'
    else:
        baslik = f"<b>{adet}{html.escape(name)}</b>"
    text = (
        f"⚠️ {baslik}\n"
        f"\n"
        f"✅ {fiyat_satir}{try_line}\n"
        f"\n"
        f"{ikon} {html.escape(espri)}"
    )
    try:
        await update.effective_message.reply_text(
            text, parse_mode="HTML", disable_web_page_preview=True
        )
        return True
    except Exception as e:
        log.warning("fiyat_gonder: %s", e)
        return False


# ---------- panel ----------
def panel_kb(cid):
    """Rose tarzi ana panel — tum dugmeler islevsel."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"👋 Greetings {_ok(cget(cid,'hosgeldin') or cget(cid,'hoscaakal'))}", callback_data="p:greet"),
                InlineKeyboardButton(f"🌊 Antiflood {_ok(cget(cid,'flood'))}", callback_data="p:flood"),
            ],
            [
                InlineKeyboardButton(f"🛡 AntiRaid {_ok(cget(cid,'antiraid'))}", callback_data="p:antiraid"),
                InlineKeyboardButton(f"✅ Approval {_ok(cget(cid,'approval'))}", callback_data="p:approval"),
            ],
            [
                InlineKeyboardButton(f"🔐 CAPTCHA {_ok(cget(cid,'captcha'))}", callback_data="p:captcha"),
                InlineKeyboardButton(f"🧹 Clean Cmd {_ok(cget(cid,'clean_cmd'))}", callback_data="p:cleancmd"),
            ],
            [
                InlineKeyboardButton(f"🧹 Clean Service {_ok(cget(cid,'servis_sil'))}", callback_data="p:servis"),
                InlineKeyboardButton(f"🔒 Locks", callback_data="p:locks"),
            ],
            [
                InlineKeyboardButton("🚫 Blocklists", callback_data="p:blocklist"),
                InlineKeyboardButton("⚠ Warns", callback_data="p:uyari"),
            ],
            [
                InlineKeyboardButton("📜 Rules", callback_data="p:kurallar"),
                InlineKeyboardButton(f"📋 Log {_ok(bool(cget(cid,'log_kanal')))}", callback_data="p:log"),
            ],
            [
                InlineKeyboardButton(f"🌙 Night {_ok(cget(cid,'gece'))}", callback_data="p:gece"),
                InlineKeyboardButton(f"🔇 Silence {_ok(cget(cid,'sessizlik'))}", callback_data="p:sessiz"),
            ],
            [
                InlineKeyboardButton("📝 Notes", callback_data="p:notes"),
                InlineKeyboardButton("📏 Msg length", callback_data="p:uzun"),
            ],
            [
                InlineKeyboardButton("🔧 Commands", callback_data="p:yardim"),
                InlineKeyboardButton("🚫 Bot block", callback_data="p:engel"),
            ],
            [
                InlineKeyboardButton("🔤 Filters", callback_data="p:filters"),
                InlineKeyboardButton("📌 Pin", callback_data="p:pin"),
            ],
            [
                InlineKeyboardButton("🗑 Purges", callback_data="p:purges"),
                InlineKeyboardButton("🌐 Federation", callback_data="p:fed"),
            ],
            [
                InlineKeyboardButton("📦 Import/Export", callback_data="p:imex"),
                InlineKeyboardButton("💬 Topics", callback_data="p:topics"),
            ],
            [
                InlineKeyboardButton("👤 Admin", callback_data="p:admin"),
                InlineKeyboardButton(f"📣 Reports {_ok(cget(cid,'reports'))}", callback_data="p:reports"),
            ],
            [
                InlineKeyboardButton(f"📢 Duyuru {_ok(cget(cid,'duyuru_aktif'))}", callback_data="p:duyuru"),
                InlineKeyboardButton(f"💡 İpucu {_ok(cget(cid,'ipucu_aktif'))}", callback_data="p:ipucu"),
            ],
            [
                InlineKeyboardButton("🚫 Disabling", callback_data="p:disable"),
                InlineKeyboardButton(f"🔏 Privacy {_ok(cget(cid,'privacy_ai'))}", callback_data="p:privacy"),
            ],
            [InlineKeyboardButton("🔒 Kapat", callback_data="p:kapat")],
        ]
    )


def panel_metin(cid, baslik=""):
    return (
        f"⚙️ <b>Ayarlar</b>\n"
        f"Grup ID: <code>{cid}</code>\n"
        f"{baslik}"
        f"Değiştirmek istediğin ayarı seç.\n"
        f"<i>Panel sadece sana özel açılır.</i>"
    )


async def ayarlar_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if chat.type == ChatType.PRIVATE and not sahip_mi(user):
        await msg.reply_text(KILIT_MESAJ)
        return

    # grupta: komutu sil, paneli ozelde ac
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        await komut_sil(msg, context.bot)
        if not await admin_mi(chat.id, user, context.bot):
            return
        context.user_data["panel_gid"] = chat.id
        try:
            await context.bot.send_message(
                user.id,
                panel_metin(chat.id, f"Grup: {html.escape(chat.title or '')}\n"),
                parse_mode="HTML",
                reply_markup=panel_kb(chat.id),
            )
        except Exception:
            await kisa_cevap(
                context.bot,
                chat.id,
                "❌ Önce bota özelden <b>/start</b> yaz, sonra tekrar /panel dene.",
                12,
            )
        return

    # ozelde: panel_gid veya args
    gid = context.user_data.get("panel_gid")
    if context.args and context.args[0].lstrip("-").isdigit():
        gid = int(context.args[0])
        context.user_data["panel_gid"] = gid
    if not gid:
        await msg.reply_text(
            "Grupta <code>/panel</code> yaz (admin olmalısın) veya burada:\n"
            "<code>/panel GRUP_ID</code>",
            parse_mode="HTML",
        )
        return
    if not await admin_mi(gid, user, context.bot) and not sahip_mi(user):
        await msg.reply_text("Bu grupta admin değilsin.")
        return
    await msg.reply_text(
        panel_metin(gid),
        parse_mode="HTML",
        reply_markup=panel_kb(gid),
    )




async def ceza_baslat(update, context, hedef, baslatan):
    """Yapay ceza oylamasi — 5 dk mute, min 6 evet."""
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not hedef or hedef.is_bot:
        return
    if await admin_mi(chat.id, hedef, context.bot):
        await msg.reply_text("🔆 Yöneticilere ceza açılamaz.")
        return
    had = html.escape(hedef.full_name or str(hedef.id))
    huser = f"@{hedef.username}" if hedef.username else had
    bad = html.escape(baslatan.full_name or str(baslatan.id))
    buser = f"@{baslatan.username}" if baslatan.username else bad
    text = (
        f"⚠️ <b>Ceza</b> {huser}\n"
        f"🚫 <b>Başlatan</b> {buser}\n\n"
        f"✅ Evet çoğunluk → <b>5 Dk</b> mesaj atmasını kapat\n"
        f"• Min <b>6 Oy</b>"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Evet (0)", callback_data=f"cz:e:0"),
        InlineKeyboardButton("❌ Hayır (0)", callback_data=f"cz:h:0"),
    ]])
    try:
        gonder = await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        log.warning("ceza_baslat: %s", e)
        return
    ceza_oylari[gonder.message_id] = {
        "chat": chat.id,
        "hedef": hedef.id,
        "hedef_ad": hedef.full_name or str(hedef.id),
        "baslatan": baslatan.id,
        "evet": set(),
        "hayir": set(),
        "bitis": False,
    }
    # 3 dk oy suresi sonra kapanir
    asyncio.create_task(ceza_zamanasimi(context.bot, chat.id, gonder.message_id))


async def ceza_zamanasimi(bot, chat_id, mid):
    await asyncio.sleep(180)
    data = ceza_oylari.get(mid)
    if not data or data.get("bitis"):
        return
    data["bitis"] = True
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=mid,
            text=f"⏱ Oylama bitti.\n✅ {len(data['evet'])} · ❌ {len(data['hayir'])}\nYetersiz oy, ceza uygulanmadı.",
        )
    except Exception:
        pass
    asyncio.create_task(sil_sonra(bot, chat_id, mid, 8))
    ceza_oylari.pop(mid, None)


async def ceza_oy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("cz:"):
        return
    mid = q.message.message_id if q.message else None
    data = ceza_oylari.get(mid)
    if not data or data.get("bitis"):
        await q.answer("Oylama bitti.", show_alert=True)
        return
    uid = q.from_user.id
    if uid == data["hedef"]:
        await q.answer("Kendine oy veremezsin.", show_alert=True)
        return
    taraf = q.data.split(":")[1]  # e veya h
    data["evet"].discard(uid)
    data["hayir"].discard(uid)
    if taraf == "e":
        data["evet"].add(uid)
    else:
        data["hayir"].add(uid)
    ne = len(data["evet"])
    nh = len(data["hayir"])
    await q.answer(f"Oyun kaydedildi ({'Evet' if taraf=='e' else 'Hayır'})")
    # min 6 evet ve evet > hayir
    if ne >= 6 and ne > nh:
        data["bitis"] = True
        hedef_id = data["hedef"]
        chat_id = data["chat"]
        ad = html.escape(data.get("hedef_ad") or str(hedef_id))
        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=5)
            await context.bot.restrict_chat_member(
                chat_id, hedef_id, permissions=MUTE_PERMS, until_date=until
            )
            txt = (
                f"✅ Ceza onaylandı\n"
                f"🔇 {ad} → <b>5 dk</b> mesaj atamaz\n"
                f"Oy: ✅{ne} ❌{nh}"
            )
        except Exception as e:
            txt = f"❌ Mute başarısız: {html.escape(str(e))}"
        try:
            await q.edit_message_text(txt, parse_mode="HTML")
        except Exception:
            pass
        asyncio.create_task(sil_sonra(context.bot, chat_id, mid, 8))
        ceza_oylari.pop(mid, None)
        await log_gonder(context.bot, chat_id, f"⚖️ Ceza oylaması: {ad} 5dk mute (✅{ne})")
        return
    # butonlari guncelle
    try:
        await q.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ Evet ({ne})", callback_data="cz:e:0"),
                InlineKeyboardButton(f"❌ Hayır ({nh})", callback_data="cz:h:0"),
            ]])
        )
    except Exception:
        pass



async def captcha_buton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("cap:"):
        return
    parts = q.data.split(":")
    try:
        cid, uid = int(parts[1]), int(parts[2])
        ans = parts[3] if len(parts) > 3 else "ok"
    except Exception:
        await q.answer()
        return
    if q.from_user.id != uid:
        await q.answer("Bu buton sana ait değil.", show_alert=True)
        return
    expected = pending_captcha.get((cid, uid))
    if expected is True or expected is None:
        ok = ans in ("ok",) or ans.isdigit()
    else:
        ok = ans.isdigit() and int(ans) == int(expected)
    if not ok:
        await q.answer("Yanlış cevap!", show_alert=True)
        return
    await q.answer()
    pending_captcha.pop((cid, uid), None)
    try:
        await context.bot.restrict_chat_member(cid, uid, permissions=FULL_PERMS)
    except Exception as e:
        log.warning("captcha unmute: %s", e)
    try:
        await q.edit_message_text("✅ Doğrulandı, yazabilirsin.")
        asyncio.create_task(sil_sonra(context.bot, cid, q.message.message_id, 5))
    except Exception:
        pass


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("p:"):
        return
    await q.answer()
    user = q.from_user
    data = q.data[2:]
    cid = context.user_data.get("panel_gid")
    if not cid:
        try:
            await q.edit_message_text("Oturum düştü. Grupta tekrar /panel yaz.")
        except Exception:
            pass
        return
    if not await admin_mi(cid, user, context.bot) and not sahip_mi(user):
        return

    async def yenile(extra=""):
        try:
            await q.edit_message_text(
                panel_metin(cid, extra),
                parse_mode="HTML",
                reply_markup=panel_kb(cid),
            )
        except Exception:
            pass

    if data == "kapat":
        try:
            await q.edit_message_text("Panel kapatıldı.")
        except Exception:
            pass
        return

    if data == "hg":
        cset(cid, "hosgeldin", not bool(cget(cid, "hosgeldin")))
        await yenile()
        return
    if data == "hc":
        cset(cid, "hoscaakal", not bool(cget(cid, "hoscaakal")))
        await yenile()
        return
    if data == "servis":
        cset(cid, "servis_sil", not bool(cget(cid, "servis_sil")))
        await yenile()
        return
    if data == "medya":
        cset(cid, "medya_engel", not bool(cget(cid, "medya_engel")))
        await yenile()
        return
    if data == "link":
        cset(cid, "link_engel", not bool(cget(cid, "link_engel")))
        await yenile()
        return
    if data == "flood":
        cset(cid, "flood", not bool(cget(cid, "flood")))
        await yenile()
        return
    if data == "gece":
        cset(cid, "gece", not bool(cget(cid, "gece")))
        await yenile()
        return
    if data == "sessiz":
        cset(cid, "sessizlik", not bool(cget(cid, "sessizlik")))
        await yenile()
        return
    if data == "captcha":
        cset(cid, "captcha", not bool(cget(cid, "captcha")))
        await yenile()
        return
    if data == "approval":
        cset(cid, "approval", not bool(cget(cid, "approval")))
        await yenile()
        return
    if data == "cleancmd":
        cset(cid, "clean_cmd", not bool(cget(cid, "clean_cmd")))
        await yenile()
        return
    if data == "antiraid":
        cset(cid, "antiraid", not bool(cget(cid, "antiraid")))
        await yenile()
        return
    if data == "greet":
        md = int(cget(cid, "hosgeldin_mute") or 0)
        await q.edit_message_text(
            f"👋 <b>Greetings</b>\n"
            f"Hoş geldin: {_ok(cget(cid,'hosgeldin'))}\n"
            f"Hoşça kal: {_ok(cget(cid,'hoscaakal'))}\n"
            f"Yeni üye mute: <b>{md if md else 'kapalı'} dk</b>\n\n"
            f"Mute sadece bu grup için. Varsayılan: kapalı.\n"
            f"/setwelcome metin — {{ad}} kullan",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Hoş Geldin {_ok(cget(cid,'hosgeldin'))}", callback_data="p:hg"),
                 InlineKeyboardButton(f"Hoşçakal {_ok(cget(cid,'hoscaakal'))}", callback_data="p:hc")],
                [
                    InlineKeyboardButton("Mute kapalı", callback_data="p:hm0"),
                    InlineKeyboardButton("5dk", callback_data="p:hm5"),
                    InlineKeyboardButton("15dk", callback_data="p:hm15"),
                    InlineKeyboardButton("30dk", callback_data="p:hm30"),
                ],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]),
        )
        return
    if data in ("hm0", "hm5", "hm15", "hm30"):
        cset(cid, "hosgeldin_mute", int(data[2:]))
        await yenile(f"Yeni üye mute: {data[2:] or '0'} dk\n")
        return
    if data == "locks":
        await q.edit_message_text(
            f"🔒 <b>Locks</b>\n"
            f"Medya: {_ok(cget(cid,'medya_engel'))}\n"
            f"Link: {_ok(cget(cid,'link_engel'))}\n",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Medya {_ok(cget(cid,'medya_engel'))}", callback_data="p:medya"),
                 InlineKeyboardButton(f"Link {_ok(cget(cid,'link_engel'))}", callback_data="p:link")],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]),
        )
        return
    if data == "blocklist":
        bl = cget(cid, "blocklist") or []
        await q.edit_message_text(
            f"🚫 <b>Blocklists</b>\n"
            f"Kelimeler: {', '.join(bl) if bl else 'yok'}\n\n"
            f"Ekle: <code>/block kelime</code>\n"
            f"Temizle: <code>/blockclear</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "notes":
        notes = cget(cid, "notes") or {}
        keys = ", ".join(list(notes.keys())[:15]) or "yok"
        await q.edit_message_text(
            f"📝 <b>Notes</b>\nKayıtlı: {html.escape(keys)}\n\n"
            f"Kaydet: <code>/save isim metin</code>\n"
            f"Getir: <code>/get isim</code> veya <code>#isim</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return


    if data == "filters":
        fl = cget(cid, "filters") or {}
        keys = ", ".join(list(fl.keys())[:12]) or "yok"
        await q.edit_message_text(
            f"🔤 <b>Filters</b>\nKayıtlı: {html.escape(keys)}\n\n"
            f"Ekle: <code>/filter kelime cevap</code>\n"
            f"Sil: <code>/stop kelime</code>\n"
            f"Liste: <code>/filters</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "pin":
        await q.edit_message_text(
            f"📌 <b>Pin</b>\n"
            f"Mesaja yanıtla: <code>/pin</code>\n"
            f"Sabiti kaldır: <code>/unpin</code>\n"
            f"Tüm sabitleri kaldır: <code>/unpinall</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "purges":
        await q.edit_message_text(
            f"🗑 <b>Purges</b>\n"
            f"<code>/purge</code> — yanıttan buraya kadar sil\n"
            f"<code>/del</code> — yanıtlanan mesajı sil\n"
            f"<code>/purge 20</code> — son 20 mesajı sil (max 100)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "fed":
        fid = cget(cid, "fed_id")
        await q.edit_message_text(
            f"🌐 <b>Federation</b>\n"
            f"Fed ID: <code>{fid or 'yok'}</code>\n\n"
            f"<code>/newfed isim</code> — fed oluştur\n"
            f"<code>/joinfed FED_ID</code> — gruba bağla\n"
            f"<code>/leavefed</code> — ayrıl\n"
            f"<code>/fban @user sebep</code> — fed ban\n"
            f"<code>/funban @user</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "imex":
        await q.edit_message_text(
            f"📦 <b>Import / Export</b>\n"
            f"<code>/export</code> — ayarları JSON olarak gönder\n"
            f"<code>/import</code> — JSON dosyasına yanıtla içe aktar",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "topics":
        tm = bool(cget(cid, "topic_mode"))
        await q.edit_message_text(
            f"💬 <b>Topics</b>\n"
            f"Mod: {_ok(tm)}\n\n"
            f"Forum gruplarında uyarı/log mesajları genel konuya gider.\n"
            f"Aç/kapa için aşağıdaki buton.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Topic mode {_ok(tm)}", callback_data="p:topic_tog")],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]),
        )
        return
    if data == "topic_tog":
        cset(cid, "topic_mode", not bool(cget(cid, "topic_mode")))
        await yenile()
        return


    if data == "admin":
        try:
            admins = await context.bot.get_chat_administrators(cid)
            lines = []
            for a in admins[:25]:
                u = a.user
                tag = "👑" if a.status in ("creator", ChatMemberStatus.OWNER) else "🛡"
                lines.append(f"{tag} {html.escape(u.full_name or str(u.id))} <code>{u.id}</code>")
            txt = "👤 <b>Admin</b>\n" + ("\n".join(lines) if lines else "Yok")
            txt += "\n\n<code>/reload</code> — listeyi yenile"
        except Exception as e:
            txt = f"❌ {html.escape(str(e))}"
        await q.edit_message_text(
            txt, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return
    if data == "reports":
        cset(cid, "reports", not bool(cget(cid, "reports")))
        await yenile()
        return
    if data == "privacy":
        cset(cid, "privacy_ai", not bool(cget(cid, "privacy_ai")))
        await yenile()
        return
    if data == "disable":
        d = cget(cid, "disabled_cmds") or []
        await q.edit_message_text(
            f"🚫 <b>Disabling</b>\n"
            f"Kapalı komutlar: {', '.join(d) if d else 'yok'}\n\n"
            f"<code>/disable ban</code> — komutu kapat\n"
            f"<code>/enable ban</code> — aç\n"
            f"<code>/disabled</code> — liste",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Geri", callback_data="p:geri")]]),
        )
        return


    if data == "duyuru":
        aktif = bool(cget(cid, "duyuru_aktif"))
        kid = cget(cid, "duyuru_kanal")
        saat = float(cget(cid, "duyuru_saat") or 5)
        n = len(cget(cid, "duyuru_posts") or [])
        txt = (
            f"📢 <b>Günlük Duyurular</b>\n"
            f"Durum: {_ok(aktif)}\n"
            f"Kanal: <code>{kid or 'bağlı değil'}</code>\n"
            f"Aralık: her <b>{saat}</b> saat\n"
            f"Kayıtlı: {n} post\n\n"
            f"Boş liste otomatik <b>gönderilmez</b>.\n"
            f"1) Botu kanala admin ekle\n"
            f"2) Kanalda: <code>/setduyuru {cid}</code>\n"
            f"3) Aç/kapa + aralık seç\n"
            f"Manuel: <code>/duyuruekle metin</code>\n"
            f"Şimdi: <code>/duyuru</code>\n"
            f"Aralık: <code>/duyurusaat 5</code>"
        )
        await q.edit_message_text(
            txt,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Aktif {_ok(aktif)}", callback_data="p:duyuru_tog")],
                [
                    InlineKeyboardButton("1s", callback_data="p:duys1"),
                    InlineKeyboardButton("2s", callback_data="p:duys2"),
                    InlineKeyboardButton("3s", callback_data="p:duys3"),
                    InlineKeyboardButton("5s", callback_data="p:duys5"),
                ],
                [
                    InlineKeyboardButton("6s", callback_data="p:duys6"),
                    InlineKeyboardButton("12s", callback_data="p:duys12"),
                    InlineKeyboardButton("24s", callback_data="p:duys24"),
                ],
                [
                    InlineKeyboardButton("Şimdi gönder", callback_data="p:duyuru_now"),
                    InlineKeyboardButton("Listeyi temizle", callback_data="p:duyuru_clr"),
                ],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]),
        )
        return
    if data == "duyuru_tog":
        cset(cid, "duyuru_aktif", not bool(cget(cid, "duyuru_aktif")))
        await yenile()
        return
    if data.startswith("duys") and data[4:].isdigit():
        cset(cid, "duyuru_saat", int(data[4:]))
        await yenile()
        return
    if data == "duyuru_now":
        ok = await duyuru_gonder_grup(context.bot, cid, zorla=True)
        await q.answer("Gönderildi" if ok else "Boş / hata", show_alert=True)
        return
    if data == "duyuru_clr":
        cset(cid, "duyuru_posts", [])
        await q.answer("Liste temizlendi", show_alert=True)
        await yenile()
        return


    if data == "ipucu":
        aktif = bool(cget(cid, "ipucu_aktif"))
        saat = int(cget(cid, "ipucu_saat") or 3)
        ozel = cget(cid, "ipucu_liste") or []
        await q.edit_message_text(
            f"💡 <b>Otomatik ipucu / bilgi</b>\n"
            f"Durum: {_ok(aktif)}\n"
            f"Aralık: her {saat} saat\n"
            f"Özel mesaj: {len(ozel)} adet\n\n"
            f"<code>/ipucuac</code> · <code>/ipucukapat</code>\n"
            f"<code>/ipucusaat 3</code>\n"
            f"<code>/ipucuekle metin</code>\n"
            f"<code>/ipucu</code> — şimdi bir tane gönder\n"
            f"<code>/ipucutemizle</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Aktif {_ok(aktif)}", callback_data="p:ipucu_tog")],
                [
                    InlineKeyboardButton("1s", callback_data="p:ips1"),
                    InlineKeyboardButton("2s", callback_data="p:ips2"),
                    InlineKeyboardButton("3s", callback_data="p:ips3"),
                    InlineKeyboardButton("5s", callback_data="p:ips5"),
                ],
                [
                    InlineKeyboardButton("6s", callback_data="p:ips6"),
                    InlineKeyboardButton("12s", callback_data="p:ips12"),
                ],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]),
        )
        return
    if data == "ipucu_tog":
        cset(cid, "ipucu_aktif", not bool(cget(cid, "ipucu_aktif")))
        await yenile()
        return
    if data.startswith("ips") and data[3:].isdigit():
        cset(cid, "ipucu_saat", int(data[3:]))
        await yenile()
        return

    if data == "kurallar":
        k = cget(cid, "kurallar") or DEFAULT_G["kurallar"]
        await q.edit_message_text(
            f"📜 <b>Kurallar</b>\n\n{html.escape(str(k))}\n\n"
            f"Değiştirmek için grupta:\n<code>/setrules metin...</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return
    if data == "uyari":
        lim = int(cget(cid, "warn_limit") or 3)
        dk = int(cget(cid, "warn_mute_dk") or 60)
        await q.edit_message_text(
            f"⚠ <b>Uyarılar</b>\nLimit: {lim}\nCeza: {dk} dk mute\n\n"
            f"Komutlar: /warn /unwarn (yanıtla)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Limit 3", callback_data="p:wl3"),
                        InlineKeyboardButton("Limit 5", callback_data="p:wl5"),
                    ],
                    [InlineKeyboardButton("« Geri", callback_data="p:geri")],
                ]
            ),
        )
        return
    if data in ("wl3", "wl5"):
        cset(cid, "warn_limit", 3 if data == "wl3" else 5)
        await yenile("Uyarı limiti güncellendi.\n")
        return
    if data == "log":
        mevcut = cget(cid, "log_kanal")
        await q.edit_message_text(
            f"📋 <b>Log kanalı</b>\nŞu an: <code>{mevcut or 'yok'}</code>\n\n"
            f"1) Botu rapor kanalına admin ekle\n"
            f"2) Gruba <code>/id</code> yaz\n"
            f"3) Kanalda: <code>/setlog {cid}</code>\n"
            f"Kaldır: grupta <code>/unsetlog</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return
    if data == "engel":
        eb = bool(cget(cid, "engel_bot"))
        await q.edit_message_text(
            f"🚫 <b>Engellemeler</b>\n"
            f"Bot ekleme engeli: {_ok(eb)}\n\n"
            f"Açıkken gruba eklenen botlar atılır (senin botun hariç).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(f"Bot engeli {_ok(eb)}", callback_data="p:ebot")],
                    [InlineKeyboardButton("« Geri", callback_data="p:geri")],
                ]
            ),
        )
        return
    if data == "ebot":
        cset(cid, "engel_bot", not bool(cget(cid, "engel_bot")))
        await yenile()
        return
    if data == "uzun":
        mx = int(cget(cid, "mesaj_max") or 0)
        await q.edit_message_text(
            f"📏 <b>Mesaj uzunluğu</b>\nŞu an: {mx or 'sınırsız'}\n\n"
            f"0 = kapalı. Uzun mesaj silinir.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Kapalı", callback_data="p:um0"),
                        InlineKeyboardButton("500", callback_data="p:um500"),
                        InlineKeyboardButton("1000", callback_data="p:um1000"),
                    ],
                    [InlineKeyboardButton("« Geri", callback_data="p:geri")],
                ]
            ),
        )
        return
    if data in ("um0", "um500", "um1000"):
        cset(cid, "mesaj_max", int(data[2:]))
        await yenile()
        return
    if data == "yardim":
        await q.edit_message_text(
            "🔧 <b>Moderasyon komutları</b>\n\n"
            "<code>/ban</code> yanıt veya @user\n"
            "<code>/unban</code> @user\n"
            "<code>/kick</code> yanıt\n"
            "<code>/mute 30</code> yanıt (dk)\n"
            "<code>/unmute</code> yanıt\n"
            "<code>/warn</code> / <code>/unwarn</code>\n"
            "<code>/reload</code> admin listesi\n"
            "<code>/id</code> chat id\n"
            "<code>/setrules metin</code>\n"
            "<code>/setwelcome metin</code>  ({ad} kullan)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Geri", callback_data="p:geri")]]
            ),
        )
        return
    if data == "geri":
        await yenile()
        return
    await yenile()


# ---------- moderasyon komutlari ----------
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


class _FakeUser:
    def __init__(self, uid, ad="", uname=""):
        self.id = int(uid)
        self.full_name = ad or str(uid)
        self.username = uname
        self.first_name = (ad or str(uid)).split()[0]
        self.is_bot = False


async def hedef_kullanici(update, context):
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
        return None


def _ad(u):
    return html.escape(getattr(u, "full_name", None) or str(getattr(u, "id", "?")))


async def _mod_giris(update, context, cmd_name: str = None):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user:
        return None
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return None
    await komut_sil(msg, context.bot)
    # komut adi: parametre veya mesajdan
    if cmd_name is None and msg.text:
        part = msg.text.split()[0].lstrip("/").split("@")[0].lower()
        cmd_name = part
    if cmd_name and komut_kapali(chat.id, cmd_name):
        await kisa_cevap(context.bot, chat.id, f"🚫 <code>/{cmd_name}</code> bu grupta kapalı.", 6)
        return None
    if not await admin_mi(chat.id, user, context.bot):
        await kisa_cevap(context.bot, chat.id, "❌ Sadece yöneticiler.", 5)
        return None
    return msg, chat, user


async def ban_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not hedef.id:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/ban</code> veya <code>/ban @user</code>")
        return
    try:
        await context.bot.ban_chat_member(chat.id, hedef.id)
        await kisa_cevap(context.bot, chat.id, f"🚫 {_ad(hedef)} banlandı.")
        await log_gonder(context.bot, chat.id, f"🚫 Ban: {_ad(hedef)} <code>{hedef.id}</code>")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def unban_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        return
    try:
        await context.bot.unban_chat_member(chat.id, hedef.id, only_if_banned=True)
        await kisa_cevap(context.bot, chat.id, f"✅ {_ad(hedef)} ban kalktı.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def kick_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/kick</code>")
        return
    try:
        await context.bot.ban_chat_member(chat.id, hedef.id)
        await context.bot.unban_chat_member(chat.id, hedef.id)
        await kisa_cevap(context.bot, chat.id, f"👢 {_ad(hedef)} atıldı.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def mute_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/mute 30</code>")
        return
    args = list(context.args or [])
    dk = 60
    if update.effective_message.reply_to_message and args and args[0].isdigit():
        dk = max(1, min(int(args[0]), 43200))
    elif len(args) >= 2 and args[1].isdigit():
        dk = max(1, min(int(args[1]), 43200))
    until = datetime.now(timezone.utc) + timedelta(minutes=dk)
    try:
        await context.bot.restrict_chat_member(chat.id, hedef.id, permissions=MUTE_PERMS, until_date=until)
        await kisa_cevap(context.bot, chat.id, f"🔇 {_ad(hedef)} {dk} dk susturuldu.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def unmute_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        return
    try:
        await context.bot.restrict_chat_member(chat.id, hedef.id, permissions=FULL_PERMS)
        await kisa_cevap(context.bot, chat.id, f"🔊 {_ad(hedef)} konuşabilir.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def warn_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/warn</code>")
        return
    lim = int(cget(chat.id, "warn_limit") or 3)
    dk = int(cget(chat.id, "warn_mute_dk") or 60)
    gmap = uyarilar.setdefault(str(chat.id), {})
    say = int(gmap.get(str(hedef.id), 0)) + 1
    gmap[str(hedef.id)] = say
    text = f"⚠️ {_ad(hedef)} uyarı: <b>{say}/{lim}</b>"
    if say >= lim:
        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=dk)
            await context.bot.restrict_chat_member(chat.id, hedef.id, permissions=MUTE_PERMS, until_date=until)
            text += f" → {dk} dk mute"
            gmap[str(hedef.id)] = 0
        except Exception:
            text += " (mute başarısız)"
    await kisa_cevap(context.bot, chat.id, text, 12)
    await log_gonder(context.bot, chat.id, text)


async def unwarn_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
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
        await kisa_cevap(context.bot, chat.id, "🔄 Adminler:\n" + "\n".join(lines), 15)
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def id_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat:
        return
    await komut_sil(msg, context.bot)
    parts = [
        f"<b>Chat</b>: {html.escape(chat.title or getattr(chat,'full_name',None) or '—')}",
        f"ID: <code>{chat.id}</code>",
        f"Tür: {chat.type}",
    ]
    if user:
        parts.append(f"Sen: <code>{user.id}</code>")
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        parts.append(f"Yanıt: <code>{u.id}</code> {html.escape(u.full_name or '')}")
    await kisa_cevap(context.bot, chat.id, "\n".join(parts), 20)


async def setrules_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/setrules metin</code>")
        return
    metin = " ".join(context.args)
    cset(chat.id, "kurallar", metin)
    await kisa_cevap(context.bot, chat.id, "✅ Kurallar kaydedildi.")


async def setwelcome_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/setwelcome metin</code> ({ad})")
        return
    cset(chat.id, "hosgeldin_metin", " ".join(context.args))
    cset(chat.id, "hosgeldin", True)
    await kisa_cevap(context.bot, chat.id, "✅ Karşılama kaydedildi ve açıldı.")


async def setlog_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user:
        return
    try:
        await msg.delete()
    except Exception:
        pass
    yetkili = sahip_mi(user)
    if not yetkili:
        try:
            m = await context.bot.get_chat_member(chat.id, user.id)
            yetkili = m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER, "administrator", "creator")
        except Exception:
            pass
    if not yetkili:
        return
    args = list(context.args or [])
    if not args and msg.text:
        parts = msg.text.split()
        if len(parts) >= 2:
            args = parts[1:]
    grup_id = None
    kanal_id = None
    if chat.type in (ChatType.CHANNEL, "channel"):
        kanal_id = chat.id
        if args and args[0].lstrip("-").isdigit():
            grup_id = int(args[0])
    elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        grup_id = chat.id
        if args and args[0].lstrip("-").isdigit():
            kanal_id = int(args[0])
    if not grup_id or not kanal_id or grup_id == kanal_id:
        await kisa_cevap(
            context.bot,
            chat.id,
            "📋 Rapor kanalında yaz:\n<code>/setlog GRUP_ID</code>\nGruba /id ile ID al.",
            15,
        )
        return
    cset(grup_id, "log_kanal", kanal_id)
    await kisa_cevap(context.bot, chat.id, f"✅ Log: grup <code>{grup_id}</code> → kanal <code>{kanal_id}</code>", 12)
    try:
        await context.bot.send_message(kanal_id, f"✅ Log kanalı aktif. Grup: <code>{grup_id}</code>", parse_mode="HTML")
    except Exception:
        pass


async def unsetlog_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "log_kanal", None)
    await kisa_cevap(context.bot, chat.id, "✅ Log kaldırıldı.")


async def izinlink_komut(update, context):
    """Izinli domain ekle: /izinlink t.me youtube.com"""
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        lst = cget(chat.id, "link_izin") or []
        await kisa_cevap(
            context.bot,
            chat.id,
            "Kullanım: <code>/izinlink t.me youtube.com</code>\n"
            f"Şu an: {', '.join(lst) if lst else 'yok'}",
            12,
        )
        return
    lst = list(cget(chat.id, "link_izin") or [])
    for a in context.args:
        a = a.lower().strip().replace("https://", "").replace("http://", "").strip("/")
        if a and a not in lst:
            lst.append(a)
    cset(chat.id, "link_izin", lst)
    await kisa_cevap(context.bot, chat.id, f"✅ İzinli: {', '.join(lst)}")



async def block_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/block kelime</code>")
        return
    lst = list(cget(chat.id, "blocklist") or [])
    for a in context.args:
        a = a.lower().strip()
        if a and a not in lst:
            lst.append(a)
    cset(chat.id, "blocklist", lst)
    await kisa_cevap(context.bot, chat.id, f"✅ Block: {', '.join(lst)}")


async def blockclear_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "blocklist", [])
    await kisa_cevap(context.bot, chat.id, "✅ Blocklist temiz.")


async def save_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if len(context.args or []) < 2:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/save isim metin</code>")
        return
    isim = context.args[0].lower().lstrip("#")
    metin = " ".join(context.args[1:])
    notes = dict(cget(chat.id, "notes") or {})
    notes[isim] = metin
    cset(chat.id, "notes", notes)
    await kisa_cevap(context.bot, chat.id, f"✅ Not kaydedildi: #{isim}")


async def get_komut(update, context):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_sil(msg, context.bot)
    if not context.args:
        return
    isim = context.args[0].lower().lstrip("#")
    notes = cget(chat.id, "notes") or {}
    if isim in notes:
        await context.bot.send_message(chat.id, notes[isim])



async def pin_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    msg, chat, _ = g
    target = msg.reply_to_message
    if not target:
        await kisa_cevap(context.bot, chat.id, "Bir mesaja yanıtla: <code>/pin</code>")
        return
    try:
        await context.bot.pin_chat_message(chat.id, target.message_id, disable_notification=True)
        await kisa_cevap(context.bot, chat.id, "📌 Sabitlendi.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def unpin_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    msg, chat, _ = g
    try:
        if msg.reply_to_message:
            await context.bot.unpin_chat_message(chat.id, msg.reply_to_message.message_id)
        else:
            await context.bot.unpin_chat_message(chat.id)
        await kisa_cevap(context.bot, chat.id, "📌 Sabit kaldırıldı.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def unpinall_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    try:
        await context.bot.unpin_all_chat_messages(chat.id)
        await kisa_cevap(context.bot, chat.id, "📌 Tüm sabitler kaldırıldı.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def del_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    msg, chat, _ = g
    if not msg.reply_to_message:
        return
    try:
        await msg.reply_to_message.delete()
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def purge_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    msg, chat, _ = g
    # /purge N  veya yanittan buraya
    n = None
    if context.args and context.args[0].isdigit():
        n = min(int(context.args[0]), 100)
    if msg.reply_to_message:
        start_id = msg.reply_to_message.message_id
        end_id = msg.message_id
        silinen = 0
        for mid in range(start_id, end_id + 1):
            try:
                await context.bot.delete_message(chat.id, mid)
                silinen += 1
            except Exception:
                pass
            if silinen >= 100:
                break
        await kisa_cevap(context.bot, chat.id, f"🗑 {silinen} mesaj silindi.")
        return
    if n:
        # son N mesaj - telegram API tek tek, sadece bilinen id yok; reply zorunlu uyar
        await kisa_cevap(context.bot, chat.id, "Yanıtlanan mesajdan buraya kadar silmek için mesaja yanıtla <code>/purge</code>")
        return
    await kisa_cevap(context.bot, chat.id, "Kullanım: mesaja yanıtla <code>/purge</code>")


async def filter_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if len(context.args or []) < 2:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/filter kelime cevap metni</code>")
        return
    kelime = context.args[0].lower()
    cevap = " ".join(context.args[1:])
    fl = dict(cget(chat.id, "filters") or {})
    fl[kelime] = cevap
    cset(chat.id, "filters", fl)
    await kisa_cevap(context.bot, chat.id, f"✅ Filter: <code>{html.escape(kelime)}</code>")


async def stop_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        return
    kelime = context.args[0].lower()
    fl = dict(cget(chat.id, "filters") or {})
    fl.pop(kelime, None)
    cset(chat.id, "filters", fl)
    await kisa_cevap(context.bot, chat.id, f"✅ Filter silindi: {html.escape(kelime)}")


async def filters_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    fl = cget(chat.id, "filters") or {}
    if not fl:
        await kisa_cevap(context.bot, chat.id, "Filter yok.")
        return
    txt = "🔤 Filters:\n" + "\n".join(f"• <code>{html.escape(k)}</code>" for k in fl)
    await kisa_cevap(context.bot, chat.id, txt, 20)


async def newfed_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not user or not msg:
        return
    await komut_sil(msg, context.bot)
    if not sahip_mi(user) and chat.type != ChatType.PRIVATE:
        if not await admin_mi(chat.id, user, context.bot):
            return
    isim = " ".join(context.args) if context.args else f"Fed-{user.id}"
    import uuid
    fid = str(uuid.uuid4())[:8]
    feds = durum.setdefault("federations", {})
    feds[fid] = {"name": isim, "owner": user.id, "chats": []}
    durum_kaydet()
    await kisa_cevap(context.bot, chat.id if chat else user.id, f"🌐 Fed oluşturuldu\nID: <code>{fid}</code>\nİsim: {html.escape(isim)}", 20)


async def joinfed_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, user = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/joinfed FED_ID</code>")
        return
    fid = context.args[0]
    feds = durum.get("federations") or {}
    if fid not in feds:
        await kisa_cevap(context.bot, chat.id, "❌ Fed bulunamadı.")
        return
    if chat.id not in feds[fid]["chats"]:
        feds[fid]["chats"].append(chat.id)
    cset(chat.id, "fed_id", fid)
    durum_kaydet()
    await kisa_cevap(context.bot, chat.id, f"✅ Fed bağlandı: <code>{fid}</code>")


async def leavefed_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    fid = cget(chat.id, "fed_id")
    if fid and fid in (durum.get("federations") or {}):
        chats = durum["federations"][fid].get("chats") or []
        if chat.id in chats:
            chats.remove(chat.id)
    cset(chat.id, "fed_id", None)
    durum_kaydet()
    await kisa_cevap(context.bot, chat.id, "✅ Fed ayrıldı.")


async def fban_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, user = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla veya /fban @user")
        return
    fid = cget(chat.id, "fed_id")
    if not fid:
        await kisa_cevap(context.bot, chat.id, "Önce /joinfed ile fed bağla.")
        return
    sebep = " ".join(context.args[1:]) if context.args and not update.effective_message.reply_to_message else (" ".join(context.args) if context.args else "fed ban")
    bans = durum.setdefault("fed_bans", {}).setdefault(fid, {})
    bans[str(hedef.id)] = {"by": user.id, "reason": sebep, "name": getattr(hedef, "full_name", "")}
    durum_kaydet()
    feds = durum.get("federations") or {}
    chats = (feds.get(fid) or {}).get("chats") or [chat.id]
    ok = 0
    for gid in chats:
        try:
            await context.bot.ban_chat_member(gid, hedef.id)
            ok += 1
        except Exception:
            pass
    await kisa_cevap(context.bot, chat.id, f"🌐 FBan {_ad(hedef)} — {ok} grup")


async def funban_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        return
    fid = cget(chat.id, "fed_id")
    if not fid:
        return
    bans = durum.setdefault("fed_bans", {}).setdefault(fid, {})
    bans.pop(str(hedef.id), None)
    durum_kaydet()
    feds = durum.get("federations") or {}
    chats = (feds.get(fid) or {}).get("chats") or [chat.id]
    for gid in chats:
        try:
            await context.bot.unban_chat_member(gid, hedef.id, only_if_banned=True)
        except Exception:
            pass
    await kisa_cevap(context.bot, chat.id, f"✅ Funban {_ad(hedef)}")


async def export_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    data = durum.get("grup", {}).get(str(chat.id), {})
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    from io import BytesIO
    bio = BytesIO(payload.encode("utf-8"))
    bio.name = f"settings_{chat.id}.json"
    try:
        await context.bot.send_document(chat.id, document=bio, caption="📦 Grup ayarları export")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def import_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    msg, chat, _ = g
    doc = None
    if msg.reply_to_message and msg.reply_to_message.document:
        doc = msg.reply_to_message.document
    elif msg.document:
        doc = msg.document
    if not doc:
        await kisa_cevap(context.bot, chat.id, "JSON dosyasına yanıtla: <code>/import</code>")
        return
    try:
        f = await context.bot.get_file(doc.file_id)
        raw = bytes(await f.download_as_bytearray())
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON obje olmalı")
        durum.setdefault("grup", {})[str(chat.id)] = data
        durum_kaydet()
        await kisa_cevap(context.bot, chat.id, f"✅ {len(data)} ayar içe aktarıldı.")
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ Import: {html.escape(str(e))}")



async def report_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return
    await komut_sil(msg, context.bot)
    if not cget(chat.id, "reports"):
        await kisa_cevap(context.bot, chat.id, "📣 Rapor sistemi kapalı.", 6)
        return
    if komut_kapali(chat.id, "report"):
        await kisa_cevap(context.bot, chat.id, "🚫 /report kapalı.", 6)
        return
    hedef = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        hedef = msg.reply_to_message.from_user
    sebep = " ".join(context.args) if context.args else "sebep belirtilmedi"
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Rapor için mesaja yanıtla: <code>/report sebep</code>")
        return
    metin = (
        f"📣 <b>Rapor</b>\n"
        f"Şikayetçi: {_ad(user)} <code>{user.id}</code>\n"
        f"Hedef: {_ad(hedef)} <code>{hedef.id}</code>\n"
        f"Sebep: {html.escape(sebep)}\n"
        f"Grup: {html.escape(chat.title or '')} <code>{chat.id}</code>"
    )
    await log_gonder(context.bot, chat.id, metin)
    # adminlere ozelden de dene
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        for a in admins:
            if a.user.is_bot:
                continue
            try:
                await context.bot.send_message(a.user.id, metin, parse_mode="HTML")
            except Exception:
                pass
    except Exception:
        pass
    await kisa_cevap(context.bot, chat.id, "✅ Rapor iletildi.", 6)


async def disable_komut(update, context):
    g = await _mod_giris(update, context, "disable")
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/disable ban</code>")
        return
    isim = context.args[0].lower().lstrip("/")
    d = list(cget(chat.id, "disabled_cmds") or [])
    if isim not in d:
        d.append(isim)
    cset(chat.id, "disabled_cmds", d)
    await kisa_cevap(context.bot, chat.id, f"🚫 <code>/{isim}</code> kapatıldı.")


async def enable_komut(update, context):
    g = await _mod_giris(update, context, "enable")
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/enable ban</code>")
        return
    isim = context.args[0].lower().lstrip("/")
    d = [x for x in (cget(chat.id, "disabled_cmds") or []) if x.lower() != isim]
    cset(chat.id, "disabled_cmds", d)
    await kisa_cevap(context.bot, chat.id, f"✅ <code>/{isim}</code> açıldı.")


async def disabled_komut(update, context):
    g = await _mod_giris(update, context, "disabled")
    if not g:
        return
    _, chat, _ = g
    d = cget(chat.id, "disabled_cmds") or []
    await kisa_cevap(
        context.bot, chat.id,
        "Kapalı: " + (", ".join(f"/{x}" for x in d) if d else "yok"),
        12,
    )



def _duyuru_baslik(msg) -> str:
    t = (msg.text or msg.caption or "").strip()
    if not t:
        if msg.photo:
            return "📷 Fotoğraf"
        if msg.video:
            return "🎬 Video"
        if msg.document:
            return "📎 Dosya"
        return "Duyuru"
    line = t.split("\n")[0].strip()
    if len(line) > 60:
        line = line[:57] + "..."
    return line


def _duyuru_link(chat, msg_id: int) -> str:
    # public username
    un = getattr(chat, "username", None)
    if un:
        return f"https://t.me/{un}/{msg_id}"
    # private channel: t.me/c/ID/msg without -100
    cid = str(chat.id)
    if cid.startswith("-100"):
        cid = cid[4:]
    return f"https://t.me/c/{cid}/{msg_id}"



async def kanal_duyuru_yakala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal postlarini bagli gruba kaydet."""
    msg = update.effective_message or update.channel_post
    chat = update.effective_chat
    if not msg or not chat:
        return
    if chat.type not in (ChatType.CHANNEL, "channel"):
        return
    for gid_s, conf in (durum.get("grup") or {}).items():
        if not isinstance(conf, dict):
            continue
        if conf.get("duyuru_kanal") != chat.id:
            continue
        posts = list(conf.get("duyuru_posts") or [])
        bugun = datetime.now(TR).strftime("%Y-%m-%d")
        entry = {
            "id": msg.message_id,
            "title": _duyuru_baslik(msg),
            "date": bugun,
            "link": _duyuru_link(chat, msg.message_id),
        }
        posts = [p for p in posts if p.get("id") != msg.message_id]
        posts.append(entry)
        keep = []
        for p in posts:
            try:
                d = datetime.strptime(p.get("date", bugun), "%Y-%m-%d").date()
                if (datetime.now(TR).date() - d).days <= 3:
                    keep.append(p)
            except Exception:
                keep.append(p)
        conf["duyuru_posts"] = keep[-40:]
        durum_kaydet()
        log.info("duyuru kayit grup=%s post=%s", gid_s, (entry["title"] or "")[:40])


def duyuru_liste_metni(chat_id, bos_mesaj=False):
    posts = list(cget(chat_id, "duyuru_posts") or [])
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    bugunku = [p for p in posts if p.get("date") == bugun]
    if not bugunku:
        if bos_mesaj:
            return "📣 <b>Bugünkü Duyurular</b>\n\nHenüz duyuru yok."
        return None
    lines = ["📣 <b>Bugünkü Duyurular</b>", ""]
    for i, p in enumerate(bugunku[-20:], 1):
        title = html.escape(p.get("title") or "Duyuru")
        link = p.get("link") or ""
        if link:
            lines.append(f'{i}. <a href="{html.escape(link)}">{title}</a>')
        else:
            lines.append(f"{i}. {title}")
    return "\n".join(lines)


async def duyuru_gonder_grup(bot, chat_id, zorla=False):
    text = duyuru_liste_metni(chat_id, bos_mesaj=zorla)
    if not text:
        return False
    try:
        await bot.send_message(
            chat_id, text, parse_mode="HTML", disable_web_page_preview=True
        )
        return True
    except Exception as e:
        log.warning("duyuru gonder: %s", e)
        return False


async def setduyuru_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user:
        return
    try:
        await msg.delete()
    except Exception:
        pass
    yetkili = sahip_mi(user)
    if not yetkili:
        try:
            m = await context.bot.get_chat_member(chat.id, user.id)
            yetkili = m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER, "administrator", "creator")
        except Exception:
            pass
    if not yetkili:
        return
    args = list(context.args or [])
    if not args and msg.text:
        parts = msg.text.split()
        if len(parts) >= 2:
            args = parts[1:]
    grup_id = None
    kanal_id = None
    if chat.type in (ChatType.CHANNEL, "channel"):
        kanal_id = chat.id
        if args and args[0].lstrip("-").isdigit():
            grup_id = int(args[0])
    elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        grup_id = chat.id
        if args and args[0].lstrip("-").isdigit():
            kanal_id = int(args[0])
    if not grup_id or not kanal_id:
        await kisa_cevap(
            context.bot, chat.id,
            "📢 Kanalda yaz:\n<code>/setduyuru GRUP_ID</code>\n"
            "Grup ID: gruba /id",
            15,
        )
        return
    cset(grup_id, "duyuru_kanal", kanal_id)
    cset(grup_id, "duyuru_aktif", True)
    await kisa_cevap(
        context.bot, chat.id,
        f"✅ Duyuru kanalı bağlandı\nGrup: <code>{grup_id}</code>\nKanal: <code>{kanal_id}</code>",
        12,
    )



async def duyuruekle_komut(update, context):
    """Manuel duyuru satiri ekle (kanal sart degil)."""
    g = await _mod_giris(update, context, "duyuruekle")
    if not g:
        return
    _, chat, _ = g
    metin = " ".join(context.args or []).strip()
    if not metin and update.effective_message:
        parts = (update.effective_message.text or "").split(maxsplit=1)
        metin = parts[1].strip() if len(parts) > 1 else ""
    if not metin:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/duyuruekle metin...</code>")
        return
    posts = list(cget(chat.id, "duyuru_posts") or [])
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    posts.append({
        "id": int(time.time()),
        "title": metin[:200],
        "date": bugun,
        "link": "",
    })
    cset(chat.id, "duyuru_posts", posts[-40:])
    await kisa_cevap(context.bot, chat.id, f"✅ Duyuru eklendi ({len(posts)}).")


async def duyuru_komut(update, context):
    g = await _mod_giris(update, context, "duyuru")
    if not g:
        return
    _, chat, _ = g
    await duyuru_gonder_grup(context.bot, chat.id, zorla=True)


async def duyuruac_komut(update, context):
    g = await _mod_giris(update, context, "duyuruac")
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "duyuru_aktif", True)
    await kisa_cevap(context.bot, chat.id, "📢 Duyuru listesi açıldı.")


async def duyurukapat_komut(update, context):
    g = await _mod_giris(update, context, "duyurukapat")
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "duyuru_aktif", False)
    await kisa_cevap(context.bot, chat.id, "📢 Duyuru listesi kapatıldı.")


async def duyurusaat_komut(update, context):
    g = await _mod_giris(update, context, "duyurusaat")
    if not g:
        return
    _, chat, _ = g
    if not context.args or not context.args[0].isdigit():
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/duyurusaat 2</code>")
        return
    s = max(1, min(int(context.args[0]), 48))
    cset(chat.id, "duyuru_saat", s)
    await kisa_cevap(context.bot, chat.id, f"✅ Her {s} saatte bir gönderilecek.")


async def duyuru_periyodik(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue: duyuru listesi + ipucu."""
    bot = context.bot
    now = time.time()
    for gid_s, conf in list((durum.get("grup") or {}).items()):
        if not isinstance(conf, dict):
            continue
        try:
            gid = int(gid_s)
        except Exception:
            continue
        # duyuru listesi
        if conf.get("duyuru_aktif"):
            saat = float(conf.get("duyuru_saat") or 5)
            last = float(conf.get("duyuru_last") or 0)
            if now - last >= saat * 3600 - 30:
                try:
                    ok = await duyuru_gonder_grup(bot, gid, zorla=False)
                    conf["duyuru_last"] = now  # bos olsa da sayac ilerlesin (spam yok)
                    durum_kaydet()
                    if ok:
                        log.info("duyuru gonderildi grup=%s", gid_s)
                except Exception as e:
                    log.warning("duyuru job %s: %s", gid_s, e)
        # ipucu
        if conf.get("ipucu_aktif"):
            saat = int(conf.get("ipucu_saat") or 3)
            last = float(conf.get("ipucu_last") or 0)
            if now - last >= saat * 3600 - 30:
                try:
                    await ipucu_gonder_grup(bot, gid)
                    conf["ipucu_last"] = now
                    durum_kaydet()
                except Exception as e:
                    log.warning("ipucu job %s: %s", gid_s, e)



def _ipucu_havuz(chat_id):
    ozel = list(cget(chat_id, "ipucu_liste") or [])
    # once ozel, sonra varsayilan — tekrarsiz secim icin ayri tutulur
    return ozel, list(DEFAULT_IPUCU)


async def ipucu_gonder_grup(bot, chat_id):
    """Her seferinde farkli ipucu; kullanilanlar bitince sifirlanir."""
    import random
    ozel, varsayilan = _ipucu_havuz(chat_id)
    havuz = ozel + varsayilan
    if not havuz:
        return False
    kullanilan = list(cget(chat_id, "ipucu_kullanilan") or [])
    adaylar = [t for t in havuz if t not in kullanilan]
    if not adaylar:
        kullanilan = []
        adaylar = list(havuz)
    text = random.choice(adaylar)
    kullanilan.append(text)
    # sadece son N hatirla (havuz buyukse)
    cset(chat_id, "ipucu_kullanilan", kullanilan[-max(5, len(havuz)):])
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
        return True
    except Exception as e:
        log.warning("ipucu: %s", e)
        return False


async def ipucu_komut(update, context):
    g = await _mod_giris(update, context, "ipucu")
    if not g:
        return
    _, chat, _ = g
    await ipucu_gonder_grup(context.bot, chat.id)


async def ipucuac_komut(update, context):
    g = await _mod_giris(update, context, "ipucuac")
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "ipucu_aktif", True)
    await kisa_cevap(context.bot, chat.id, "💡 Otomatik ipucu açıldı.")


async def ipucukapat_komut(update, context):
    g = await _mod_giris(update, context, "ipucukapat")
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "ipucu_aktif", False)
    await kisa_cevap(context.bot, chat.id, "💡 Otomatik ipucu kapatıldı.")


async def ipucusaat_komut(update, context):
    g = await _mod_giris(update, context, "ipucusaat")
    if not g:
        return
    _, chat, _ = g
    if not context.args or not context.args[0].isdigit():
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/ipucusaat 3</code>")
        return
    s = max(1, min(int(context.args[0]), 24))
    cset(chat.id, "ipucu_saat", s)
    await kisa_cevap(context.bot, chat.id, f"✅ Her {s} saatte bir ipucu.")


async def ipucuekle_komut(update, context):
    g = await _mod_giris(update, context, "ipucuekle")
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/ipucuekle metin...</code>")
        return
    metin = " ".join(context.args)
    lst = list(cget(chat.id, "ipucu_liste") or [])
    lst.append("💡 " + metin)
    cset(chat.id, "ipucu_liste", lst[-50:])
    await kisa_cevap(context.bot, chat.id, f"✅ İpucu eklendi ({len(lst)} adet).")


async def ipucutemizle_komut(update, context):
    g = await _mod_giris(update, context, "ipucutemizle")
    if not g:
        return
    _, chat, _ = g
    cset(chat.id, "ipucu_liste", [])
    await kisa_cevap(context.bot, chat.id, "✅ Özel ipuçları silindi (varsayılanlar durur).")


async def rules_komut(update, context):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat:
        return
    if chat.type == ChatType.PRIVATE:
        return
    await komut_sil(msg, context.bot)
    k = cget(chat.id, "kurallar") or DEFAULT_G["kurallar"]
    await kisa_cevap(context.bot, chat.id, f"📜 <b>Kurallar</b>\n\n{html.escape(str(k))}", 30)


# ---------- hosgeldin / ayrildi / servis ----------
async def hosgeldin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or not msg.new_chat_members:
        return
    if cget(chat.id, "servis_sil"):
        try:
            await msg.delete()
        except Exception:
            pass
    for u in msg.new_chat_members:
        if u.is_bot:
            if cget(chat.id, "engel_bot") and u.id != context.bot.id:
                try:
                    await context.bot.ban_chat_member(chat.id, u.id)
                    await context.bot.unban_chat_member(chat.id, u.id)
                    await log_gonder(context.bot, chat.id, f"🤖 Bot atıldı: {html.escape(u.full_name or str(u.id))}")
                except Exception:
                    pass
            continue
        uye_kaydi(chat.id, u)
        # Fed ban kontrol
        fid = cget(chat.id, "fed_id")
        if fid:
            bans = (durum.get("fed_bans") or {}).get(fid) or {}
            if str(u.id) in bans:
                try:
                    await context.bot.ban_chat_member(chat.id, u.id)
                    await log_gonder(context.bot, chat.id, f"🌐 Fed-ban ile engellendi: {html.escape(u.full_name or str(u.id))}")
                except Exception:
                    pass
                continue
        await log_gonder(
            context.bot, chat.id,
            f"➕ {html.escape(u.full_name or str(u.id))} gruba katıldı <code>{u.id}</code>",
        )
        if cget(chat.id, "antiraid"):
            jt = join_times[chat.id]
            now = time.time()
            sn = int(cget(chat.id, "antiraid_sn") or 10)
            adet = int(cget(chat.id, "antiraid_adet") or 5)
            while jt and now - jt[0] > sn:
                jt.popleft()
            jt.append(now)
            if len(jt) >= adet:
                try:
                    await context.bot.set_chat_permissions(chat.id, MUTE_PERMS)
                    await kisa_cevap(context.bot, chat.id, "🛡 AntiRaid: grup geçici kilitlendi.", 15)
                    await log_gonder(context.bot, chat.id, "🛡 AntiRaid tetiklendi")
                except Exception as e:
                    log.warning("antiraid: %s", e)
        # Mute: sadece bu grupta ayar aciksa (varsayilan 0 = kapali)
        mute_dk = int(cget(chat.id, "hosgeldin_mute") or 0)
        if cget(chat.id, "approval") or cget(chat.id, "captcha"):
            mute_dk = max(mute_dk, 60)
        if mute_dk > 0 and (cget(chat.id, "hosgeldin") or cget(chat.id, "approval") or cget(chat.id, "captcha")):
            try:
                until = datetime.now(timezone.utc) + timedelta(minutes=mute_dk)
                await context.bot.restrict_chat_member(chat.id, u.id, permissions=MUTE_PERMS, until_date=until)
            except Exception as e:
                log.warning("join mute: %s", e)
        if cget(chat.id, "captcha"):
            pending_captcha[(chat.id, u.id)] = True
            if cget(chat.id, "captcha_math"):
                import random
                a, b = random.randint(2, 9), random.randint(2, 9)
                pending_captcha[(chat.id, u.id)] = a + b
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(str(a + b), callback_data=f"cap:{chat.id}:{u.id}:{a+b}"),
                    InlineKeyboardButton(str(a + b + 2), callback_data=f"cap:{chat.id}:{u.id}:x"),
                    InlineKeyboardButton(str(max(1, a + b - 3)), callback_data=f"cap:{chat.id}:{u.id}:y"),
                ]])
                txt = f"🔐 {html.escape(u.full_name or 'Üye')}, {a}+{b} = ?"
            else:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ İnsanım", callback_data=f"cap:{chat.id}:{u.id}:ok")]])
                txt = f"🔐 {html.escape(u.full_name or 'Üye')}, gruba yazmak için butona bas."
            try:
                gonder = await context.bot.send_message(chat.id, txt, parse_mode="HTML", reply_markup=kb)
                asyncio.create_task(sil_sonra(context.bot, chat.id, gonder.message_id, 120))
            except Exception as e:
                log.warning("captcha: %s", e)
        elif cget(chat.id, "hosgeldin"):
            metin = (cget(chat.id, "hosgeldin_metin") or DEFAULT_G["hosgeldin_metin"]).replace(
                "{ad}", html.escape(u.full_name or u.first_name or "üye")
            )
            try:
                gonder = await context.bot.send_message(chat.id, metin, parse_mode="HTML")
                sil = int(cget(chat.id, "hosgeldin_sil") or 0)
                if sil > 0:
                    asyncio.create_task(sil_sonra(context.bot, chat.id, gonder.message_id, sil))
            except Exception as e:
                log.warning("hosgeldin: %s", e)


async def ayrildi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
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
    await log_gonder(context.bot, chat.id, f"➖ {html.escape(ad)} gruptan ayrıldı")
    if not cget(chat.id, "hoscaakal"):
        return
    metin = (cget(chat.id, "hoscaakal_metin") or DEFAULT_G["hoscaakal_metin"]).replace("{ad}", ad)
    try:
        gonder = await context.bot.send_message(chat.id, metin)
        sil = int(cget(chat.id, "hoscaakal_sil") or 0)
        if sil > 0:
            asyncio.create_task(sil_sonra(context.bot, chat.id, gonder.message_id, sil))
    except Exception as e:
        log.warning("hoscaakal: %s", e)


async def servis_mesaj_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or chat.type == ChatType.PRIVATE:
        return
    if not cget(chat.id, "servis_sil"):
        return
    try:
        await msg.delete()
    except Exception:
        pass


# ---------- mesaj filtre + AI ----------
LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)", re.I)


def mesajda_link_var(msg, metin: str) -> bool:
    """Metin veya entity icinde link var mi?"""
    if metin and LINK_RE.search(metin):
        return True
    for ent in list(msg.entities or []) + list(msg.caption_entities or []):
        t = getattr(ent, "type", None)
        if t in ("url", "text_link"):
            return True
    return False


async def sahip_yakala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or durum.get("sahip"):
        return
    if SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI:
        durum["sahip"] = user.id
        durum_kaydet()



async def kilit_engel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ozelde sahibinden baskasini engelle."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    if chat.type != ChatType.PRIVATE:
        return
    if sahip_mi(user):
        durum["sahip"] = user.id
        return
    if update.callback_query:
        try:
            await update.callback_query.answer("🔒 Kilitli — @Turkpronim", show_alert=True)
        except Exception:
            pass
        raise ApplicationHandlerStop
    msg = update.effective_message
    if msg:
        try:
            await msg.reply_text(KILIT_MESAJ)
        except Exception:
            pass
    raise ApplicationHandlerStop


async def mesaj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if user.is_bot:
        return
    metin = (msg.text or msg.caption or "").strip()
    ozel = chat.type == ChatType.PRIVATE
    cid = chat.id

    # --- KILIT ---
    if ozel:
        if not sahip_mi(user):
            if metin:
                try:
                    await msg.reply_text(KILIT_MESAJ)
                except Exception:
                    pass
            return
        durum["sahip"] = user.id
        durum_kaydet()
    else:
        # grup: sadece sahip bu grubun uyesi/yoneticisiyse calis
        if not await sahip_grupta_mi(context.bot, cid):
            return

    if not ozel:
        # admin degilse filtreler
        is_adm = await admin_mi(cid, user, context.bot)
        if not is_adm:
            # sessizlik
            if cget(cid, "sessizlik"):
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            # gece modu 00-07 TR
            if cget(cid, "gece"):
                saat = datetime.now(TR).hour
                bas = int(cget(cid, "gece_bas") or 0)
                bit = int(cget(cid, "gece_bit") or 7)
                if bas <= saat < bit or (bas > bit and (saat >= bas or saat < bit)):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return
            # flood
            if cget(cid, "flood"):
                key = (cid, user.id)
                now = time.time()
                adet = int(cget(cid, "flood_adet") or 5)
                sn = int(cget(cid, "flood_sn") or 5)
                buf = flood_buf[key]
                while buf and now - buf[0] > sn:
                    buf.popleft()
                buf.append(now)
                if len(buf) >= adet:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    dk = int(cget(cid, "flood_mute_dk") or 10)
                    try:
                        until = datetime.now(timezone.utc) + timedelta(minutes=dk)
                        await context.bot.restrict_chat_member(
                            cid, user.id, permissions=MUTE_PERMS, until_date=until
                        )
                        await kisa_cevap(
                            context.bot, cid,
                            f"🌊 Flood: {_ad(user)} {dk} dk mute",
                            8,
                        )
                    except Exception:
                        pass
                    buf.clear()
                    return
            # medya engel
            if cget(cid, "medya_engel"):
                sil = False
                if msg.photo and cget(cid, "medya_foto"):
                    sil = True
                if msg.video and cget(cid, "medya_video"):
                    sil = True
                if msg.animation and cget(cid, "medya_gif"):
                    sil = True
                if msg.sticker and cget(cid, "medya_sticker"):
                    sil = True
                if msg.document and cget(cid, "medya_dosya"):
                    sil = True
                if (msg.voice or msg.audio) and cget(cid, "medya_ses"):
                    sil = True
                if sil:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return
            # link engel (metin + entity)
            if cget(cid, "link_engel") and mesajda_link_var(msg, metin):
                izin = [x.lower() for x in (cget(cid, "link_izin") or [])]
                ok = False
                low_m = (metin or "").lower()
                for d in izin:
                    if d and d in low_m:
                        ok = True
                        break
                if not ok:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return
            # blocklist kelime
            bl = cget(cid, "blocklist") or []
            if bl and metin:
                low_m = metin.lower()
                if any(w in low_m for w in bl if w):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return
            # mesaj uzunlugu
            mx = int(cget(cid, "mesaj_max") or 0)
            if mx > 0 and metin and len(metin) > mx:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        uye_kaydi(cid, user)

    if not metin:
        return

    if ozel and sahip_mi(user):
        low = kucult(metin)
        if low.startswith(("talimat ", "öğret ", "ogret ")):
            t = metin.split(None, 1)[1] if " " in metin else ""
            if t:
                durum.setdefault("talimat", []).append({"t": t, "ts": time.strftime("%Y-%m-%d %H:%M")})
                durum["talimat"] = durum["talimat"][-30:]
                durum_kaydet()
                await msg.reply_text("Talimat kaydedildi.")
                return

    # filters tetik
    if not ozel and metin:
        fl = cget(cid, "filters") or {}
        low_m = metin.lower()
        for k, v in fl.items():
            if k and k in low_m:
                try:
                    await msg.reply_text(v)
                except Exception:
                    pass
                break

    # #not tetik
    if metin.startswith("#") and not ozel:
        isim = metin[1:].split()[0].lower() if metin[1:] else ""
        notes = cget(cid, "notes") or {}
        if isim in notes:
            try:
                await msg.reply_text(notes[isim])
            except Exception:
                pass
            return

    # yapay ceza oylamasi
    if not ozel and metin:
        low_c = kucult(metin)
        if "yapay" in low_c and "ceza" in low_c:
            hedef = None
            if msg.reply_to_message and msg.reply_to_message.from_user:
                hedef = msg.reply_to_message.from_user
            if not hedef and msg.entities:
                for ent in msg.entities:
                    if ent.type == "mention" and msg.text:
                        uname = msg.text[ent.offset + 1 : ent.offset + ent.length]
                        # uyelerden bul
                        for uid, bil in (uyeler.get(str(cid)) or {}).items():
                            if (bil.get("kullanici") or "") == uname.lower():
                                hedef = _FakeUser(uid, bil.get("ad") or uname, uname)
                                break
                    elif ent.type == "text_mention" and ent.user:
                        hedef = ent.user
            if not hedef:
                try:
                    await msg.reply_text(
                        "🔆 Ceza için birine <b>yanıtla</b> veya @kullanıcı etiketle:\n"
                        "<code>yapay ceza</code>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                return
            await ceza_baslat(update, context, hedef, user)
            return

    low = kucult(metin)
    cagrildi = ozel
    reply_bot = False
    mention_bot = False
    if not ozel:
        reply_bot = bool(
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == context.bot.id
        )
        try:
            me = context.bot.username or ""
            if me and f"@{me.lower()}" in low:
                mention_bot = True
        except Exception:
            pass
        if cget(cid, "privacy_ai"):
            cagrildi = bool(reply_bot or mention_bot)
        else:
            if "yapay" in low or reply_bot or mention_bot:
                cagrildi = True

    # Fiyat: once ticker dene (yapay yazilsa bile "yapay 1 btc" -> fiyat)
    fiyat_ok = False
    adaylar = [metin]
    if "yapay" in low:
        adaylar.append(_re_sub_yapay(metin))
    for aday in adaylar:
        if not aday:
            continue
        kt = kisa_token(aday)
        if kt:
            if await fiyat_gonder(update, kt[0], kt[1]):
                fiyat_ok = True
                break
    if fiyat_ok:
        return

    if not cagrildi:
        return

    soru = re.sub(r"(?i)\byapay\b", "", metin).strip() or metin
    ad = (user.first_name or user.full_name or "dostum").split()[0]
    # yanitlanan kisi varsa baglama ekle
    if msg.reply_to_message and msg.reply_to_message.from_user:
        ry = msg.reply_to_message.from_user
        ry_ad = (ry.first_name or ry.full_name or "?").split()[0]
        ry_txt = (msg.reply_to_message.text or msg.reply_to_message.caption or "")[:120]
        if ry.id == context.bot.id:
            soru = f"(Yapay'a yanıt) {soru}"
        else:
            soru = f"({ry_ad} adlı kişiye yanıt, onun mesajı: «{ry_txt}») {soru}"
    key = f"{cid}:{user.id}"
    hist = gecmis.setdefault(key, [])
    hist.append({"role": "user", "content": f"{ad}: {soru}"})
    hist[:] = hist[-12:]
    # grup uyelerini hatirlat
    ek_parts = []
    if not ozel:
        uy = uyeler.get(str(cid)) or {}
        # en aktif / son kayitli uyeler
        isimler = []
        for uid, bil in list(uy.items())[:40]:
            isim = (bil.get("ad") or bil.get("kullanici") or "").strip()
            if isim:
                isimler.append(isim.split()[0] if isim else "")
        isimler = [x for x in isimler if x][:25]
        if isimler:
            ek_parts.append(
                "Bu gruptaki bazı üyeler (unutma, isimleriyle tanı): "
                + ", ".join(isimler)
            )
        ek_parts.append(f"Şu an konuşan: {ad}")
    if durum.get("talimat"):
        ek_parts.append("Ek talimatlar: " + " | ".join(x["t"] for x in durum["talimat"][-5:]))
    ek = "\n".join(ek_parts)
    try:
        await context.bot.send_chat_action(cid, "typing")
    except Exception:
        pass
    yanit = sor(hist, ek=ek)
    if not yanit or "Forbidden" in yanit[:30]:
        yanit = "Anlamadım, tekrar söyler misin?"
    # kisa tut
    if len(yanit) > 220:
        kes = yanit[:220]
        yanit = (kes.rsplit(".", 1)[0] + ".") if "." in kes else kes.rsplit(" ", 1)[0] + "..."
    yanit = yanit.strip()
    if yanit.startswith("🔆"):
        goster = yanit
    else:
        goster = f"🔆 {yanit}"
    hist.append({"role": "assistant", "content": yanit})
    try:
        await msg.reply_text(goster)
    except Exception:
        try:
            await context.bot.send_message(cid, goster)
        except Exception as e:
            log.warning("AI: %s", e)


async def hata(update, ctx):
    err = str(ctx.error or "")
    if "Conflict" in err and "getUpdates" in err:
        log.error("CONFLICT: Ayni token baska yerde calisiyor.")
    else:
        log.warning("Hata: %s", ctx.error)


async def baslat(app):
    me = await app.bot.get_me()
    log.info("Bot hazir @%s | kilit sahip=%s @%s", me.username, SAHIP_ID, SAHIP_KULLANICI)
    log.info(
        "AI keys: groq=%s gemini=%s deepseek=%s mistral=%s openrouter=%s",
        bool(GROQ_KEY), bool(GEMINI_KEY), bool(DEEPSEEK_KEY),
        bool(MISTRAL_KEY), bool(OPENROUTER_KEY),
    )
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    # duyuru job: her 10 dk kontrol (aralik gruba gore)
    try:
        if app.job_queue:
            app.job_queue.run_repeating(duyuru_periyodik, interval=600, first=60)
            log.info("Duyuru job aktif (10dk)")
        else:
            log.warning("JobQueue yok — pip install python-telegram-bot[job-queue]")
    except Exception as e:
        log.warning("JobQueue: %s", e)
    try:
        await app.bot.set_my_commands(
            [
                BotCommand("panel", "Grup ayar paneli"),
                BotCommand("ayarlar", "Grup ayar paneli"),
                BotCommand("ban", "Ban"),
                BotCommand("unban", "Ban kaldır"),
                BotCommand("kick", "Kick"),
                BotCommand("mute", "Mute"),
                BotCommand("unmute", "Unmute"),
                BotCommand("warn", "Uyarı"),
                BotCommand("unwarn", "Uyarı sil"),
                BotCommand("rules", "Kurallar"),
                BotCommand("reload", "Admin listesi"),
                BotCommand("id", "Chat ID"),
            ]
        )
    except Exception:
        pass


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(baslat).build()
    app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE, kilit_engel), group=-3)
    app.add_handler(CallbackQueryHandler(kilit_engel), group=-3)
    app.add_handler(CommandHandler("panel", ayarlar_komut))
    app.add_handler(CommandHandler("ayarlar", ayarlar_komut))
    app.add_handler(CommandHandler("settings", ayarlar_komut))
    app.add_handler(CommandHandler("ban", ban_komut))
    app.add_handler(CommandHandler("unban", unban_komut))
    app.add_handler(CommandHandler("kick", kick_komut))
    app.add_handler(CommandHandler("mute", mute_komut))
    app.add_handler(CommandHandler("unmute", unmute_komut))
    app.add_handler(CommandHandler("warn", warn_komut))
    app.add_handler(CommandHandler("unwarn", unwarn_komut))
    app.add_handler(CommandHandler("reload", reload_komut))
    app.add_handler(CommandHandler("id", id_komut))
    app.add_handler(CommandHandler("setrules", setrules_komut))
    app.add_handler(CommandHandler("setwelcome", setwelcome_komut))
    app.add_handler(CommandHandler("setlog", setlog_komut))
    app.add_handler(CommandHandler("unsetlog", unsetlog_komut))
    app.add_handler(CommandHandler("izinlink", izinlink_komut))
    app.add_handler(CommandHandler("rules", rules_komut))
    app.add_handler(CommandHandler("kurallar", rules_komut))
    app.add_handler(CommandHandler("block", block_komut))
    app.add_handler(CommandHandler("blockclear", blockclear_komut))
    app.add_handler(CommandHandler("save", save_komut))
    app.add_handler(CommandHandler("get", get_komut))
    app.add_handler(CommandHandler("pin", pin_komut))
    app.add_handler(CommandHandler("unpin", unpin_komut))
    app.add_handler(CommandHandler("unpinall", unpinall_komut))
    app.add_handler(CommandHandler("del", del_komut))
    app.add_handler(CommandHandler("purge", purge_komut))
    app.add_handler(CommandHandler("filter", filter_komut))
    app.add_handler(CommandHandler("stop", stop_komut))
    app.add_handler(CommandHandler("filters", filters_komut))
    app.add_handler(CommandHandler("newfed", newfed_komut))
    app.add_handler(CommandHandler("joinfed", joinfed_komut))
    app.add_handler(CommandHandler("leavefed", leavefed_komut))
    app.add_handler(CommandHandler("fban", fban_komut))
    app.add_handler(CommandHandler("funban", funban_komut))
    app.add_handler(CommandHandler("export", export_komut))
    app.add_handler(CommandHandler("import", import_komut))
    app.add_handler(CommandHandler("setduyuru", setduyuru_komut))
    app.add_handler(CommandHandler("duyuru", duyuru_komut))
    app.add_handler(CommandHandler("duyuruekle", duyuruekle_komut))
    app.add_handler(CommandHandler("duyuruac", duyuruac_komut))
    app.add_handler(CommandHandler("duyurukapat", duyurukapat_komut))
    app.add_handler(CommandHandler("duyurusaat", duyurusaat_komut))
    app.add_handler(CommandHandler("ipucu", ipucu_komut))
    app.add_handler(CommandHandler("ipucuac", ipucuac_komut))
    app.add_handler(CommandHandler("ipucukapat", ipucukapat_komut))
    app.add_handler(CommandHandler("ipucusaat", ipucusaat_komut))
    app.add_handler(CommandHandler("ipucuekle", ipucuekle_komut))
    app.add_handler(CommandHandler("ipucutemizle", ipucutemizle_komut))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, kanal_duyuru_yakala))
    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.Regex(r"(?i)^/setduyuru(@\w+)?(\s|$)"),
            setduyuru_komut,
        ),
        group=-1,
    )
    app.add_handler(CommandHandler("report", report_komut))
    app.add_handler(CommandHandler("disable", disable_komut))
    app.add_handler(CommandHandler("enable", enable_komut))
    app.add_handler(CommandHandler("disabled", disabled_komut))
    # kanal postunda /setlog
    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.Regex(r"(?i)^/setlog(@\w+)?(\s|$)"),
            setlog_komut,
        )
    )
    app.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^p:"))
    app.add_handler(CallbackQueryHandler(captcha_buton, pattern=r"^cap:"))
    app.add_handler(CallbackQueryHandler(ceza_oy_callback, pattern=r"^cz:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, hosgeldin))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, ayrildi))
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_TITLE
            | filters.StatusUpdate.NEW_CHAT_PHOTO
            | filters.StatusUpdate.DELETE_CHAT_PHOTO
            | filters.StatusUpdate.PINNED_MESSAGE,
            servis_mesaj_sil,
        )
    )
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION | filters.PHOTO | filters.VIDEO
             | filters.Document.ALL | filters.Sticker.ALL | filters.ANIMATION
             | filters.VOICE | filters.AUDIO)
            & (~filters.COMMAND)
            & filters.UpdateType.MESSAGE,
            mesaj,
        )
    )
    app.add_error_handler(hata)
    log.info("Bot basliyor...")
    # CoinGecko markets on yukle (arka plan)
    def _preload_cg():
        try:
            _cg_load_disk()
            # ilk sayfa hemen
            data = _cg_http(
                "/coins/markets",
                vs_currency="usd",
                order="market_cap_desc",
                per_page=250,
                page=1,
                sparkline="false",
                price_change_percentage="24h",
            )
            if data:
                _cg_index(data)
                _cg_save_disk()
            log.info("CG hazir: %s coin", len(_cg_by_id))
        except Exception as e:
            log.warning("CG preload: %s", e)
        # surekli refresher
        try:
            _cg_refresher()
        except Exception as e:
            log.warning("CG refresher: %s", e)
    threading.Thread(target=_preload_cg, daemon=True).start()

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
