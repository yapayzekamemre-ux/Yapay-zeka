import asyncio, html, json, logging, os, re, threading, time, requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, timezone
from groq import Groq
from google import genai
from google.genai import types
from telegram import ChatPermissions
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, PollHandler, filters

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
CEZA_SURE_SN = 120  # oylama max süresi

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
# aktif cezalar: poll_id -> {cid, hedef_id, hedef_ad, baslatan, mid, ...}
aktif_ceza = {}

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

async def hosgeldin(update, ctx):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    grup_kaydet(chat)
    mute_dk = int(durum.get("hosgeldin_mute_dk") or 15)
    sablon = durum.get("hosgeldin_metin") or VARSAYILAN_HOSGELDIN

    for u in msg.new_chat_members:
        if u.is_bot:
            continue
        try:
            await sustur(ctx, chat.id, u.id, mute_dk)
        except Exception as e:
            log.warning(f"Yeni üye susturulamadı: {e}")

        metin = (
            sablon
            .replace("{ad}", u.mention_html())
            .replace("{KullanıcıAdı}", u.mention_html())
            .replace("{kullanici}", u.mention_html())
            .replace("{isim}", html.escape(u.full_name))
            .replace("{mute}", str(mute_dk))
            .replace("{grup}", html.escape(chat.title or ""))
        )
        try:
            gonderilen = await ctx.bot.send_message(chat.id, metin, parse_mode="HTML")
            t = asyncio.create_task(mesaj_sil_gecikmeli(ctx, chat.id, gonderilen.message_id, 5))
            gorevler.add(t)
            t.add_done_callback(gorevler.discard)
        except Exception as e:
            log.warning(f"Hoşgeldin gönderilemedi: {e}")

# ============================================================
# CEZA OYLAMASI
# ============================================================

async def ceza_bitir(ctx, poll_id):
    bil = aktif_ceza.pop(poll_id, None)
    if not bil:
        return
    cid = bil["cid"]
    try:
        # Poll'u durdur ve sonucu al
        poll = await ctx.bot.stop_poll(cid, bil["mid"])
        evet = poll.options[0].voter_count if poll.options else 0
        hayir = poll.options[1].voter_count if len(poll.options) > 1 else 0
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

        m = await ctx.bot.send_message(cid, sonuc, parse_mode="HTML")
        t = asyncio.create_task(mesaj_sil_gecikmeli(ctx, cid, m.message_id, 5))
        gorevler.add(t)
        t.add_done_callback(gorevler.discard)

        # Oylama mesajını da sil
        try:
            await ctx.bot.delete_message(cid, bil["mid"])
        except Exception:
            pass
    except Exception as e:
        log.warning(f"Ceza bitirme hatası: {e}")

async def ceza_baslat(update, ctx, hedef):
    msg = update.effective_message
    chat = update.effective_chat
    baslatan = update.effective_user

    if hedef.id == ctx.bot.id or hedef.id == durum.get("sahip"):
        await msg.reply_text("Buna ceza veremem 😄")
        return

    # Aynı kişiye zaten aktif oylama var mı
    for b in aktif_ceza.values():
        if b["cid"] == chat.id and b["hedef_id"] == hedef.id:
            await msg.reply_text("Bu kişi için zaten oylama var.")
            return

    soru = (
        f"⚠️ Ceza @{hedef.username or hedef.full_name}\n"
        f"🚫 Başlatan @{baslatan.username or baslatan.full_name}\n"
        f"✅ Evet çoğunluk → {CEZA_MUTE_DK} Dk Mesaj Atmasını Kapat • Min {CEZA_MIN_OY} Oy"
    )
    try:
        poll_msg = await ctx.bot.send_poll(
            chat_id=chat.id,
            question=soru[:300],
            options=["✅ Evet", "❌ Hayır"],
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        aktif_ceza[poll_msg.poll.id] = {
            "cid": chat.id,
            "mid": poll_msg.message_id,
            "hedef_id": hedef.id,
            "hedef_ad": hedef.full_name,
            "baslatan": baslatan.id,
            "baslangic": time.time(),
        }
        # Süre dolunca bitir
        async def zamanlayici(pid):
            await asyncio.sleep(CEZA_SURE_SN)
            if pid in aktif_ceza:
                await ceza_bitir(ctx, pid)
        t = asyncio.create_task(zamanlayici(poll_msg.poll.id))
        gorevler.add(t)
        t.add_done_callback(gorevler.discard)
    except Exception as e:
        log.warning(f"Ceza oylaması başlatılamadı: {e}")
        await msg.reply_text("Oylama başlatılamadı (yetki gerekebilir).")

async def poll_guncelle(update, ctx):
    """Oy gelince min oy sayısına ulaştıysa erken bitir."""
    poll = update.poll
    if not poll or poll.id not in aktif_ceza:
        return
    if poll.is_closed:
        return
    toplam = sum(o.voter_count for o in poll.options)
    if toplam >= CEZA_MIN_OY:
        await ceza_bitir(ctx, poll.id)

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

    # CEZA OYLAMASI (grupta)
    if not ozel and "yapay" in t and "ceza" in t:
        hedef = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            hedef = msg.reply_to_message.from_user
        else:
            m = re.search(r"@(\w{4,})", metin)
            if m:
                # sadece username ile bulamayız kolayca, yanıt şart
                await msg.reply_text("Cezalandırılacak kişiye yanıt vererek yaz: yapay ceza")
                return
        if hedef:
            await ceza_baslat(update, ctx, hedef)
            return
        await msg.reply_text("Cezalandırılacak kişiye yanıt vererek yaz: yapay ceza")
        return

    # Karşılama mesajı ayarla (özelde)
    if ozel and sahip_mi(user):
        if any(x in t for x in ("karşılama", "karsilama", "hosgeldin", "hoşgeldin", "welcome")):
            kaynak = None
            if msg.reply_to_message:
                kaynak = msg.reply_to_message.text or msg.reply_to_message.caption
            m = re.search(r"(?:karşılama|karsilama|hosgeldin|hoşgeldin)\s*mesaj[ıi]?\s*[:=]?\s*(.+)", metin, re.I | re.S)
            if m and m.group(1).strip() and "yap" not in m.group(1).lower()[:10]:
                kaynak = m.group(1).strip()
            if not kaynak and any(x in t for x in ("yap", "ayarla", "kaydet", "olsun")):
                if "{ad}" in metin or "Hoşgeldiniz" in metin or "Hoş geldiniz" in metin:
                    kaynak = re.sub(r"(?i).*(?:karşılama|karsilama|hosgeldin|hoşgeldin).*?(?:yap|ayarla|kaydet|olsun)\s*", "", metin).strip() or metin
            if kaynak:
                durum["hosgeldin_metin"] = kaynak
                durum_kaydet()
                await msg.reply_text("✅ Karşılama mesajı kaydedildi.")
                return
        m2 = re.search(r"(?:mute|susturma|sustur)\s*(\d+)", t)
        if m2 and any(x in t for x in ("karşılama", "karsilama", "hosgeldin", "hoşgeldin", "mute")):
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
app.add_handler(PollHandler(poll_guncelle))
app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.UpdateType.MESSAGE, mesaj))
app.add_error_handler(hata)

log.info("Bot başlıyor...")
app.run_polling()
