import asyncio, html, json, logging, os, re, threading, time, requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, timezone
from groq import Groq
from google import genai
from google.genai import types
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ChatMemberHandler, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")

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
TR = timezone(timedelta(hours=3))
CEZA_MIN_OY = 6
CEZA_MUTE_DK = 5
CEZA_SURE_SN = 120

SISTEM = (
    "Sen bir Telegram grubunun zeki, esprili, samimi ve makaracı asistanısın. "
    "İnsanlarla sıcak ve doğal konuş. Gerekirse hafif küfür de edebilirsin (amk, aq, lan gibi) ama abartma. "
    "Türkçe konuş. Cevapların 1-3 cümle olsun, gereksiz uzatma. "
    "Cümleleri asla yarım bırakma, her cümleyi düzgün bitir. "
    "ÖNCEKİ KONUŞMAYI MUTLAKA TAKİP ET. Konu dışına çıkma. "
    "İnsanların isimleriyle hitap et, samimi ol, espri yap. "
    "Kendi adını ASLA söyleme. Sorulursa 'Ben grubun yapay zeka asistanıyım' de. "
    "Siyaset konuşma. Yatırım tavsiyesi verme. Bilmediğin şeyi uydurma. "
    "Saat sorulursa ASLA uydurma. Sahibinin kalıcı talimatlarına sessizce uy."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
log = logging.getLogger("bot")

groq = Groq(api_key=GROQ_KEY, timeout=30)
gem = genai.Client(api_key=GEMINI_KEY)
gecmis = []
gorevler = set()
aktif_ceza = {}
onbellek = {}

DURUM = "durum.json"
try:
    with open(DURUM, "r", encoding="utf-8") as f:
        durum = json.load(f)
except Exception:
    durum = {}
for _k, _v in (("sahip", None), ("talimat", []), ("gecmis", []), ("gruplar", {}),
               ("hosgeldin_metin", None), ("hosgeldin_mute_dk", 15)):
    durum.setdefault(_k, _v)

gecmis = list(durum.get("gecmis") or [])

VARSAYILAN_HOSGELDIN = (
    "⛔ <b>{ad}</b> Hoşgeldiniz\n"
    "⚠️ Katıldığı andan itibaren {mute} dakika boyunca mesaj gönderemez\n"
    "✅ {mute} dakika sonra sohbeti başlatabilirsiniz. 🚀"
)

def durum_kaydet():
    try:
        durum["gecmis"] = gecmis[-40:]
        with open(DURUM, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Durum kayıt hatası: {e}")

def kucult(t):
    return t.replace("İ", "i").replace("I", "ı").lower()

def sahip_mi(user):
    return bool(user) and durum.get("sahip") == user.id

def simdi_saat():
    return datetime.now(TR).strftime("%H:%M")

async def sahip_yakala(update, ctx):
    u = update.effective_user
    if u and u.username and u.username.lower() == SAHIP_KULLANICI and durum.get("sahip") != u.id:
        durum["sahip"] = u.id
        durum_kaydet()
        log.info(f"Sahip tanındı: {u.id}")

def grup_kaydet(chat):
    if chat and chat.type in ("group", "supergroup") and chat.id < 0:
        durum["gruplar"][str(chat.id)] = chat.title or str(chat.id)
        durum_kaydet()

async def sustur(ctx, chat_id, user_id, dakika):
    until = datetime.now(timezone.utc) + timedelta(minutes=dakika)
    await ctx.bot.restrict_chat_member(
        chat_id, user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until,
    )

# ============================================================
# AI
# ============================================================

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

SAGLAYICILAR = [("Gemini", gemini_sor), ("Groq", groq_sor)]
if MISTRAL_KEY:
    SAGLAYICILAR.append(("Mistral", mistral_sor))

def sor(mesajlar, ek="", arama=False):
    sistem = SISTEM + ek
    zincir = [("Gemini+Arama", gemini_arama)] + SAGLAYICILAR if arama else SAGLAYICILAR
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

ARAMA_KELIME = {"araştır", "arastir", "haber", "haberi", "güncel", "guncel", "gündem", "gundem",
                "bugün", "bugun", "dün", "dun"}
ARAMA_IFADE = ("son dakika", "şu an", "ne oldu", "kim kazandı")

def arama_gerek(t):
    k = kucult(t)
    if any(i in k for i in ARAMA_IFADE):
        return True
    return bool(set(re.findall(r"\w+", k)) & ARAMA_KELIME)

def saat_soruldu_mu(t):
    k = kucult(t)
    kelimeler = re.findall(r"\w+", k)
    if not any(x in kelimeler for x in ("saat", "saati", "kaç", "kac", "time")):
        return False
    if any(x in k for x in ("gruba", "grupta")):
        return False
    return True

# ============================================================
# FİYAT (Yahoo Finance + CoinGecko)
# ============================================================

def sayi(x):
    if x is None:
        return "?"
    if x >= 1:
        return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{x:.8f}".rstrip("0").rstrip(".").replace(".", ",")

def sade(x):
    s = f"{x:.8f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")

def yahoo_fiyat(sembol):
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

# Yahoo: sadece döviz + Türk hisseleri (coin değil)
YAHOO_MAP = {
    "dolar": "USDTRY=X", "usd": "USDTRY=X", "dollar": "USDTRY=X",
    "euro": "EURTRY=X", "eur": "EURTRY=X",
    "sterlin": "GBPTRY=X", "gbp": "GBPTRY=X",
    "usdt": "USDT-TRY", "tether": "USDT-TRY",
    "usdc": "USDC-USD",
    # BIST hisseleri
    "thyao": "THYAO.IS", "thy": "THYAO.IS",
    "garanti": "GARAN.IS", "garan": "GARAN.IS",
    "akbank": "AKBNK.IS", "akbnk": "AKBNK.IS",
    "bipas": "BIMAS.IS", "bimas": "BIMAS.IS",
    "aselsan": "ASELS.IS", "asels": "ASELS.IS",
    "eregl": "EREGL.IS", "eregli": "EREGL.IS",
    "sahol": "SAHOL.IS", "kchol": "KCHOL.IS",
    "tuprs": "TUPRS.IS", "sise": "SISE.IS",
    "tcelt": "TCELL.IS", "tcell": "TCELL.IS",
    "ykbnk": "YKBNK.IS", "isctr": "ISCTR.IS",
    "froto": "FROTO.IS", "toaso": "TOASO.IS",
    "kozaa": "KOZAA.IS", "kozal": "KOZAL.IS",
    "petkm": "PETKM.IS", "sasa": "SASA.IS",
    "astor": "ASTOR.IS", "enjsa": "ENJSA.IS",
}

YAHOO_AD = {
    "dolar": "Dolar (USD)", "usd": "Dolar (USD)", "dollar": "Dolar (USD)",
    "euro": "Euro", "eur": "Euro",
    "sterlin": "Sterlin", "gbp": "Sterlin",
    "usdt": "USDT", "tether": "USDT", "usdc": "USDC",
}

def fiyat_ara(q):
    q = q.lower().strip()

    # 1) Yahoo — döviz ve Türk hisseleri
    ysymbol = YAHOO_MAP.get(q)
    if ysymbol:
        y = yahoo_fiyat(ysymbol)
        if y:
            guzel = YAHOO_AD.get(q, q.upper())
            if "TRY" in ysymbol or ysymbol.endswith("=X") or ysymbol.endswith(".IS"):
                return {
                    "ad": guzel, "sembol": guzel, "usd": None, "try": y["fiyat"],
                    "deg": y["deg"], "kaynak": "yahoo",
                    "link": f"https://finance.yahoo.com/quote/{ysymbol}",
                }
            try_fiyat = None
            kur = yahoo_fiyat("USDTRY=X")
            if kur:
                try_fiyat = y["fiyat"] * kur["fiyat"]
            return {
                "ad": guzel, "sembol": guzel, "usd": y["fiyat"], "try": try_fiyat,
                "deg": y["deg"], "kaynak": "yahoo",
                "link": f"https://finance.yahoo.com/quote/{ysymbol}",
            }

    # 2) CoinGecko — TÜM coinler
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": q}, timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        ).json()
        coinler = r.get("coins") or []
        # Önce sembol tam eşleşme, sonra isim, sonra ilk sonuç
        tam_sembol = [c for c in coinler if c.get("symbol", "").lower() == q]
        tam_isim = [c for c in coinler if c.get("name", "").lower() == q]
        aday = tam_sembol or tam_isim or coinler
        if aday:
            sec = min(aday, key=lambda c: c.get("market_cap_rank") or 10**9)
            p = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": sec["id"],
                    "vs_currencies": "usd,try",
                    "include_24hr_change": "true",
                },
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
            ).json()
            d = p.get(sec["id"], {})
            if d.get("usd") is not None or d.get("try") is not None:
                return {
                    "ad": sec["name"],
                    "sembol": sec["symbol"].upper(),
                    "usd": d.get("usd"),
                    "try": d.get("try"),
                    "deg": d.get("usd_24h_change") or d.get("try_24h_change"),
                    "kaynak": "coingecko",
                    "link": f"https://www.coingecko.com/en/coins/{sec['id']}",
                }
    except Exception as e:
        log.warning(f"CoinGecko hatası: {e}")

    # 3) DexScreener yedek
    try:
        r = requests.get(
            "https://api.dexscreener.com/latest/dex/search",
            params={"q": q}, timeout=10,
        ).json()
        pairs = [
            p for p in (r.get("pairs") or [])
            if p.get("priceUsd") and p.get("baseToken", {}).get("symbol", "").lower() == q
        ]
        if not pairs:
            pairs = [p for p in (r.get("pairs") or []) if p.get("priceUsd")]
        if pairs:
            p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
            return {
                "ad": p["baseToken"]["name"],
                "sembol": p["baseToken"]["symbol"].upper(),
                "usd": float(p["priceUsd"]),
                "try": None,
                "deg": (p.get("priceChange") or {}).get("h24"),
                "kaynak": "dex",
                "link": p.get("url") or "",
            }
    except Exception as e:
        log.warning(f"DexScreener hatası: {e}")
    return None

