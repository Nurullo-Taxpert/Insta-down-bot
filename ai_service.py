import html
import time
import asyncio
import logging
from typing import Dict, Optional, Any
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# Asosiy model band bo'lsa (503) ishlatiladigan zaxira model
FALLBACK_MODEL = "gemini-flash-lite-latest"
REQUEST_TIMEOUT_MS = 90_000
PRIMARY_TIMEOUT_S = 40
FALLBACK_TIMEOUT_S = 90

SYSTEM_INSTRUCTION = (
    "Siz foydali, aqlli, samimiy va xushmuomala sun'iy intellekt (Gemini) yordamchisisiz. "
    "Foydalanuvchilarning savollariga aniq, to'liq, tushunarli va chiroyli javob bering. "
    "O'zbek tilidagi savollarga o'zbek tilida, rus tilidagilarga rus tilida, boshqa tillarda bo'lsa o'sha tilda javob bering. "
    "Javoblaringizda matnni o'qishga qulay qilib, kerak bo'lganda punktlar, ro'yxatlar va abzaslar bilan taqdim eting."
)


class GeminiService:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL or "gemini-3.8-flash"
        self._client: Optional[genai.Client] = None
        self._chats: Dict[int, Any] = {}
        self._chat_timestamps: Dict[int, float] = {}

    @property
    def client(self) -> Optional[genai.Client]:
        if not self.api_key:
            return None
        if self._client is None:
            # Timeout bo'lmasa, Gemini band bo'lganda so'rov cheksiz osilib qoladi
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
            )
        return self._client

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def reset_chat(self, user_id: int):
        """Foydalanuvchining oldingi suhbat tarixini tozalaydi."""
        self._chats.pop(user_id, None)
        self._chat_timestamps.pop(user_id, None)

    def _cleanup_old_sessions(self, max_idle_seconds: int = 7200):
        """2 soatdan ortiq faol bo'lmagan suhbatlarni xotiradan tozalaydi."""
        now = time.time()
        expired = [
            uid for uid, ts in self._chat_timestamps.items()
            if now - ts > max_idle_seconds
        ]
        for uid in expired:
            self._chats.pop(uid, None)
            self._chat_timestamps.pop(uid, None)

    async def _get_or_create_chat(self, user_id: int):
        self._cleanup_old_sessions()

        if user_id in self._chats:
            self._chat_timestamps[user_id] = time.time()
            return self._chats[user_id]

        chat = self._create_chat(self.model_name)
        self._chats[user_id] = chat
        self._chat_timestamps[user_id] = time.time()
        return chat

    def _create_chat(self, model: str, history: Optional[list] = None):
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.7,
        )
        return self.client.aio.chats.create(model=model, config=config, history=history)

    async def _send_with_fallback(self, user_id: int, chat, message_text: str):
        """Asosiy model band (503) yoki javob bermasa, suhbat tarixini saqlagan holda zaxira modelga o'tadi."""
        try:
            # Asosiy modelni uzoq kutmaymiz: SDK ichki qayta urinishlari bilan birga ham shu chegarada to'xtaydi
            return await asyncio.wait_for(chat.send_message(message_text), timeout=PRIMARY_TIMEOUT_S)
        except Exception as e:
            err = str(e).lower() or type(e).__name__.lower()
            busy = isinstance(e, asyncio.TimeoutError) or any(
                k in err for k in ("503", "504", "unavailable", "overloaded", "deadline", "timeout", "timed out")
            )
            if not busy or self.model_name == FALLBACK_MODEL:
                raise
            logger.warning(f"{self.model_name} band, {FALLBACK_MODEL} ga o'tilmoqda: {e!r}")
            fallback = self._create_chat(FALLBACK_MODEL, history=chat.get_history())
            try:
                response = await asyncio.wait_for(fallback.send_message(message_text), timeout=FALLBACK_TIMEOUT_S)
            except asyncio.TimeoutError:
                raise TimeoutError("Gemini timeout")
            self._chats[user_id] = fallback
            return response

    async def ask(self, user_id: int, message_text: str) -> str:
        """
        Foydalanuvchi xabarini Gemini modeliga yuborib javob oladi.
        Kontekst (suhbat tarixi) saqlanadi.
        """
        if not self.is_configured():
            return (
                "⚠️ <b>Gemini API kaliti topilmadi!</b>\n\n"
                "AI Chat ishlashi uchun <code>.env</code> fayliga <code>GEMINI_API_KEY</code> kalitini qo'shish lozim.\n\n"
                "🔑 <i>API kalitni bepul olish:</i> <a href='https://aistudio.google.com'>Google AI Studio</a>"
            )

        try:
            chat = await self._get_or_create_chat(user_id)
            response = await self._send_with_fallback(user_id, chat, message_text)

            if response and response.text:
                return response.text.strip()
            return "Kechirasiz, javob matnini olib bo'lmadi. Qaytadan urinib ko'ring."

        except Exception as e:
            err_msg = str(e).lower()
            logger.error(f"Gemini xatoligi (User: {user_id}): {e}", exc_info=True)

            if "api_key" in err_msg or "invalid api key" in err_msg or "unauthenticated" in err_msg:
                return (
                    "❌ <b>Gemini API kaliti noto'g'ri yoki yaroqsiz!</b>\n\n"
                    "Iltimos, <code>.env</code> faylidagi <code>GEMINI_API_KEY</code> ni tekshiring."
                )
            elif "quota" in err_msg or "resource_exhausted" in err_msg or "429" in err_msg:
                return (
                    "⏳ <b>Gemini so'rovlar limiti tugadi!</b>\n"
                    "Biroz kuting va yana urinib ko'ring."
                )
            elif any(k in err_msg for k in ("503", "504", "unavailable", "deadline", "timeout", "timed out")):
                return (
                    "⏳ <b>Gemini serverlari hozir juda band.</b>\n"
                    "Bir necha daqiqadan so'ng qayta urinib ko'ring."
                )
            elif "safety" in err_msg or "blocked" in err_msg:
                return (
                    "🛡 <b>Kechirasiz, xavfsizlik filtri sababli bu savolga javob berilmadi.</b>\n"
                    "Iltimos, savolni boshqacharoq shaklda berib ko'ring."
                )
            else:
                return (
                    f"❌ <b>Sun'iy intellekt javob berishda xatolik yuz berdi:</b>\n"
                    f"<code>{html.escape(str(e)[:150])}</code>\n\n"
                    "Birozdan so'ng qayta urinib ko'ring yoki «🔄 Yangi suhbat» tugmasini bosing."
                )


# Global singleton nusxa
ai_service = GeminiService()
