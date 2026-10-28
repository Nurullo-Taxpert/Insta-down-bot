import os
import re
import time
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Dict, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CallbackQuery,
    Message
)

from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import web

from config import BOT_TOKEN, DOWNLOAD_DIR
from downloader import MediaDownloader
from ai_service import ai_service

# Loglarni sozlash
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("DIQQAT: BOT_TOKEN topilmadi! .env faylini tekshiring.")

# Katta videolarni (50MB gacha) uzatish uchun 300 soniyalik (5 daqiqa) timeout
session = AiohttpSession(timeout=300)

bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Instagram va YouTube havolalarini tutib olish uchun regex
MEDIA_URL_REGEX = re.compile(
    r"(https?://(?:www\.|m\.)?(?:instagram\.com/[A-Za-z0-9_.\-\/?=&%#]+|youtube\.com/(?:watch\?v=|shorts/|live/|embed/)[A-Za-z0-9_\-\/?=&%#]+|youtu\.be/[A-Za-z0-9_\-\/?=&%#]+))"
)

# Yuklangan videolarni vaqtincha saqlash keshi (dumaloq video qilish uchun)
VIDEO_CACHE: Dict[str, dict] = {}


class AIChatStates(StatesGroup):
    chatting = State()


def cleanup_expired_cache(ttl_seconds: int = 900):
    """
    15 daqiqadan oshgan keshdagi videolarni diskdan o'chiradi.
    """
    now = time.time()
    expired_keys = []
    for cid, data in list(VIDEO_CACHE.items()):
        if now - data.get("timestamp", 0) > ttl_seconds:
            expired_keys.append(cid)
            try:
                p = Path(data["path"])
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Keshni tozalashda xatolik: {e}")

    for cid in expired_keys:
        VIDEO_CACHE.pop(cid, None)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Doimiy asosiy menyu tugmalari.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🤖 Gemini AI Chat")],
            [KeyboardButton(text="ℹ️ Qo'llanma / Yordam")]
        ],
        resize_keyboard=True
    )


def get_ai_chat_keyboard() -> ReplyKeyboardMarkup:
    """
    AI Chat rejimidagi boshqaruv tugmalari.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔄 Yangi suhbat"), KeyboardButton(text="🔙 Chiqish")]
        ],
        resize_keyboard=True
    )


def split_message(text: str, max_length: int = 4000) -> List[str]:
    """
    Telegramning 4096 belgi chegarasi sababli uzun matnlarni qismlarga bo'ladi.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_idx = text.rfind("\n", 0, max_length)
        if split_idx == -1:
            split_idx = text.rfind(" ", 0, max_length)
        if split_idx == -1:
            split_idx = max_length
        chunks.append(text[:split_idx].strip())
        text = text[split_idx:].strip()
    return chunks


