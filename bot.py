import asyncio
import json
import logging
import os
import re
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests
from groq import Groq
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# Gerekli Render Environment Variables:
# TELEGRAM_TOKEN, GROQ_KEY, GEMINI_KEY
# İsteğe bağlı: DEEPSEEK_KEY, CEREBRAS_KEY, OPENROUTER_KEY, MISTRAL_KEY, SAHIP_KULLANICI

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("yapay")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_KEY = os.environ["GROQ_KEY"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_KEY", "")
CEREBRAS_KEY = os.environ.get("CEREBRAS_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
MISTRAL_KEY = os.environ.get("MISTRAL_KEY", "")
SAHIP_KULLANICI = (os.environ.get("SAHIP_KULLANICI") or os.environ.get("SAHIP_USERNAME") or "").lower().lstrip("@")

groq = Groq(api_key=GROQ_KEY)
gem = genai.Client(api_key=GEMINI_KEY)
TR = timezone(timedelta(hours=3))
SISTEM = (
    "Sen grubun samimi, esprili yapay zekâ asistanısın. Adın Yapay. Türkçe konuş. "
    "Kısa ve anlaşılır cevap ver; genellikle 1-2 cümle. Samimi ol, abartılı küfür kullanma. "
    "Konuşma bağlamını takip et. Kullanıcıya sadece bilinen adıyla hitap et. "
    "Model/şirket adını kendiliğinden söyleme. Yatırım veya siyasi yönlendirme yapma. "
    "Bilmediğin bilgiyi uydurma. Sahibinin kalıcı talimatlarına uy. "
    "Airdrop güvenliği gerektiğinde kullanıcıya cüzdanını ve gizli anahtarını kimseyle paylaşmamasını hatırlat."
)
DOSYA = "yapay_durum.json"
TIP_ARALIK = 3 * 60 * 60  # 3 saatte bir otomatik bilgilendirme
try:
    with open(DOSYA, "r", encoding="utf-8") as f:
        durum = json.load(f)
except (OSError, json.JSONDecodeError):
    durum = {}
durum.setdefault("sahip", None)
durum.setdefault("talimat", [])
durum.setdefault("ipucu_gruplari", {})
def kaydet():
    try:
        with open(DOSYA, "w", encoding="utf-8") as f:
            json.dump(durum, f, ensure_ascii=False, indent=2)
    except OSError:
        log.exception("Durum dosyası kaydedilemedi")

gecmis = defaultdict(list)
ARAMA_IFADE = ("araştır", "arastir", "internette ara", "google'da", "google da", "haberleri bul", "güncel bilgi", "guncel bilgi")
ARAMA_KELIME = {"haber", "haberler", "gündem", "gundem", "araştır", "arastir", "airdrop", "tge"}

def kucult(text):
    return (text or "").replace("İ", "i").replace("I", "ı").lower()

def sahip_mi(user):
    if not user:
        return False
    if durum.get("sahip") and int(durum["sahip"]) == user.id:
        return True
    return bool(SAHIP_KULLANICI and user.username and user.username.lower() == SAHIP_KULLANICI)

# Yahoo Finance ve CoinGecko veri çekme bölümleri korunmuştur.
# Fiyat komutları ve otomatik fiyat yanıtları bu bot sürümünde devre dışıdır.

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


def _gemini_icerik(messages):
    return [
        {"role": "model" if item["role"] == "assistant" else "user",
         "parts": [{"text": item["content"]}]}
        for item in messages
    ]

def groq_sor(messages, system):
    last_error = None
    for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"):
        try:
            result = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=350,
            )
            answer = result.choices[0].message.content
            if answer:
                return answer.strip()
        except Exception as exc:
            last_error = exc
            log.warning("Groq %s: %s", model, exc)
    if last_error:
        raise last_error
    return None

def gemini_sor(messages, system, search=False):
    config = types.GenerateContentConfig(system_instruction=system)
    if search:
        config.tools = [types.Tool(google_search=types.GoogleSearch())]
    result = gem.models.generate_content(
        model="gemini-2.5-flash",
        contents=_gemini_icerik(messages),
        config=config,
    )
    return (result.text or "").strip()

def api_chat(url, key, model, messages, system, headers_extra=None):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if headers_extra:
        headers.update(headers_extra)
    response = requests.post(
        url, headers=headers,
        json={"model": model, "messages": [{"role": "system", "content": system}] + messages,
              "temperature": 0.7, "max_tokens": 350},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def sor(messages, extra="", search=False):
    system = SISTEM + extra
    providers = [
        ("Gemini", lambda: gemini_sor(messages, system, search)),
        ("Groq", lambda: groq_sor(messages, system)),
    ]
    if DEEPSEEK_KEY:
        providers.append(("DeepSeek", lambda: api_chat(
            "https://api.deepseek.com/chat/completions", DEEPSEEK_KEY, "deepseek-chat", messages, system)))
    if CEREBRAS_KEY:
        providers.append(("Cerebras", lambda: api_chat(
            "https://api.cerebras.ai/v1/chat/completions", CEREBRAS_KEY, "gpt-oss-120b", messages, system)))
    if OPENROUTER_KEY:
        providers.append(("OpenRouter", lambda: api_chat(
            "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_KEY,
            "meta-llama/llama-3.3-70b-instruct:free", messages, system)))
    if MISTRAL_KEY:
        providers.append(("Mistral", lambda: api_chat(
            "https://api.mistral.ai/v1/chat/completions", MISTRAL_KEY, "mistral-small-latest", messages, system)))
    for name, call in providers:
        try:
            answer = call()
            if answer:
                return re.sub(
                    r"(?i)(tabii ki|anladım\.|başka bir konuda yardımcı olabilir miyim|size yardımcı olmaya hazırım\.?)\s*",
                    "", answer
                ).strip()
        except Exception as exc:
            log.warning("%s sağlayıcısı başarısız: %s", name, exc)
    return None

def gemini_resim(data):
    result = gem.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=data, mime_type="image/jpeg"),
            "Görseldeki yazıları ve içeriği Türkçe, kısa ve doğru biçimde açıkla. Emin olmadığın şeyi uydurma."
        ],
    )
    return (result.text or "").strip()

