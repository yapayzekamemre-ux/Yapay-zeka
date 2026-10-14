import asyncio, html, json, logging, os, random, re, threading, time, requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import deque
from datetime import datetime, timedelta, timezone
from groq import Groq
from google import genai
from google.genai import types
from telegram import ChatPermissions, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeAllChatAdministrators, Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
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

def _self_ping():
    """Render free: DIS URL'e ping (localhost uyandirmaz). 3 dk'da bir."""
    import urllib.request
    port = int(os.environ.get("PORT", 8080))
    time.sleep(15)  # server ayaga kalksin
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
        # ayni surecte local de dene (zararsiz)
        urls.append(f"http://127.0.0.1:{port}/")
        for u in urls:
            try:
                urllib.request.urlopen(u, timeout=15)
                logging.getLogger("bot").info(f"keep-alive OK: {u}")
                break
            except Exception as e:
                logging.getLogger("bot").warning(f"keep-alive fail {u}: {e}")
        time.sleep(180)  # 3 dakika

threading.Thread(target=keep_alive, daemon=True).start()
threading.Thread(target=_self_ping, daemon=True).start()

SAHIP_KULLANICI = (os.environ.get("SAHIP_KULLANICI") or os.environ.get("SAHIP_USERNAME") or "").lower().lstrip("@")
TIP_ARALIK = 3600
TR = timezone(timedelta(hours=3))
NUMARALAR = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
LISTE_KISA = {"günlük", "gunluk", "haftalık", "haftalik", "aylık", "aylik", "bugünkü", "bugunku",
              "duyuru", "duyurular", "duyuruları", "duyurulari"}

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

VARS = {
    "ai": True, "ipucu": False, "hosgeldin": False, "captcha": False, "adminizin": True,
    "kilit": ["link"], "flood": 6, "warn_limit": 3, "warn_eylem": "mute",
    "hosgeldin_metin": (
        "⛔ {ad} Hoşgeldiniz\n"
        "⚠️ Katıldığı andan itibaren 15 dakika boyunca mesaj gönderemez\n"
        "✅ 15 dakika sonra sohbeti başlatabilirsiniz"
    ),
    "kurallar": None, "log_kanal": None, "duyuru_kanal": None,
    "duyuru_aralik_saat": 3, "slowmode": 0, "night_bas": None, "night_bit": None,
    "newbies_dk": 15, "ai_mod": False,
        "cleanservice": True,   # katıl/ayrıl sistem mesajı sil
    "cleancommand": True,   # /komut mesajlarını sil
    "reports": True,        # /report /rapor
    "privaterules": False,
    "hosgeldin_sil_sn": 15,
    "link_izinli": [],          # serbest domain/url/kelime listesi
    "antiraid": False,
    "antiraid_limit": 5,        # X sn içinde bu kadar katılım = kilit
    "antiraid_sn": 30,
    "blocklist_mode": "mute",   # mute|kick|ban|sil
    "report_log_only": False,   # rapor sadece log kanalına
    "hosgeldin_dil": "tr",
    "kanal_yorum": False,
    "otopin": False,  # kanal postlarını otomatik pinleme KAPALI
  # sadece /kanalyorum on ile aç; her posta yorum yok
}

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
    """Sahibin özelden verdiği ayar: global + tüm gruplar (ayar + uyeler)."""
    durum["ayar"].setdefault(GLOBAL_AYAR, {})[k] = v
    idler = set()
    for gcid in list(uyeler.keys()):
        try:
            if int(gcid) < 0:
                idler.add(str(gcid))
        except Exception:
            pass
    for gcid in list(durum.get("ayar", {}).keys()):
        if gcid == GLOBAL_AYAR:
            continue
        try:
            if int(gcid) < 0:
                idler.add(str(gcid))
        except Exception:
            pass
    for gcid in idler:
        durum["ayar"].setdefault(gcid, {})[k] = v
    durum_kaydet()
    log.info(f"Global ayar: {k}={v} → {len(idler)} grup")

