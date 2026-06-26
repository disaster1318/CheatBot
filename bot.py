import asyncio
import logging
import random
import re
import string
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    PreCheckoutQuery,
    LabeledPrice,
    ErrorEvent,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client, Client

# ──────────────────────────────────────────────────────────────────────────
# ВНИМАНИЕ: токен и ключ ниже — тестовые по словам пользователя.
# Если это не так (или бот когда-нибудь станет реальным) — обязательно
# вынести в переменные окружения (os.environ) и перевыпустить токен у @BotFather,
# так как любой, кто видел этот файл, может управлять ботом.
# ──────────────────────────────────────────────────────────────────────────
API_TOKEN = "8942639067:AAGgub5pba2LK2WLjJ6n1KpJGfmGcZpVMCQ"
ADMIN_ID = 8915415360

SUPABASE_URL = "https://umjmcdvjdqlsjmphvsfc.supabase.co"
SUPABASE_KEY = "sb_publishable_4hpLHc_Wxl323Y5nGODAdQ_3vle6d2t"

MAX_CUSTOM_DAYS = 3650  # ограничение на "свои дни", чтобы не улетать в абсурдные суммы
STARS_PER_DAY = 50

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("xenon_bot")


class States(StatesGroup):
    choosing_duration = State()
    custom_days = State()
    support_message = State()
    admin_add = State()
    admin_remove = State()
    admin_give = State()
    admin_ban = State()
    admin_unban = State()
    admin_create_key = State()
    enter_key = State()


# ── Утилиты ────────────────────────────────────────────────────────────────

def generate_license() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=16))


_MD_SPECIAL_RE = re.compile(r"([_*`\[\]])")
_SEPARATOR_RE = re.compile(r"[\s,]+")


def split_id_days(text: str):
    """Парсит строки вида 'ID дни', 'ID, дни' или 'ID,дни' — разделителем может
    быть запятая и/или любые пробельные символы (обычный пробел, неразрывный
    пробел \\xa0, табуляция и т.п.), в любом количестве. Возвращает (user_id, days)
    или вызывает ValueError."""
    cleaned = _SEPARATOR_RE.sub(" ", text.strip())
    parts = cleaned.split(" ")
    parts = [p for p in parts if p]  # на случай начальных/конечных разделителей
    if len(parts) != 2:
        raise ValueError(f"expected 2 parts, got {len(parts)}: {parts!r}")
    user_id = int(parts[0])
    days = int(parts[1])
    return user_id, days


def escape_md(text) -> str:
    """Экранирует спецсимволы Markdown (legacy parse_mode='Markdown'),
    чтобы username/тексты с _ * ` [ ] не ломали edit_text/answer."""
    if text is None:
        return "—"
    return _MD_SPECIAL_RE.sub(r"\\\1", str(text))


def safe_username(user: types.User) -> str:
    """first_name/username пользователя могут содержать markdown-спецсимволы."""
    name = escape_md(user.first_name or "")
    uname = f"@{escape_md(user.username)}" if user.username else "без username"
    return f"{name} ({uname})"


# ── Доступ к данным (с обработкой ошибок Supabase) ─────────────────────────

def _safe_select(table: str, user_id: int):
    try:
        res = supabase.table(table).select("*").eq("user_id", user_id).execute()
        return res.data
    except Exception:
        logger.exception("Ошибка запроса к таблице %s для user_id=%s", table, user_id)
        return []


def get_user_record(user_id: int) -> dict:
    data = _safe_select("users", user_id)
    return data[0] if data else {}


def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    try:
        admin_check = supabase.table("admins").select("*").eq("user_id", user_id).execute()
        return bool(admin_check.data)
    except Exception:
        logger.exception("Ошибка проверки админа user_id=%s", user_id)
        return False


def is_subscribed_data(user_data: dict) -> bool:
    if user_data.get("banned", 0) == 1:
        return False
    end_date = user_data.get("end_date")
    if not end_date:
        return False
    try:
        return datetime.strptime(end_date, "%Y-%m-%d") > datetime.now()
    except (ValueError, TypeError):
        return False