def arama_gerek(text):
    normalized = kucult(text)
    return any(phrase in normalized for phrase in ARAMA_IFADE) or bool(
        set(re.findall(r"\w+", normalized)) & ARAMA_KELIME
    )


IPUCLARI = [
    "💡 Airdrop güvenliği: Cüzdanının kurtarma kelimelerini (seed phrase) kimseyle paylaşma.",
    "🔐 Hiçbir gerçek destek ekibi senden özel anahtarını veya seed phrase’ini istemez.",
    "🎁 Airdrop duyurularını katılmadan önce projenin resmî kanallarından doğrula.",
    "⚠️ Ücretsiz token vaadiyle cüzdan bağlatan şüpheli bağlantılara dikkat et.",
    "🛡️ İşlemi imzalamadan önce cüzdan ekranındaki izinleri ve işlem ayrıntılarını oku.",
    "🔎 Bir airdrop için para yatırman veya gizli anahtarını vermen isteniyorsa durup kontrol et.",
    "🌐 Proje bağlantısının yazımını kontrol et; sahte siteler resmî siteleri taklit edebilir.",
    "📌 Aynı parolayı farklı platformlarda kullanma; mümkünse iki aşamalı doğrulamayı aç.",
    "🚫 Tanımadığın kişilerin gönderdiği dosya ve bağlantıları açmadan önce doğrula.",
    "✅ Airdrop görevlerini yaparken hangi cüzdanı bağladığını ve hangi izinleri verdiğini kontrol et.",
]

async def otomatik_ipucu_dongusu(app):
    # Grupta botun konuştuğu/etiketlendiği yerleri kayıt altına alır ve 3 saatte bir ipucu yollar.
    while True:
        await asyncio.sleep(60)
        now = time.time()
        gruplar = durum.get("ipucu_gruplari", {})
        for cid, info in list(gruplar.items()):
            try:
                if not info.get("aktif", True):
                    continue
                if now - float(info.get("son_ipucu", 0)) < TIP_ARALIK:
                    continue
                await app.bot.send_message(chat_id=int(cid), text=random.choice(IPUCLARI))
                info["son_ipucu"] = now
                kaydet()
            except Exception as exc:
                log.warning("Otomatik ipucu gönderilemedi (%s): %s", cid, exc)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and sahip_mi(user) and not durum.get("sahip"):
        durum["sahip"] = user.id
        kaydet()
    await update.effective_message.reply_text(
        "Selam! Ben Yapay 🤖 Sohbet edebilir, araştırma yapabilir ve görselleri yorumlayabilirim.\n\n"
        "💡 Bilgilendirme: Airdrop alırken cüzdanını ve gizli anahtarını kimseyle paylaşma."
    )