async def send_ai_response(message: Message, response_text: str):
    """
    AI javobini xavfsiz jo'natadi (HTML xatolik bersa, oddiy matn orqali).
    """
    chunks = split_message(response_text)
    for chunk in chunks:
        try:
            await message.reply(chunk, parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await message.reply(chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await message.reply(chunk, parse_mode=None)


async def enter_ai_chat_flow(message_or_callback, state: FSMContext):
    """
    AI Chat rejimini faollashtirish.
    """
    await state.set_state(AIChatStates.chatting)
    text = (
        "🤖 <b>Gemini AI Chat rejimiga xush kelibsiz!</b>\n\n"
        "Menga istalgan savolingizni berishingiz mumkin:\n"
        "• 💡 Istalgan sohada savol-javoblar\n"
        "• ✍️ Post, maqola, insho yoki tarjimalar\n"
        "• 💻 Dasturlash va kod yozish bo'yicha maslahatlar\n"
        "• 📚 Maslahatlar, ta'lim va barcha ma'lumotlar\n\n"
        "💬 <b>Savolingizni yozing:</b>\n"
        "<i>(Chiqish uchun «🔙 Chiqish» tugmasini bosing yoki /cancel yozing)</i>"
    )
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(text, reply_markup=get_ai_chat_keyboard())
    else:
        await message_or_callback.answer(text, reply_markup=get_ai_chat_keyboard())


@dp.callback_query(F.data == "start_ai_chat")
async def handle_start_ai_chat_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await enter_ai_chat_flow(callback, state)


@dp.message(F.text == "🤖 Gemini AI Chat")
async def handle_ai_chat_button(message: types.Message, state: FSMContext):
    await enter_ai_chat_flow(message, state)


@dp.message(Command("ai"))
@dp.message(Command("chat"))
async def handle_ai_command(message: types.Message, state: FSMContext):
    command_prefix = "/ai" if message.text.startswith("/ai") else "/chat"
    prompt = message.text.replace(command_prefix, "", 1).strip()

    if not prompt:
        await enter_ai_chat_flow(message, state)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    response = await ai_service.ask(message.from_user.id, prompt)
    await send_ai_response(message, response)


# ==========================================
# AI CHAT REJIMI HANDLERLARI (FSM)
# ==========================================

@dp.message(AIChatStates.chatting, F.text.in_(["🔙 Chiqish", "/cancel", "/exit", "/stop", "Chiqish"]))
async def handle_exit_ai_chat(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>AI Chat rejimidan chiqdingiz.</b>\n\n"
        "Endi yana Instagram/YouTube havolalari yuborishingiz yoki dumaloq video qilish uchun 4 burchak video yuborishingiz mumkin.",
        reply_markup=get_main_keyboard()
    )


@dp.message(AIChatStates.chatting, F.text == "🔄 Yangi suhbat")
async def handle_reset_ai_chat(message: types.Message):
    ai_service.reset_chat(message.from_user.id)
    await message.answer(
        "🧹 <b>Suhbat xotirasi tozalandi!</b>\n\n"
        "Yangi mavzuda savollaringizni yozishingiz mumkin.",
        reply_markup=get_ai_chat_keyboard()
    )


@dp.message(AIChatStates.chatting, F.text)
async def handle_ai_chat_message(message: types.Message):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    response = await ai_service.ask(message.from_user.id, message.text)
    await send_ai_response(message, response)


# ==========================================
# ASOSIY BUYRUQLAR VA YORDAM
# ==========================================

@dp.message(CommandStart())
async def handle_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name or "Foydalanuvchi"
    text = (
        f"👋 <b>Assalomu alaykum, {user_name}!</b>\n\n"
        "🎬 <b>Bot imkoniyatlari:</b>\n"
        "1. 📥 <b>Instagram</b> (Reels, Post, Video) yuklab beraman.\n"
        "2. 🔴 <b>YouTube</b> (Shorts va videolar) yuklab beraman.\n"
        "3. 🔘 <b>Dumaloq video (Video Note)</b> tayyorlayman!\n"
        "4. 🤖 <b>Gemini AI Chat:</b> Istalgan savolingizga sun'iy intellekt orqali aqlli javob beraman!\n\n"
        "💡 <b>Qanday ishlatish kerak?</b>\n"
        "• Instagram yoki YouTube havolasini yuboring — video yuklanadi.\n"
        "• Dumaloq video qilish uchun menga istalgan 4 burchakli video yuboring.\n"
        "• AI bilan suhbatlashish uchun <b>«🤖 Gemini AI Chat»</b> tugmasini bosing yoki <code>/ai savolingiz</code> deb yozing!"
    )
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🤖 Gemini AI Chatni boshlash",
                callback_data="start_ai_chat"
            )
        ]]
    )
    await message.answer(text, reply_markup=get_main_keyboard())
    await message.answer("👇 AI bilan suhbatlashish uchun:", reply_markup=inline_kb)


@dp.message(F.text == "ℹ️ Qo'llanma / Yordam")
@dp.message(Command("help"))
async def handle_help(message: types.Message):
    text = (
        "ℹ️ <b>Qo'llanma:</b>\n\n"
        "📥 <b>Instagram & YouTube yuklash:</b>\n"
        "• Video havolasini shunchaki botga yuboring.\n"
        "• Yuklangan video tagida <code>🔘 Dumaloq video qilish</code> tugmasi chiqadi.\n\n"
        "🔘 <b>Dumaloq video (Video Note):</b>\n"
        "• Istalgan to'rtburchak videoni botga yuboring — bot uni markaziy kvadrat qirqib, Telegram dumaloq videosi qilib beradi.\n"
        "• Maksimal davomiylik: 60 soniya.\n\n"
        "🤖 <b>Gemini AI Chat:</b>\n"
        "• <b>«🤖 Gemini AI Chat»</b> tugmasini bosing yoki <code>/ai savolingiz</code> deb yozing."
    )
    await message.answer(text, reply_markup=get_main_keyboard())


