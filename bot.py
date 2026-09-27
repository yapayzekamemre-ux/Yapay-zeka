import asyncio, html, json, logging, os, random, re, threading, time, requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import deque
from datetime import datetime, timedelta, timezone
from groq import Groq
from google import genai
from google.genai import types
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
NVIDIA_KEY = os.environ.get("NVIDIA_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

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

threading.Thread(target=keep_alive, daemon=True).start()

SAHIP_KULLANICI = "jiminienn"
TIP_ARALIK = 3600
TR = timezone(timedelta(hours=3))
NUMARALAR = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
LISTE_KISA = {"günlük", "gunluk", "haftalık", "haftalik", "aylık", "aylik", "bugünkü", "bugunku",
              "duyuru", "duyurular", "duyuruları", "duyurulari"}

SISTEM = (
    "Sen bir Telegram grubunun zeki, esprili, samimi ve makaracı asistanısın. "
    "İnsanlarla sıcak ve doğal konuş. Gerekirse hafif küfür de edebilirsin (amk, aq, lan gibi) ama abartma. "
    "Türkçe konuş. Cevapların 1-3 cümle olsun, gereksiz uzatma. "
    "Cümleleri asla yarım bırakma, her cümleyi düzgün bitir. "
    "ÖNCEKİ KONUŞMAYI MUTLAKA TAKİP ET, bağlamı asla unutma, konu dışına çıkma, başka yerlere sıçrama. "
    "İnsanların isimleriyle hitap et, samimi ol, espri yap. "
    "Kendi adını, hangi model olduğunu veya hangi şirketin ürünü olduğunu ASLA söyleme. "
    "Sorulursa sadece 'Ben grubun yapay zeka asistanıyım' de. "
    "Grubun amacı, içeriği hakkında ASLA bilgi uydurma. "
    "Siyaset konuşma. Yatırım tavsiyesi verme. Bilmediğin şeyi uydurma. "
    "Sahibinin kalıcı talimatlarına sessizce uy."
)

YARDIM = (
    "<b>Herkes:</b> /rules /kurallar /id /info /bilgi /adminlist /top /rapor /report "
    "/notes /notlar /filters /filtreler /locks /kilitler /fiyat btc\n\n"
    "<b>Moderasyon (Rose/Combot):</b>\n"
    "/ban /sban /dban /tban 2h /unban\n"
    "/kick /skick /dkick\n"
    "/mute /smute /dmute /tmute 10m /unmute\n"
    "/warn /dwarn /unwarn /warns /resetwarns\n"
    "/del /purge /pin /unpin\n\n"
    "<b>Yönetim:</b> /panel (butonlu menü) /promote /demote /adminlist\n"
    "/setwelcome metin /welcome on|off /resetwelcome\n"
    "/setrules metin /rules /resetrules\n"
    "/lock link|sticker|... /unlock link /locks /unlocks\n"
    "/setflood 6 /warnlimit 3 /warntime mute\n"
    "/setlog @kanal /unsetlog /save isim metin (#isim)\n\n"
    "<b>Komutsuz:</b> mesaja yanıt + 'yapay banla / sustur / uçur'\n"
    "Özelden: 'yapay karşılama mesajı şöyle yap: ...' tüm gruplara uygulanır."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
log = logging.getLogger("bot")

groq = Groq(api_key=GROQ_KEY, timeout=30)
gem = genai.Client(api_key=GEMINI_KEY)
gecmis = {}
zamanlar = {}
uyari = {}
onbellek = {}
sabit_onbellek = {}
vision_onbellek = {}
bekleyen = {}
gorevler = set()

DOSYA = "uyeler.json"
try:
    with open(DOSYA, "r", encoding="utf-8") as f:
        uyeler = json.load(f)
except Exception:
    uyeler = {}

DURUM = "durum.json"
try:
    with open(DURUM, "r", encoding="utf-8") as f:
        durum = json.load(f)
except Exception:
    durum = {}
for _k, _v in (("son", 0), ("liste", []), ("sahip", None), ("sabit", {}), ("ayar", {}),
               ("warn", {}), ("kara", {}), ("filtre", {}), ("not", {}), ("talimat", []), ("arsiv", {}),
               ("duyuru_saat", 0), ("approved", {}), ("blacklist", {}), ("whitelist", {}),
               ("schedule", []), ("giveaway", {})):
    durum.setdefault(_k, _v)
if not durum["son"]:
    durum["son"] = time.time()

VARS = {"ai": True, "ipucu": True, "hosgeldin": True, "captcha": False, "adminizin": False,
        "kilit": ["link"], "flood": 6, "warn_limit": 3, "warn_eylem": "mute",
        "hosgeldin_metin": None, "kurallar": None, "log_kanal": None, "duyuru_kanal": None, "duyuru_aralik_saat": 3,
        "slowmode": 0, "night_bas": None, "night_bit": None, "newbies_dk": 0, "ai_mod": False}

GLOBAL_AYAR = "_global"

def cget(cid, k):
    """Grup ayarı → global (özelden) → varsayılan."""
    a = durum["ayar"]
    scid = str(cid)
    if scid in a and k in a[scid]:
        return a[scid][k]
    if GLOBAL_AYAR in a and k in a[GLOBAL_AYAR]:
        return a[GLOBAL_AYAR][k]
    return VARS[k]

def cset(cid, k, v):
    durum["ayar"].setdefault(str(cid), {})[k] = v
    durum_kaydet()

def cset_global(k, v):
    """Sahibin özelden verdiği ayar: global + bilinen tüm gruplar."""
    durum["ayar"].setdefault(GLOBAL_AYAR, {})[k] = v
    for gcid in list(uyeler.keys()):
        try:
            if int(gcid) < 0:
                durum["ayar"].setdefault(str(gcid), {})[k] = v
        except Exception:
            pass
    durum_kaydet()

def grup_ayari_uygula(cid, k, v, ozel):
    if ozel:
        cset_global(k, v)
    else:
        cset(cid, k, v)

def tum_kilitleri_ac(ozel=True, cid=None):
    """Rose/Combot gibi: link dahil tüm kilitleri herkese aç."""
    if ozel or cid is None:
        cset_global("kilit", [])
    else:
        cset(cid, "kilit", [])

async def log_gonder(ctx, kaynak_cid, metin):
    """Grup işlemlerini rapor kanalına yaz. log_kanal ayarlı değilse sessizce çık."""
    kid = cget(kaynak_cid, "log_kanal")
    if not kid:
        return
    try:
        await ctx.bot.send_message(int(kid), metin, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Log kanalına yazılamadı ({kid}): {e}")

SAHIP_KOD = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
if not durum["sahip"]:
    print("\n=========================================")
    print(" @" + SAHIP_KULLANICI + " yazinca otomatik sahip olur.")
    print(" Yedek kod: " + SAHIP_KOD + "  (botuna ozelden /sahip " + SAHIP_KOD + ")")
    print("=========================================\n")

def kaydet():
    try:
        with open(DOSYA, "w", encoding="utf-8") as f:
            json.dump(uyeler, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Kayıt hatası: {e}")

def durum_kaydet():
    try:
        with open(DURUM, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Durum kayıt hatası: {e}")

def kucult(t):
    return t.replace("İ", "i").replace("I", "ı").lower()

def uye_kaydi(chat_id, user, say=True):
    k = uyeler.setdefault(str(chat_id), {})
    u = k.setdefault(str(user.id), {"ad": user.full_name, "kullanici": user.username or "",
                                    "ilk": time.strftime("%Y-%m-%d"), "mesaj": 0})
    u["ad"] = user.full_name
    u["kullanici"] = user.username or ""
    if say:
        u["mesaj"] += 1
        if u["mesaj"] == 1 or u["mesaj"] % 5 == 0:
            kaydet()
    return u

def tanidiklar(chat_id):
    k = uyeler.get(str(chat_id), {})
    en = sorted(k.values(), key=lambda u: u["mesaj"], reverse=True)[:15]
    parcalar = []
    for u in en:
        s = u["ad"]
        if u["kullanici"]:
            s = s + " (@" + u["kullanici"] + ")"
        parcalar.append(s + " " + str(u["mesaj"]) + " mesaj")
    return ", ".join(parcalar)

def ad_bul(cid, uid):
    u = uyeler.get(str(cid), {}).get(str(uid))
    return u["ad"] if u else "kullanıcı"

def mention(cid, uid, ad=None):
    return f'<a href="tg://user?id={uid}">{html.escape(ad or ad_bul(cid, uid))}</a>'

def groq_sor(m, sistem):
    son = None
    for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"):
        try:
            r = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sistem}] + m,
            )
            c = r.choices[0].message.content
            if c:
                return c
        except Exception as e:
            son = e
            log.warning(f"Groq {model}: {e}")
    if son:
        raise son
    return None

def _gemini_icerik(m):
    return [{"role": "model" if x["role"] == "assistant" else "user",
             "parts": [{"text": x["content"]}]} for x in m]

def gemini_sor(m, sistem):
    r = gem.models.generate_content(
        model="gemini-3.8-flash",
        contents=_gemini_icerik(m),
        config={"system_instruction": sistem},
    )
    return r.text

def gemini_arama(m, sistem):
    r = gem.models.generate_content(
        model="gemini-3.8-flash",
        contents=_gemini_icerik(m),
        config=types.GenerateContentConfig(
            system_instruction=sistem,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    return r.text

def mistral_sor(m, sistem):
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + MISTRAL_KEY},
        json={"model": "mistral-small-latest",
              "messages": [{"role": "system", "content": sistem}] + m},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def cerebras_sor(m, sistem):
    r = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + CEREBRAS_KEY},
        json={"model": "gpt-oss-120b",
              "messages": [{"role": "system", "content": sistem}] + m},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def openrouter_sor(m, sistem):
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer " + OPENROUTER_KEY},
        json={"model": "meta-llama/llama-3.3-70b-instruct:free",
              "messages": [{"role": "system", "content": sistem}] + m},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

# NVIDIA free endpoint modelleri (build.nvidia.com — sohbet için en iyiler)
NVIDIA_MODELLER = [
    "deepseek-ai/deepseek-v4.1-flash",   # hızlı, akıllı, multimodal
    "z-ai/glm-5.3-flash",                # güçlü sohbet, çok dilli
    "z-ai/glm-5.3",                      # daha derin akıl yürütme
    "mistralai/mistral-nemotron",        # talimat takibi iyi
    "openai/gpt-oss-20b",                # akıl yürütme
    "google/gemma-4-31b-it",             # genel amaçlı güçlü
    "nvidia/nemotron-3.5-lightning-30b-a3b",  # NVIDIA hızlı model
    "meta/llama-3.3-70b-instruct",       # yedek
]

def nvidia_sor(m, sistem, model=None):
    modeller = [model] if model else NVIDIA_MODELLER
    son_hata = None
    for model_id in modeller:
        if not model_id:
            continue
        try:
            r = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + NVIDIA_KEY},
                json={
                    "model": model_id,
                    "messages": [{"role": "system", "content": sistem}] + m,
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
                timeout=25,
            )
            if r.status_code >= 400:
                log.warning(f"NVIDIA {model_id}: HTTP {r.status_code}")
                son_hata = r.text[:200]
                continue
            data = r.json()
            cevap = data["choices"][0]["message"]["content"]
            if cevap:
                log.info(f"NVIDIA cevap: {model_id}")
                return cevap
        except Exception as e:
            log.warning(f"NVIDIA {model_id} hata: {e}")
            son_hata = str(e)
    if son_hata:
        raise RuntimeError(f"NVIDIA modelleri başarısız: {son_hata}")
    return None


def claude_sor(m, sistem):
    """Anthropic Claude — ANTHROPIC_KEY gerekir (console.anthropic.com)."""
    # Anthropic Messages API format
    mesajlar = []
    for x in m:
        role = x.get("role", "user")
        if role == "assistant":
            mesajlar.append({"role": "assistant", "content": x["content"]})
        else:
            mesajlar.append({"role": "user", "content": x["content"]})
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 512,
            "system": sistem,
            "messages": mesajlar,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return text.strip() or None

SAGLAYICILAR = [("Groq", groq_sor), ("Gemini", gemini_sor)]
if CEREBRAS_KEY:
    SAGLAYICILAR.append(("Cerebras", cerebras_sor))
if OPENROUTER_KEY:
    SAGLAYICILAR.append(("OpenRouter", openrouter_sor))
if MISTRAL_KEY:
    SAGLAYICILAR.append(("Mistral", mistral_sor))
if NVIDIA_KEY:
    # NVIDIA en sonda (son çare)
    SAGLAYICILAR.append(("NVIDIA", nvidia_sor))

def sor(mesajlar, ek="", arama=False):
    sistem = SISTEM + ek
    zincir = SAGLAYICILAR
    if arama:
        zincir = [("Gemini+Arama", gemini_arama)] + SAGLAYICILAR
    for ad, fonk in zincir:
        try:
            cevap = fonk(mesajlar, sistem)
            if cevap:
                cevap = re.sub(
                    r"(?i)(tabii ki|anladım\.|başka bir konuda yardımcı olabilir miyim|size yardımcı olmaya hazırım\.?)\s*",
                    "", cevap
                ).strip()
                if len(cevap.split()) > 60:
                    cevap = " ".join(cevap.split()[:50]) + "..."
                return cevap
        except Exception as e:
            log.warning(f"{ad} cöktü: {e}")
    return None

# ---------- NIYET (KOMUT) ANLAMA ----------
NIYET_SISTEM = (
    "Telegram grup botu için niyet anlama motorusun. Kullanıcının Türkçe, yazım hatalı, kısaltmalı ya da argo "
    "olabilecek mesajını oku, SADECE geçerli JSON döndür, başka hiçbir açıklama, giriş cümlesi yazma.\n"
    "action alanı şunlardan biri olmalı: ban, unban, kick, mute, unmute, warn, sil, pin, unpin, duy, "
    "talimat, talimat_sil, talimat_liste, ayar, hosgeldin_metin, kural_metin, yok.\n"
    "Anlamlar: ban=kalıcı yasakla, unban=yasağı kaldır, kick=gruptan at ama yasaklama, mute=belirli süre sustur, "
    "unmute=susturmayı kaldır, warn=uyarı ver, sil=yanıtlanan mesajı sil, pin=yanıtlanan mesajı sabitle, "
    "unpin=sabiti kaldır, duy=yanıtlanan mesajı duyuru arşivine ekle, talimat=botun kalıcı hatırlayacağı bir "
    "kural/tercih belirtiliyor (örn: 'bundan sonra kısa yaz', 'küfürlere cevap verme'), "
    "talimat_sil=kayıtlı talimatları sıfırla, talimat_liste=talimatları göster, "
    "ayar=captcha/hoşgeldin/ipucu özelliğini aç-kapa, hosgeldin_metin=yeni üye karşılama mesajı belirleniyor, "
    "kural_metin=grup kuralları metni belirleniyor.\n"
    "Mesaj sıradan sohbetse, soru soruyorsa, fiyat/bilgi istiyorsa ya da hiçbiri değilse action='yok' yaz. "
    "Emin değilsen ya da mesaj belirsizse action='yok' yaz, tahmin ederek ban/mute gibi ağır eylemler uydurma.\n"
    "sure_dakika: mute için istenen süre, sayı olarak dakika cinsinden (belirtilmemişse null).\n"
    "metin: hosgeldin_metin/kural_metin için ayarlanacak asıl metin, talimat için hatırlanacak kural "
    "(kullanıcının kendi cümlesiyle, kısaca) (yoksa null).\n"
    "ayar_adi: 'captcha', 'hosgeldin' veya 'ipucu' (sadece ayar eylemi için, yoksa null).\n"
    "ayar_ac: ayarın açılacağı true, kapatılacağı false (sadece ayar eylemi için, yoksa null).\n"
    'JSON şeması: {"action": "...", "sure_dakika": null, "metin": null, "ayar_adi": null, "ayar_ac": null}'
)

def niyet_coz(metin):
    try:
        r = groq.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "system", "content": NIYET_SISTEM},
                      {"role": "user", "content": metin}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=150,
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        log.warning(f"Niyet çözümleme hatası: {e}")
        return None

ARAMA_KELIME = {"araştır", "arastir", "haber", "haberi", "güncel", "guncel", "gündem", "gundem",
                "bugün", "bugun", "dün", "dun", "snapshot", "tge", "listelendi", "airdrop"}
ARAMA_IFADE = ("son dakika", "şu an", "ne oldu", "kim kazandı")

def arama_gerek(t):
    k = kucult(t)
    if any(i in k for i in ARAMA_IFADE):
        return True
    return bool(set(re.findall(r"\w+", k)) & ARAMA_KELIME)

def gemini_resim(veri):
    r = gem.models.generate_content(
        model="gemini-3.8-flash",
        contents=[types.Part.from_bytes(data=veri, mime_type="image/jpeg"),
                  "Bu görseldeki yazıları ve içeriği en fazla 3 kısa cümleyle Türkçe özetle. Emin olmadığın şeyi yazma."],
    )
    return (r.text or "").strip()

def sayi(x):
    if x is None:
        return "?"
    if x >= 1:
        return f"{x:,.2f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def sade(x):
    return f"{x:.8f}".rstrip("0").rstrip(".")

def fiyat_bul(sorgu, siki=False):
    q = sorgu.strip().lower()
    an = onbellek.get((q, siki))
    if an and time.time() - an[0] < 30:
        return an[1]
    veri = fiyat_ara(q, siki)
    onbellek[(q, siki)] = (time.time(), veri)
    return veri