def fiyat_bul(sorgu):
    q = sorgu.strip().lower()
    an = onbellek.get(q)
    if an and time.time() - an[0] < 30:
        return an[1]
    veri = fiyat_ara(q)
    onbellek[q] = (time.time(), veri)
    return veri

KISA_FIYAT = re.compile(r"^\s*(?:(\d+(?:[.,]\d+)?)\s*\$?\s+)?([a-zA-Z][a-zA-Z0-9]{1,12})\s*$")
SAYI_KELIME = {"tl", "try", "gb", "mb", "kg", "tane", "adet", "saat", "gun", "dk", "sn", "lira"}

def kisa_token(metin):
    m = KISA_FIYAT.match(metin.strip())
    if m:
        miktar_text = m.group(1)
        token = m.group(2)
        if not token or token.lower() in SAYI_KELIME or len(token) < 2:
            return None
        try:
            mk = float(miktar_text.replace(",", ".")) if miktar_text else 1.0
        except Exception:
            return None
        if mk <= 0 or mk > 1e12:
            return None
        return mk, token
    t = kucult(metin).strip()
    if 2 <= len(t) <= 12 and t.isalpha() and t not in SAYI_KELIME:
        return 1.0, t
    return None

async def fiyat_gonder(update, ctx, sorgu, miktar=1.0):
    msg = update.effective_message
    user = update.effective_user
    try:
        veri = await asyncio.to_thread(fiyat_bul, sorgu)
    except Exception as e:
        log.warning(f"fiyat_bul hata: {e}")
        return False
    if not veri:
        log.info(f"Fiyat bulunamadı: {sorgu}")
        return False

    # Başlık: "10 Pudgy Penguins (PENGU):" veya "1 USDT:"
    ad = veri.get("ad") or veri["sembol"]
    sembol = veri["sembol"]
    if ad.upper() != sembol.upper() and veri.get("kaynak") == "coingecko":
        baslik = f"⚠️ {sade(miktar)} {ad} ({sembol}):"
    else:
        baslik = f"⚠️ {sade(miktar)} {sembol}:"

    # Fiyat satırı
    if veri.get("try") is not None:
        fiyat_satir = f"✅ ₺{sayi(veri['try'] * miktar)}"
    elif veri.get("usd") is not None:
        fiyat_satir = f"✅ ${sayi(veri['usd'] * miktar)} Usdt"
    else:
        return False

    deg_text = ""
    if veri.get("deg") is not None:
        try:
            d = float(veri["deg"])
            yon = "yükseldi" if d >= 0 else "düştü"
            deg_text = f"%{abs(d):.2f} {yon}"
        except Exception:
            pass

    espri = None
    try:
        espri = await asyncio.to_thread(sor, [{"role": "user", "content":
            f"{ad} ({sembol}) fiyatı şu an "
            f"{'₺' + sayi(veri['try']) if veri.get('try') is not None else '$' + sayi(veri.get('usd'))}, "
            f"24 saatte %{veri.get('deg') or 0:+.2f} değişti. "
            f"Buna çok kısa, esprili, samimi bir Türkçe cümle yaz. Yatırım tavsiyesi verme."}])
    except Exception as e:
        log.warning(f"Fiyat espri hata: {e}")

    satirlar = []
    if user:
        satirlar.append(f"<b>{html.escape(user.full_name)}</b>")
        satirlar.append(html.escape(msg.text or sorgu))
        satirlar.append("")
    satirlar.append(baslik)
    satirlar.append(fiyat_satir)
    if deg_text or espri:
        ek = "➖ "
        if deg_text:
            ek += deg_text + " "
        if espri:
            ek += espri.strip()
        satirlar.append(ek.strip())

    # Kaynak linki
    if veri.get("link"):
        satirlar.append(f'\n🔗 <a href="{html.escape(veri["link"])}">Kaynak</a>')

    try:
        await msg.reply_text("\n".join(satirlar), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Fiyat mesaj gönderilemedi: {e}")
        await msg.reply_text("\n".join(re.sub(r"<[^>]+>", "", s) for s in satirlar))
    return True

async def gruba_gonder(ctx, metin):
    gruplar = durum.get("gruplar") or {}
    if not gruplar:
        return 0, "Henüz grup kaydı yok. Önce botu gruba ekle ve grupta 'yapay merhaba' yaz."
    sayac = 0
    for gid in list(gruplar.keys()):
        try:
            await ctx.bot.send_message(int(gid), metin)
            sayac += 1
        except Exception as e:
            log.warning(f"Gruba gönderilemedi ({gid}): {e}")
    return sayac, None

async def mesaj_sil_gecikmeli(ctx, cid, mid, sn=5):
    await asyncio.sleep(sn)
    try:
        await ctx.bot.delete_message(cid, mid)
    except Exception:
        pass

# ============================================================
# HOŞ GELDİN
# ============================================================

async def hosgeldin_uye(ctx, chat, u):
    """Tek kullanıcıya hoş geldin + mute."""
    if not u or u.is_bot:
        return
    grup_kaydet(chat)
    mute_dk = int(durum.get("hosgeldin_mute_dk") or 15)
    sablon = durum.get("hosgeldin_metin") or VARSAYILAN_HOSGELDIN

    # Önce sustur (yetki yoksa sessizce geç)
    if mute_dk > 0:
        try:
            await sustur(ctx, chat.id, u.id, mute_dk)
            log.info(f"Yeni üye susturuldu: {u.id} ({mute_dk} dk)")
        except Exception as e:
            log.warning(f"Yeni üye susturulamadı: {e}")

    metin = (
        sablon
        .replace("{ad}", u.mention_html())
        .replace("{KullanıcıAdı}", u.mention_html())
        .replace("{kullanici}", u.mention_html())
        .replace("{isim}", html.escape(u.full_name or "Üye"))
        .replace("{mute}", str(mute_dk))
        .replace("{grup}", html.escape(chat.title or ""))
    )
    try:
        gonderilen = await ctx.bot.send_message(chat.id, metin, parse_mode="HTML")
        log.info(f"Hoşgeldin gönderildi: {chat.id} -> {u.id}")
        t = asyncio.create_task(mesaj_sil_gecikmeli(ctx, chat.id, gonderilen.message_id, 5))
        gorevler.add(t)
        t.add_done_callback(gorevler.discard)
    except Exception as e:
        log.warning(f"Hoşgeldin HTML hata, düz metin deneniyor: {e}")
        try:
            duz = re.sub(r"<[^>]+>", "", metin)
            gonderilen = await ctx.bot.send_message(chat.id, duz)
            t = asyncio.create_task(mesaj_sil_gecikmeli(ctx, chat.id, gonderilen.message_id, 5))
            gorevler.add(t)
            t.add_done_callback(gorevler.discard)
        except Exception as e2:
            log.warning(f"Hoşgeldin gönderilemedi: {e2}")

async def hosgeldin(update, ctx):
    """Eski yöntem: new_chat_members service mesajı."""
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or not msg.new_chat_members:
        return
    for u in msg.new_chat_members:
        await hosgeldin_uye(ctx, chat, u)

async def uye_guncelle(update, ctx):
    """Yeni yöntem: chat_member güncellemesi (daha güvenilir)."""
    cm = update.chat_member
    if not cm:
        return
    eski = cm.old_chat_member.status if cm.old_chat_member else None
    yeni = cm.new_chat_member.status if cm.new_chat_member else None
    # gruba yeni katıldı
    if yeni in (ChatMember.MEMBER, ChatMember.RESTRICTED) and eski in (
        ChatMember.LEFT, ChatMember.BANNED, None, "left", "kicked"
    ):
        u = cm.new_chat_member.user
        chat = cm.chat
        await hosgeldin_uye(ctx, chat, u)

# ============================================================
# CEZA OYLAMASI (BUTONLU)
# ============================================================

def ceza_klavye(ceza_id, evet, hayir):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Evet ({evet})", callback_data=f"ceza:{ceza_id}:evet"),
        InlineKeyboardButton(f"❌ Hayır ({hayir})", callback_data=f"ceza:{ceza_id}:hayir"),
    ]])