def grup_ayari_uygula(cid, k, v, ozel):
    if ozel:
        cset_global(k, v)
    else:
        cset(cid, k, v)

def tum_kilitleri_ac(ozel=True, cid=None):
    """Link kilitlerini ac."""
    if ozel or cid is None:
        cset_global("kilit", [])
    else:
        cset(cid, "kilit", [])

async def log_gonder(ctx, kaynak_cid, metin):
    """Giren/çıkan ve işlemleri log veya duyuru kanalına yaz."""
    kid = cget(kaynak_cid, "log_kanal") or cget(kaynak_cid, "duyuru_kanal")
    if not kid:
        # global ayardan dene
        kid = cget(GLOBAL_AYAR, "log_kanal") or cget(GLOBAL_AYAR, "duyuru_kanal")
    if not kid:
        return
    try:
        hedef = int(str(kid)) if str(kid).lstrip("-").isdigit() else kid
        if isinstance(hedef, str):
            hedef = hedef if hedef.startswith("@") else f"@{hedef.lstrip('@')}"
        await ctx.bot.send_message(hedef, metin, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Log/duyuru kanalına yazılamadı ({kid}): {e}")

SAHIP_KOD = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
if not durum["sahip"]:
    print("\n=========================================")
    print(" Sahip yok: ozelden /start veya /sahip yaz.")
    if SAHIP_KULLANICI:
        print(" @" + SAHIP_KULLANICI + " yazinca da otomatik sahip olur.")
    print(" Yedek kod: " + SAHIP_KOD + "  (/sahip " + SAHIP_KOD + ")")
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
                    "max_tokens": 180,
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
            "max_tokens": 180,
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

def deepseek_sor(m, sistem):
    """DeepSeek API — DEEPSEEK_KEY (platform.deepseek.com)."""
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

SAGLAYICILAR = [("Groq", groq_sor), ("Gemini", gemini_sor)]
if DEEPSEEK_KEY:
    SAGLAYICILAR.append(("DeepSeek", deepseek_sor))
if CEREBRAS_KEY:
    SAGLAYICILAR.append(("Cerebras", cerebras_sor))
if OPENROUTER_KEY:
    SAGLAYICILAR.append(("OpenRouter", openrouter_sor))
if MISTRAL_KEY:
    SAGLAYICILAR.append(("Mistral", mistral_sor))

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
    "action alani her zaman 'yok' olmali. Ban/mute/kick YAPMA. "
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
    Örn: https://t.me/bağlı duyuru kanalı/123
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
    # Önce kanal post linki (bağlı duyuru kanalı), yoksa grup mesajı
    link = kanal_post_linki(m) or mesaj_linki(chat, mid)
    return {"id": mid, "metin": metin[:1500], "link": link, "tarih": tarih}

async def baslat(app):
    try:
        await app.bot.delete_my_commands()
        await app.bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
        await app.bot.delete_my_commands(scope=BotCommandScopeAllGroupChats())
        await app.bot.delete_my_commands(scope=BotCommandScopeAllChatAdministrators())
    except Exception:
        pass
    try:
        durum["ayar"].setdefault(GLOBAL_AYAR, {})
        durum["ayar"][GLOBAL_AYAR].setdefault("otopin", False)
        durum["ayar"][GLOBAL_AYAR].setdefault("adminizin", True)
        durum_kaydet()
    except Exception:
        pass
    me = await app.bot.get_me()
    log.info(f"Bot hazir: @{me.username} (sadece AI, komut yok)")


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

def _linkleri_topla(msg, metin):
    adaylar = list(LINK_RE.findall(kucult(metin or "")))
    if msg:
        for e in (getattr(msg, "entities", None) or []) + (getattr(msg, "caption_entities", None) or []):
            try:
                if getattr(e, "type", None) == "text_link" and getattr(e, "url", None):
                    adaylar.append(e.url.lower())
                elif getattr(e, "type", None) == "url":
                    if msg.text:
                        adaylar.append(msg.parse_entity(e).lower())
                    elif msg.caption:
                        adaylar.append(msg.parse_caption_entity(e).lower())
            except Exception:
                pass
    return adaylar

def _normalize_link(a):
    a2 = (a or "").lower().strip()
    a2 = a2.replace("https://", "").replace("http://", "").rstrip("/")
    return a2

def _izin_listesi(cid):
    """duyuru_kanal + link_izinli + sabit domainler"""
    out = list(IZINLI)
    duy = cget(cid, "duyuru_kanal")
    if duy:
        s = str(duy).strip().lstrip("@").lower()
        if s:
            out.append(s)
            out.append(f"t.me/{s}")
            out.append(f"telegram.me/{s}")
    for x in (cget(cid, "link_izinli") or []):
        z = _normalize_link(str(x).lstrip("@"))
        if z:
            out.append(z)
            if not z.startswith("t.me/") and " " not in z and "." not in z:
                out.append(f"t.me/{z}")
    # global
    for x in (cget(GLOBAL_AYAR, "link_izinli") or []):
        z = _normalize_link(str(x).lstrip("@"))
        if z:
            out.append(z)
    gd = cget(GLOBAL_AYAR, "duyuru_kanal")
    if gd:
        s = str(gd).strip().lstrip("@").lower()
        out.append(s)
        out.append(f"t.me/{s}")
    return out

def link_izinli_mi(cid, metin, msg=None):
    izinler = _izin_listesi(cid)
    if not izinler:
        return False
    for a in _linkleri_topla(msg, metin):
        a2 = _normalize_link(a)
        for z in izinler:
            if z and z in a2:
                return True
    # metin içinde kanal adı geçiyorsa (invite link vs)
    ham = kucult(metin or "")
    for z in izinler:
        if z and len(z) > 2 and z in ham:
            return True
    return False

def link_var(msg, metin, cid=None):
    """Yasaklanması gereken link var mı? Serbest listedekiler sayılmaz."""
    adaylar = _linkleri_topla(msg, metin)
    if not adaylar:
        return False
    izinler = _izin_listesi(cid) if cid is not None else list(IZINLI)
    for a in adaylar:
        a2 = _normalize_link(a)
        if any(z and z in a2 for z in izinler):
            continue
        return True  # en az bir serbest olmayan link
    return False

def spam_mi(chat_id, user_id, n):
    dq = zamanlar.get((chat_id, user_id))
    if dq is None or dq.maxlen != n:
        dq = zamanlar[(chat_id, user_id)] = deque(maxlen=n)
    now = time.time()
    dq.append(now)
    return len(dq) == n and now - dq[0] < 10



def bagli_kanal_mi(cid, ch):
    """Mesajın kaynağı sahibin bağladığı duyuru kanalı mı?"""
    if ch is None:
        return False
    izinli = cget(cid, "duyuru_kanal")
    un = (getattr(ch, "username", None) or "").lower()
    title = kucult(getattr(ch, "title", None) or "")
    kid = getattr(ch, "id", None)
    if not izinli:
        return False
    s = str(izinli).strip()
    if s.lstrip("-").isdigit() and kid is not None:
        try:
            if int(s) == int(kid):
                return True
        except Exception:
            pass
    z = s.lower().lstrip("@")
    if z and (z == un or z in title.replace(" ", "") or z in title):
        return True
    # link_izinli listesinde kanal adı da olabilir
    for x in (cget(cid, "link_izinli") or []):
        xz = kucult(str(x)).replace("https://", "").replace("http://", "").replace("t.me/", "").lstrip("@")
        if xz and (xz == un or xz in title.replace(" ", "")):
            return True
    return False

def mesaj_bagli_kanal_mi(cid, m):
    for ch in (
        getattr(m, "sender_chat", None),
        getattr(m, "forward_from_chat", None),
        getattr(getattr(m, "forward_origin", None), "chat", None),
    ):
        if bagli_kanal_mi(cid, ch):
            return True
    return False

def hosgeldin_sablon_dil(cid, dil=None):
    """Çok dilli karşılama şablonları."""
    d = (dil or cget(cid, "hosgeldin_dil") or "tr").lower()
    if d == "auto":
        d = "tr"
    sablon = cget(cid, "hosgeldin_metin")
    if sablon and d == "tr":
        return sablon
    paket = {
        "tr": (
            "⛔ {ad} Hoşgeldiniz\n"
            "⚠️ Katıldığı andan itibaren 15 dakika boyunca mesaj gönderemez\n"
            "✅ 15 dakika sonra sohbeti başlatabilirsiniz"
        ),
        "en": (
            "⛔ {ad} Welcome\n"
            "⚠️ You cannot send messages for 15 minutes after joining\n"
            "✅ You can chat after 15 minutes"
        ),
        "ru": (
            "⛔ {ad} Добро пожаловать\n"
            "⚠️ 15 минут нельзя писать сообщения\n"
            "✅ Через 15 минут можно общаться"
        ),
        "ar": (
            "⛔ {ad} أهلاً بك\n"
            "⚠️ لا يمكنك إرسال رسائل لمدة 15 دقيقة\n"
            "✅ يمكنك الدردشة بعد 15 دقيقة"
        ),
    }
    if sablon and d == "tr":
        return sablon
    return paket.get(d) or paket["tr"]

# antiraid sayaç
_raid_sayac = {}

def antiraid_kontrol(cid):
    """Ani katılım: limit aşılırsa True (kilit öner)."""
    if not cget(cid, "antiraid"):
        return False
    lim = int(cget(cid, "antiraid_limit") or 5)
    sn = int(cget(cid, "antiraid_sn") or 30)
    now = time.time()
    q = _raid_sayac.setdefault(cid, [])
    q.append(now)
    _raid_sayac[cid] = [x for x in q if now - x <= sn]
    return len(_raid_sayac[cid]) >= lim


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
        niyet = {"eylem": None}  # komut/niyet kaldirildi
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
            await msg.reply_text("Bunu sadece sahibim yapabilir 😄", do_quote=False)
            return True
        return False

    async def de(s, html_mod=False):
        m = await msg.reply_text(s, parse_mode=("HTML" if html_mod else None), do_quote=False)
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
    if False and eylem in ("hosgeldin_metin", "kural_metin"):  # kaldirildi
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
    if False and eylem in ("ban", "unban", "kick", "mute", "unmute", "warn"):  # kaldirildi
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


def _hosgeldin_debounce(cid, uid, sn=15):
    k = (cid, uid)
    now = time.time()
    if now - _hosgeldin_son.get(k, 0) < sn:
        return False
    _hosgeldin_son[k] = now
    return True

async def hosgeldin_gonder(ctx, cid, u, baslik):
    """Karşılama mesajı — hata yutmaz, mutlaka dener."""
    try:
        if cget(cid, "hosgeldin") is False:
            log.info(f"Karşılama kapalı: {cid}")
            return
        if not _hosgeldin_debounce(cid, u.id):
            return
        sablon = hosgeldin_sablon_dil(cid)
        ad_html = u.mention_html()
        ad_duz = u.full_name or "Üye"
        s = str(sablon)
        for a, b in (
            ("{ad}", ad_html), ("{Ad}", ad_html), ("{isim}", ad_html),
            ("{KullanıcıAdı}", ad_html), ("{kullaniciadi}", ad_html), ("{name}", ad_html),
            ("{grup}", html.escape(baslik or "")), ("{Grup}", html.escape(baslik or "")),
        ):
            s = s.replace(a, b)
        mid = None
        try:
            m = await ctx.bot.send_message(cid, s, parse_mode="HTML", disable_web_page_preview=True)
            mid = m.message_id
        except Exception as e1:
            log.warning(f"Karşılama HTML hata: {e1}")
            s2 = str(sablon)
            for a, b in (
                ("{ad}", ad_duz), ("{Ad}", ad_duz), ("{isim}", ad_duz),
                ("{KullanıcıAdı}", ad_duz), ("{kullaniciadi}", ad_duz), ("{name}", ad_duz),
                ("{grup}", baslik or ""), ("{Grup}", baslik or ""),
            ):
                s2 = s2.replace(a, b)
            m = await ctx.bot.send_message(cid, s2, disable_web_page_preview=True)
            mid = m.message_id
        log.info(f"Karşılama OK: {cid} -> {u.id} {ad_duz}")
        sn = int(cget(cid, "hosgeldin_sil_sn") or 0)
        if mid and sn > 0:
            try:
                task = asyncio.create_task(mesaj_sil_sn(ctx, cid, mid, sn))
                gorevler.add(task)
                task.add_done_callback(gorevler.discard)
            except Exception:
                pass
    except Exception as e:
        log.exception(f"Karşılama kritik hata {cid}: {e}")
        try:
            m = await ctx.bot.send_message(cid, f"⛔ {u.full_name or 'Üye'} Hoşgeldiniz")
            sn = int(cget(cid, "hosgeldin_sil_sn") or 0)
            if sn > 0:
                task = asyncio.create_task(mesaj_sil_sn(ctx, cid, m.message_id, sn))
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
    if not msg or not chat:
        return
    cid = chat.id
    log.info(f"NEW_CHAT_MEMBERS: chat={cid} n={len(msg.new_chat_members or [])}")
    try:
        if cget(cid, "cleanservice"):
            await msg.delete()
    except Exception:
        pass
    for u in (msg.new_chat_members or []):
        try:
            if u.is_bot:
                continue
            log.info(f"Yeni üye: {u.id} {u.full_name}")
            uye_kaydi(cid, u, say=False)
            kaydet()
            try:
                uname = f"@{u.username}" if u.username else "—"
                await log_gonder(
                    ctx, cid,
                    f"🟢 <b>Katıldı</b>\n👤 {html.escape(u.full_name)} ({uname})\n"
                    f"🆔 <code>{u.id}</code>\n📍 {html.escape(chat.title or str(cid))}",
                )
            except Exception:
                pass
            if cget(cid, "captcha"):
                try:
                    await sustur(ctx, cid, u.id)
                    klavye = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("✅ Robot değilim", callback_data=f"cap:{u.id}")]]
                    )
                    m = await ctx.bot.send_message(
                        cid,
                        f"{u.mention_html()} 3 dk içinde butona bas.",
                        parse_mode="HTML",
                        reply_markup=klavye,
                    )
                    bekleyen[(cid, u.id)] = m.message_id
                    tsk = asyncio.create_task(captcha_sure(ctx, cid, u.id, m.message_id))
                    gorevler.add(tsk)
                    tsk.add_done_callback(gorevler.discard)
                    continue
                except Exception as e:
                    log.warning(f"Captcha: {e}")
            if antiraid_kontrol(cid):
                try:
                    # geçici: link kilidi aç (zaten varsa), uyarı at
                    await ctx.bot.send_message(
                        cid,
                        "🚨 Antiraid: çok hızlı üye girişi — dikkat!",
                        disable_notification=True,
                    )
                    log.warning(f"Antiraid tetik: {cid}")
                except Exception:
                    pass
            await hosgeldin_gonder(ctx, cid, u, chat.title or "")
            ndk = int(cget(cid, "newbies_dk") or 15)
            if ndk > 0:
                try:
                    await sustur(ctx, cid, u.id, ndk)
                    log.info(f"Mute {ndk}dk: {u.id}")
                except Exception as e:
                    log.warning(f"Mute hata: {e}")
        except Exception as e:
            log.exception(f"hosgeldin üye döngü: {e}")