def yahoo_fiyat(sembol):
    """Yahoo Finance'ten fiyat çeker (BTC-USD, ETH-USD, USDT-TRY vs.)."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sembol}"
        r = requests.get(url, params={"interval": "1d", "range": "2d"}, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"}).json()
        result = r.get("chart", {}).get("result")
        if not result:
            return None
        meta = result[0].get("meta", {})
        fiyat = meta.get("regularMarketPrice") or meta.get("previousClose")
        onceki = meta.get("chartPreviousClose") or meta.get("previousClose")
        if fiyat is None:
            return None
        deg = None
        if onceki and onceki > 0:
            deg = ((fiyat - onceki) / onceki) * 100
        return {"fiyat": float(fiyat), "deg": deg}
    except Exception as e:
        log.warning(f"Yahoo hatası ({sembol}): {e}")
        return None

def fiyat_ara(q, siki):
    q = q.lower().strip()

    yahoo_map = {
        "usdt": "USDT-TRY", "tether": "USDT-TRY",
        "dolar": "USDTRY=X", "usd": "USDTRY=X",
        "euro": "EURTRY=X", "eur": "EURTRY=X",
    }
    ysymbol = yahoo_map.get(q)
    if ysymbol:
        y = yahoo_fiyat(ysymbol)
        if y:
            ad_map = {"dolar": "Dolar (USD)", "usd": "Dolar (USD)", "euro": "Euro", "eur": "Euro",
                      "usdt": "USDT", "tether": "USDT"}
            guzel_ad = ad_map.get(q, q.upper())
            guzel_sembol = ad_map.get(q, q.upper())

            if "TRY" in ysymbol or ysymbol.endswith("=X"):
                return {"ad": guzel_ad, "sembol": guzel_sembol, "usd": None,
                        "try": y["fiyat"], "deg": y["deg"]}
            try_fiyat = None
            kur = yahoo_fiyat("USDTRY=X")
            if kur:
                try_fiyat = y["fiyat"] * kur["fiyat"]
            return {"ad": guzel_ad, "sembol": guzel_sembol, "usd": y["fiyat"],
                    "try": try_fiyat, "deg": y["deg"]}

    try:
        r = requests.get("https://api.coingecko.com/api/v3/search", params={"query": q}, timeout=10).json()
        coinler = r.get("coins", [])
        tam = [c for c in coinler if c["symbol"].lower() == q or c["name"].lower() == q]
        aday = tam if siki else (tam or coinler)
        if aday:
            sec = min(aday, key=lambda c: c.get("market_cap_rank") or 10**9)
            p = requests.get("https://api.coingecko.com/api/v3/simple/price",
                             params={"ids": sec["id"], "vs_currencies": "usd,try",
                                     "include_24hr_change": "true"}, timeout=10).json()
            d = p.get(sec["id"], {})
            if d.get("usd") is not None:
                return {"ad": sec["name"], "sembol": sec["symbol"].upper(), "usd": d.get("usd"),
                        "try": d.get("try"), "deg": d.get("usd_24h_change")}
    except Exception as e:
        log.warning(f"CoinGecko hatası: {e}")

    if siki:
        return None

    try:
        r = requests.get("https://api.dexscreener.com/latest/dex/search", params={"q": q}, timeout=10).json()
        pairs = [p for p in (r.get("pairs") or []) if p.get("priceUsd")
                 and p["baseToken"]["symbol"].lower() == q]
        if pairs:
            p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
            return {"ad": p["baseToken"]["name"], "sembol": p["baseToken"]["symbol"].upper(),
                    "usd": float(p["priceUsd"]), "try": None,
                    "deg": (p.get("priceChange") or {}).get("h24")}
    except Exception as e:
        log.warning(f"DexScreener hatası: {e}")
    return None

def token_cikar(metin):
    s = sor([{"role": "user", "content":
              "Bu mesajda fiyatı sorulan kripto para/token adı veya sembolü nedir? "
              "Sadece adını veya sembolünü yaz, başka hiçbir şey yazma. Yoksa sadece YOK yaz.\nMesaj: " + metin}])
    if not s:
        return None
    s = s.strip().splitlines()[0].strip(" .\"'$")
    if not s or len(s) > 25 or "YOK" in s.upper():
        return None
    return s

KISA_FIYAT = re.compile(r"^\s*(?:(\d+(?:[.,]\d+)?)\s*\$?\s+)?([a-zA-Z][a-zA-Z0-9]{1,12})\s*$")
SAYI_KELIME = {"tl", "try", "gb", "mb", "kg", "tane", "adet", "saat", "gun", "dk", "sn", "lira"}

def kisa_token(metin):
    m = KISA_FIYAT.match(metin.strip())
    if m:
        miktar_text = m.group(1)
        token = m.group(2)
        if not token:
            return None
        if token.lower() in SAYI_KELIME:
            return None
        if len(token) < 2:
            return None
        try:
            mk = float(miktar_text.replace(",", ".")) if miktar_text else 1.0
        except Exception:
            return None
        if mk <= 0 or mk > 1e12:
            return None
        return mk, token
    t = kucult(metin).strip()
    if 2 <= len(t) <= 12 and t.isalpha():
        if t in SAYI_KELIME:
            return None
        return 1.0, t
    return None

async def fiyat_gonder(update, ctx, sorgu, miktar=1.0, siki=False):
    msg = update.effective_message
    veri = await asyncio.to_thread(fiyat_bul, sorgu, siki)
    if not veri:
        return False

    baslik = f"⚠️ {sade(miktar)} {veri['sembol']}:"
    if veri.get("try"):
        fiyat_satir = f"✅ ₺{sayi(veri['try'] * miktar)}"
    elif veri.get("usd"):
        fiyat_satir = f"✅ ${sayi(veri['usd'] * miktar)}"
    else:
        return False

    deg_text = ""
    if veri.get("deg") is not None:
        yon = "yükseldi" if veri["deg"] >= 0 else "düştü"
        deg_text = f"%{abs(veri['deg']):.2f} {yon}"

    espri = await asyncio.to_thread(sor, [{"role": "user", "content":
        f"{veri['ad']} ({veri['sembol']}) fiyatı şu an "
        f"{'₺' + sayi(veri['try']) if veri.get('try') else '$' + sayi(veri.get('usd'))}, "
        f"24 saatte %{veri['deg'] or 0:+.2f} değişti. "
        f"Buna çok kısa, esprili ve samimi bir cümle yaz. Yatırım tavsiyesi verme."}])
    satirlar = [baslik, fiyat_satir]
    if deg_text or espri:
        ek = "➖ "
        if deg_text:
            ek += deg_text + " "
        if espri:
            ek += espri.strip()
        satirlar.append(ek.strip())

    await msg.reply_text("\n".join(satirlar))
    return True

def sahip_mi(user):
    return bool(user) and durum.get("sahip") == user.id

async def sahip_yakala(update, ctx):
    u = update.effective_user
    if u and u.username and u.username.lower() == SAHIP_KULLANICI and durum.get("sahip") != u.id:
        durum["sahip"] = u.id
        durum_kaydet()
        log.info(f"Sahip tanındı: {u.id}")

async def yonetici_mi(ctx, chat_id, user_id):
    try:
        uye = await ctx.bot.get_chat_member(chat_id, user_id)
        return uye.status in ("administrator", "creator")
    except Exception:
        return False

async def yetkili_mi(ctx, chat_id, user_id):
    if durum.get("sahip"):
        if user_id == durum["sahip"]:
            return True
        return bool(cget(chat_id, "adminizin")) and await yonetici_mi(ctx, chat_id, user_id)
    return await yonetici_mi(ctx, chat_id, user_id)

async def muaf_mi(ctx, chat_id, user_id):
    if durum.get("sahip") and user_id == durum["sahip"]:
        return True
    return await yonetici_mi(ctx, chat_id, user_id)

async def mesaj_sil_sn(ctx, chat_id, message_id, sn=10):
    """Mesajı N saniye sonra sil (komut gizleme)."""
    await asyncio.sleep(sn)
    try:
        await ctx.bot.delete_message(chat_id, message_id)
    except Exception:
        pass

def komut_silici(fonk):
    """Slash komut mesajını 5 sn sonra siler."""
    async def sar(update, ctx):
        await fonk(update, ctx)
        msg = update.effective_message
        chat = update.effective_chat
        if msg and chat and chat.type != "private":
            task = asyncio.create_task(mesaj_sil_sn(ctx, chat.id, msg.message_id, 5))
            gorevler.add(task)
            task.add_done_callback(gorevler.discard)
    return sar

def mesaj_linki(chat, mid):
    """Sohbet mesajına derin link."""
    if not mid:
        return None
    try:
        mid = int(mid)
    except Exception:
        return None
    uname = getattr(chat, "username", None)
    if uname:
        return f"https://t.me/{uname}/{mid}"
    s = str(getattr(chat, "id", "") or "")
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{mid}"
    if s.lstrip("-").isdigit():
        return f"https://t.me/c/{s.lstrip('-')}/{mid}"
    return None

def kanal_post_linki(msg):
    """Kanal / otomatik iletim mesajından orijinal kanal post linki.
    Örn: https://t.me/YeniBirAirdrops/123
    """
    if not msg:
        return None
    # 1) forward_origin (yeni API)
    fo = getattr(msg, "forward_origin", None)
    if fo is not None:
        ch = getattr(fo, "chat", None)
        mid = getattr(fo, "message_id", None)
        if ch is not None and mid:
            un = getattr(ch, "username", None)
            if un:
                return f"https://t.me/{un}/{int(mid)}"
            cid = str(getattr(ch, "id", "") or "")
            if cid.startswith("-100"):
                return f"https://t.me/c/{cid[4:]}/{int(mid)}"
    # 2) klasik forward_from_chat + forward_from_message_id
    fch = getattr(msg, "forward_from_chat", None)
    fmid = getattr(msg, "forward_from_message_id", None)
    if fch is not None and fmid:
        un = getattr(fch, "username", None)
        if un:
            return f"https://t.me/{un}/{int(fmid)}"
        cid = str(getattr(fch, "id", "") or "")
        if cid.startswith("-100"):
            return f"https://t.me/c/{cid[4:]}/{int(fmid)}"
    # 3) sender_chat = kanal (tartışma grubunda kanal kimliğiyle post)
    sc = getattr(msg, "sender_chat", None)
    if sc is not None and getattr(sc, "type", "") == "channel":
        mid = getattr(msg, "forward_from_message_id", None) or getattr(msg, "message_id", None)
        un = getattr(sc, "username", None)
        if un and mid:
            return f"https://t.me/{un}/{int(mid)}"
        cid = str(getattr(sc, "id", "") or "")
        if cid.startswith("-100") and mid:
            return f"https://t.me/c/{cid[4:]}/{int(mid)}"
    return None

async def resim_oku(ctx, cid, m):
    anahtar = (cid, m.message_id)
    if anahtar in vision_onbellek:
        return vision_onbellek[anahtar]
    s = ""
    try:
        dosya = await ctx.bot.get_file(m.photo[-1].file_id)
        veri = bytes(await dosya.download_as_bytearray())
        s = await asyncio.to_thread(gemini_resim, veri)
    except Exception as e:
        log.warning(f"Görsel okunamadı: {e}")
    vision_onbellek[anahtar] = s
    return s

async def mesaj_ozeti(ctx, m, chat):
    mid = getattr(m, "message_id", None)
    if not mid:
        return None
    metin = (getattr(m, "text", None) or getattr(m, "caption", None) or "").strip()
    if not metin and getattr(m, "photo", None):
        metin = await resim_oku(ctx, chat.id, m)
    tarih = time.time()
    d = getattr(m, "date", None)
    if d and d.year > 2000:
        tarih = d.timestamp()
    # Önce kanal post linki (YeniBirAirdrops), yoksa grup mesajı
    link = kanal_post_linki(m) or mesaj_linki(chat, mid)
    return {"id": mid, "metin": metin[:1500], "link": link, "tarih": tarih}

async def sabit_al(ctx, chat, taze=False):
    an = sabit_onbellek.get(chat.id)
    if an and not taze and time.time() - an[0] < 60:
        return an[1]
    kayit = None
    try:
        c = await ctx.bot.get_chat(chat.id)
        if c.pinned_message:
            kayit = await mesaj_ozeti(ctx, c.pinned_message, c)
    except Exception as e:
        log.warning(f"Sabit mesaj alınamadı: {e}")
    sabit_onbellek[chat.id] = (time.time(), kayit)
    if kayit:
        durum["sabit"].setdefault(str(chat.id), {})["son"] = kayit
        durum_kaydet()
    return kayit

async def sabit_cevap(update, ctx):
    msg = update.effective_message
    kayit = await sabit_al(ctx, update.effective_chat)
    if not kayit:
        await msg.reply_text("Şu an sabitlenmiş mesaj görünmüyor.")
        return
    ozet = None
    if kayit["metin"]:
        ozet = await asyncio.to_thread(sor, [{"role": "user", "content":
            "Aşağıdaki sabitlenmiş grup mesajını en fazla 2 kısa cümleyle Türkçe özetle, linkleri yazma:\n" + kayit["metin"]}])
    parca = ["📌 " + (ozet.strip() if ozet else "Sabit mesajın içeriğini okuyamadım, linkten bak.")]
    if kayit.get("link"):
        parca.append(kayit["link"])
    await msg.reply_text("\n".join(parca))

def arsiv_baslik_uret(metin, link=None):
    """Metinden kısa başlık; zayıfsa AI ile üret."""
    ham = (metin or "").strip()
    # URL ve fazla boşluk temizle
    temiz_satirlar = []
    for s in ham.splitlines():
        s = re.sub(r"https?://\S+", "", s).strip()
        s = re.sub(r"[@#]\w+", "", s).strip()
        if s and len(s) > 2:
            temiz_satirlar.append(s)
    if temiz_satirlar:
        bas = temiz_satirlar[0]
        return bas[:42] + ("…" if len(bas) > 42 else "")
    # Linkten token/bot adı çıkar
    if link:
        m = re.search(r"t\.me/([A-Za-z0-9_]+)", link)
        if m and m.group(1).lower() not in ("yenibirairdrops", "c"):
            return m.group(1)[:40]
    # AI kısa başlık
    if ham or link:
        try:
            ai = sor([{"role": "user", "content":
                "Bu airdrop/duyuru için en fazla 6 kelimelik Türkçe başlık yaz. "
                "Sadece başlık, tırnak yok, emoji yok:\n" + (ham or link or "")[:500]}])
            if ai:
                b = " ".join(ai.strip().split())[:42]
                if b and "yoğun" not in b.lower():
                    return b
        except Exception:
            pass
    return "Duyuru"

def arsiv_ekle(cid, kayit):
    liste = durum["arsiv"].setdefault(str(cid), [])
    baslik = kayit.get("baslik") or arsiv_baslik_uret(kayit.get("metin", ""), kayit.get("link"))
    for x in liste:
        if x["id"] == kayit["id"]:
            x["tarih"] = kayit["tarih"]
            x["metin"] = kayit.get("metin", "")
            x["link"] = kayit.get("link")
            x["baslik"] = baslik
            durum_kaydet()
            return
    liste.append({
        "id": kayit["id"],
        "metin": kayit.get("metin", ""),
        "link": kayit.get("link"),
        "baslik": baslik,
        "tarih": kayit["tarih"],
    })
    sinir = time.time() - 45 * 86400
    durum["arsiv"][str(cid)] = [x for x in liste if x["tarih"] >= sinir][-200:]
    durum_kaydet()

def arsiv_liste(cid, gun):
    liste = durum["arsiv"].get(str(cid), [])
    if gun == 1:
        bugun = datetime.now(TR).date()
        return [x for x in liste if datetime.fromtimestamp(x["tarih"], TR).date() == bugun]
    sinir = time.time() - gun * 86400
    return [x for x in liste if x["tarih"] >= sinir]

def arsiv_baslik(k):
    if k.get("baslik") and k["baslik"] != "Duyuru":
        return k["baslik"][:45]
    for s in (k.get("metin") or "").splitlines():
        s = re.sub(r"https?://\S+", "", s).strip()
        if s and len(s) > 2:
            return s[:45] + ("…" if len(s) > 45 else "")
    # Eski kayit: bir kez baslik üret ve sakla
    b = arsiv_baslik_uret(k.get("metin", ""), k.get("link"))
    k["baslik"] = b
    return b[:45]

def liste_gun(kw):
    if any(k in ("aylık", "aylik") for k in kw):
        return 30, "Aylık"
    if any(k in ("haftalık", "haftalik") for k in kw):
        return 7, "Haftalık"
    return 1, "Bugünkü"

async def arsiv_gonder(update, ctx, gun, baslik):
    """Butona tıkla → gruptaki orijinal airdrop/duyuru mesajına git."""
    msg = update.effective_message
    chat = update.effective_chat
    kayitlar = arsiv_liste(chat.id, gun)
    if not kayitlar:
        await msg.reply_text(f"{baslik} duyuru yok.")
        return
    satirlar = [f"📢 {baslik} Duyurular", ""]
    dugmeler = []
    for i, k in enumerate(kayitlar[:10], 1):
        ad = arsiv_baslik(k)
        link = k.get("link")
        # Eski kayıtlarda sadece grup linki olabilir; id ile grup yedegi
        if not link:
            link = mesaj_linki(chat, k.get("id"))
        if link:
            dugmeler.append([InlineKeyboardButton(f"{NUMARALAR[i - 1]} {ad}", url=link)])
            satirlar.append(f"{NUMARALAR[i - 1]} {ad}")
        else:
            satirlar.append(f"{NUMARALAR[i - 1]} {ad}")
    satirlar.append("")
    satirlar.append("Numaraya bas → kanal duyurusuna gider.")
    await msg.reply_text(
        "\n".join(satirlar),
        reply_markup=InlineKeyboardMarkup(dugmeler) if dugmeler else None,
        disable_web_page_preview=True,
    )

async def liste_komut(update, ctx):
    chat = update.effective_chat
    msg = update.effective_message
    if chat.type == "private" or not msg or not msg.text:
        return
    ad = msg.text.split()[0][1:].split("@")[0].lower()
    gun, baslik = {"gunluk": (1, "Bugünkü"), "haftalik": (7, "Haftalık"), "aylik": (30, "Aylık"),
                   "duyurular": (1, "Bugünkü")}.get(ad, (1, "Bugünkü"))
    await arsiv_gonder(update, ctx, gun, baslik)

async def sabitlendi(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    # "X bir mesajı sabitledi" servis mesajını sil
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass
    pm = getattr(msg, "pinned_message", None) if msg else None
    if not pm:
        return
    kayit = await mesaj_ozeti(ctx, pm, chat)
    if not kayit:
        return
    durum["sabit"].setdefault(str(chat.id), {})["son"] = kayit
    yeni = dict(kayit)
    yeni["tarih"] = time.time()
    arsiv_ekle(chat.id, yeni)
    sabit_onbellek.pop(chat.id, None)
    durum_kaydet()

async def sahip_komut(update, ctx):
    chat = update.effective_chat
    msg = update.effective_message
    user = update.effective_user
    if chat.type != "private":
        return
    if durum.get("sahip"):
        await msg.reply_text("Sahip zaten kayıtlı." if user.id == durum["sahip"] else "Yetkin yok.")
        return
    if ctx.args and ctx.args[0].upper() == SAHIP_KOD:
        durum["sahip"] = user.id
        durum_kaydet()
        await msg.reply_text("✅ Sahip sensin. Tüm yönetim komutları artık sadece sende.")
    else:
        await msg.reply_text("Kod yanlış.")

async def ayar_komut(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private" or not await yetkili_mi(ctx, chat.id, update.effective_user.id):
        return
    komut_adi = msg.text.split()[0][1:].split("@")[0].lower()
    ad, _, deger = komut_adi.partition("_")
    if ad not in ("ai", "ipucu", "hosgeldin", "captcha", "adminizin"):
        return
    ozel = chat.type == "private"
    grup_ayari_uygula(chat.id, ad, deger == "ac", ozel)
    yer = "tüm gruplarda" if ozel else "bu grupta"
    await msg.reply_text(f"{ad.upper()} {yer} {'açıldı' if deger == 'ac' else 'kapatıldı'}.")

async def durum_komut(update, ctx):
    if update.effective_chat.type != "private" or update.effective_user.id != durum.get("sahip"):
        return
    satirlar = []
    for cid in uyeler:
        if int(cid) < 0:
            try:
                baslik = (await ctx.bot.get_chat(int(cid))).title
            except Exception:
                baslik = cid
            ai = "açık" if cget(cid, "ai") else "kapalı"
            ip = "açık" if cget(cid, "ipucu") else "kapalı"
            satirlar.append(f"• {baslik}\n  AI: {ai} | İpucu: {ip} | Duyuru arşivi: {len(durum['arsiv'].get(cid, []))}")
    await update.effective_message.reply_text("\n".join(satirlar) or "Henüz grup yok.")

async def duyuru_komut(update, ctx):
    msg = update.effective_message
    if update.effective_chat.type != "private" or update.effective_user.id != durum.get("sahip"):
        return
    parcalar = msg.text.split(None, 1)
    if len(parcalar) < 2:
        await msg.reply_text("Örnek: /duyuru metin")
        return
    sayac = 0
    for cid in list(uyeler.keys()):
        if int(cid) < 0:
            try:
                await ctx.bot.send_message(int(cid), parcalar[1])
                sayac += 1
            except Exception as e:
                log.warning(f"Duyuru gönderilemedi ({cid}): {e}")
    await msg.reply_text(f"{sayac} gruba gönderildi.")

def ipucu_uret():
    eskiler = " | ".join(durum["liste"][-8:])
    ham = sor([{"role": "user", "content":
        "Kripto/airdrop grubu için TEK satır ipucu yaz. "
        "Format: 💡 kısa cümle. "
        "Kurallar: sadece 1 adet 💡 kullan, en fazla 120 karakter, tek cümle, nokta ile bitir. "
        "Yatırım tavsiyesi yok. Şunları tekrar etme: " + eskiler}])
    if not ham:
        return None
    s = " ".join(ham.strip().split())
    # Fazla ampulleri temizle
    while s.count("💡") > 1:
        s = s.replace("💡", "", 1)
    if not s.startswith("💡"):
        s = "💡 " + s.lstrip("💡 ").strip()
    # Uzunsa kısalt
    if len(s) > 140:
        s = s[:137].rsplit(" ", 1)[0] + "..."
    return s

async def ipucu_gonder(app):
    s = await asyncio.to_thread(ipucu_uret)
    if not s:
        return
    durum["liste"] = (durum["liste"] + [s])[-20:]
    durum["son"] = time.time()
    durum_kaydet()
    for cid in list(uyeler.keys()):
        if int(cid) < 0 and cget(cid, "ipucu"):
            try:
                await app.bot.send_message(int(cid), s)
            except Exception as e:
                log.warning(f"İpucu gönderilemedi ({cid}): {e}")

async def ipucu_dongusu(app):
    while True:
        await asyncio.sleep(300)
        try:
            saat = datetime.now(TR).hour
            if 8 <= saat < 24 and time.time() - durum["son"] > TIP_ARALIK:
                await ipucu_gonder(app)
        except Exception as e:
            log.warning(f"İpucu döngüsü hatası: {e}")

async def duyuru_saatlik(app):
    """Günün arşivindeki duyuruları belirli aralıkla (varsayılan 3 saat) gruba tekrar atar."""
    while True:
        await asyncio.sleep(120)
        try:
            son = durum.get("duyuru_saat", 0)
            # En kısa aralık 3 saat (10800 sn); grup ayarı duyuru_aralik_saat ile değiştirilebilir
            aralik = 3
            try:
                # Tüm gruplar için ortak döngü; aralık min 3 saat
                aralik = max(3, int(aralik))
            except Exception:
                aralik = 3
            if time.time() - son < aralik * 3600 - 60:
                continue
            durum["duyuru_saat"] = time.time()
            durum_kaydet()
            for cid in list(uyeler.keys()):
                if int(cid) < 0:
                    try:
                        kayitlar = arsiv_liste(int(cid), 1)
                        if not kayitlar:
                            continue
                        satirlar = ["📢 Bugünkü Duyurular"]
                        dugmeler = []
                        for i, k in enumerate(kayitlar[:10], 1):
                            ad = arsiv_baslik(k)
                            if k.get("link"):
                                dugmeler.append([InlineKeyboardButton(f"{NUMARALAR[i-1]} {ad}", url=k["link"])])
                            else:
                                satirlar.append(f"{NUMARALAR[i-1]} {ad}")
                        await app.bot.send_message(
                            int(cid),
                            "\n".join(satirlar),
                            reply_markup=InlineKeyboardMarkup(dugmeler) if dugmeler else None
                        )
                    except Exception as e:
                        log.warning(f"Saatlik duyuru hatası ({cid}): {e}")
        except Exception as e:
            log.warning(f"Duyuru döngüsü hatası: {e}")

async def baslat(app):
    # Link kilidi açık: sadece YeniBirAirdrops kanalından gelenler serbest
    try:
        for gcid, ay in list(durum.get("ayar", {}).items()):
            if not isinstance(ay, dict):
                continue
            k = list(ay.get("kilit") or [])
            if "link" not in k:
                k.append("link")
                ay["kilit"] = k
        durum["ayar"].setdefault(GLOBAL_AYAR, {})["kilit"] = list(
            set(durum["ayar"].get(GLOBAL_AYAR, {}).get("kilit") or []) | {"link"}
        )
        durum_kaydet()
        log.info("Link kilidi aktif — sadece YeniBirAirdrops kanal paylaşımları serbest")
    except Exception as e:
        log.warning(f"Kilit ayarı: {e}")
    app.bot_data["ipucu"] = asyncio.create_task(ipucu_dongusu(app))
    app.bot_data["duyuru"] = asyncio.create_task(duyuru_saatlik(app))
    app.bot_data["schedule"] = asyncio.create_task(schedule_dongusu(app))
    try:
        await app.bot.set_my_commands([
            BotCommand("yardim", "Komut listesi"), BotCommand("kurallar", "Grup kuralları"),
            BotCommand("gunluk", "Bugünkü duyurular"), BotCommand("haftalik", "Haftalık duyurular"),
            BotCommand("aylik", "Aylık duyurular"), BotCommand("fiyat", "Token fiyatı"),
            BotCommand("top", "En aktif üyeler"), BotCommand("rapor", "Yöneticilere bildir")])
    except Exception as e:
        log.warning(f"Komut menüsü kurulamadı: {e}")

async def ipucu_komut(update, ctx):
    chat = update.effective_chat
    if chat.type != "private" and not await yetkili_mi(ctx, chat.id, update.effective_user.id):
        return
    s = await asyncio.to_thread(ipucu_uret)
    if s:
        s = s.strip()
        durum["liste"] = (durum["liste"] + [s])[-20:]
        durum_kaydet()
        await update.effective_message.reply_text(s)

KUFUR_TAM = {"amk", "aq", "amq", "orospu", "piç", "sik", "sikik", "yarak", "yarrak", "göt", "götveren",
             "gavat", "pezevenk", "ibne", "puşt", "salak", "aptal", "gerizekalı", "şerefsiz", "serefsiz"}
KUFUR_KOK = ("siktir", "sikeyim", "sikerim", "orospu", "yarrak", "amına", "amina", "ananı", "anani",
             "pezevenk", "şerefsiz", "gerizekalı")

LINK_RE = re.compile(r"(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+|\b[a-z0-9-]+\.(?:com|io|xyz|net|org|me|app|co|link|fun|ai|gg|site|online|top|click)\b\S*)")
IZINLI = (
    "coingecko.com", "coinmarketcap.com", "dexscreener.com", "tradingview.com",
    "t.me/yenibirairdrops", "telegram.me/yenibirairdrops", "yenibirairdrops",
)
SCAM_IFADE = ("seed phrase", "private key", "gizli anahtar", "özel anahtar", "12 kelime", "24 kelime",
              "kurtarma ifadesi", "recovery phrase", "cüzdanını bağla", "connect your wallet")
KILIT_TURLERI = ("link", "sticker", "gif", "foto", "video", "ses", "dosya", "iletilen")

def kufur_var(t):
    for k in re.findall(r"\w+", kucult(t)):
        if k in KUFUR_TAM or k.startswith(KUFUR_KOK):
            return True
    return False

def kara_var(cid, kelimeler):
    kl = durum["kara"].get(str(cid), [])
    return any(k in kelimeler for k in kl)

def scam_var(t):
    k = kucult(t)
    return any(i in k for i in SCAM_IFADE)

def link_var(msg, metin):
    adaylar = LINK_RE.findall(kucult(metin))
    for e in (msg.entities or msg.caption_entities or []):
        try:
            if e.type == "text_link" and e.url:
                adaylar.append(e.url.lower())
            elif e.type == "url":
                parca = msg.parse_entity(e) if msg.text else msg.parse_caption_entity(e)
                adaylar.append(parca.lower())
        except Exception:
            pass
    temiz = []
    for a in adaylar:
        a2 = a.lower().replace("https://", "").replace("http://", "")
        if any(d in a2 for d in IZINLI):
            continue
        # t.me/YeniBirAirdrops veya t.me/c/... kanal postları serbest
        if a2.startswith("t.me/yenibirairdrops") or "t.me/yenibirairdrops/" in a2:
            continue
        temiz.append(a)
    return len(temiz) > 0

def spam_mi(chat_id, user_id, n):
    dq = zamanlar.get((chat_id, user_id))
    if dq is None or dq.maxlen != n:
        dq = zamanlar[(chat_id, user_id)] = deque(maxlen=n)
    now = time.time()
    dq.append(now)
    return len(dq) == n and now - dq[0] < 10

def mesaj_turleri(msg):
    t = []
    if msg.sticker:
        t.append("sticker")
    if msg.animation:
        t.append("gif")
    if msg.photo:
        t.append("foto")
    if msg.video:
        t.append("video")
    if msg.voice or msg.audio:
        t.append("ses")
    if msg.document and not msg.animation:
        t.append("dosya")
    if getattr(msg, "forward_origin", None):
        t.append("iletilen")
    return t

async def sustur(ctx, chat_id, user_id, dakika=None):
    kw = {}
    if dakika:
        kw["until_date"] = datetime.now(timezone.utc) + timedelta(minutes=dakika)
    await ctx.bot.restrict_chat_member(chat_id, user_id,
                                       permissions=ChatPermissions(can_send_messages=False), **kw)

async def sesi_ac(ctx, chat_id, user_id):
    varsayilan = (await ctx.bot.get_chat(chat_id)).permissions
    await ctx.bot.restrict_chat_member(chat_id, user_id,
                                       permissions=varsayilan or ChatPermissions(can_send_messages=True))

async def ihlal(update, ctx, ad, sil):
    msg = update.effective_message
    user = update.effective_user
    cid = update.effective_chat.id
    anahtar = (cid, user.id)
    uyari[anahtar] = uyari.get(anahtar, 0) + 1
    # İhlal mesajını her zaman silmeye çalış (link/küfür/kara)
    if sil and msg:
        try:
            await msg.delete()
        except Exception as e:
            log.warning(f"İhlal mesajı silinemedi: {e}")
    if uyari[anahtar] == 1:
        uy = await ctx.bot.send_message(
            cid,
            f"{user.mention_html()} {ad} yasak, bu ilk uyarın. Tekrarında 5 dk susturulursun.",
            parse_mode="HTML",
        )
    else:
        uyari[anahtar] = 0
        try:
            await sustur(ctx, cid, user.id, 5)
            uy = await ctx.bot.send_message(
                cid,
                f"{user.mention_html()} uyarıya rağmen tekrar ettiğin için 5 dk susturuldun ({ad}).",
                parse_mode="HTML",
            )
        except Exception as e:
            log.warning(f"Susturma hatası: {e}")
            uy = await ctx.bot.send_message(
                cid, "Susturamadım, yetkim yok. Beni yönetici yapıp üyeleri kısıtlama yetkisi ver."
            )
    # Uyarı mesajını 15 sn sonra sil
    try:
        t = asyncio.create_task(mesaj_sil_sn(ctx, cid, uy.message_id, 15))
        gorevler.add(t)
        t.add_done_callback(gorevler.discard)
    except Exception:
        pass
    zamanlar.pop(anahtar, None)

def kw_var(kw, *kokler):
    return any(k.startswith(kokler) for k in kw)

def sure_bul(t):
    t = re.sub(r"@\w+", "", t)
    m = re.search(r"(\d+)\s*(dakika|dk|saat|sa|gün|gun|g|h|m)?\b", t)
    if not m:
        return None
    carp = {"dakika": 1, "dk": 1, "m": 1, "saat": 60, "sa": 60, "h": 60, "gün": 1440, "gun": 1440, "g": 1440}[m.group(2) or "dk"]
    return max(1, min(int(m.group(1)) * carp, 525600))

def hedef_coz(msg, cid, t):
    """Hedef kullanıcı: yanıt > @username > isim eşleşmesi."""
    r = msg.reply_to_message
    if r and r.from_user and not r.from_user.is_bot:
        return r.from_user.id, r.from_user.full_name

    # @username
    m = re.search(r"@(\w{4,})", t)
    if m:
        uname = m.group(1).lower()
        for uid, u in uyeler.get(str(cid), {}).items():
            if (u.get("kullanici") or "").lower() == uname:
                return int(uid), u["ad"]

    # Süre kalıplarını metinden çıkar: "2 dk", "10 dakika", "1 saat" vb.
    t_temiz = re.sub(
        r"\b\d+\s*(?:dk|dakika|saat|sn|saniye|min|m|h|d)\b",
        " ",
        t,
        flags=re.I,
    )
    # Başta/sonda tek başına kalan süre sayısı da atılsın (sadece isim kalır)
    atilacak = {
        "yapay", "sustur", "susturulsun", "mute", "ban", "banla", "kick", "at", "uçur", "ucur",
        "warn", "uyar", "uyarı", "uyari", "unmute", "aç", "ac", "kaldır", "kaldir",
        "dk", "dakika", "saat", "sn", "saniye", "m", "h", "d", "min",
        "et", "yapsana", "olarak", "şu", "su", "bu", "şunu", "sunu", "bunu", "kişiyi", "kisiyi",
        "gruptan", "gruba", "kullanici", "kullanıcı",
    }
    kelimeler = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", t_temiz)
    aday_parcalar = []
    for k in kelimeler:
        kl = kucult(k)
        if kl in atilacak:
            continue
        aday_parcalar.append(k)

    if not aday_parcalar:
        return None, None

    # Birden fazla aday dene: tam metin + son 1-3 kelime (isim genelde sonda)
    adaylar = []
    adaylar.append(" ".join(aday_parcalar))
    for n in (1, 2, 3):
        if len(aday_parcalar) >= n:
            adaylar.append(" ".join(aday_parcalar[-n:]))
            adaylar.append(" ".join(aday_parcalar[:n]))
    # Tekrarları temizle
    gorulen = set()
    aday_listesi = []
    for a in adaylar:
        ak = kucult(a).strip()
        if len(ak) >= 2 and ak not in gorulen:
            gorulen.add(ak)
            aday_listesi.append(ak)

    en_iyi = None  # (skor, uid, ad)
    grup_uyeleri = uyeler.get(str(cid), {})
    for aday_k in aday_listesi:
        for uid, u in grup_uyeleri.items():
            ad = u.get("ad") or ""
            ad_k = kucult(ad)
            kullanici = (u.get("kullanici") or "").lower()
            skor = 0
            if ad_k == aday_k:
                skor = 100
            elif aday_k in ad_k or ad_k in aday_k:
                skor = 80
            elif kullanici and (
                kullanici == aday_k.replace(" ", "")
                or aday_k.replace(" ", "") == kullanici
                or aday_k.replace(" ", "") in kullanici
            ):
                skor = 70
            else:
                ad_kel = set(re.findall(r"[\wçğıöşü]+", ad_k))
                aday_kel = set(re.findall(r"[\wçğıöşü]+", aday_k))
                ortak = ad_kel & aday_kel
                if ortak:
                    skor = 40 + 15 * len(ortak)
            if skor > 0 and (en_iyi is None or skor > en_iyi[0]):
                en_iyi = (skor, int(uid), ad)

    if en_iyi and en_iyi[0] >= 40:
        return en_iyi[1], en_iyi[2]
    return None, None

async def komut(update, ctx, metin):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    cid = chat.id
    ozel = chat.type == "private"
    t = kucult(metin)
    kw = re.findall(r"\w+", t)
    r = msg.reply_to_message
    yapay = "yapay" in t
    bota = bool(r and r.from_user and r.from_user.id == ctx.bot.id)
    adresli = yapay or bota or ozel
    kalici = any(x in t for x in ("bundan sonra", "bundan böyle", "bundan boyle", "unutma", "aklında tut", "aklinda tut"))
    fiil = any(k in ("yap", "yapsana", "ayarla", "yaz", "değiştir", "degistir", "güncelle", "guncelle", "kaydet") for k in kw)
    kapat = kw_var(kw, "kapat", "kapa", "kapalı", "kapali", "devre")
    ac = any(k in ("aç", "ac", "açık", "acik", "aktif") for k in kw)

    eylem = None
    niyet_metin = None
    niyet_ayar = None
    niyet_ac = None
    niyet_sure = None

    if adresli:
        niyet = await asyncio.to_thread(niyet_coz, metin)
        if niyet:
            a = (niyet.get("action") or "yok")
            a = str(a).strip().lower()
            gecerli = ("ban", "unban", "kick", "mute", "unmute", "warn", "sil", "pin", "unpin", "duy",
                       "talimat", "talimat_sil", "talimat_liste", "ayar", "hosgeldin_metin", "kural_metin")
            if a in gecerli:
                if a == "talimat" and not sahip_mi(user):
                    a = None
                if a:
                    eylem = a
                    niyet_sure = niyet.get("sure_dakika")
                    niyet_metin = niyet.get("metin")
                    niyet_ayar = niyet.get("ayar_adi")
                    niyet_ac = niyet.get("ayar_ac")

    if not eylem:
        if adresli and kalici and sahip_mi(user):
            eylem = "talimat"
        elif adresli and kw_var(kw, "talimat"):
            eylem = "talimat_sil" if kw_var(kw, "sil", "sıfırla", "sifirla", "temizle") else "talimat_liste"
        elif yapay and ":" in metin and kw_var(kw, "hoşgeldin", "hosgeldin") and fiil:
            eylem = "hosgeldin_metin"
        elif yapay and ":" in metin and kw_var(kw, "kural") and fiil:
            eylem = "kural_metin"
        elif yapay and kw_var(kw, "captcha", "hoşgeldin", "hosgeldin", "ipucu") and (kapat or ac):
            eylem = "ayar"
        else:
            unban = "unban" in kw or (kw_var(kw, "banı", "bani") and (kw_var(kw, "kald") or "aç" in kw or "ac" in kw))
            unmute = ("unmute" in kw or (kw_var(kw, "ses") and ("aç" in kw or "ac" in kw))
                      or (kw_var(kw, "susturmay") and kw_var(kw, "kald")) or "konuşabilir" in kw or "konusabilir" in kw)
            if unban:
                eylem = "unban"
            elif kw_var(kw, "banla", "yasakla") or "ban" in kw or any(k in ("kov", "kovsana", "kovun") for k in kw):
                eylem = "ban"
            elif "kick" in kw or ("at" in kw and yapay) or ("gruptan" in kw and any(k in ("at", "çıkar", "cikar") for k in kw)):
                eylem = "kick"
            elif unmute:
                eylem = "unmute"
            elif kw_var(kw, "sustur"):
                eylem = "mute"
            elif any(k in ("uyar", "uyarsana", "uyarın", "uyarin") for k in kw) or (("uyarı" in kw or "uyari" in kw) and "ver" in kw):
                eylem = "warn"
            elif any(k in ("sil", "silsene", "silin", "siler", "sildir") for k in kw):
                eylem = "sil"
            elif kw_var(kw, "sabit", "pin") and kw_var(kw, "kald", "çöz", "coz"):
                eylem = "unpin"
            elif kw_var(kw, "sabitle", "pinle") or ("sabit" in kw and any(k in ("yap", "yapsana", "et", "olarak") for k in kw)):
                eylem = "pin"
            elif kw_var(kw, "duyuru") and any(k in ("yap", "yapsana", "et", "ekle", "kaydet", "olarak") for k in kw):
                eylem = "duy"

    if not eylem:
        return False
    # Özelden: talimat, ayar, gruba mesaj serbest; ban/mute gibi işlemler grupta yapılır
    if ozel and not (eylem.startswith("talimat") or eylem in ("ayar", "hosgeldin_metin", "kural_metin", "gruba_gonder")):
        return False
    kisa = len(kw) <= 4
    if eylem not in ("talimat", "talimat_sil", "talimat_liste", "hosgeldin_metin", "kural_metin", "ayar", "gruba_gonder") \
            and not (adresli or kisa):
        return False
    if not await yetkili_mi(ctx, cid, user.id):
        if adresli:
            await msg.reply_text("Bunu sadece sahibim yapabilir 😄")
            return True
        return False

    async def de(s, html_mod=False):
        m = await msg.reply_text(s, parse_mode=("HTML" if html_mod else None))
        try:
            t = asyncio.create_task(mesaj_sil_sn(ctx, cid, m.message_id, 10))
            gorevler.add(t)
            t.add_done_callback(gorevler.discard)
        except Exception:
            pass

    async def bitir():
        try:
            t = asyncio.create_task(mesaj_sil_sn(ctx, cid, msg.message_id, 10))
            gorevler.add(t)
            t.add_done_callback(gorevler.discard)
        except Exception:
            pass

    if eylem == "talimat":
        s = niyet_metin or re.sub(r"(?i)yapay", "", metin).strip(" ,:.")
        durum["talimat"] = (durum["talimat"] + [{"t": s[:300]}])[-20:]
        durum_kaydet()
        await de("Tamam, aklımda 👍")
        return True
    if eylem == "talimat_sil":
        durum["talimat"] = []
        durum_kaydet()
        await de("Talimatların hepsi silindi.")
        return True
    if eylem == "talimat_liste":
        tl = durum["talimat"]
        await de(("📋 Talimatlar:\n" + "\n".join(f"{i}. {x['t']}" for i, x in enumerate(tl, 1))) if tl else "Henüz talimat yok.")
        return True
    if eylem in ("hosgeldin_metin", "kural_metin"):
        s = niyet_metin or (metin.split(":", 1)[1].strip() if ":" in metin else "")
        if not s:
            await de("Metni belirtmen lazım, örnek: 'yapay hoşgeldin mesajını şöyle yap: ...'")
            return True
        if eylem == "hosgeldin_metin":
            grup_ayari_uygula(cid, "hosgeldin_metin", s, ozel)
            grup_ayari_uygula(cid, "hosgeldin", True, ozel)
            yer = "tüm gruplara" if ozel else "bu gruba"
            await de(f"✅ Hoş geldin metni {yer} ayarlandı. ({{ad}} ve {{grup}} kullanabilirsin)")
        else:
            grup_ayari_uygula(cid, "kurallar", s, ozel)
            yer = "tüm gruplara" if ozel else "bu gruba"
            await de(f"✅ Kurallar {yer} ayarlandı.")
        return True
    if eylem == "ayar":
        ad = niyet_ayar if niyet_ayar in ("captcha", "hosgeldin", "ipucu") else (
             "captcha" if "captcha" in kw else ("ipucu" if kw_var(kw, "ipucu") else "hosgeldin"))
        ac_deger = niyet_ac if isinstance(niyet_ac, bool) else (not kapat)
        grup_ayari_uygula(cid, ad, ac_deger, ozel)
        yer = "tüm gruplarda" if ozel else "bu grupta"
        await de(f"{ad.upper()} {yer} {'açıldı' if ac_deger else 'kapatıldı'}.")
        return True

    if eylem in ("sil", "pin", "duy") and not r:
        if adresli:
            await de("Bir mesaja yanıt ver.")
        return adresli
    m = ""
    hid = None
    if eylem in ("ban", "unban", "kick", "mute", "unmute", "warn"):
        hid, hadi = hedef_coz(msg, cid, t)
        if not hid:
            if adresli:
                await de("Kimi? Bir mesaja yanıt ver ya da @kullanıcı yaz.")
            return adresli
        if hid == ctx.bot.id or hid == durum.get("sahip"):
            await de("Bunu yapamam 😄")
            return True
        m = mention(cid, hid, hadi)
    try:
        if eylem == "ban":
            await ctx.bot.ban_chat_member(cid, hid)
            cevap = f"🔨 {m} banlandı."
        elif eylem == "unban":
            await ctx.bot.unban_chat_member(cid, hid, only_if_banned=True)
            cevap = f"✅ {m} banı kaldırıldı."
        elif eylem == "kick":
            await ctx.bot.ban_chat_member(cid, hid)
            await ctx.bot.unban_chat_member(cid, hid)
            cevap = f"👢 {m} gruptan atıldı."
        elif eylem == "mute":
            dk = niyet_sure or sure_bul(t) or 10
            await sustur(ctx, cid, hid, dk)
            cevap = f"🔇 {m} {dk} dk susturuldu."
        elif eylem == "unmute":
            await sesi_ac(ctx, cid, hid)
            cevap = f"🔊 {m} artık konuşabilir."
        elif eylem == "warn":
            cevap = await uyari_ver(ctx, cid, hid, m, "")
        elif eylem == "sil":
            await r.delete()
            await bitir()
            return True
        elif eylem == "pin":
            await ctx.bot.pin_chat_message(cid, r.message_id)
            cevap = "📌 Sabitledim."
        elif eylem == "unpin":
            if r:
                await ctx.bot.unpin_chat_message(cid, r.message_id)
            else:
                await ctx.bot.unpin_chat_message(cid)
            cevap = "📌 Sabit kaldırıldı."
        else:
            k = await mesaj_ozeti(ctx, r, chat)
            if not k:
                raise ValueError("mesaj özeti yok")
            k["tarih"] = time.time()
            arsiv_ekle(cid, k)
            cevap = "✅ Duyurulara eklendi."
        await de(cevap, html_mod=True)
        hedef_txt = m if eylem not in ("pin", "unpin", "sil", "arsiv") else "—"
        await log_gonder(ctx, cid,
            f"⚙️ <b>İşlem</b>: {html.escape(str(eylem))}\n"
            f"🎯 {hedef_txt}\n"
            f"👮 {html.escape(user.full_name)}\n"
            f"📍 {html.escape(chat.title or str(cid))}\n"
            f"💬 {html.escape(cevap[:200])}")
        await bitir()
    except Exception as e:
        log.warning(f"Doğal komut hatası: {e}")
        await de("Yapamadım (botun yönetici yetkisi eksik olabilir).")
    return True

ALIAS = {
    # ban
    "ban": "ban", "yasakla": "ban", "b": "ban",
    "sban": "sban", "dban": "dban", "tban": "tban",
    "unban": "unban", "banac": "unban",
    # kick
    "kick": "kick", "at": "kick", "skick": "skick", "dkick": "dkick",
    # mute
    "mute": "mute", "sustur": "mute", "tmute": "tmute", "smute": "smute", "dmute": "dmute",
    "unmute": "unmute", "sesac": "unmute",
    # warn
    "warn": "warn", "uyar": "warn", "dwarn": "dwarn",
    "unwarn": "unwarn", "uyarisil": "unwarn",
    "warns": "warns", "uyarilar": "warns",
    "resetwarns": "resetwarns", "uyarisifirla": "resetwarns",
}

def sure_coz(s):
    """Rose/Combot süre: 10m 2h 3d 1w 30dk 2sa 1gun"""
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*(dk|dakika|sa|saat|gun|gün|g|m|h|d|w|hafta)?", s.lower().strip())
    if not m:
        return None
    birim = m.group(2) or "m"
    carp = {
        "dk": 1, "dakika": 1, "m": 1,
        "sa": 60, "saat": 60, "h": 60,
        "gun": 1440, "gün": 1440, "g": 1440, "d": 1440,
        "w": 10080, "hafta": 10080,
    }.get(birim, 1)
    return max(1, min(int(m.group(1)) * carp, 525600))

def hedef_bul(msg, cid, args):
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.full_name, args
    if args:
        a = args[0]
        if a.startswith("@"):
            for uid, u in uyeler.get(str(cid), {}).items():
                if u["kullanici"].lower() == a[1:].lower():
                    return int(uid), u["ad"], args[1:]
        elif a.isdigit():
            return int(a), ad_bul(cid, a), args[1:]
    return None, None, args

def warn_liste(cid, uid):
    return durum["warn"].setdefault(str(cid), {}).setdefault(str(uid), [])

async def uyari_ver(ctx, cid, hid, m, sebep):
    w = warn_liste(cid, hid)
    w.append({"sebep": sebep, "t": time.time()})
    limit = cget(cid, "warn_limit")
    if len(w) >= limit:
        w.clear()
        eylem = cget(cid, "warn_eylem")
        if eylem == "ban":
            await ctx.bot.ban_chat_member(cid, hid)
            son = "banlandı"
        elif eylem == "kick":
            await ctx.bot.ban_chat_member(cid, hid)
            await ctx.bot.unban_chat_member(cid, hid)
            son = "gruptan atıldı"
        else:
            await sustur(ctx, cid, hid, 60)
            son = "1 saat susturuldu"
        durum_kaydet()
        return f"⚠️ {m} uyarı limitine ulaştı ({limit}/{limit}) ve {son}."
    durum_kaydet()
    return f"⚠️ {m} uyarıldı ({len(w)}/{limit})." + (f"\nSebep: {html.escape(sebep)}" if sebep else "")

async def mod_komut(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private" or not msg.text:
        return
    cid = chat.id
    if not await yetkili_mi(ctx, cid, update.effective_user.id):
        return
    parcalar = msg.text.split()
    islem = ALIAS.get(parcalar[0][1:].split("@")[0].lower())
    if not islem:
        return
    hid, hadi, kalan = hedef_bul(msg, cid, parcalar[1:])
    if not hid:
        await msg.reply_text("Bir mesaja yanıt ver ya da @kullanıcı / ID yaz.")
        return
    if hid == ctx.bot.id or hid == durum.get("sahip"):
        await msg.reply_text("Bunu yapamam 😄")
        return
    m = mention(cid, hid, hadi)
    sebep = " ".join(kalan)
    ekstra = True
    sessiz = False
    try:
        # Yanıt mesajını sil (d* / s* Rose/Combot)
        if islem in ("dban", "dmute", "dkick", "dwarn", "sban", "smute", "skick") and msg.reply_to_message:
            try:
                await msg.reply_to_message.delete()
            except Exception:
                pass
        sessiz = islem in ("sban", "smute", "skick")

        if islem in ("ban", "sban", "dban"):
            await ctx.bot.ban_chat_member(cid, hid)
            cevap = f"🔨 {m} banlandı."
        elif islem == "tban":
            dk = sure_coz(kalan[0]) if kalan else None
            if not dk:
                await msg.reply_text("Süre yaz. Örnek: /tban 2h veya /tban 3d")
                return
            sebep = " ".join(kalan[1:])
            until = datetime.now(timezone.utc) + timedelta(minutes=dk)
            await ctx.bot.ban_chat_member(cid, hid, until_date=until)
            cevap = f"🔨 {m} {dk} dk geçici banlandı."
        elif islem == "unban":
            await ctx.bot.unban_chat_member(cid, hid, only_if_banned=True)
            cevap = f"✅ {m} banı kaldırıldı."
        elif islem in ("kick", "skick", "dkick"):
            await ctx.bot.ban_chat_member(cid, hid)
            await ctx.bot.unban_chat_member(cid, hid)
            cevap = f"👢 {m} gruptan atıldı."
        elif islem in ("mute", "tmute", "smute", "dmute"):
            dk = sure_coz(kalan[0]) if kalan else None
            if dk:
                sebep = " ".join(kalan[1:])
            if islem == "tmute" and not dk:
                await msg.reply_text("Süre yaz. Örnek: /tmute 10m")
                return
            await sustur(ctx, cid, hid, dk)
            cevap = f"🔇 {m} " + (f"{dk} dk " if dk else "") + "susturuldu."
        elif islem == "unmute":
            await sesi_ac(ctx, cid, hid)
            cevap = f"🔊 {m} artık konuşabilir."
        elif islem in ("warn", "dwarn"):
            cevap = await uyari_ver(ctx, cid, hid, m, sebep)
            ekstra = False
        elif islem == "unwarn":
            w = warn_liste(cid, hid)
            if w:
                w.pop()
                durum_kaydet()
            cevap = f"✅ {m} bir uyarısı silindi ({len(w)}/{cget(cid, 'warn_limit')})."
            ekstra = False
        elif islem == "warns":
            w = warn_liste(cid, hid)
            cevap = f"⚠️ {m}: {len(w)}/{cget(cid, 'warn_limit')} uyarı"
            for i, x in enumerate(w, 1):
                cevap += f"\n{i}. {html.escape(x.get('sebep') or 'sebep yok')}"
            ekstra = False
        else:
            warn_liste(cid, hid).clear()
            durum_kaydet()
            cevap = f"✅ {m} uyarıları sıfırlandı."
            ekstra = False
        if ekstra and sebep:
            cevap += "\nSebep: " + html.escape(sebep)
        if not sessiz:
            await ctx.bot.send_message(cid, cevap, parse_mode="HTML")
        else:
            try:
                await msg.delete()
            except Exception:
                pass
        await log_gonder(ctx, cid,
            f"⚙️ <b>{html.escape(islem)}</b>\n🎯 {m}\n👮 {html.escape(update.effective_user.full_name)}\n💬 {html.escape(cevap[:150])}")
    except Exception as e:
        log.warning(f"Moderasyon hatası: {e}")
        await msg.reply_text("Yapamadım (hedef yönetici olabilir ya da yetkim yok).")

def komut_metni(msg):
    p = msg.text.split(None, 1)
    if len(p) > 1:
        return p[1].strip()
    r = msg.reply_to_message
    return ((r.text or r.caption or "").strip()) if r else ""

def ayar_ozet(cid):
    def a(x):
        return "açık" if cget(cid, x) else "kapalı"
    return (f"⚙️ Ayarlar\nAI: {a('ai')} | İpucu: {a('ipucu')} | Hoş geldin: {a('hosgeldin')} | "
            f"Captcha: {a('captcha')} | Yönetici izni: {a('adminizin')}\n"
            f"Flood: {cget(cid, 'flood')} mesaj/10sn | Uyarı limiti: {cget(cid, 'warn_limit')} → {cget(cid, 'warn_eylem')}\n"
            f"Kilitler: {', '.join(cget(cid, 'kilit')) or 'yok'}\n"
            f"Yasaklı kelime: {len(durum['kara'].get(str(cid), []))} | Not: {len(durum['not'].get(str(cid), {}))} | "
            f"Filtre: {len(durum['filtre'].get(str(cid), {}))} | Duyuru arşivi: {len(durum['arsiv'].get(str(cid), []))}")

async def yonet_komut(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    cid = chat.id
    if not msg or not msg.text:
        return
    # Özelde sadece sahip ayar komutları çalışsın (gruba yayılır)
    ozel_izinli = {
        "hosgeldinmetni", "hosgeldinsifirla", "kuralayarla", "kuralsil",
        "flood", "setflood", "uyarilimit", "uyarieylem",
        "kilit", "kilitac", "lock", "unlock", "locks", "unlocks", "kilitler", "ayarlar",
    }
    ad0 = msg.text.split()[0][1:].split("@")[0].lower()
    if chat.type == "private":
        if not sahip_mi(update.effective_user) or ad0 not in ozel_izinli:
            return
    elif not await yetkili_mi(ctx, cid, update.effective_user.id):
        return
    p = msg.text.split(None, 2)
    ad = p[0][1:].split("@")[0].lower()
    a1 = p[1] if len(p) > 1 else ""
    a2 = p[2] if len(p) > 2 else ""
    yanit = msg.reply_to_message
    scid = str(cid)

    async def de(t):
        await msg.reply_text(t)

    if ad in ("flood", "setflood"):
        if a1.isdigit() and 0 <= int(a1) <= 30:
            grup_ayari_uygula(cid, "flood", int(a1), chat.type == "private")
            await de("Flood: " + ("kapalı" if int(a1) == 0 else f"10 sn'de {a1} mesaj") + (" (tüm gruplar)" if chat.type == "private" else ""))
        else:
            await de("Örnek: /flood 6 (0 = kapalı)")
    elif ad in ("uyarilimit", "warnlimit"):
        if a1.isdigit() and 1 <= int(a1) <= 20:
            grup_ayari_uygula(cid, "warn_limit", int(a1), chat.type == "private")
            await de(f"Uyarı limiti: {a1}" + (" (tüm gruplar)" if chat.type == "private" else ""))
        else:
            await de("Örnek: /uyarilimit 3")
    elif ad in ("uyarieylem", "warntime"):
        if a1.lower() in ("ban", "kick", "mute"):
            grup_ayari_uygula(cid, "warn_eylem", a1.lower(), chat.type == "private")
            await de(f"Limit dolunca: {a1.lower()}" + (" (tüm gruplar)" if chat.type == "private" else ""))
        else:
            await de("Örnek: /uyarieylem mute (ban, kick, mute)")
    elif ad == "kuralayarla":
        t = komut_metni(msg)
        if t:
            grup_ayari_uygula(cid, "kurallar", t, chat.type == "private")
            yer = "tüm gruplara" if chat.type == "private" else "bu gruba"
            await de(f"✅ Kurallar {yer} kaydedildi.")
        else:
            await de("Örnek: /kuralayarla kural metni")
    elif ad == "kuralsil":
        grup_ayari_uygula(cid, "kurallar", None, chat.type == "private")
        await de("Kurallar silindi.")
    elif ad == "hosgeldinmetni":
        t = komut_metni(msg)
        if t:
            grup_ayari_uygula(cid, "hosgeldin_metin", t, chat.type == "private")
            grup_ayari_uygula(cid, "hosgeldin", True, chat.type == "private")
            yer = "tüm gruplara" if chat.type == "private" else "bu gruba"
            await de(f"✅ Hoş geldin metni {yer} kaydedildi. ({{ad}} ve {{grup}} kullanabilirsin)")
        else:
            await de("Örnek: /hosgeldinmetni Merhaba {ad}, {grup} grubuna hoş geldin!")
    elif ad == "hosgeldinsifirla":
        grup_ayari_uygula(cid, "hosgeldin_metin", None, chat.type == "private")
        await de("Hoş geldin metni varsayılana döndü (yapay zeka yazar).")
    elif ad == "setlog":
        # /setlog @kanal | /setlog -100... | kanal mesajına yanıt | iletilmiş kanala yanıt
        def kanal_id_bul(m):
            if not m:
                return None
            if getattr(m, "forward_from_chat", None) is not None:
                return m.forward_from_chat.id
            if getattr(m, "sender_chat", None) is not None and getattr(m.sender_chat, "type", "") in ("channel", "supergroup"):
                return m.sender_chat.id
            fo = getattr(m, "forward_origin", None)
            if fo is not None:
                ch = getattr(fo, "chat", None)
                if ch is not None:
                    return ch.id
            return None

        hedef = None
        arg = (a1 + " " + a2).strip()
        if arg.startswith("@"):
            try:
                ch = await ctx.bot.get_chat(arg.split()[0])
                hedef = ch.id
            except Exception as e:
                await de(f"Kanal bulunamadı: {e}")
                return
        elif arg.lstrip("-").isdigit():
            hedef = int(arg.split()[0])
        else:
            hedef = kanal_id_bul(yanit) or kanal_id_bul(msg)

        if not hedef:
            await de(
                "Rapor kanalı ayarlamak için:\n"
                "1) Kanalından bir mesajı gruba ilet\n"
                "2) O iletilmiş mesaja yanıt verip yaz: /setlog\n\n"
                "veya kanalın @kullaniciadi varsa: /setlog @kanaladi"
            )
            return
        cset(cid, "log_kanal", hedef)
        await de(f"✅ Rapor kanalı ayarlandı: <code>{hedef}</code>\nBot o kanalda yönetici olmalı (mesaj gönderebilsin).")
        try:
            await ctx.bot.send_message(
                hedef,
                f"📋 Bu kanal artık <b>{html.escape(chat.title or str(cid))}</b> grubunun rapor kanalı.",
                parse_mode="HTML",
            )
        except Exception as e:
            await de(f"⚠️ Kanal ayarlandı ama test mesajı gidemedi (botu kanala yönetici ekle): {e}")
    elif ad == "unsetlog":
        cset(cid, "log_kanal", None)
        await de("Rapor kanalı kaldırıldı.")
    elif ad in ("kaydet", "save"):
        isim = kucult(a1)
        t = a2.strip() or ((yanit.text or yanit.caption or "").strip() if yanit else "")
        if isim and t:
            durum["not"].setdefault(scid, {})[isim] = t
            durum_kaydet()
            await de(f"✅ Kaydedildi: #{isim}")
        else:
            await de("Örnek: /kaydet isim metin (ya da bir mesaja yanıt ver)")
    elif ad == "notsil":
        if durum["not"].get(scid, {}).pop(kucult(a1), None) is not None:
            durum_kaydet()
            await de("Not silindi.")
        else:
            await de("Böyle bir not yok.")
    elif ad == "filtre":
        kw = kucult(a1)
        t = a2.strip() or ((yanit.text or yanit.caption or "").strip() if yanit else "")
        if kw and t:
            durum["filtre"].setdefault(scid, {})[kw] = t
            durum_kaydet()
            await de(f"✅ Filtre eklendi: {kw}")
        else:
            await de("Örnek: /filtre kelime cevap")
    elif ad == "filtresil":
        if durum["filtre"].get(scid, {}).pop(kucult(a1), None) is not None:
            durum_kaydet()
            await de("Filtre silindi.")
        else:
            await de("Böyle bir filtre yok.")
    elif ad in ("kara", "karasil"):
        kelimeler = [kucult(x) for x in (a1 + " " + a2).split() if x]
        liste = durum["kara"].setdefault(scid, [])
        if not kelimeler:
            await de("Örnek: /kara kelime")
        else:
            for k in kelimeler:
                if ad == "kara" and k not in liste:
                    liste.append(k)
                if ad == "karasil" and k in liste:
                    liste.remove(k)
            durum_kaydet()
            await de(("✅ Yasaklı kelimeler: " + ", ".join(liste)) if liste else "Yasaklı kelime listesi boş.")
    elif ad == "karalar":
        liste = durum["kara"].get(scid, [])
        await de(("Yasaklı kelimeler: " + ", ".join(liste)) if liste else "Yasaklı kelime yok.")
    elif ad in ("kilit", "kilitac", "lock", "unlock", "locks", "unlocks", "kilitler"):
        ozel = chat.type == "private"
        # /locks veya /kilitler → liste
        if ad in ("locks", "kilitler") or (ad in ("kilit", "lock") and not a1):
            liste = cget(cid, "kilit") or []
            await de("🔒 Aktif kilitler: " + (", ".join(liste) if liste else "yok (her şey açık)"))
            return
        # /unlocks veya /unlock all → hepsini aç
        if ad in ("unlocks",) or (ad in ("kilitac", "unlock") and kucult(a1) in ("all", "hepsi", "hepsini", "tümü", "tumu", "")):
            if not a1 and ad in ("kilitac", "unlock"):
                # tek tür yoksa all say
                pass
            tum_kilitleri_ac(ozel=ozel, cid=None if ozel else cid)
            if not ozel:
                cset(cid, "kilit", [])
            await de("🔓 Tüm kilitler açıldı — link dahil herkes paylaşabilir." + (" (tüm gruplar)" if ozel else ""))
            return
        tur = kucult(a1)
        if tur in ("all", "hepsi", "hepsini", "tümü", "tumu"):
            if ad in ("kilitac", "unlock"):
                tum_kilitleri_ac(ozel=ozel, cid=None if ozel else cid)
                if not ozel:
                    cset(cid, "kilit", [])
                await de("🔓 Tüm kilitler açıldı.")
            else:
                grup_ayari_uygula(cid, "kilit", list(KILIT_TURLERI), ozel)
                await de("🔒 Tüm türler kilitlendi.")
            return
        if tur not in KILIT_TURLERI:
            await de("Türler: " + ", ".join(KILIT_TURLERI) + "\nÖrnek: /unlock link  |  /lock sticker  |  /unlocks")
            return
        k = list(cget(cid, "kilit") or [])
        if ad in ("kilit", "lock"):
            if tur not in k:
                k.append(tur)
            grup_ayari_uygula(cid, "kilit", k, ozel)
            await de(f"🔒 Kilitlendi: {tur}" + (" (tüm gruplar)" if ozel else ""))
        else:
            if tur in k:
                k.remove(tur)
            grup_ayari_uygula(cid, "kilit", k, ozel)
            await de(f"🔓 Açıldı: {tur}" + (" (tüm gruplar)" if ozel else ""))
    elif ad in ("promote", "yukselt"):
        if not yanit and not a1:
            await de("Yanıt ver veya @kullanıcı yaz.")
            return
        hid, hadi, _ = hedef_bul(msg, cid, ([a1] if a1 else []))
        if not hid and yanit and yanit.from_user:
            hid, hadi = yanit.from_user.id, yanit.from_user.full_name
        if not hid:
            await de("Kullanıcı bulunamadı.")
            return
        try:
            await ctx.bot.promote_chat_member(
                cid, hid,
                can_delete_messages=True, can_restrict_members=True,
                can_pin_messages=True, can_manage_chat=True,
            )
            await de(f"✅ {html.escape(hadi or str(hid))} yönetici yapıldı.")
        except Exception as e:
            await de(f"Yükseltemedim: {e}")
    elif ad in ("demote", "dusur"):
        if not yanit and not a1:
            await de("Yanıt ver veya @kullanıcı yaz.")
            return
        hid, hadi, _ = hedef_bul(msg, cid, ([a1] if a1 else []))
        if not hid and yanit and yanit.from_user:
            hid, hadi = yanit.from_user.id, yanit.from_user.full_name
        if not hid:
            await de("Kullanıcı bulunamadı.")
            return
        try:
            await ctx.bot.promote_chat_member(
                cid, hid,
                can_change_info=False, can_delete_messages=False, can_restrict_members=False,
                can_invite_users=False, can_pin_messages=False, can_manage_chat=False,
            )
            await de(f"✅ {html.escape(hadi or str(hid))} yöneticilikten alındı.")
        except Exception as e:
            await de(f"Düşüremedim: {e}")
    elif ad in ("adminlist", "admins", "yoneticiler"):
        try:
            ads = await ctx.bot.get_chat_administrators(cid)
            satir = ["👮 Yöneticiler:"]
            for a in ads:
                u = a.user
                if u.is_bot:
                    continue
                un = f"@{u.username}" if u.username else u.full_name
                satir.append(f"• {html.escape(un)} (<code>{u.id}</code>)")
            await de("\n".join(satir))
        except Exception as e:
            await de(f"Liste alınamadı: {e}")
    elif ad in ("setwelcome", "setrules", "welcome", "resetwelcome", "resetrules"):
        # Rose alias'ları
        if ad == "setwelcome":
            met = komut_metni(msg)
            if not met:
                await de("Örnek: /setwelcome Merhaba {ad}!")
                return
            grup_ayari_uygula(cid, "hosgeldin_metin", met, chat.type == "private")
            grup_ayari_uygula(cid, "hosgeldin", True, chat.type == "private")
            await de("✅ Welcome ayarlandı.")
        elif ad == "welcome":
            if kucult(a1) in ("on", "ac", "aç", "true", "1"):
                grup_ayari_uygula(cid, "hosgeldin", True, chat.type == "private")
                await de("Welcome açıldı.")
            elif kucult(a1) in ("off", "kapat", "kapali", "kapalı", "false", "0"):
                grup_ayari_uygula(cid, "hosgeldin", False, chat.type == "private")
                await de("Welcome kapatıldı.")
            else:
                m = cget(cid, "hosgeldin_metin")
                await de(("Welcome metni:\n" + m) if m else "Özel metin yok (AI yazar). /setwelcome ile ayarla.")
        elif ad == "resetwelcome":
            grup_ayari_uygula(cid, "hosgeldin_metin", None, chat.type == "private")
            await de("Welcome sıfırlandı.")
        elif ad == "setrules":
            met = komut_metni(msg)
            if not met:
                await de("Örnek: /setrules Kurallar burada...")
                return
            grup_ayari_uygula(cid, "kurallar", met, chat.type == "private")
            await de("✅ Rules ayarlandı.")
        elif ad == "resetrules":
            grup_ayari_uygula(cid, "kurallar", None, chat.type == "private")
            await de("Rules silindi.")
    elif ad == "ayarlar":

        await de(ayar_ozet(cid))
    elif ad == "duyuruekle":
        if not yanit:
            await de("Duyuru yapılacak mesaja yanıt ver.")
            return
        k = await mesaj_ozeti(ctx, yanit, chat)
        if k:
            k["tarih"] = time.time()
            arsiv_ekle(cid, k)
            await de("✅ Duyurulara eklendi.")
        else:
            await de("Ekleyemedim.")
    elif ad in ("del", "sil"):
        if not yanit:
            await de("Silinecek mesaja yanıt ver.")
            return
        try:
            await yanit.delete()
            await msg.delete()
        except Exception:
            await de("Silemedim (yetkim yok olabilir).")
    elif ad == "purge":
        if not yanit:
            await de("Silmeye başlanacak mesaja yanıt ver.")
            return
        ids = list(range(yanit.message_id, msg.message_id + 1))[-100:]
        try:
            await ctx.bot.delete_messages(cid, ids)
        except Exception as e:
            log.warning(f"Purge hatası: {e}")
            await de("Silemedim (yetkim yok olabilir).")
    elif ad in ("pin", "sabitle"):
        if not yanit:
            await de("Sabitlenecek mesaja yanıt ver.")
            return
        try:
            await ctx.bot.pin_chat_message(cid, yanit.message_id)
        except Exception:
            await de("Sabitleyemedim (yetkim yok olabilir).")
    elif ad in ("unpin", "sabitkaldir"):
        try:
            if yanit:
                await ctx.bot.unpin_chat_message(cid, yanit.message_id)
            else:
                await ctx.bot.unpin_chat_message(cid)
            await de("📌 Sabit kaldırıldı.")
        except Exception:
            await de("Kaldıramadım (yetkim yok olabilir).")

async def rapor_gonder(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    hedef = msg.reply_to_message or msg
    try:
        adminler = await ctx.bot.get_chat_administrators(chat.id)
        etiket = " ".join(a.user.mention_html() for a in adminler if not a.user.is_bot)
    except Exception:
        etiket = ""
    link = mesaj_linki(chat, hedef.message_id) or ""
    await ctx.bot.send_message(chat.id, f"🚨 Rapor: {etiket}\n{link}", parse_mode="HTML")

async def genel_komut(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    cid = chat.id
    if not msg or not msg.text:
        return
    p = msg.text.split()
    ad = p[0][1:].split("@")[0].lower()
    if ad in ("yardim", "help", "start"):
        await msg.reply_text(YARDIM, parse_mode="HTML")
        return
    if chat.type == "private":
        return
    scid = str(cid)
    if ad in ("kurallar", "rules"):
        await msg.reply_text(cget(cid, "kurallar") or "Henüz kural yazılmamış.")
    elif ad in ("not", "get"):
        isim = kucult(p[1]) if len(p) > 1 else ""
        await msg.reply_text(durum["not"].get(scid, {}).get(isim) or "Böyle bir not yok. /notlar yaz.")
    elif ad in ("notlar", "notes"):
        n = durum["not"].get(scid, {})
        await msg.reply_text(("📝 Notlar: " + " ".join("#" + k for k in n)) if n else "Kayıtlı not yok.")
    elif ad in ("filtreler", "filters"):
        f = durum["filtre"].get(scid, {})
        await msg.reply_text(("🔎 Filtreler: " + ", ".join(f)) if f else "Filtre yok.")
    elif ad == "kilitler":
        await msg.reply_text("🔒 Kilitler: " + (", ".join(cget(cid, "kilit")) or "yok"))
    elif ad == "id":
        h = msg.reply_to_message.from_user if msg.reply_to_message and msg.reply_to_message.from_user else user
        await msg.reply_text(f"🆔 {h.id}\nGrup: {cid}")
    elif ad in ("bilgi", "info"):
        h = msg.reply_to_message.from_user if msg.reply_to_message and msg.reply_to_message.from_user else user
        k = uyeler.get(scid, {}).get(str(h.id), {})
        w = len(durum["warn"].get(scid, {}).get(str(h.id), []))
        satir = [f"👤 {h.full_name}", f"🆔 {h.id}"]
        if h.username:
            satir.append(f"@{h.username}")
        satir.append(f"💬 {k.get('mesaj', 0)} mesaj | 📅 İlk görülme: {k.get('ilk', '?')}")
        satir.append(f"⚠️ Uyarı: {w}/{cget(cid, 'warn_limit')}")
        await msg.reply_text("\n".join(satir))
    elif ad == "top":
        en = sorted(uyeler.get(scid, {}).values(), key=lambda u: u["mesaj"], reverse=True)[:10]
        satir = ["🏆 En aktif üyeler"] + [f"{i}. {u['ad']} — {u['mesaj']}" for i, u in enumerate(en, 1)]
        await msg.reply_text("\n".join(satir))
    elif ad == "istatistik":
        k = uyeler.get(scid, {})
        await msg.reply_text(f"📊 Tanıdığım üye: {len(k)}\n💬 Toplam mesaj: {sum(u['mesaj'] for u in k.values())}")
    elif ad in ("rapor", "report"):
        await rapor_gonder(update, ctx)

async def hosgeldin_gonder(ctx, cid, u, baslik):
    if not cget(cid, "hosgeldin"):
        return
    sablon = cget(cid, "hosgeldin_metin")
    if sablon:
        s = html.escape(sablon).replace("{ad}", u.mention_html()).replace("{grup}", html.escape(baslik or ""))
        if "{ad}" not in sablon:
            s = u.mention_html() + " " + s
    else:
        ai = await asyncio.to_thread(sor, [{"role": "user", "content":
            "Gruba yeni katılan birine tek cümlelik, samimi ve kısa bir hoş geldin mesajı yaz. "
            "İsim yazma, link verme."}])
        s = f"{u.mention_html()} {html.escape((ai or 'Hoş geldin!').strip())}\nKural: link, küfür ve spam yasak. /kurallar"
    m = await ctx.bot.send_message(cid, s, parse_mode="HTML")
    try:
        task = asyncio.create_task(mesaj_sil_sn(ctx, cid, m.message_id, 5))
        gorevler.add(task)
        task.add_done_callback(gorevler.discard)
    except Exception:
        pass

async def captcha_sure(ctx, cid, uid, mid):
    await asyncio.sleep(180)
    if bekleyen.pop((cid, uid), None):
        try:
            await ctx.bot.ban_chat_member(cid, uid)
            await ctx.bot.unban_chat_member(cid, uid)
        except Exception as e:
            log.warning(f"Captcha atma hatası: {e}")
        try:
            await ctx.bot.delete_message(cid, mid)
        except Exception:
            pass

async def hosgeldin(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    cid = chat.id
    # "X kişisini eklediniz / gruba katıldı" sistem mesajını sil
    try:
        await msg.delete()
    except Exception as e:
        log.warning(f"Katılım mesajı silinemedi: {e}")

    for u in (msg.new_chat_members or []):
        if u.is_bot:
            # Bot eklendiyse sadece sistem mesajı silindi, hoşgeldin atma
            continue
        uye_kaydi(cid, u, say=False)
        kaydet()
        uname = f"@{u.username}" if u.username else "—"
        await log_gonder(ctx, cid,
            f"🟢 <b>Katıldı</b>"
            f"👤 {html.escape(u.full_name)} ({uname})"
            f"🆔 <code>{u.id}</code>"
            f"📍 {html.escape(chat.title or str(cid))}")
        if cget(cid, "captcha"):
            try:
                await sustur(ctx, cid, u.id)
                klavye = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Robot değilim", callback_data=f"cap:{u.id}")]])
                m = await ctx.bot.send_message(
                    cid, f"{u.mention_html()} hoş geldin! 3 dk içinde butona bas, yoksa gruptan atılırsın.",
                    parse_mode="HTML", reply_markup=klavye)
                bekleyen[(cid, u.id)] = m.message_id
                t = asyncio.create_task(captcha_sure(ctx, cid, u.id, m.message_id))
                gorevler.add(t)
                t.add_done_callback(gorevler.discard)
                continue
            except Exception as e:
                log.warning(f"Captcha kurulamadı: {e}")
        await hosgeldin_gonder(ctx, cid, u, chat.title)
        # Newbies: yeni üyeyi X dk sustur
        ndk = int(cget(cid, "newbies_dk") or 0)
        if ndk > 0:
            try:
                await sustur(ctx, cid, u.id, ndk)
            except Exception as e:
                log.warning(f"Newbies mute: {e}")

async def ayrildi(update, ctx):
    """X gruptan ayrildi - sil + log + unut."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    cid = chat.id
    try:
        await msg.delete()
    except Exception:
        pass
    u = msg.left_chat_member
    if u and not u.is_bot:
        uname = f"@{u.username}" if u.username else "—"
        metin = (
            "🔴 <b>Ayrıldı / çıkarıldı</b>\n"
            f"👤 {html.escape(u.full_name)} ({uname})\n"
            f"🆔 <code>{u.id}</code>\n"
            f"📍 {html.escape(chat.title or str(cid))}"
        )
        await log_gonder(ctx, cid, metin)
        try:
            k = uyeler.get(str(cid), {})
            if str(u.id) in k:
                del k[str(u.id)]
                kaydet()
        except Exception as e:
            log.warning(f"Üye silme hatası: {e}")
    try:
        await msg.delete()
    except Exception as e:
        log.warning(f"Ayrılma mesajı silinemedi: {e}")