def ceza_metin(bil, evet, hayir, ekstra=""):
    return (
        f"⚠️ Ceza <b>{html.escape(bil['hedef_ad'])}</b>\n"
        f"🚫 Başlatan <b>{html.escape(bil['baslatan_ad'])}</b>\n"
        f"✅ Evet çoğunluk → {CEZA_MUTE_DK} Dk Mesaj Atmasını Kapat • Min {CEZA_MIN_OY} Oy\n"
        f"📊 Evet: {evet} | Hayır: {hayir}"
        + (f"\n{ekstra}" if ekstra else "")
    )

async def ceza_geri_sayim_sil(ctx, cid, mid, sonuc_metin, sn=5):
    """Sonuç mesajında 5..1 geri sayıp sil."""
    try:
        for i in range(sn, 0, -1):
            try:
                await ctx.bot.edit_message_text(
                    chat_id=cid, message_id=mid,
                    text=f"{sonuc_metin}\n\n⏳ {i} saniye sonra kaybolacak...",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            await asyncio.sleep(1)
        try:
            await ctx.bot.delete_message(cid, mid)
        except Exception:
            pass
    except Exception:
        pass

async def ceza_bitir(ctx, ceza_id):
    bil = aktif_ceza.pop(ceza_id, None)
    if not bil:
        return
    cid = bil["cid"]
    mid = bil["mid"]
    evet = len(bil["evet"])
    hayir = len(bil["hayir"])
    toplam = evet + hayir

    if toplam >= CEZA_MIN_OY and evet > hayir:
        try:
            await sustur(ctx, cid, bil["hedef_id"], CEZA_MUTE_DK)
            sonuc = (
                f"✅ Oylama bitti\n"
                f"⚠️ {html.escape(bil['hedef_ad'])} {CEZA_MUTE_DK} dk susturuldu\n"
                f"📊 Evet: {evet} | Hayır: {hayir}"
            )
        except Exception as e:
            log.warning(f"Ceza susturma hatası: {e}")
            sonuc = f"❌ Susturulamadı (yetki eksik olabilir)\n📊 Evet: {evet} | Hayır: {hayir}"
    else:
        sonuc = (
            f"❌ Oylama bitti — ceza uygulanmadı\n"
            f"📊 Evet: {evet} | Hayır: {hayir} (min {CEZA_MIN_OY} oy, çoğunluk Evet gerekli)"
        )

    try:
        await ctx.bot.edit_message_text(
            chat_id=cid, message_id=mid,
            text=sonuc, parse_mode="HTML",
        )
    except Exception:
        try:
            m = await ctx.bot.send_message(cid, sonuc, parse_mode="HTML")
            mid = m.message_id
        except Exception as e:
            log.warning(f"Ceza sonuç gönderilemedi: {e}")
            return

    t = asyncio.create_task(ceza_geri_sayim_sil(ctx, cid, mid, sonuc, 5))
    gorevler.add(t)
    t.add_done_callback(gorevler.discard)

async def ceza_baslat(update, ctx, hedef):
    msg = update.effective_message
    chat = update.effective_chat
    baslatan = update.effective_user

    if hedef.id == ctx.bot.id or hedef.id == durum.get("sahip"):
        await msg.reply_text("Buna ceza veremem 😄")
        return
    for b in aktif_ceza.values():
        if b["cid"] == chat.id and b["hedef_id"] == hedef.id:
            await msg.reply_text("Bu kişi için zaten oylama var.")
            return

    ceza_id = f"{chat.id}_{hedef.id}_{int(time.time())}"
    bil = {
        "cid": chat.id,
        "mid": None,
        "hedef_id": hedef.id,
        "hedef_ad": hedef.full_name,
        "baslatan": baslatan.id,
        "baslatan_ad": baslatan.full_name,
        "evet": set(),
        "hayir": set(),
        "baslangic": time.time(),
    }
    try:
        m = await ctx.bot.send_message(
            chat.id,
            ceza_metin(bil, 0, 0),
            parse_mode="HTML",
            reply_markup=ceza_klavye(ceza_id, 0, 0),
        )
        bil["mid"] = m.message_id
        aktif_ceza[ceza_id] = bil

        async def zamanlayici(cid_):
            await asyncio.sleep(CEZA_SURE_SN)
            if cid_ in aktif_ceza:
                await ceza_bitir(ctx, cid_)
        t = asyncio.create_task(zamanlayici(ceza_id))
        gorevler.add(t)
        t.add_done_callback(gorevler.discard)
    except Exception as e:
        log.warning(f"Ceza oylaması başlatılamadı: {e}")
        await msg.reply_text("Oylama başlatılamadı.")

async def ceza_buton(update, ctx):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("ceza:"):
        return
    try:
        _, ceza_id, oy = q.data.split(":", 2)
    except Exception:
        await q.answer()
        return

    bil = aktif_ceza.get(ceza_id)
    if not bil:
        await q.answer("Oylama bitti.", show_alert=True)
        return

    uid = q.from_user.id
    # Aynı kişi tekrar oy veremesin; oyunu değiştirebilsin
    bil["evet"].discard(uid)
    bil["hayir"].discard(uid)
    if oy == "evet":
        bil["evet"].add(uid)
        await q.answer("Evet oyu verildi ✅")
    else:
        bil["hayir"].add(uid)
        await q.answer("Hayır oyu verildi ❌")

    evet = len(bil["evet"])
    hayir = len(bil["hayir"])
    try:
        await q.edit_message_text(
            ceza_metin(bil, evet, hayir),
            parse_mode="HTML",
            reply_markup=ceza_klavye(ceza_id, evet, hayir),
        )
    except Exception:
        pass

    if evet + hayir >= CEZA_MIN_OY:
        await ceza_bitir(ctx, ceza_id)

# ============================================================
# ANA MESAJ
# ============================================================

async def mesaj(update, ctx):
    global gecmis
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or user.is_bot:
        return
    metin = msg.text or msg.caption
    if not metin:
        return

    ozel = chat.type == "private"
    t = kucult(metin)

    if not ozel:
        grup_kaydet(chat)

    # Kalıcı talimat
    if sahip_mi(user) and "yapay" in t and any(x in t for x in ("bundan sonra", "bundan böyle", "bundan boyle", "unutma", "aklında tut")):
        s = re.sub(r"(?i)yapay", "", metin).strip(" ,:.")
        durum["talimat"] = (durum["talimat"] + [{"t": s[:300]}])[-20:]
        durum_kaydet()
        await msg.reply_text("Tamam, aklımda 👍")
        return

    # FİYAT — kısa yazım (1 usdt, btc, 1 dolar, thyao ...)
    kt = kisa_token(metin)
    if kt:
        if await fiyat_gonder(update, ctx, kt[1], kt[0]):
            return

    # CEZA
    if not ozel and "yapay" in t and "ceza" in t:
        hedef = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            hedef = msg.reply_to_message.from_user
        if hedef:
            await ceza_baslat(update, ctx, hedef)
            return
        await msg.reply_text("Cezalandırılacak kişiye yanıt vererek yaz: yapay ceza")
        return

    # Karşılama ayarla (özelde sahip)
    if ozel and sahip_mi(user):
        karsilama_kelime = any(x in t for x in ("karşılama", "karsilama", "hosgeldin", "hoşgeldin", "welcome"))
        if karsilama_kelime:
            kaynak = None
            # 1) Yanıt verilen mesaj
            if msg.reply_to_message:
                kaynak = msg.reply_to_message.text or msg.reply_to_message.caption
            # 2) "karşılama mesajı: METİN"
            m = re.search(
                r"(?:karşılama|karsilama|hosgeldin|hoşgeldin)\s*mesaj[ıi]?\s*[:=]\s*(.+)",
                metin, re.I | re.S
            )
            if m and m.group(1).strip():
                kaynak = m.group(1).strip()
            # 3) Mesajın içinde şablon varsa (Hoşgeldiniz / {ad})
            if not kaynak and ("hoşgeldiniz" in t or "hosgeldiniz" in t or "{ad}" in metin or "{KullanıcıAdı}" in metin):
                kaynak = metin
                # Sondaki "bunu karşılama mesajı yap" kısmını temizle
                kaynak = re.sub(
                    r"(?i)\s*(bunu\s+)?(karşılama|karsilama|hosgeldin|hoşgeldin).*?(yap|ayarla|kaydet|olsun)\s*$",
                    "", kaynak
                ).strip()
            # 4) Sadece "karşılama mesajı yap" + yanıt yoksa varsayılanı kaydet
            if not kaynak and any(x in t for x in ("yap", "ayarla", "kaydet", "olsun", "varsayılan", "varsayilan")):
                kaynak = VARSAYILAN_HOSGELDIN
                await msg.reply_text("✅ Varsayılan karşılama mesajı aktif.")
                durum["hosgeldin_metin"] = kaynak
                durum_kaydet()
                return
            if kaynak:
                durum["hosgeldin_metin"] = kaynak
                durum_kaydet()
                await msg.reply_text(
                    "✅ Karşılama mesajı kaydedildi.\n"
                    "Gruba yeni biri girince bu mesaj gidecek (bot admin olmalı)."
                )
                return
        m2 = re.search(r"(?:mute|susturma|sustur)\s*(\d+)", t)
        if m2 and any(x in t for x in ("karşılama", "karsilama", "hosgeldin", "hoşgeldin", "mute", "yeni")):
            durum["hosgeldin_mute_dk"] = max(0, min(int(m2.group(1)), 1440))
            durum_kaydet()
            await msg.reply_text(f"✅ Yeni üyeler {durum['hosgeldin_mute_dk']} dk susturulacak.")
            return

    if saat_soruldu_mu(t) and (ozel or "yapay" in t):
        await msg.reply_text(f"Şu an saat {simdi_saat()} 🕐")
        return

    if ozel and sahip_mi(user):
        m = re.search(
            r"(?:gruba|grupta|gruba\s+söyle|grupta\s+söyle|gruba\s+yaz|grupta\s+yaz|gruba\s+at|grupta\s+at|gruba\s+paylaş|grupta\s+paylaş)\s+(.+)",
            metin, re.IGNORECASE
        )
        if m:
            gonderilecek = m.group(1).strip()
            if re.search(r"\bsaat\b", gonderilecek, re.I) and len(gonderilecek.split()) <= 4:
                gonderilecek = f"Şu an saat {simdi_saat()}"
            sayac, hata = await gruba_gonder(ctx, gonderilecek)
            await msg.reply_text(hata if hata else f"✅ {sayac} gruba gönderildi:\n{gonderilecek}")
            return
        if re.search(r"(gruba|grupta).*(saat|saati)", t):
            gonderilecek = f"Şu an saat {simdi_saat()}"
            sayac, hata = await gruba_gonder(ctx, gonderilecek)
            await msg.reply_text(hata if hata else f"✅ {sayac} gruba gönderildi:\n{gonderilecek}")
            return

    if not ozel:
        botun_mesaji = (msg.reply_to_message and msg.reply_to_message.from_user
                        and msg.reply_to_message.from_user.id == ctx.bot.id)
        if not ("yapay" in t or botun_mesaji):
            return

    await ctx.bot.send_chat_action(chat.id, "typing")

    if ozel:
        ek = f"\nŞu an: {user.full_name}. Bu ÖZEL sohbet. Saat: {simdi_saat()}."
    else:
        ek = f"\nŞu an: {user.full_name}. Bu GRUP ({chat.title or '?'}). Saat: {simdi_saat()}."
    if sahip_mi(user):
        ek += "\nBu kişi patronun (Jimin). Samimi ol."
    if durum.get("talimat"):
        ek += "\nTalimatlar: " + " | ".join(x["t"] for x in durum["talimat"][-10:])

    gecmis.append({"role": "user", "content": f"{user.full_name}: {metin}"})
    yanit = await asyncio.to_thread(sor, gecmis[-12:], ek, arama_gerek(metin))
    if not yanit:
        yanit = "Şu an biraz yoğunum, birazdan yazarım."
    else:
        gecmis.append({"role": "assistant", "content": yanit})
    gecmis = gecmis[-40:]
    durum_kaydet()
    await msg.reply_text(yanit)

async def sifirla(update, ctx):
    global gecmis
    user = update.effective_user
    if not sahip_mi(user) and update.effective_chat.type != "private":
        return
    gecmis = []
    durum["gecmis"] = []
    durum_kaydet()
    await update.effective_message.reply_text("Hafıza sıfırlandı.")

async def hata(update, ctx):
    log.warning(f"Hata: {ctx.error}")

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
app.add_handler(CommandHandler("sifirla", sifirla))
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, hosgeldin))
app.add_handler(ChatMemberHandler(uye_guncelle, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CallbackQueryHandler(ceza_buton, pattern=r"^ceza:"))
app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.UpdateType.MESSAGE, mesaj))
app.add_error_handler(hata)

log.info("Bot başlıyor...")
# chat_member güncellemelerini de al (yeni üye için şart)
app.run_polling(allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"])
