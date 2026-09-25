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
    "🤖 <b>Komutlar</b>\n\n"
    "<b>Herkes:</b> /kurallar /fiyat btc /top /bilgi /id /notlar /not isim /filtreler /kilitler /rapor "
    "/gunluk /haftalik /aylik\n\n"
    "<b>Moderasyon:</b> /ban /unban /kick /mute [süre] /tmute 10m /unmute /warn /unwarn /warns /resetwarns "
    "/del /purge /pin /unpin\n"
    "Hedef: mesaja yanıt ver ya da @kullanıcı / ID yaz. Süre: 10m, 2h, 1d\n\n"
    "<b>Komutsuz (sahip):</b> mesaja yanıt verip doğal cümlelerle 'yapay banla', 'şunu sustur', 'bunu uçur', "
    "'sabitle', 'duyuru yap' gibi yazabilirsin, bot anlamaya çalışır. 'yapay bundan sonra ...' ile kalıcı "
    "talimat verirsin.\n\n"
    "<b>Ayar:</b> /ayarlar /hosgeldin_ac /hosgeldin_kapat /hosgeldinmetni metin ({ad} {grup}) /hosgeldinsifirla "
    "/kuralayarla metin /kuralsil /captcha_ac /captcha_kapat /flood 6 /uyarilimit 3 /uyarieylem ban|mute|kick "
    "/ai_ac /ai_kapat /ipucu_ac /ipucu_kapat /adminizin_ac /adminizin_kapat\n\n"
    "<b>İçerik:</b> /kaydet isim metin (sonra #isim) /notsil isim /filtre kelime cevap /filtresil kelime "
    "/kara kelime /karasil kelime /karalar /kilit tür /kilitac tür /duyuruekle\n"
    "Kilit türleri: link sticker gif foto video ses dosya iletilen\n\n"
    "Yapay zeka için mesajında 'yapay' yaz."
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
               ("duyuru_saat", 0)):
    durum.setdefault(_k, _v)
if not durum["son"]:
    durum["son"] = time.time()

VARS = {"ai": True, "ipucu": True, "hosgeldin": True, "captcha": False, "adminizin": False,
        "kilit": ["link"], "flood": 6, "warn_limit": 3, "warn_eylem": "mute",
        "hosgeldin_metin": None, "kurallar": None}

def cget(cid, k):
    return durum["ayar"].get(str(cid), {}).get(k, VARS[k])

def cset(cid, k, v):
    durum["ayar"].setdefault(str(cid), {})[k] = v
    durum_kaydet()

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
    r = groq.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "system", "content": sistem}] + m,
    )
    return r.choices[0].message.content

def _gemini_icerik(m):
    return [{"role": "model" if x["role"] == "assistant" else "user",
             "parts": [{"text": x["content"]}]} for x in m]

def gemini_sor(m, sistem):
    r = gem.models.generate_content(
        model="gemini-2.0-flash",
        contents=_gemini_icerik(m),
        config={"system_instruction": sistem},
    )
    return r.text

