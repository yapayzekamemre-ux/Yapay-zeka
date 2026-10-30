# -*- coding: utf-8 -*-
"""
TurkPronimBot v2.1
Bolumler: ayarlar | AI | fiyat | panel | moderasyon | duyuru | ipucu |
oyunlar | guvenlik | joblar | mesaj | baslat
Panel: /panel veya /ayarlar (sadece admin)
"""
BOT_SURUM = "v2.7.0"
import pymongo.collection as _pmc
_pmc.Collection.__bool__ = lambda self: True
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
    ChatMemberHandler,
    filters,
    # ChatBoostHandler runtime'da denenir

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

# Hazir egitici / uyari mesajlari — genis havuz, donuste tekrar etmesin
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
    "💡 <b>Köprü riski:</b> Akıllı sözleşme açıkları nedeniyle köprüler risk taşır; fon kaybına yol açabilir.",
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
    "💡 <b>Airdrop:</b> Resmi Discord/Twitter dışında “claim” linkine tıklama.",
    "💡 <b>Snapshot:</b> Tarih geçmiş olabilir; geciken görev işe yaramaz.",
    "💡 <b>Retrodrop:</b> Geçmiş kullanım ödüllendirilir; sahte volume ban getirir.",
    "💡 <b>Galxe / Zealy:</b> Görev botları tespit edilir. İnsan gibi ilerle.",
    "💡 <b>Wallet connect:</b> Tanımadığın siteye cüzdan bağlama.",
    "💡 <b>Permit imza:</b> Sınırsız approve tehlikelidir. Limit koy.",
    "💡 <b>Staking kilidi:</b> Erken çıkış cezasını oku.",
    "💡 <b>Launchpad:</b> KYC ve bölgesel kısıtları önceden kontrol et.",
    "💡 <b>Influencer shill:</b> Ücretli tanıtım olabilir. Kendi araştırman şart.",
    "💡 <b>Fake support:</b> Telegram’da “admin” taklidi seed ister — asla verme.",
    "💡 <b>RPC sahte:</b> Cüzdana elle eklenen ağ/RPC fon çalabilir.",
    "💡 <b>Airdrop ücreti:</b> “Gas için ETH gönder” klasik dolandırıcılık.",
    "💡 <b>Whitelist satış:</b> Önce tokenomics, sonra hype.",
    "💡 <b>Likidite oranı:</b> Market cap’e göre sığ LP = kolay pump-dump.",
    "💡 <b>Kontrat renounce:</b> Owner yetkisi duruyorsa risk devam eder.",
    "💡 <b>Honeypot:</b> Alınır satılmaz token. Simülasyon ile test et.",
    "💡 <b>Twitter space:</b> Sesli vaat ≠ whitepaper. Yazılı kaynağa bak.",
    "💡 <b>Layer2 gas:</b> Bridge + L2 ücreti ayrı; toplam maliyeti hesapla.",
    "💡 <b>Cüzdan yedek:</b> Seed’i çevrimdışı, tek kopya değil güvenli yerde tut.",
    "💡 <b>Borsa çekim:</b> Adres etiketi / memo alanını unutma.",
    "💡 <b>Pump grupları:</b> Koordineli alım sonrası seni exit liquidity yapar.",
    "💡 <b>Domain taklidi:</b> unicоde harfli sahte sitelere dikkat (lookalike).",
    "💡 <b>Airdrop farm:</b> Aynı IP/cihazda onlarca cüzdan = Sybil skoru.",
    "💡 <b>Quest spam:</b> Anlamsız like/rt görevleri düşük kalite sinyalidir.",
    "💡 <b>Token unlock:</b> Büyük unlock gününde satış baskısı gelebilir.",
    "💡 <b>Oracle riski:</b> DeFi protokolünde fiyat beslemesi bozulursa tasfiye olur.",
    "💡 <b>Stablecoin:</b> Hepsi aynı riskte değil; ihraççı ve rezerv oku.",
    "💡 <b>Kaldıraç:</b> Likidasyon aniden gelir. Kaldıracı abartma.",
    "💡 <b>Gece FOMO:</b> Uykusuz karar genelde pahalıya patlar.",
    "💡 <b>Topluluk admin:</b> Ani admin değişimi / silinen mesajlar kırmızı bayrak.",
]

# Temel Turkce kufur kokleri (otomatik engel + ogrenme)
DEFAULT_KUFUR = {
    "amk", "aq", "a.q", "amq", "amına", "amina", "amcık", "amcik", "orospu",
    "oç", "piç", "sikeyim", "sikerim", "siktir", "s.ktir",
    "yarrak", "yarak", "götün", "gerizekalı", "gerizekali",
    "kahpe", "şerefsiz", "serefsiz", "pezevenk", "ibne", "gavat",
    "dalyarak", "sikik", "amına koyayım", "siktirgit", "amkoyayim",
}
_kufur_sayac = defaultdict(lambda: defaultdict(int))  # chat_id -> kelime -> say





# ---------- keep-alive + basit web panel ----------
PANEL_TOKEN = (os.environ.get("PANEL_TOKEN") or os.environ.get("WEB_PANEL_TOKEN") or "").strip()


class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        path = (self.path or "/").split("?")[0]
        qs = {}
        if "?" in (self.path or ""):
            from urllib.parse import parse_qs
            qs = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
        if path in ("/", "/health", "/ping"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
            return
        if path == "/panel":
            tok = qs.get("token") or ""
            if not PANEL_TOKEN or tok != PANEL_TOKEN:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Forbidden - ?token=PANEL_TOKEN")
                return
            # ozet HTML
            gruplar = durum.get("grup") or {}
            rows = []
            for gid, conf in list(gruplar.items())[:30]:
                if not isinstance(conf, dict):
                    continue
                rows.append(
                    f"<tr><td>{gid}</td><td>{conf.get('bot_mod','normal')}</td>"
                    f"<td>{'Y' if conf.get('flood') else '-'}</td>"
                    f"<td>{'Y' if conf.get('link_engel') else '-'}</td>"
                    f"<td>{(conf.get('istatistik') or {}).get('mesaj',0)}</td></tr>"
                )
            html_page = (
                "<html><head><meta charset=utf-8><title>Yapay Panel</title>"
                "<style>body{font-family:sans-serif;background:#111;color:#eee;padding:20px}"
                "table{border-collapse:collapse}td,th{border:1px solid #444;padding:6px}</style></head><body>"
                "<h2>Yapay Bot Panel</h2>"
                "<p>Uptime OK. Detaylı ayar Telegram'dan /panel veya /ozellik.</p>"
                "<table><tr><th>Grup</th><th>Mod</th><th>Flood</th><th>Link</th><th>Mesaj</th></tr>"
                + "".join(rows)
                + "</table></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_page.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

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

SISTEM_TABAN = (
    "Adın Yapay. Bu gruptasın; sohbet eden samimi bir arkadaş gibisin, müşteri hizmeti değilsin.\n"
    "KURALLAR:\n"
    "- Kullanıcı hangi dilde yazarsa o dilde cevap ver.\n"
    "- Kısa ve net: basit soruya 1-2 cümle, zor soruya en fazla 4-5 cümle. Yarım bırakma.\n"
    "- ASLA şunları yazma: 'yardımcı olabilir miyim', 'başka bir konuda', 'nasıl yardımcı olabilirim', "
    "'başka bir şey', 'size yardımcı olayım'. Soru bitince sus; ekstra kapanış cümlesi ekleme.\n"
    "- Robot gibi konuşma. Doğal, içli dışlı, grubun argosuyla konuş.\n"
    "- Bilmiyorsan 'bilmiyorum' de; uydurma.\n"
    "- Canlı haber/skor uydurma.\n"
    "- Al-sat emri verme. Kriptoda gerekirse bir kez 'finansal tavsiye değil' de.\n"
    "- Olgun ol, sulu. Guncel haber/hack bilmiyorsan uydurma, bilmiyorum de/flörtöz olma. Dalga geçilirse kısa zekice cevap ver.\n"
    "- Bot/model adı yazma. Üyeleri isimleriyle tanı.\n"
    "- ESPRİ: İsim veya cümleden komik bağlantı kur; cevap bitince sus.\n"
    "- MATEMATİK: Oran, çarpma, bölme, yüzde sorularında ÖNCE doğru sayıyı hesapla, "
    "sonra 1 kısa espri ekle. Yanlış sayı verme. Örnek: 10k→5 ise 600k→300.\n"
    "- Canlı grup sohbeti gibi ol; kuru resmi dil yok.\n"
)

SISTEM = SISTEM_TABAN  # geriye uyum

# kisi basi AI limit (dakikada)
AI_LIMIT_DK = 20
AI_LIMIT_PENCERE = 60
_ai_limit = defaultdict(lambda: deque())  # uid -> timestamps

# kisi hafiza: ozet + son mesajlar
_hafiza = {}  # key -> {"hist":[], "ozet":"", "ts":0}
_oyun_adam = {}  # chat_id -> oyun dict
_hatirlat_q = []  # {"chat","user","text","at"}  (job ile islenir)

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
_ceza_izle = {}  # (chat_id, uid) -> {until, count, max, ad}
_CEZA_IZLE_LAF = [
    "Cezadan yeni çıktın, artislik yapman şaşkınlık verici 😅",
    "5 dk susup gelince turbo moda mı geçtin? Sakin ol.",
    "Cezan biteli az oldu, yine aynı film mi?",
    "Yeni çıktın cezadan, frene bas — grup da sen de rahat eder.",
    "Az önce susturuldun, şimdi ders almış gibi davranırsan daha iyi olur.",
    "Cezadan çıkış kutlaması ileri geri konuşmak değil bence.",
]

_konusma_aktif = {}  # (chat_id, user_id) -> expire_ts
_fud_buf = defaultdict(lambda: deque())  # chat_id -> timestamps of fud words
_mesaj_hiz = defaultdict(lambda: deque())  # chat_id -> msg timestamps for slow mode
_destek_bilet = {}  # ticket_id -> {user, text, ts}
_son_islem = {}  # chat_id -> {tip, hedef_id, ekstra, ts}
_onay_bekleyen = {}  # oid -> {tip, chat, hedef, by, ts}
_cift_onay = {}  # oid -> {tip, chat, hedef, onaylar:set, ihtiyac}
_spam_ornek = defaultdict(list)  # chat_id -> [normalized spam texts]
_ama = {}  # chat_id -> {aktif, sorular: {qid: {text, oy:set, by}}}
_mesaj_arsiv = defaultdict(lambda: deque(maxlen=400))  # chat_id -> {ts, uid, ad, text}
_SEED_RE = re.compile(
    r"(?i)\b([a-z]+\s+){11,23}[a-z]+\b"
)  # 12-24 kelime seed adayi
_KISISEL_RE = [
    re.compile(r"(?i)\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b"),  # IBAN
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),  # email
    re.compile(r"(?<!\d)(\+90|0)?\s*5\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"),  # TR tel
    re.compile(r"(?<!\d)\d{11}(?!\d)"),  # TC / uzun numara
]
_quiz_duello = {}  # chat_id -> {soru, cevap, a, b, bitis}
_KRIPTO_ARGO = {
    "aya gidiyor": "çok yükseliyor (FOMO dili)",
    "rekt": "büyük zarar etti",
    "rekt oldum": "büyük zarar ettim",
    "dipten aldım": "düşük fiyattan alım yaptım",
    "dipten aldim": "düşük fiyattan alım yaptım",
    "gem": "keşfedilmemiş umutlu proje",
    "ngmi": "not gonna make it — başaramaz",
    "wagmi": "we all gonna make it",
    "hopium": "aşırı iyimser umut",
    "copium": "zararı kabullenme esprisi",
    "ape": "düşünmeden almak",
    "apew": "düşünmeden aldım",
    "lambo": "çok zengin olma hayali",
    "ser": "kripto hitabı (sir)",
    "wen": "ne zaman (listing/moon)",
    "moon": "çok yükselmek",
    "bagholder": "düşen coini tutan",
    "exit liquidity": "başkalarının satışı için alıcı olmak",
}
# sahte domain kalıpları (typosquat)
_SAHTE_DOMAIN = [
    "binnance", "binancе", "binanсe", "binanse", "binancee",
    "coinbasee", "coınbase", "coınbase",
    "metamask", "metamaskk", "meta-mask-airdrop",
    "t.me",  # sadece path süzülür
]
_SAHTE_RE = re.compile(
    r"(?i)\b(binnance|binanse|binancee|binancе|coınbase|coinbasee|"
    r"metamask-airdrop|trustwalleet|pancakeswap[a-z]*\.xyz|"
    r"airdrop-[a-z0-9]+\.(xyz|top|click|loan))\b"
)

_HAFTA_DOLANDIRICI = [
    "Bu hafta numara: <b>sahte airdrop sitesi</b>. Resmi link dışına cüzdan bağlama; gas için ETH isteme klasik tuzak.",
    "Bu hafta numara: <b>sahte destek hesabı</b>. Telegram’da ‘admin’ DM atıp seed/seed phrase asla isteme — gerçek destek istemez.",
    "Bu hafta numara: <b>phishing bot</b>. ‘Ödülünüzü almak için buraya tıklayın’ linkleri cüzdanını boşaltabilir.",
    "Bu hafta numara: <b>sahte listing duyurusu</b>. Borsanın kendi hesabı dışında ‘listelendiniz, ücret yatırın’ mesajlarına inanma.",
    "Bu hafta numara: <b>rugpull / honeypot token</b>. Likidite kilitli mi, kontrat okundu mu — DYOR etmeden alma.",
    "Bu hafta numara: <b>QR kod tuzağı</b>. Bilinmeyen QR ile cüzdan bağlama; önce adresi kendin yaz.",
]
_FUD_KELIME = ("rug", "rugpull", "dump", "scam", "çöktü", "coktu", "battı", "batti", "exit scam", "honeypot")
_MINI_DERS = {
    "cüzdan": "💡 <b>Cüzdan:</b> Kripto anahtarlarını tutan araçtır. Hot (telefon/uzantı) hızlı ama riskli; cold (hardware) daha güvenli.",
    "cuzdan": "💡 <b>Cüzdan:</b> Kripto anahtarlarını tutan araçtır. Hot hızlı ama riskli; cold daha güvenli.",
    "gas": "💡 <b>Gas:</b> Ağda işlem ücretidir. Yoğun saatte artar; acil değilse sakin saat bekle.",
    "seed": "💡 <b>Seed phrase:</b> Cüzdanın ana anahtarıdır. Kimseyle paylaşma; paylaşan mesaj silinir. Gerçek destek asla seed istemez.",
    "seed phrase": "💡 <b>Seed phrase:</b> Cüzdanın ana anahtarıdır. Kimseyle paylaşma; gerçek destek asla seed istemez.",
    "private key": "💡 <b>Private key:</b> Cüzdanın gizli anahtarı. Ekran görüntüsü / sohbet = fon kaybı riski.",
    "airdrop": "💡 <b>Airdrop:</b> Proje token dağıtımı. Resmi link dışına tıklama; gas için ETH isteme klasik dolandırıcılık.",
    "slippage": "💡 <b>Slippage:</b> Emir ile gerçekleşen fiyat farkı. Büyük işlemde parçala veya limit kullan.",
}

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
    "airdrop_yorum": True,  # kanal/airdrop paylasimlarina AI ozet

    "duyuru_aktif": False,
    "duyuru_saat": 5,
    "duyuru_posts": [],
    "ipucu_aktif": False,
    "ipucu_saat": 3,
    "ipucu_last": 0,
    "ipucu_liste": [],
    # --- ozellik anahtarlari ---
    "ozellik": {
        "admin_taklit": True,
        "davet": True,
        "portfoy": True,
        "link_tara": True,
        "guven": True,
        "fed_ban": True,
        "stil_uyum": True,
        "vip": False,
        "balina": False,
        "test_mod": False,
    },
    "davetler": {},       # inviter_id -> sayi
    "guven_puan": {},     # uid -> puan
    "stil_ornek": [],     # grup konusma ornekleri
    "admin_adlar": [],    # cache admin isimleri
    "konusma_sn": 90,     # yapay dedikten sonra devam suresi
    "forward_engel": False,
    "forward_izin": [],  # izinli kaynak chat id veya @username
    "tekrar_mesajlar": [],  # [{id,text,btn,url,saat,last,aktif}]

    "kural_onay": False,
    "yavas_mod_otomatik": False,
    "emoji_tepki": False,
    "moderatorler": [],   # uid list — mute/warn, ban yok
    "bilgi_tabani": [],   # ogretilen bilgiler
    "admin_notlar": [],   # admin not defteri
    "kural_onayli": [],   # uid list
    "istatistik": {"giren": 0, "cikan": 0, "spam": 0, "mesaj": 0},
    "bot_mod": "normal",  # normal | ciddi | eglenceli | sert
    "cift_onay_ban": False,
    "spam_ogren": False,
    "bakim": False,
    "bakim_metin": "🔧 Bakımdayım, birazdan dönerim.",
    "anti_nuke": True,
    "anti_nuke_adet": 5,
    "anti_nuke_sn": 60,
    "gunluk_odul": True,
    "topic_ayar": {},  # thread_id -> {kurallar, bot_mod, ...}
    "sohbet_baslat": True,
    "sohbet_sessiz_saat": 3,
    "yabanci_spam": True,
    "rozetler": {},  # uid -> rozet adi
    "dogum_gunu": {},  # uid -> "MM-DD"
    "gecici_ceza": {},  # uid -> {tip, bitis, uyari_gonderildi}
    "tahmin": None,  # {soru, evet:set, hayir:set, bitis, sonuc}
    "kopru_pin": False,
    "davet_kaynak": {},   # kaynak -> sayi  (twitter, youtube, instagram, diger)
    "gizli_kelime": None,  # {kelime, odul, by}
    "cevap_sil_sn": 90,    # fiyat/komut cevaplari kac sn sonra silinsin (0=kalici)
    "bagis_metin": "",     # bagis adresi/aciklama
    "anon_imza": "Yönetim",
    "sus_bitis": 0,        # unix — bot sessiz
    "oy_mute_min": 6,
    "oy_mute_dk": 5,
    "kriz": False,
    "kriz_yedek": {},       # kriz oncesi ayarlar
    "etkinlik": False,
    "etkinlik_yedek": {},
    "kisilik": "",          # canli karakter (DB)
    "sozluk": {},           # kelime -> aciklama
    "hg_test": False,       # A/B hosgeldin
    "hg_a": "👋 <b>{ad}</b> hoş geldin! Kuralları oku, soru sor.",
    "hg_b": "🚀 <b>{ad}</b> aramıza katıldı. DYOR yap, seed paylaşma!",
    "hg_sayac": {"a": 0, "b": 0, "cikan_a": 0, "cikan_b": 0},
    "hg_uye_versiyon": {},  # uid -> a|b
    "saat_dilimi": {},      # uid -> "Europe/Istanbul" vb
    "ceza_tavan": 10,       # gunluk max ban+mute
    "ceza_gun": {},         # {"tarih": "YYYY-MM-DD", "say": N}
    "golge": False,         # gölge mod — ceza yazma sadece log
    "reaksiyon_yonetim": True,
    "isim_gecmis": {},      # uid -> [{ad, uname, ts}]
    "ai_kota": {},          # provider -> {gun, say}
    "ai_kota_limit": 400,   # gunluk istek / provider yaklasik
    "yasaklilar": [],       # [{uid, ad, uname, sebep, tarih, by, by_ad}]
    "ban_ay": {},           # {"YYYY-MM": say}
    "lakap": {},            # uid -> lakap
    "af_oy": {},            # uid -> {evet:[], hayir:[], mid}
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
    _db_push()


# ---------- kalici DB (Mongo opsiyonel) ----------
_MONGO_URI = (os.environ.get("MONGO_URI") or os.environ.get("MONGODB_URI") or "").strip()
_mongo_col = None
if _MONGO_URI:
    try:
        from pymongo import MongoClient
        _mc = MongoClient(
            _MONGO_URI,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
        )
        # baglanti testi
        _mc.admin.command("ping")
        try:
            db = _mc.get_default_database()
        except Exception:
            db = _mc["turkpronim"]
        _mongo_col = db["bot_state"]
        log.info("MongoDB baglandi: %s", db.name)
    except Exception as e:
        log.warning("Mongo yok/hata (JSON devam): %s", e)
        _mongo_col = None


def _db_push():
    if not _mongo_col:
        return
    try:
        _mongo_col.update_one(
            {"_id": "state"},
            {"$set": {"uyeler": uyeler, "durum": durum, "ts": time.time()}},
            upsert=True,
        )
    except Exception as e:
        log.warning("mongo push: %s", e)


def _db_pull():
    global uyeler, durum
    if not _mongo_col:
        return
    try:
        doc = _mongo_col.find_one({"_id": "state"})
        if not doc:
            return
        if isinstance(doc.get("uyeler"), dict):
            uyeler = doc["uyeler"]
        if isinstance(doc.get("durum"), dict):
            durum = doc["durum"]
            for _k, _v in (("sahip", None), ("talimat", []), ("grup", {}), ("federations", {}), ("fed_bans", {})):
                durum.setdefault(_k, _v)
        log.info("MongoDB state yuklendi")
    except Exception as e:
        log.warning("mongo pull: %s", e)


_db_pull()


def ozellik_acik(chat_id, isim: str) -> bool:
    """Ozellik anahtari — kapaliysa o modul calismaz."""
    oz = cget(chat_id, "ozellik") or {}
    if not isinstance(oz, dict):
        oz = {}
    # test_mod: sadece sahip
    if oz.get("test_mod"):
        return False  # mesaj handler'da sahip kontrolu ayri
    if isim in oz:
        return bool(oz[isim])
    # varsayilan
    return bool((DEFAULT_G.get("ozellik") or {}).get(isim, True))


def ozellik_acik_user(chat_id, isim: str, user) -> bool:
    oz = cget(chat_id, "ozellik") or {}
    if isinstance(oz, dict) and oz.get("test_mod"):
        return sahip_mi(user)
    return ozellik_acik(chat_id, isim)


def guven_get(chat_id, uid) -> int:
    g = cget(chat_id, "guven_puan") or {}
    return int(g.get(str(uid), 50))


def guven_set(chat_id, uid, puan):
    g = dict(cget(chat_id, "guven_puan") or {})
    g[str(uid)] = max(0, min(100, int(puan)))
    cset(chat_id, "guven_puan", g)


def guven_ekle(chat_id, uid, delta):
    guven_set(chat_id, uid, guven_get(chat_id, uid) + delta)


def _benzer_isim(a, b) -> bool:
    """Admin taklidi — kısa isimlerde yanlış eşleşme olmasın."""
    if not a or not b:
        return False
    a, b = kucult(str(a)), kucult(str(b))
    if len(a) < 5 or len(b) < 5:
        return a == b
    if a == b:
        return True
    if (a in b or b in a) and abs(len(a) - len(b)) <= 2:
        return True
    return False


def linkleri_cikar(metin, msg=None):
    urls = []
    if metin:
        urls += re.findall(r"https?://[^\s<>\"']+", metin)
        urls += re.findall(r"(?:t\.me|telegram\.me)/[^\s<>\"']+", metin, re.I)
    if msg and msg.entities:
        for e in msg.entities:
            if e.type in ("url", "text_link") and msg.text:
                if e.type == "text_link" and e.url:
                    urls.append(e.url)
                else:
                    urls.append(msg.text[e.offset : e.offset + e.length])
    return list(dict.fromkeys(urls))


def link_guvenli_mi(url: str):
    """VirusTotal / Safe Browsing (key varsa). Yoksa heuristic."""
    u = (url or "").lower()
    # heuristic tehlikeli
    kotu = ("free-claim", "double-eth", "seed-phrase", "connect-wallet-airdrop",
            "walletconnect-dapp", "metamask-airdrop", "claim-now-eth")
    if any(k in u for k in kotu):
        return False, "şüpheli kalıp"
    vt = (os.environ.get("VIRUSTOTAL_KEY") or "").strip()
    if vt and u.startswith("http"):
        try:
            r = requests.get(
                "https://www.virustotal.com/api/v3/urls",
                headers={"x-apikey": vt},
                timeout=8,
            )
            # VT URL id base64 — basit: search
            r2 = requests.get(
                f"https://www.virustotal.com/api/v3/search?query={requests.utils.quote(url, safe='')}",
                headers={"x-apikey": vt},
                timeout=10,
            )
            if r2.ok:
                data = (r2.json().get("data") or [])
                if data:
                    stats = (data[0].get("attributes") or {}).get("last_analysis_stats") or {}
                    if int(stats.get("malicious") or 0) >= 2:
                        return False, "VirusTotal"
        except Exception as e:
            log.warning("VT: %s", e)
    gsb = (os.environ.get("SAFE_BROWSING_KEY") or "").strip()
    if gsb and u.startswith("http"):
        try:
            body = {
                "client": {"clientId": "turkpronim", "clientVersion": "1.0"},
                "threatInfo": {
                    "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
                    "platformTypes": ["ANY_PLATFORM"],
                    "threatEntryTypes": ["URL"],
                    "threatEntries": [{"url": url}],
                },
            }
            r = requests.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={gsb}",
                json=body,
                timeout=10,
            )
            if r.ok and r.json().get("matches"):
                return False, "Safe Browsing"
        except Exception as e:
            log.warning("GSB: %s", e)
    return True, ""


def fed_ban_ekle(uid, sebep=""):
    fb = durum.setdefault("fed_bans", {})
    fb[str(uid)] = {"sebep": sebep, "ts": time.time()}
    durum_kaydet()


_BAN_KARTLAR = [
    "Reklam yapan arkadaş uçuşa geçti ✈️",
    "Scammer exit liquidity bulamadı, biz bulduk 🚪",
    "Sahte admin denemesi → kalıcı tatil 🏖️",
    "Grup güvenliği 1–0 önde 🛡️",
    "Bu sefer airdrop değil, ban drop 📦",
    "DYOR etmeyen değil, kural bozan gitti 👋",
]


def yasakli_kaydet(chat_id, hedef, sebep, by_user=None):
    lst = list(cget(chat_id, "yasaklilar") or [])
    lst = [x for x in lst if str(x.get("uid")) != str(hedef.id)]
    lst.insert(0, {
        "uid": hedef.id,
        "ad": getattr(hedef, "full_name", None) or str(hedef.id),
        "uname": getattr(hedef, "username", None) or "",
        "sebep": (sebep or "kural ihlali")[:80],
        "tarih": time.strftime("%Y-%m-%d %H:%M"),
        "by": getattr(by_user, "id", None) if by_user else None,
        "by_ad": (getattr(by_user, "full_name", None) or "") if by_user else "",
    })
    cset(chat_id, "yasaklilar", lst[:100])
    ay = time.strftime("%Y-%m")
    ba = dict(cget(chat_id, "ban_ay") or {})
    ba[ay] = int(ba.get(ay) or 0) + 1
    cset(chat_id, "ban_ay", ba)


def yasakli_sil(chat_id, uid):
    lst = [x for x in (cget(chat_id, "yasaklilar") or []) if str(x.get("uid")) != str(uid)]
    cset(chat_id, "yasaklilar", lst)



# Mesaj sayisi kademeleri
_MESAJ_KADEMELER = [
    (0, "Yeni Yüz"),
    (30, "Çaylak"),
    (200, "Aktif"),
    (500, "Deneyimli"),
    (1000, "Usta"),
    (3000, "Efsane"),
]


def mesaj_kademe(mesaj_s: int):
    """(kademe_adi, min_esik, sonraki_esik|None)"""
    n = int(mesaj_s or 0)
    cur_name, cur_min = _MESAJ_KADEMELER[0]
    sonraki = _MESAJ_KADEMELER[1][0] if len(_MESAJ_KADEMELER) > 1 else None
    for i, (thr, name) in enumerate(_MESAJ_KADEMELER):
        if n >= thr:
            cur_name, cur_min = name, thr
            sonraki = _MESAJ_KADEMELER[i + 1][0] if i + 1 < len(_MESAJ_KADEMELER) else None
        else:
            break
    return cur_name, cur_min, sonraki


async def kademe_tebrik(bot, chat_id, user, uy):
    """Belirli mesaj esigine ulasinca gruba kisa tebrik."""
    if not user or not uy:
        return
    n = int(uy.get("mesaj") or 0)
    for thr, name in _MESAJ_KADEMELER:
        if thr > 0 and n == thr:
            ad = html.escape(user.first_name or user.full_name or "Üye")
            try:
                await bot.send_message(
                    chat_id,
                    f"🏅 <b>{ad}</b> kademe atladı: <b>{html.escape(name)}</b> ({n} mesaj)!",
                    parse_mode="HTML",
                )
            except Exception as e:
                log.warning("kademe tebrik: %s", e)
            break


def lakap_hesapla(chat_id, uid) -> str:
    uy = (uyeler.get(str(chat_id)) or {}).get(str(uid)) or {}
    m = int(uy.get("mesaj") or 0)
    g = guven_get(chat_id, uid)
    if m > 500 and g >= 70:
        return "Hodl Ustası"
    if m > 200:
        return "Dip Avcısı"
    if g >= 80:
        return "Güvenilir Ser"
    if m > 50:
        return "Chat Warrior"
    if m > 10:
        return "Çaylak Trader"
    return "Yeni Yüz"


def fed_banli_mi(uid) -> bool:
    return str(uid) in (durum.get("fed_bans") or {})


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
    eski_ad = u.get("ad") or ""
    eski_un = u.get("kullanici") or ""
    yeni_ad = user.full_name or ""
    yeni_un = (user.username or "").lower()
    if (eski_ad and yeni_ad and eski_ad != yeni_ad) or (eski_un and yeni_un and eski_un != yeni_un):
        gec = list(u.get("isim_gecmis") or [])
        gec.append({"ad": eski_ad, "un": eski_un, "ts": time.strftime("%Y-%m-%d")})
        u["isim_gecmis"] = gec[-10:]
        # grup geneli de
        ig = dict(cget(chat_id, "isim_gecmis") or {})
        lst = list(ig.get(str(user.id)) or [])
        lst.append({"ad": eski_ad, "un": eski_un, "ts": time.strftime("%Y-%m-%d")})
        ig[str(user.id)] = lst[-10:]
        cset(chat_id, "isim_gecmis", ig)
    u["ad"] = yeni_ad or u.get("ad", "")
    u["kullanici"] = yeni_un
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


async def _kuyruk_worker(bot):
    """Telegram flood onlemek icin mesajlari yavas gonder."""
    global _msg_q
    while True:
        try:
            item = await _msg_q.get()
            if not item:
                continue
            kw = dict(item)
            sil_sn = kw.pop("_sil", None)
            try:
                m = await bot.send_message(**kw)
                if sil_sn and m:
                    asyncio.create_task(sil_sonra(bot, kw.get("chat_id"), m.message_id, sil_sn))
            except Exception as e:
                err = str(e)
                _hata_log.append(f"{time.strftime('%H:%M:%S')} send: {err[:120]}")
                if "RetryAfter" in err or "Flood" in err or "Too Many" in err:
                    await asyncio.sleep(5)
                log.warning("kuyruk send: %s", e)
            await asyncio.sleep(0.05)  # ~20 msg/sn ust sinir yumusak
        except Exception as e:
            log.warning("kuyruk: %s", e)
            await asyncio.sleep(1)


def _kuyruk_baslat(bot):
    global _msg_q
    if _msg_q is None:
        _msg_q = asyncio.Queue()
        asyncio.create_task(_kuyruk_worker(bot))


async def guvenli_gonder(bot, chat_id, text, parse_mode="HTML", sil=None, **extra):
    """Kuyruklu gonderim."""
    _kuyruk_baslat(bot)
    payload = {"chat_id": chat_id, "text": text, "_sil": sil}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    payload.update(extra)
    await _msg_q.put(payload)


async def kisa_cevap(bot, chat_id, text, sn=8, sahip_kopya=True):
    try:
        _kuyruk_baslat(bot)
        # hizli yol: kisa cevaplar yine await (onay/feedback)
        m = await bot.send_message(chat_id, text, parse_mode="HTML")
        if sn:
            asyncio.create_task(sil_sonra(bot, chat_id, m.message_id, sn))
        # sahip ozelden yonetiyorsa gruba giden ozeti DM'de de gorsun
        if sahip_kopya and SAHIP_ID and int(chat_id) != int(SAHIP_ID):
            try:
                if _aktif_grup_id() and int(chat_id) == int(_aktif_grup_id()):
                    await bot.send_message(SAHIP_ID, f"↪️ grup <code>{chat_id}</code>\n{text}", parse_mode="HTML")
            except Exception:
                pass
        return m
    except Exception as e:
        err = str(e)
        _hata_log.append(f"{time.strftime('%H:%M:%S')} kisa: {err[:120]}")
        if "RetryAfter" in type(e).__name__ or "Flood" in err:
            await asyncio.sleep(3)
            try:
                return await bot.send_message(chat_id, text, parse_mode="HTML")
            except Exception:
                pass
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


# ---------- web arama (ucretsiz, guncel bilgi) ----------
_web_cache = {}

def _rss_basliklar(limit=10):
    """CoinDesk + Cointelegraph son basliklar."""
    out = []
    for feed in (
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ):
        try:
            rr = requests.get(feed, timeout=9, headers={"User-Agent": "Mozilla/5.0 TurkPronimBot"})
            if not rr.ok:
                continue
            titles = re.findall(
                r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                rr.text,
                re.I | re.S,
            )
            for title in titles[1:12]:
                title = re.sub(r"<[^>]+>", "", html.unescape(title))
                title = re.sub(r"\s+", " ", title).strip()
                low = title.lower()
                if not title or len(title) < 20:
                    continue
                if "coindesk" in low or "cointelegraph" in low:
                    continue
                out.append("• " + title[:220])
        except Exception as e:
            log.warning("rss: %s", e)
    # tekil
    seen, uniq = set(), []
    for x in out:
        k = x[:50].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq[:limit]


def web_arama(sorgu: str, limit: int = 6) -> str:
    """RSS once, sonra DDG. Guncel olaylar icin RSS zorunlu."""
    q = (sorgu or "").strip()[:140]
    if not q:
        return ""
    now = time.time()
    ck = q.lower()
    if ck in _web_cache and now - _web_cache[ck][0] < 120:
        return _web_cache[ck][1]

    parcalar = []
    low_q = q.lower()
    # her zaman RSS (kripto guncel)
    try:
        rss = _rss_basliklar(12)
        # sorguyla ilgili basliklari one al
        anahtar = [w for w in re.split(r"\W+", low_q) if len(w) > 2]
        ilgili, diger = [], []
        for b in rss:
            bl = b.lower()
            if any(a in bl for a in anahtar):
                ilgili.append(b)
            else:
                diger.append(b)
        parcalar.extend(ilgili[:8])
        # genel gundem / haber sorgusunda hepsini ekle
        if any(x in low_q for x in ("haber", "gündem", "gundem", "news", "bugün", "bugun", "crypto")):
            for b in diger:
                if b not in parcalar:
                    parcalar.append(b)
                if len(parcalar) >= 10:
                    break
        elif not ilgili and diger:
            # spesifik sorgu eslesmedi — yine de son haberleri ver (Binance vs)
            parcalar.extend(diger[:5])
    except Exception as e:
        log.warning("rss block: %s", e)

    # DDG instant — birden fazla sorgu varyanti
    varyantlar = [q]
    if "2026" in q and "hack" in low_q:
        varyantlar.append(q.replace("2026", "").strip())
        varyantlar.append("Binance hack October 2026")
        varyantlar.append("Binance security incident")
    for v in varyantlar[:3]:
        try:
            r = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": v, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=8,
                headers={"User-Agent": "Mozilla/5.0 TurkPronimBot"},
            )
            if r.ok:
                d = r.json()
                if d.get("AbstractText"):
                    parcalar.append(d["AbstractText"][:400])
                for tpc in (d.get("RelatedTopics") or [])[:3]:
                    if isinstance(tpc, dict) and tpc.get("Text"):
                        parcalar.append(tpc["Text"][:200])
        except Exception as e:
            log.warning("ddg instant: %s", e)

    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": q},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TurkPronimBot/2.7)"},
        )
        if r.ok:
            texts = re.findall(
                r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
                r.text,
                flags=re.I | re.S,
            )
            for raw in texts[:limit]:
                clean = re.sub(r"<[^>]+>", " ", raw)
                clean = re.sub(r"\s+", " ", clean).strip()
                if len(clean) > 40:
                    parcalar.append(clean[:280])
    except Exception as e:
        log.warning("ddg html: %s", e)

    seen, uniq = set(), []
    for p0 in parcalar:
        k = p0[:55].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p0)
    out = "\n".join(uniq[:12])
    _web_cache[ck] = (now, out)
    if len(_web_cache) > 80:
        for k in list(_web_cache.keys())[:25]:
            _web_cache.pop(k, None)
    return out