# ==========================================
# VIDEO YUKLASH VA DUMALOQ QILISH
# ==========================================

@dp.message(F.text.regexp(MEDIA_URL_REGEX))
async def handle_media_link(message: types.Message):
    cleanup_expired_cache()

    match = MEDIA_URL_REGEX.search(message.text)
    if not match:
        return

    url = match.group(1)
    is_yt = ("youtube.com" in url) or ("youtu.be" in url)
    platform_name = "YouTube" if is_yt else "Instagram"

    logger.info(f"{platform_name} havolasi qabul qilindi: {url} (User: {message.from_user.id})")
    status_msg = await message.reply(f"⏳ <b>{platform_name} videosi yuklab olinmoqda, kuting...</b>")

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    try:
        result = await asyncio.to_thread(MediaDownloader.download, url)

        if not result.get("success"):
            error_reason = result.get("error", "Noma'lum xatolik yuz berdi.")
            await status_msg.edit_text(f"❌ <b>Xatolik yuz berdi:</b>\n\n{error_reason}")
            return

        file_path = result["file_path"]
        title = result.get("title", "")
        if len(title) > 200:
            title = title[:197] + "..."

        uploader = result.get("uploader", platform_name)
        bot_info = await bot.get_me()

        caption = (
            f"🎬 <b>{title}</b>\n\n"
            f"👤 <b>Kanal/Muallif:</b> {uploader}\n"
            f"🔗 <b>Manba:</b> <a href='{url}'>{platform_name}</a>\n\n"
            f"🤖 <b>Bot:</b> @{bot_info.username}"
        )

        cache_id = str(uuid.uuid4())[:8]
        VIDEO_CACHE[cache_id] = {
            "path": file_path,
            "timestamp": time.time()
        }

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔘 Dumaloq video qilish (Video Note)",
                    callback_data=f"round:{cache_id}"
                )
            ]]
        )

        await status_msg.edit_text("📤 <b>Video Telegramga yuborilmoqda...</b>")
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO)

        video_file = types.FSInputFile(file_path)
        await message.reply_video(
            video=video_file,
            caption=caption,
            duration=result.get("duration"),
            width=result.get("width"),
            height=result.get("height"),
            supports_streaming=True,
            reply_markup=keyboard,
            request_timeout=300
        )

        await status_msg.delete()
        logger.info(f"{platform_name} videosi muvaffaqiyatli jo'natildi.")

    except Exception as e:
        logger.error(f"Yuklashda xatolik yuz berdi: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Xatolik yuz berdi:</b>\n<code>{str(e)[:150]}</code>")


@dp.callback_query(F.data.startswith("round:"))
async def handle_round_callback(callback: CallbackQuery):
    cache_id = callback.data.split(":", 1)[1]
    data = VIDEO_CACHE.get(cache_id)

    if not data or not Path(data["path"]).exists():
        await callback.answer(
            "⚠️ Ushbu video eskirgan yoki o'chirilgan. Iltimos, havolani qaytadan yuboring.",
            show_alert=True
        )
        return

    await callback.answer("🔄 Dumaloq video tayyorlanmoqda, biroz kuting...")
    progress_msg = await callback.message.reply("⏳ <b>Video dumaloq formatga (Video Note) aylantirilmoqda...</b>")
    await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.RECORD_VIDEO_NOTE)

    input_path = data["path"]
    round_path = str(DOWNLOAD_DIR / f"round_{cache_id}.mp4")

    try:
        convert_res = await asyncio.to_thread(
            MediaDownloader.convert_to_round_video,
            input_path,
            round_path,
            max_duration=60
        )

        if not convert_res.get("success"):
            err = convert_res.get("error", "Aylantirib bo'lmadi.")
            await progress_msg.edit_text(f"❌ <b>Xatolik:</b>\n{err}")
            return

        await bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO_NOTE)
        try:
            await callback.message.reply_video_note(
                video_note=types.FSInputFile(round_path),
                length=480,
                request_timeout=180
            )
        except Exception as e:
            if "VOICE_MESSAGES_FORBIDDEN" in str(e):
                await callback.message.reply(
                    "⚠️ <b>Dumaloq videoni yuborib bo'lmadi!</b>\n\n"
                    "Sizning Telegram profilingizda ovozli/dumaloq xabarlarni qabul qilish cheklangan.\n"
                    "<i>Telegram Sozlamalari -> Maxfiylik (Privacy) -> Ovozli xabarlar (Voice Messages)</i> bo'limida botlarga ruxsat bering."
                )
            else:
                raise e
        await progress_msg.delete()

    except Exception as e:
        logger.error(f"Dumaloq videoga aylantirishda xatolik: {e}", exc_info=True)
        await progress_msg.edit_text(f"❌ <b>Aylantirishda xatolik:</b>\n<code>{str(e)[:150]}</code>")

    finally:
        if Path(round_path).exists():
            try:
                Path(round_path).unlink()
            except Exception:
                pass