async def mesaj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not chat or (user and user.is_bot):
        return

    # Grubu otomatik ipucu listesine ekle; özel sohbetler dahil edilmez.
    if chat.type in ("group", "supergroup"):
        cid_key = str(chat.id)
        durum.setdefault("ipucu_gruplari", {}).setdefault(cid_key, {"aktif": True, "son_ipucu": time.time()})
        kaydet()

    # Görselleri de yapay zekâya okut.
    text = (message.text or message.caption or "").strip()
    if message.photo:
        try:
            photo_file = await context.bot.get_file(message.photo[-1].file_id)
            image_bytes = bytes(await photo_file.download_as_bytearray())
            image_text = await asyncio.to_thread(gemini_resim, image_bytes)
            if not text:
                text = "Bu görselde ne var?"
            text += "\n\nGörsel içeriği: " + image_text
        except Exception as exc:
            log.warning("Görsel okunamadı: %s", exc)
            if not text:
                await message.reply_text("Görseli şu an okuyamadım, tekrar dener misin?")
                return
    if not text or text.startswith("/"):
        return

    # Sahibin özel sohbetten verdiği kalıcı AI talimatları.
    if chat.type == "private" and user and sahip_mi(user):
        if not durum.get("sahip"):
            durum["sahip"] = user.id
            kaydet()
        normalized = kucult(text)
        if normalized.startswith("yapay bundan sonra ") or normalized.startswith("bundan sonra "):
            instruction = re.sub(r"(?i)^yapay\s+", "", text).strip()
            instruction = re.sub(r"(?i)^bundan sonra\s+", "", instruction).strip()
            if instruction:
                durum.setdefault("talimat", []).append(instruction)
                durum["talimat"] = durum["talimat"][-30:]
                kaydet()
                await message.reply_text("Tamam, bunu sonraki konuşmalarda uygulayacağım. ✅")
                return
        if normalized in ("yapay talimatları göster", "yapay talimatlari goster", "yapay talimatlar"):
            saved = durum.get("talimat", [])
            await message.reply_text("\n".join(f"• {x}" for x in saved) if saved else "Kayıtlı talimat yok.")
            return
        if normalized in ("yapay talimatları sil", "yapay talimatlari sil", "yapay unut talimatları"):
            durum["talimat"] = []
            kaydet()
            await message.reply_text("Kalıcı talimatları sildim.")
            return
        # Sahip özelden "gruba yaz: ..." derse kayıtlı gruplara gönderme özelliği yoktur.

    is_private = chat.type == "private"
    normalized = kucult(text)

    if not is_private and "yapay" not in normalized and not (
        message.reply_to_message and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == context.bot.id
    ):
        # Bot kullanıcı adıyla etiketlenmişse yanıt verir.
        if not context.bot.username or f"@{context.bot.username.lower()}" not in normalized:
            return

    name = (user.first_name or user.full_name) if user else "dostum"
    extra = f"\nŞu an yazan kişinin adı: {name}. Ona doğal biçimde adıyla hitap edebilirsin."
    if user and sahip_mi(user):
        extra += "\nBu kişi botun sahibidir; talimatlarına uy."
    if durum.get("talimat"):
        extra += "\nSahibinin kalıcı talimatları: " + " | ".join(durum["talimat"][-10:])

    key = (chat.id, user.id if user else (message.sender_chat.id if message.sender_chat else 0))
    history = gecmis[key]
    history.append({"role": "user", "content": text})
    await context.bot.send_chat_action(chat.id, "typing")
    answer = await asyncio.to_thread(sor, history[-16:], extra, arama_gerek(text))
    if not answer:
        answer = "Şu an yanıt oluşturamadım; biraz sonra tekrar dener misin?"
    answer = answer.strip()
    if len(answer) > 1000:
        answer = answer[:997].rsplit(" ", 1)[0] + "..."
    history.append({"role": "assistant", "content": answer})
    gecmis[key] = history[-32:]
    await message.reply_text(answer)

async def hata(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.warning("Telegram bot hatası: %s", context.error)

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, mesaj))
    app.add_error_handler(hata)
    app.create_task(otomatik_ipucu_dongusu(app))
    log.info("Yapay başladı: AI sohbeti, görsel yorumlama, araştırma ve 3 saatlik otomatik ipuçları açık.")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