def groq_sor(m, sistem):
    if not groq:
        return None
    for model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-20b", "openai/gpt-oss-120b"):
        try:
            r = groq.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sistem}] + m,
                temperature=0.7,
                max_tokens=400,
            )
            t = (r.choices[0].message.content or "").strip()
            if t and len(t) >= 2:
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
                    system_instruction=sistem, temperature=0.7, max_output_tokens=400
                ),
            )
            t = (getattr(r, "text", None) or "").strip()
            if t:
                return t
        except Exception as e:
            log.warning("Gemini %s: %s", model, e)
    return None



def gemini_gorsel_sor(prompt: str, image_bytes: bytes, mime: str = "image/jpeg", sistem: str = None):
    """Resim + metin → Gemini vision."""
    if not gem or not image_bytes:
        return None
    sistem = sistem or SISTEM_TABAN
    prompt = (prompt or "Bu görseli kısa ve net açıkla. Türkçe cevap ver.").strip()
    for model in (
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ):
        try:
            r = gem.models.generate_content(
                model=model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime),
                            types.Part.from_text(text=prompt),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    system_instruction=str(sistem)
                    + "\nKullanıcı resim gönderdi. Resmi gerçekten incele, uydurma. Kısa ve samimi Türkçe cevap ver.",
                    temperature=0.6,
                    max_output_tokens=500,
                ),
            )
            out = (getattr(r, "text", None) or "").strip()
            if out:
                return out
        except Exception as e:
            log.warning("Gemini vision %s: %s", model, e)
    return None


async def mesajdan_foto_indir(bot, msg):
    """Mesaj veya yanitlanan fotoyu indir. (bytes, mime) veya None."""
    if not msg:
        return None
    hedef = msg
    if not getattr(msg, "photo", None) and msg.reply_to_message and getattr(msg.reply_to_message, "photo", None):
        hedef = msg.reply_to_message
    if not getattr(hedef, "photo", None):
        doc = getattr(hedef, "document", None)
        if doc and (getattr(doc, "mime_type", None) or "").startswith("image/"):
            try:
                f = await bot.get_file(doc.file_id)
                raw = bytes(await f.download_as_bytearray())
                return raw, doc.mime_type or "image/jpeg"
            except Exception as e:
                log.warning("doc foto: %s", e)
                return None
        return None
    try:
        ph = hedef.photo[-1]
        f = await bot.get_file(ph.file_id)
        raw = bytes(await f.download_as_bytearray())
        return raw, "image/jpeg"
    except Exception as e:
        log.warning("foto indir: %s", e)
        return None


def deepseek_sor(m, sistem):
    if not DEEPSEEK_KEY:
        return None
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            json={"model": "deepseek-chat", "messages": [{"role": "system", "content": sistem}] + m, "max_tokens": 400},
            timeout=15,
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
            json={"model": "mistral-small-latest", "messages": [{"role": "system", "content": sistem}] + m, "max_tokens": 400},
            timeout=15,
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
                    "max_tokens": 400,
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


def _zor_soru_mu(soru: str) -> bool:
    s = (soru or "").lower()
    if len(s) > 120:
        return True
    anahtar = (
        "neden", "nasıl", "nasil", "açıkla", "acikla", "fark", "karşılaştır",
        "karsilastir", "analiz", "strateji", "risk", "hukuk", "sağlık", "saglik",
        "yatırım", "yatirim", "tokenomics", "whitepaper", "airdrop", "kontrakt",
        "why", "how", "explain", "compare", "analysis",
    )
    return sum(1 for k in anahtar if k in s) >= 1 and len(s) > 40


def _duygu_algila(soru: str) -> str:
    s = (soru or "").lower()
    uzgun = ("üzgün", "uzgun", "kötü", "kotu", "mutsuz", "ağlıyorum", "aglıyorum",
             "depres", "canım sıkkın", "canim sikkin", "berbat", "yıkıldım", "yikildim")
    sinir = ("sinir", "kızgın", "kizgin", "öfkeli", "ofkeli", "sinirlendim", "bıktım",
             "biktım", "nefret", "lanet", "deliricem", "sinirliyim")
    if any(x in s for x in uzgun):
        return "uzgun"
    if any(x in s for x in sinir):
        return "sinir"
    return "notr"


def _hassas_mi(soru: str) -> bool:
    s = (soru or "").lower()
    return any(x in s for x in (
        "al mı", "al mi", "sat mı", "sat mi", "yatırım", "yatirim", "tavsiye",
        "sağlık", "saglik", "doktor", "ilaç", "ilac", "hukuk", "dava", "avukat",
        "leverage", "kaldıraç", "kaldirac", "all in",
    ))


def _bot_mod_metin(chat_id):
    m = (cget(chat_id, "bot_mod") or "normal").lower()
    if m == "ciddi":
        return "Ton: ciddi ve resmi. Espri yapma."
    if m in ("eglenceli", "eğlenceli"):
        return "Ton: samimi ve hafif esprili; yine de kısa tut."
    if m == "sert":
        return "Ton: sert ve net. Uyarıları kesin söyle; yumuşatma."
    return "Ton: olgun ve dengeli."


def _sistem_dinamik(ek="", duygu="notr", zor=False, dil_ipucu="", chat_id=None):
    parca = [SISTEM_TABAN]
    if chat_id is not None:
        parca.append(_bot_mod_metin(chat_id))
    if duygu == "uzgun":
        parca.append("Kullanıcı üzgün görünüyor: espri yapma, sakin ve destekleyici ol.")
    elif duygu == "sinir":
        parca.append("Kullanıcı sinirli: sakin, kısa, kışkırtma.")
    else:
        parca.append("Nötr tonda kal; moda uy.")
    if zor:
        parca.append("Bu soru biraz zor: net ve biraz daha detaylı cevap ver (yine kısa tut).")
    else:
        parca.append("Kolay soru: tek kısa cümle yeterli.")
    if dil_ipucu:
        parca.append(dil_ipucu)
    if ek:
        parca.append(ek)
    return "\n".join(parca)


def _ai_limit_ok(uid) -> bool:
    now = time.time()
    q = _ai_limit[str(uid)]
    while q and now - q[0] > AI_LIMIT_PENCERE:
        q.popleft()
    if len(q) >= AI_LIMIT_DK:
        return False
    q.append(now)
    return True


def _hafiza_key(chat_id, user_id):
    return f"{chat_id}:{user_id}"


def _hafiza_al(key):
    h = _hafiza.get(key) or {"hist": [], "ozet": "", "ts": 0}
    return h


def _hafiza_ozetle(key):
    """Uzun sohbeti tek paragrafa indir."""
    h = _hafiza_al(key)
    hist = h.get("hist") or []
    if len(hist) < 10:
        return
    metin = " | ".join(
        f"{x.get('role','')}: {x.get('content','')[:80]}" for x in hist[-16:]
    )
    sistem = "Turkce, max 2 cumle. Bu sohbeti ozetle; isimleri ve konuyu koru."
    m = [{"role": "user", "content": metin[:1500]}]
    ozet = None
    for fn in (groq_sor, gemini_sor, deepseek_sor):
        try:
            ozet = cevap_temizle(fn(m, sistem))
        except Exception:
            ozet = None
        if ozet:
            break
    if ozet:
        h["ozet"] = ozet[:400]
        h["hist"] = hist[-4:]
        h["ts"] = time.time()
        _hafiza[key] = h


def _ai_kota_asildi(ad: str) -> bool:
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    kota = durum.setdefault("ai_kota_global", {})
    bag = dict(kota.get(ad) or {})
    if bag.get("gun") != bugun:
        return False
    limit = int(durum.get("ai_kota_limit") or 400)
    return int(bag.get("say") or 0) >= limit


def _ai_kota_artir(ad: str):
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    kota = durum.setdefault("ai_kota_global", {})
    bag = dict(kota.get(ad) or {})
    if bag.get("gun") != bugun:
        bag = {"gun": bugun, "say": 0}
    bag["say"] = int(bag.get("say") or 0) + 1
    kota[ad] = bag
    # sik yazma — her 10da bir
    if bag["say"] % 10 == 0:
        try:
            durum_kaydet()
        except Exception:
            pass


def _sor_modeller(mesajlar, sistem, hizli=True):
    """hizli: kucuk modeller once; guclu: buyukler once. Limitte sonrakine gec."""
    if hizli:
        sira = (groq_sor, gemini_sor, mistral_sor, deepseek_sor, openrouter_sor)
    else:
        sira = (deepseek_sor, groq_sor, gemini_sor, openrouter_sor, mistral_sor)
    for fn in sira:
        ad = getattr(fn, "__name__", str(fn))
        if _ai_kota_asildi(ad):
            continue
        t0 = time.time()
        try:
            t = cevap_temizle(fn(mesajlar, sistem))
        except Exception as e:
            log.warning("model fail %s: %s", ad, e)
            t = None
            _hata_log.append(f"{time.strftime('%H:%M:%S')} {ad}: {str(e)[:100]}")
        _ai_latans[ad] = int((time.time() - t0) * 1000)
        if t:
            _ai_kota_artir(ad)
            return t
    return None


def _ikinci_kontrol(soru, yanit):
    """Onemli cevapta hizli dogruluk kontrolu."""
    sistem = (
        "Sadece OK veya DUZELT: satir yaz. "
        "Cevap uydurma/yanlis fiyat/tehlikeli tavsiye iceriyorsa DUZELT: kisa dogru metin."
    )
    m = [{"role": "user", "content": f"Soru: {soru[:200]}\nCevap: {yanit[:300]}"}]
    t = _sor_modeller(m, sistem, hizli=True)
    if not t:
        return yanit
    if t.upper().startswith("OK"):
        return yanit
    if t.upper().startswith("DUZELT") or t.upper().startswith("DÜZELT"):
        duz = t.split(":", 1)[-1].strip()
        return duz or yanit
    return yanit


def sor(mesajlar, ek="", zor=False, duygu="notr", soru_metin="", chat_id=None):
    sistem = _sistem_dinamik(ek=ek, duygu=duygu, zor=zor, chat_id=chat_id)
    yanit = _sor_modeller(mesajlar, sistem, hizli=not zor)
    if not yanit:
        yanit = _sor_modeller(mesajlar, sistem, hizli=zor)  # ters sira dene
    if not yanit:
        return "Biraz yoğunum, sonra tekrar dene."
    if _hassas_mi(soru_metin) or zor:
        try:
            yanit = _ikinci_kontrol(soru_metin or "", yanit)
        except Exception:
            pass
    if _hassas_mi(soru_metin) and "tavsiye değildir" not in yanit.lower() and "tavsiye degildir" not in yanit.lower():
        if any(x in (soru_metin or "").lower() for x in ("yatırım", "yatirim", "al mı", "sat mı", "kaldıraç", "kaldirac")):
            yanit = yanit.rstrip(".") + ". (Finansal tavsiye değildir.)"
    return yanit


# ---------- fiyat (Claude mimari: snapshot + cooldown + rank) ----------
CG_BASE = "https://api.coingecko.com/api/v3"
CG_CACHE = "cg_snap.json"
CG_PAGES = 8
CG_STEP = 20  # sayfalar arasi sn (~3 istek/dk)

# parca birlestir — yuzlerce farkli tam cumle
_FIYAT_ESPRI_SON = []
_Y_A = [
    "boğa canlanıyor", "yeşil mumlar geldi", "hafif pump var", "alım baskısı arttı",
    "trend yukarı", "momentum geldi", "cüzdan gülümsüyor", "hop diye çıktı",
    "ayılar geriledi", "chart mutlu", "küçük sıçrama var", "yeşil ışık yandı",
]
_Y_B = [
    "cüzdan keyifli", "iyi gidiyor", "sakin izle", "acele etme",
    "boğa dansı gibi", "umut yeşerdi", "nefes almak iyi", "takip et yeter",
]
_D_A = [
    "kırmızı mumlar geldi", "satış baskısı var", "cüzdan inceldi", "chart üzgün",
    "ayı baskın", "soğuk duş oldu", "biraz geriledi", "düzeltme kokusu var",
    "geçici kanama gibi", "panik havası var", "dip mi geliyor", "su döküldü",
]
_D_B = [
    "sakin kal", "panik yapma", "nefes al", "acele satma",
    "hold düşün", "sakin izle", "geçici olabilir", "soğukkanlı ol",
]
_T_A = [
    "yatay sürünüyor", "sessiz piyasa", "fiyat uyuyor", "dar bantta",
    "ne boğa ne ayı", "kıprıtı yok", "donmuş chart", "ufak titreşim",
]
_T_B = [
    "net yön yok", "bekle gör", "sabır zamanı", "sıkıcı ama normal",
    "büyük hareket yok", "izle yeter", "sakin sakin", "acele yok",
]


def _espri_uret(yon: str) -> str:
    """Her seferinde farkli tam cumle; son 12 tekrar etmez."""
    import random
    if yon == "up":
        a, b = _Y_A, _Y_B
    elif yon == "down":
        a, b = _D_A, _D_B
    else:
        a, b = _T_A, _T_B
    for _ in range(30):
        cumle = f"{random.choice(a)}, {random.choice(b)}"
        if cumle not in _FIYAT_ESPRI_SON[-12:]:
            _FIYAT_ESPRI_SON.append(cumle)
            if len(_FIYAT_ESPRI_SON) > 40:
                del _FIYAT_ESPRI_SON[:-30]
            return cumle
    cumle = f"{random.choice(a)}, {random.choice(b)}"
    _FIYAT_ESPRI_SON.append(cumle)
    return cumle

_CG_ALIAS = {"ton": "the-open-network", "gram": "the-open-network", "toncoin": "the-open-network"}
_cg_by_id = {}
_cg_by_symbol = {}  # symbol -> [coin, ...] rank sirali
_cg_miss = {}       # symbol -> miss_until
_cg_cooldown_until = 0.0
_cg_lock = threading.Lock()
_fiyat_cache = {}  # sembol -> (ts, bil)
_FIYAT_CACHE_SN = 30
_nuke_buf = defaultdict(lambda: deque())  # (chat, admin_id) -> timestamps
_hata_log = deque(maxlen=40)  # son hatalar
_msg_queue = asyncio.Queue() if False else None  # lazy init
_msg_q = None
_son_grup_mesaj = {}  # chat_id -> ts
_ai_latans = {}  # provider -> ms

KISA = re.compile(
    r"(?i)^\s*(?:(\d+(?:[.,]\d+)?)\s+)?"
    r"(?:\$|fiyat\s+|price\s+)?"
    r"([a-zA-Z][a-zA-Z0-9]{1,15})"
    r"(?:\s+(?:fiyat|price|ne kadar|kaç|kac))?$"
)
_FIYAT_NIYET = re.compile(r"(?i)(\d|\$|\bfiyat\b|\bprice\b|\bne kadar\b|\bkaç\b|\bkac\b)")
_BILINEN_DOVIZ = {
    "usd", "usdt", "dolar", "eur", "euro", "gbp", "sterlin",
    "altin", "gold", "ons", "gumus", "silver",
}
_ATLA = {
    "tl", "try", "gb", "mb", "kg", "tane", "adet", "saat", "gun", "dk", "sn",
    "lira", "fiyat", "price", "yapay", "ne", "naber", "merhaba", "selam", "sa",
    "as", "nbr", "iyi", "iyiyim", "nasilsin", "tamam", "ok", "evet", "hayir",
    "yok", "var", "lan", "abi", "knk", "bro", "anlamadim", "anlamadım",
    "etmiyorum", "belki", "ben", "sen", "biz", "bu", "su", "kim", "neden",
    "nasil", "ceza", "bot", "grup", "mesaj", "chat", "link", "amk", "aq",
    "aslan", "bildin", "aklan", "tamamdır", "tamamdir", "haha", "lol",
}


def _re_sub_yapay(metin: str) -> str:
    return re.sub(r"(?i)\byapay\b", "", metin or "").strip()


# Bot cagri kelimeleri (tam kelime eslesme)
_YAPAY_TETIK = (
    "yapay", "yapayım", "yapayim", "yapaydım", "yapaydim",
    "yapayız", "yapayiz", "yapaya", "yapayı", "yapayi",
    "yapayla", "yapaymı", "yapaymi", "yapaymis", "yapaymış",
)


def basit_oran_hesap(metin: str):
    """10k hacime 5 gidiyor 600k kaç gider → 300 gibi oran sorulari."""
    if not metin:
        return None
    low = kucult(metin)
    if not any(x in low for x in ("kaç", "kac", "ne kadar", "kaçtır", "kactir", "gider", "eder", "olur")):
        return None
    # sayilari cek: 10k, 600k, 5, 10.5
    def parse_num(s):
        s = s.lower().replace(",", ".")
        carp = 1
        if s.endswith("k"):
            carp = 1000
            s = s[:-1]
        if s.endswith("m"):
            carp = 1000000
            s = s[:-1]
        try:
            return float(s) * carp
        except Exception:
            return None
    nums = re.findall(r"\d+(?:[.,]\d+)?[kKmM]?", metin)
    vals = [parse_num(x) for x in nums]
    vals = [v for v in vals if v is not None]
    if len(vals) < 3:
        return None
    a, b, c = vals[0], vals[1], vals[2]
    if a == 0:
        return None
    # a hacme b sonuç → c hacme ?
    sonuc = b * (c / a)
    if abs(sonuc - round(sonuc)) < 1e-6:
        sonuc = int(round(sonuc))
    else:
        sonuc = round(sonuc, 2)
    return sonuc


def yapay_geciyor(metin: str) -> bool:
    """yapay + ek cekim/yazimlar (yapayım, yapaydım...)."""
    if not metin:
        return False
    low = kucult(metin)
    for k in _YAPAY_TETIK:
        if re.search(r"(?i)\b" + re.escape(k) + r"\b", low):
            return True
    return False


def _coin_snapshot_top(sembol: str, max_rank: int = 300) -> bool:
    """API cagrisi yok; sadece snapshot rank."""
    q = (sembol or "").strip().lower()
    if not q:
        return False
    if q in _BILINEN_DOVIZ:
        return True
    alias_map = globals().get("_CG_ALIAS") or {}
    aid = alias_map.get(q)
    coin = None
    if aid and aid in _cg_by_id:
        coin = _cg_by_id[aid]
    if coin is None:
        lst = _cg_by_symbol.get(q) or []
        if lst:
            coin = lst[0]
    if coin is None:
        return False
    rank = coin.get("market_cap_rank")
    if rank is None:
        return False
    try:
        return int(rank) <= max_rank
    except Exception:
        return False


def kisa_token(metin):
    """(miktar, sembol, niyetli) veya None. Niyetsiz rastgele kelimeye API yok."""
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
    niyet = bool(_FIYAT_NIYET.search(t)) or bool(m.group(1))
    if not niyet and not _coin_snapshot_top(s):
        return None
    return (miktar, s, niyet)


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
    # 30 sn onbellek — CoinGecko limit + hiz
    hit = _fiyat_cache.get(q)
    if hit and time.time() - hit[0] < _FIYAT_CACHE_SN:
        return dict(hit[1]) if isinstance(hit[1], dict) else hit[1]
    bil = None
    # doviz / altin (gram coin CG'de TON; altin = "altin")
    if q in ("usd", "dolar", "usdt", "eur", "euro", "gbp", "sterlin", "altin", "gold", "ons", "gumus", "silver"):
        bil = _yahoo_fiyat(q)
    if not bil:
        bil = _coingecko_fiyat(q)
    if not bil and q.isalpha() and 3 <= len(q) <= 6:
        bil = _yahoo_fiyat(q)
    if bil:
        _fiyat_cache[q] = (time.time(), bil)
        # cache buyumesin
        if len(_fiyat_cache) > 300:
            eski = sorted(_fiyat_cache.items(), key=lambda x: x[1][0])[:80]
            for k, _ in eski:
                _fiyat_cache.pop(k, None)
    return bil


async def fiyat_gonder(update, miktar, sembol, niyetli=False):
    bil = fiyat_cek(sembol)
    if not bil:
        if not niyetli:
            return False
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
    ch = bil.get("ch")
    name = str(bil.get("s") or sembol).upper()
    link = bil.get("link") or ""
    adet = f"{miktar:g} " if miktar != 1 else ""
    usd = bil.get("usd")
    try_p = bil.get("try")
    if usd is not None:
        u = float(usd) * miktar
        if u < 0.0001:
            fiyat_satir = f"${u:.8f} Usdt"
        elif u < 1:
            fiyat_satir = f"${u:.4f} Usdt"
        else:
            fiyat_satir = f"${u:,.2f} Usdt"
    elif try_p is not None:
        fiyat_satir = f"₺{float(try_p) * miktar:,.2f}"
    else:
        fiyat_satir = "—"
    try_line = ""
    if usd is not None and try_p is not None:
        try_line = f"\n🇹🇷 ₺{float(try_p) * miktar:,.2f}"

    # her seferinde farkli tam cumle
    if ch is not None and float(ch) >= 0.3:
        ikon = "📈"
        espri = f"%{float(ch):.2f} yükseldi — {_espri_uret('up')}"
    elif ch is not None and float(ch) <= -0.3:
        ikon = "⛔"
        espri = f"%{abs(float(ch)):.2f} düştü — {_espri_uret('down')}"
    else:
        ikon = "💬"
        ch_s = f"{abs(float(ch)):.2f}" if ch is not None else "0.00"
        yon = "yükseldi" if (ch or 0) >= 0 else "düştü"
        espri = f"%{ch_s} {yon} — {_espri_uret('flat')}"

    baslik = f"<b>{adet}{html.escape(name)}</b>"
    text = (
        f"⚠️ {baslik}\n"
        f"\n"
        f"✅ {fiyat_satir}{try_line}\n"
        f"\n"
        f"{ikon} {html.escape(espri)}"
    )
    try:
        m = await update.effective_message.reply_text(
            text, parse_mode="HTML", disable_web_page_preview=True
        )
        chat = update.effective_chat
        sil_sn = int(cget(chat.id, "cevap_sil_sn") or 90) if chat else 90
        if sil_sn > 0 and m:
            asyncio.create_task(_mesaj_sil_sn(m, sil_sn))
        return True
    except Exception as e:
        log.warning("fiyat_gonder: %s", e)
        return False



async def guvenli_sil(msg, neden: str, user=None, chat_id=None, bot=None):
    """Tek silme noktasi: boostlu + linkli mesaji ASLA silme; sahibe log."""
    try:
        uid = getattr(user, "id", None) or getattr(getattr(msg, "from_user", None), "id", None)
        cid = chat_id or getattr(getattr(msg, "chat", None), "id", None)
        metin = ""
        if msg:
            metin = (msg.text or msg.caption or "") or ""
        boostlu = False
        if cid and uid:
            try:
                boostlu = boost_link_hakki_var(cid, uid)
            except Exception:
                pass
        if boostlu and (mesajda_link_var(msg, metin) if msg else False):
            log.info("SILME IPTAL (boostlu) neden=%s uid=%s", neden, uid)
            return False
        if boostlu and neden in (
            "link", "link_engel", "sahte", "link_tara", "guven_link", "medya", "medya_engel", "reklam"
        ):
            log.info("SILME IPTAL (boostlu kural) neden=%s uid=%s", neden, uid)
            return False
        await msg.delete()
        log.info("SILINDI neden=%s uid=%s chat=%s", neden, uid, cid)
        return True
    except Exception as e:
        log.warning("sil hata neden=%s %s", neden, e)
        return False


async def _mesaj_sil_sn(m, sn):
    await asyncio.sleep(max(5, int(sn)))
    try:
        await m.delete()
    except Exception:
        pass


# ---------- panel ----------
def panel_kb(cid):
    """Ana panel — Turkce dugmeler."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"👋 Karsilama {_ok(cget(cid,'hosgeldin') or cget(cid,'hoscaakal'))}",
                    callback_data="p:greet",
                ),
                InlineKeyboardButton(f"🌊 Flood koruma {_ok(cget(cid,'flood'))}", callback_data="p:flood"),
            ],
            [
                InlineKeyboardButton(f"🛡 Baskin koruma {_ok(cget(cid,'antiraid'))}", callback_data="p:antiraid"),
                InlineKeyboardButton(f"✅ Uye onayi {_ok(cget(cid,'approval'))}", callback_data="p:approval"),
            ],
            [
                InlineKeyboardButton(f"🔐 CAPTCHA {_ok(cget(cid,'captcha'))}", callback_data="p:captcha"),
                InlineKeyboardButton(f"🧹 Komut sil {_ok(cget(cid,'clean_cmd'))}", callback_data="p:cleancmd"),
            ],
            [
                InlineKeyboardButton(f"🧹 Servis sil {_ok(cget(cid,'servis_sil'))}", callback_data="p:servis"),
                InlineKeyboardButton("🔒 Kilitler", callback_data="p:locks"),
            ],
            [
                InlineKeyboardButton(
                    f"🔗 Link engel: {'ACIK' if cget(cid,'link_engel') else 'KAPALI'}",
                    callback_data=f"p:link:{cid}",
                ),
                InlineKeyboardButton(
                    f"🖼 Medya engel: {'ACIK' if cget(cid,'medya_engel') else 'KAPALI'}",
                    callback_data=f"p:medya:{cid}",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"↪️ Ilet engel: {'ACIK' if cget(cid,'forward_engel') else 'KAPALI'}",
                    callback_data=f"p:forward:{cid}",
                ),
                InlineKeyboardButton("🚫 Yasak kelimeler", callback_data="p:blocklist"),
            ],
            [
                InlineKeyboardButton("⚠ Uyarilar", callback_data="p:uyari"),
            ],
            [
                InlineKeyboardButton("📜 Kurallar", callback_data="p:kurallar"),
                InlineKeyboardButton(f"📋 Log {_ok(bool(cget(cid,'log_kanal')))}", callback_data="p:log"),
            ],
            [
                InlineKeyboardButton(f"🌙 Gece modu {_ok(cget(cid,'gece'))}", callback_data="p:gece"),
                InlineKeyboardButton(f"🔇 Sessizlik {_ok(cget(cid,'sessizlik'))}", callback_data="p:sessiz"),
            ],
            [
                InlineKeyboardButton("📝 Notlar", callback_data="p:notes"),
                InlineKeyboardButton("📏 Mesaj uzunlugu", callback_data="p:uzun"),
            ],
            [
                InlineKeyboardButton("🔧 Komutlar", callback_data="p:yardim"),
                InlineKeyboardButton("🚫 Bot engel", callback_data="p:engel"),
            ],
            [
                InlineKeyboardButton("🔤 Filtreler", callback_data="p:filters"),
                InlineKeyboardButton("📌 Sabitleme", callback_data="p:pin"),
            ],
            [
                InlineKeyboardButton("🗑 Toplu silme", callback_data="p:purges"),
                InlineKeyboardButton("🌐 Federasyon", callback_data="p:fed"),
            ],
            [
                InlineKeyboardButton("📦 Ice/Disa aktar", callback_data="p:imex"),
                InlineKeyboardButton("💬 Konular", callback_data="p:topics"),
            ],
            [
                InlineKeyboardButton("👤 Yoneticiler", callback_data="p:admin"),
                InlineKeyboardButton(f"📣 Sikayetler {_ok(cget(cid,'reports'))}", callback_data="p:reports"),
            ],
            [
                InlineKeyboardButton(f"📢 Duyuru {_ok(cget(cid,'duyuru_aktif'))}", callback_data="p:duyuru"),
                InlineKeyboardButton(f"💡 Ipucu {_ok(cget(cid,'ipucu_aktif'))}", callback_data="p:ipucu"),
            ],
            [
                InlineKeyboardButton(
                    f"🪂 Airdrop yorum: {'ACIK' if cget(cid,'airdrop_yorum') else 'KAPALI'}",
                    callback_data=f"p:airdrop:{cid}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔁 Tekrar mesaj ekle",
                    callback_data=f"p:tekrar:{cid}",
                ),
            ],
            [
                InlineKeyboardButton("🚫 Komut kapat", callback_data="p:disable"),
                InlineKeyboardButton(f"🔏 Gizlilik {_ok(cget(cid,'privacy_ai'))}", callback_data="p:privacy"),
            ],
            [InlineKeyboardButton("🔒 Paneli kapat", callback_data="p:kapat")],
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
    try:
        if gid is not None and int(gid) >= 0:
            gid = None
    except Exception:
        pass
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





def _artislik_mi(metin: str) -> bool:
    low = kucult(metin or "")
    if not low or len(low) < 2:
        return False
    # kufur / kasma / artislik
    kel = (
        "amk", "aq", "sg", "siktir", "orospu", "piç", "pic", "gerizekal", "salak",
        "mal", "aptal", "ezik", "köpek", "kopek", "yarrak", "mk", "mq",
        "ne bakıyon", "ne bakiyon", "lanet", "kahpe", "haysiyetsiz",
    )
    if any(k in low for k in kel):
        return True
    if any(k in low for k in ("sus lan", "kes sesini", "kimsin sen", "sen kimsin", "gel buraya")):
        return True
    # buyuk harf spam
    harf = [c for c in (metin or "") if c.isalpha()]
    if len(harf) >= 8 and sum(1 for c in harf if c.isupper()) / len(harf) > 0.7:
        return True
    return False


async def ceza_izle_kontrol(update, context) -> bool:
    """Cezadan yeni cikan: artislik yaparsa etiketleyip laf sok (max 5). Reply ile devam."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return False
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return False
    key = (chat.id, user.id)
    bil = _ceza_izle.get(key)
    if not bil:
        return False
    now = time.time()
    if now > float(bil.get("until") or 0):
        _ceza_izle.pop(key, None)
        return False
    metin = (msg.text or msg.caption or "").strip()
    if not metin:
        return False
    # botun mesajina yanit → kisa sohbet surdur (1-2 cumle)
    reply_bot = (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and msg.reply_to_message.from_user.id == context.bot.id
    )
    if reply_bot and bil.get("count", 0) < int(bil.get("max") or 5):
        bil["count"] = int(bil.get("count") or 0) + 1
        try:
            await msg.reply_text(
                "Anladım — sakin devam edelim, grup da rahat etsin."
                if not _artislik_mi(metin)
                else "Cezadan yeni çıktın; bu tonla devam edersen yine aynı yerde buluşuruz."
            )
        except Exception:
            pass
        if bil["count"] >= int(bil.get("max") or 5):
            _ceza_izle.pop(key, None)
        return True
    if not _artislik_mi(metin):
        return False
    if int(bil.get("count") or 0) >= int(bil.get("max") or 5):
        _ceza_izle.pop(key, None)
        return False
    bil["count"] = int(bil.get("count") or 0) + 1
    import random
    laf = random.choice(_CEZA_IZLE_LAF)
    mention = f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "Üye")}</a>'
    try:
        await msg.reply_text(f"{mention} {laf}", parse_mode="HTML")
    except Exception:
        try:
            await msg.reply_text(laf)
        except Exception:
            pass
    if bil["count"] >= int(bil.get("max") or 5):
        _ceza_izle.pop(key, None)
    return True


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
            dk_ceza = int(cget(chat_id, "oy_mute_dk") or 5)
            until = datetime.now(timezone.utc) + timedelta(minutes=dk_ceza)
            await context.bot.restrict_chat_member(
                chat_id, hedef_id, permissions=MUTE_PERMS, until_date=until
            )
            cez = dict(cget(chat_id, "gecici_ceza") or {})
            cez[str(hedef_id)] = {
                "tip": "mute",
                "bitis": time.time() + dk_ceza * 60,
                "uyari_gonderildi": False,
                "sebep": "grup oylaması",
                "ad": data.get("hedef_ad") or str(hedef_id),
            }
            cset(chat_id, "gecici_ceza", cez)
            txt = (
                f"✅ Ceza onaylandı\n"
                f"🔇 {ad} → <b>{dk_ceza} dk</b> mesaj atamaz\n"
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
        await log_gonder(context.bot, chat_id, f"⚖️ Ceza oylaması: {ad} mute (✅{ne})")
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
    user = q.from_user
    data = q.data[2:]
    # p:link:-100123 veya p:medya:-100123 → gid callback'ten
    cid = context.user_data.get("panel_gid")
    try:
        if cid is not None and int(cid) >= 0:
            cid = None
    except Exception:
        cid = None
    if ":" in data:
        par = data.split(":")
        if len(par) >= 2 and par[0] in ("link", "medya", "forward", "airdrop", "tekrar") and par[1].lstrip("-").isdigit():
            cid = int(par[1])
            data = par[0]
            context.user_data["panel_gid"] = cid
    if not cid:
        try:
            await q.answer("Oturum düştü — grupta /panel yaz", show_alert=True)
        except Exception:
            pass
        return
    if not await admin_mi(cid, user, context.bot) and not sahip_mi(user):
        try:
            await q.answer("Yetkin yok", show_alert=True)
        except Exception:
            pass
        return
    try:
        await q.answer()
    except Exception:
        pass

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
        acik = bool(cget(cid, "medya_engel"))
        try:
            await q.answer("Medya engel AÇIK" if acik else "Medya engel KAPALI")
        except Exception:
            pass
        await yenile("Medya engel: %s\n" % ("AÇIK" if acik else "KAPALI"))
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
            f"Link/Reklam/Buton: {_ok(cget(cid,'link_engel'))}\n\n"
            f"<i>Link açıkken üye t.me, url ve mavi buton paylaşamaz.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"Medya engel: {'AÇIK' if cget(cid,'medya_engel') else 'KAPALI'}",
                    callback_data=f"p:medya:{cid}"),
                 InlineKeyboardButton(
                    f"Link engel: {'AÇIK' if cget(cid,'link_engel') else 'KAPALI'}",
                    callback_data=f"p:link:{cid}")],
                [InlineKeyboardButton("« Geri", callback_data="p:geri")],
            ]),
        )
        return
    if data == "link":
        yeni = not bool(cget(cid, "link_engel"))
        cset(cid, "link_engel", yeni)
        acik = bool(cget(cid, "link_engel"))
        try:
            await q.answer(
                "Link engel AÇIK — üyeler atamaz" if acik else "Link engel KAPALI — serbest",
                show_alert=False,
            )
        except Exception:
            pass
        txt = (
            "🔗 <b>Link / Reklam engeli</b>\n"
            "Grup: <code>%s</code>\n"
            "Durum: <b>%s</b>\n\n"
            "AÇIK = üyeler link/t.me/buton atamaz\n"
            "KAPALI = herkes serbest\n"
            "Adminler her zaman serbest.\n"
            "İzin: <code>/izinlink t.me/kanal</code>"
        ) % (cid, "AÇIK — yasak" if acik else "KAPALI — serbest")
        try:
            await q.edit_message_text(
                txt,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Kapat (serbest)" if acik else "Aç (yasakla)",
                        callback_data="p:link:%s" % cid,
                    )],
                    [InlineKeyboardButton("« Ana panel", callback_data="p:geri")],
                ]),
            )
        except Exception as e:
            log.warning("panel link edit: %s", e)
            await yenile("Link engel: %s\n" % ("AÇIK" if acik else "KAPALI"))
        return

    if data == "tekrar":
        context.user_data["panel_gid"] = cid
        context.user_data["tekrar_wizard"] = {
            "adim": "saat",
            "cid": cid,
            "buttons": [],
        }
        try:
            await q.answer()
            await q.edit_message_text(
                "🔁 <b>Tekrar mesaj kurulum</b>\n"
                "Grup: <code>%s</code>\n\n"
                "1️⃣ Kac <b>saatte bir</b> atilsin?\n"
                "Ornek: <code>1</code> veya <code>12</code>\n\n"
                "Iptal: <code>iptal</code>" % cid,
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                q.from_user.id if q.from_user else cid,
                "🔁 Tekrar mesaj: kac saatte bir? Ornek: 12\nIptal: iptal",
            )
        return

    if data == "airdrop":
        yeni = not bool(cget(cid, "airdrop_yorum"))
        cset(cid, "airdrop_yorum", yeni)
        acik = bool(cget(cid, "airdrop_yorum"))
        try:
            await q.answer("Airdrop yorum AÇIK" if acik else "Airdrop yorum KAPALI")
        except Exception:
            pass
        txt = (
            "🪂 <b>Airdrop yorumu</b>\n"
            "Durum: <b>%s</b>\n\n"
            "AÇIK = kanaldan/gruba düşen airdrop paylaşımlarına bot kısa özet yazar:\n"
            "nedir · yapılacaklar · risk\n\n"
            "KAPALI = sessiz."
        ) % ("AÇIK" if acik else "KAPALI")
        try:
            await q.edit_message_text(
                txt,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Kapat" if acik else "Ac",
                        callback_data="p:airdrop:%s" % cid,
                    )],
                    [InlineKeyboardButton("« Ana panel", callback_data="p:geri")],
                ]),
            )
        except Exception:
            await yenile("Airdrop yorum: %s\n" % ("ACIK" if acik else "KAPALI"))
        return

    if data == "forward":
        yeni = not bool(cget(cid, "forward_engel"))
        cset(cid, "forward_engel", yeni)
        acik = bool(cget(cid, "forward_engel"))
        izin = cget(cid, "forward_izin") or []
        try:
            await q.answer("Ilet engel AÇIK" if acik else "Ilet engel KAPALI")
        except Exception:
            pass
        txt = (
            "↪️ <b>Ilet / Forward engeli</b>\n"
            "Durum: <b>%s</b>\n\n"
            "AÇIK = baska gruptan iletilen mesajlar silinir.\n"
            "Bagli duyuru kanali otomatik mesajlari silinmez.\n"
            "Adminler serbest.\n\n"
            "Izinli kaynaklar: %s\n"
            "Ekle: <code>/izinilet @kanal</code> veya <code>/izinilet -100xxx</code>\n"
            "Sil: <code>/iziniletkaldir @kanal</code>"
        ) % (
            "AÇIK — ilet yasak" if acik else "KAPALI — serbest",
            (", ".join(str(x) for x in izin) if izin else "yok"),
        )
        try:
            await q.edit_message_text(
                txt,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Kapat (serbest)" if acik else "Ac (yasakla)",
                        callback_data="p:forward:%s" % cid,
                    )],
                    [InlineKeyboardButton("« Ana panel", callback_data="p:geri")],
                ]),
            )
        except Exception:
            await yenile("Ilet engel: %s\n" % ("ACIK" if acik else "KAPALI"))
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