def is_subscribed(user_id: int) -> bool:
    return is_subscribed_data(get_user_record(user_id))


def get_days_left_data(user_data: dict) -> int:
    end_date = user_data.get("end_date")
    if not end_date:
        return 0
    try:
        delta = datetime.strptime(end_date, "%Y-%m-%d") - datetime.now()
        return max(delta.days, 0)
    except (ValueError, TypeError):
        return 0


def get_subscription_end_data(user_data: dict) -> str:
    return user_data.get("end_date") or "Нет подписки"


def activate_subscription(user_id: int, days: int) -> bool:
    """Продлевает подписку. Если она уже активна — добавляет дни к текущей дате окончания,
    а не перезаписывает (иначе повторная покупка/выдача укорачивала бы уже оплаченный срок,
    если новый срок короче старого)."""
    try:
        existing_data = _safe_select("users", user_id)
        now = datetime.now()
        base_date = now
        if existing_data:
            current_end = existing_data[0].get("end_date")
            if current_end:
                try:
                    parsed = datetime.strptime(current_end, "%Y-%m-%d")
                    if parsed > now:
                        base_date = parsed
                except (ValueError, TypeError):
                    pass

        end_date = (base_date + timedelta(days=days)).strftime("%Y-%m-%d")

        if existing_data:
            supabase.table("users").update({"end_date": end_date}).eq("user_id", user_id).execute()
        else:
            supabase.table("users").insert({"user_id": user_id, "end_date": end_date}).execute()
        return True
    except Exception:
        logger.exception("Ошибка активации подписки user_id=%s days=%s", user_id, days)
        return False


def get_ref_by(user_id: int):
    return get_user_record(user_id).get("ref_by")


def set_ref_by(user_id: int, ref_id: int) -> None:
    try:
        existing = _safe_select("users", user_id)
        if existing:
            supabase.table("users").update({"ref_by": ref_id}).eq("user_id", user_id).execute()
        else:
            supabase.table("users").insert({"user_id": user_id, "ref_by": ref_id}).execute()
    except Exception:
        logger.exception("Ошибка установки ref_by user_id=%s ref_id=%s", user_id, ref_id)


def get_user_key(user_id: int):
    try:
        res = supabase.table("keys").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data[0].get("license_key")
    except Exception:
        logger.exception("Ошибка получения ключа user_id=%s", user_id)
    return None


def get_total_earnings() -> int:
    try:
        res = supabase.table("payments").select("amount").execute()
        return sum(p.get("amount", 0) for p in res.data)
    except Exception:
        logger.exception("Ошибка получения суммы оплат")
        return 0


def get_total_payments() -> int:
    try:
        res = supabase.table("payments").select("id", count="exact").execute()
        return res.count or 0
    except Exception:
        logger.exception("Ошибка получения количества оплат")
        return 0


def get_active_users():
    try:
        now = datetime.now().strftime("%Y-%m-%d")
        res = supabase.table("users").select("user_id, end_date").eq("banned", 0).execute()
        return [
            (u["user_id"], u["end_date"])
            for u in res.data
            if u.get("end_date") and u["end_date"] > now
        ]
    except Exception:
        logger.exception("Ошибка получения активных пользователей")
        return []


# ── Клавиатуры ───────────────────────────────────────────────────────────