@dp.message(F.video)
async def handle_incoming_video(message: types.Message):
    cleanup_expired_cache()

    video = message.video
    if video.file_size and video.file_size > 40 * 1024 * 1024:
        await message.reply("⚠️ Video hajmi juda katta. Iltimos, 40 MB dan kichikroq video yuboring.")
        return

    status_msg = await message.reply("⏳ <b>Video qabul qilindi. Dumaloq video (Video Note) tayyorlanmoqda...</b>")
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.RECORD_VIDEO_NOTE)

    unique_id = str(uuid.uuid4())[:8]
    input_file = DOWNLOAD_DIR / f"user_vid_{unique_id}.mp4"
    output_file = DOWNLOAD_DIR / f"round_user_{unique_id}.mp4"

    try:
        await bot.download(video, destination=input_file, timeout=180)

        convert_res = await asyncio.to_thread(
            MediaDownloader.convert_to_round_video,
            str(input_file),
            str(output_file),
            max_duration=60
        )

        if not convert_res.get("success"):
            err = convert_res.get("error", "Videoni aylantirib bo'lmadi.")
            await status_msg.edit_text(f"❌ <b>Xatolik:</b>\n{err}")
            return

        await status_msg.edit_text("📤 <b>Dumaloq video yuborilmoqda...</b>")
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO_NOTE)

        try:
            await message.reply_video_note(
                video_note=types.FSInputFile(str(output_file)),
                length=480,
                request_timeout=180
            )
        except Exception as e:
            if "VOICE_MESSAGES_FORBIDDEN" in str(e):
                await message.reply(
                    "⚠️ <b>Dumaloq videoni yuborib bo'lmadi!</b>\n\n"
                    "Sizning Telegram profilingizda ovozli/dumaloq xabarlarni qabul qilish cheklangan.\n"
                    "<i>Telegram Sozlamalari -> Maxfiylik (Privacy) -> Ovozli xabarlar (Voice Messages)</i> bo'limida botlarga ruxsat bering."
                )
            else:
                raise e
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Foydalanuvchi videosini aylantirishda xatolik: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Xatolik yuz berdi:</b>\n<code>{str(e)[:150]}</code>")

    finally:
        for f in (input_file, output_file):
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass


@dp.message()
async def handle_other_messages(message: types.Message):
    await message.reply(
        "👋 <b>Nima qilmoqchisiz?</b>\n\n"
        "• 🤖 Sun'iy intellekt bilan suhbatlashish uchun <b>«🤖 Gemini AI Chat»</b> tugmasini bosing yoki <code>/ai savolingiz</code> deb yozing.\n"
        "• 📥 <b>Instagram</b> yoki <b>YouTube</b> havolasini yuborsangiz, videoni yuklab beraman.\n"
        "• 🔘 Dumaloq video qilish uchun esa istalgan <b>4 burchak videoni</b> yuboring 🎥",
        reply_markup=get_main_keyboard()
    )


async def start_health_check_server():
    """Render Web Service uchun portni tinglovchi mini health-check server."""
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()

    async def ping(request):
        return web.Response(text="Bot is running! 🚀", content_type="text/plain")

    app.router.add_get("/", ping)
    app.router.add_get("/health", ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Render health-check server {port}-portda ishga tushirildi.")


async def main():
    logger.info("Bot ishga tushmoqda...")
    # Render Web Service port talab qiladi (PORT o'zgaruvchisi mavjud bo'lsa)
    if "PORT" in os.environ:
        await start_health_check_server()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