# ---------- boost / guclendirme haklari ----------
# Her boost sayisi ayri etiket + artan hak
# adet -> (etiket, emoji, link_max, mute_max)
_BOOST_KADEME = {
    1:  ("Lite", "⭐", 1, 1),
    2:  ("Bronze", "🥉", 1, 1),
    3:  ("Silver", "🥈", 2, 1),
    4:  ("Gold", "🥇", 2, 2),
    5:  ("Platin", "🏆", 3, 2),
    6:  ("Elmas", "💠", 3, 3),
    7:  ("Premium", "💎", 4, 3),
    8:  ("Elite", "👑", 4, 4),
    9:  ("Legend", "🔥", 5, 4),
    10: ("Mythic", "🌟", 5, 5),
    12: ("Titan", "🛡", 6, 5),
    15: ("Immortal", "♾️", 7, 6),
    20: ("Godmode", "🚀", 10, 8),
}


def _boost_gun_key():
    return datetime.now(TR).strftime("%Y-%m-%d")


def _boost_kayit(chat_id) -> dict:
    d = cget(chat_id, "boost_uyeler") or {}
    return d if isinstance(d, dict) else {}


def boost_seviye_bilgi(adet: int):
    adet = int(adet or 0)
    if adet <= 0:
        return {"adet": 0, "etiket": None, "emoji": "", "link_max": 0, "mute_max": 0, "seviye": 0}
    # en yuksek esik <= adet
    sec = None
    for min_a in sorted(_BOOST_KADEME.keys()):
        if adet >= min_a:
            sec = min_a
        else:
            break
    if sec is None:
        sec = 1
    etiket, emoji, lmax, mmax = _BOOST_KADEME[sec]
    # ara sayilar (orn. 11): bir onceki etiketi tut, haklari orantila
    return {
        "adet": adet,
        "etiket": etiket,
        "emoji": emoji,
        "link_max": lmax,
        "mute_max": mmax,
        "seviye": sec,
    }


def boost_bilgi(chat_id, user_id) -> dict:
    kayit = _boost_kayit(chat_id)
    u = dict(kayit.get(str(user_id)) or {})
    gun = _boost_gun_key()
    if u.get("gun") != gun:
        u["link_k"] = 0
        u["mute_k"] = 0
        u["gun"] = gun
    bil = boost_seviye_bilgi(u.get("adet") or 0)
    bil["link_k"] = int(u.get("link_k") or 0)
    bil["mute_k"] = int(u.get("mute_k") or 0)
    bil["gun"] = gun
    return bil


def boost_kaydet(chat_id, user_id, u: dict):
    kayit = _boost_kayit(chat_id)
    bil = boost_seviye_bilgi(u.get("adet") or 0)
    kayit[str(user_id)] = {
        "adet": int(u.get("adet") or 0),
        "link_k": int(u.get("link_k") or 0),
        "mute_k": int(u.get("mute_k") or 0),
        "gun": u.get("gun") or _boost_gun_key(),
        "etiket": bil.get("etiket"),
    }
    cset(chat_id, "boost_uyeler", kayit)


def boost_link_hakki_var(chat_id, user_id) -> bool:
    """Etiketi/adet olan boostlu uye link atabilir — asla silinmez."""
    try:
        u = boost_bilgi(chat_id, user_id)
        if u.get("etiket") or int(u.get("adet") or 0) >= 1:
            return True
        kayit = _boost_kayit(chat_id)
        raw = kayit.get(str(user_id))
        if raw is None and str(user_id).isdigit():
            for k, v in kayit.items():
                if str(k) == str(user_id):
                    raw = v
                    break
        if isinstance(raw, dict) and (raw.get("etiket") or int(raw.get("adet") or 0) >= 1):
            return True
    except Exception as e:
        log.warning("boost_link_hakki_var: %s", e)
    return False


def boost_link_kullan(chat_id, user_id) -> bool:
    """Istatistik icin say, ama hak bitince de True (link silinmez)."""
    u = boost_bilgi(chat_id, user_id)
    if not u.get("etiket"):
        return False
    u["link_k"] = int(u.get("link_k") or 0) + 1
    boost_kaydet(chat_id, user_id, u)
    return True


def boost_mute_hakki_var(chat_id, user_id) -> bool:
    u = boost_bilgi(chat_id, user_id)
    return bool(u.get("etiket")) and u["mute_k"] < u["mute_max"]


def boost_mute_kullan(chat_id, user_id) -> bool:
    u = boost_bilgi(chat_id, user_id)
    if not u.get("etiket") or u["mute_k"] >= u["mute_max"]:
        return False
    u["mute_k"] += 1
    boost_kaydet(chat_id, user_id, u)
    return True



_LINK_GECTI = set()  # (chat_id, message_id) boost/domain ile gecen mesajlar


def link_uye_izinli(chat_id, user_id, metin: str, kullan_hak=True) -> bool:
    """Izinli domain veya boost link hakki. kullan_hak=True ise hak duser."""
    izin = [x.lower() for x in (cget(chat_id, "link_izin") or [])]
    low = (metin or "").lower()
    if any(d and d in low for d in izin):
        return True
    if boost_link_hakki_var(chat_id, user_id):
        if not kullan_hak:
            return True
        return boost_link_kullan(chat_id, user_id)
    return False


def boost_etiket_text(u: dict) -> str:
    if not u or not u.get("etiket"):
        return ""
    return ("%s %s" % (u.get("emoji") or "", u.get("etiket") or "")).strip()


async def boost_senkron(bot, chat_id, user_id) -> dict:
    u = boost_bilgi(chat_id, user_id)
    try:
        r = await bot.get_user_chat_boosts(chat_id, user_id)
        n = len(getattr(r, "boosts", None) or [])
        if n > int(u.get("adet") or 0):
            u["adet"] = n
            boost_kaydet(chat_id, user_id, u)
            u = boost_bilgi(chat_id, user_id)
    except Exception:
        pass
    return u


def _boost_unvan_temiz(etiket: str) -> str:
    """Telegram custom title: emoji genelde reddedilir, max 16 karakter."""
    if not etiket:
        return ""
    # emoji / sembol temizle — sadece harf, rakam, bosluk, - _
    s = re.sub(r"[^\w\s\-\+]+", "", etiket, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    # bos kalirsa ham metinden ascii-ish
    if not s:
        s = re.sub(r"[^ -~]+", "", etiket).strip()
    return (s or "Boost")[:16]


async def boost_etiket_dene(bot, chat_id, user_id, etiket: str):
    """Isim yanina unvan: yetkisiz admin + emojisiz title (Lite, Godmode...)."""
    if not etiket:
        return
    title = _boost_unvan_temiz(etiket)
    if not title:
        return
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        if st in (ChatMemberStatus.OWNER, "creator"):
            return
        if st not in (ChatMemberStatus.ADMINISTRATOR, "administrator"):
            # Telegram unvan icin en az bir gercek yetki ister — davet yeterli
            await bot.promote_chat_member(
                chat_id,
                user_id,
                can_change_info=False,
                can_delete_messages=False,
                can_invite_users=True,
                can_restrict_members=False,
                can_pin_messages=False,
                can_promote_members=False,
                can_manage_chat=False,
                can_manage_video_chats=False,
                is_anonymous=False,
            )
        try:
            await bot.set_chat_administrator_custom_title(chat_id, user_id, title)
            log.info("boost unvan OK uid=%s title=%s", user_id, title)
        except Exception as e2:
            # bazen promote sonrasi kisa bekleme gerekir
            import asyncio as _aio
            await _aio.sleep(0.8)
            await bot.set_chat_administrator_custom_title(chat_id, user_id, title)
            log.info("boost unvan retry OK uid=%s title=%s (%s)", user_id, title, e2)
    except Exception as e:
        log.warning("boost unvan yazilamadi uid=%s: %s", user_id, e)


async def boost_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cb = getattr(update, "chat_boost", None)
    if not cb:
        return
    chat = getattr(cb, "chat", None) or update.effective_chat
    if not chat:
        return
    cid = chat.id
    boost = getattr(cb, "boost", None) or cb
    src = getattr(boost, "source", None)
    uid = None
    if src is not None:
        uid = getattr(getattr(src, "user", None), "id", None) or getattr(src, "user_id", None)
    if not uid:
        return
    u = boost_bilgi(cid, uid)
    eski = u.get("etiket")
    u["adet"] = max(int(u.get("adet") or 0) + 1, 1)
    boost_kaydet(cid, uid, u)
    u = boost_bilgi(cid, uid)
    await boost_etiket_dene(context.bot, cid, uid, u.get('etiket') or boost_etiket_text(u))
    try:
        et = boost_etiket_text(u) or "—"
        txt = (
            "🚀 <b>Grup güçlendirildi!</b>\n"
            "Etiket: <b>%s</b> (boost x%s)\n"
            "Bugün hak: %s link · %s mute"
        ) % (et, u["adet"], u["link_max"], u["mute_max"])
        await context.bot.send_message(cid, txt, parse_mode="HTML")
        if u.get("etiket") and u.get("etiket") != eski:
            await context.bot.send_message(
                cid,
                "🏷 Yeni etiket: <b>%s</b>" % boost_etiket_text(u),
                parse_mode="HTML",
            )
    except Exception:
        pass


async def boost_komut(update, context):
    """Grupta yazilirsa o gruba boost verir. Komut+cevap kisa surede silinir."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not user or not chat:
        return

    async def _sil_ikisi(cevap, sn=12):
        try:
            asyncio.create_task(_mesaj_sil_sn(msg, sn))
        except Exception:
            pass
        if cevap:
            try:
                asyncio.create_task(_mesaj_sil_sn(cevap, sn))
            except Exception:
                pass

    if chat.type != ChatType.PRIVATE:
        cid = chat.id
        try:
            g = durum.setdefault("grup", {}).setdefault(str(cid), {})
            if getattr(chat, "title", None):
                g["title"] = chat.title
                durum_kaydet()
        except Exception:
            pass
    else:
        cid = _aktif_grup_id() or 0

    adet = 1
    isim_parca = []
    for a in (context.args or []):
        if str(a).isdigit():
            adet = max(1, min(int(a), 30))
        else:
            isim_parca.append(str(a))

    hedef = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        ru = msg.reply_to_message.from_user
        if not getattr(ru, "is_bot", False):
            hedef = ru
    if hedef is None and isim_parca:
        hedef = await hedef_kullanici(update, context, isim_args=isim_parca)

    yetkili = sahip_mi(user)
    if not yetkili and chat.type != ChatType.PRIVATE:
        try:
            yetkili = await admin_mi(cid, user, context.bot)
        except Exception:
            yetkili = False

    ver_istegi = bool(
        (msg.reply_to_message and msg.reply_to_message.from_user)
        or isim_parca
    )

    if ver_istegi and yetkili:
        if not cid:
            r = await msg.reply_text("Özelde /gruplar → /grup 1 veya komutu grupta yaz.")
            await _sil_ikisi(r)
            return
        if not hedef:
            r = await msg.reply_text(
                "Üye bulunamadı.\nMesaja yanıtla: /boost 1\nveya: /boost @kullanici 1"
            )
            await _sil_ikisi(r)
            return
        try:
            u = boost_bilgi(cid, hedef.id)
            u["adet"] = int(adet)
            boost_kaydet(cid, hedef.id, u)
            u = boost_bilgi(cid, hedef.id)
            try:
                await boost_etiket_dene(context.bot, cid, hedef.id, u.get('etiket') or boost_etiket_text(u))
            except Exception:
                pass
            r = await msg.reply_text(
                "✅ %s → <b>%s</b> (x%s)\nHak: %s link / %s mute (bu grup)"
                % (
                    _ad(hedef),
                    boost_etiket_text(u) or "yok",
                    u["adet"],
                    u["link_max"],
                    u["mute_max"],
                ),
                parse_mode="HTML",
            )
            await _sil_ikisi(r, 15)
        except Exception as e:
            log.exception("boost ver")
            r = await msg.reply_text("Boost kaydı hata: %s" % e)
            await _sil_ikisi(r)
        return

    if not cid:
        r = await msg.reply_text("Grupta /boost yaz veya /grup 1 seç.")
        await _sil_ikisi(r)
        return
    try:
        u = await boost_senkron(context.bot, cid, user.id)
    except Exception:
        u = boost_bilgi(cid, user.id)
    if not u.get("etiket"):
        lines = ["🚀 <b>Boost etiketleri</b> (bu grup)"]
        for a in sorted(_BOOST_KADEME.keys()):
            et, em, l, m = _BOOST_KADEME[a]
            lines.append("%s <b>%s</b> — %s boost → %s link + %s mute" % (em, et, a, l, m))
        lines.append("")
        lines.append("Admin: mesaja yanıtla → /boost 1")
        r = await msg.reply_text("\n".join(lines), parse_mode="HTML")
        await _sil_ikisi(r, 20)
        return
    r = await msg.reply_text(
        "🏷 Etiket: <b>%s</b> (boost x%s)\n"
        "Bugün link: <b>%s/%s</b>\n"
        "Bugün mute: <b>%s/%s</b>\n"
        "<i>Bu gruba özel.</i>"
        % (
            boost_etiket_text(u),
            u["adet"],
            u["link_k"],
            u["link_max"],
            u["mute_k"],
            u["mute_max"],
        ),
        parse_mode="HTML",
    )
    await _sil_ikisi(r, 15)


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


async def hedef_kullanici(update, context, isim_args=None):
    """Reply, @username, id veya isim ile uye bul. isim_args: boost icin birlesik isim."""
    msg = update.effective_message
    chat = update.effective_chat
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        if not u.is_bot:
            return u
    args = list(isim_args if isim_args is not None else (context.args or []))
    if not args:
        return None
    a0 = args[0].lstrip("@")
    if a0.isdigit() and len(args) == 1:
        return _FakeUser(a0)
    isim = " ".join(a.lstrip("@") for a in args if not a.isdigit()).strip().lower()
    if not isim:
        isim = a0.lower()

    def _esles(bil, uid):
        kul = (bil.get("kullanici") or "").lower()
        ad = (bil.get("ad") or "").lower()
        if kul and kul == isim.lstrip("@"):
            return _FakeUser(uid, bil.get("ad") or kul, kul)
        if ad and (ad == isim or isim in ad or ad.startswith(isim)):
            return _FakeUser(uid, bil.get("ad") or ad, kul)
        return None

    # 1) bu grup
    if chat and chat.type != ChatType.PRIVATE:
        for uid, bil in (uyeler.get(str(chat.id)) or {}).items():
            r = _esles(bil or {}, uid)
            if r:
                return r
    # 2) aktif grup + digerleri (ozel yonetim)
    arama = []
    ag = _aktif_grup_id()
    if ag:
        arama.append(str(ag))
    if chat and chat.type != ChatType.PRIVATE:
        arama.append(str(chat.id))
    arama.extend(list(uyeler.keys()))
    seen = set()
    for gid in arama:
        if gid in seen:
            continue
        seen.add(gid)
        for uid, bil in (uyeler.get(str(gid)) or {}).items():
            r = _esles(bil or {}, uid)
            if r:
                return r
    # 3) @username api
    try:
        uname = isim.split()[0].lstrip("@")
        c = await context.bot.get_chat("@" + uname)
        return _FakeUser(c.id, getattr(c, "full_name", None) or uname, uname)
    except Exception:
        return None


def _ad(u):
    return html.escape(getattr(u, "full_name", None) or str(getattr(u, "id", "?")))


class _ProxyChat:
    """Ozelden yonetim icin sahte chat (id + type)."""
    def __init__(self, cid):
        self.id = int(cid)
        self.type = ChatType.SUPERGROUP
        self.title = ""



def gercek_grup_listesi():
    """Sadece gercek grup/supergroup (id < 0). Ozel sohbet / kullanici id elenir."""
    out = []
    temizle = []
    for gid, conf in list((durum.get("grup") or {}).items()):
        try:
            i = int(gid)
        except Exception:
            temizle.append(gid)
            continue
        if i >= 0:
            # kullanici id veya ozel chat — grup degil
            temizle.append(gid)
            continue
        out.append((i, conf if isinstance(conf, dict) else {}))
    for gid in temizle:
        try:
            (durum.get("grup") or {}).pop(str(gid), None)
            (durum.get("grup") or {}).pop(gid, None)
        except Exception:
            pass
    if temizle:
        # aktif_grup yanlis ise sifirla
        try:
            ag = int(durum.get("aktif_grup") or 0)
            if ag >= 0:
                durum["aktif_grup"] = None
        except Exception:
            pass
        durum_kaydet()
    out.sort(key=lambda x: x[0])
    return out


def _aktif_grup_id():
    try:
        v = int(durum.get("aktif_grup") or 0)
        if v >= 0:
            return None  # ozel chat / kullanici id degil
        return v
    except Exception:
        return None


def hedef_grup_id(update=None, context=None):
    """Grupta: o grup. Ozelde: aktif_grup veya panel_gid."""
    chat = update.effective_chat if update else None
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL, "group", "supergroup", "channel"):
        return chat.id
    ag = _aktif_grup_id()
    if ag:
        return ag
    if context is not None:
        pg = (context.user_data or {}).get("panel_gid")
        if pg:
            try:
                return int(pg)
            except Exception:
                pass
    return None


def wizard_sohbet_uygun(update, hedef_cid) -> bool:
    """Sihirbaz cevabi: ayni grup VEYA sahip ozel sohbet."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if chat.id == hedef_cid:
        return True
    if chat.type in (ChatType.PRIVATE, "private") and sahip_mi(user):
        return True
    return False




async def _mod_giris(update, context, cmd_name: str = None):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or not user:
        return None
    # --- sahip ozelden: aktif gruba yonlendir ---
    ozel = chat.type in (ChatType.PRIVATE, "private")
    if ozel and sahip_mi(user):
        gid = _aktif_grup_id()
        if not gid:
            try:
                await msg.reply_text(
                    "Önce grup seç:\n"
                    "<code>/gruplar</code> → liste\n"
                    "<code>/grup -100...</code> veya <code>/grup 1</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return None
        if cmd_name is None and msg.text:
            part = msg.text.split()[0].lstrip("/").split("@")[0].lower()
            cmd_name = part
        proxy = _ProxyChat(gid)
        return msg, proxy, user
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
    is_adm = await admin_mi(chat.id, user, context.bot)
    mod_ok = {"mute", "unmute", "warn", "unwarn", "kick", "del", "report"}
    if not is_adm:
        if cmd_name and cmd_name.lower() in mod_ok and moderator_mi(chat.id, user):
            return msg, chat, user
        await kisa_cevap(context.bot, chat.id, "❌ Sadece yöneticiler.", 5)
        return None
    return msg, chat, user


async def ban_komut(update, context):
    # moderatör banlayamaz
    msg0, chat0, user0 = update.effective_message, update.effective_chat, update.effective_user
    if chat0 and user0 and moderator_mi(chat0.id, user0) and not await admin_mi(chat0.id, user0, context.bot):
        await kisa_cevap(context.bot, chat0.id, "Moderatör banlayamaz; mute/warn kullan.")
        return
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef or not hedef.id:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/ban</code> veya <code>/ban @user</code>")
        return
    try:
        if await _anti_nuke_kontrol(context.bot, chat.id, update.effective_user.id if update.effective_user else None, "ban"):
            await kisa_cevap(context.bot, chat.id, "🚨 Anti-nuke: çok hızlı işlem — durduruldu.")
            return
        if not _ceza_tavan_ok(chat.id):
            await kisa_cevap(context.bot, chat.id, "🛑 Günlük ceza tavanı doldu. Sahip bilgilendirildi.")
            return
        if cget(chat.id, "golge"):
            await log_gonder(context.bot, chat.id, f"👤 Gölge ban: {_ad(hedef)}")
            await kisa_cevap(context.bot, chat.id, "👤 Gölge: ban uygulanmadı (sadece log).")
            return
        sebep = " ".join(
            a for a in (context.args or [])
            if not a.isdigit() and not a.startswith("@")
        ) or "kural ihlali"
        await context.bot.ban_chat_member(chat.id, hedef.id)
        _ceza_tavan_artir(chat.id)
        _son_islem[str(chat.id)] = {"tip": "ban", "hedef_id": hedef.id, "ts": time.time()}
        yasakli_kaydet(chat.id, hedef, sebep, update.effective_user)
        if ozellik_acik(chat.id, "fed_ban"):
            fed_ban_ekle(hedef.id, sebep=sebep)
            guven_set(chat.id, hedef.id, 0)
        import random
        kart = random.choice(_BAN_KARTLAR)
        ay = time.strftime("%Y-%m")
        say = int((cget(chat.id, "ban_ay") or {}).get(ay) or 0)
        await kisa_cevap(
            context.bot, chat.id,
            f"🚫 {_ad(hedef)} banlandı\n"
            f"Sebep: {html.escape(sebep)}\n"
            f"<i>{kart}</i>\n"
            f"📊 Bu ay engel: <b>{say}</b>",
            25,
        )
        await log_gonder(context.bot, chat.id, f"🚫 Ban: {_ad(hedef)} <code>{hedef.id}</code> · {html.escape(sebep)}")
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
    notu = " ".join(
        a for a in (context.args or [])
        if not a.isdigit() and not a.startswith("@")
    )
    try:
        await context.bot.unban_chat_member(chat.id, hedef.id, only_if_banned=True)
        yasakli_sil(chat.id, hedef.id)
        txt = f"✅ {_ad(hedef)} ban kalktı."
        if notu:
            txt += f"\nNot: {html.escape(notu)}"
        await kisa_cevap(context.bot, chat.id, txt)
        await log_gonder(context.bot, chat.id, f"✅ Unban: {_ad(hedef)}" + (f" · {html.escape(notu)}" if notu else ""))
    except Exception as e:
        await kisa_cevap(context.bot, chat.id, f"❌ {html.escape(str(e))}")


async def yasaklilar_komut(update, context):
    """Genel liste — sebep/tarih (kisa)."""
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_sil(msg, context.bot)
    lst = list(cget(chat.id, "yasaklilar") or [])[:15]
    ay = time.strftime("%Y-%m")
    say = int((cget(chat.id, "ban_ay") or {}).get(ay) or 0)
    if not lst:
        await kisa_cevap(context.bot, chat.id, f"Yasaklı yok.\n📊 Bu ay engel: <b>{say}</b>")
        return
    lines = ["🚫 <b>Yasaklılar</b>", f"📊 Bu ay: <b>{say}</b> engel", ""]
    for x in lst:
        un = f"@{x['uname']}" if x.get("uname") else x.get("ad", "?")
        lines.append(f"• {html.escape(str(un))} — {html.escape(x.get('sebep') or '')} ({x.get('tarih','')[:10]})")
    await kisa_cevap(context.bot, chat.id, "\n".join(lines), 30)


async def ban_listesi_dm(bot, chat_id, to_user_id):
    """Admin'e butonlu detayli liste."""
    lst = list(cget(chat_id, "yasaklilar") or [])[:20]
    if not lst:
        await bot.send_message(to_user_id, "Yasaklı kayıt yok.")
        return
    await bot.send_message(to_user_id, f"🚫 <b>Banlılar</b> (grup <code>{chat_id}</code>)", parse_mode="HTML")
    for x in lst:
        un = f"@{x['uname']}" if x.get("uname") else ""
        txt = (
            f"<b>{html.escape(x.get('ad') or '?')}</b> {html.escape(un)}\n"
            f"ID: <code>{x.get('uid')}</code>\n"
            f"Sebep: {html.escape(x.get('sebep') or '')}\n"
            f"Tarih: {html.escape(x.get('tarih') or '')}\n"
            f"Banlayan: {html.escape(x.get('by_ad') or str(x.get('by') or '—'))}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Banı kaldır", callback_data=f"ub:{chat_id}:{x.get('uid')}"),
        ]])
        try:
            await bot.send_message(to_user_id, txt, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


async def unban_btn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("ub:"):
        return
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    cid, uid = int(parts[1]), int(parts[2])
    if not sahip_mi(q.from_user) and not await admin_mi(cid, q.from_user, context.bot):
        await q.answer("Yetkin yok", show_alert=True)
        return
    try:
        await context.bot.unban_chat_member(cid, uid, only_if_banned=True)
        yasakli_sil(cid, uid)
        await q.answer("Ban kalktı")
        await q.edit_message_text((q.message.text or "") + "\n\n✅ Affedildi / ban kaldırıldı.")
        await log_gonder(context.bot, cid, f"✅ Unban (buton): <code>{uid}</code> · {html.escape(q.from_user.full_name or '')}")
    except Exception as e:
        await q.answer(str(e)[:80], show_alert=True)


async def af_oy_baslat(update, context, hedef):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not hedef:
        return
    text = (
        f"🕊️ <b>Af oylaması</b>\n"
        f"{html.escape(hedef.full_name or str(hedef.id))}\n"
        f"Affedelim mi? Min 5 evet."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Evet (0)", callback_data=f"af:e:{hedef.id}"),
        InlineKeyboardButton("❌ Hayır (0)", callback_data=f"af:h:{hedef.id}"),
    ]])
    g = await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)
    af = dict(cget(chat.id, "af_oy") or {})
    af[str(hedef.id)] = {"evet": [], "hayir": [], "mid": g.message_id}
    cset(chat.id, "af_oy", af)