def main_menu(user_id: int) -> InlineKeyboardMarkup:
    user_data = get_user_record(user_id)

    if user_data.get("banned", 0) == 1:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⛔ Доступ заблокирован", callback_data="banned")]
        ])

    kb = []
    if is_subscribed_data(user_data):
        kb.append([InlineKeyboardButton(text="⬇️ Скачать чит", callback_data="download_cheat")])
        kb.append([InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile")])
    else:
        kb.append([InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_subscription")])
        kb.append([InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile")])

    kb.append([InlineKeyboardButton(text="🔗 Реферальная система", callback_data="referral_system")])
    kb.append([InlineKeyboardButton(text="📢 Наш канал", callback_data="our_channel")])
    kb.append([InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")])

    if is_admin(user_id):
        kb.append([InlineKeyboardButton(text="⚙️ Админ меню", callback_data="admin_menu")])

    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_kb_row():
    """Возвращает строку (список кнопок), а не InlineKeyboardMarkup — для встраивания в составные клавиатуры."""
    return [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]


def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[back_kb_row()])


def subscription_durations() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день — 50 ⭐", callback_data="sub_1")],
        [InlineKeyboardButton(text="7 дней — 100 ⭐", callback_data="sub_7")],
        [InlineKeyboardButton(text="30 дней — 250 ⭐", callback_data="sub_30")],
        [InlineKeyboardButton(text="365 дней — 500 ⭐", callback_data="sub_365")],
        [InlineKeyboardButton(text="✏️ Свои дни", callback_data="custom_days")],
        back_kb_row(),
    ])


def cheat_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 PUBG", callback_data="cheat_pubg")],
        [InlineKeyboardButton(text="⚔️ Brawl Stars", callback_data="cheat_brawl")],
        [InlineKeyboardButton(text="🔫 Standoff 2", callback_data="cheat_standoff")],
        [InlineKeyboardButton(text="⚡ Mobile Legends", callback_data="cheat_ml")],
        [InlineKeyboardButton(text="🎮 Roblox", callback_data="cheat_roblox")],
        back_kb_row(),
    ])


def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Создать ключ", callback_data="admin_create_key")],
        [InlineKeyboardButton(text="📦 Все ключи", callback_data="admin_keys")],
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove")],
        [InlineKeyboardButton(text="📋 Все подписки", callback_data="admin_users")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_give")],
        [InlineKeyboardButton(text="🔨 Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🔓 Разбан", callback_data="admin_unban")],
        [InlineKeyboardButton(text="💰 Статистика", callback_data="admin_stats")],
        back_kb_row(),
    ])


# ── Хендлеры ──────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("REF"):
        try:
            ref_id = int(args[1][3:])
            if ref_id != message.from_user.id and not get_ref_by(message.from_user.id):
                set_ref_by(message.from_user.id, ref_id)
        except ValueError:
            pass  # некорректная реф-ссылка — просто игнорируем

    await message.answer(
        "🔥 Добро пожаловать в магазин читов!\n\nВыбери действие:",
        reply_markup=main_menu(message.from_user.id),
    )


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # на случай если юзер был в середине ввода (FSM) — выходим из него
    await callback.message.edit_text(
        "🔥 Главное меню:",
        reply_markup=main_menu(callback.from_user.id),
    )
    await callback.answer()


@dp.callback_query(F.data == "my_profile")
async def my_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data = get_user_record(user_id)

    days = get_days_left_data(user_data)
    end_date = get_subscription_end_data(user_data)
    ref_by = get_ref_by(user_id)
    total_payments = get_total_payments()
    license_key = get_user_key(user_id)

    text = (
        f"👤 *Твой профиль*\n\n"
        f"📅 Дней подписки: *{days}*\n"
        f"📆 Подписка до: *{escape_md(end_date)}*\n"
        f"🔗 Пригласил: *{escape_md(ref_by) if ref_by else 'Нет'}*\n"
        f"💰 Всего оплат в боте: *{total_payments}*\n\n"
    )

    if license_key:
        text += f"🔑 *Ваш ключ:*\n`{license_key}`"
    else:
        text += "❌ *Купите подписку!*"

    kb = [back_kb_row()]
    if not license_key and not is_subscribed_data(user_data):
        kb.insert(0, [InlineKeyboardButton(text="🔑 Ввести ключ", callback_data="enter_key")])

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()


@dp.callback_query(F.data == "enter_key")
async def enter_key_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔑 Введи свой лицензионный ключ:",
        reply_markup=back_button(),
    )
    await state.set_state(States.enter_key)
    await callback.answer()


@dp.message(States.enter_key)
async def process_enter_key(message: types.Message, state: FSMContext):
    key = message.text.strip().upper()
    try:
        res = supabase.table("keys").select("*").eq("license_key", key).execute()
    except Exception:
        logger.exception("Ошибка проверки ключа")
        await message.answer("⚠️ Ошибка сервера, попробуй позже.", reply_markup=back_button())
        return

    if not res.data:
        await message.answer("❌ Неверный ключ! Попробуй снова.", reply_markup=back_button())
        return

    key_data = res.data[0]
    if key_data.get("used", 0) == 1:
        await message.answer("❌ Этот ключ уже использован!", reply_markup=main_menu(message.from_user.id))
        await state.clear()
        return

    expires = key_data.get("expires_at")
    if expires and expires < datetime.now().strftime("%Y-%m-%d"):
        await message.answer("❌ Ключ истёк!", reply_markup=main_menu(message.from_user.id))
        await state.clear()
        return

    days_left = 30
    if expires:
        try:
            days_left = (datetime.strptime(expires, "%Y-%m-%d") - datetime.now()).days
            if days_left < 1:
                days_left = 30
        except (ValueError, TypeError):
            days_left = 30

    if activate_subscription(message.from_user.id, days_left):
        supabase.table("keys").update({"used": 1}).eq("license_key", key).execute()
        await message.answer(
            f"✅ Ключ активирован! Подписка на {days_left} дней.\n"
            f"Теперь тебе доступен раздел 'Скачать чит'.",
            reply_markup=main_menu(message.from_user.id),
        )
    else:
        await message.answer("⚠️ Не удалось активировать подписку, попробуй позже.", reply_markup=back_button())
    await state.clear()


@dp.callback_query(F.data == "referral_system")
async def referral_system(callback: CallbackQuery):
    bot_username = (await bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=REF{callback.from_user.id}"
    text = (
        f"🔗 *Реферальная система*\n\n"
        f"Твоя ссылка:\n`{ref_link}`\n\n"
        f"💰 За каждого друга, купившего подписку,\n"
        f"ты получишь *40%* от его покупки в днях!"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()


@dp.callback_query(F.data == "our_channel")
async def our_channel(callback: CallbackQuery):
    await callback.message.edit_text(
        "📢 *Наш канал*\n\nПодписывайся:\nhttps://t.me/xenoncheatschanell",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    await callback.answer()


@dp.callback_query(F.data == "buy_subscription")
async def buy_sub(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💎 *При покупке подписки*\nты получаешь доступ к 5+ читам!\n\nВыбери длительность:",
        parse_mode="Markdown",
        reply_markup=subscription_durations(),
    )
    await state.set_state(States.choosing_duration)
    await callback.answer()


@dp.callback_query(F.data == "custom_days")
async def custom_days(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"✏️ Введи количество дней (от 1 до {MAX_CUSTOM_DAYS}):",
        reply_markup=back_button(),
    )
    await state.set_state(States.custom_days)
    await callback.answer()


@dp.message(States.custom_days)
async def process_custom_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text)
    except ValueError:
        await message.answer("❌ Введи число!")
        return

    if days <= 0:
        await message.answer("❌ Введи положительное число!")
        return
    if days > MAX_CUSTOM_DAYS:
        await message.answer(f"❌ Максимум {MAX_CUSTOM_DAYS} дней за раз!")
        return

    price = days * STARS_PER_DAY
    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="Подписка на читы",
            description=f"Доступ к читам на {days} дней",
            payload=f"sub_{days}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Подписка", amount=price)],
            start_parameter="sub",
        )
        await state.clear()
    except Exception:
        logger.exception("Ошибка отправки инвойса (custom_days)")
        await message.answer("⚠️ Не удалось создать счёт на оплату, попробуй позже.")


