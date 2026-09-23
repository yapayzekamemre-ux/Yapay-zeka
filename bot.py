import asyncio, json, logging, os, re, threading, time, requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from groq import Groq
from google import genai
from google.genai import types
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters

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

SISTEM = (
    "Sen bir Telegram grubunun zeki, esprili, samimi ve makaracı asistanısın. "
    "İnsanlarla sıcak ve doğal konuş. Gerekirse hafif küfür de edebilirsin (amk, aq, lan gibi) ama abartma. "
    "Türkçe konuş. Cevapların 1-3 cümle olsun, gereksiz uzatma. "
    "Cümleleri asla yarım bırakma, her cümleyi düzgün bitir. "
    "ÖNCEKİ KONUŞMAYI MUTLAKA TAKİP ET. Konu dışına çıkma, başka yerlere sıçrama. "
    "İnsanların isimleriyle hitap et, samimi ol, espri yap. "
    "Kendi adını, hangi model olduğunu veya hangi şirketin ürünü olduğunu ASLA söyleme. "
    "Sorulursa sadece 'Ben grubun yapay zeka asistanıyım' de. "
    "Grubun amacı, içeriği hakkında ASLA bilgi uydurma. "
    "Siyaset konuşma. Yatırım tavsiyesi verme. Bilmediğin şeyi uydurma. "
    "Sahibinin kalıcı talimatlarına sessizce uy."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
log = logging.getLogger("bot")

groq = Groq(api_key=GROQ_KEY, timeout=30)
gem = genai.Client(api_key=GEMINI_KEY)

# TEK ORTAK HAFIZA — özel ve grup aynı
gecmis = []

DURUM = "durum.json"
try:
    with open(DURUM, "r", encoding="utf-8") as f:
        durum = json.load(f)
except Exception:
    durum = {}
for _k, _v in (("sahip", None), ("talimat", []), ("gecmis", [])):
    durum.setdefault(_k, _v)

# Kayıtlı hafızayı yükle
gecmis = list(durum.get("gecmis") or [])

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

async def sahip_yakala(update, ctx):
    u = update.effective_user
    if u and u.username and u.username.lower() == SAHIP_KULLANICI and durum.get("sahip") != u.id:
        durum["sahip"] = u.id
        durum_kaydet()
        log.info(f"Sahip tanındı: {u.id}")

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

ARAMA_KELIME = {"araştır", "arastir", "haber", "haberi", "güncel", "guncel", "gündem", "gundem",
                "bugün", "bugun", "dün", "dun", "snapshot", "tge", "listelendi", "airdrop"}
ARAMA_IFADE = ("son dakika", "şu an", "ne oldu", "kim kazandı")

def arama_gerek(t):
    k = kucult(t)
    if any(i in k for i in ARAMA_IFADE):
        return True
    return bool(set(re.findall(r"\w+", k)) & ARAMA_KELIME)

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

    # Kalıcı talimat (sadece sahip)
    if sahip_mi(user) and "yapay" in t and any(x in t for x in ("bundan sonra", "bundan böyle", "bundan boyle", "unutma", "aklında tut")):
        s = re.sub(r"(?i)yapay", "", metin).strip(" ,:.")
        durum["talimat"] = (durum["talimat"] + [{"t": s[:300]}])[-20:]
        durum_kaydet()
        await msg.reply_text("Tamam, aklımda 👍")
        return

    # Grupta sadece "yapay" denince veya bota yanıt verilince cevap ver
    if not ozel:
        botun_mesaji = (msg.reply_to_message and msg.reply_to_message.from_user
                        and msg.reply_to_message.from_user.id == ctx.bot.id)
        cagrildi = "yapay" in t or bool(botun_mesaji)
        if not cagrildi:
            return

    await ctx.bot.send_chat_action(chat.id, "typing")

    ek = f"\nŞu an sana yazan kişi: {user.full_name}."
    if sahip_mi(user):
        ek += "\nBu kişi senin patronun (Jimin). Ona karşı çok samimi, sıcak ve itaatkâr ol."
    if durum.get("talimat"):
        ek += ("\nSahibinin kalıcı talimatları (sessizce uy): "
               + " | ".join(x["t"] for x in durum["talimat"][-10:]))

    # TEK ORTAK HAFIZA
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
    await update.effective_message.reply_text("Hafıza sıfırlandı (özel + grup ortak).")

async def hata(update, ctx):
    log.warning(f"Hata: {ctx.error}")

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, sahip_yakala), group=-2)
app.add_handler(CommandHandler("sifirla", sifirla))
app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.UpdateType.MESSAGE, mesaj))
app.add_error_handler(hata)

log.info("Bot başlıyor... (tek ortak hafıza)")
app.run_polling()