async def af_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("af:"):
        return
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    taraf, uid = parts[1], parts[2]
    chat = q.message.chat if q.message else None
    if not chat:
        return
    af = dict(cget(chat.id, "af_oy") or {})
    bag = dict(af.get(uid) or {})
    if not bag:
        await q.answer("Oylama yok", show_alert=True)
        return
    evet = [int(x) for x in (bag.get("evet") or [])]
    hayir = [int(x) for x in (bag.get("hayir") or [])]
    if q.from_user.id in evet or q.from_user.id in hayir:
        await q.answer("Zaten oy verdin")
        return
    if taraf == "e":
        evet.append(q.from_user.id)
    else:
        hayir.append(q.from_user.id)
    bag["evet"], bag["hayir"] = evet, hayir
    af[uid] = bag
    cset(chat.id, "af_oy", af)
    await q.answer("Oy kaydedildi")
    if len(evet) >= 5 and len(evet) > len(hayir):
        try:
            await context.bot.unban_chat_member(chat.id, int(uid), only_if_banned=True)
            yasakli_sil(chat.id, int(uid))
            await q.edit_message_text(f"✅ Af kabul · <code>{uid}</code> ban kalktı\n✅{len(evet)} ❌{len(hayir)}", parse_mode="HTML")
        except Exception as e:
            await q.edit_message_text(f"Af oylandı ama unban hatası: {e}")
        af.pop(uid, None)
        cset(chat.id, "af_oy", af)
        return
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Evet ({len(evet)})", callback_data=f"af:e:{uid}"),
            InlineKeyboardButton(f"❌ Hayır ({len(hayir)})", callback_data=f"af:h:{uid}"),
        ]]))
    except Exception:
        pass


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
    msg0, chat0, user0 = update.effective_message, update.effective_chat, update.effective_user
    # boost üyesi ozel/grup: admin degilse boost mute hakki
    boost_mute = False
    if user0 and chat0 and not sahip_mi(user0):
        cid_try = chat0.id if chat0.type != ChatType.PRIVATE else (_aktif_grup_id() or 0)
        if cid_try and not await admin_mi(cid_try, user0, context.bot):
            if boost_mute_hakki_var(cid_try, user0.id):
                boost_mute = True
    g = await _mod_giris(update, context)
    if not g and not boost_mute:
        return
    if g:
        _, chat, _ = g
    else:
        chat = _ProxyChat(_aktif_grup_id() or chat0.id)
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/mute 30</code>")
        return
    if boost_mute:
        if not boost_mute_kullan(chat.id, user0.id):
            await kisa_cevap(context.bot, chat.id if chat0.type != ChatType.PRIVATE else user0.id,
                             "🚀 Bugünkü boost mute hakkın bitti.")
            return
        # boost mute max 10 dk
        if not context.args:
            context.args = ["10"]
    args = list(context.args or [])
    dk = 60
    if update.effective_message.reply_to_message and args and args[0].isdigit():
        dk = max(1, min(int(args[0]), 43200))
    elif len(args) >= 2 and args[1].isdigit():
        dk = max(1, min(int(args[1]), 43200))
    until = datetime.now(timezone.utc) + timedelta(minutes=dk)
    try:
        await context.bot.restrict_chat_member(chat.id, hedef.id, permissions=MUTE_PERMS, until_date=until)
        # sebep: /mute 30 spam
        sebep = ""
        for a in args:
            if not a.isdigit() and not a.startswith("@"):
                sebep = " ".join(x for x in args if not x.isdigit() and not x.startswith("@"))
                break
        if not sebep:
            sebep = "kurallara aykırı davranış"
        cez = dict(cget(chat.id, "gecici_ceza") or {})
        cez[str(hedef.id)] = {
            "tip": "mute",
            "bitis": time.time() + dk * 60,
            "uyari_gonderildi": False,
            "sebep": sebep,
            "ad": hedef.full_name or str(hedef.id),
        }
        cset(chat.id, "gecici_ceza", cez)
        _son_islem[str(chat.id)] = {"tip": "mute", "hedef_id": hedef.id, "ts": time.time()}
        await kisa_cevap(
            context.bot, chat.id,
            f"🔇 {_ad(hedef)} <b>{dk} dk</b> susturuldu.\n"
            f"Sebep: {html.escape(sebep)}\n"
            f"<i>İtiraz: bota DM → itiraz</i>",
            20,
        )
        # moderatör koçu: ilk uyari olmadan uzun mute
        if moderator_mi(chat.id, update.effective_user) and not await admin_mi(chat.id, update.effective_user, context.bot):
            if dk >= 60:
                try:
                    await context.bot.send_message(
                        update.effective_user.id,
                        "💡 <b>Moderatör ipucu</b>\n"
                        "Uzun susturma yerine önce /warn ile uyarı daha yumuşak olur. "
                        "Tekrar ederse mute uygula.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
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




async def hgdurum_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grupta: karsilama/mute ayarlarini goster (teshis)."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        await msg.reply_text("Bu komutu grup içinde yaz.")
        return
    if not sahip_mi(user) and not await admin_mi(chat.id, user, context.bot):
        return
    try:
        await msg.delete()
    except Exception:
        pass
    yetki = "?"
    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
        yetki = str(me.status)
        cr = getattr(me, "can_restrict_members", None)
        if cr is not None:
            yetki += f" restrict={cr}"
    except Exception as e:
        yetki = f"alinamadi:{e}"
    kayit = (durum.get("grup") or {}).get(str(chat.id))
    await context.bot.send_message(
        chat.id,
        f"🔍 <b>Giriş ayarları (bu grup)</b>\n"
        f"Grup: <code>{chat.id}</code>\n"
        f"Kayıt var: {_ok(bool(kayit))}\n"
        f"Karşılama: {_ok(cget(chat.id, 'hosgeldin'))}\n"
        f"Mute dk: <b>{cget(chat.id, 'hosgeldin_mute')}</b>\n"
        f"Mesaj sil sn: {cget(chat.id, 'hosgeldin_sil')}\n"
        f"Captcha: {_ok(cget(chat.id, 'captcha'))}\n"
        f"Bot: {html.escape(str(yetki))}\n"
        f"aktif_grup: <code>{durum.get('aktif_grup')}</code>",
        parse_mode="HTML",
    )


async def welcomemute_komut(update, context):
    """Yeni uye susturma suresi (dakika). 0 = kapali."""
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        cur = int(cget(chat.id, "hosgeldin_mute") or 0)
        await kisa_cevap(
            context.bot, chat.id,
            f"Şu an: <b>{cur}</b> dk\nKullanım: <code>/welcomemute 15</code> · kapat: <code>/welcomemute 0</code>",
        )
        return
    try:
        dk = int(context.args[0])
    except Exception:
        await kisa_cevap(context.bot, chat.id, "Sayı yaz: <code>/welcomemute 15</code>")
        return
    dk = max(0, min(1440, dk))
    cset(chat.id, "hosgeldin_mute", dk)
    if dk > 0:
        cset(chat.id, "hosgeldin", True)
        await kisa_cevap(context.bot, chat.id, f"✅ Yeni üyeler <b>{dk}</b> dk susturulacak.")
    else:
        await kisa_cevap(context.bot, chat.id, "✅ Giriş susturması kapatıldı.")


async def setwelcome_komut(update, context):
    g = await _mod_giris(update, context)
    if not g:
        return
    _, chat, _ = g
    if not context.args:
        await kisa_cevap(
            context.bot, chat.id,
            "Kullanım:\n<code>/setwelcome metin</code>\n"
            "Mute: <code>/welcomemute 15</code>\n"
            "{ad} = üye adı",
        )
        return
    metin = " ".join(context.args)
    cset(chat.id, "hosgeldin_metin", metin)
    cset(chat.id, "hosgeldin", True)
    # metinde "15 dakika" varsa mute otomatik
    m = re.search(r"(\d+)\s*(?:dk|dakika|min)", metin, re.I)
    if m:
        dk = max(1, min(1440, int(m.group(1))))
        cset(chat.id, "hosgeldin_mute", dk)
        extra = f" + {dk} dk susturma"
    else:
        extra = ""
        if int(cget(chat.id, "hosgeldin_mute") or 0) == 0:
            extra = " (mute yok — /welcomemute 15)"
    await kisa_cevap(
        context.bot, chat.id,
        f"✅ Karşılama kaydedildi ve açıldı{extra}.",
    )


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



def _duyuru_temiz_baslik(ham: str) -> str:
    """URL ve kirli satirlari at, kisa isim birak."""
    t = (ham or "").strip()
    if not t:
        return "Duyuru"
    satirlar = []
    for ln in t.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if re.search(r"https?://|t\.me/", ln):
            temiz = re.sub(r"https?://\S+|t\.me/\S+", "", ln).strip()
            if len(temiz) < 3:
                continue
            ln = temiz
        satirlar.append(ln)
    line = satirlar[0] if satirlar else t.splitlines()[0].strip()
    line = re.sub(r"https?://\S+", "", line).strip()
    line = re.sub(r"t\.me/\S+", "", line).strip()
    line = re.sub(r"\s+", " ", line).strip(" -|·•")
    if len(line) < 3:
        line = "Duyuru"
    if len(line) > 48:
        line = line[:45].rstrip() + "..."
    return line


def _duyuru_baslik(msg) -> str:
    t = (msg.text or msg.caption or "").strip()
    if not t:
        if getattr(msg, "photo", None):
            return "📷 Fotoğraf"
        if getattr(msg, "video", None):
            return "🎬 Video"
        if getattr(msg, "document", None):
            return "📎 Dosya"
        return "Duyuru"
    return _duyuru_temiz_baslik(t)



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




_AIRDROP_IPUCU = (
    "airdrop", "claim", "snapshot", "galxe", "zealy", "layer3", "task",
    "görev", "gorev", "retrodrop", "whitelist", "wl ", "mint", "points",
    "puan", "quest", "kampanya", "testnet", "mainnet", "faucet",
)


def airdrop_metin_mi(metin: str) -> bool:
    low = kucult(metin or "")
    if not low or len(low) < 8:
        return False
    return any(k in low for k in _AIRDROP_IPUCU)


def airdrop_analiz_uret(metin: str) -> str:
    """Airdrop ozeti — 3 bolum TAM, token limiti yuksek."""
    metin = (metin or "").strip()
    if not metin:
        return ""
    sistem = (
        "Sen kripto asistanisin. Verilen duyuru/airdrop metnini ozetle.\n"
        "SADECE su format, 3 bolumu de doldur, yarim cumle YASAK:\n\n"
        "📌 Nedir: (2-3 tam cumle)\n"
        "✅ Yapılacaklar: 1) ... 2) ... 3) ...\n"
        "⚠ Risk: (1-2 tam cumle; seed/gas/sahte link)\n\n"
        "Turkce yaz. Finansal tavsiye degil. En az 8 satir."
    )
    user = "Metni eksiksiz ozetle:\n\n" + metin[:3500]
    mesajlar = [{"role": "user", "content": user}]
    yanit = None

    # yuksek token ile dogrudan dene
    if gem:
        for model in ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash"):
            try:
                r = gem.models.generate_content(
                    model=model,
                    contents=_gem_parts(mesajlar),
                    config=types.GenerateContentConfig(
                        system_instruction=sistem,
                        temperature=0.4,
                        max_output_tokens=900,
                    ),
                )
                yanit = (getattr(r, "text", None) or "").strip()
                if yanit and len(yanit) > 60:
                    break
            except Exception as e:
                log.warning("airdrop gemini %s: %s", model, e)
                yanit = None

    if (not yanit or len(yanit) < 60) and GROQ_KEY:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "system", "content": sistem}] + mesajlar,
                    "max_tokens": 900,
                    "temperature": 0.4,
                },
                timeout=45,
            )
            if r.status_code == 200:
                yanit = (r.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:
            log.warning("airdrop groq: %s", e)

    if not yanit or len(yanit) < 60:
        try:
            yanit = _sor_modeller(mesajlar, sistem, hizli=False)
        except Exception as e:
            log.warning("airdrop fallback: %s", e)
            yanit = None

    if yanit:
        yanit = yanit.strip()
        if yanit[-1].isalnum():
            yanit += "."
        # eksik bolum varsa kaynak metinden tamamla
        low = yanit.lower()
        if "yap" not in low and "görev" not in low and "gorev" not in low:
            yanit += "\n✅ Yapılacaklar: Duyurudaki adımları takip edin; resmi link kullanın."
        if "risk" not in low and "⚠" not in yanit:
            yanit += "\n⚠ Risk: Seed/cüzdan bağlama ve sahte linklere dikkat. Finansal tavsiye değil."

    if not yanit or len(yanit) < 40:
        satirlar = [x.strip() for x in metin.splitlines() if x.strip()][:10]
        govde = "\n".join(satirlar)
        if len(govde) > 900:
            govde = govde[:900].rsplit(".", 1)[0] + "."
        yanit = (
            "📌 Nedir: Kanal airdrop / etkinlik duyurusu.\n"
            f"✅ Detay:\n{govde}\n"
            "⚠ Risk: Resmi link dışı cüzdan bağlama; seed/gas tuzaklarına dikkat. "
            "Finansal tavsiye değil."
        )
    return yanit.strip()



async def airdrop_yorum_gonder(bot, chat_id, metin: str, reply_to_message_id=None):
    if not cget(chat_id, "airdrop_yorum"):
        return
    metin = (metin or "").strip()
    low = kucult(metin)
    # "Bugünkü Duyurular" listesini asla yorumlama
    if "bugünkü duyuru" in low or "bugunku duyuru" in low or "bugünkü duyurular" in low:
        return
    if low.startswith("📣") and "duyuru" in low and len(metin) < 800:
        return
    if not airdrop_metin_mi(metin):
        return
    try:
        yanit = await asyncio.to_thread(airdrop_analiz_uret, metin)
    except Exception as e:
        log.warning("airdrop thread: %s", e)
        return
    if not yanit:
        return
    try:
        await bot.send_message(
            chat_id,
            yanit[:3500],
            parse_mode=None,
            reply_to_message_id=reply_to_message_id,
            allow_sending_without_reply=True,
        )
    except Exception as e:
        log.warning("airdrop yorum gonder: %s", e)


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
        govde_txt = (msg.text or msg.caption or "").strip()
        entry = {
            "id": msg.message_id,
            "title": _duyuru_baslik(msg),
            "text": govde_txt[:1500],
            "date": bugun,
            "link": _duyuru_link(chat, msg.message_id),
        }
        posts = [p for p in posts if p.get("id") != msg.message_id]
        posts.append(entry)
        keep = []
        for p in posts:
            try:
                d = datetime.strptime(p.get("date", bugun), "%Y-%m-%d").date()
                if (datetime.now(TR).date() - d).days <= 14:
                    keep.append(p)
            except Exception:
                keep.append(p)
        conf["duyuru_posts"] = keep[-80:]
        durum_kaydet()
        log.info("duyuru kayit grup=%s post=%s", gid_s, (entry["title"] or "")[:40])
        # AI airdrop yorumu gruba
        try:
            govde = (msg.text or msg.caption or entry.get("title") or "").strip()
            if conf.get("airdrop_yorum", True) and airdrop_metin_mi(govde):
                asyncio.create_task(
                    airdrop_yorum_gonder(context.bot, int(gid_s), govde)
                )
        except Exception as e:
            log.warning("airdrop kanal yorum: %s", e)


def duyuru_liste_metni(chat_id, bos_mesaj=False):
    """Numarali, isimli, tiklaninca kanala giden duzenli liste."""
    posts = list(cget(chat_id, "duyuru_posts") or [])
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    bugunku = [p for p in posts if p.get("date") == bugun]
    if not bugunku:
        if bos_mesaj:
            return "📣 <b>Bugünkü Duyurular</b>\n\nHenüz duyuru yok."
        return None
    sec = bugunku[-15:]
    nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    lines = ["📣 <b>Bugünkü Duyurular</b>", ""]
    for i, p in enumerate(sec, 1):
        ham = p.get("title") or "Duyuru"
        try:
            title = html.escape(_duyuru_temiz_baslik(ham))
        except Exception:
            title = html.escape(str(ham)[:48])
        link = (p.get("link") or "").strip()
        no = nums[i - 1] if i <= 10 else f"<b>{i}.</b>"
        if link:
            lines.append(f'{no} <a href="{html.escape(link)}">{title}</a>')
        else:
            lines.append(f"{no} {title}")
    lines.append("")
    lines.append("<i>Başlığa tıkla → kanal duyurusuna git</i>")
    return "\n".join(lines)


def duyuru_liste_butonlar(chat_id):
    """URL buton satirlari (max 12)."""
    posts = list(cget(chat_id, "duyuru_posts") or [])
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    bugunku = [p for p in posts if p.get("date") == bugun][-12:]
    rows = []
    for i, p in enumerate(bugunku, 1):
        link = (p.get("link") or "").strip()
        if not link:
            continue
        try:
            ad = _duyuru_temiz_baslik(p.get("title") or f"Duyuru {i}")[:32]
        except Exception:
            ad = f"Duyuru {i}"
        rows.append([InlineKeyboardButton(f"{i}. {ad}", url=link)])
    return InlineKeyboardMarkup(rows) if rows else None



def duyuru_ara(chat_id, sorgu: str, limit: int = 3):
    """Grup duyuru havuzunda kelime ara (title+text)."""
    posts = list(cget(chat_id, "duyuru_posts") or [])
    if not posts or not sorgu:
        return []
    # temizle: yapay, duyuru, airdrop, link, ne, nedir
    q = kucult(sorgu)
    for at in ("yapay", "duyuru", "duyurusu", "airdrop", "nedir", "neydi", "hakkinda", "hakkında",
               "link", "var mi", "var mı", "goster", "göster", "bul", "ara"):
        q = q.replace(at, " ")
    q = re.sub(r"\s+", " ", q).strip()
    kelimeler = [k for k in q.split() if len(k) >= 2]
    if not kelimeler:
        # sadece "duyuru" dediyse bugunku son postlar
        bugun = datetime.now(TR).strftime("%Y-%m-%d")
        bugunku = [p for p in posts if p.get("date") == bugun]
        return (bugunku or posts)[-limit:][::-1]
    skorlu = []
    for p in posts:
        blob = kucult((p.get("title") or "") + " " + (p.get("text") or ""))
        skor = sum(1 for k in kelimeler if k in blob)
        if skor:
            skorlu.append((skor, p))
    skorlu.sort(key=lambda x: (-x[0], x[1].get("id") or 0))
    return [p for _, p in skorlu[:limit]]


async def duyuru_sorgu_cevap(bot, chat_id, sorgu: str, reply_to=None):
    """Eslsen duyuruyu ozetle + Duyuruya Git butonu."""
    bulunan = duyuru_ara(chat_id, sorgu, limit=1)
    if not bulunan:
        return False
    p = bulunan[0]
    title = p.get("title") or "Duyuru"
    text = (p.get("text") or title).strip()
    link = p.get("link") or ""
    # kisa ozet AI
    ozet = None
    try:
        ozet = await asyncio.to_thread(airdrop_analiz_uret, text[:1200])
    except Exception:
        pass
    if not ozet:
        # dusuk fallback: ilk 2-3 satir
        satirlar = [x.strip() for x in text.splitlines() if x.strip()][:4]
        ozet = "\n".join(satirlar)[:400] if satirlar else title
    # cok uzunsa kisalt
    if len(ozet) > 700:
        ozet = ozet[:680].rsplit(" ", 1)[0] + "..."
    kb = None
    if link:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📌 Duyuruya Git", url=link)]]
        )
    try:
        await bot.send_message(
            chat_id,
            ozet,
            reply_to_message_id=reply_to,
            reply_markup=kb,
            allow_sending_without_reply=True,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        log.warning("duyuru sorgu cevap: %s", e)
        return False


async def duyuru_gonder_grup(bot, chat_id, zorla=False):
    text = duyuru_liste_metni(chat_id, bos_mesaj=zorla)
    if not text:
        return False
    try:
        kb = duyuru_liste_butonlar(chat_id)
        m = await bot.send_message(
            chat_id, text, parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=kb,
        )
        if cget(chat_id, "kopru_pin") and m:
            try:
                await bot.pin_chat_message(chat_id, m.message_id, disable_notification=True)
            except Exception:
                pass
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
        await wizard_baslat(update, context, "duyuru", chat.id, "📢 Duyuru metnini yaz:")
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



def _hatirlat_ayikla(soru, chat_id, user_id):
    """Basit: 'X dakika sonra hatırlat Y' / 'yarın 17:00 hatırlat Y'."""
    s = (soru or "").strip()
    low = kucult(s)
    if "hatırlat" not in low and "hatirlat" not in low:
        return None
    # uye saat dilimi (basit offset: UTC+3 varsayilan TR)
    now = datetime.now(TR)
    tz_name = (cget(chat_id, "saat_dilimi") or {}).get(str(user_id))
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    at = None
    goster = ""
    m = re.search(r"(\d+)\s*(dk|dakika|min)\s*(sonra)?", low)
    if m:
        dk = int(m.group(1))
        at = now + timedelta(minutes=max(1, min(dk, 10080)))
        goster = f"{dk} dk sonra"
    if not at:
        m = re.search(r"(yarın|yarin)\s*(\d{1,2})(?:[:.](\d{2}))?", low)
        if m:
            saat = int(m.group(2))
            dakika = int(m.group(3) or 0)
            at = (now + timedelta(days=1)).replace(hour=min(saat, 23), minute=min(dakika, 59), second=0)
            goster = at.strftime("yarın %H:%M")
    if not at:
        m = re.search(r"(\d{1,2})[:.](\d{2})\s*hat[iı]rlat", low)
        if m:
            saat, dakika = int(m.group(1)), int(m.group(2))
            at = now.replace(hour=min(saat, 23), minute=min(dakika, 59), second=0)
            if at <= now:
                at += timedelta(days=1)
            goster = at.strftime("%H:%M")
    if not at:
        return None
    # metin: hatirlat kelimesinden sonrasi
    parca = re.split(r"hat[iı]rlat", s, flags=re.I, maxsplit=1)
    notu = (parca[1] if len(parca) > 1 else s).strip(" :,-")
    if not notu:
        notu = "Hatırlatma"
    return {
        "chat": chat_id,
        "user": user_id,
        "text": notu[:200],
        "at": at.timestamp(),
        "goster": goster,
    }


async def hatirlat_periyodik(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    kalan = []
    for h in list(_hatirlat_q):
        if float(h.get("at") or 0) <= now:
            try:
                await context.bot.send_message(
                    h["chat"],
                    f"⏰ <b>Hatırlatma</b>\n{html.escape(h.get('text') or '')}",
                    parse_mode="HTML",
                )
            except Exception as e:
                log.warning("hatirlat: %s", e)
        else:
            kalan.append(h)
    _hatirlat_q[:] = kalan


# --- adam asmaca (butonlu) ---
_ADAM_KELIME = [
    "bitcoin", "ethereum", "airdrop", "cuzdan", "token", "defi", "nft",
    "mainnet", "testnet", "staking", "snapshot", "whitelist", "blockchain",
    "liquidity", "bridge", "oracle", "wallet", "mining", "validator",
    "protocol", "governance", "stablecoin", "altcoin", "memecoin", "hodl",
    "bullrun", "whitepaper", "roadmap", "ankara", "istanbul", "izmir",
    "trabzon", "bursa", "antalya", "kitap", "kalem", "defter", "okul",
    "bilgisayar", "telefon", "internet", "yazilim", "algoritma", "bulut",
    "sunucu", "guvenlik", "anahtar", "kahve", "cay", "simit", "baklava",
    "kebap", "futbol", "basketbol", "yuzme", "kosu", "bisiklet", "modem",
]
_ADAM_CIGIM = [
    "```\n  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========```",
    "```\n  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========```",
]


def _adam_gorunum(oy):
    k = oy.get("kelime") or ""
    ac = oy.get("acilan") or set()
    satir = " ".join(ch.upper() if ch in ac else "_" for ch in k)
    yanlis = int(oy.get("yanlis") or 0)
    maxh = int(oy.get("max") or 6)
    kullanilan = " ".join(sorted(oy.get("kullanilan") or set())) or "—"
    cigim = _ADAM_CIGIM[min(yanlis, 6)]
    return (
        f"🎮 <b>Adam Asmaca</b>\n{cigim}\n"
        f"<code>{satir}</code>\nHarfler: {html.escape(kullanilan)}\n"
        f"Hak: {maxh - yanlis}/{maxh}"
    )


async def _adam_bekle(bot, chat_id, baslatan_id=None):
    oy = _oyun_adam.get(str(chat_id))
    if oy and oy.get("durum") in ("bekle", "oyna"):
        try:
            await bot.send_message(chat_id, "🎮 Zaten bir oyun var.")
        except Exception:
            pass
        return
    oyuncular = set()
    if baslatan_id:
        oyuncular.add(baslatan_id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Katıl ({len(oyuncular)})", callback_data=f"adam:kat:{chat_id}")
    ]])
    try:
        m = await bot.send_message(
            chat_id,
            "🎮 <b>Adam Asmaca</b>\nKatılmak için butona bas.\n⏳ 60 sn · en az 2 kişi",
            parse_mode="HTML",
            reply_markup=kb,
        )
        mid = m.message_id
    except Exception as e:
        log.warning("adam bekle: %s", e)
        return
    _oyun_adam[str(chat_id)] = {
        "durum": "bekle", "oyuncular": oyuncular, "ts": time.time(), "mid": mid,
    }
    for sn in range(55, 0, -5):
        await asyncio.sleep(5)
        oy = _oyun_adam.get(str(chat_id))
        if not oy or oy.get("durum") != "bekle":
            return
        n = len(oy.get("oyuncular") or [])
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=mid,
                text=f"🎮 <b>Adam Asmaca</b>\nKatılmak için butona bas.\n⏳ {sn} sn · {n} kişi",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"✅ Katıl ({n})", callback_data=f"adam:kat:{chat_id}")
                ]]),
            )
        except Exception:
            pass
    oy = _oyun_adam.get(str(chat_id))
    if not oy or oy.get("durum") != "bekle":
        return
    if len(oy.get("oyuncular") or []) < 2:
        _oyun_adam.pop(str(chat_id), None)
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=mid, text="🎮 Yeterli katılım yok, oyun iptal.")
        except Exception:
            try:
                await bot.send_message(chat_id, "🎮 Yeterli katılım yok, oyun iptal.")
            except Exception:
                pass
        return
    await _adam_baslat_oyna(bot, chat_id)


async def _adam_baslat_oyna(bot, chat_id):
    import random
    oy = _oyun_adam.get(str(chat_id))
    if not oy:
        return
    kelime = random.choice(_ADAM_KELIME)
    oy.update({
        "durum": "oyna", "kelime": kelime, "acilan": set(), "kullanilan": set(),
        "yanlis": 0, "max": 6, "ts": time.time(),
    })
    _oyun_adam[str(chat_id)] = oy
    try:
        if oy.get("mid"):
            await bot.edit_message_text(
                chat_id=chat_id, message_id=oy["mid"],
                text=_adam_gorunum(oy) + "\n\nHarf veya kelime yaz (sadece katılanlar).",
                parse_mode="HTML",
            )
        else:
            m = await bot.send_message(chat_id, _adam_gorunum(oy) + "\n\nHarf yaz.", parse_mode="HTML")
            oy["mid"] = m.message_id
    except Exception as e:
        log.warning("adam baslat: %s", e)


async def _adam_harf(update, context, tahmin):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    oy = _oyun_adam.get(str(chat.id))
    if not oy or oy.get("durum") != "oyna":
        return
    if time.time() - float(oy.get("ts") or 0) > 300:
        _oyun_adam.pop(str(chat.id), None)
        try:
            await context.bot.send_message(chat.id, "🎮 Oyun süre aşımı ile bitti.")
        except Exception:
            pass
        return
    if user.id not in (oy.get("oyuncular") or set()):
        return
    k = (oy.get("kelime") or "").lower()
    tahmin = (tahmin or "").lower().strip()
    try:
        await msg.delete()
    except Exception:
        pass
    if len(tahmin) > 1:
        if tahmin == k:
            _oyun_adam.pop(str(chat.id), None)
            try:
                guven_ekle(chat.id, user.id, 5)
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🏆 <a href=\"tg://user?id={user.id}\">{html.escape(user.first_name or 'Üye')}</a> "
                    f"bildi: <b>{html.escape(k)}</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return
        oy["yanlis"] = int(oy.get("yanlis") or 0) + 1
    else:
        harf = tahmin
        if harf in (oy.get("kullanilan") or set()):
            return
        oy.setdefault("kullanilan", set()).add(harf)
        if harf in k:
            oy.setdefault("acilan", set()).add(harf)
            if all(c in oy["acilan"] for c in k):
                _oyun_adam.pop(str(chat.id), None)
                try:
                    guven_ekle(chat.id, user.id, 5)
                except Exception:
                    pass
                try:
                    await context.bot.send_message(
                        chat.id,
                        f"🏆 <a href=\"tg://user?id={user.id}\">{html.escape(user.first_name or 'Üye')}</a> "
                        f"kazandı: <b>{html.escape(k)}</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                return
        else:
            oy["yanlis"] = int(oy.get("yanlis") or 0) + 1
    oy["ts"] = time.time()
    if int(oy.get("yanlis") or 0) >= int(oy.get("max") or 6):
        _oyun_adam.pop(str(chat.id), None)
        try:
            await context.bot.send_message(chat.id, f"💀 Bitti. Kelime: <b>{html.escape(k)}</b>", parse_mode="HTML")
        except Exception:
            pass
        return
    try:
        if oy.get("mid"):
            await context.bot.edit_message_text(
                chat_id=chat.id, message_id=oy["mid"],
                text=_adam_gorunum(oy) + "\n\nHarf veya kelime yaz.",
                parse_mode="HTML",
            )
    except Exception:
        pass


async def adam_katil_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("adam:kat:"):
        return
    try:
        cid = int(q.data.split(":")[2])
    except Exception:
        return
    oy = _oyun_adam.get(str(cid))
    if not oy or oy.get("durum") != "bekle":
        await q.answer("Oyun yok / başladı", show_alert=True)
        return
    uid = q.from_user.id
    oyuncular = set(oy.get("oyuncular") or [])
    if uid in oyuncular:
        await q.answer("Zaten katıldın")
        return
    oyuncular.add(uid)
    oy["oyuncular"] = oyuncular
    await q.answer("Katıldın!")
    n = len(oyuncular)
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Katıl ({n})", callback_data=f"adam:kat:{cid}")
        ]]))
    except Exception:
        pass


def _ipucu_havuz(chat_id):
    ozel = list(cget(chat_id, "ipucu_liste") or [])
    # once ozel, sonra varsayilan — tekrarsiz secim icin ayri tutulur
    return ozel, list(DEFAULT_IPUCU)


def _ipucu_ai_uret():
    """Ara sira AI ipucu — cumle yarim kalmasin."""
    import random
    konular = [
        "airdrop guvenligi", "cüzdan guvenligi", "rugpull belirtileri",
        "sybil riski", "phishing", "likidite riski", "FOMO", "gas ucreti",
        "token unlock", "sahte admin DM", "bridge / köprü riski", "honeypot",
        "DYOR adimlari", "approve/revoke", "testnet vs mainnet",
        "akilli sozlesme riski", "seed phrase",
    ]
    konu = random.choice(konular)
    sistem = (
        "Turkce tek ipucu yaz. 1 veya 2 tam cumle. "
        "Cumleyi ortada kesme; nokta ile bitir. "
        "Max 200 karakter. Basina emoji koyma. Net ve ciddi."
    )
    m = [{"role": "user", "content": f"Konu: {konu}. Tam cumleli kisa ipucu yaz."}]
    for fn in (groq_sor, gemini_sor, deepseek_sor, mistral_sor, openrouter_sor):
        try:
            out = fn(m, sistem)
        except Exception:
            out = None
        if out:
            out = out.strip().strip('"').replace("\n", " ")
            if out and out[-1] not in ".!?…":
                out = out.rstrip(" ,;") + "."
            if 25 <= len(out) <= 220:
                return "💡 " + html.escape(out)
    return None



async def ipucu_gonder_grup(bot, chat_id):
    """Farkli ipucu; ara sira AI uretimi; kullanilanlar bitene kadar tekrar yok."""
    import random
    ozel, varsayilan = _ipucu_havuz(chat_id)
    havuz = ozel + varsayilan
    if not havuz:
        return False
    kullanilan = list(cget(chat_id, "ipucu_kullanilan") or [])
    sayac = int(cget(chat_id, "ipucu_sayac") or 0) + 1
    cset(chat_id, "ipucu_sayac", sayac)

    text = None
    # her 3. gonderimde AI dene (cesitlilik)
    if sayac % 3 == 0:
        text = _ipucu_ai_uret()
        if text and text in kullanilan:
            text = None

    if not text:
        adaylar = [t for t in havuz if t not in kullanilan]
        if not adaylar:
            kullanilan = []
            adaylar = list(havuz)
        text = random.choice(adaylar)

    kullanilan.append(text)
    cset(chat_id, "ipucu_kullanilan", kullanilan[-max(8, len(havuz)):])
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
        await wizard_baslat(update, context, "ipucu", chat.id, "💡 İpucu metnini yaz:")
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


async def ozellik_komut(update, context):
    """/ozellik admin_taklit ac|kapat  veya /ozellik liste"""
    g = await _mod_giris(update, context, "ozellik")
    if not g:
        return
    _, chat, _ = g
    oz = dict(cget(chat.id, "ozellik") or DEFAULT_G["ozellik"])
    args = list(context.args or [])
    if not args or args[0] in ("liste", "list"):
        lines = [f"• <code>{k}</code>: {_ok(v)}" for k, v in sorted(oz.items())]
        await kisa_cevap(
            context.bot, chat.id,
            "🎛 <b>Özellikler</b>\n" + "\n".join(lines) +
            "\n\n<code>/ozellik isim ac|kapat</code>",
            25,
        )
        return
    isim = args[0].lower()
    if isim not in (DEFAULT_G.get("ozellik") or {}) and isim not in oz:
        await kisa_cevap(context.bot, chat.id, "Bilinmeyen özellik. <code>/ozellik liste</code>")
        return
    if len(args) < 2:
        await kisa_cevap(context.bot, chat.id, f"{isim}: {_ok(oz.get(isim))}")
        return
    val = args[1].lower() in ("ac", "aç", "on", "1", "true", "open")
    oz[isim] = val
    cset(chat.id, "ozellik", oz)
    await kisa_cevap(context.bot, chat.id, f"✅ <code>{html.escape(isim)}</code> → {_ok(val)}")


async def davet_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_sil(msg, context.bot)
    if not ozellik_acik(chat.id, "davet"):
        await kisa_cevap(context.bot, chat.id, "Davet takibi kapalı.")
        return
    args = list(context.args or [])
    # /davet link twitter  → ozel invite link olustur
    if args and args[0].lower() == "link" and len(args) >= 2:
        if not await admin_mi(chat.id, user, context.bot):
            return
        kaynak = args[1].lower()
        if kaynak not in ("twitter", "youtube", "instagram", "tiktok", "diger", "telegram"):
            kaynak = "diger"
        try:
            link = await context.bot.create_chat_invite_link(
                chat.id,
                name=f"src_{kaynak}"[:32],
                creates_join_request=False,
            )
            await kisa_cevap(
                context.bot, chat.id,
                f"🔗 <b>{kaynak}</b> davet linki:\n<code>{html.escape(link.invite_link)}</code>\n"
                f"Bu linkten gelenler kaynak olarak sayılır.",
                40,
            )
        except Exception as e:
            await kisa_cevap(context.bot, chat.id, f"Link oluşturulamadı (bot admin + davet yetkisi lazım): {html.escape(str(e))}")
        return
    dmap = cget(chat.id, "davetler") or {}
    kaynak = cget(chat.id, "davet_kaynak") or {}
    lines = ["🏆 <b>Davet liderliği</b>", ""]
    if kaynak:
        lines.append("📡 Kaynaklar: " + ", ".join(f"{k}={v}" for k, v in sorted(kaynak.items(), key=lambda x: -int(x[1]))))
        lines.append("")
    if not dmap and not kaynak:
        await kisa_cevap(context.bot, chat.id, "Henüz davet kaydı yok.\nAdmin: <code>/davet link twitter</code>")
        return
    uy = uyeler.get(str(chat.id)) or {}
    sirali = sorted(dmap.items(), key=lambda x: int(x[1]), reverse=True)[:15]
    for i, (uid, n) in enumerate(sirali, 1):
        ad = (uy.get(uid) or {}).get("ad") or uid
        lines.append(f"{i}. {html.escape(str(ad).split()[0])} — <b>{n}</b>")
    await kisa_cevap(context.bot, chat.id, "\n".join(lines), 30)


async def portfoy_komut(update, context):
    """/portfoy ekle btc 0.5 | /portfoy | /portfoy sil btc"""
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not msg or not user:
        return
    if chat and chat.type != ChatType.PRIVATE:
        await komut_sil(msg, context.bot)
    if chat and not ozellik_acik(chat.id if chat else 0, "portfoy"):
        # ozelde de calisabilir
        pass
    args = list(context.args or [])
    key = f"pf:{user.id}"
    pf = durum.setdefault("portfoy", {}).setdefault(str(user.id), {})
    if not args:
        if not pf:
            await msg.reply_text("Portföy boş.\n<code>/portfoy ekle btc 0.5</code>", parse_mode="HTML")
            return
        lines = ["💼 <b>Portföyün</b>", ""]
        toplam = 0.0
        for sym, miktar in pf.items():
            bil = fiyat_cek(sym)
            usd = (bil or {}).get("usd")
            if usd is not None:
                val = float(usd) * float(miktar)
                toplam += val
                lines.append(f"• {sym.upper()} × {miktar:g} = <b>${val:,.2f}</b>")
            else:
                lines.append(f"• {sym.upper()} × {miktar:g} = ?")
        lines.append("")
        lines.append(f"Toplam ≈ <b>${toplam:,.2f}</b>")
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
        return
    if args[0].lower() in ("ekle", "add") and len(args) >= 3:
        sym = args[1].lower()
        try:
            miktar = float(args[2].replace(",", "."))
        except Exception:
            await msg.reply_text("Miktar hatalı.")
            return
        pf[sym] = float(pf.get(sym) or 0) + miktar
        durum_kaydet()
        await msg.reply_text(f"✅ {sym.upper()} eklendi: {pf[sym]:g}")
        return
    if args[0].lower() in ("sil", "del", "remove") and len(args) >= 2:
        pf.pop(args[1].lower(), None)
        durum_kaydet()
        await msg.reply_text("🗑 Silindi.")
        return
    await msg.reply_text("Kullanım:\n<code>/portfoy</code>\n<code>/portfoy ekle btc 0.5</code>\n<code>/portfoy sil btc</code>", parse_mode="HTML")


async def guven_komut(update, context):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not chat or chat.type == ChatType.PRIVATE:
        return
    await komut_sil(msg, context.bot)
    hedef = await hedef_kullanici(update, context) or user
    puan = guven_get(chat.id, hedef.id)
    await kisa_cevap(context.bot, chat.id, f"🛡 {_ad(hedef)} güven: <b>{puan}/100</b>")



async def izinilet_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Izinli ilet kaynak ekle: /izinilet @kanal veya -100id"""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return
    if not sahip_mi(user) and not (chat and await admin_mi(chat.id, user, context.bot)):
        return
    await komut_sil(msg, context.bot)
    cid = chat.id if chat and chat.type != ChatType.PRIVATE else _aktif_grup_id()
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        cid = chat.id
    if not cid:
        await msg.reply_text("Once grupta kullan veya /grup sec.")
        return
    args = context.args or []
    if not args:
        liste = cget(cid, "forward_izin") or []
        await msg.reply_text(
            "Izinli ilet kaynaklari: %s\nKullanim: <code>/izinilet @kanal</code> veya <code>/izinilet -100xxx</code>"
            % (", ".join(str(x) for x in liste) if liste else "yok"),
            parse_mode="HTML",
        )
        return
    val = args[0].strip().lstrip("@")
    if val.startswith("https://t.me/"):
        val = val.split("t.me/")[-1].split("/")[0]
    if val.startswith("t.me/"):
        val = val.split("/", 1)[-1]
    liste = list(cget(cid, "forward_izin") or [])
    if val not in liste and str(val) not in [str(x) for x in liste]:
        liste.append(val)
        cset(cid, "forward_izin", liste)
    await msg.reply_text("✅ Ilet izni eklendi: <code>%s</code>\nListe: %s" % (html.escape(val), ", ".join(str(x) for x in liste)), parse_mode="HTML")


async def iziniletkaldir_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return
    if not sahip_mi(user) and not (chat and await admin_mi(chat.id, user, context.bot)):
        return
    await komut_sil(msg, context.bot)
    cid = chat.id if chat and chat.type != ChatType.PRIVATE else _aktif_grup_id()
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        cid = chat.id
    if not cid or not context.args:
        await msg.reply_text("Kullanim: /iziniletkaldir @kanal")
        return
    val = context.args[0].strip().lstrip("@")
    liste = [x for x in (cget(cid, "forward_izin") or []) if str(x).lower().lstrip("@") != val.lower()]
    cset(cid, "forward_izin", liste)
    await msg.reply_text("Kaldirildi. Kalan: %s" % (", ".join(str(x) for x in liste) if liste else "yok"))



def _tekrar_normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("@"):
        return "https://t.me/" + u.lstrip("@")
    if u.startswith("t.me/"):
        return "https://" + u
    if not u.startswith("http://") and not u.startswith("https://"):
        return "https://" + u
    return u


async def tekrar_gonder_bir(bot, chat_id, item: dict):
    """Tekrarlayan mesaj + url buton."""
    text = (item.get("text") or "").strip()
    if not text:
        return False
    kb = None
    btn = (item.get("btn") or "").strip()
    url = _tekrar_normalize_url(item.get("url") or "")
    if btn and url:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn[:64], url=url)]])
    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:
        log.warning("tekrar gonder chat=%s: %s", chat_id, e)
        return False


async def tekrar_periyodik(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    now = time.time()
    for gid_s, conf in list((durum.get("grup") or {}).items()):
        if not isinstance(conf, dict):
            continue
        liste = list(conf.get("tekrar_mesajlar") or [])
        if not liste:
            continue
        degisti = False
        for it in liste:
            if not it.get("aktif", True):
                continue
            saat = float(it.get("saat") or 1)
            if saat < 0.1:
                saat = 0.1
            last = float(it.get("last") or 0)
            if now - last < saat * 3600:
                continue
            try:
                ok = await tekrar_gonder_bir(bot, int(gid_s), it)
                if ok:
                    it["last"] = now
                    degisti = True
            except Exception as e:
                log.warning("tekrar job: %s", e)
        if degisti:
            conf["tekrar_mesajlar"] = liste
            durum_kaydet()


async def tekrarekle_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adim adim: saat → metin → buton → link. Grupta veya ozelde (aktif grup)."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return
    ozel = chat and chat.type in (ChatType.PRIVATE, "private")
    if ozel and not sahip_mi(user):
        return
    if not ozel and not sahip_mi(user) and not await admin_mi(chat.id, user, context.bot):
        return
    if not ozel:
        await komut_sil(msg, context.bot)
    cid = hedef_grup_id(update, context)
    if not cid:
        await msg.reply_text(
            "Once grup sec (ozelden):\n"
            "<code>/gruplar</code>\n"
            "<code>/grup 1</code>\n\n"
            "Sonra: <code>/tekrarekle</code>",
            parse_mode="HTML",
        )
        return
    # hizli yol: arguman varsa eski format
    raw = " ".join(context.args or []).strip()
    if raw and "|" in raw:
        # eski | formati — asagidaki parse'a dusmesin, basitce kullaniciyi yonlendir
        await msg.reply_text(
            "Kolay yol icin sadece <code>/tekrarekle</code> yaz, adim adim sorayim.\n"
            "Hizli format: <code>/tekrarekle 1 | metin | buton | link</code>",
            parse_mode="HTML",
        )
        # yine de | ile devam etmek isterse asagidaki wizard-disi islem
        context.user_data["tekrar_hizli"] = raw
        context.user_data["tekrar_wizard"] = {"adim": "hizli", "cid": cid}
        await _tekrar_hizli_kaydet(update, context, cid, raw)
        return
    context.user_data["tekrar_wizard"] = {
        "adim": "saat",
        "cid": chat.id,
        "buttons": [],
    }
    await msg.reply_text(
        "🔁 <b>Tekrar mesaj kurulum</b>\n\n"
        "1️⃣ Kac <b>saatte bir</b> atilsin?\n"
        "Ornek: <code>1</code> veya <code>0.5</code> (30 dk)\n\n"
        "Iptal: <code>iptal</code>",
        parse_mode="HTML",
    )


async def _tekrar_hizli_kaydet(update, context, cid, raw: str):
    par = [x.strip() for x in raw.split("|")]
    if len(par) < 4:
        await update.effective_message.reply_text("Eksik. Kolay yol: sadece /tekrarekle yaz.")
        return
    try:
        saat = float(par[0].replace(",", "."))
    except Exception:
        saat = 1.0
    saat = max(0.25, min(168.0, saat))
    text = par[1]
    buttons = []
    rest = par[2:]
    i = 0
    while i + 1 < len(rest):
        bt, bu = rest[i].strip(), _tekrar_normalize_url(rest[i + 1])
        if bt and bu:
            buttons.append({"text": bt[:64], "url": bu})
        i += 2
    if not text or not buttons:
        await update.effective_message.reply_text("Metin ve buton lazim.")
        return
    await _tekrar_kaydet_bitir(context.bot, update.effective_message, cid, saat, text, buttons)


async def _tekrar_kaydet_bitir(bot, msg, cid, saat, text, buttons):
    liste = list(cget(cid, "tekrar_mesajlar") or [])
    tid = str(int(time.time()) % 100000)
    item = {
        "id": tid,
        "text": text,
        "btn": buttons[0]["text"],
        "url": buttons[0]["url"],
        "buttons": buttons,
        "saat": saat,
        "last": 0,
        "aktif": True,
    }
    liste.append(item)
    cset(cid, "tekrar_mesajlar", liste[-20:])
    await tekrar_gonder_bir(bot, cid, item)
    item["last"] = time.time()
    cset(cid, "tekrar_mesajlar", liste[-20:])
    btn_ozet = " · ".join(html.escape(b["text"]) for b in buttons)
    await msg.reply_text(
        "✅ Kaydedildi (id <code>%s</code>)\n"
        "Her <b>%s</b> saatte · %s buton: %s\n"
        "/tekrarliste · /tekrardur %s · /tekrarsil %s"
        % (tid, saat, len(buttons), btn_ozet, tid, tid),
        parse_mode="HTML",
    )



async def wizard_baslat(update, context, tip: str, cid: int, ilk_soru: str, veri=None):
    context.user_data["wizard"] = {"tip": tip, "adim": 1, "cid": cid, "veri": veri or {}}
    await update.effective_message.reply_text(
        ilk_soru + "\n\nIptal: <code>iptal</code>", parse_mode="HTML"
    )


async def wizard_devam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Genel adim adim sihirbaz. True = mesaj tuketildi."""
    try:
        if await tekrar_wizard_devam(update, context):
            return True
    except Exception as e:
        log.warning("tekrar wizard: %s", e)
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    w = (context.user_data or {}).get("wizard")
    if not w or not msg or not user or not chat:
        return False
    if not wizard_sohbet_uygun(update, w.get("cid")):
        return False
    metin = (msg.text or msg.caption or "").strip()
    if not metin:
        return False
    low = kucult(metin)
    if low in ("iptal", "vazgec", "iptal et"):
        context.user_data.pop("wizard", None)
        await msg.reply_text("Iptal.")
        return True
    tip = w.get("tip")
    cid = w["cid"]

    if tip == "welcome":
        cset(cid, "hosgeldin_metin", metin)
        cset(cid, "hosgeldin", True)
        context.user_data.pop("wizard", None)
        await msg.reply_text(
            "✅ Karsilama kaydedildi.\nOnizleme: "
            + metin.replace("{ad}", user.first_name or "Uye")[:200]
        )
        return True
    if tip == "block":
        bl = list(cget(cid, "blocklist") or [])
        kel = metin.strip().lower()
        if kel and kel not in bl:
            bl.append(kel)
            cset(cid, "blocklist", bl[-80:])
        context.user_data.pop("wizard", None)
        await msg.reply_text("✅ Yasak kelime: <code>%s</code>" % html.escape(kel), parse_mode="HTML")
        return True
    if tip == "izinlink":
        doms = metin.replace(",", " ").split()
        cur = list(cget(cid, "link_izin") or [])
        for d in doms:
            d = d.strip().lower().replace("https://", "").replace("http://", "").strip("/")
            if d and d not in cur:
                cur.append(d)
        cset(cid, "link_izin", cur)
        context.user_data.pop("wizard", None)
        await msg.reply_text("✅ Izinli linkler: %s" % (", ".join(cur) if cur else "yok"))
        return True
    if tip == "izinilet":
        val = metin.strip().lstrip("@")
        if val.startswith("https://t.me/"):
            val = val.split("t.me/")[-1].split("/")[0]
        liste = list(cget(cid, "forward_izin") or [])
        if val and val not in [str(x) for x in liste]:
            liste.append(val)
            cset(cid, "forward_izin", liste)
        context.user_data.pop("wizard", None)
        await msg.reply_text(
            "✅ Ilet izni: <code>%s</code>" % html.escape(val), parse_mode="HTML"
        )
        return True
    if tip == "ipucu":
        liste = list(cget(cid, "ipucu_liste") or [])
        liste.append(metin)
        cset(cid, "ipucu_liste", liste[-50:])
        cset(cid, "ipucu_aktif", True)
        context.user_data.pop("wizard", None)
        await msg.reply_text("✅ Ipucu eklendi. Toplam: %s" % len(liste))
        return True
    if tip == "duyuru":
        posts = list(cget(cid, "duyuru_posts") or [])
        posts.append({"title": metin[:80], "text": metin, "link": "", "ts": time.time()})
        cset(cid, "duyuru_posts", posts[-40:])
        cset(cid, "duyuru_aktif", True)
        context.user_data.pop("wizard", None)
        await msg.reply_text("✅ Duyuru metni eklendi.")
        return True
    return False