@dp.callback_query(F.data.startswith("sub_"))
async def process_sub(callback: CallbackQuery, state: FSMContext):
    try:
        days = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Некорректные данные", show_alert=True)
        return

    prices_map = {1: 50, 7: 100, 30: 250, 365: 500}
    price = prices_map.get(days, days * STARS_PER_DAY)

    try:
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title="Подписка на читы",
            description=f"Доступ к читам на {days} дней",
            payload=f"sub_{days}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Подписка", amount=price)],
            start_parameter="sub",
        )
    except Exception:
        logger.exception("Ошибка отправки инвойса (process_sub)")
        await callback.message.answer("⚠️ Не удалось создать счёт на оплату, попробуй позже.")
    await state.clear()
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    try:
        days = int(payload.split("_")[1])
    except (IndexError, ValueError):
        logger.error("Некорректный payload оплаты: %s", payload)
        await message.answer("⚠️ Произошла ошибка обработки платежа. Напиши в поддержку!")
        return

    amount = message.successful_payment.total_amount
    user_id = message.from_user.id

    if not activate_subscription(user_id, days):
        await message.answer("⚠️ Оплата прошла, но подписка не активировалась. Напиши в поддержку!")
        return

    try:
        supabase.table("payments").insert({
            "user_id": user_id,
            "days": days,
            "amount": amount,
            "date": datetime.now().isoformat(),
        }).execute()
    except Exception:
        logger.exception("Не удалось записать платёж в таблицу payments")

    # Реферальный бонус начисляется один раз — сразу обнуляем ref_by ДО уведомления,
    # чтобы при повторной покупке бонус не пришёл снова.
    ref_by = get_ref_by(user_id)
    if ref_by:
        try:
            supabase.table("users").update({"ref_by": None}).eq("user_id", user_id).execute()
        except Exception:
            logger.exception("Не удалось обнулить ref_by для user_id=%s", user_id)

        bonus_days = int(days * 0.4)
        if bonus_days > 0 and activate_subscription(ref_by, bonus_days):
            try:
                await bot.send_message(ref_by, f"🎉 Твой реферал купил подписку! Ты получил +{bonus_days} дней!")
            except Exception:
                logger.warning("Не удалось отправить уведомление рефереру %s", ref_by)

    await message.answer(
        f"✅ Оплата прошла!\n"
        f"Подписка на *{days}* дней активирована!\n\n"
        f"📱 Перейди в раздел *'Скачать чит'*,\n"
        f"выбери игру и получи свой ключ и .apk!",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id),
    )

    try:
        admins = supabase.table("admins").select("user_id").execute()
        for admin in admins.data:
            try:
                await bot.send_message(
                    admin["user_id"],
                    f"🛒 Юзер {safe_username(message.from_user)}\n"
                    f"купил подписку на {days} дней за {amount} ⭐!",
                    parse_mode="Markdown",
                )
            except Exception:
                logger.warning("Не удалось уведомить админа %s", admin["user_id"])
    except Exception:
        logger.exception("Не удалось получить список админов для уведомления об оплате")