async def ayrildi(update, ctx):
    """X gruptan ayrildi - sil + log + unut."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    cid = chat.id
    if cget(cid, "cleanservice"):
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



# --- silinen komut fonksiyonlari icin guvenli stub ---
async def sustur(ctx, cid, uid, dk=10):
    return
async def sesi_ac(ctx, cid, uid):
    return
async def ihlal(update, ctx, ad, sil=True):
    return
async def arsiv_gonder(update, ctx, gun, baslik):
    return
def arsiv_ekle(cid, kayit):
    return
def liste_gun(kw):
    return 0, ""
def niyet_coz(metin):
    return {"eylem": None}

async def mesaj(update, ctx):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not chat:
        return
    # Bot mesajlarını yoksay (kendi döngüsü)
    if user and user.is_bot:
        return
    metin = msg.text or msg.caption
    if not metin:
        return
    if (msg.text or "").lstrip().startswith("/"):
        return
    ozel = chat.type == "private"
    cid = chat.id
    # Anonim / kanal tartışması: user yoksa sender_chat ile devam (AI için)
    if user:
        kayit = uye_kaydi(cid, user)
    else:
        kayit = {"ilk": "?", "mesaj": 0}
    if user and not ozel and str(user.id) in _liste_uid(cid, "blacklist"):
        try:
            await msg.delete()
            await ctx.bot.ban_chat_member(cid, user.id)
        except Exception:
            pass
        return
    if user and not ozel and gece_modu_aktif(cid) and not await muaf_mi(ctx, cid, user.id):
        try:
            await msg.delete()
        except Exception:
            pass
        return
    sm = int(cget(cid, "slowmode") or 0)
    if user and not ozel and sm > 0 and not await muaf_mi(ctx, cid, user.id):
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

    # otomatik pin YOK

    # sadece AI

    if False and not ozel and "yapay" in kucult(metin) and "ceza" in kucult(metin):
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
        kanal_izinli = mesaj_bagli_kanal_mi(cid, msg) or (
            getattr(msg, "is_automatic_forward", False) and mesaj_bagli_kanal_mi(cid, msg)
        )
        # Kanaldan sohbete düşen / duyuru kanalı t.me linkleri serbest
        duy = str(cget(cid, "duyuru_kanal") or "").lower().lstrip("@")
        met_l = kucult(metin)
        kanal_link_ok = False
        if duy and (duy in met_l or f"t.me/{duy}" in met_l):
            kanal_link_ok = True
        if link_izinli_mi(cid, metin, msg):
            kanal_link_ok = True
        n = cget(cid, "flood")
        spam = n > 0 and user is not None and spam_mi(cid, user.id, n)
        ad = None
        onayli = user is not None and (str(user.id) in _liste_uid(cid, "approved") or str(user.id) in _liste_uid(cid, "whitelist"))
        if kanal_izinli or kanal_link_ok:
            pass
        elif not onayli and (scam_var(metin) or ("link" in (cget(cid, "kilit") or []) and link_var(msg, metin, cid))):
            ad = "link/şifre paylaşımı"
        elif kufur_var(metin):
            ad = "küfür/hakaret"
        elif kara_var(cid, kelimeler):
            ad = "yasaklı kelime"
        elif spam:
            ad = "spam"
        if ad and user is not None and not await muaf_mi(ctx, cid, user.id):
            return  # ihlal/mod kaldirildi
            return
        if "@admin" in kucult(metin):
            return  # rapor kaldirildi
            return
        if metin.startswith("#") and len(metin) > 1:
            parca = metin[1:].split()
            tn = durum["not"].get(str(cid), {}).get(kucult(parca[0])) if parca else None
            if tn:
                await msg.reply_text(tn)
                return
        # filtre: grup + global
        flt = dict(durum["filtre"].get(GLOBAL_AYAR, {}) or {})
        flt.update(durum["filtre"].get(str(cid), {}) or {})
        met_k = kucult(metin)
        for kw_, cev in flt.items():
            if not kw_:
                continue
            if kw_ in kelimeler or kw_ in met_k:
                # sağdaki örnek gibi: mesaja yanıt olarak gönder
                pass  # filtre kaldirildi
                # return
        if kt and await fiyat_gonder(update, ctx, kt[1], kt[0], False):
            return
        # Grupta / tartışmada: metinde "yapay" veya @bot geçince (anonim/grup imzası fark etmez)
        bot_un = (ctx.bot.username or "").lower()
        met_k = kucult(metin)
        # Bota yanıt (reply) → yapay yazmadan da konuş
        rt = msg.reply_to_message
        bota_yanit = bool(
            rt and rt.from_user and rt.from_user.id == ctx.bot.id
        )
        cagrildi = (
            "yapay" in met_k
            or (bot_un and f"@{bot_un}" in met_k)
            or bota_yanit
        )
        for e in (getattr(msg, "entities", None) or []):
            et = getattr(e, "type", None)
            if et == "mention" and bot_un and bot_un in kucult(metin):
                cagrildi = True
            if et == "text_mention" and getattr(e, "user", None) and e.user.id == ctx.bot.id:
                cagrildi = True
        if (cagrildi or len(kelimeler) <= 3) and set(kelimeler) & LISTE_KISA:
            gun, baslik = liste_gun(kelimeler)
            pass  # arsiv kaldirildi
            return
        if not cagrildi:
            return
        log.info(f"AI cagrildi: chat={cid} user={getattr(user,'id',None)} text={metin[:80]!r}")
    else:
        if kt and await fiyat_gonder(update, ctx, kt[1], kt[0], False):
            return

    # Grup AI kapalı mı
    if not ozel and cget(cid, "ai") is False:
        return

    await ctx.bot.send_chat_action(cid, "typing")

    # pin/sabit komutları kapalı

    if any(k.startswith(FIYAT_KOK) for k in kelimeler):
        token = await asyncio.to_thread(token_cikar, metin)
        if token and await fiyat_gonder(update, ctx, token):
            return

    if not ozel and not cget(cid, "ai"):
        return
    if not ozel and cget(cid, "ai_mod") and not await yetkili_mi(ctx, cid, user.id):
        return

    ad_kisi = None
    if user:
        ad_kisi = (user.first_name or user.full_name or user.username or "").strip()
    if not ad_kisi or ad_kisi.lower() in ("telegram", "bot", "channel", "kanal"):
        ad_kisi = "dostum"
    ek = (
        f"\nŞu an yazan kişinin adı: {ad_kisi}. "
        f"Ona sadece '{ad_kisi}' diye hitap et. 'Telegram' deme."
    )
    if user:
        ek += f" Grupta {kayit.get('mesaj', 0)} mesajı var."
    if user and sahip_mi(user):
        ek += " Bu kişi SAHİP; samimi ol."
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

    uid = user.id if user else (getattr(msg.sender_chat, "id", None) or 0)
    anahtar = (cid, uid)
    h = gecmis.setdefault(anahtar, [])
    h.append({"role": "user", "content": metin})

    yanit = await asyncio.to_thread(sor, h[-20:], ek, arama_gerek(metin))
    if not yanit:
        yanit = "Bir saniye, tekrar dene 🙏"
    else:
        # uzun cevapları kısalt
        yanit = yanit.strip()
        if len(yanit) > 220:
            kes = yanit[:220]
            if " " in kes:
                kes = kes.rsplit(" ", 1)[0]
            yanit = kes + "…"
        h.append({"role": "assistant", "content": yanit})
    gecmis[anahtar] = h[-40:]
    try:
        await msg.reply_text(yanit, do_quote=True)
    except Exception as e:
        log.warning(f"AI reply hata: {e}")
        try:
            await ctx.bot.send_message(cid, yanit)
        except Exception as e2:
            log.warning(f"AI send hata: {e2}")

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
    if re.search(r"https?://\S+", k) and "bagli-kanal" not in k:
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




app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(baslat).build()

# HIC KOMUT YOK — sadece AI sohbet + giris/cikis
app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
app.add_handler(MessageHandler(
    (filters.TEXT | filters.CAPTION) & (~filters.COMMAND) & filters.UpdateType.MESSAGE, mesaj
))

app.add_error_handler(hata)
log.info("Bot basliyor (sadece AI + fiyat)...")
app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