async def tekrar_wizard_devam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Wizard aktifse True (mesaj islenmis)."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    w = (context.user_data or {}).get("tekrar_wizard")
    if not w or not msg or not user or not chat:
        return False
    if not wizard_sohbet_uygun(update, w.get("cid")):
        return False
    metin = (msg.text or msg.caption or "").strip()
    if not metin:
        return False
    low = kucult(metin)
    if low in ("iptal", "vazgec", "iptal et"):
        context.user_data.pop("tekrar_wizard", None)
        await msg.reply_text("Iptal edildi.")
        return True
    adim = w.get("adim")
    if adim == "saat":
        try:
            saat = float(metin.replace(",", ".").replace("saat", "").strip())
        except Exception:
            await msg.reply_text("Sayi yaz. Ornek: <code>1</code>", parse_mode="HTML")
            return True
        saat = max(0.25, min(168.0, saat))
        w["saat"] = saat
        w["adim"] = "metin"
        context.user_data["tekrar_wizard"] = w
        await msg.reply_text(
            "2️⃣ <b>Mesaj metnini</b> yaz (grupta gorunecek yazi):\n\nIptal: <code>iptal</code>",
            parse_mode="HTML",
        )
        return True
    if adim == "metin":
        w["text"] = metin
        w["adim"] = "btn"
        context.user_data["tekrar_wizard"] = w
        await msg.reply_text(
            "3️⃣ <b>Buton yazisi</b> ne olsun?\nOrnek: <code>Katil</code> / <code>Telegram</code>\n\nIptal: <code>iptal</code>",
            parse_mode="HTML",
        )
        return True
    if adim == "btn":
        w["btn_tmp"] = metin[:64]
        w["adim"] = "url"
        context.user_data["tekrar_wizard"] = w
        await msg.reply_text(
            "4️⃣ Bu butonun <b>linki</b>?\nOrnek: <code>https://t.me/kanal</code>\n\nIptal: <code>iptal</code>",
            parse_mode="HTML",
        )
        return True
    if adim == "url":
        url = _tekrar_normalize_url(metin)
        if not url.startswith("http"):
            await msg.reply_text("Gecerli link yaz. Ornek: https://t.me/xxx")
            return True
        buttons = list(w.get("buttons") or [])
        buttons.append({"text": w.get("btn_tmp") or "Git", "url": url})
        w["buttons"] = buttons
        w["adim"] = "daha"
        context.user_data["tekrar_wizard"] = w
        await msg.reply_text(
            f"✅ Buton eklendi ({len(buttons)}. buton).\n\n"
            "5️⃣ Baska buton eklemek ister misin?\n"
            "<b>evet</b> veya <b>hayir</b>",
            parse_mode="HTML",
        )
        return True
    if adim == "daha":
        if low in ("evet", "e", "yes", "y", "başka", "baska", "+"):
            w["adim"] = "btn"
            context.user_data["tekrar_wizard"] = w
            await msg.reply_text("Yeni <b>buton yazisini</b> yaz:", parse_mode="HTML")
            return True
        if low in ("hayir", "h", "no", "n", "tamam", "bitir", "ok"):
            context.user_data.pop("tekrar_wizard", None)
            await _tekrar_kaydet_bitir(
                context.bot, msg, w["cid"], w.get("saat", 1), w.get("text", ""), w.get("buttons") or []
            )
            return True
        await msg.reply_text("<b>evet</b> veya <b>hayir</b> yaz.", parse_mode="HTML")
        return True
    return False


async def tekrarliste_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return
    if not sahip_mi(user) and not (chat and chat.type != ChatType.PRIVATE and await admin_mi(chat.id, user, context.bot)):
        return
    await komut_sil(msg, context.bot)
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL, "group", "supergroup", "channel"):
        pass
    cid = hedef_grup_id(update, context)
    if not cid:
        await msg.reply_text("Once /gruplar → /grup 1")
        return
    liste = cget(cid, "tekrar_mesajlar") or []
    if not liste:
        await msg.reply_text("Tekrar mesaj yok. Ekle: /tekrarekle")
        return
    lines = ["📋 <b>Tekrar mesajlar</b>\n"]
    for it in liste:
        lines.append(
            "• id <code>%s</code> | her %s sa | %s | %s\n  %s\n  %s"
            % (
                it.get("id"),
                it.get("saat"),
                "ACIK" if it.get("aktif", True) else "KAPALI",
                html.escape((it.get("btn") or "")[:30]),
                html.escape((it.get("text") or "")[:80]),
                html.escape((it.get("url") or "")[:60]),
            )
        )
    await msg.reply_text("\n".join(lines), parse_mode="HTML")


async def tekrarsil_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or not sahip_mi(user) and not (chat and chat.type != ChatType.PRIVATE and await admin_mi(chat.id, user, context.bot)):
        return
    await komut_sil(msg, context.bot)
    cid = hedef_grup_id(update, context)
    if not cid:
        await msg.reply_text("Once /gruplar → /grup 1")
        return
    if not context.args:
        await msg.reply_text("Kullanim: /tekrarsil id")
        return
    tid = context.args[0].strip()
    liste = [x for x in (cget(cid, "tekrar_mesajlar") or []) if str(x.get("id")) != tid]
    cset(cid, "tekrar_mesajlar", liste)
    await msg.reply_text("Silindi: %s" % tid)


async def tekrardur_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user:
        return
    if not sahip_mi(user) and not (chat and chat.type != ChatType.PRIVATE and await admin_mi(chat.id, user, context.bot)):
        return
    await komut_sil(msg, context.bot)
    cid = hedef_grup_id(update, context)
    if not cid:
        await msg.reply_text("Once /gruplar → /grup 1")
        return
    if not context.args:
        await msg.reply_text("Kullanim: /tekrardur id   veya /tekrarac id")
        return
    tid = context.args[0].strip()
    cmd = (msg.text or "").split()[0].lower().lstrip("/")
    ac = "ac" in cmd or "aç" in cmd
    liste = list(cget(cid, "tekrar_mesajlar") or [])
    for it in liste:
        if str(it.get("id")) == tid:
            it["aktif"] = ac if "tekrarac" in cmd or cmd.startswith("tekrarac") else (not it.get("aktif", True) if cmd == "tekrardur" else False)
            if cmd.startswith("tekrardur"):
                it["aktif"] = False
            if cmd.startswith("tekrarac"):
                it["aktif"] = True
            cset(cid, "tekrar_mesajlar", liste)
            await msg.reply_text("id %s → %s" % (tid, "ACIK" if it["aktif"] else "KAPALI"))
            return
    await msg.reply_text("id bulunamadi")


async def yedek_komut(update, context):
    user = update.effective_user
    if not sahip_mi(user):
        return
    try:
        blob = json.dumps({"uyeler": uyeler, "durum": durum}, ensure_ascii=False)[:4000]
        await context.bot.send_message(user.id, f"📦 Yedek özeti (kısmi):\n<code>{html.escape(blob[:3500])}</code>", parse_mode="HTML")
        # dosya olarak
        path = "/tmp/bot_yedek.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"uyeler": uyeler, "durum": durum}, f, ensure_ascii=False)
        with open(path, "rb") as f:
            await context.bot.send_document(user.id, document=f, filename="bot_yedek.json")
        await update.effective_message.reply_text("✅ Yedek DM'ye gitti.")
    except Exception as e:
        await update.effective_message.reply_text(f"Yedek hata: {e}")


async def yedek_periyodik(context: ContextTypes.DEFAULT_TYPE):
    """Gunluk yedek KAPALI — sahibe json atilmaz."""
    return


async def haftalik_rapor(context: ContextTypes.DEFAULT_TYPE):
    """Sahibe haftalik ozet."""
    lines = ["📊 <b>Haftalık rapor</b>", ""]
    for gid, conf in (durum.get("grup") or {}).items():
        if not isinstance(conf, dict):
            continue
        st = conf.get("istatistik") or {}
        if not st:
            continue
        lines.append(
            f"Grup <code>{gid}</code>\n"
            f"• Mesaj: {st.get('mesaj', 0)}\n"
            f"• Giren: {st.get('giren', 0)} / Çıkan: {st.get('cikan', 0)}\n"
            f"• Spam sil: {st.get('spam', 0)}\n"
        )
        # sifirla
        conf["istatistik"] = {"giren": 0, "cikan": 0, "spam": 0, "mesaj": 0}
    durum_kaydet()
    if len(lines) > 2:
        try:
            await context.bot.send_message(SAHIP_ID, "\n".join(lines), parse_mode="HTML")
        except Exception as e:
            log.warning("haftalik: %s", e)


async def not_komut(update, context):
    """Admin not defteri: /not ekle metin | /not liste"""
    g = await _mod_giris(update, context, "not")
    if not g:
        return
    _, chat, user = g
    args = list(context.args or [])
    notlar = list(cget(chat.id, "admin_notlar") or [])
    if not args or args[0] in ("liste", "list"):
        if not notlar:
            await kisa_cevap(context.bot, chat.id, "Not yok.")
            return
        txt = "📝 <b>Admin notları</b>\n" + "\n".join(
            f"• {html.escape(n.get('t', ''))} <i>({n.get('ts','')})</i>" for n in notlar[-15:]
        )
        await kisa_cevap(context.bot, chat.id, txt, 30)
        return
    if args[0] in ("ekle", "add") and len(args) >= 2:
        t = " ".join(args[1:])
        notlar.append({"t": t, "by": user.id, "ts": time.strftime("%Y-%m-%d %H:%M")})
        cset(chat.id, "admin_notlar", notlar[-40:])
        await kisa_cevap(context.bot, chat.id, "✅ Not eklendi.")
        return
    if args[0] in ("sil", "del") and len(args) >= 2 and args[1].isdigit():
        i = int(args[1]) - 1
        if 0 <= i < len(notlar):
            notlar.pop(i)
            cset(chat.id, "admin_notlar", notlar)
        await kisa_cevap(context.bot, chat.id, "✅ Silindi.")
        return
    await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/not ekle metin</code> · <code>/not liste</code>")


async def topic_komut(update, context):
    """Forum konusu ayari: konuda /topic mod ciddi | /topic kural metin"""
    g = await _mod_giris(update, context, "topic")
    if not g:
        return
    msg, chat, _ = g
    tid = getattr(msg, "message_thread_id", None)
    if not tid:
        await kisa_cevap(context.bot, chat.id, "Bu komutu bir forum konusunda yaz.")
        return
    args = list(context.args or [])
    tmap = dict(cget(chat.id, "topic_ayar") or {})
    cur = dict(tmap.get(str(tid)) or {})
    if not args:
        await kisa_cevap(
            context.bot, chat.id,
            f"Konu {tid}: mod={cur.get('bot_mod','—')} kural={html.escape(str(cur.get('kurallar') or '—')[:80])}",
        )
        return
    if args[0].lower() == "mod" and len(args) >= 2:
        cur["bot_mod"] = args[1].lower()
        tmap[str(tid)] = cur
        cset(chat.id, "topic_ayar", tmap)
        await kisa_cevap(context.bot, chat.id, f"✅ Konu modu: {args[1]}")
        return
    if args[0].lower() in ("kural", "kurallar") and len(args) >= 2:
        cur["kurallar"] = " ".join(args[1:])
        tmap[str(tid)] = cur
        cset(chat.id, "topic_ayar", tmap)
        await kisa_cevap(context.bot, chat.id, "✅ Konu kuralı kaydedildi.")
        return
    await kisa_cevap(context.bot, chat.id, "Kullanım: <code>/topic mod ciddi</code> · <code>/topic kural ...</code>")


async def bakim_komut(update, context):
    g = await _mod_giris(update, context, "bakim")
    if not g:
        return
    _, chat, _ = g
    ac = not bool(cget(chat.id, "bakim"))
    if context.args:
        ac = context.args[0].lower() in ("ac", "aç", "on", "1")
    cset(chat.id, "bakim", ac)
    await kisa_cevap(context.bot, chat.id, f"🔧 Bakım: {_ok(ac)}")


async def send_komut(update, context):
    """Sahip: ozelden tum bilinen gruplara mesaj."""
    user = update.effective_user
    if not sahip_mi(user):
        return
    met = " ".join(context.args or []).strip()
    if not met:
        try:
            await update.effective_message.reply_text(
                "Kullanım: <code>/send Bakımdayız, birazdan döneriz</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return
    ok_n, fail_n = 0, 0
    for gid in list((durum.get("grup") or {}).keys()):
        try:
            await context.bot.send_message(int(gid), met)
            ok_n += 1
        except Exception:
            fail_n += 1
    try:
        await update.effective_message.reply_text(
            f"📢 Gönderildi: {ok_n} grup" + (f" · hata: {fail_n}" if fail_n else "")
        )
    except Exception:
        pass


async def gruplar_komut(update, context):
    """Sahip: bilinen gruplari listele (ozelden yonetim)."""
    user = update.effective_user
    if not sahip_mi(user):
        return
    liste = gercek_grup_listesi()
    if not liste:
        await update.effective_message.reply_text(
            "Kayıtlı <b>grup</b> yok.\nBotu gruba ekle, grupta bir mesaj atsın, sonra tekrar /gruplar.",
            parse_mode="HTML",
        )
        return
    aktif = _aktif_grup_id()
    lines = ["📋 <b>Grupların</b> (özelden yönetim)", ""]
    for i, (gid, conf) in enumerate(liste[:40], 1):
        title = conf.get("title") or conf.get("baslik") or ""
        mark = " ✅" if aktif and int(aktif) == int(gid) else ""
        lines.append(f"{i}. <code>{gid}</code> {html.escape(str(title)[:40])}{mark}")
    lines.append("")
    lines.append("Seç: <code>/grup 1</code> veya <code>/grup -100...</code>")
    lines.append("Bu gruptaysan: <code>/grup burasi</code>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")



async def grup_sec_komut(update, context):
    """Sahip: aktif yonetim grubunu sec."""
    user = update.effective_user
    chat = update.effective_chat
    if not sahip_mi(user):
        return
    args = context.args or []
    # /grup burasi veya grup icinde /grup
    if (not args and chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup")) or (
        args and kucult(args[0]) in ("burasi", "burada", "this", "bu")
    ):
        if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
            sec = chat.id
        else:
            await update.effective_message.reply_text("Bu komutu grupta yaz veya /gruplar ile sec.")
            return
    elif not args:
        a = _aktif_grup_id()
        await update.effective_message.reply_text(
            f"Aktif grup: <code>{a or 'yok'}</code>\n<code>/gruplar</code> · <code>/grup 1</code> · grupta <code>/grup burasi</code>",
            parse_mode="HTML",
        )
        return
    else:
        key = args[0].strip()
        liste = gercek_grup_listesi()
        sec = None
        if key.isdigit() and 1 <= int(key) <= len(liste):
            sec = liste[int(key) - 1][0]
        else:
            try:
                sec = int(key)
            except Exception:
                sec = None
        if sec is None or sec >= 0:
            await update.effective_message.reply_text(
                "Geçersiz. <code>/gruplar</code> ile bak. Grup id negatif olur (-100...).",
                parse_mode="HTML",
            )
            return
    durum["aktif_grup"] = sec
    if context.user_data is not None:
        context.user_data["panel_gid"] = sec
    conf = (durum.get("grup") or {}).setdefault(str(sec), {})
    try:
        ch = await context.bot.get_chat(sec)
        if getattr(ch, "title", None):
            conf["title"] = ch.title
    except Exception:
        pass
    durum_kaydet()
    await update.effective_message.reply_text(
        f"✅ Aktif grup: <code>{sec}</code> {html.escape(str(conf.get('title') or ''))}\n"
        f"Artık /ban /mute /kick /welcome buraya uygulanır.",
        parse_mode="HTML",
    )



async def durum_komut(update, context):
    user = update.effective_user
    if not sahip_mi(user) and not (update.effective_chat and await admin_mi(update.effective_chat.id, user, context.bot)):
        return
    lines = ["📊 <b>Bot durum</b>", ""]
    lines.append(f"Groq: {_ok(bool(GROQ_KEY))} · Gemini: {_ok(bool(GEMINI_KEY))}")
    lines.append(f"DeepSeek: {_ok(bool(DEEPSEEK_KEY))} · Mistral: {_ok(bool(MISTRAL_KEY))}")
    lines.append(f"OpenRouter: {_ok(bool(OPENROUTER_KEY))}")
    if _ai_latans:
        lines.append("Gecikme: " + ", ".join(f"{k.replace('_sor','')}={v}ms" for k, v in list(_ai_latans.items())[-5:]))
    lines.append(f"MongoDB: {_ok(bool(_mongo_col))}")
    lines.append(f"Fiyat cache: {len(_fiyat_cache)} sembol")
    lines.append(f"CG snapshot: {len(_cg_by_id)} id")
    lines.append(f"Hata buffer: {len(_hata_log)}")
    cd = max(0, int(_cg_cooldown_until - time.time()))
    if cd:
        lines.append(f"CG cooldown: {cd}s")
    try:
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception:
        pass


async def log_komut(update, context):
    user = update.effective_user
    if not sahip_mi(user):
        return
    if not _hata_log:
        await update.effective_message.reply_text("Hata kaydı yok.")
        return
    txt = "🧾 <b>Son hatalar</b>\n\n" + "\n".join(html.escape(x) for x in list(_hata_log)[-20:])
    try:
        await context.bot.send_message(user.id, txt[:3500], parse_mode="HTML")
        await update.effective_message.reply_text("✅ Log DM'ye gitti.")
    except Exception as e:
        await update.effective_message.reply_text(f"DM açılamadı: {e}")


async def rozet_komut(update, context):
    """/rozet @user Doğrulanmış"""
    g = await _mod_giris(update, context, "rozet")
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla <code>/rozet @user İsim</code>")
        return
    ad = " ".join(context.args[1:]) if len(context.args or []) > 1 else "Doğrulanmış"
    if context.args and not context.args[0].startswith("@") and not (update.effective_message.reply_to_message):
        ad = " ".join(context.args) or ad
    rz = dict(cget(chat.id, "rozetler") or {})
    if str(hedef.id) in rz and len(context.args or []) <= 1:
        rz.pop(str(hedef.id), None)
        cset(chat.id, "rozetler", rz)
        await kisa_cevap(context.bot, chat.id, f"Rozet kaldırıldı: {_ad(hedef)}")
        return
    rz[str(hedef.id)] = ad[:40]
    cset(chat.id, "rozetler", rz)
    await kisa_cevap(context.bot, chat.id, f"✅ ✅ {_ad(hedef)} → <b>{html.escape(ad)}</b>")


async def uye_guncelle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Invite link kaynak sayimi (ChatMemberHandler)."""
    res = update.chat_member or update.my_chat_member
    if not res:
        return
    chat = res.chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return
    old = res.old_chat_member
    new = res.new_chat_member
    if not new or not new.user or new.user.is_bot:
        return
    # yeni uye
    was = old.status if old else None
    now = new.status
    if was in ("left", "kicked", "banned", ChatMemberStatus.LEFT, ChatMemberStatus.BANNED, None) and now in (
        "member", "restricted", ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED
    ):
        uye_kaydi(chat.id, new.user)
        try:
            await yeni_uye_karsila(context.bot, chat, new.user, context)
        except Exception as e:
            log.warning("uye_guncelle karsila: %s", e)
        il = getattr(res, "invite_link", None)
        if il and getattr(il, "name", None):
            name = (il.name or "").lower()
            kaynak = "diger"
            for k in ("twitter", "youtube", "instagram", "tiktok", "telegram"):
                if k in name:
                    kaynak = k
                    break
            if name.startswith("src_"):
                kaynak = name[4:] or kaynak
            dk = dict(cget(chat.id, "davet_kaynak") or {})
            dk[kaynak] = int(dk.get(kaynak) or 0) + 1
            cset(chat.id, "davet_kaynak", dk)
            await log_gonder(
                context.bot, chat.id,
                f"➕ {html.escape(new.user.full_name or str(new.user.id))} · kaynak: <b>{kaynak}</b>",
            )


async def itiraz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("it:"):
        return
    parts = q.data.split(":")
    if len(parts) < 4:
        return
    islem, cid, uid = parts[1], int(parts[2]), int(parts[3])
    if not sahip_mi(q.from_user) and not await admin_mi(cid, q.from_user, context.bot):
        await q.answer("Yetkin yok", show_alert=True)
        return
    await q.answer()
    if islem == "ok":
        try:
            await context.bot.unban_chat_member(cid, uid, only_if_banned=True)
            try:
                await context.bot.send_message(uid, "✅ İtirazın kabul edildi, gruba dönebilirsin.")
            except Exception:
                pass
            await q.edit_message_text(f"✅ İtiraz kabul — uid {uid}")
        except Exception as e:
            await q.edit_message_text(f"Hata: {e}")
    else:
        try:
            await context.bot.send_message(uid, "İtirazın reddedildi.")
        except Exception:
            pass
        try:
            await q.edit_message_text("İtiraz reddedildi.")
        except Exception:
            pass


KOMUT_LISTESI = (
    "📌 <b>Sahip komutları (özelde)</b>\n\n"
    "<b>Grup seç / yayın</b>\n"
    "• <code>/gruplar</code> — botun bildiği gruplar\n"
    "• <code>/grup 1</code> — aktif yönetim grubu seç\n"
    "• <code>/send metin</code> — tüm gruplara duyuru\n"
    "• <code>gruba gönder metin</code> — aynı\n"
    "• <code>bakım aç</code> / <code>bakım kapat</code> — bakım + gruba bilgi\n\n"
    "<b>Moderasyon (önce /grup seç)</b>\n"
    "• <code>/ban @user sebep</code> — ban\n"
    "• <code>/unban id/@user</code> — ban kaldır\n"
    "• <code>/kick @user</code> — gruptan at\n"
    "• <code>/mute @user 30</code> — dk sustur\n"
    "• <code>/unmute @user</code>\n"
    "• <code>/warn @user</code> · <code>/unwarn</code>\n"
    "• <code>/yasaklilar</code> — ban listesi\n\n"
    "<b>Link / reklam</b>\n"
    "• <code>link engel aç</code> — üye link/buton atamaz\n"
    "• <code>link engel kapat</code> — serbest\n"
    "• <code>/izinlink t.me/kanal</code> — istisna domain\n"
    "• Panel: <b>Link/Reklam</b> butonu\n\n"
    "<b>Panel & ayar</b>\n"
    "• <code>/panel</code> veya <code>/ayarlar</code> — butonlu panel\n"
    "• <code>/setwelcome metin</code> · <code>/setrules</code>\n"
    "• <code>/setlog</code> · <code>/unsetlog</code>\n"
    "• <code>/duyuru</code> · <code>/ipucu</code> ayarları\n"
    "• <code>/ozellik</code> · <code>/durum</code> · <code>/log</code>\n"
    "• <code>/bakim</code> · <code>/mod</code>\n\n"
    "<b>Sohbet</b>\n"
    "• Grupta <code>yapay ...</code> — AI cevap\n"
    "• <code>btc</code> / <code>1 eth</code> — fiyat\n"
    "• <code>adam asmaca</code> — oyun\n"
    "• <code>/komutlar</code> — bu listeyi tekrar getir\n"
)


async def komutlar_komut(update, context):
    user = update.effective_user
    if not sahip_mi(user):
        return
    try:
        await update.effective_message.reply_text(KOMUT_LISTESI, parse_mode="HTML")
    except Exception:
        pass


async def sabah_brifing(context: ContextTypes.DEFAULT_TYPE):
    """Sahibe sabah ozet + komut listesi (gunde 1)."""
    now = datetime.now(TR)
    if now.hour != 9:
        return
    key = f"brif:{now.strftime('%Y-%m-%d')}"
    if durum.get("brif_son") == key:
        return
    lines = ["☀️ <b>Sabah brifing</b>", ""]
    for gid_s, conf in list((durum.get("grup") or {}).items()):
        if not isinstance(conf, dict):
            continue
        st = conf.get("istatistik") or {}
        cg = conf.get("ceza_gun") or {}
        lines.append(
            f"Grup <code>{gid_s}</code>\n"
            f"• Spam sil: {st.get('spam', 0)} · Mesaj: {st.get('mesaj', 0)}\n"
            f"• Giren/çıkan: {st.get('giren', 0)}/{st.get('cikan', 0)}\n"
            f"• Bugün ceza: {cg.get('say', 0)}/{conf.get('ceza_tavan', 10)}\n"
            f"• Link engel: {'açık' if conf.get('link_engel') else 'kapalı'}\n"
        )
    lines.append("Bekleyen: /log ile son hatalar")
    try:
        await context.bot.send_message(SAHIP_ID, "\n".join(lines)[:3500], parse_mode="HTML")
    except Exception as e:
        log.warning("brifing: %s", e)
    # komut hatirlatma (ayri mesaj)
    try:
        await context.bot.send_message(SAHIP_ID, KOMUT_LISTESI, parse_mode="HTML")
    except Exception as e:
        log.warning("komut listesi dm: %s", e)
    durum["brif_son"] = key
    durum_kaydet()


async def reaksiyon_yonet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🚫 sil+uyar, 💀 mute — MessageReactionHandler."""
    try:
        mr = update.message_reaction
    except Exception:
        return
    if not mr or not mr.chat:
        return
    cid = mr.chat.id
    if not cget(cid, "reaksiyon_yonetim"):
        return
    user = mr.user
    if not user or not (await admin_mi(cid, user, context.bot) or sahip_mi(user) or moderator_mi(cid, user)):
        return
    yeni = []
    for r in (mr.new_reaction or []):
        emoji = getattr(r, "emoji", None) or str(r)
        yeni.append(emoji)
    mid = mr.message_id
    if "🚫" in yeni or "⛔" in yeni:
        try:
            await context.bot.delete_message(cid, mid)
            await kisa_cevap(context.bot, cid, "🗑 Reaksiyonla silindi.", 6)
        except Exception:
            pass
    elif "💀" in yeni or "☠️" in yeni:
        # hedef bilinmiyor reaction'da — sadece mesaji silmeye calis + log
        try:
            await context.bot.delete_message(cid, mid)
            await log_gonder(context.bot, cid, f"💀 Reaksiyon mute/sil denendi mid={mid}")
        except Exception:
            pass


async def haftanin_mesaji_job(context: ContextTypes.DEFAULT_TYPE):
    """Arsivden uzun/kaliteli bir mesaji 'haftanin mesaji' sec (reaksiyon API yoksa yaklasik)."""
    import random
    now = datetime.now(TR)
    if now.weekday() != 6 or not (18 <= now.hour <= 20):  # pazar aksam
        return
    key = f"hm:{now.isocalendar()[0]}-{now.isocalendar()[1]}"
    if durum.get("hm_son") == key:
        return
    for gid_s in list((durum.get("grup") or {}).keys()):
        try:
            gid = int(gid_s)
        except Exception:
            continue
        arsiv = [x for x in list(_mesaj_arsiv.get(gid) or []) if len((x.get("text") or "")) > 40]
        if not arsiv:
            continue
        sec = max(arsiv[-50:], key=lambda x: len(x.get("text") or ""))
        try:
            await context.bot.send_message(
                gid,
                f"🏅 <b>Haftanın mesajı</b> (öne çıkan paylaşım)\n"
                f"{html.escape(sec.get('ad') or '?')}:\n"
                f"<i>{html.escape((sec.get('text') or '')[:200])}</i>",
                parse_mode="HTML",
            )
            if sec.get("uid"):
                guven_ekle(gid, int(sec["uid"]), 4)
        except Exception:
            pass
    durum["hm_son"] = key
    durum_kaydet()


async def hafta_dolandirici_job(context: ContextTypes.DEFAULT_TYPE):
    """Haftada bir dolandiricilik bulteni."""
    import random
    now = datetime.now(TR)
    if now.weekday() != 0 or now.hour != 12:  # pazartesi ~12
        # her saatte bir kontrol; ayni hafta tekrar yok
        pass
    key = f"dol:{now.isocalendar()[0]}-{now.isocalendar()[1]}"
    if durum.get("dol_son") == key:
        return
    # sadece pazartesi gonder (saat genis: 10-14)
    if now.weekday() != 0 or not (10 <= now.hour <= 14):
        return
    text = "🛡 <b>Haftanın dolandırıcılık yöntemi</b>\n\n" + random.choice(_HAFTA_DOLANDIRICI)
    for gid_s in list((durum.get("grup") or {}).keys()):
        try:
            await context.bot.send_message(int(gid_s), text, parse_mode="HTML")
        except Exception:
            pass
    durum["dol_son"] = key
    durum_kaydet()


async def gunun_uyesi_job(context: ContextTypes.DEFAULT_TYPE):
    """Her gun en aktif uyeyi sec."""
    import random
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    if durum.get("gunun_uye_tarih") == bugun:
        return
    for gid_s, conf in list((durum.get("grup") or {}).items()):
        if not isinstance(conf, dict):
            continue
        try:
            gid = int(gid_s)
        except Exception:
            continue
        uy = uyeler.get(str(gid)) or {}
        if not uy:
            continue
        # mesaj sayisina gore ust 5'ten random
        sirali = sorted(uy.items(), key=lambda x: int((x[1] or {}).get("mesaj") or 0), reverse=True)[:8]
        if not sirali:
            continue
        uid, bil = random.choice(sirali[:5])
        ad = (bil or {}).get("ad") or uid
        try:
            await context.bot.send_message(
                gid,
                f"🌟 <b>Günün üyesi</b>: {html.escape(str(ad).split()[0])}\n"
                f"Aktif katkın için teşekkürler!",
                parse_mode="HTML",
            )
            guven_ekle(gid, int(uid), 3)
        except Exception:
            pass
    durum["gunun_uye_tarih"] = bugun
    durum_kaydet()


async def tahmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("th:"):
        return
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    taraf, cid = parts[1], int(parts[2])
    th = cget(cid, "tahmin")
    if not th or not th.get("soru"):
        await q.answer("Tahmin kapalı", show_alert=True)
        return
    uid = q.from_user.id
    evet = [int(x) for x in (th.get("evet") or [])]
    hayir = [int(x) for x in (th.get("hayir") or [])]
    if uid in evet or uid in hayir:
        await q.answer("Zaten oy verdin")
        return
    if taraf == "e":
        evet.append(uid)
    else:
        hayir.append(uid)
    th["evet"] = evet
    th["hayir"] = hayir
    cset(cid, "tahmin", th)
    await q.answer("Oy kaydedildi")
    try:
        await q.edit_message_text(
            f"🎯 <b>Tahmin</b>\n{html.escape(th['soru'])}\n\n"
            f"✅ {len(evet)} · ❌ {len(hayir)}\n"
            f"<i>Yatırım tavsiyesi değildir.</i>",
            parse_mode="HTML",
            reply_markup=q.message.reply_markup,
        )
    except Exception:
        pass


async def sikayet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("sk:"):
        return
    parts = q.data.split(":")
    # sk:ban:chat:uid:mid  | sk:sil:... | sk:yok:...
    if len(parts) < 5:
        return
    islem, cid, uid, mid = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
    if not await admin_mi(cid, q.from_user, context.bot) and not sahip_mi(q.from_user):
        await q.answer("Yetkin yok", show_alert=True)
        return
    await q.answer()
    if islem == "ban":
        try:
            await context.bot.ban_chat_member(cid, uid)
            await q.edit_message_text(f"🚫 Banlandı uid={uid}")
        except Exception as e:
            await q.edit_message_text(f"Hata: {e}")
    elif islem == "sil":
        try:
            await context.bot.delete_message(cid, mid)
            await q.edit_message_text("🗑 Mesaj silindi")
        except Exception as e:
            await q.edit_message_text(f"Silinemedi: {e}")
    else:
        try:
            await q.edit_message_text("Yok sayıldı.")
        except Exception:
            pass


async def sohbet_baslatici(context: ContextTypes.DEFAULT_TYPE):
    """Sessiz gruplara konu at (gece 00-08 yok)."""
    import random
    saat = datetime.now(TR).hour
    if 0 <= saat < 8:
        return
    konular = [
        "💬 Bugün hangi airdrop’a bakıyorsunuz?",
        "💬 Portföyde bu hafta ne değişti?",
        "💬 Gas ücretleri nasıl, zincir öneriniz var mı?",
        "💬 Yeni başlayan birine tek cümle tavsiyeniz?",
        "💬 En çok pişman olduğunuz işlem neydi? (isterseniz yazın)",
    ]
    now = time.time()
    for gid_s, conf in list((durum.get("grup") or {}).items()):
        if not isinstance(conf, dict) or not conf.get("sohbet_baslat", True):
            continue
        try:
            gid = int(gid_s)
        except Exception:
            continue
        son = float(_son_grup_mesaj.get(gid) or conf.get("son_mesaj_ts") or 0)
        saat_sn = float(conf.get("sohbet_sessiz_saat") or 3) * 3600
        if son and now - son >= saat_sn:
            try:
                await context.bot.send_message(gid, random.choice(konular))
                conf["son_mesaj_ts"] = now
                _son_grup_mesaj[gid] = now
                durum_kaydet()
            except Exception as e:
                log.warning("sohbet baslat %s: %s", gid, e)


def _yabanci_spam_mi(metin: str) -> bool:
    """Turkce grupta yabanci dil agirlikli kisa reklam."""
    if not metin or len(metin) < 20:
        return False
    # kiril / cin / arap agir
    if len(re.findall(r"[\u0400-\u04FF]", metin)) > 15:
        return True
    if len(re.findall(r"[\u4e00-\u9fff]", metin)) > 8:
        return True
    if len(re.findall(r"[\u0600-\u06FF]", metin)) > 15:
        return True
    # latin ama turkce karakter yok + crypto spam kalibi
    if not re.search(r"[ğüşıöçĞÜŞİÖÇ]", metin):
        low = metin.lower()
        if any(x in low for x in ("airdrop", "claim", "free token", "connect wallet", "http")) and len(metin) > 40:
            tr_kelime = sum(1 for w in ("ve", "bir", "bu", "için", "icin", "var", "yok", "nedir") if w in low)
            if tr_kelime == 0:
                return True
    return False


_OZEL_GUN = {
    "01-01": "🎉 Yeni yılınız kutlu olsun!",
    "04-23": "🇹🇷 23 Nisan kutlu olsun!",
    "05-01": "🌺 Emek ve Dayanışma Günü kutlu olsun!",
    "05-19": "🇹🇷 19 Mayıs kutlu olsun!",
    "08-30": "🇹🇷 30 Ağustos zaferi kutlu olsun!",
    "10-29": "🇹🇷 Cumhuriyet Bayramı kutlu olsun!",
}


async def ozel_gun_job(context: ContextTypes.DEFAULT_TYPE):
    bugun = datetime.now(TR).strftime("%m-%d")
    msg = _OZEL_GUN.get(bugun)
    if not msg:
        return
    key = f"ozel:{bugun}:{datetime.now(TR).year}"
    if durum.get("ozel_gonderilen") == key:
        return
    for gid_s in list((durum.get("grup") or {}).keys()):
        try:
            await context.bot.send_message(int(gid_s), msg)
        except Exception:
            pass
    durum["ozel_gonderilen"] = key
    durum_kaydet()


# ---------- ekonomik takvim (yaklasik / bilinen yuksek etkili gunler) ----------
# format: (ay, gun, aciklama) — yillik tekrar veya ozel yil
_EKONOMI_TAKVIM = [
    (1, 15, "ABD enflasyon (CPI) haftası — volatilite artabilir"),
    (3, 19, "FED faiz kararı dönemi — piyasada sarsıntı olabilir"),
    (5, 7, "FED faiz kararı dönemi — volatilite uyarısı"),
    (6, 12, "ABD enflasyon verisi dönemi"),
    (6, 18, "FED faiz kararı dönemi"),
    (7, 15, "ABD enflasyon (CPI) dönemi"),
    (9, 17, "FED faiz kararı dönemi"),
    (11, 5, "FED faiz kararı dönemi"),
    (12, 17, "FED faiz kararı dönemi — yıl sonu volatilite"),
]


async def ekonomi_takvim_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TR)
    for ay, gun, acik in _EKONOMI_TAKVIM:
        if now.month == ay and now.day == gun:
            key = f"eko:{now.year}-{ay}-{gun}"
            if durum.get("eko_son") == key:
                return
            text = f"📅 <b>Ekonomik takvim</b>\n{html.escape(acik)}\n⚠️ Yatırım tavsiyesi değildir."
            for gid_s in list((durum.get("grup") or {}).keys()):
                try:
                    await context.bot.send_message(int(gid_s), text, parse_mode="HTML")
                except Exception:
                    pass
            durum["eko_son"] = key
            durum_kaydet()
            return