def gemini_arama(m, sistem):
    r = gem.models.generate_content(
        model="gemini-2.0-flash",
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

def nvidia_sor(m, sistem):
    r = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": "Bearer " + NVIDIA_KEY},
        json={"model": "meta/llama-3.3-70b-instruct",
              "messages": [{"role": "system", "content": sistem}] + m},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

SAGLAYICILAR = [("Gemini", gemini_sor), ("Groq", groq_sor)]
if CEREBRAS_KEY:
    SAGLAYICILAR.append(("Cerebras", cerebras_sor))
if OPENROUTER_KEY:
    SAGLAYICILAR.append(("OpenRouter", openrouter_sor))
if NVIDIA_KEY:
    SAGLAYICILAR.append(("NVIDIA", nvidia_sor))
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
        model="gemini-2.0-flash",
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

def komut_silici(fonk):
    async def sar(update, ctx):
        await fonk(update, ctx)
        msg = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if msg and user and chat.type != "private" and await yetkili_mi(ctx, chat.id, user.id):
            try:
                await msg.delete()
            except Exception:
                pass
    return sar

def mesaj_linki(chat, mid):
    if chat.username:
        return f"https://t.me/{chat.username}/{mid}"
    s = str(chat.id)
    if s.startswith("-100"):
        return f"https://t.me/c/{s[4:]}/{mid}"
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
    return {"id": mid, "metin": metin[:1500], "link": mesaj_linki(chat, mid), "tarih": tarih}

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

def arsiv_ekle(cid, kayit):
    liste = durum["arsiv"].setdefault(str(cid), [])
    for x in liste:
        if x["id"] == kayit["id"]:
            x["tarih"] = kayit["tarih"]
            x["metin"] = kayit.get("metin", "")
            x["link"] = kayit.get("link")
            durum_kaydet()
            return
    liste.append({"id": kayit["id"], "metin": kayit.get("metin", ""),
                  "link": kayit.get("link"), "tarih": kayit["tarih"]})
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
    for s in (k.get("metin") or "").splitlines():
        s = re.sub(r"https?://\S+", "", s).strip()
        if s:
            return s[:45] + ("…" if len(s) > 45 else "")
    return "Duyuru"

def liste_gun(kw):
    if any(k in ("aylık", "aylik") for k in kw):
        return 30, "Aylık"
    if any(k in ("haftalık", "haftalik") for k in kw):
        return 7, "Haftalık"
    return 1, "Bugünkü"

async def arsiv_gonder(update, ctx, gun, baslik):
    msg = update.effective_message
    kayitlar = arsiv_liste(update.effective_chat.id, gun)
    if not kayitlar:
        await msg.reply_text(f"{baslik} duyuru yok.")
        return
    satirlar = [f"📢 {baslik} Duyurular"]
    dugmeler = []
    for i, k in enumerate(kayitlar[:10], 1):
        ad = arsiv_baslik(k)
        if k.get("link"):
            dugmeler.append([InlineKeyboardButton(f"{NUMARALAR[i - 1]} {ad}", url=k["link"])])
        else:
            satirlar.append(f"{NUMARALAR[i - 1]} {ad}")
    await msg.reply_text("\n".join(satirlar), reply_markup=InlineKeyboardMarkup(dugmeler) if dugmeler else None)

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
    pm = msg.pinned_message
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
    cset(chat.id, ad, deger == "ac")
    await msg.reply_text(f"{ad.upper()} {'açıldı' if deger == 'ac' else 'kapatıldı'}.")

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
    return sor([{"role": "user", "content":
        "Kripto ve airdrop meraklısı bir Telegram grubu için 💡 ile başlayan, en fazla 2 kısa ve TAM cümlelik, "
        "doğru ve yeni başlayanlara faydalı tek bir bilgi yaz (güvenlik, terimler, airdrop dolandırıcılıkları, "
        "cüzdan kullanımı gibi). Cümleleri yarım bırakma, her cümleyi nokta ile bitir. "
        "Emin olmadığın bilgiyi yazma. Yatırım tavsiyesi ve fiyat tahmini verme. "
        "Şunları tekrar etme: " + eskiler}])

async def ipucu_gonder(app):
    s = await asyncio.to_thread(ipucu_uret)
    if not s:
        return
    s = s.strip()
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
    while True:
        await asyncio.sleep(60)
        try:
            now = datetime.now(TR)
            if now.minute > 1:
                continue
            son = durum.get("duyuru_saat", 0)
            if time.time() - son < 3500:
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
    app.bot_data["ipucu"] = asyncio.create_task(ipucu_dongusu(app))
    app.bot_data["duyuru"] = asyncio.create_task(duyuru_saatlik(app))
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
IZINLI = ("coingecko.com", "coinmarketcap.com", "dexscreener.com", "tradingview.com")
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
    adaylar = [a for a in adaylar if not any(d in a for d in IZINLI)]
    return len(adaylar) > 0

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
    if sil:
        try:
            await msg.delete()
        except Exception:
            pass
    if uyari[anahtar] == 1:
        await ctx.bot.send_message(cid, f"{user.mention_html()} {ad} yasak, bu ilk uyarın. "
                                        f"Tekrarında 5 dk susturulursun.", parse_mode="HTML")
    else:
        uyari[anahtar] = 0
        try:
            await sustur(ctx, cid, user.id, 5)
            await ctx.bot.send_message(cid, f"{user.mention_html()} uyarıya rağmen tekrar ettiğin için "
                                            f"5 dk susturuldun ({ad}).", parse_mode="HTML")
        except Exception as e:
            log.warning(f"Susturma hatası: {e}")
            await ctx.bot.send_message(cid, "Susturamadım, yetkim yok. Beni yönetici yapıp üyeleri kısıtlama yetkisi ver.")
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
    r = msg.reply_to_message
    if r and r.from_user:
        return r.from_user.id, r.from_user.full_name
    m = re.search(r"@(\w{4,})", t)
    if m:
        for uid, u in uyeler.get(str(cid), {}).items():
            if u["kullanici"].lower() == m.group(1):
                return int(uid), u["ad"]
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
    if ozel and not eylem.startswith("talimat"):
        return False
    kisa = len(kw) <= 4
    if eylem not in ("talimat", "talimat_sil", "talimat_liste", "hosgeldin_metin", "kural_metin", "ayar") \
            and not (adresli or kisa):
        return False
    if not await yetkili_mi(ctx, cid, user.id):
        if adresli:
            await msg.reply_text("Bunu sadece sahibim yapabilir 😄")
            return True
        return False

    async def de(s):
        await msg.reply_text(s)

    async def bitir():
        try:
            await msg.delete()
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
            cset(cid, "hosgeldin_metin", s)
            await de("✅ Hoş geldin metni ayarlandı. ({ad} ve {grup} kullanabilirsin)")
        else:
            cset(cid, "kurallar", s)
            await de("✅ Kurallar ayarlandı.")
        return True
    if eylem == "ayar":
        ad = niyet_ayar if niyet_ayar in ("captcha", "hosgeldin", "ipucu") else (
             "captcha" if "captcha" in kw else ("ipucu" if kw_var(kw, "ipucu") else "hosgeldin"))
        ac_deger = niyet_ac if isinstance(niyet_ac, bool) else (not kapat)
        cset(cid, ad, ac_deger)
        await de(f"{ad.upper()} {'açıldı' if ac_deger else 'kapatıldı'}.")
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
        await ctx.bot.send_message(cid, cevap, parse_mode="HTML")
        await bitir()
    except Exception as e:
        log.warning(f"Doğal komut hatası: {e}")
        await de("Yapamadım (botun yönetici yetkisi eksik olabilir).")
    return True

ALIAS = {"ban": "ban", "yasakla": "ban", "unban": "unban", "banac": "unban", "kick": "kick", "at": "kick",
         "mute": "mute", "sustur": "mute", "tmute": "tmute", "unmute": "unmute", "sesac": "unmute",
         "warn": "warn", "uyar": "warn", "unwarn": "unwarn", "uyarisil": "unwarn",
         "warns": "warns", "uyarilar": "warns", "resetwarns": "resetwarns", "uyarisifirla": "resetwarns"}

def sure_coz(s):
    m = re.fullmatch(r"(\d+)(dk|sa|gun|g|m|h|d)?", s.lower())
    if not m:
        return None
    carp = {"dk": 1, "m": 1, "sa": 60, "h": 60, "gun": 1440, "g": 1440, "d": 1440}[m.group(2) or "dk"]
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
    try:
        if islem == "ban":
            await ctx.bot.ban_chat_member(cid, hid)
            cevap = f"🔨 {m} banlandı."
        elif islem == "unban":
            await ctx.bot.unban_chat_member(cid, hid, only_if_banned=True)
            cevap = f"✅ {m} banı kaldırıldı."
        elif islem == "kick":
            await ctx.bot.ban_chat_member(cid, hid)
            await ctx.bot.unban_chat_member(cid, hid)
            cevap = f"👢 {m} gruptan atıldı."
        elif islem in ("mute", "tmute"):
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
        elif islem == "warn":
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
        await ctx.bot.send_message(cid, cevap, parse_mode="HTML")
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
    if chat.type == "private" or not msg.text:
        return
    if not await yetkili_mi(ctx, cid, update.effective_user.id):
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
            cset(cid, "flood", int(a1))
            await de("Flood: " + ("kapalı" if int(a1) == 0 else f"10 sn'de {a1} mesaj"))
        else:
            await de("Örnek: /flood 6 (0 = kapalı)")
    elif ad == "uyarilimit":
        if a1.isdigit() and 1 <= int(a1) <= 20:
            cset(cid, "warn_limit", int(a1))
            await de(f"Uyarı limiti: {a1}")
        else:
            await de("Örnek: /uyarilimit 3")
    elif ad == "uyarieylem":
        if a1.lower() in ("ban", "kick", "mute"):
            cset(cid, "warn_eylem", a1.lower())
            await de(f"Limit dolunca: {a1.lower()}")
        else:
            await de("Örnek: /uyarieylem mute (ban, kick, mute)")
    elif ad == "kuralayarla":
        t = komut_metni(msg)
        if t:
            cset(cid, "kurallar", t)
            await de("✅ Kurallar kaydedildi.")
        else:
            await de("Örnek: /kuralayarla kural metni")
    elif ad == "kuralsil":
        cset(cid, "kurallar", None)
        await de("Kurallar silindi.")
    elif ad == "hosgeldinmetni":
        t = komut_metni(msg)
        if t:
            cset(cid, "hosgeldin_metin", t)
            await de("✅ Hoş geldin metni kaydedildi. ({ad} ve {grup} kullanabilirsin)")
        else:
            await de("Örnek: /hosgeldinmetni Merhaba {ad}, {grup} grubuna hoş geldin!")
    elif ad == "hosgeldinsifirla":
        cset(cid, "hosgeldin_metin", None)
        await de("Hoş geldin metni varsayılana döndü (yapay zeka yazar).")
    elif ad == "kaydet":
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
    elif ad in ("kilit", "kilitac"):
        t = kucult(a1)
        if t not in KILIT_TURLERI:
            await de("Türler: " + ", ".join(KILIT_TURLERI))
        else:
            k = list(cget(cid, "kilit"))
            if ad == "kilit" and t not in k:
                k.append(t)
            if ad == "kilitac" and t in k:
                k.remove(t)
            cset(cid, "kilit", k)
            await de(("🔒 Kilitlendi: " if ad == "kilit" else "🔓 Açıldı: ") + t)
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
    if ad == "kurallar":
        await msg.reply_text(cget(cid, "kurallar") or "Henüz kural yazılmamış.")
    elif ad in ("not", "get"):
        isim = kucult(p[1]) if len(p) > 1 else ""
        await msg.reply_text(durum["not"].get(scid, {}).get(isim) or "Böyle bir not yok. /notlar yaz.")
    elif ad == "notlar":
        n = durum["not"].get(scid, {})
        await msg.reply_text(("📝 Notlar: " + " ".join("#" + k for k in n)) if n else "Kayıtlı not yok.")
    elif ad == "filtreler":
        f = durum["filtre"].get(scid, {})
        await msg.reply_text(("🔎 Filtreler: " + ", ".join(f)) if f else "Filtre yok.")
    elif ad == "kilitler":
        await msg.reply_text("🔒 Kilitler: " + (", ".join(cget(cid, "kilit")) or "yok"))
    elif ad == "id":
        h = msg.reply_to_message.from_user if msg.reply_to_message and msg.reply_to_message.from_user else user
        await msg.reply_text(f"🆔 {h.id}\nGrup: {cid}")
    elif ad == "bilgi":
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
    elif ad == "rapor":
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
    await ctx.bot.send_message(cid, s, parse_mode="HTML")

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
    for u in msg.new_chat_members:
        if u.is_bot:
            continue
        uye_kaydi(cid, u, say=False)
        kaydet()
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
    kilit = cget(chat.id, "kilit")
    if not kilit or not any(t in kilit for t in mesaj_turleri(msg)):
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
    kt = kisa_token(metin)
    kelimeler = re.findall(r"\w+", kucult(metin))

    if not ozel and sahip_mi(user) and link_var(msg, metin):
        try:
            kayit_ozet = await mesaj_ozeti(ctx, msg, chat)
            if kayit_ozet:
                kayit_ozet["tarih"] = time.time()
                arsiv_ekle(cid, kayit_ozet)
                await ctx.bot.pin_chat_message(cid, msg.message_id, disable_notification=True)
                log.info(f"Sahip linki otomatik kaydedildi + pinlendi: {cid}")
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
        n = cget(cid, "flood")
        spam = n > 0 and spam_mi(cid, user.id, n)
        ad = None
        if scam_var(metin) or ("link" in cget(cid, "kilit") and link_var(msg, metin)):
            ad = "link/şifre paylaşımı"
        elif kufur_var(metin):
            ad = "küfür/hakaret"
        elif kara_var(cid, kelimeler):
            ad = "yasaklı kelime"
        elif spam:
            ad = "spam"
        if ad and not await muaf_mi(ctx, cid, user.id):
            await ihlal(update, ctx, ad, ad != "spam")
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
        cagrildi = "yapay" in kucult(metin) or bool(botun_mesaji)
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
        yanit = "Şu an biraz yoğunum, birazdan yazarım."
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
                                "hosgeldinmetni", "hosgeldinsifirla", "kaydet", "notsil", "filtre", "filtresil",
                                "kara", "karasil", "karalar", "kilit", "kilitac", "ayarlar", "del", "sil", "purge",
                                "pin", "sabitle", "unpin", "sabitkaldir", "duyuruekle"], yonet_komut))
app.add_handler(CommandHandler(["yardim", "help", "start", "kurallar", "not", "get", "notlar", "filtreler",
                                "kilitler", "id", "bilgi", "top", "istatistik", "rapor"], genel_komut))
app.add_handler(CommandHandler("sifirla", sifirla))
app.add_handler(CommandHandler("fiyat", fiyat_komut))
app.add_handler(CommandHandler("ipucu", ipucu_komut))
app.add_handler(CallbackQueryHandler(captcha_buton, pattern=r"^cap:"))
app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, sabitlendi))
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, hosgeldin))
app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.UpdateType.MESSAGE, mesaj))
app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.UpdateType.MESSAGE, kilit_kontrol), group=1)
app.add_error_handler(hata)
log.info("Bot başlıyor...")
app.run_polling()