@dp.callback_query(F.data == "download_cheat")
async def download_cheat(callback: CallbackQuery):
    if not is_subscribed(callback.from_user.id):
        await callback.message.answer("❌ Нет активной подписки!", reply_markup=back_button())
        await callback.answer()
        return
    await callback.message.edit_text(
        "*Выбери чит и доминируй в играх!*",
        parse_mode="Markdown",
        reply_markup=cheat_menu(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("cheat_"))
async def send_cheat(callback: CallbackQuery):
    game = callback.data.split("_")[1]
    user_id = callback.from_user.id

    if not is_subscribed(user_id):
        await callback.message.answer("❌ Нет активной подписки!", reply_markup=back_button())
        await callback.answer()
        return

    try:
        key_res = supabase.table("keys").select("*").eq("user_id", user_id).execute()
    except Exception:
        logger.exception("Ошибка получения ключа в send_cheat")
        await callback.message.answer("⚠️ Ошибка сервера, попробуй позже.", reply_markup=back_button())
        await callback.answer()
        return

    try:
        if key_res.data:
            license_key = key_res.data[0]["license_key"]
            expires = key_res.data[0].get("expires_at", "∞")
            supabase.table("keys").update({"game": game}).eq("user_id", user_id).execute()
        else:
            license_key = generate_license()
            expires_at = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            supabase.table("keys").insert({
                "user_id": user_id,
                "license_key": license_key,
                "game": game,
                "created_at": datetime.now().isoformat(),
                "expires_at": expires_at,
                "used": 0,
            }).execute()
            expires = expires_at
    except Exception:
        logger.exception("Ошибка создания/обновления ключа в send_cheat")
        await callback.message.answer("⚠️ Ошибка сервера, попробуй позже.", reply_markup=back_button())
        await callback.answer()
        return

    apk_links = {
        "pubg": "https://ссылка_на_pubg.apk",
        "brawl": "https://ссылка_на_brawl.apk",
        "standoff": "https://ссылка_на_standoff.apk",
        "ml": "https://ссылка_на_ml.apk",
        "roblox": "https://ссылка_на_roblox.apk",
    }
    apk_link = apk_links.get(game, "https://ссылка_на_чит.apk")

    await callback.message.answer(
        f"📁 *Чит для {escape_md(game.upper())}*\n\n"
        f"🔑 *Твой ключ:*\n`{license_key}`\n"
        f"📅 Действителен до: {expires}\n\n"
        f"📱 *Скачай .apk:*\n[Скачать {escape_md(game.upper())}]({apk_link})\n\n"
        f"Установи и введи ключ при запуске.\n"
        f"Ключ также доступен в разделе *'Мой профиль'*.",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    await callback.answer()


@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🆘 Напиши свою проблему:", reply_markup=back_button())
    await state.set_state(States.support_message)
    await callback.answer()


@dp.message(States.support_message)
async def process_support(message: types.Message, state: FSMContext):
    try:
        admins = supabase.table("admins").select("user_id").execute()
        admin_ids = [a["user_id"] for a in admins.data]
    except Exception:
        logger.exception("Ошибка получения списка админов в process_support")
        admin_ids = []

    if ADMIN_ID not in admin_ids:
        admin_ids.append(ADMIN_ID)  # главный админ должен видеть обращения даже если не в таблице admins

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"🆘 *Новое обращение!*\n\n"
                f"От: {safe_username(message.from_user)}\n"
                f"ID: `{message.from_user.id}`\n\n"
                f"Сообщение:\n{escape_md(message.text)}",
                parse_mode="Markdown",
            )
        except Exception:
            logger.warning("Не удалось отправить обращение админу %s", admin_id)

    await message.answer("✅ Отправлено админам!", reply_markup=main_menu(message.from_user.id))
    await state.clear()


@dp.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ *Админ панель*",
        parse_mode="Markdown",
        reply_markup=admin_panel(),
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_create_key")
async def admin_create_key(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text(
        "🔑 *Создать ключ*\n\n"
        "Введи ID пользователя и срок в днях (формат: `ID, 30`):",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    await state.set_state(States.admin_create_key)
    await callback.answer()


@dp.message(States.admin_create_key)
async def process_admin_create_key(message: types.Message, state: FSMContext):
    try:
        user_id, days = split_id_days(message.text)
        if days <= 0:
            raise ValueError("days must be positive")
    except ValueError:
        await message.answer("❌ Ошибка! Формат: `ID, 30` (оба значения — целые числа, дни > 0)", parse_mode="Markdown")
        return

    license_key = generate_license()
    expires_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        existing = _safe_select("keys", user_id)
        if existing:
            supabase.table("keys").update({
                "license_key": license_key,
                "expires_at": expires_at,
                "used": 0,
            }).eq("user_id", user_id).execute()
        else:
            supabase.table("keys").insert({
                "user_id": user_id,
                "license_key": license_key,
                "game": "all",
                "created_at": datetime.now().isoformat(),
                "expires_at": expires_at,
                "used": 0,
            }).execute()
    except Exception:
        logger.exception("Ошибка создания ключа админом")
        await message.answer("⚠️ Ошибка сервера при создании ключа.")
        await state.clear()
        return

    if activate_subscription(user_id, days):
        await message.answer(
            f"✅ Ключ создан и подписка активирована!\n\n"
            f"🔑 `{license_key}`\n"
            f"👤 Пользователь: `{user_id}`\n"
            f"📅 Действителен до: {expires_at}\n"
            f"📆 Дней: {days}",
            parse_mode="Markdown",
            reply_markup=main_menu(message.from_user.id),
        )
    else:
        await message.answer("⚠️ Ключ создан, но подписка не активировалась. Проверь вручную.")
    await state.clear()


@dp.callback_query(F.data == "admin_keys")
async def admin_keys(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    try:
        res = supabase.table("keys").select("license_key, user_id, game, expires_at, used").execute()
    except Exception:
        logger.exception("Ошибка получения списка ключей")
        await callback.message.edit_text("⚠️ Ошибка сервера.", reply_markup=back_button())
        await callback.answer()
        return

    text = f"📦 *Всего ключей:* {len(res.data)}\n\n"
    for k in res.data[:20]:
        status = "✅" if k.get("used", 0) == 0 else "❌"
        game = escape_md(k.get("game", "all"))
        text += f"{status} `{k['license_key']}` — {k['user_id']} ({game}) до {k.get('expires_at', '∞')}\n"
    if len(res.data) > 20:
        text += f"\n...и ещё {len(res.data) - 20}"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    earnings = get_total_earnings()
    active = len(get_active_users())
    total_payments = get_total_payments()
    await callback.message.edit_text(
        f"💰 *Статистика*\n\n"
        f"📊 Активных подписок: *{active}*\n"
        f"⭐ Заработано звёзд: *{earnings}*\n"
        f"💳 Всего покупок: *{total_payments}*",
        parse_mode="Markdown",
        reply_markup=back_button(),
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_add")
async def admin_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("➕ Введи ID для добавления в админы:", reply_markup=back_button())
    await state.set_state(States.admin_add)
    await callback.answer()


@dp.message(States.admin_add)
async def process_admin_add(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный ID! Введи число.")
        return
    try:
        existing = supabase.table("admins").select("*").eq("user_id", user_id).execute()
        if existing.data:
            await message.answer(f"ℹ️ {user_id} уже админ!", reply_markup=main_menu(message.from_user.id))
        else:
            supabase.table("admins").insert({"user_id": user_id}).execute()
            await message.answer(f"✅ Админ {user_id} добавлен!", reply_markup=main_menu(message.from_user.id))
    except Exception:
        logger.exception("Ошибка добавления админа")
        await message.answer("⚠️ Ошибка сервера.")
    await state.clear()


@dp.callback_query(F.data == "admin_remove")
async def admin_remove(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("➖ Введи ID для удаления из админов:", reply_markup=back_button())
    await state.set_state(States.admin_remove)
    await callback.answer()


@dp.message(States.admin_remove)
async def process_admin_remove(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный ID! Введи число.")
        return
    try:
        supabase.table("admins").delete().eq("user_id", user_id).execute()
        await message.answer(f"✅ Админ {user_id} удалён!", reply_markup=main_menu(message.from_user.id))
    except Exception:
        logger.exception("Ошибка удаления админа")
        await message.answer("⚠️ Ошибка сервера.")
    await state.clear()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    users = get_active_users()
    text = f"📋 *Всего активных:* {len(users)}\n\n"
    for uid, end in users[:20]:
        text += f"👤 `{uid}` — до {end}\n"
    if len(users) > 20:
        text += f"\n...и ещё {len(users) - 20}"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()


@dp.callback_query(F.data == "admin_give")
async def admin_give(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🎁 Введи ID и дни (формат: ID, 30):", reply_markup=back_button())
    await state.set_state(States.admin_give)
    await callback.answer()


@dp.message(States.admin_give)
async def process_admin_give(message: types.Message, state: FSMContext):
    try:
        user_id, days = split_id_days(message.text)
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Формат: ID, 30 (дни — положительное число)")
        return

    if activate_subscription(user_id, days):
        await message.answer(f"✅ Пользователю {user_id} выдано {days} дней!", reply_markup=main_menu(message.from_user.id))
    else:
        await message.answer("⚠️ Ошибка сервера при выдаче подписки.")
    await state.clear()


@dp.callback_query(F.data == "admin_ban")
async def admin_ban(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🔨 Введи ID для бана:", reply_markup=back_button())
    await state.set_state(States.admin_ban)
    await callback.answer()


@dp.message(States.admin_ban)
async def process_admin_ban(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный ID! Введи число.")
        return
    try:
        existing = _safe_select("users", user_id)
        if existing:
            supabase.table("users").update({"banned": 1}).eq("user_id", user_id).execute()
        else:
            supabase.table("users").insert({"user_id": user_id, "banned": 1}).execute()
        await message.answer(f"✅ Пользователь {user_id} забанен!", reply_markup=main_menu(message.from_user.id))
    except Exception:
        logger.exception("Ошибка бана пользователя")
        await message.answer("⚠️ Ошибка сервера.")
    await state.clear()


@dp.callback_query(F.data == "admin_unban")
async def admin_unban(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🔓 Введи ID для разбана:", reply_markup=back_button())
    await state.set_state(States.admin_unban)
    await callback.answer()


@dp.message(States.admin_unban)
async def process_admin_unban(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный ID! Введи число.")
        return
    try:
        existing = _safe_select("users", user_id)
        if existing:
            supabase.table("users").update({"banned": 0}).eq("user_id", user_id).execute()
        else:
            supabase.table("users").insert({"user_id": user_id, "banned": 0}).execute()
        await message.answer(f"✅ Пользователь {user_id} разбанен!", reply_markup=main_menu(message.from_user.id))
    except Exception:
        logger.exception("Ошибка разбана пользователя")
        await message.answer("⚠️ Ошибка сервера.")
    await state.clear()


@dp.callback_query(F.data == "banned")
async def banned(callback: CallbackQuery):
    await callback.answer("⛔ Ты забанен!", show_alert=True)


@dp.message(Command("check"))
async def check_key(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Введи ключ: /check КЛЮЧ")
        return

    key = args[1]
    try:
        res = supabase.table("keys").select("*").eq("license_key", key).execute()
    except Exception:
        logger.exception("Ошибка проверки ключа /check")
        await message.answer("⚠️ Ошибка сервера, попробуй позже.")
        return

    if not res.data:
        await message.answer("❌ Неверный ключ!")
        return

    key_data = res.data[0]
    if key_data.get("used", 0) == 1:
        await message.answer("❌ Ключ уже использован!")
        return

    expires = key_data.get("expires_at")
    if expires and expires < datetime.now().strftime("%Y-%m-%d"):
        await message.answer("❌ Ключ истёк!")
        return

    await message.answer(
        f"✅ Ключ валидный!\n"
        f"👤 Пользователь: {key_data['user_id']}\n"
        f"🎮 Игра: {key_data.get('game', 'all')}\n"
        f"📅 Действителен до: {expires}"
    )


# ── Глобальный обработчик ошибок ───────────────────────────────────────────
# Перехватывает ЛЮБОЕ необработанное исключение в хендлерах, логирует его
# и (если возможно) сообщает пользователю, что что-то пошло не так,
# вместо того чтобы кнопка просто "висела" без ответа.

@dp.errors()
async def global_error_handler(event: ErrorEvent):
    logger.exception("Необработанная ошибка в хендлере: %s", event.exception)
    try:
        update = event.update
        if update.callback_query:
            await update.callback_query.answer("⚠️ Произошла ошибка, попробуй ещё раз", show_alert=True)
        elif update.message:
            await update.message.answer("⚠️ Произошла ошибка, попробуй ещё раз позже.")
    except Exception:
        logger.exception("Не удалось уведомить пользователя об ошибке")
    return True


async def main():
    logger.info("🚀 Бот запущен с Supabase...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