async def gecici_ceza_job(context: ContextTypes.DEFAULT_TYPE):
    """Suresi biten mute: gruba duyur + 5 dk izlemeye al."""
    now = time.time()
    for gid_s, conf in list((durum.get("grup") or {}).items()):
        if not isinstance(conf, dict):
            continue
        cezalar = dict(conf.get("gecici_ceza") or {})
        degisti = False
        for uid, bil in list(cezalar.items()):
            bitis = float((bil or {}).get("bitis") or 0)
            if bitis and now >= bitis:
                cezalar.pop(uid, None)
                degisti = True
                ad = html.escape((bil or {}).get("ad") or "Üye")
                try:
                    await context.bot.send_message(
                        int(gid_s),
                        f"✅ <a href='tg://user?id={uid}'>{ad}</a> cezası bitti — tekrar yazabilir.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                try:
                    _ceza_izle[(int(gid_s), int(uid))] = {
                        "until": now + 300,
                        "count": 0,
                        "max": 5,
                        "ad": (bil or {}).get("ad") or "",
                    }
                except Exception:
                    pass
        if degisti:
            conf["gecici_ceza"] = cezalar
            durum_kaydet()



def _cuzdan_eth(addr: str):
    """Ucretsiz public endpoint — basarisiz olabilir."""
    try:
        r = requests.get(
            f"https://api.ethplorer.io/getAddressInfo/{addr}",
            params={"apiKey": "freekey"},
            timeout=12,
        )
        if not r.ok:
            return None
        j = r.json()
        eth = (j.get("ETH") or {}).get("balance")
        txc = j.get("countTxs")
        return {"chain": "ETH", "balance": eth, "tx": txc, "addr": addr}
    except Exception as e:
        log.warning("ethplorer: %s", e)
        return None


def _cuzdan_btc(addr: str):
    try:
        r = requests.get(f"https://blockchain.info/balance?active={addr}", timeout=12)
        if not r.ok:
            return None
        j = r.json().get(addr) or {}
        sat = int(j.get("final_balance") or 0)
        return {"chain": "BTC", "balance": sat / 1e8, "tx": j.get("n_tx"), "addr": addr}
    except Exception as e:
        log.warning("btc explorer: %s", e)
        return None


def _adres_mi(metin: str):
    t = (metin or "").strip()
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", t):
        return "eth", t
    if re.fullmatch(r"[13][a-km-zA-HJ-NP-Z1-9]{25,34}", t) or re.fullmatch(r"bc1[a-z0-9]{25,62}", t):
        return "btc", t
    return None, None


async def acilis_testi(bot):
    """API + DB kontrol, bozuksa sahip DM."""
    sorunlar = []
    if not TELEGRAM_TOKEN:
        sorunlar.append("TELEGRAM_TOKEN yok")
    if not any([GROQ_KEY, GEMINI_KEY, DEEPSEEK_KEY, MISTRAL_KEY, OPENROUTER_KEY]):
        sorunlar.append("Hiç AI key yok")
    # kisa CG ping
    try:
        r = requests.get(f"{CG_BASE}/ping", timeout=8)
        if not r.ok:
            sorunlar.append(f"CoinGecko ping {r.status_code}")
    except Exception as e:
        sorunlar.append(f"CoinGecko: {e}")
    if _MONGO_URI and not _mongo_col:
        sorunlar.append("Mongo URI var ama baglanamadi")
    try:
        await bot.send_message(
            SAHIP_ID,
            f"🚀 <b>{BOT_SURUM}</b> çalışıyor\n"
            + ("⚠️ " + " | ".join(sorunlar) if sorunlar else "✅ API/DB kontrol OK"),
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning("acilis DM: %s", e)
    return sorunlar


async def mod_komut(update, context):
    """/mod @user — moderatör ekle (mute/warn, ban yok)"""
    g = await _mod_giris(update, context, "mod")
    if not g:
        return
    _, chat, _ = g
    hedef = await hedef_kullanici(update, context)
    if not hedef:
        await kisa_cevap(context.bot, chat.id, "Yanıtla veya @user ile <code>/mod</code>")
        return
    mods = [int(x) for x in (cget(chat.id, "moderatorler") or [])]
    if hedef.id in mods:
        mods = [x for x in mods if x != hedef.id]
        cset(chat.id, "moderatorler", mods)
        await kisa_cevap(context.bot, chat.id, f"Moderatörlük alındı: {_ad(hedef)}")
    else:
        mods.append(hedef.id)
        cset(chat.id, "moderatorler", mods)
        await kisa_cevap(context.bot, chat.id, f"✅ Moderör: {_ad(hedef)}")


def moderator_mi(chat_id, user) -> bool:
    if not user:
        return False
    if sahip_mi(user):
        return True
    mods = [int(x) for x in (cget(chat_id, "moderatorler") or [])]
    return user.id in mods


async def kuralonay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("ko:"):
        return
    parts = q.data.split(":")
    if len(parts) < 3:
        return
    cid, uid = int(parts[1]), int(parts[2])
    if q.from_user.id != uid:
        await q.answer("Bu buton sana değil.", show_alert=True)
        return
    onayli = [str(x) for x in (cget(cid, "kural_onayli") or [])]
    if str(uid) not in onayli:
        onayli.append(str(uid))
        cset(cid, "kural_onayli", onayli[-500:])
    await q.answer("Kurallar kabul edildi ✅")
    try:
        await q.edit_message_text("✅ Kuralları kabul ettin, yazabilirsin.")
    except Exception:
        pass


def _isim_adaylari(chat_id, isim: str):
    """Grup uyelerinden isim eslesenler."""
    isim = (isim or "").lower().strip()
    if not isim or len(isim) < 2:
        return []
    aday = []
    for uid, bil in (uyeler.get(str(chat_id)) or {}).items():
        ad = (bil.get("ad") or "").lower()
        un = (bil.get("kullanici") or "").lower()
        if isim in ad.split() or isim == ad or isim == un or ad.startswith(isim):
            aday.append(_FakeUser(uid, bil.get("ad") or uid, un))
    return aday[:8]


async def _anti_nuke_kontrol(bot, chat_id, by_id, tip) -> bool:
    """True = islem engellendi."""
    if not cget(chat_id, "anti_nuke"):
        return False
    if tip not in ("ban", "mute", "kick"):
        return False
    if by_id and by_id == SAHIP_ID:
        return False
    key = (chat_id, by_id or 0)
    now = time.time()
    sn = int(cget(chat_id, "anti_nuke_sn") or 60)
    adet = int(cget(chat_id, "anti_nuke_adet") or 5)
    buf = _nuke_buf[key]
    while buf and now - buf[0] > sn:
        buf.popleft()
    buf.append(now)
    if len(buf) >= adet:
        try:
            await bot.send_message(
                SAHIP_ID,
                f"🚨 <b>Anti-nuke</b>\nGrup <code>{chat_id}</code>\n"
                f"Admin <code>{by_id}</code> kısa sürede {len(buf)} {tip} denedi — durduruldu.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await log_gonder(bot, chat_id, f"🚨 Anti-nuke: admin {by_id} işlemi kesildi")
        return True
    return False


def _ceza_tavan_ok(chat_id) -> bool:
    """Gunluk ceza tavani — False = dur."""
    tavan = int(cget(chat_id, "ceza_tavan") or 10)
    if tavan <= 0:
        return True
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    cg = dict(cget(chat_id, "ceza_gun") or {})
    if cg.get("tarih") != bugun:
        cg = {"tarih": bugun, "say": 0}
    if int(cg.get("say") or 0) >= tavan:
        return False
    return True


def _ceza_tavan_artir(chat_id):
    bugun = datetime.now(TR).strftime("%Y-%m-%d")
    cg = dict(cget(chat_id, "ceza_gun") or {})
    if cg.get("tarih") != bugun:
        cg = {"tarih": bugun, "say": 0}
    cg["say"] = int(cg.get("say") or 0) + 1
    cset(chat_id, "ceza_gun", cg)


async def _islem_uygula(bot, chat_id, tip, hedef_id, by_id=None):
    """ban/mute/unban uygula + geri al kaydi."""
    try:
        if tip in ("ban", "mute") and not _ceza_tavan_ok(chat_id):
            try:
                await bot.send_message(
                    SAHIP_ID,
                    f"🛑 <b>Ceza tavanı</b>\nGrup <code>{chat_id}</code> günlük limite ulaştı.\n"
                    f"Yeni {tip} durduruldu. Artırmak için: yapay ceza tavan 20",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return False
        if tip in ("ban", "mute") and cget(chat_id, "golge"):
            await log_gonder(
                bot, chat_id,
                f"👤 Gölge: {tip} uygulanırdı → <code>{hedef_id}</code> (ceza yok)",
            )
            return True  # "basarili" gibi davran ama ceza yok
        if await _anti_nuke_kontrol(bot, chat_id, by_id, tip):
            return False
        if tip == "ban":
            await bot.ban_chat_member(chat_id, hedef_id)
            _ceza_tavan_artir(chat_id)
            try:
                yasakli_kaydet(chat_id, _FakeUser(hedef_id), "ban", _FakeUser(by_id) if by_id else None)
            except Exception:
                pass
            if ozellik_acik(chat_id, "fed_ban"):
                fed_ban_ekle(hedef_id, sebep="ban")
        elif tip == "mute":
            until = datetime.now(timezone.utc) + timedelta(minutes=60)
            await bot.restrict_chat_member(chat_id, hedef_id, permissions=MUTE_PERMS, until_date=until)
            _ceza_tavan_artir(chat_id)
        elif tip == "unban":
            await bot.unban_chat_member(chat_id, hedef_id, only_if_banned=True)
        elif tip == "unmute":
            await bot.restrict_chat_member(chat_id, hedef_id, permissions=FULL_PERMS)
        _son_islem[str(chat_id)] = {
            "tip": tip, "hedef_id": hedef_id, "by": by_id, "ts": time.time()
        }
        return True
    except Exception as e:
        log.warning("islem %s: %s", tip, e)
        return False


async def _nl_mod_onay(update, context, tip, adaylar, by_user):
    """Birden fazla Ahmet veya emin misin butonu."""
    chat = update.effective_chat
    if len(adaylar) > 1:
        rows = []
        for a in adaylar:
            rows.append([InlineKeyboardButton(
                f"{(a.full_name or str(a.id))[:28]}",
                callback_data=f"onay:{tip}:{chat.id}:{a.id}:{by_user.id}",
            )])
        rows.append([InlineKeyboardButton("İptal", callback_data="onay:iptal:0:0:0")])
        await update.effective_message.reply_text(
            f"Hangisini <b>{tip}</b>?\nEmin misin — seç:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return
    a = adaylar[0]
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Evet, {tip}", callback_data=f"onay:{tip}:{chat.id}:{a.id}:{by_user.id}"),
            InlineKeyboardButton("❌ İptal", callback_data="onay:iptal:0:0:0"),
        ]
    ])
    await update.effective_message.reply_text(
        f"⚠️ <b>{html.escape(a.full_name or str(a.id))}</b> için <code>{tip}</code>?\nEmin misin?",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def onay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data or not q.data.startswith("onay:"):
        return
    parts = q.data.split(":")
    if len(parts) < 5:
        return
    tip, cid_s, hid_s, by_s = parts[1], parts[2], parts[3], parts[4]
    if tip == "iptal":
        await q.answer("İptal")
        try:
            await q.edit_message_text("İptal edildi.")
        except Exception:
            pass
        return
    try:
        cid, hid, by = int(cid_s), int(hid_s), int(by_s)
    except Exception:
        return
    if q.from_user.id != by and not sahip_mi(q.from_user):
        await q.answer("Bu onay sana değil.", show_alert=True)
        return
    # cift onay kritik
    if tip == "ban" and cget(cid, "cift_onay_ban"):
        oid = f"{cid}:{hid}:{tip}"
        bag = _cift_onay.setdefault(oid, {"onaylar": set(), "ihtiyac": 2})
        bag["onaylar"].add(q.from_user.id)
        if len(bag["onaylar"]) < 2:
            await q.answer("1/2 onay — ikinci admin de onaylasın")
            try:
                await q.edit_message_text(
                    f"🔐 Ban için 2 admin onayı: {len(bag['onaylar'])}/2\n"
                    f"Başka admin de butona bassın.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Onaylıyorum", callback_data=q.data),
                        InlineKeyboardButton("İptal", callback_data="onay:iptal:0:0:0"),
                    ]]),
                )
            except Exception:
                pass
            return
        _cift_onay.pop(oid, None)
    ok = await _islem_uygula(context.bot, cid, tip, hid, by)
    await q.answer("Tamam" if ok else "Hata")
    try:
        await q.edit_message_text(
            f"{'✅' if ok else '❌'} <code>{tip}</code> uygulandı. Geri almak için: <code>yapay son işlemi geri al</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass


def _spam_benzer(chat_id, metin: str) -> bool:
    if not cget(chat_id, "spam_ogren"):
        return False
    norm = re.sub(r"\s+", " ", (metin or "").lower().strip())
    if len(norm) < 8:
        return False
    for ornek in _spam_ornek.get(str(chat_id)) or []:
        if norm == ornek or (len(norm) > 15 and (norm in ornek or ornek in norm)):
            return True
        # kisa ortak
        a, b = set(norm.split()), set(ornek.split())
        if len(a) >= 3 and len(a & b) / max(len(a), 1) >= 0.7:
            return True
    return False



async def link_filtre_oncelik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Boostlu = link silinmez. Digerleri link_engel aciksa silinir."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if getattr(chat, "type", None) not in (ChatType.GROUP, ChatType.SUPERGROUP, "group", "supergroup"):
        return
    if getattr(user, "is_bot", False):
        return
    # kanal / otomatik iletim — bagli kanal serbest
    if getattr(msg, "is_automatic_forward", False):
        return
    if getattr(msg, "sender_chat", None) is not None:
        return
    # baska gruptan ILET
    if cget(chat.id, "forward_engel") and mesaj_iletildi_mi(msg):
        try:
            if not await admin_mi(chat.id, user, context.bot) and not sahip_mi(user):
                if not ilet_izinli_mi(chat.id, msg):
                    await msg.delete()
                    log.info("ilet silindi (oncelik) uid=%s", user.id)
                    raise ApplicationHandlerStop
        except ApplicationHandlerStop:
            raise
        except Exception as e:
            log.warning("ilet filtre: %s", e)
    if getattr(msg, "sender_boost_count", None):
        pass
    metin = (msg.text or msg.caption or "") or ""
    try:
        var_link = mesajda_link_var(msg, metin)
    except Exception:
        var_link = bool(metin and LINK_RE.search(metin))
    if not var_link:
        return
    uid = user.id
    cid = chat.id
    # sahip / admin
    try:
        if sahip_mi(user):
            return
        if await admin_mi(cid, user, context.bot):
            return
    except Exception:
        pass
    # BOOST — en onemli
    if boost_link_hakki_var(cid, uid):
        try:
            boost_link_kullan(cid, uid)
        except Exception:
            pass
        try:
            _LINK_GECTI.add((cid, msg.message_id))
        except Exception:
            pass
        log.info("BOOST LINK SERBEST uid=%s chat=%s", uid, cid)
        return
    # engel kapaliysa birak
    if not cget(cid, "link_engel"):
        return
    # domain izin
    izin = [x.lower() for x in (cget(cid, "link_izin") or [])]
    low = metin.lower()
    if any(d and d in low for d in izin):
        return
    # SIL (boost zaten ustte return etti)
    ok = await guvenli_sil(msg, "link_engel", user=user, chat_id=cid)
    if ok:
        raise ApplicationHandlerStop
    return



async def mesaj_duzenlendi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit tuzagi: duzenlenen mesaji tekrar tara."""
    msg = update.edited_message or update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or chat.type == ChatType.PRIVATE:
        return
    if not await sahip_grupta_mi(context.bot, chat.id):
        return
    metin = (msg.text or msg.caption or "").strip()
    if not metin:
        return
    # seed
    if _SEED_RE.search(metin) and len(metin.split()) >= 12:
        try:
            await msg.delete()
        except Exception:
            pass
        return
    # link tara
    if ozellik_acik(chat.id, "link_tara"):
        for url in linkleri_cikar(metin, msg):
            guven, neden = link_guvenli_mi(url)
            if not guven:
                try:
                    await msg.delete()
                    await kisa_cevap(context.bot, chat.id, f"🛡 Düzenlenen zararlı link silindi ({neden})", 10)
                except Exception:
                    pass
                return
    # link engel
    if cget(chat.id, "link_engel") and mesajda_link_var(msg, metin):
        is_adm = await admin_mi(chat.id, user, context.bot)
        if not is_adm:
            izin = [x.lower() for x in (cget(chat.id, "link_izin") or [])]
            ok = any(d and d in metin.lower() for d in izin)
            if not ok and boost_link_hakki_var(chat.id, user.id):
                ok = True
            if not ok:
                try:
                    await msg.delete()
                except Exception:
                    pass


# ---------- hosgeldin / ayrildi / servis ----------
async def yetki_kontrol(bot, chat_id, bildir=True):
    """Bot kendi yetkilerini kontrol eder, eksikleri adminlere soyler."""
    eksik = []
    try:
        me = await bot.get_me()
        m = await bot.get_chat_member(chat_id, me.id)
        if m.status not in (ChatMemberStatus.ADMINISTRATOR, "administrator"):
            eksik.append("bot yönetici değil")
        else:
            if hasattr(m, "can_delete_messages") and m.can_delete_messages is False:
                eksik.append("mesaj silme")
            if hasattr(m, "can_restrict_members") and m.can_restrict_members is False:
                eksik.append("üye kısıtlama (mute/ban)")
            if hasattr(m, "can_pin_messages") and m.can_pin_messages is False:
                eksik.append("sabitleme")
            if hasattr(m, "can_invite_users") and m.can_invite_users is False:
                eksik.append("davet linki")
    except Exception as e:
        eksik.append(f"kontrol hatası: {e}")
    if eksik and bildir:
        try:
            await bot.send_message(
                chat_id,
                "⚠️ <b>Bot yetki uyarısı</b>\nEksik: "
                + ", ".join(html.escape(x) for x in eksik)
                + "\nBu yüzden spam silme / mute çalışmayabilir.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    return eksik


async def kriz_ac(chat_id):
    if cget(chat_id, "kriz"):
        return False
    yedek = {
        "link_engel": cget(chat_id, "link_engel"),
        "flood": cget(chat_id, "flood"),
        "hosgeldin_mute": cget(chat_id, "hosgeldin_mute"),
        "medya_engel": cget(chat_id, "medya_engel"),
        "yavas": True,
    }
    cset(chat_id, "kriz_yedek", yedek)
    cset(chat_id, "kriz", True)
    cset(chat_id, "link_engel", True)
    cset(chat_id, "flood", True)
    cset(chat_id, "hosgeldin_mute", 30)
    cset(chat_id, "medya_engel", True)
    return True


async def kriz_kapat(chat_id, bot=None):
    if not cget(chat_id, "kriz"):
        return False
    yedek = cget(chat_id, "kriz_yedek") or {}
    for k, v in yedek.items():
        if k != "yavas":
            cset(chat_id, k, v)
    cset(chat_id, "kriz", False)
    cset(chat_id, "kriz_yedek", {})
    if bot:
        try:
            await bot.set_chat_slow_mode_delay(chat_id, 0)
        except Exception:
            pass
    return True


async def etkinlik_ac(chat_id, tip="ama"):
    if cget(chat_id, "etkinlik"):
        return False
    cset(chat_id, "etkinlik_yedek", {
        "link_engel": cget(chat_id, "link_engel"),
        "flood": cget(chat_id, "flood"),
        "bot_mod": cget(chat_id, "bot_mod"),
        "privacy_ai": cget(chat_id, "privacy_ai"),
    })
    cset(chat_id, "etkinlik", True)
    cset(chat_id, "link_engel", True)
    cset(chat_id, "flood", True)
    cset(chat_id, "bot_mod", "ciddi")
    cset(chat_id, "privacy_ai", True)
    return True


async def etkinlik_kapat(chat_id):
    if not cget(chat_id, "etkinlik"):
        return False
    yedek = cget(chat_id, "etkinlik_yedek") or {}
    for k, v in yedek.items():
        cset(chat_id, k, v)
    cset(chat_id, "etkinlik", False)
    cset(chat_id, "etkinlik_yedek", {})
    return True



def hosgeldin_metin_hazirla(sablon: str, ad_esc: str) -> str:
    """Markdown kalintilarini HTML yap; {ad}/{name} degistir."""
    s = sablon or DEFAULT_G.get("hosgeldin_metin") or "Hos geldin {ad}"
    s = s.replace("{ad}", ad_esc).replace("{name}", ad_esc).replace("{Name}", ad_esc)
    s = s.replace("{KullanıcıAdı}", ad_esc).replace("{KullaniciAdi}", ad_esc)
    # **kalin** -> <b>
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__([^_]+)__", r"<b>\1</b>", s)
    return s



# Ayni uye 30sn icinde 2 kez karsilanmasin (Message + ChatMember cift tetik)
_join_lock = {}


async def yeni_uye_karsila(bot, chat, u, context=None):
    """Mute + hosgeldin mesaji. hosgeldin() ve uye_guncelle() ortak."""
    if not chat or not u or getattr(u, "is_bot", False):
        return
    key = (chat.id, u.id)
    now = time.time()
    son = _join_lock.get(key) or 0
    if now - son < 25:
        return
    _join_lock[key] = now
    # temizlik
    if len(_join_lock) > 500:
        for k in list(_join_lock.keys())[:200]:
            if now - _join_lock[k] > 120:
                _join_lock.pop(k, None)

    uye_kaydi(chat.id, u)

    # Mute
    mute_dk = int(cget(chat.id, "hosgeldin_mute") or 0)
    if cget(chat.id, "approval") or cget(chat.id, "captcha"):
        mute_dk = max(mute_dk, 60)
    if mute_dk > 0:
        try:
            until = datetime.now(timezone.utc) + timedelta(minutes=mute_dk)
            await bot.restrict_chat_member(
                chat.id, u.id, permissions=MUTE_PERMS, until_date=until
            )
            log.info("join mute OK %sdk uid=%s chat=%s", mute_dk, u.id, chat.id)
        except Exception as e:
            log.warning("join mute FAIL: %s", e)
            try:
                await bot.send_message(
                    SAHIP_ID,
                    f"⚠️ Mute basarisiz (chat {chat.id}, uid {u.id}):\n<code>{html.escape(str(e)[:200])}</code>\n"
                    "Botta \"kullanicilari kisitla\" yetkisi var mi?",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # Captcha
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
            gonder = await bot.send_message(chat.id, txt, parse_mode="HTML", reply_markup=kb)
            asyncio.create_task(sil_sonra(bot, chat.id, gonder.message_id, 120))
        except Exception as e:
            log.warning("captcha: %s", e)
        return

    # Hosgeldin mesaji
    if not (cget(chat.id, "hosgeldin") or cget(chat.id, "kural_onay") or cget(chat.id, "hg_test")):
        return
    ad_esc = html.escape(u.full_name or u.first_name or "üye")
    if cget(chat.id, "hg_test"):
        ver = "a" if (u.id % 2 == 0) else "b"
        sablon = cget(chat.id, f"hg_{ver}") or DEFAULT_G.get(f"hg_{ver}") or DEFAULT_G["hosgeldin_metin"]
        metin = hosgeldin_metin_hazirla(sablon, ad_esc)
    else:
        metin = hosgeldin_metin_hazirla(
            cget(chat.id, "hosgeldin_metin") or DEFAULT_G["hosgeldin_metin"],
            ad_esc,
        )
    kb = None
    if cget(chat.id, "kural_onay"):
        kur = html.escape(str(cget(chat.id, "kurallar") or DEFAULT_G.get("kurallar") or "")[:400])
        metin += f"\n\n📜 <b>Kurallar</b>\n{kur}\n\nYazmak için butona bas."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Kuralları kabul ediyorum", callback_data=f"ko:{chat.id}:{u.id}")
        ]])
    try:
        try:
            gonder = await bot.send_message(chat.id, metin, parse_mode="HTML", reply_markup=kb)
        except Exception:
            gonder = await bot.send_message(
                chat.id, re.sub(r"<[^>]+>", "", metin), reply_markup=kb
            )
        sil = int(cget(chat.id, "hosgeldin_sil") or 0)
        if sil > 0 and not cget(chat.id, "kural_onay"):
            asyncio.create_task(sil_sonra(bot, chat.id, gonder.message_id, sil))
        log.info("hosgeldin OK uid=%s chat=%s", u.id, chat.id)
    except Exception as e:
        log.warning("hosgeldin send: %s", e)
        try:
            await bot.send_message(
                SAHIP_ID,
                f"⚠️ Hosgeldin mesaji gitmedi (chat {chat.id}):\n<code>{html.escape(str(e)[:200])}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def hosgeldin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, chat = update.effective_message, update.effective_chat
    if not msg or not chat or not msg.new_chat_members:
        return
    # bot kendisi eklendiyse yetki kontrol
    for u in msg.new_chat_members:
        if u.is_bot and u.id == context.bot.id:
            await yetki_kontrol(context.bot, chat.id, bildir=True)
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
        # global fed / kara liste
        if ozellik_acik(chat.id, "fed_ban") and fed_banli_mi(u.id):
            try:
                await context.bot.ban_chat_member(chat.id, u.id)
                await log_gonder(context.bot, chat.id, f"🌐 Kara listeden ban: {html.escape(u.full_name or str(u.id))}")
            except Exception:
                pass
            continue
        # Fed ban (eski fed_id yapisi)
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
        # guven puani baslangic
        if ozellik_acik(chat.id, "guven"):
            if str(u.id) not in (cget(chat.id, "guven_puan") or {}):
                guven_set(chat.id, u.id, 40)  # yeni uye dusuk
        # davet takibi
        if ozellik_acik(chat.id, "davet") and msg.from_user and not msg.from_user.is_bot:
            inv = msg.from_user.id
            if inv != u.id:
                dmap = dict(cget(chat.id, "davetler") or {})
                dmap[str(inv)] = int(dmap.get(str(inv)) or 0) + 1
                cset(chat.id, "davetler", dmap)
                guven_ekle(chat.id, inv, 2)
        # kaynakli davet (invite link name)
        try:
            # telegram invite link uzerinden gelince from_user bot olabilir; kaynak ayri komutla isaretlenir
            pass
        except Exception:
            pass
        # admin taklidi (isim benzerligi)
        if ozellik_acik(chat.id, "admin_taklit"):
            try:
                admins = await context.bot.get_chat_administrators(chat.id)
                admin_names = []
                for a in admins:
                    if a.user.is_bot:
                        continue
                    admin_names.append(a.user.full_name or "")
                    if a.user.username:
                        admin_names.append(a.user.username)
                cset(chat.id, "admin_adlar", admin_names[:40])
                uad = u.full_name or ""
                uun = u.username or ""
                taklit = False
                for an in admin_names:
                    if _benzer_isim(uad, an) or (uun and _benzer_isim(uun, an)):
                        # kendisi admin degilse
                        if not any(a.user.id == u.id for a in admins):
                            taklit = True
                            break
                if taklit:
                    try:
                        await context.bot.ban_chat_member(chat.id, u.id)
                        await log_gonder(
                            context.bot, chat.id,
                            f"🚨 Admin taklidi şüphesi → ban: {html.escape(uad)} <code>{u.id}</code>",
                        )
                        await kisa_cevap(
                            context.bot, chat.id,
                            f"🚨 <b>Admin taklidi</b> şüphesi: {html.escape(uad)} engellendi.",
                            20,
                        )
                    except Exception as e:
                        log.warning("taklit ban: %s", e)
                    continue
            except Exception as e:
                log.warning("admin taklit: %s", e)
        # invite link kaynagi
        try:
            inv_name = ""
            if getattr(msg, "from_user", None) is None:
                pass
            # ChatMemberUpdated degil join message — invite_link field
            il = getattr(msg, "invite_link", None) or getattr(update, "invite_link", None)
            if il is None and hasattr(msg, "json"):
                pass
            # python-telegram-bot: Message.invite_link yok; ChatMemberHandler daha dogru
            # yedek: bot tarafindan olusturulmus link ismi src_twitter
        except Exception:
            pass
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
        try:
            await yeni_uye_karsila(context.bot, chat, u, context)
        except Exception as e:
            log.warning("hosgeldin karsila: %s", e)

        # istatistik giren
        st = dict(cget(chat.id, "istatistik") or {})
        st["giren"] = int(st.get("giren") or 0) + 1
        cset(chat.id, "istatistik", st)


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
    st = dict(cget(chat.id, "istatistik") or {})
    st["cikan"] = int(st.get("cikan") or 0) + 1
    cset(chat.id, "istatistik", st)
    # A/B hosgeldin: cikan say
    if cget(chat.id, "hg_test"):
        ver = (cget(chat.id, "hg_uye_versiyon") or {}).get(str(u.id))
        if ver in ("a", "b"):
            sc = dict(cget(chat.id, "hg_sayac") or {})
            sc[f"cikan_{ver}"] = int(sc.get(f"cikan_{ver}") or 0) + 1
            cset(chat.id, "hg_sayac", sc)
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


_REKLAM_KELIME = re.compile(
    r"(?i)(\bairdrop\b|\bfree\s*chicken\b|\bjoin\s+with\s+my\s+link\b|"
    r"\bget\s+my\s+free\b|\bclaim\s+now\b|\bref(eral)?\s*link\b|"
    r"\bwithdraw\s+to\s+your\b|\bmini\s*app\b|\btap\s+to\s+earn\b|"
    r"\bconnect\s+wallet\b|\bpresale\b|\bwhite\s*list\b)",
)


def mesajda_buton_var(msg) -> bool:
    rm = getattr(msg, "reply_markup", None)
    if not rm:
        return False
    rows = getattr(rm, "inline_keyboard", None) or []
    for row in rows:
        for btn in row:
            if getattr(btn, "url", None) or getattr(btn, "web_app", None):
                return True
            if getattr(btn, "login_url", None):
                return True
            # callback_data'li tanitim butonlari da engelle (reklam kartlari)
            if getattr(btn, "callback_data", None) or getattr(btn, "switch_inline_query", None):
                return True
    return bool(rows)



def mesaj_iletildi_mi(msg) -> bool:
    """Kullanicinin baska sohbetten ilettigi mesaj mi? (kanal otomatik baglanti haric)."""
    if not msg:
        return False
    if getattr(msg, "is_automatic_forward", False):
        return False  # bagli kanal — serbest
    if getattr(msg, "forward_date", None):
        return True
    if getattr(msg, "forward_from_chat", None):
        return True
    if getattr(msg, "forward_from", None):
        return True
    fo = getattr(msg, "forward_origin", None)
    if fo is not None:
        return True
    return False


def ilet_kaynak_bilgi(msg):
    """(chat_id veya None, username veya None, title)."""
    ch = getattr(msg, "forward_from_chat", None)
    if ch is not None:
        return (getattr(ch, "id", None), getattr(ch, "username", None), getattr(ch, "title", None) or "")
    fo = getattr(msg, "forward_origin", None)
    if fo is not None:
        # MessageOriginChannel / Chat
        chat = getattr(fo, "chat", None) or getattr(fo, "sender_chat", None)
        if chat is not None:
            return (getattr(chat, "id", None), getattr(chat, "username", None), getattr(chat, "title", None) or "")
        # MessageOriginUser — kisi iletimi
        sender = getattr(fo, "sender_user", None)
        if sender is not None:
            return (None, getattr(sender, "username", None), getattr(sender, "full_name", None) or getattr(sender, "first_name", "") or "")
    return (None, None, "")


def ilet_izinli_mi(chat_id, msg) -> bool:
    """forward_izin listesinde kaynak var mi?"""
    izin = [str(x).lower().lstrip("@") for x in (cget(chat_id, "forward_izin") or []) if x]
    if not izin:
        return False
    kid, uname, title = ilet_kaynak_bilgi(msg)
    if kid is not None and str(kid) in izin:
        return True
    if uname and uname.lower() in izin:
        return True
    # t.me/xxx yazilmissa
    if uname and any(uname.lower() in z or z.endswith("/" + uname.lower()) for z in izin):
        return True
    return False


def mesajda_link_var(msg, metin: str) -> bool:
    """Metin, entity, inline buton, via_bot, reklam kalibi."""
    if metin and LINK_RE.search(metin):
        return True
    if metin and _REKLAM_KELIME.search(metin):
        return True
    for ent in list(getattr(msg, "entities", None) or []) + list(getattr(msg, "caption_entities", None) or []):
        t = getattr(ent, "type", None)
        if t in ("url", "text_link", "mention"):
            # mention tek basina engellenmesin; sadece text_link/url
            if t in ("url", "text_link"):
                return True
    if mesajda_buton_var(msg):
        return True
    if getattr(msg, "via_bot", None):
        return True
    if getattr(msg, "forward_origin", None) or getattr(msg, "forward_from_chat", None):
        if metin and (LINK_RE.search(metin) or _REKLAM_KELIME.search(metin)):
            return True
        if mesajda_buton_var(msg):
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
    # adim adim sihirbazlar
    try:
        if await wizard_devam(update, context):
            return
    except Exception as e:
        log.warning("wizard: %s", e)

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
        # bakim ac/kapat + gruba mesaj (sadece sahip ozel)
        low0 = kucult(metin or "")
        if low0 in ("bakım aç", "bakim ac", "bakımda", "bakimda") or low0.startswith("bakım aç") or low0.startswith("bakim ac"):
            duyuru = "🔧 <b>Bakımdayım</b>\nKısa süre işlem yapamayabilirim. Bitince yazacağım."
            # ozel metin: "bakim ac mesajiniz"
            for prefix in ("bakım aç", "bakim ac", "bakımda", "bakimda"):
                if low0.startswith(prefix) and len(metin) > len(prefix) + 1:
                    duyuru = metin[len(prefix):].strip() or duyuru
                    break
            ok_n, fail_n = 0, 0
            for gid in list((durum.get("grup") or {}).keys()):
                try:
                    gid_i = int(gid)
                    cset(gid_i, "bakim", True)
                    await context.bot.send_message(gid_i, duyuru, parse_mode="HTML")
                    ok_n += 1
                except Exception:
                    fail_n += 1
            await msg.reply_text(f"🔧 Bakım AÇIK · gruba giden: {ok_n}" + (f" · hata: {fail_n}" if fail_n else ""))
            return
        if low0 in ("bakım kapat", "bakim kapat", "bakım bitti", "bakim bitti"):
            ok_n = 0
            for gid in list((durum.get("grup") or {}).keys()):
                try:
                    gid_i = int(gid)
                    cset(gid_i, "bakim", False)
                    await context.bot.send_message(gid_i, "✅ Bakım bitti, normal çalışıyorum.")
                    ok_n += 1
                except Exception:
                    pass
            await msg.reply_text(f"✅ Bakım kapandı · gruba bilgi: {ok_n}")
            return
        # gruba gonder / send  (sadece sahip, ozel sohbet)
        gonder_met = None
        for prefix in ("gruba gönder", "gruba gonder", "gruba yaz", "/send", "send "):
            if low0.startswith(prefix.strip().lower()) or (metin or "").lower().startswith(prefix):
                gonder_met = (metin or "")[len(prefix):].strip()
                break
        if gonder_met is None and (metin or "").startswith("/send"):
            gonder_met = (metin or "")[5:].strip()
        if gonder_met is not None:
            if not gonder_met:
                await msg.reply_text("Kullanım:\n<code>gruba gönder Bakımdayız</code>\n<code>/send Bakımdayız</code>", parse_mode="HTML")
                return
            ok_n, fail_n = 0, 0
            for gid in list((durum.get("grup") or {}).keys()):
                try:
                    await context.bot.send_message(int(gid), gonder_met)
                    ok_n += 1
                except Exception:
                    fail_n += 1
            await msg.reply_text(f"📢 Gönderildi: {ok_n} grup" + (f" · hata: {fail_n}" if fail_n else ""))
            return
        # link engel ac/kapat (aktif grup veya tum gruplar)
        if low0 in ("link engel aç", "link engel ac", "link aç", "link ac", "reklam kapat", "link yasak"):
            hedefler = []
            ag = _aktif_grup_id()
            if ag:
                hedefler = [ag]
            else:
                hedefler = [int(x) for x in (durum.get("grup") or {}).keys()]
            for gid in hedefler:
                cset(gid, "link_engel", True)
            await msg.reply_text(
                f"🔗 Link/buton engeli <b>AÇIK</b> ({len(hedefler)} grup)\n"
                f"Üye link, t.me, url buton, webapp paylaşamaz.\n"
                f"İzinli domain: <code>/izinlink t.me/senin</code>",
                parse_mode="HTML",
            )
            return
        if low0 in ("link engel kapat", "link kapat", "reklam aç", "reklam ac", "link serbest"):
            hedefler = []
            ag = _aktif_grup_id()
            if ag:
                hedefler = [ag]
            else:
                hedefler = [int(x) for x in (durum.get("grup") or {}).keys()]
            for gid in hedefler:
                cset(gid, "link_engel", False)
            await msg.reply_text(f"🔗 Link engeli <b>KAPALI</b> — üyeler link paylaşabilir ({len(hedefler)} grup).", parse_mode="HTML")
            return

        
        if low0 in ("airdrop yorum ac", "airdrop yorum aç", "airdrop analiz ac", "airdrop analiz aç"):
            ag = _aktif_grup_id()
            hedefler = [ag] if ag else [int(x) for x in (durum.get("grup") or {}).keys()]
            for gid in hedefler:
                cset(gid, "airdrop_yorum", True)
            await msg.reply_text("✅ Airdrop yorumu AÇIK (%s grup)." % len(hedefler))
            return
        if low0 in ("airdrop yorum kapat", "airdrop analiz kapat"):
            ag = _aktif_grup_id()
            hedefler = [ag] if ag else [int(x) for x in (durum.get("grup") or {}).keys()]
            for gid in hedefler:
                cset(gid, "airdrop_yorum", False)
            await msg.reply_text("✅ Airdrop yorumu KAPALI.")
            return
        if low0 in ("ilet engel ac", "ilet engel aç", "forward engel ac", "forward engel aç", "ileti yasak", "forward yasak"):
            hedefler = []
            ag = _aktif_grup_id()
            hedefler = [ag] if ag else [int(x) for x in (durum.get("grup") or {}).keys()]
            for gid in hedefler:
                cset(gid, "forward_engel", True)
            await msg.reply_text("↪️ Ilet engeli <b>AÇIK</b> — baska gruptan iletim silinir (%s grup)." % len(hedefler), parse_mode="HTML")
            return
        if low0 in ("ilet engel kapat", "forward engel kapat", "ileti serbest", "forward serbest"):
            hedefler = []
            ag = _aktif_grup_id()
            hedefler = [ag] if ag else [int(x) for x in (durum.get("grup") or {}).keys()]
            for gid in hedefler:
                cset(gid, "forward_engel", False)
            await msg.reply_text("↪️ Ilet engeli <b>KAPALI</b> (%s grup)." % len(hedefler), parse_mode="HTML")
            return
    else:
        # grubu her zaman kaydet
        try:
            gconf = (durum.setdefault("grup", {})).setdefault(str(cid), {})
            if chat.title and not gconf.get("title"):
                gconf["title"] = chat.title
                durum_kaydet()
        except Exception:
            pass

        # kanal postu / otomatik forward — filtre yok
        # airdrop yorumu SADECE kanal_duyuru_yakala'dan (listeye yorum yok)
        if getattr(msg, "sender_chat", None) is not None or getattr(msg, "is_automatic_forward", False):
            pass
        # LINK/REKLAM FILTRESI — bakim ve sahip kontrolunden ONCE (t.me/ChickenLandBot vb.)
        if not sahip_mi(user) and not getattr(msg, "sender_chat", None) and not getattr(msg, "is_automatic_forward", False):
            is_adm_erken = await admin_mi(cid, user, context.bot)
            # link silme link_filtre_oncelik (-5) yaptı; burada sadece boost isaretle
            if mesajda_link_var(msg, metin) and boost_link_hakki_var(cid, user.id):
                try:
                    _LINK_GECTI.add((cid, msg.message_id))
                except Exception:
                    pass

        # grup: sadece sahip bu grubun uyesi/yoneticisiyse AI/komut
        if not await sahip_grupta_mi(context.bot, cid):
            return
        # bakim modu — AI susar ama spam filtresi yukarda calisti
        if cget(cid, "bakim") and not sahip_mi(user):
            if metin and (yapay_geciyor(metin) or ozel):
                try:
                    await msg.reply_text(cget(cid, "bakim_metin") or "🔧 Bakımdayım, birazdan dönerim.")
                except Exception:
                    pass
            return

    if not ozel:
        # admin degilse filtreler
        is_adm = await admin_mi(cid, user, context.bot)
        if getattr(msg, "sender_chat", None) is not None or getattr(msg, "is_automatic_forward", False):
            is_adm = True
        boostlu = False
        try:
            boostlu = (not is_adm) and boost_link_hakki_var(cid, user.id)
        except Exception:
            boostlu = False
        # link engel sadece erken filtrede (boost hakki orada)
        if not is_adm:
            # BOOSTLU: otomatik silme yok (sadece seed/kritik asagida ayri)
            if boostlu:
                pass  # sessizlik/gece/flood/medya/link asagida atlanacak
            # sessizlik
            if cget(cid, "sessizlik") and not boostlu:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return
            # gece modu 00-07 TR
            if cget(cid, "gece") and not boostlu:
                saat = datetime.now(TR).hour
                bas = int(cget(cid, "gece_bas") or 0)
                bit = int(cget(cid, "gece_bit") or 7)
                if bas <= saat < bit or (bas > bit and (saat >= bas or saat < bit)):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return
            # flood (adam asmaca harfi sayilmasin)
            oy_aktif = False
            try:
                _oy = _oyun_adam.get(str(cid)) or {}
                oy_aktif = _oy.get("durum") == "oyna" and metin and len(metin.strip()) <= 12
            except Exception:
                pass
            if cget(cid, "flood") and not oy_aktif and not boostlu:
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
            # medya engel (boostlu + linkli kart silinmesin)
            if cget(cid, "medya_engel") and not boostlu:
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
            # typosquat / sahte site (boostlu serbest)
            if metin and _SAHTE_RE.search(metin) and not boostlu:
                if cget(cid, "golge"):
                    await log_gonder(context.bot, cid, f"👤 Gölge: sahte domain yakalandı (silinmedi)\n{html.escape(metin[:120])}")
                else:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    try:
                        await kisa_cevap(context.bot, cid, f"🎣 {_ad(user)} sahte/şüpheli site linki silindi.", 10)
                    except Exception:
                        pass
                    return
            # link engel erken filtrede islendi
            # link guvenlik tarama
            if ozellik_acik(cid, "link_tara") and metin and not boostlu:
                for url in linkleri_cikar(metin, msg):
                    guven, neden = link_guvenli_mi(url)
                    if not guven:
                        try:
                            await msg.delete()
                        except Exception:
                            pass
                        try:
                            await kisa_cevap(
                                context.bot, cid,
                                f"🛡 Zararlı link silindi ({html.escape(neden)})",
                                10,
                            )
                        except Exception:
                            pass
                        guven_ekle(cid, user.id, -15)
                        return
            # dusuk guven + link = ekstra sikı
            if ozellik_acik(cid, "guven") and guven_get(cid, user.id) < 25:
                if mesajda_link_var(msg, metin) and (cid, msg.message_id) not in _LINK_GECTI:
                    if not boost_link_hakki_var(cid, user.id) and not link_uye_izinli(cid, user.id, metin, kullan_hak=False):
                        try:
                            await msg.delete()
                        except Exception:
                            pass
                        return
            # blocklist + otomatik kufur
            if metin:
                low_m = metin.lower()
                bl = list(cget(cid, "blocklist") or [])
                yasak = set(x.lower() for x in bl if x) | set(DEFAULT_KUFUR)
                # ogrenme: sik gecen kufur-benzeri kelimeleri ekle
                if cget(cid, "kufur_otomatik") is not False:
                    for ham in re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ]{3,16}", low_m):
                        if ham in yasak or any(k in ham for k in DEFAULT_KUFUR if len(k) >= 3):
                            _kufur_sayac[str(cid)][ham] += 1
                            if _kufur_sayac[str(cid)][ham] >= 3 and ham not in bl:
                                bl.append(ham)
                                cset(cid, "blocklist", bl[-80:])
                                yasak.add(ham)
                                log.info("kufur ogrenildi grup=%s kelime=%s", cid, ham)
                # kripto argosu — haksız filtre olmasın
                if any(a in low_m for a in _KRIPTO_ARGO):
                    pass  # argo tek basina silinmez
                # akilli kufur: yumusak baglamda (kardesim, saka) tek basina "salak" silme
                yumusak = any(x in low_m for x in ("kardeşim", "kardesim", "şaka", "saka", "espiri", "lafı", "lafi"))
                yumusak = yumusak or any(a in low_m for a in ("rekt", "ape", "moon", "gem", "ngmi", "wagmi"))
                agir = any(w in low_m for w in DEFAULT_KUFUR if len(w) >= 4)
                if agir or (any(w and w in low_m for w in yasak) and not yumusak):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    st = dict(cget(cid, "istatistik") or {})
                    st["spam"] = int(st.get("spam") or 0) + 1
                    cset(cid, "istatistik", st)
                    guven_ekle(cid, user.id, -5)
                    return
            # mesaj uzunlugu
            mx = int(cget(cid, "mesaj_max") or 0)
            if mx > 0 and metin and len(metin) > mx:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

        _uy = uye_kaydi(cid, user)
        try:
            await kademe_tebrik(context.bot, cid, user, _uy)
        except Exception:
            pass
        # mesaj arsivi (arama icin)
        if metin and len(metin) < 500:
            _mesaj_arsiv[cid].append({
                "ts": time.time(),
                "uid": user.id,
                "ad": (user.first_name or "")[:20],
                "text": metin[:300],
            })
        # ogrenilen spam (boostlu degil)
        if metin and _spam_benzer(cid, metin) and not boostlu:
            try:
                await msg.delete()
            except Exception:
                pass
            st = dict(cget(cid, "istatistik") or {})
            st["spam"] = int(st.get("spam") or 0) + 1
            cset(cid, "istatistik", st)
            return
        # yabanci dil spam
        if (not boostlu) and cget(cid, "yabanci_spam") is not False and metin and _yabanci_spam_mi(metin):
            if guven_get(cid, user.id) < 70:
                try:
                    await msg.delete()
                except Exception:
                    pass
                st = dict(cget(cid, "istatistik") or {})
                st["spam"] = int(st.get("spam") or 0) + 1
                cset(cid, "istatistik", st)
                return
        # istatistik + sessizlik
        st = dict(cget(cid, "istatistik") or {})
        st["mesaj"] = int(st.get("mesaj") or 0) + 1
        cset(cid, "istatistik", st)
        _son_grup_mesaj[cid] = time.time()
        durum.setdefault("grup", {}).setdefault(str(cid), {})["son_mesaj_ts"] = time.time()
        # otomatik yavas mod
        if cget(cid, "yavas_mod_otomatik"):
            mh = _mesaj_hiz[cid]
            now = time.time()
            while mh and now - mh[0] > 10:
                mh.popleft()
            mh.append(now)
            if len(mh) >= 25:
                try:
                    await context.bot.set_chat_slow_mode_delay(cid, 10)
                    await kisa_cevap(context.bot, cid, "🐢 Yoğunluk: yavaş mod 10sn açıldı.", 12)
                    mh.clear()
                except Exception:
                    pass

    if not metin:
        return

    # kisisel veri maskeleme (IBAN, e-posta, telefon)
    if not ozel and metin:
        try:
            is_adm_chk = await admin_mi(cid, user, context.bot)
        except Exception:
            is_adm_chk = False
        if not is_adm_chk:
            lowk = kucult(metin)
            for rx in _KISISEL_RE:
                if not rx.search(metin):
                    continue
                if "\\d{11}" in rx.pattern and "tc" not in lowk and "kimlik" not in lowk:
                    continue
                try:
                    await msg.delete()
                except Exception:
                    pass
                try:
                    await kisa_cevap(
                        context.bot, cid,
                        f"🔒 {_ad(user)} kişisel bilgi paylaşımı silindi.",
                        12,
                    )
                except Exception:
                    pass
                return

    # seed phrase korumasi — herkese
    if not ozel and metin and _SEED_RE.search(metin) and len(metin.split()) >= 12:
        # cok sayida ingilizce kisa kelime = seed adayi
        kelimeler = re.findall(r"[a-zA-Z]{3,8}", metin.lower())
        if len(kelimeler) >= 12:
            try:
                await msg.delete()
            except Exception:
                pass
            try:
                await kisa_cevap(
                    context.bot, cid,
                    f"🚨 {_ad(user)} seed/private key paylaşımı silindi. Asla paylaşma!",
                    15,
                )
            except Exception:
                pass
            guven_ekle(cid, user.id, -20)
            return

    # ILET / FORWARD engeli — baska gruptan iletilen icerik
    if not ozel and cget(cid, "forward_engel") and mesaj_iletildi_mi(msg):
        is_adm_f = False
        try:
            is_adm_f = await admin_mi(cid, user, context.bot) or sahip_mi(user)
        except Exception:
            pass
        if not is_adm_f and not ilet_izinli_mi(cid, msg):
            try:
                await msg.delete()
                log.info("ilet silindi chat=%s user=%s", cid, user.id)
            except Exception:
                pass
            return

    # kural onayi zorunlu
    if not ozel and cget(cid, "kural_onay"):
        onayli = [str(x) for x in (cget(cid, "kural_onayli") or [])]
        is_adm = await admin_mi(cid, user, context.bot)
        if not is_adm and str(user.id) not in onayli:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # FUD / panik tespiti
    if not ozel and metin:
        low_f = kucult(metin)
        if any(k in low_f for k in _FUD_KELIME):
            fb = _fud_buf[cid]
            now = time.time()
            while fb and now - fb[0] > 120:
                fb.popleft()
            fb.append(now)
            if len(fb) >= 5:
                fb.clear()
                try:
                    await context.bot.send_message(
                        SAHIP_ID,
                        f"⚠️ <b>FUD/Panik</b> grubunda yoğunlaştı\nChat: <code>{cid}</code>\nÖrnek: {html.escape(metin[:120])}",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                await log_gonder(context.bot, cid, "⚠️ FUD yoğunluğu — sahip bilgilendirildi")

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
        # destek bileti (uye DM — sahip degilse asagida)
    # destek: ozelde normal kullanici (kilit kapali degilse — bizde kilit var)
    if ozel and not sahip_mi(user) and metin and not metin.startswith("/"):
        # kilit nedeniyle genelde buraya gelmez; sahip disi engelli
        pass

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

    # yapay ceza / susturalim oylamasi
    if not ozel and metin:
        low_c = kucult(metin)
        if (yapay_geciyor(metin) and "ceza" in low_c) or "susturalım" in low_c or "susturalim" in low_c or "mute oyla" in low_c:
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
        # konusma devam: yapay dedikten sonra N sn isim yazmadan devam
        ck = (cid, user.id)
        if ck in _konusma_aktif and time.time() < _konusma_aktif[ck]:
            cagrildi = True
        if cget(cid, "privacy_ai"):
            cagrildi = bool(reply_bot or mention_bot or cagrildi)
        else:
            if yapay_geciyor(metin) or reply_bot or mention_bot:
                cagrildi = True
        if cagrildi and (yapay_geciyor(metin) or reply_bot or mention_bot):
            sn = int(cget(cid, "konusma_sn") or 90)
            _konusma_aktif[ck] = time.time() + max(30, min(sn, 300))

    # Adam asmaca (yapay yazmadan da)
    if not ozel and ("adam asmaca" in low or "adamasmaca" in low.replace(" ", "")):
        asyncio.create_task(_adam_bekle(context.bot, cid, baslatan_id=user.id))
        return

    # --- adam asmaca tahmini ---
    if not ozel and str(cid) in _oyun_adam:
        oy = _oyun_adam.get(str(cid)) or {}
        if oy.get("durum") == "oyna":
            t0 = (metin or "").strip()
            if user.id in (oy.get("oyuncular") or set()) and t0 and (
                (len(t0) == 1 and t0.isalpha())
                or (len(t0) > 1 and t0.isalpha())
            ):
                await _adam_harf(update, context, t0.lower())
                return

    # Fiyat: niyet veya top-300
    fiyat_ok = False
    adaylar = [metin]
    if yapay_geciyor(metin):
        adaylar.append(_re_sub_yapay(metin))
    for aday in adaylar:
        if not aday:
            continue
        kt = kisa_token(aday)
        if kt:
            miktar, sembol = kt[0], kt[1]
            niyetli = kt[2] if len(kt) > 2 else False
            if await fiyat_gonder(update, miktar, sembol, niyetli=niyetli):
                fiyat_ok = True
                break
    if fiyat_ok:
        return

    # gizli kelime — yapay demeden de yakala
    if not ozel and metin:
        gk = cget(cid, "gizli_kelime")
        if isinstance(gk, dict) and gk.get("kelime") and kucult(metin.strip()) == kucult(gk["kelime"]):
            cset(cid, "gizli_kelime", None)
            guven_ekle(cid, user.id, 5)
            try:
                await msg.reply_text(
                    f"🎉 <b>{html.escape(user.first_name or 'Üye')}</b> gizli kelimeyi buldu!",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

    # bot sus modu
    sus_bit = float(cget(cid, "sus_bitis") or 0)
    if not ozel and sus_bit > time.time() and not sahip_mi(user):
        # admin sus acabilir/kapatabilir asagida
        if not (await admin_mi(cid, user, context.bot) and ("sus" in kucult(metin) or "konus" in kucult(metin))):
            if cagrildi:
                return  # sessiz — cevap yok

    if not cagrildi:
        return

    # kullanici basi spam limiti
    if not _ai_limit_ok(user.id):
        try:
            await msg.reply_text("⏳ Çok hızlı yazıyorsun, biraz bekle.")
        except Exception:
            pass
        return

    soru = re.sub(r"(?i)\byapay\b", "", metin).strip() or metin

    # Kanal duyuru ara: "yapay folk duyuru" / "yapay neopod"
    try:
        if cagrildi and not ozel and (duyuru_posts := (cget(cid, "duyuru_posts") or [])):
            low_s = kucult(soru or metin or "")
            iste_duyuru = any(
                x in low_s
                for x in (
                    "duyuru", "airdrop", "kampanya", "etkinlik", "kayit", "kayıt",
                    "link var", "nedir", "ne o", "ne bu",
                )
            )
            # veya havuzda eslesen kelime
            eslesen = duyuru_ara(cid, soru or metin or "", limit=1)
            if iste_duyuru or eslesen:
                if eslesen or iste_duyuru:
                    ok = await duyuru_sorgu_cevap(
                        context.bot, cid, soru or metin or "", msg.message_id
                    )
                    if ok:
                        return
    except Exception as e:
        log.warning("duyuru ara hook: %s", e)

    ad = (user.first_name or user.full_name or "dostum").split()[0]

    # hatirlatici: "yarin 17:00 hatirlat X" / "5 dakika sonra hatirlat X"
    hat = _hatirlat_ayikla(soru, cid, user.id)
    if hat:
        _hatirlat_q.append(hat)
        try:
            await msg.reply_text(
                f"⏰ Tamam, {html.escape(hat['goster'])} hatırlatacağım.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # gündem/haber — RSS basliklari (model süslemesin)
    low_soru = kucult(soru)
    if any(x in low_soru for x in ("gündem", "gundem", "son dakika", "haber", "bugün ne oldu", "bugun ne oldu", "gündemde ne", "gundemde ne", "kripto haber")):
        try:
            await context.bot.send_chat_action(cid, "typing")
        except Exception:
            pass
        try:
            ham = await asyncio.to_thread(web_arama, "crypto news today", 8)
        except Exception as e:
            log.warning("gundem web: %s", e)
            ham = ""
        # Sadece • ile baslayan basliklari al
        basliklar = [ln.strip() for ln in (ham or "").splitlines() if ln.strip().startswith("•")]
        if not basliklar:
            basliklar = [ln.strip() for ln in (ham or "").splitlines() if len(ln.strip()) > 30][:6]
        if not basliklar:
            try:
                await msg.reply_text("🔆 Şu an haber başlığı çekemedim, biraz sonra tekrar dene.")
            except Exception:
                pass
            return
        # Model sadece sirala/kisalt — yeni olay uydurma
        ozet = sor(
            [{"role": "user", "content":
              "Asagidaki basliklari Turkce 4-6 madde yap. "
              "YENI DETAY EKLEME. Rakam/hack uydurma. Baslikta yoksa yazma.\n\n"
              + "\n".join(basliklar[:8])}],
            ek="Sadece verilen basliklari ozetle. Uydurma yasak.",
            zor=False,
            soru_metin=soru,
        )
        if not ozet or len(ozet) < 20:
            met = "📰 <b>Kısa gündem</b>\n" + "\n".join(html.escape(b) for b in basliklar[:6])
        else:
            met = "📰 <b>Kısa gündem</b>\n" + html.escape(ozet)
        try:
            await msg.reply_text(met, parse_mode="HTML")
        except Exception:
            await msg.reply_text("📰 Gündem\n" + (ozet or "\n".join(basliklar[:6])))
        return

        # kriz / etkinlik
    if kucult(soru) in ("kriz aç", "kriz ac", "alarm aç", "alarm ac") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        ok = await kriz_ac(cid)
        try:
            await context.bot.set_chat_slow_mode_delay(cid, 10)
        except Exception:
            pass
        await msg.reply_text("🚨 <b>Kriz modu AÇIK</b>\nLink yasak · yavaş mod · yeni üye mute 30dk", parse_mode="HTML" if ok else None)
        return
    if kucult(soru) in ("kriz kapat", "kriz bitir", "alarm kapat") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        await kriz_kapat(cid, context.bot)
        await msg.reply_text("✅ Kriz modu kapandı, eski ayarlar geri yüklendi.")
        return
    if kucult(soru) in ("etkinlik aç", "etkinlik ac", "ama mod", "lansman mod") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        await etkinlik_ac(cid)
        await msg.reply_text("🎤 <b>Etkinlik modu</b> açık (sıkı kurallar). Bitince: <code>yapay etkinlik kapat</code>", parse_mode="HTML")
        return
    if kucult(soru) in ("etkinlik kapat", "etkinlik bitir") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        await etkinlik_kapat(cid)
        await msg.reply_text("✅ Etkinlik modu kapandı.")
        return

    # kisilik (canli, DB)
    if kucult(soru).startswith("kişilik ") or kucult(soru).startswith("kisilik "):
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            k = re.sub(r"(?i)^(kişilik|kisilik)\s*", "", soru).strip()
            cset(cid, "kisilik", k[:300])
            await msg.reply_text(f"✅ Kişilik güncellendi:\n<i>{html.escape(k[:200])}</i>", parse_mode="HTML")
            return

    # sozluk
    if kucult(soru).startswith("sözlük ekle ") or kucult(soru).startswith("sozluk ekle "):
        if await admin_mi(cid, user, context.bot) or sahip_mi(user) or moderator_mi(cid, user):
            par = re.sub(r"(?i)^(sözlük|sozluk)\s*ekle\s*", "", soru).strip()
            if "=" in par:
                kel, acik = par.split("=", 1)
            elif ":" in par:
                kel, acik = par.split(":", 1)
            else:
                parts = par.split(None, 1)
                kel, acik = (parts[0], parts[1]) if len(parts) > 1 else (par, "")
            if kel and acik:
                sz = dict(cget(cid, "sozluk") or {})
                sz[kel.strip().lower()] = acik.strip()[:200]
                cset(cid, "sozluk", sz)
                await msg.reply_text(f"✅ Sözlük: <b>{html.escape(kel.strip())}</b>", parse_mode="HTML")
                return
    if kucult(soru).startswith("bu ne demek") or kucult(soru).startswith("ne demek "):
        kel = re.sub(r"(?i)^(bu\s+)?ne demek\s*", "", soru).strip().lower()
        sz = cget(cid, "sozluk") or {}
        if kel in sz:
            await msg.reply_text(f"📖 <b>{html.escape(kel)}</b>: {html.escape(sz[kel])}", parse_mode="HTML")
            return
        for k, v in sz.items():
            if k in kel or kel in k:
                await msg.reply_text(f"📖 <b>{html.escape(k)}</b>: {html.escape(v)}", parse_mode="HTML")
                return

    # saat dilimi
    if kucult(soru).startswith("saat dilimi ") or kucult(soru).startswith("timezone "):
        tz = soru.split(None, 2)[-1].strip() if len(soru.split()) >= 3 else soru.split(None, 1)[-1]
        sd = dict(cget(cid, "saat_dilimi") or {})
        sd[str(user.id)] = tz[:40]
        cset(cid, "saat_dilimi", sd)
        await msg.reply_text(f"🌍 Saat dilimin: <code>{html.escape(tz[:40])}</code>", parse_mode="HTML")
        return

    # hg test sonuc
    if kucult(soru) in ("hg test sonuç", "hg test sonuc", "karşılama test") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        sc = cget(cid, "hg_sayac") or {}
        a, b = int(sc.get("a") or 0), int(sc.get("b") or 0)
        ca, cb = int(sc.get("cikan_a") or 0), int(sc.get("cikan_b") or 0)
        oran_a = (ca / a * 100) if a else 0
        oran_b = (cb / b * 100) if b else 0
        await msg.reply_text(
            f"🧪 <b>Karşılama A/B</b>\n"
            f"A: {a} giriş · {ca} çıkış (%{oran_a:.0f})\n"
            f"B: {b} giriş · {cb} çıkış (%{oran_b:.0f})\n"
            f"{'A daha iyi' if oran_a < oran_b else 'B daha iyi' if oran_b < oran_a else 'Berabere'}",
            parse_mode="HTML",
        )
        return
    if kucult(soru) in ("hg test aç", "hg test ac") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        cset(cid, "hg_test", True)
        await msg.reply_text("🧪 Karşılama A/B testi açıldı.")
        return
    if kucult(soru) in ("hg test kapat",) and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        cset(cid, "hg_test", False)
        await msg.reply_text("A/B test kapandı.")
        return

    # sus / konus
    msus = re.search(r"(?i)\b(\d+)\s*(saat|dk|dakika|min)?\s*sus\b", soru) or (
        kucult(soru) in ("sus", "sessiz ol", "biraz sus") and True
    )
    if msus and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        if msus is True:
            sn = 3600
            goster = "1 saat"
        else:
            n = int(msus.group(1))
            birim = (msus.group(2) or "saat").lower()
            if birim in ("dk", "dakika", "min"):
                sn = n * 60
                goster = f"{n} dk"
            else:
                sn = n * 3600
                goster = f"{n} saat"
        cset(cid, "sus_bitis", time.time() + min(sn, 86400))
        await msg.reply_text(f"🤫 Tamam, {goster} susuyorum.")
        return
    if kucult(soru) in ("konuş", "konus", "susma", "konuşabilirsin", "konusabilirsin") and (
        await admin_mi(cid, user, context.bot) or sahip_mi(user)
    ):
        cset(cid, "sus_bitis", 0)
        await msg.reply_text("🔊 Konuşuyorum yine.")
        return

    # quiz duellosu
    if kucult(soru).startswith("düello") or kucult(soru).startswith("duello") or kucult(soru).startswith("quiz düello"):
        if msg.reply_to_message and msg.reply_to_message.from_user:
            rakip = msg.reply_to_message.from_user
            import random
            sorular = [
                ("Bitcoin'in sembolü?", "btc"),
                ("Ethereum gas birimi?", "gwei"),
                ("Seed phrase kaç kelime olur genelde?", "12"),
                ("DeFi açılımı?", "decentralized finance"),
                ("NFT açılımı?", "non fungible token"),
            ]
            s, cevap = random.choice(sorular)
            _quiz_duello[str(cid)] = {
                "soru": s, "cevap": cevap.lower(),
                "a": user.id, "b": rakip.id,
                "ad_a": user.first_name, "ad_b": rakip.first_name,
                "bitis": time.time() + 60,
            }
            await msg.reply_text(
                f"⚔️ <b>Quiz düellosu</b>\n"
                f"{html.escape(user.first_name or '')} vs {html.escape(rakip.first_name or '')}\n\n"
                f"❓ {html.escape(s)}\n60 sn — ilk doğru yazan kazanır!",
                parse_mode="HTML",
            )
            return
        await msg.reply_text("Birine yanıtla: <code>yapay düello</code>", parse_mode="HTML")
        return
    qd = _quiz_duello.get(str(cid))
    if qd and time.time() < float(qd.get("bitis") or 0):
        if user.id in (qd.get("a"), qd.get("b")) and qd["cevap"] in kucult(soru):
            _quiz_duello.pop(str(cid), None)
            guven_ekle(cid, user.id, 3)
            await msg.reply_text(f"🏆 {html.escape(user.first_name or 'Üye')} kazandı!", parse_mode="HTML")
            return

    # bagis
    if kucult(soru) in ("bağış", "bagis", "donate", "destek", "donation"):
        met = cget(cid, "bagis_metin") or durum.get("bagis_metin") or ""
        if not met:
            await msg.reply_text("Bağış bilgisi henüz ayarlanmadı. Admin: <code>yapay bagis ayarla ADRES</code>", parse_mode="HTML")
            return
        await msg.reply_text(f"💚 <b>Destek / Bağış</b>\n{html.escape(met)}", parse_mode="HTML")
        return
    if kucult(soru).startswith("bagis ayarla") or kucult(soru).startswith("bağış ayarla"):
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            met = re.sub(r"(?i)(yapay\s*)?(bağış|bagis)\s*ayarla\s*", "", soru).strip()
            cset(cid, "bagis_metin", met)
            await msg.reply_text("✅ Bağış metni kaydedildi.")
            return

    # gizli kelime avi
    gk = cget(cid, "gizli_kelime")
    if isinstance(gk, dict) and gk.get("kelime"):
        if kucult(soru) == kucult(gk["kelime"]) or kucult(gk["kelime"]) == kucult(metin):
            cset(cid, "gizli_kelime", None)
            guven_ekle(cid, user.id, 5)
            await msg.reply_text(
                f"🎉 <b>{html.escape(user.first_name or 'Üye')}</b> gizli kelimeyi buldu!\n"
                f"Kelime: <code>{html.escape(gk['kelime'])}</code>",
                parse_mode="HTML",
            )
            return
    if kucult(soru).startswith("gizli kelime ") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        kel = soru.split(None, 2)[-1].strip() if len(soru.split()) >= 3 else ""
        if kel:
            cset(cid, "gizli_kelime", {"kelime": kel, "by": user.id})
            await msg.reply_text("🕵️ Gizli kelime konuldu. İlk yazan kazanır!")
            return

    # golge / ceza tavan
    if kucult(soru) in ("gölge aç", "golge ac", "shadow on") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        cset(cid, "golge", True)
        await msg.reply_text("👤 Gölge mod AÇIK — cezalar sadece loglanır.")
        return
    if kucult(soru) in ("gölge kapat", "golge kapat", "shadow off") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        cset(cid, "golge", False)
        await msg.reply_text("✅ Gölge mod kapandı — cezalar gerçek.")
        return
    m_tavan = re.search(r"(?i)ceza tavan\s*(\d+)", soru)
    if m_tavan and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        cset(cid, "ceza_tavan", max(1, min(int(m_tavan.group(1)), 100)))
        await msg.reply_text(f"✅ Günlük ceza tavanı: {cget(cid, 'ceza_tavan')}")
        return

    # banlilari goster (admin DM)
    if any(x in kucult(soru) for x in ("banlıları göster", "banlilari goster", "yasaklıları göster", "yasaklilari goster", "ban listesi")):
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            await ban_listesi_dm(context.bot, cid, user.id)
            await msg.reply_text("✅ Ban listesi DM'ye gitti (butonlu).")
            return
    if kucult(soru) in ("yasaklılar", "yasaklilar") or kucult(soru).startswith("yasaklılar"):
        # genel kisa liste
        class _U:
            pass
        u = _U()
        u.effective_message = msg
        u.effective_chat = update.effective_chat
        await yasaklilar_komut(update, context)
        return
    if ("affedelim" in kucult(soru) or "af oyla" in kucult(soru)) and msg.reply_to_message and msg.reply_to_message.from_user:
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            await af_oy_baslat(update, context, msg.reply_to_message.from_user)
            return
    if kucult(soru) in ("bu ay engel", "bu ay engellenenler", "scammer sayısı", "scammer sayisi"):
        ay = time.strftime("%Y-%m")
        say = int((cget(cid, "ban_ay") or {}).get(ay) or 0)
        await msg.reply_text(f"📊 Bu ay <b>{say}</b> engel / scammer kaydı.", parse_mode="HTML")
        return

    # isim gecmisi
    if kucult(soru).startswith("isim geçmiş") or kucult(soru).startswith("isim gecmis") or kucult(soru) == "isim geçmişi":
        hedef = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            hedef = msg.reply_to_message.from_user
        if hedef:
            ig = (cget(cid, "isim_gecmis") or {}).get(str(hedef.id)) or []
            uy = (uyeler.get(str(cid)) or {}).get(str(hedef.id)) or {}
            ig2 = uy.get("isim_gecmis") or ig
            if not ig2:
                await msg.reply_text("Kayıtlı isim değişikliği yok.")
                return
            lines = [f"🧾 <b>{html.escape(hedef.full_name or str(hedef.id))}</b>"]
            for x in ig2[-8:]:
                lines.append(f"• {html.escape(x.get('ad') or '')} @{html.escape(x.get('un') or '')} ({x.get('ts','')})")
            await msg.reply_text("\n".join(lines), parse_mode="HTML")
            return

    # anonim oneri (ozelde)
    if ozel and (kucult(soru).startswith("öneri") or kucult(soru).startswith("oneri") or kucult(soru).startswith("anonim")):
        met = re.sub(r"(?i)^(öneri|oneri|anonim)\s*:?\s*", "", soru).strip() or soru
        try:
            await context.bot.send_message(
                SAHIP_ID,
                f"📭 <b>Anonim öneri/şikayet</b>\n{html.escape(met[:500])}\n"
                f"<i>Gönderen gizli tutuldu (id logda yok)</i>",
                parse_mode="HTML",
            )
            await msg.reply_text("✅ Anonim olarak iletildi.")
        except Exception:
            await msg.reply_text("İletilemedi.")
        return

    # argo aciklama
    for a, acik in _KRIPTO_ARGO.items():
        if a in kucult(soru) and any(x in kucult(soru) for x in ("ne demek", "nedir", "anlam")):
            await msg.reply_text(f"📖 <b>{html.escape(a)}</b>: {html.escape(acik)}", parse_mode="HTML")
            return

    # anon duyuru: yapay anon: metin
    if (kucult(soru).startswith("anon:") or kucult(soru).startswith("anon ")) and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        met = re.sub(r"(?i)^anon\s*:\s*", "", soru).strip()
        if met:
            imza = cget(cid, "anon_imza") or "Yönetim"
            try:
                await context.bot.send_message(cid, f"📢 <b>{html.escape(imza)}</b>\n\n{html.escape(met)}", parse_mode="HTML")
                try:
                    await msg.delete()
                except Exception:
                    pass
            except Exception as e:
                await msg.reply_text(f"Hata: {e}")
            return

    # itiraz (ozelde)
    if ozel and kucult(soru).startswith("itiraz"):
        met = soru.split(None, 1)[-1] if " " in soru else "İtiraz"
        # son banlanan grup bilinmiyor — sahip'e genel
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Kabul", callback_data=f"it:ok:0:{user.id}"),
            InlineKeyboardButton("❌ Red", callback_data=f"it:no:0:{user.id}"),
        ]])
        try:
            await context.bot.send_message(
                SAHIP_ID,
                f"📨 <b>İtiraz</b>\n{html.escape(user.full_name or '')} <code>{user.id}</code>\n{html.escape(met[:400])}",
                parse_mode="HTML",
                reply_markup=kb,
            )
            await msg.reply_text("✅ İtirazın iletildi.")
        except Exception:
            await msg.reply_text("İletilemedi.")
        return

    # whitepaper / pdf ozet — document caption
    if msg.reply_to_message and msg.reply_to_message.document and any(
        x in kucult(soru) for x in ("özetle", "ozetle", "whitepaper", "özet", "ozet")
    ):
        doc = msg.reply_to_message.document
        if (doc.mime_type or "").endswith("pdf") or (doc.file_name or "").lower().endswith(".pdf"):
            await msg.reply_text("⏳ PDF özetleniyor...")
            try:
                f = await doc.get_file()
                path = f"/tmp/wp_{user.id}.pdf"
                await f.download_to_drive(path)
                metin_pdf = ""
                try:
                    # ham metin denemesi
                    with open(path, "rb") as fh:
                        raw = fh.read()
                    # basit pdf stream extract
                    metin_pdf = re.sub(rb"[^\x20-\x7E\n]{3,}", b" ", raw).decode("latin-1", errors="ignore")
                    metin_pdf = re.sub(r"\s+", " ", metin_pdf)[:4000]
                except Exception:
                    metin_pdf = ""
                ozet = sor(
                    [{"role": "user", "content":
                      f"Bu whitepaper metninden 4 madde ozet cikar: ana fikir, token dagilimi, riskler, ne ise yarar:\n{metin_pdf[:3500]}"}],
                    zor=True, chat_id=cid,
                )
                await msg.reply_text(f"📄 <b>Whitepaper özeti</b>\n{ozet or 'Özet çıkarılamadı.'}\n<i>Tavsiye değildir.</i>", parse_mode="HTML")
            except Exception as e:
                await msg.reply_text(f"PDF okunamadı: {e}")
            return

    # cuzdan sorgusu (0x... / bc1...)
    for parca in [soru.strip()] + soru.split():
        chain, addr = _adres_mi(parca.strip(".,"))
        if chain and addr:
            bil = _cuzdan_eth(addr) if chain == "eth" else _cuzdan_btc(addr)
            if bil:
                await msg.reply_text(
                    f"👛 <b>{bil['chain']}</b>\n<code>{html.escape(addr)}</code>\n"
                    f"Bakiye: <b>{bil.get('balance')}</b> · Tx: {bil.get('tx')}\n"
                    f"<i>Açık veri · tavsiye değildir</i>",
                    parse_mode="HTML",
                )
            else:
                await msg.reply_text("Cüzdan verisi alınamadı.")
            return

    # tahmin oyunu
    if kucult(soru).startswith("tahmin ") and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        soru_t = soru.split(None, 1)[-1].strip()
        if soru_t and "kapat" not in kucult(soru_t) and "bitir" not in kucult(soru_t):
            cset(cid, "tahmin", {
                "soru": soru_t, "evet": [], "hayir": [],
                "bitis": time.time() + 7 * 86400, "sonuc": None,
            })
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Evet", callback_data=f"th:e:{cid}"),
                InlineKeyboardButton("❌ Hayır", callback_data=f"th:h:{cid}"),
            ]])
            await msg.reply_text(
                f"🎯 <b>Tahmin</b>\n{html.escape(soru_t)}\n\n"
                f"<i>Yatırım tavsiyesi değildir.</i>",
                parse_mode="HTML", reply_markup=kb,
            )
            return
    if kucult(soru) in ("tahmin kapat evet", "tahmin bitir evet", "tahmin kapat hayır", "tahmin kapat hayir"):
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            th = cget(cid, "tahmin") or {}
            if not th.get("soru"):
                await msg.reply_text("Aktif tahmin yok.")
                return
            sonuc = "evet" if "evet" in kucult(soru) else "hayir"
            dogru = list(th.get("evet") or []) if sonuc == "evet" else list(th.get("hayir") or [])
            for uid in dogru:
                guven_ekle(cid, uid, 2)
            cset(cid, "tahmin", None)
            await msg.reply_text(
                f"🏁 Sonuç: <b>{sonuc}</b> · Doğru: {len(dogru)} kişi",
                parse_mode="HTML",
            )
            return

    # ogret: yapay sunu ogren: ...
    if re.search(r"(?i)(öğren|ogren|öğret|ogret)\s*:", soru) or kucult(soru).startswith(("öğren ", "ogren ", "öğret ", "ogret ")):
        is_adm = ozel or await admin_mi(cid, user, context.bot)
        if is_adm or sahip_mi(user):
            bilgi = re.split(r"(?i)(?:öğren|ogren|öğret|ogret)\s*:", soru, maxsplit=1)
            t = (bilgi[-1] if len(bilgi) > 1 else soru.split(None, 1)[-1] if " " in soru else "").strip()
            if t:
                if not ozel:
                    bt = list(cget(cid, "bilgi_tabani") or [])
                    bt.append({"t": t, "by": user.id, "ts": time.strftime("%Y-%m-%d")})
                    cset(cid, "bilgi_tabani", bt[-50:])
                else:
                    durum.setdefault("talimat", []).append({"t": t, "ts": time.strftime("%Y-%m-%d %H:%M")})
                    durum["talimat"] = durum["talimat"][-30:]
                    durum_kaydet()
                await msg.reply_text("✅ Öğrendim, bilgi tabanına eklendi.")
                return

    # arastir — ayni kaynak (RSS+DDG), gundemle tutarli
    if re.search(r"(?i)\b(araştır|arastir|research)\b", soru):
        proje = re.sub(r"(?i)\b(araştır|arastir|research|yapay|şu|su|projeyi|projeyi)\b", "", soru).strip()
        if not proje:
            proje = soru
        try:
            await context.bot.send_chat_action(cid, "typing")
        except Exception:
            pass
        try:
            ham = await asyncio.to_thread(web_arama, proje, 8)
        except Exception as e:
            log.warning("web_arama: %s", e)
            ham = ""
        user_c = (
            f"Soru: {proje}\n\nKaynak metin (RSS/haber):\n{ham or '(bos)'}\n\n"
            "Bu metne dayanarak kisa Turkce cevap ver (max 5 cumle). "
            "Metinde Binance/hack/rezerv geciyorsa inkâr etme; ozetle. "
            "Metin bossa 'kaynak cekemedim' de. Rakam uydurma; metindeki rakami kullan. "
            "Kesin degilse 'iddia / sorusturma asamasinda' de."
        )
        ozet = sor(
            [{"role": "user", "content": user_c}],
            ek="Kaynak metne sadik kal. Uydurma yasak.",
            zor=True,
            soru_metin=proje,
        )
        met = ozet or "Kaynaklardan net özet çıkaramadım."
        if "tavsiye değildir" not in met.lower() and "tavsiye degildir" not in met.lower():
            met = met.rstrip(".") + ".\n(Finansal tavsiye değildir.)"
        await msg.reply_text(f"🔍 {met}")
        return

    # guncel olay (hack/binance vs) — araştır demeden de web
    _guncel_kw = ("hack", "hacklendi", "hacklenmis", "siber", "çalındı", "calindi", "soygun", "breach")
    if any(k in kucult(soru) for k in _guncel_kw) and len(soru) < 200:
        try:
            await context.bot.send_chat_action(cid, "typing")
        except Exception:
            pass
        try:
            ham = await asyncio.to_thread(web_arama, soru, 8)
        except Exception:
            ham = ""
        if ham:
            ozet = sor(
                [{"role": "user", "content":
                  f"Soru: {soru}\n\nKaynak:\n{ham}\n\n"
                  "Kaynaga dayan, kisa Turkce cevap. Inkar etme. Uydurma yasak. Max 5 cumle."}],
                ek="Kaynak metne sadik.",
                zor=True,
                soru_metin=soru,
            )
            if ozet:
                if "tavsiye değildir" not in ozet.lower():
                    ozet = ozet.rstrip(".") + ".\n(Finansal tavsiye değildir.)"
                await msg.reply_text(f"🔆 {ozet}")
                return

    # mini ders
    for anahtar, ders in _MINI_DERS.items():
        if anahtar in kucult(soru) and any(x in kucult(soru) for x in ("nedir", "ne demek", "anlat", "öğret", "ogret", "ders")):
            await msg.reply_text(ders, parse_mode="HTML")
            return

    # emoji tepki KAPALI (parmak/👍 atmaz). Acmak icin panelden emoji_tepki.
    # eski: kisa "sa" eslesmesi "sakin" icinde bile 👍 atiyordu — kaldirildi.

    # topic (forum) — konu bazli bot_mod / kurallar
    tid = getattr(msg, "message_thread_id", None)
    if tid and not ozel:
        taya = (cget(cid, "topic_ayar") or {}).get(str(tid)) or {}
        if taya.get("bot_mod"):
            # gecici olarak bu mesaj icin moda ekle
            ek_parts_topic = f"Bu forum konusu modu: {taya.get('bot_mod')}"
        else:
            ek_parts_topic = ""
    else:
        ek_parts_topic = ""

    # sikayet
    if kucult(soru) in ("şikayet", "sikayet", "report", "şikayet et", "sikayet et") and msg.reply_to_message:
        hedef_m = msg.reply_to_message
        hu = hedef_m.from_user
        if hu:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🚫 Ban", callback_data=f"sk:ban:{cid}:{hu.id}:{hedef_m.message_id}"),
                InlineKeyboardButton("🗑 Sil", callback_data=f"sk:sil:{cid}:{hu.id}:{hedef_m.message_id}"),
                InlineKeyboardButton("Yok say", callback_data=f"sk:yok:{cid}:{hu.id}:{hedef_m.message_id}"),
            ]])
            txt = (
                f"🚨 <b>Şikayet</b>\n"
                f"Şikayet eden: {_ad(user)}\n"
                f"Hedef: {_ad(hu)} <code>{hu.id}</code>\n"
                f"Mesaj: {html.escape((hedef_m.text or hedef_m.caption or '')[:200])}"
            )
            # adminlere / log kanalina
            kid = cget(cid, "log_kanal")
            try:
                if kid:
                    await context.bot.send_message(int(kid), txt, parse_mode="HTML", reply_markup=kb)
                else:
                    await context.bot.send_message(SAHIP_ID, txt, parse_mode="HTML", reply_markup=kb)
                await msg.reply_text("✅ Şikayet iletildi.")
            except Exception as e:
                await msg.reply_text(f"İletilemedi: {e}")
            return

    # reklam basvuru (ozelde sahip disi kilitli — sahip form kaydeder)
    if ozel and sahip_mi(user) and kucult(soru).startswith("reklam onay"):
        await msg.reply_text("Reklam slotu için grupta duyuru kanalını kullan.")
        return
    if "reklam başvur" in kucult(soru) or "reklam basvur" in kucult(soru):
        durum.setdefault("reklam_basvuru", []).append({
            "uid": user.id, "ad": user.full_name or "", "text": soru[:300],
            "ts": time.strftime("%Y-%m-%d %H:%M"),
        })
        durum["reklam_basvuru"] = durum["reklam_basvuru"][-50:]
        durum_kaydet()
        try:
            await context.bot.send_message(
                SAHIP_ID,
                f"📢 Reklam başvurusu\n{html.escape(user.full_name or '')} <code>{user.id}</code>\n{html.escape(soru[:300])}",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await msg.reply_text("✅ Başvurun alındı, incelenecek.")
        return

    # profil karti
    if kucult(soru) in ("profilim", "profil", "profilim nedir", "kartım", "kartim"):
        uy = (uyeler.get(str(cid)) or {}).get(str(user.id)) or {}
        mesaj_s = int(uy.get("mesaj") or 0)
        lakap, min_m, sonraki = mesaj_kademe(mesaj_s)
        puan = guven_get(cid, user.id)
        gun = durum.setdefault("gunluk", {}).setdefault(str(cid), {}).get(str(user.id), {})
        seri = int(gun.get("seri") or 0)
        rz = (cget(cid, "rozetler") or {}).get(str(user.id))
        rozet_satir = f"\n• Rozet: <b>{html.escape(rz)}</b>" if rz else ""
        if sonraki:
            kalan = max(0, sonraki - mesaj_s)
            ilerleme = f"Sonraki kademe için {kalan} mesaj"
        else:
            ilerleme = "En üst kademe"
        await msg.reply_text(
            f"🪪 <b>Profil — {html.escape(user.first_name or 'Üye')}</b>\n"
            f"• Kademe: <b>{html.escape(lakap)}</b>\n"
            f"• Mesaj: <b>{mesaj_s}</b> — {ilerleme}\n"
            f"• Güven: <b>{puan}/100</b>\n"
            f"• Günlük seri: <b>{seri}</b> gün{rozet_satir}\n"
            f"• ID: <code>{user.id}</code>",
            parse_mode="HTML",
        )
        return

    # gunluk giris odulu
    if cget(cid, "gunluk_odul") is not False:
        bugun = datetime.now(TR).strftime("%Y-%m-%d")
        gmap = durum.setdefault("gunluk", {}).setdefault(str(cid), {})
        kayit = dict(gmap.get(str(user.id)) or {})
        if kayit.get("gun") != bugun and cagrildi:
            dun = (datetime.now(TR) - timedelta(days=1)).strftime("%Y-%m-%d")
            seri = int(kayit.get("seri") or 0)
            seri = seri + 1 if kayit.get("gun") == dun else 1
            odul = min(5 + seri, 20)
            kayit.update({"gun": bugun, "seri": seri, "odul": odul})
            gmap[str(user.id)] = kayit
            durum_kaydet()
            guven_ekle(cid, user.id, min(3, 1 + seri // 3))
            # sessizce puan; istege bagli bildirim sadece seri milestone
            if seri in (3, 7, 14, 30):
                try:
                    await msg.reply_text(f"🔥 Günlük seri: <b>{seri}</b> gün! (+güven)", parse_mode="HTML")
                except Exception:
                    pass

    # link / youtube ozeti
    if any(x in kucult(soru) for x in ("özetle", "ozetle", "özet", "ozet")):
        urls = linkleri_cikar(soru, msg)
        if msg.reply_to_message:
            urls += linkleri_cikar(
                msg.reply_to_message.text or msg.reply_to_message.caption or "",
                msg.reply_to_message,
            )
        if urls:
            url = urls[0]
            try:
                await context.bot.send_chat_action(cid, "typing")
            except Exception:
                pass
            parca = ""
            try:
                if "youtu" in url.lower():
                    parca = f"YouTube linki: {url}"
                else:
                    r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
                    if r.ok:
                        txt = re.sub(r"<[^>]+>", " ", r.text)[:2500]
                        parca = txt
            except Exception:
                parca = url
            ozet = sor(
                [{"role": "user", "content": f"Şu içeriği 3 kısa cümleyle özetle:\n{parca[:2000]}"}],
                zor=True,
                chat_id=cid,
            )
            await msg.reply_text(f"📄 {ozet or 'Özet çıkmadı.'}")
            return

    # beni unut — gizlilik
    if kucult(soru) in ("beni unut", "unut beni", "verilerimi sil", "hafızamı sil", "hafizami sil"):
        key = _hafiza_key(cid, user.id)
        _hafiza.pop(key, None)
        gecmis.pop(key, None)
        durum.get("portfoy", {}).pop(str(user.id), None)
        durum_kaydet()
        await msg.reply_text("🗑 Seni unuttum. Hafıza ve portföy silindi.")
        return

    # son islemi geri al
    if any(x in kucult(soru) for x in ("geri al", "geri al son", "son işlemi geri", "son islemi geri", "undo")):
        if not (ozel or await admin_mi(cid, user, context.bot) or moderator_mi(cid, user)):
            await msg.reply_text("Yetkin yok.")
            return
        son = _son_islem.get(str(cid))
        if not son or time.time() - float(son.get("ts") or 0) > 3600:
            await msg.reply_text("Geri alınacak son işlem yok.")
            return
        tip = son.get("tip")
        hid = son.get("hedef_id")
        ters = {"ban": "unban", "mute": "unmute", "unban": "ban", "unmute": "mute"}.get(tip)
        if not ters:
            await msg.reply_text("Bu işlem geri alınamaz.")
            return
        ok = await _islem_uygula(context.bot, cid, ters, hid, user.id)
        await msg.reply_text("✅ Geri alındı." if ok else "❌ Geri alınamadı.")
        return

    # bu spam (yanitla)
    if kucult(soru) in ("bu spam", "spam", "spam işaretle", "spam isaretle") and msg.reply_to_message:
        if await admin_mi(cid, user, context.bot) or moderator_mi(cid, user):
            sp = (msg.reply_to_message.text or msg.reply_to_message.caption or "").strip().lower()
            sp = re.sub(r"\s+", " ", sp)
            if sp:
                _spam_ornek[str(cid)].append(sp[:200])
                _spam_ornek[str(cid)] = _spam_ornek[str(cid)][-50:]
                try:
                    await msg.reply_to_message.delete()
                except Exception:
                    pass
                await msg.reply_text("✅ Spam olarak işaretlendi; benzerleri silinecek.")
                return

    # bot mod
    m = re.search(r"(?i)mod\s*(ciddi|normal|eğlenceli|eglenceli|sert)", soru)
    if m and (await admin_mi(cid, user, context.bot) or sahip_mi(user)):
        mod = m.group(1).lower().replace("ğ", "g")
        if mod == "egenceli":
            mod = "eglenceli"
        cset(cid, "bot_mod", mod)
        await msg.reply_text(f"✅ Bot modu: <b>{mod}</b>", parse_mode="HTML")
        return

    # AMA
    low_s = kucult(soru)
    if "ama aç" in low_s or "ama ac" in low_s or low_s == "ama baslat":
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            _ama[str(cid)] = {"aktif": True, "sorular": {}}
            await msg.reply_text("🎤 AMA açıldı. Üyeler: <code>yapay soru: ...</code>", parse_mode="HTML")
            return
    if "ama kapat" in low_s or "ama bitir" in low_s:
        if await admin_mi(cid, user, context.bot) or sahip_mi(user):
            bag = _ama.get(str(cid)) or {}
            sorular = bag.get("sorular") or {}
            sirali = sorted(sorular.values(), key=lambda x: len(x.get("oy") or []), reverse=True)[:15]
            lines = ["🎤 <b>AMA sonuçları</b>", ""]
            for i, s in enumerate(sirali, 1):
                lines.append(f"{i}. ({len(s.get('oy') or [])} oy) {html.escape(s.get('text','')[:120])}")
            _ama[str(cid)] = {"aktif": False, "sorular": {}}
            await msg.reply_text("\n".join(lines) if sirali else "Soru yoktu.", parse_mode="HTML")
            return
    if (_ama.get(str(cid)) or {}).get("aktif") and (low_s.startswith("soru:") or "soru:" in low_s):
        qtext = re.split(r"(?i)soru\s*:", soru, maxsplit=1)[-1].strip()
        if qtext:
            import hashlib
            qid = hashlib.md5(qtext.lower().encode()).hexdigest()[:10]
            sq = _ama[str(cid)].setdefault("sorular", {})
            if qid in sq:
                sq[qid].setdefault("oy", set()).add(user.id)
            else:
                # tekrar eleme: benzer metin
                for mevcut in sq.values():
                    if qtext.lower()[:40] == (mevcut.get("text") or "").lower()[:40]:
                        mevcut.setdefault("oy", set()).add(user.id)
                        qid = None
                        break
                if qid:
                    sq[qid] = {"text": qtext, "oy": {user.id}, "by": user.id}
            await msg.reply_text("✅ Soru alındı.")
            return

    # dogal dil moderasyon: "ahmeti banla"
    if await admin_mi(cid, user, context.bot) or moderator_mi(cid, user):
        mban = re.search(r"(?i)\b([\wçğıöşüÇĞİÖŞÜ]{2,20})[\'’]?[yiı]?\.?\s*(banla|ban\s?at|yasakla)\b", soru)
        mmute = re.search(r"(?i)\b([\wçğıöşüÇĞİÖŞÜ]{2,20})[\'’]?[yiı]?\.?\s*(sustur|mute|sessiz)\b", soru)
        if mban or mmute:
            tip = "ban" if mban else "mute"
            isim = (mban or mmute).group(1)
            if tip == "ban" and moderator_mi(cid, user) and not await admin_mi(cid, user, context.bot):
                await msg.reply_text("Moderatör banlayamaz.")
                return
            adaylar = _isim_adaylari(cid, isim)
            if not adaylar:
                await msg.reply_text(f"«{html.escape(isim)}» için üye bulamadım. Yanıtla /ban kullan.", parse_mode="HTML")
                return
            await _nl_mod_onay(update, context, tip, adaylar, user)
            return

    # mesaj arama / gecmis ozet
    if any(x in low_s for x in ("ne konuşuldu", "ne konusuldu", "geçen hafta", "gecen hafta", "geçmişte", "gecmiste", "ara:", "arama")):
        konu = re.sub(r"(?i)(yapay|ne konuşuldu|ne konusuldu|geçen hafta|gecen hafta|hakkında|hakkinda|ara:|arama)", " ", soru)
        konu = re.sub(r"\s+", " ", konu).strip().lower()
        arsiv = list(_mesaj_arsiv.get(cid) or [])
        if "hafta" in low_s:
            cutoff = time.time() - 7 * 86400
            arsiv = [x for x in arsiv if x.get("ts", 0) >= cutoff]
        if konu:
            arsiv = [x for x in arsiv if konu in (x.get("text") or "").lower()]
        if not arsiv:
            await msg.reply_text("Bu konuda arşivde bir şey bulamadım (bot yeniden başladıysa arşiv boşalır).")
            return
        ornek = arsiv[-12:]
        metin = "\n".join(f"- {x.get('ad')}: {x.get('text','')[:80]}" for x in ornek)
        ozet = sor(
            [{"role": "user", "content": f"Şu grup mesajlarını 2-3 cümlede özetle:\n{metin}"}],
            zor=True,
            chat_id=cid,
        )
        await msg.reply_text(f"🔎 {ozet or 'Özet çıkmadı.'}")
        return

    # yanit + baglam (ozetle / dogru mu)
    if msg.reply_to_message:
        ry_txt = (msg.reply_to_message.text or msg.reply_to_message.caption or "")[:500]
        ry = msg.reply_to_message.from_user
        ry_ad = (ry.first_name or ry.full_name or "?") if ry else "?"
        ry_ad = str(ry_ad).split()[0]
        low_s = kucult(soru)
        if any(x in low_s for x in ("özetle", "ozetle", "özet", "ozet", "kısalt", "kisalt")):
            soru = f"Şu mesajı kısa özetle:\n«{ry_txt}»"
        elif any(x in low_s for x in ("doğru mu", "dogru mu", "doğru?", "dogru?", "bu doğru", "bu dogru", "yanlış mı", "yanlis mi")):
            soru = f"Bu mesaj doğru mu, kısa ve net söyle:\n«{ry_txt}»"
        elif any(x in low_s for x in ("ne demek", "ne diyor", "açıkla", "acikla")):
            soru = f"Bu mesajı açıkla:\n«{ry_txt}»\nSoru: {soru}"
        elif ry and ry.id == context.bot.id:
            soru = f"(Yapay'a yanıt) {soru}"
        elif ry_txt:
            soru = f"({ry_ad} adlı kişiye yanıt, onun mesajı: «{ry_txt[:120]}») {soru}"
    # stil uyumu: ornek biriktir
    if not ozel and ozellik_acik(cid, "stil_uyum") and metin and len(metin) < 100:
        ornek = list(cget(cid, "stil_ornek") or [])
        if metin not in ornek:
            ornek.append(metin[:80])
            cset(cid, "stil_ornek", ornek[-30:])

    key = _hafiza_key(cid, user.id)
    h = _hafiza_al(key)
    hist = list(h.get("hist") or [])
    # eski gecmis ile uyum
    if not hist and key in gecmis:
        hist = list(gecmis.get(key) or [])

    # dil: turkce disi karakter agirligi
    dil_ipucu = ""
    if re.search(r"[а-яА-Я]", soru):
        dil_ipucu = "Kullanıcı Rusça yazıyor; Rusça cevap ver."
    elif re.search(r"[\u0600-\u06FF]", soru):
        dil_ipucu = "Kullanıcı Arapça yazıyor; Arapça cevap ver."
    elif re.search(r"[a-zA-Z]", soru) and not re.search(r"[ğüşıöçĞÜŞİÖÇ]", soru) and len(soru.split()) > 3:
        # muhtemel Ingilizce
        if sum(1 for w in soru.split() if re.match(r"^[a-zA-Z]+$", w)) >= 3:
            dil_ipucu = "Kullanıcı İngilizce yazıyor; İngilizce cevap ver."

    duygu = _duygu_algila(soru)
    zor = _zor_soru_mu(soru)

    hist.append({"role": "user", "content": f"{ad}: {soru}"})
    hist = hist[-14:]
    ek_parts = []
    if h.get("ozet"):
        ek_parts.append("Bu kişiyle önceki özet: " + h["ozet"])
    if not ozel:
        uy = uyeler.get(str(cid)) or {}
        isimler = []
        for uid, bil in list(uy.items())[:40]:
            isim = (bil.get("ad") or bil.get("kullanici") or "").strip()
            if isim:
                isimler.append(isim.split()[0])
        isimler = [x for x in isimler if x][:25]
        if isimler:
            ek_parts.append("Grup üyeleri: " + ", ".join(isimler))
        ek_parts.append(f"Şu an konuşan: {ad}")
    if durum.get("talimat"):
        ek_parts.append("Ek talimatlar: " + " | ".join(x["t"] for x in durum["talimat"][-5:]))
    kis = cget(cid, "kisilik") or ""
    if kis:
        ek_parts.append("Karakter ayarın (uy): " + kis[:250])
    if not ozel:
        bt = cget(cid, "bilgi_tabani") or []
        if bt:
            ek_parts.append("Grup bilgi tabanı: " + " | ".join(x.get("t", "") for x in bt[-8:]))
        sz = cget(cid, "sozluk") or {}
        if sz:
            ek_parts.append("Grup sözlüğü: " + " | ".join(f"{k}={v}" for k, v in list(sz.items())[-10:]))
        tid = getattr(msg, "message_thread_id", None)
        if tid:
            taya = (cget(cid, "topic_ayar") or {}).get(str(tid)) or {}
            if taya:
                if taya.get("bot_mod"):
                    ek_parts.append(f"Forum konu modu: {taya['bot_mod']}")
                if taya.get("kurallar"):
                    ek_parts.append(f"Bu konu kuralları: {taya['kurallar'][:200]}")
    if not ozel and ozellik_acik(cid, "stil_uyum"):
        ornek = cget(cid, "stil_ornek") or []
        if ornek:
            ek_parts.append(
                "Bu grubun konuşma tarzına uy (örnekler): "
                + " || ".join(ornek[-8:])
            )
    try:
        ad_u = (user.first_name or "")[:40]
        if ad_u:
            ek_parts.append("Konusan üye adı: " + ad_u)
        low_m = kucult(metin or "")
        if "yapay" in low_m and not re.search(r"(?i)\byapay\b", metin or ""):
            ek_parts.append(
                "Üye bilerek çağırmadı; cümlede yanlışlıkla yapay geçti. "
                "1 cümle muzip takıl (isminden espri), kaba olma."
            )
    except Exception:
        pass
    ek = "\n".join(ek_parts)
    if dil_ipucu:
        ek = (ek + "\n" + dil_ipucu).strip()

    try:
        await context.bot.send_chat_action(cid, "typing")
    except Exception:
        pass
    hiz = _mesaj_hiz.get(cid) or deque()
    max_len_hiz = 120 if (len(hiz) >= 12 and not zor) else None

    async def _ai_cevap_arka():
        try:
            yanit = None
            # RESIM OKUMA — foto varsa Gemini vision
            try:
                foto = await mesajdan_foto_indir(context.bot, msg)
            except Exception as e:
                log.warning("foto al: %s", e)
                foto = None
            if foto:
                img_bytes, mime = foto
                prompt = soru if soru and kucult(soru) not in ("yapay", "bot", "ai") else (
                    "Bu görseli incele. Ne gösteriyor, önemli rakam/yazılar neler? "
                    "Kısa, samimi ve mantıklı Türkçe yorum yap."
                )
                sist = (ek + "\n" + SISTEM_TABAN) if ek else SISTEM_TABAN
                yanit = await asyncio.to_thread(gemini_gorsel_sor, prompt, img_bytes, mime, sist)
                if not yanit:
                    yanit = await asyncio.to_thread(
                        sor, hist,
                        (ek or "") + "\nKullanici resim gonderdi ama okuyamadim; metne gore cevap ver.",
                        zor, duygu, soru or "bu resim ne", cid,
                    )
            if not yanit:
                yanit = await asyncio.to_thread(sor, hist, ek, zor, duygu, soru, cid)
            if not yanit or "Forbidden" in (yanit[:30] if yanit else ""):
                yanit = "Anlamadım, tekrar söyler misin?"
            max_len = 500 if zor else 280
            if max_len_hiz:
                max_len = max_len_hiz
            if len(yanit) > max_len:
                kes = yanit[:max_len]
                yanit = (kes.rsplit(".", 1)[0] + ".") if "." in kes else kes.rsplit(" ", 1)[0] + "..."
            yanit = yanit.strip()
            goster = yanit.lstrip("🔆 ").strip() if yanit else yanit
            # kapanis klişelerini at
            try:
                import re as _re
                goster = _re.sub(
                    r"(?is)(\n|^).{0,40}(yardımcı olabilir miyim|başka bir konuda|nasıl yardımcı|başka bir şey|size yardımcı).*$",
                    "",
                    goster or "",
                ).strip()
            except Exception:
                pass
            hist2 = list(hist)
            hist2.append({"role": "assistant", "content": yanit})
            h2 = _hafiza_al(key)
            h2["hist"] = hist2[-14:]
            h2["ts"] = time.time()
            _hafiza[key] = h2
            gecmis[key] = hist2[-14:]
            if len(hist2) >= 12:
                try:
                    _hafiza_ozetle(key)
                except Exception:
                    pass
            try:
                await msg.reply_text(goster)
            except Exception:
                try:
                    await context.bot.send_message(cid, goster)
                except Exception as e:
                    log.warning("AI: %s", e)
        except Exception as e:
            log.warning("AI arka: %s", e)
            try:
                await msg.reply_text("🔆 Biraz yoğunum, tekrar dener misin?")
            except Exception:
                pass

    # basit matematik oran — dogru sayi + kisa espri
    try:
        oran_s = basit_oran_hesap(soru or metin or "")
        if oran_s is not None and cagrildi:
            import random
            espriler = [
                f"Cevap <b>{oran_s}</b>. Cüzdana şimdiden bir bardak soğuk su ısmarla.",
                f"Matematik can çekişiyor ama sonuç <b>{oran_s}</b>.",
                f"<b>{oran_s}</b> — hesap makinesi de aynı diyor, inanmazsan bir daha say.",
                f"Oran net: <b>{oran_s}</b>. Hayırlı olsun, cüzdan yorulmasın.",
            ]
            await msg.reply_text(random.choice(espriler), parse_mode="HTML")
            return
    except Exception as e:
        log.warning("oran hesap: %s", e)

    asyncio.create_task(_ai_cevap_arka())


async def hata(update, ctx):
    err = str(ctx.error or "")
    _hata_log.append(f"{time.strftime('%H:%M:%S')} {err[:180]}")
    if "Conflict" in err and "getUpdates" in err:
        log.error("CONFLICT: Ayni token baska yerde calisiyor.")
    else:
        log.warning("Hata: %s", ctx.error)


async def baslat(app):
    me = await app.bot.get_me()
    log.info("Bot %s hazir @%s | sahip=%s", BOT_SURUM, me.username, SAHIP_ID)
    # acilis testi + surum
    await acilis_testi(app.bot)
    if durum.get("son_surum") != BOT_SURUM:
        durum["son_surum"] = BOT_SURUM
        durum_kaydet()
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
            app.job_queue.run_repeating(tekrar_periyodik, interval=300, first=90)
            app.job_queue.run_repeating(hatirlat_periyodik, interval=30, first=20)
            # yedek_periyodik KAPALI — gunluk json atilmasin
            # app.job_queue.run_repeating(yedek_periyodik, interval=86400, first=3600)
            app.job_queue.run_repeating(haftalik_rapor, interval=604800, first=7200)
            app.job_queue.run_repeating(sohbet_baslatici, interval=1800, first=300)
            app.job_queue.run_repeating(ozel_gun_job, interval=3600, first=120)
            app.job_queue.run_repeating(ekonomi_takvim_job, interval=3600, first=180)
            app.job_queue.run_repeating(gecici_ceza_job, interval=120, first=90)
            app.job_queue.run_repeating(gunun_uyesi_job, interval=3600, first=600)
            app.job_queue.run_repeating(hafta_dolandirici_job, interval=3600, first=900)
            app.job_queue.run_repeating(haftanin_mesaji_job, interval=3600, first=1200)
            app.job_queue.run_repeating(sabah_brifing, interval=3600, first=200)
            log.info("Joblar aktif %s", BOT_SURUM)
            _kuyruk_baslat(app.bot)
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
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & (~filters.COMMAND) & filters.UpdateType.MESSAGE,
            link_filtre_oncelik,
        ),
        group=-5,
    )
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
    app.add_handler(CommandHandler("welcomemute", welcomemute_komut))
    app.add_handler(CommandHandler("hgdurum", hgdurum_komut))
    app.add_handler(CommandHandler("dbg", hgdurum_komut))
    app.add_handler(CommandHandler("hgmute", welcomemute_komut))
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
    app.add_handler(CommandHandler("ozellik", ozellik_komut))
    app.add_handler(CommandHandler("davet", davet_komut))
    app.add_handler(CommandHandler("portfoy", portfoy_komut))
    app.add_handler(CommandHandler("guven", guven_komut))
    app.add_handler(CommandHandler("tekrarekle", tekrarekle_komut))
    app.add_handler(CommandHandler("tekrarliste", tekrarliste_komut))
    app.add_handler(CommandHandler("tekrarsil", tekrarsil_komut))
    app.add_handler(CommandHandler("tekrardur", tekrardur_komut))
    app.add_handler(CommandHandler("tekrarac", tekrardur_komut))
    app.add_handler(CommandHandler("izinilet", izinilet_komut))
    app.add_handler(CommandHandler("iziniletkaldir", iziniletkaldir_komut))
    app.add_handler(CommandHandler("yedek", yedek_komut))
    app.add_handler(CommandHandler("not", not_komut))
    app.add_handler(CommandHandler("mod", mod_komut))
    app.add_handler(CommandHandler("topic", topic_komut))
    app.add_handler(CommandHandler("bakim", bakim_komut))
    app.add_handler(CommandHandler("send", send_komut))
    app.add_handler(CommandHandler("gruplar", gruplar_komut))
    app.add_handler(CommandHandler("grup", grup_sec_komut))
    app.add_handler(CommandHandler("komutlar", komutlar_komut))
    app.add_handler(CommandHandler("boost", boost_komut))
    app.add_handler(CommandHandler("hakkim", boost_komut))
    app.add_handler(CommandHandler("yardim", komutlar_komut))
    app.add_handler(CommandHandler("durum", durum_komut))
    app.add_handler(CommandHandler("log", log_komut))
    app.add_handler(CommandHandler("rozet", rozet_komut))
    app.add_handler(CommandHandler("yasaklilar", yasaklilar_komut))
    app.add_handler(CallbackQueryHandler(unban_btn_callback, pattern=r"^ub:"))
    app.add_handler(CallbackQueryHandler(af_callback, pattern=r"^af:"))
    app.add_handler(CallbackQueryHandler(sikayet_callback, pattern=r"^sk:"))
    app.add_handler(CallbackQueryHandler(tahmin_callback, pattern=r"^th:"))
    app.add_handler(CallbackQueryHandler(itiraz_callback, pattern=r"^it:"))
    app.add_handler(ChatMemberHandler(uye_guncelle, ChatMemberHandler.CHAT_MEMBER))
    try:
        from telegram.ext import ChatBoostHandler
        app.add_handler(ChatBoostHandler(boost_handler))
    except Exception as e:
        log.warning("ChatBoostHandler yok: %s", e)
    try:
        from telegram.ext import MessageReactionHandler
        app.add_handler(MessageReactionHandler(reaksiyon_yonet))
    except Exception as e:
        log.warning("MessageReactionHandler yok: %s", e)
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, mesaj_duzenlendi))
    app.add_handler(CallbackQueryHandler(kuralonay_callback, pattern=r"^ko:"))
    app.add_handler(CallbackQueryHandler(onay_callback, pattern=r"^onay:"))
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
    app.add_handler(CallbackQueryHandler(adam_katil_callback, pattern=r"^adam:"))
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