async def captcha_buton(update, ctx):
    q = update.callback_query
    try:
        uid = int(q.data.split(":")[1])
    except Exception:
        return
    if q.from_user.id != uid:
        await q.answer("Bu buton senin için değil.", show_alert=True)
        return
    cid = q.message.chat.id
    if bekleyen.pop((cid, uid), None) is None:
        await q.answer()
        return
    try:
        await sesi_ac(ctx, cid, uid)
    except Exception as e:
        log.warning(f"Captcha açma hatası: {e}")
    await q.answer("Doğrulandı ✅")
    try:
        await q.message.delete()
    except Exception:
        pass
    await hosgeldin_gonder(ctx, cid, q.from_user, q.message.chat.title)

FIYAT_KOK = ("fiyat", "kaç", "kac", "price", "dolar", "değer")
GRUP_SORU = re.compile(r"(grubun\s+amac|grup\s+ne\s+i[cç]in|ne\s+payla[sş][iı]l|neler\s+payla[sş][iı]l|grupta\s+ne|burada\s+ne\s+(var|yap|konu[sş]))")

async def kilit_kontrol(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not user or user.is_bot or chat.type == "private":
        return
    # Sadece YeniBirAirdrops kanal paylaşımları kilide takılmaz
    def _izinli_kanal(m):
        for ch in (
            getattr(m, "sender_chat", None),
            getattr(m, "forward_from_chat", None),
            getattr(getattr(m, "forward_origin", None), "chat", None),
        ):
            if ch is None:
                continue
            un = (getattr(ch, "username", None) or "").lower()
            title = kucult(getattr(ch, "title", None) or "")
            if un == "yenibirairdrops" or "yenibirairdrops" in title.replace(" ", "") or "yeni bir airdrop" in title:
                return True
        return False
    if _izinli_kanal(msg):
        return
    kilit = cget(chat.id, "kilit") or []
    if not kilit or not any(x in kilit for x in mesaj_turleri(msg)):
        return
    if await muaf_mi(ctx, chat.id, user.id):
        return
    try:
        await msg.delete()
    except Exception:
        pass

async def mesaj(update, ctx):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or user.is_bot:
        return
    metin = msg.text or msg.caption
    if not metin:
        return
    ozel = chat.type == "private"
    cid = chat.id
    kayit = uye_kaydi(cid, user)
    if not ozel and str(user.id) in _liste_uid(cid, "blacklist"):
        try:
            await msg.delete()
            await ctx.bot.ban_chat_member(cid, user.id)
        except Exception:
            pass
        return
    if not ozel and gece_modu_aktif(cid) and not await muaf_mi(ctx, cid, user.id):
        try:
            await msg.delete()
        except Exception:
            pass
        return
    sm = int(cget(cid, "slowmode") or 0)
    if not ozel and sm > 0 and not await muaf_mi(ctx, cid, user.id):
        anahtar_sm = ("sm", cid, user.id)
        son = zamanlar.get(anahtar_sm)
        now = time.time()
        if isinstance(son, (int, float)) and now - son < sm:
            try:
                await msg.delete()
            except Exception:
                pass
            return
        zamanlar[anahtar_sm] = now
    kt = kisa_token(metin)
    kelimeler = re.findall(r"\w+", kucult(metin))

    # ÖZELDEN GRUBA MESAJ (sahip)
    if ozel and (sahip_mi(user) or (user.username and user.username.lower() == SAHIP_KULLANICI)):
        if not sahip_mi(user) and user.username and user.username.lower() == SAHIP_KULLANICI:
            durum["sahip"] = user.id
            durum_kaydet()
        t0 = kucult(metin)
        temiz = re.sub(r"(?i)\byapay\b", "", metin).strip()
        gonderilecek = None
        m = re.search(
            r"(?:gruba|grupta)\s+(?:şunu\s+|sunu\s+|bunu\s+)?(?:söyle|soyle|yaz|at|paylaş|paylas|gönder|gonder)?\s*[:=]?\s*(.+)",
            temiz, re.IGNORECASE | re.DOTALL
        )
        if m and m.group(1).strip():
            gonderilecek = re.sub(
                r"^(?:şunu|sunu|bunu|yaz|at|söyle|soyle|paylaş|paylas|gönder|gonder)\s*[:=]?\s*",
                "", m.group(1).strip(), flags=re.I
            ).strip()
        if not gonderilecek and re.search(r"(gruba|grupta).*(saat|saati)", t0):
            gonderilecek = datetime.now(TR).strftime("Şu an saat %H:%M")
        if gonderilecek:
            sayac = 0
            for gcid in list(uyeler.keys()):
                if int(gcid) < 0:
                    try:
                        await ctx.bot.send_message(int(gcid), gonderilecek)
                        sayac += 1
                    except Exception as e:
                        log.warning(f"Gruba gönderilemedi ({gcid}): {e}")
            if sayac == 0:
                await msg.reply_text("Henüz kayıtlı grup yok. Botu gruba ekle, grupta bir mesaj yaz.")
            else:
                await msg.reply_text(f"✅ {sayac} gruba gönderildi:\n{gonderilecek}")
            return

    # Sadece bağlı kanaldan (Yeni Bir Airdrop vb.) gelen otomatik iletileri sabitle + arşive al
    if not ozel:
        kanal_mesaji = False
        kanal_adi = ""
        sc = getattr(msg, "sender_chat", None)
        if sc is not None and getattr(sc, "type", "") == "channel":
            kanal_mesaji = True
            kanal_adi = (sc.title or sc.username or "")
        if getattr(msg, "is_automatic_forward", False):
            kanal_mesaji = True
            fo = getattr(msg, "forward_origin", None)
            if fo is not None and getattr(fo, "chat", None) is not None:
                kanal_adi = (fo.chat.title or fo.chat.username or kanal_adi)
            elif getattr(msg, "forward_from_chat", None) is not None:
                kanal_adi = (msg.forward_from_chat.title or msg.forward_from_chat.username or kanal_adi)
        if kanal_mesaji:
            izinli = cget(cid, "duyuru_kanal")  # None = varsayılan: YeniBirAirdrops
            ad_k = kucult(kanal_adi)
            uname = ""
            if sc is not None:
                uname = (sc.username or "").lower()
            fo_chat = getattr(msg, "forward_from_chat", None)
            if fo_chat is not None and not uname:
                uname = (fo_chat.username or "").lower()
            fo = getattr(msg, "forward_origin", None)
            if fo is not None and getattr(fo, "chat", None) is not None and not uname:
                uname = (fo.chat.username or "").lower()
            uygun = False
            if izinli:
                if str(izinli).lstrip("-").isdigit():
                    kid = sc.id if sc else None
                    if kid and int(izinli) == int(kid):
                        uygun = True
                    elif fo_chat and int(izinli) == int(fo_chat.id):
                        uygun = True
                elif kucult(str(izinli)) in ad_k or kucult(str(izinli)) == uname:
                    uygun = True
            else:
                # Varsayılan kaynak: https://t.me/YeniBirAirdrops
                uygun = (
                    "yenibirairdrops" in ad_k.replace(" ", "")
                    or "yeni bir airdrop" in ad_k
                    or (sc and (sc.username or "").lower() == "yenibirairdrops")
                )
            if uygun:
                try:
                    kayit_ozet = await mesaj_ozeti(ctx, msg, chat)
                    if kayit_ozet:
                        kayit_ozet["tarih"] = time.time()
                        # Başlık: metin yoksa AI ile üret
                        met = kayit_ozet.get("metin") or ""
                        if len(met.strip()) < 8:
                            try:
                                bas = await asyncio.to_thread(
                                    arsiv_baslik_uret, met, kayit_ozet.get("link")
                                )
                                kayit_ozet["baslik"] = bas
                            except Exception:
                                pass
                        else:
                            kayit_ozet["baslik"] = arsiv_baslik_uret(met, kayit_ozet.get("link"))
                        arsiv_ekle(cid, kayit_ozet)
                        await ctx.bot.pin_chat_message(cid, msg.message_id, disable_notification=True)
                        log.info(f"Kanal duyurusu pin+arsiv: {cid} | {kanal_adi} | {kayit_ozet.get('baslik')}")
                except Exception as e:
                    log.warning(f"Otomatik duyuru/pin hatası: {e}")

    if await komut(update, ctx, metin):
        return

    if not ozel and "yapay" in kucult(metin) and "ceza" in kucult(metin):
        hedef_user = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            hedef_user = msg.reply_to_message.from_user
        else:
            m = re.search(r"@(\w{4,})", metin)
            if m:
                for uid, u in uyeler.get(str(cid), {}).items():
                    if u["kullanici"].lower() == m.group(1).lower():
                        class FakeUser:
                            def __init__(self, uid, ad):
                                self.id = int(uid)
                                self.full_name = ad
                                self.mention_html = lambda: f'<a href="tg://user?id={self.id}">{html.escape(ad)}</a>'
                        hedef_user = FakeUser(uid, u["ad"])
                        break
        if hedef_user and hedef_user.id != ctx.bot.id and hedef_user.id != durum.get("sahip"):
            try:
                await ctx.bot.send_poll(
                    chat_id=cid,
                    question=f"⚠️ Ceza: {hedef_user.full_name}\n5 dakika susturulsun mu?",
                    options=["✅ Evet", "❌ Hayır"],
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
            except Exception as e:
                log.warning(f"Ceza oylaması hatası: {e}")
            return

    if not ozel:
        # Sadece YeniBirAirdrops kanalından gelen paylaşımlar link yasağından muaf
        def _yenibir_kanal_mi(m):
            sc = getattr(m, "sender_chat", None)
            fo = getattr(m, "forward_from_chat", None)
            fo2 = getattr(m, "forward_origin", None)
            adaylar = []
            if sc is not None:
                adaylar.append(sc)
            if fo is not None:
                adaylar.append(fo)
            if fo2 is not None and getattr(fo2, "chat", None) is not None:
                adaylar.append(fo2.chat)
            for ch in adaylar:
                un = (getattr(ch, "username", None) or "").lower()
                title = kucult(getattr(ch, "title", None) or "")
                if un == "yenibirairdrops" or "yenibirairdrops" in title.replace(" ", "") or "yeni bir airdrop" in title:
                    return True
            return False

        kanal_izinli = _yenibir_kanal_mi(msg) or (
            getattr(msg, "is_automatic_forward", False) and _yenibir_kanal_mi(msg)
        )
        n = cget(cid, "flood")
        spam = n > 0 and spam_mi(cid, user.id, n)
        ad = None
        onayli = str(user.id) in _liste_uid(cid, "approved") or str(user.id) in _liste_uid(cid, "whitelist")
        if not kanal_izinli and not onayli and (scam_var(metin) or ("link" in (cget(cid, "kilit") or []) and link_var(msg, metin))):
            ad = "link/şifre paylaşımı"
        elif kufur_var(metin):
            ad = "küfür/hakaret"
        elif kara_var(cid, kelimeler):
            ad = "yasaklı kelime"
        elif spam:
            ad = "spam"
        if ad and not await muaf_mi(ctx, cid, user.id):
            await ihlal(update, ctx, ad, True)  # ihlal mesajı silinsin
            return
        if "@admin" in kucult(metin):
            await rapor_gonder(update, ctx)
            return
        if metin.startswith("#") and len(metin) > 1:
            parca = metin[1:].split()
            tn = durum["not"].get(str(cid), {}).get(kucult(parca[0])) if parca else None
            if tn:
                await msg.reply_text(tn)
                return
        for kw_, cev in durum["filtre"].get(str(cid), {}).items():
            if kw_ in kelimeler:
                await msg.reply_text(cev)
                return
        if kt and await fiyat_gonder(update, ctx, kt[1], kt[0], False):
            return
        botun_mesaji = (msg.reply_to_message and msg.reply_to_message.from_user
                        and msg.reply_to_message.from_user.id == ctx.bot.id)
        cagrildi = (
            "yapay" in kucult(metin)
            or bool(botun_mesaji)
            or sahip_mi(user)
        )
        if (cagrildi or len(kelimeler) <= 3) and set(kelimeler) & LISTE_KISA:
            gun, baslik = liste_gun(kelimeler)
            await arsiv_gonder(update, ctx, gun, baslik)
            return
        if not cagrildi:
            return
    else:
        if kt and await fiyat_gonder(update, ctx, kt[1], kt[0], False):
            return

    await ctx.bot.send_chat_action(cid, "typing")

    if not ozel and any(k.startswith(("pin", "sabit")) for k in kelimeler):
        await sabit_cevap(update, ctx)
        return

    if any(k.startswith(FIYAT_KOK) for k in kelimeler):
        token = await asyncio.to_thread(token_cikar, metin)
        if token and await fiyat_gonder(update, ctx, token):
            return

    if not ozel and not cget(cid, "ai"):
        return
    if not ozel and cget(cid, "ai_mod") and not await yetkili_mi(ctx, cid, user.id):
        return

    ek = f"\nŞu an sana yazan kişi: {user.full_name}. Bu kişi {kayit['ilk']} tarihinden beri grupta, {kayit['mesaj']} mesaj yazdı. Ona ismiyle hitap et."
    if sahip_mi(user):
        ek += "\nBu kişi grubun SAHİBİ ve senin patronun (Jimin). Ona karşı çok samimi, sıcak ve itaatkâr ol."
    if durum["talimat"]:
        ek += ("\nSahibinin kalıcı talimatları (sessizce uy): "
               + " | ".join(x["t"] for x in durum["talimat"][-10:]))
    if not ozel:
        ek += "\nGrubun bilinen üyeleri: " + tanidiklar(cid)
        son = durum["sabit"].get(str(cid), {}).get("son")
        if son and son.get("metin"):
            ek += "\nGrubun sabitlenmiş mesajı: " + son["metin"][:350]
        if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == ctx.bot.id:
            onceki = (msg.reply_to_message.text or msg.reply_to_message.caption or "").strip()
            if onceki:
                ek += f"\nBu kişi senin şu önceki mesajına yanıt veriyor: \"{onceki[:300]}\". O konuyu sürdür, konuyu değiştirme."
    if GRUP_SORU.search(kucult(metin)):
        ek += ("\nBu soruda grubun içeriği hakkında HİÇBİR bilgi verme. "
               "Esprili ve kısa bir kaçamak cevap ver.")

    anahtar = (cid, user.id)
    h = gecmis.setdefault(anahtar, [])
    h.append({"role": "user", "content": metin})

    yanit = await asyncio.to_thread(sor, h[-20:], ek, arama_gerek(metin))
    if not yanit:
        yanit = "Bir saniye, servisler yoğun — tekrar dene 🙏"
    else:
        h.append({"role": "assistant", "content": yanit})
    gecmis[anahtar] = h[-40:]
    await msg.reply_text(yanit)

async def fiyat_komut(update, ctx):
    msg = update.effective_message
    if not ctx.args:
        await msg.reply_text("Örnek: /fiyat btc")
        return
    if not await fiyat_gonder(update, ctx, " ".join(ctx.args)[:30]):
        await msg.reply_text("Bu tokeni bulamadım.")

async def sifirla(update, ctx):
    chat = update.effective_chat
    if chat.type != "private" and not await yetkili_mi(ctx, chat.id, update.effective_user.id):
        return
    for k in [k for k in list(gecmis.keys()) if (isinstance(k, tuple) and k[0] == chat.id) or k == chat.id]:
        gecmis.pop(k, None)
    await update.effective_message.reply_text("Hafıza sıfırlandı.")

async def hata(update, ctx):
    log.warning(f"Hata: {ctx.error}")


# ===================== EK KOMUTLAR (slowmode, stats, giveaway...) =====================

def _liste_uid(cid, anahtar):
    return set(str(x) for x in durum.setdefault(anahtar, {}).setdefault(str(cid), []))

def _liste_ekle(cid, anahtar, uid):
    L = durum.setdefault(anahtar, {}).setdefault(str(cid), [])
    s = str(uid)
    if s not in L:
        L.append(s)
        durum_kaydet()

def _liste_sil(cid, anahtar, uid):
    L = durum.setdefault(anahtar, {}).setdefault(str(cid), [])
    s = str(uid)
    if s in L:
        L.remove(s)
        durum_kaydet()
        return True
    return False

def gece_modu_aktif(cid):
    bas, bit = cget(cid, "night_bas"), cget(cid, "night_bit")
    if bas is None or bit is None:
        return False
    try:
        bas, bit = int(bas), int(bit)
    except Exception:
        return False
    saat = datetime.now(TR).hour
    if bas <= bit:
        return bas <= saat < bit
    return saat >= bas or saat < bit

async def gas_bilgi():
    try:
        r = requests.get("https://api.etherscan.io/api?module=gastracker&action=gasoracle", timeout=8)
        d = r.json().get("result") or {}
        if d.get("ProposeGasPrice"):
            return (f"⛽ Ethereum Gas\n"
                    f"🐢 Yavaş: {d.get('SafeGasPrice')} gwei\n"
                    f"🚗 Orta: {d.get('ProposeGasPrice')} gwei\n"
                    f"🚀 Hızlı: {d.get('FastGasPrice')} gwei")
    except Exception as e:
        log.warning(f"Gas API: {e}")
    return "⛽ Gas bilgisi alınamadı."

def ca_kontrol(metin):
    m = re.search(r"\b(0x[a-fA-F0-9]{40})\b", metin)
    if not m:
        return None
    ad = m.group(1)
    ok = len(ad) == 42
    return f"{'✅' if ok else '❌'} Contract: <code>{ad}</code>\nUzunluk: {len(ad)} (42 olmalı)"

def scam_link_skor(metin):
    k = kucult(metin)
    skor = 0
    notlar = []
    if re.search(r"t\.me/\+", k) or "joinchat" in k:
        skor += 2; notlar.append("davet linki")
    if any(x in k for x in ("airdrop", "claim", "connect wallet", "seed", "private key", "cüzdan bağla")):
        skor += 3; notlar.append("şüpheli kelime")
    if re.search(r"https?://\S+", k) and "yenibirairdrops" not in k:
        skor += 1; notlar.append("harici link")
    if skor >= 4:
        seviye = "🔴 Yüksek risk"
    elif skor >= 2:
        seviye = "🟡 Orta risk"
    else:
        seviye = "🟢 Düşük risk"
    return f"🔍 Scam kontrol\n{seviye} (skor {skor})\n" + (", ".join(notlar) if notlar else "Belirgin kırmızı bayrak yok")

async def schedule_dongusu(app):
    while True:
        await asyncio.sleep(30)
        try:
            now = time.time()
            kalan = []
            for item in list(durum.get("schedule") or []):
                if item.get("zaman", 0) <= now:
                    try:
                        await app.bot.send_message(int(item["cid"]), item["metin"])
                    except Exception as e:
                        log.warning(f"Schedule hata: {e}")
                    if item.get("tekrar"):
                        item["zaman"] = now + int(item["tekrar"])
                        kalan.append(item)
                else:
                    kalan.append(item)
            durum["schedule"] = kalan
            durum_kaydet()
        except Exception as e:
            log.warning(f"Schedule döngü: {e}")

async def ekstra_komut(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not msg.text or not user:
        return
    cid = chat.id
    p = msg.text.split(None, 1)
    ad = p[0][1:].split("@")[0].lower()
    arg = p[1].strip() if len(p) > 1 else ""
    ozel = chat.type == "private"
    yanit = msg.reply_to_message

    # --- herkes ---
    if ad in ("stats", "istatistik"):
        if ozel:
            await msg.reply_text("Grupta kullan.")
            return
        u = uyeler.get(str(cid), {})
        top = sorted(u.values(), key=lambda x: x.get("mesaj", 0), reverse=True)[:5]
        satir = [f"📊 İstatistik\nÜye kayıt: {len(u)}\nAktif kilit: {', '.join(cget(cid,'kilit') or []) or 'yok'}",
                 f"Slowmode: {cget(cid,'slowmode')} sn | Newbies: {cget(cid,'newbies_dk')} dk",
                 f"Flood: {cget(cid,'flood')} | AI mod: {'sadece admin' if cget(cid,'ai_mod') else 'herkes'}"]
        if top:
            satir.append("Top 5:")
            for i, x in enumerate(top, 1):
                satir.append(f"{i}. {x.get('ad','?')} — {x.get('mesaj',0)} mesaj")
        await msg.reply_text("\n".join(satir))
        return

    if ad == "active":
        if ozel:
            return
        gun = int(arg) if arg.isdigit() else 7
        sinir = time.time() - gun * 86400
        # uyeler has ilk date string - approximate by mesaj count
        u = uyeler.get(str(cid), {})
        aktif = [x for x in u.values() if x.get("mesaj", 0) > 0]
        aktif.sort(key=lambda x: x.get("mesaj", 0), reverse=True)
        satir = [f"🟢 Son aktivite (kayıtlı, top 15) — {gun}g referans:"]
        for x in aktif[:15]:
            satir.append(f"• {x.get('ad','?')} ({x.get('mesaj',0)} msg)")
        await msg.reply_text("\n".join(satir) if len(satir) > 1 else "Veri yok.")
        return

    if ad == "inactive":
        if ozel:
            return
        gun = int(arg) if arg.isdigit() else 30
        u = uyeler.get(str(cid), {})
        az = [x for x in u.values() if x.get("mesaj", 0) <= 2]
        satir = [f"😴 Az aktif / pasif (≤2 mesaj), örnek {gun}g bakışı:"]
        for x in az[:20]:
            satir.append(f"• {x.get('ad','?')}")
        await msg.reply_text("\n".join(satir) if len(satir) > 1 else "Yok.")
        return

    if ad == "gas":
        await msg.reply_text(await asyncio.to_thread(gas_bilgi))
        return

    if ad == "ca":
        met = arg or ((yanit.text or yanit.caption or "") if yanit else "")
        r = ca_kontrol(met)
        await msg.reply_text(r or "0x ile başlayan 40 hex karakterli adres yapıştır.", parse_mode="HTML")
        return

    if ad == "scam":
        met = arg or ((yanit.text or yanit.caption or "") if yanit else "")
        if not met:
            await msg.reply_text("Link veya metin ver / yanıtlа.")
            return
        await msg.reply_text(scam_link_skor(met))
        return

    if ad in ("talimatlar", "talimat_liste"):
        tl = durum.get("talimat") or []
        await msg.reply_text(("📋 Talimatlar:\n" + "\n".join(f"{i}. {x['t']}" for i, x in enumerate(tl, 1))) if tl else "Talimat yok.")
        return

    if ad in ("ozet", "özet"):
        if not yanit:
            await msg.reply_text("Özetlenecek mesaja yanıt ver (veya /ozet ile uzun metin).")
            return
        met = (yanit.text or yanit.caption or "")[:3000]
        s = await asyncio.to_thread(sor, [{"role": "user", "content": "Şu metni Türkçe 2-3 cümlede özetle:\n" + met}])
        await msg.reply_text(s or "Özetleyemedim.")
        return

    if ad in ("cevir", "çevir", "translate"):
        if not yanit and not arg:
            await msg.reply_text("Yanıtla veya /cevir en metin")
            return
        dil = "English"
        met = arg
        if arg.split(None, 1)[0].lower() in ("en", "tr", "ru", "de", "fr"):
            par = arg.split(None, 1)
            dil = {"en": "English", "tr": "Turkish", "ru": "Russian", "de": "German", "fr": "French"}[par[0].lower()]
            met = par[1] if len(par) > 1 else ""
        if not met and yanit:
            met = yanit.text or yanit.caption or ""
        s = await asyncio.to_thread(sor, [{"role": "user", "content": f"Translate to {dil}. Only translation:\n{met[:2500]}"}])
        await msg.reply_text(s or "Çeviremedim.")
        return

    if ad == "pinlast":
        if ozel or not await yetkili_mi(ctx, cid, user.id):
            return
        try:
            # pin most recent arsiv item link message if possible - else error
            kayitlar = durum.get("arsiv", {}).get(str(cid), [])
            if not kayitlar:
                await msg.reply_text("Arşivde duyuru yok.")
                return
            son = kayitlar[-1]
            mid = son.get("id")
            if mid:
                await ctx.bot.pin_chat_message(cid, mid, disable_notification=True)
                r = await msg.reply_text("📌 Son duyuru sabitlendi.")
                try:
                    task = asyncio.create_task(mesaj_sil_sn(ctx, cid, r.message_id, 5))
                    gorevler.add(task)
                    task.add_done_callback(gorevler.discard)
                except Exception:
                    pass
            else:
                await msg.reply_text("Mesaj ID yok.")
        except Exception as e:
            await msg.reply_text(f"Sabitleyemedim: {e}")
        return

    if ad == "poll":
        if ozel or not await yetkili_mi(ctx, cid, user.id):
            return
        # /poll Soru | A | B | C
        par = [x.strip() for x in arg.split("|") if x.strip()]
        if len(par) < 3:
            await msg.reply_text("Örnek: /poll Hangi zincir? | ETH | SOL | BSC")
            return
        try:
            await ctx.bot.send_poll(cid, par[0][:300], par[1:11], is_anonymous=False)
        except Exception as e:
            await msg.reply_text(f"Anket hatası: {e}")
        return

    if ad == "giveaway":
        if ozel or not await yetkili_mi(ctx, cid, user.id):
            return
        odul = arg or "Ödül"
        kl = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 Katıl", callback_data=f"gw:{cid}")]])
        m = await msg.reply_text(f"🎁 Çekiliş: {odul}\nKatılmak için butona bas!", reply_markup=kl)
        durum.setdefault("giveaway", {})[str(m.message_id)] = {"cid": cid, "odul": odul, "katilan": []}
        durum_kaydet()
        return

    if ad == "çekilişbitir" or ad == "giveawayend":
        if ozel or not await yetkili_mi(ctx, cid, user.id):
            return
        if not yanit:
            await msg.reply_text("Çekiliş mesajına yanıt ver.")
            return
        g = durum.get("giveaway", {}).get(str(yanit.message_id))
        if not g or not g.get("katilan"):
            await msg.reply_text("Katılan yok veya çekiliş bulunamadı.")
            return
        kazanan = random.choice(g["katilan"])
        await msg.reply_text(f"🏆 Kazanan: <a href=\"tg://user?id={kazanan}\">{kazanan}</a>\nÖdül: {html.escape(g.get('odul',''))}", parse_mode="HTML")
        return

    # --- admin only below ---
    if not ozel and not await yetkili_mi(ctx, cid, user.id):
        if ad in ("slowmode", "nightmode", "newbies", "approved", "unapproved", "blacklist", "whitelist",
                  "schedule", "repeat", "ai_mod"):
            return
        return

    if ozel and not sahip_mi(user):
        return

    if ad == "slowmode":
        sn = int(arg) if arg.isdigit() else 0
        sn = max(0, min(sn, 600))
        grup_ayari_uygula(cid, "slowmode", sn, ozel)
        await msg.reply_text(f"⏱ Slowmode: {sn} sn" + (" (kapalı)" if sn == 0 else ""))
        return

    if ad == "nightmode":
        # /nightmode 0-8  veya /nightmode off
        if kucult(arg) in ("off", "kapat", "0"):
            grup_ayari_uygula(cid, "night_bas", None, ozel)
            grup_ayari_uygula(cid, "night_bit", None, ozel)
            await msg.reply_text("🌙 Gece modu kapatıldı.")
            return
        m = re.match(r"(\d{1,2})\s*[-–]\s*(\d{1,2})", arg)
        if not m:
            await msg.reply_text("Örnek: /nightmode 0-8  (00:00-08:00 sadece admin)")
            return
        grup_ayari_uygula(cid, "night_bas", int(m.group(1)) % 24, ozel)
        grup_ayari_uygula(cid, "night_bit", int(m.group(2)) % 24, ozel)
        await msg.reply_text(f"🌙 Gece modu: {m.group(1)}:00 – {m.group(2)}:00 (sadece admin)")
        return

    if ad == "newbies":
        dk = int(arg) if arg.isdigit() else 0
        dk = max(0, min(dk, 1440))
        grup_ayari_uygula(cid, "newbies_dk", dk, ozel)
        await msg.reply_text(f"🆕 Yeni üyeler {dk} dk susturulacak." if dk else "🆕 Newbies susturma kapalı.")
        return

    if ad == "ai_mod":
        ac = kucult(arg) in ("on", "1", "ac", "aç", "admin")
        grup_ayari_uygula(cid, "ai_mod", ac, ozel)
        await msg.reply_text("🤖 AI sadece admin/sahibe cevap verir." if ac else "🤖 AI herkese açık.")
        return

    if ad in ("approved", "unapproved", "blacklist", "whitelist"):
        hid = None
        if yanit and yanit.from_user:
            hid = yanit.from_user.id
        elif arg.startswith("@"):
            for uid, u in uyeler.get(str(cid if not ozel else cid), {}).items():
                if (u.get("kullanici") or "").lower() == arg[1:].lower():
                    hid = int(uid)
                    break
        elif arg.lstrip("-").isdigit():
            hid = int(arg)
        if not hid and ad not in ("approved", "blacklist", "whitelist"):
            pass
        if ad == "approved" and hid:
            _liste_ekle(cid, "approved", hid)
            await msg.reply_text(f"✅ Onaylandı: {hid} (link atabilir)")
        elif ad == "unapproved" and hid:
            _liste_sil(cid, "approved", hid)
            await msg.reply_text(f"Onay kaldırıldı: {hid}")
        elif ad == "blacklist" and hid:
            _liste_ekle(cid, "blacklist", hid)
            try:
                if not ozel:
                    await ctx.bot.ban_chat_member(cid, hid)
            except Exception:
                pass
            await msg.reply_text(f"⛔ Blacklist + ban: {hid}")
        elif ad == "whitelist" and hid:
            _liste_ekle(cid, "whitelist", hid)
            await msg.reply_text(f"✅ Whitelist: {hid}")
        else:
            await msg.reply_text("Yanıt ver veya @user / id yaz.")
        return

    if ad == "schedule":
        # /schedule 18:30 metin
        m = re.match(r"(\d{1,2}):(\d{2})\s+(.+)", arg, re.S)
        if not m:
            await msg.reply_text("Örnek: /schedule 18:30 Duyuru metni")
            return
        hh, mm, met = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        now = datetime.now(TR)
        hedef = now.replace(hour=hh % 24, minute=mm % 60, second=0, microsecond=0)
        if hedef <= now:
            hedef += timedelta(days=1)
        hedef_cid = cid if not ozel else next((int(x) for x in uyeler if int(x) < 0), None)
        if not hedef_cid:
            await msg.reply_text("Grup bulunamadı.")
            return
        durum.setdefault("schedule", []).append({"cid": hedef_cid, "zaman": hedef.timestamp(), "metin": met, "tekrar": None})
        durum_kaydet()
        await msg.reply_text(f"🗓️ Planlandı: {hedef.strftime('%d.%m %H:%M')}")
        return

    if ad == "repeat":
        # /repeat 3h metin
        m = re.match(r"(\d+)\s*(h|sa|saat|m|dk)?\s+(.+)", arg, re.S | re.I)
        if not m:
            await msg.reply_text("Örnek: /repeat 3h Her 3 saatte bir duyuru")
            return
        n, birim, met = int(m.group(1)), (m.group(2) or "h").lower(), m.group(3).strip()
        sn = n * (3600 if birim in ("h", "sa", "saat") else 60)
        sn = max(600, min(sn, 86400 * 7))
        hedef_cid = cid if not ozel else next((int(x) for x in uyeler if int(x) < 0), None)
        if not hedef_cid:
            await msg.reply_text("Grup yok.")
            return
        durum.setdefault("schedule", []).append({"cid": hedef_cid, "zaman": time.time() + sn, "metin": met, "tekrar": sn})
        durum_kaydet()
        await msg.reply_text(f"🔁 Her {sn // 60} dk tekrarlanacak.")
        return

async def giveaway_buton(update, ctx):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("gw:"):
        return
    try:
        await q.answer("Katıldın! 🎉")
    except Exception:
        pass
    mid = str(q.message.message_id) if q.message else ""
    g = durum.get("giveaway", {}).get(mid)
    if not g:
        return
    uid = str(q.from_user.id)
    if uid not in g.get("katilan", []):
        g.setdefault("katilan", []).append(uid)
        durum_kaydet()



# ===================== BUTONLU PANEL (/panel) =====================

def panel_klavye(cid):
    def on(k):
        return "✅" if cget(cid, k) else "❌"
    kilit = cget(cid, "kilit") or []
    link_kilit = "🔒" if "link" in kilit else "🔓"
    sm = cget(cid, "slowmode") or 0
    rows = [
        [InlineKeyboardButton(f"{on('ai')} AI", callback_data=f"pn:{cid}:tog:ai"),
         InlineKeyboardButton(f"{on('ipucu')} İpucu", callback_data=f"pn:{cid}:tog:ipucu")],
        [InlineKeyboardButton(f"{on('hosgeldin')} Karşılama", callback_data=f"pn:{cid}:tog:hosgeldin"),
         InlineKeyboardButton(f"{on('captcha')} Captcha", callback_data=f"pn:{cid}:tog:captcha")],
        [InlineKeyboardButton(f"{link_kilit} Link kilidi", callback_data=f"pn:{cid}:link"),
         InlineKeyboardButton(f"{on('ai_mod')} AI sadece admin", callback_data=f"pn:{cid}:tog:ai_mod")],
        [InlineKeyboardButton(f"⏱ Slowmode: {sm}s", callback_data=f"pn:{cid}:slow"),
         InlineKeyboardButton(f"Flood: {cget(cid,'flood')}", callback_data=f"pn:{cid}:flood")],
        [InlineKeyboardButton(f"Warn limit: {cget(cid,'warn_limit')}", callback_data=f"pn:{cid}:wlim"),
         InlineKeyboardButton(f"Newbies: {cget(cid,'newbies_dk')}dk", callback_data=f"pn:{cid}:newb")],
        [InlineKeyboardButton("📊 Stats", callback_data=f"pn:{cid}:stats"),
         InlineKeyboardButton("📋 Kilitler", callback_data=f"pn:{cid}:locks")],
        [InlineKeyboardButton("📢 Bugünkü duyurular", callback_data=f"pn:{cid}:duy"),
         InlineKeyboardButton("🔄 Yenile", callback_data=f"pn:{cid}:ref")],
        [InlineKeyboardButton("❌ Kapat", callback_data=f"pn:{cid}:close")],
    ]
    return InlineKeyboardMarkup(rows)

def panel_metin(cid, baslik=""):
    try:
        # baslik optional
        pass
    except Exception:
        pass
    kilit = ", ".join(cget(cid, "kilit") or []) or "yok"
    return (
        f"⚙️ <b>Kontrol Paneli</b>\n"
        f"AI: {'açık' if cget(cid,'ai') else 'kapalı'} | "
        f"İpucu: {'açık' if cget(cid,'ipucu') else 'kapalı'}\n"
        f"Karşılama: {'açık' if cget(cid,'hosgeldin') else 'kapalı'} | "
        f"Captcha: {'açık' if cget(cid,'captcha') else 'kapalı'}\n"
        f"Link kilidi: {'açık' if 'link' in (cget(cid,'kilit') or []) else 'kapalı'}\n"
        f"Slowmode: {cget(cid,'slowmode')} sn | Flood: {cget(cid,'flood')}\n"
        f"Warn: {cget(cid,'warn_limit')} → {cget(cid,'warn_eylem')} | "
        f"Newbies: {cget(cid,'newbies_dk')} dk\n"
        f"Kilitler: {kilit}\n\n"
        f"Butonlarla aç/kapa. AI sohbeti aynı şekilde çalışır."
    )

async def panel_komut(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not user:
        return
    cid = chat.id
    if chat.type == "private":
        # özelde: bilinen ilk grubu veya tüm gruplar için global
        gruplar = [int(x) for x in uyeler.keys() if int(x) < 0]
        if not gruplar:
            await msg.reply_text("Önce botu gruba ekle.")
            return
        if not sahip_mi(user):
            await msg.reply_text("Sadece sahip özelden panel açabilir.")
            return
        cid = gruplar[0]
    elif not await yetkili_mi(ctx, cid, user.id):
        await msg.reply_text("Sadece yönetici / sahip.")
        return
    await msg.reply_text(panel_metin(cid), parse_mode="HTML", reply_markup=panel_klavye(cid))

async def panel_buton(update, ctx):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("pn:"):
        return
    user = q.from_user
    try:
        _, scid, islem, *rest = q.data.split(":")
        cid = int(scid)
    except Exception:
        await q.answer("Hatalı veri", show_alert=True)
        return
    # yetki
    if not sahip_mi(user):
        try:
            if not await yetkili_mi(ctx, cid, user.id):
                await q.answer("Yetkin yok", show_alert=True)
                return
        except Exception:
            await q.answer("Yetkin yok", show_alert=True)
            return

    if islem == "close":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer()
        return

    if islem == "tog" and rest:
        key = rest[0]
        if key not in ("ai", "ipucu", "hosgeldin", "captcha", "ai_mod", "adminizin"):
            await q.answer("?")
            return
        yeni = not bool(cget(cid, key))
        cset(cid, key, yeni)
        await q.answer(f"{key}: {'açık' if yeni else 'kapalı'}")
    elif islem == "link":
        k = list(cget(cid, "kilit") or [])
        if "link" in k:
            k.remove("link")
            await q.answer("Link serbest")
        else:
            k.append("link")
            await q.answer("Link kilitli")
        cset(cid, "kilit", k)
    elif islem == "slow":
        sm = int(cget(cid, "slowmode") or 0)
        # cycle 0 -> 5 -> 10 -> 30 -> 60 -> 0
        dongu = [0, 5, 10, 30, 60]
        try:
            i = dongu.index(sm)
            sm = dongu[(i + 1) % len(dongu)]
        except ValueError:
            sm = 5
        cset(cid, "slowmode", sm)
        await q.answer(f"Slowmode: {sm}s")
    elif islem == "flood":
        f = int(cget(cid, "flood") or 0)
        dongu = [0, 3, 6, 10, 15]
        try:
            i = dongu.index(f)
            f = dongu[(i + 1) % len(dongu)]
        except ValueError:
            f = 6
        cset(cid, "flood", f)
        await q.answer(f"Flood: {f}")
    elif islem == "wlim":
        w = int(cget(cid, "warn_limit") or 3)
        w = 3 if w >= 7 else w + 1
        cset(cid, "warn_limit", w)
        await q.answer(f"Warn limit: {w}")
    elif islem == "newb":
        n = int(cget(cid, "newbies_dk") or 0)
        dongu = [0, 5, 15, 30, 60]
        try:
            i = dongu.index(n)
            n = dongu[(i + 1) % len(dongu)]
        except ValueError:
            n = 15
        cset(cid, "newbies_dk", n)
        await q.answer(f"Newbies: {n} dk")
    elif islem == "stats":
        u = uyeler.get(str(cid), {})
        await q.answer(f"Kayıtlı üye: {len(u)}", show_alert=True)
        return
    elif islem == "locks":
        k = cget(cid, "kilit") or []
        await q.answer(", ".join(k) if k else "Kilit yok", show_alert=True)
        return
    elif islem == "duy":
        kayitlar = durum.get("arsiv", {}).get(str(cid), [])
        await q.answer(f"Bugün/arsiv: {len(kayitlar)} kayıt", show_alert=True)
        return
    elif islem == "ref":
        await q.answer("Yenilendi")
    else:
        await q.answer()
        return

    try:
        await q.message.edit_text(panel_metin(cid), parse_mode="HTML", reply_markup=panel_klavye(cid))
    except Exception:
        pass


mod_komut = komut_silici(mod_komut)
yonet_komut = komut_silici(yonet_komut)
ayar_komut = komut_silici(ayar_komut)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(baslat).build()
app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
app.add_handler(CommandHandler("sahip", sahip_komut))
app.add_handler(CommandHandler("durum", durum_komut))
app.add_handler(CommandHandler("duyuru", duyuru_komut))
app.add_handler(CommandHandler(["ai_ac", "ai_kapat", "ipucu_ac", "ipucu_kapat", "hosgeldin_ac", "hosgeldin_kapat",
                                "captcha_ac", "captcha_kapat", "adminizin_ac", "adminizin_kapat"], ayar_komut))
app.add_handler(CommandHandler(["gunluk", "haftalik", "aylik", "duyurular"], liste_komut))
app.add_handler(CommandHandler(list(ALIAS.keys()), mod_komut))
app.add_handler(CommandHandler(["flood", "setflood", "uyarilimit", "uyarieylem", "kuralayarla", "kuralsil",
                                "hosgeldinmetni", "hosgeldinsifirla", "setlog", "unsetlog", "kaydet", "notsil", "filtre", "filtresil",
                                "kara", "karasil", "karalar", "kilit", "kilitac", "lock", "unlock", "locks", "unlocks", "kilitler", "ayarlar", "del", "sil", "purge",
                                "pin", "sabitle", "unpin", "sabitkaldir", "duyuruekle", "promote", "demote", "adminlist", "admins", "yoneticiler", "yukselt", "dusur", "setwelcome", "welcome", "resetwelcome", "setrules", "resetrules", "warnlimit", "warntime", "save"], yonet_komut))
app.add_handler(CommandHandler(["yardim", "help", "start", "kurallar", "rules", "not", "get", "notlar", "notes", "filtreler", "filters",
                                "kilitler", "id", "info", "bilgi", "top", "istatistik", "rapor", "report", "adminlist"], genel_komut))
app.add_handler(CommandHandler("sifirla", sifirla))
app.add_handler(CommandHandler("fiyat", fiyat_komut))
app.add_handler(CommandHandler("ipucu", ipucu_komut))
app.add_handler(CommandHandler([
    "stats", "istatistik", "active", "inactive", "gas", "ca", "scam",
    "talimatlar", "ozet", "cevir", "translate", "pinlast",
    "poll", "giveaway", "giveawayend",
    "slowmode", "nightmode", "newbies", "ai_mod",
    "approved", "unapproved", "blacklist", "whitelist",
    "schedule", "repeat",
], ekstra_komut))
app.add_handler(CommandHandler("panel", panel_komut))
app.add_handler(CallbackQueryHandler(panel_buton, pattern=r"^pn:"))
app.add_handler(CallbackQueryHandler(giveaway_buton, pattern=r"^gw:"))


app.add_handler(CallbackQueryHandler(captcha_buton, pattern=r"^cap:"))
app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, sabitlendi))
async def servis_temizle(update, ctx):
    msg = update.effective_message
    if msg:
        try:
            await msg.delete()
        except Exception:
            pass
app.add_handler(MessageHandler(
    filters.StatusUpdate.NEW_CHAT_TITLE | filters.StatusUpdate.NEW_CHAT_PHOTO |
    filters.StatusUpdate.DELETE_CHAT_PHOTO,
    servis_temizle
))

app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, hosgeldin))
app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, ayrildi))
app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.UpdateType.MESSAGE, mesaj))
app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE, kilit_kontrol), group=1)
app.add_error_handler(hata)
log.info("Bot başlıyor...")
app.run_polling()
