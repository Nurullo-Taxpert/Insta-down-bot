# 🎬 Media Downloader, Video Note & Gemini AI Telegram Bot

Ushbu bot ko'p funksiyali Telegram yordamchisi bo'lib, quyidagi vazifalarni bajaradi:
1. 🤖 **Gemini AI Chat:** Google Gemini sun'iy intellekti orqali istalgan savollarga to'liq va aqlli javob berish.
2. 📥 **Instagram:** Reels, post va IGTV videolarini yuqori sifatda yuklash.
3. 🔴 **YouTube:** YouTube Shorts va standart videolarni audio bilan birlashtirib yuklash.
4. 🔘 **Dumaloq video (Telegram Video Note):** To'rtburchak videolarni 1:1 formatdagi dumaloq video shakliga aylantirish.

---

## 🚀 Asosiy imkoniyatlar

1. 🤖 **Google Gemini AI Chat:**
   - Menyudagi **«🤖 Gemini AI Chat»** tugmasi orqali rejimga kirish.
   - Tezkor savollar uchun: `/ai savolingiz` yoki `/chat savolingiz`.
   - Kontekstni (suhbat tarixini) eslab qolish.
   - `🔄 Yangi suhbat` orqali xotirani tozalash va `🔙 Chiqish` orqali rejimdan chiqish.
   - O'zbek, rus, ingliz va boshqa tillarda erkin muloqot.

2. 📥 **Instagram & YouTube yuklash:**
   - Havolani yuborishning o'zi kifoya.
   - Yuklangan video ostida `🔘 Dumaloq video qilish` tugmasi chiqadi.

3. 🔘 **Dumaloq video (Video Note / Круглое видео):**
   - **Tugma orqali:** Yuklangan video tagidagi tugmani bosish orqali.
   - **To'g'ridan-to'g'ri:** Botga istalgan to'rtburchak videoni yuborsangiz, avtomatik kvadrat qirqilib, teleskop (Video note) formatida qaytariladi.

---

## 📁 Loyiha tuzilishi

- [bot.py](file:///d:/Shaxsiy/AI/Instagram%20download/bot.py) — Asosiy bot handlerlari, menyu va tugmalar.
- [ai_service.py](file:///d:/Shaxsiy/AI/Instagram%20download/ai_service.py) — Google Gemini AI integratsiyasi va suhbat xotirasi boshqaruvi.
- [downloader.py](file:///d:/Shaxsiy/AI/Instagram%20download/downloader.py) — YouTube va Instagram yuklovchisi hamda FFmpeg konverteri.
- [config.py](file:///d:/Shaxsiy/AI/Instagram%20download/config.py) — Konfiguratsiya va sozlamalar.
- [requirements.txt](file:///d:/Shaxsiy/AI/Instagram%20download/requirements.txt) — Kerakli kutubxonalar (`aiogram`, `google-genai`, `yt-dlp`, `imageio-ffmpeg`).
- [.env](file:///d:/Shaxsiy/AI/Instagram%20download/.env) — Bot tokeni va Gemini API kaliti.

---

## 🛠 O'rnatish va Ishga tushirish

1. Kutubxonalarni o'rnatish:
   ```bash
   pip install -r requirements.txt
   ```

2. `.env` faylida sozlamalarni kiriting:
   ```env
   BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
   GEMINI_API_KEY=YOUR_GEMINI_API_KEY
   ```

3. Botni ishga tushirish:
   ```bash
   python bot.py
   ```
