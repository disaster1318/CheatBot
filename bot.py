import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client, Client

API_TOKEN = "8942639067:AAEMn3yJYwtCFHtcCKIsgk8mgSrsVcpkk9M"

SUPABASE_URL = "https://umjmcdvjdqlsjmphvsfc.supabase.co"
SUPABASE_KEY = "sb_publishable_4hpLHc_Wxl323Y5nGODAdQ_3vle6d2t"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

class States(StatesGroup):
    choosing_duration = State()
    custom_days = State()
    support_message = State()
    admin_add = State()
    admin_remove = State()
    admin_give = State()
    admin_ban = State()
    admin_unban = State()

def generate_license():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))

def main_menu(user_id):
    kb = []
    user = supabase.table("users").select("*").eq("user_id", user_id).execute()
    user_data = user.data[0] if user.data else {}
    
    if user_data.get("banned", 0) == 1:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⛔ Доступ заблокирован", callback_data="banned")]
        ])
    
    if is_subscribed(user_id):
        kb.append([InlineKeyboardButton(text="⬇️ Скачать чит", callback_data="download_cheat")])
        kb.append([InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile")])
        kb.append([InlineKeyboardButton(text="🔑 Мои ключи", callback_data="my_keys")])
    else:
        kb.append([InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_subscription")])
        kb.append([InlineKeyboardButton(text="👤 Мой профиль", callback_data="my_profile")])
    
    kb.append([InlineKeyboardButton(text="🔗 Реферальная система", callback_data="referral_system")])
    kb.append([InlineKeyboardButton(text="📢 Наш канал", callback_data="our_channel")])
    kb.append([InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")])
    
    admin_check = supabase.table("admins").select("*").eq("user_id", user_id).execute()
    if admin_check.data:
        kb.append([InlineKeyboardButton(text="⚙️ Админ меню", callback_data="admin_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def subscription_durations():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день — 50 ⭐", callback_data="sub_1")],
        [InlineKeyboardButton(text="7 дней — 100 ⭐", callback_data="sub_7")],
        [InlineKeyboardButton(text="30 дней — 250 ⭐", callback_data="sub_30")],
        [InlineKeyboardButton(text="365 дней — 500 ⭐", callback_data="sub_365")],
        [InlineKeyboardButton(text="✏️ Свои дни", callback_data="custom_days")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def cheat_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 PUBG", callback_data="cheat_pubg")],
        [InlineKeyboardButton(text="⚔️ Brawl Stars", callback_data="cheat_brawl")],
        [InlineKeyboardButton(text="🔫 Standoff 2", callback_data="cheat_standoff")],
        [InlineKeyboardButton(text="⚡ Mobile Legends", callback_data="cheat_ml")],
        [InlineKeyboardButton(text="🎮 Roblox", callback_data="cheat_roblox")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove")],
        [InlineKeyboardButton(text="📋 Все подписки", callback_data="admin_users")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_give")],
        [InlineKeyboardButton(text="🔨 Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🔓 Разбан", callback_data="admin_unban")],
        [InlineKeyboardButton(text="💰 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📦 Все ключи", callback_data="admin_keys")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def is_subscribed(user_id):
    user = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user.data:
        return False
    user_data = user.data[0]
    if user_data.get("banned", 0) == 1:
        return False
    end_date = user_data.get("end_date")
    if not end_date:
        return False
    try:
        return datetime.strptime(end_date, "%Y-%m-%d") > datetime.now()
    except:
        return False

def get_days_left(user_id):
    user = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user.data:
        return 0
    end_date = user.data[0].get("end_date")
    if not end_date:
        return 0
    try:
        delta = datetime.strptime(end_date, "%Y-%m-%d") - datetime.now()
        return max(delta.days, 0)
    except:
        return 0

def get_subscription_end(user_id):
    user = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user.data:
        return "Нет подписки"
    return user.data[0].get("end_date", "Нет подписки")

def activate_subscription(user_id, days):
    end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    existing = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if existing.data:
        supabase.table("users").update({"end_date": end_date}).eq("user_id", user_id).execute()
    else:
        supabase.table("users").insert({"user_id": user_id, "end_date": end_date}).execute()

def get_ref_by(user_id):
    user = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if not user.data:
        return None
    return user.data[0].get("ref_by")

def set_ref_by(user_id, ref_id):
    existing = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if existing.data:
        supabase.table("users").update({"ref_by": ref_id}).eq("user_id", user_id).execute()
    else:
        supabase.table("users").insert({"user_id": user_id, "ref_by": ref_id}).execute()

def get_total_earnings():
    res = supabase.table("payments").select("amount").execute()
    return sum(p.get("amount", 0) for p in res.data)

def get_total_payments():
    res = supabase.table("payments").select("id", count="exact").execute()
    return res.count

def get_active_users():
    now = datetime.now().strftime("%Y-%m-%d")
    res = supabase.table("users").select("user_id, end_date").eq("banned", 0).execute()
    active = []
    for u in res.data:
        if u.get("end_date") and u["end_date"] > now:
            active.append((u["user_id"], u["end_date"]))
    return active

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("REF"):
        ref_id = int(args[1][3:])
        if ref_id != message.from_user.id and not get_ref_by(message.from_user.id):
            set_ref_by(message.from_user.id, ref_id)
    
    await message.answer(
        "🔥 Добро пожаловать в магазин читов!\n\nВыбери действие:",
        reply_markup=main_menu(message.from_user.id)
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔥 Главное меню:",
        reply_markup=main_menu(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "my_profile")
async def my_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    days = get_days_left(user_id)
    end_date = get_subscription_end(user_id)
    ref_by = get_ref_by(user_id) or "Нет"
    total_payments = get_total_payments()
    
    text = (
        f"👤 *Твой профиль*\n\n"
        f"📅 Дней подписки: *{days}*\n"
        f"📆 Подписка до: *{end_date}*\n"
        f"🔗 Пригласил: *{ref_by}*\n"
        f"💰 Всего оплат в боте: *{total_payments}*"
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@dp.callback_query(F.data == "my_keys")
async def my_keys(callback: CallbackQuery):
    user_id = callback.from_user.id
    res = supabase.table("keys").select("*").eq("user_id", user_id).execute()
    
    if not res.data:
        await callback.message.edit_text(
            "🔑 *Твои ключи*\n\nУ тебя пока нет активных ключей.",
            parse_mode="Markdown",
            reply_markup=back_button()
        )
        await callback.answer()
        return
    
    text = "🔑 *Твои ключи*\n\n"
    for key in res.data:
        status = "✅ Активен" if key.get("used", 0) == 0 else "❌ Использован"
        text += f"`{key['license_key']}` — {status}\n"
        text += f"Действителен до: {key.get('expires_at', '∞')}\n\n"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

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
        reply_markup=back_button()
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_subscription")
async def buy_sub(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💎 *При покупке подписки*\nты получаешь доступ к 5+ читам!\n\nВыбери длительность:",
        parse_mode="Markdown",
        reply_markup=subscription_durations()
    )
    await state.set_state(States.choosing_duration)
    await callback.answer()

@dp.callback_query(F.data == "custom_days")
async def custom_days(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Введи количество дней:", reply_markup=back_button())
    await state.set_state(States.custom_days)
    await callback.answer()

@dp.message(States.custom_days)
async def process_custom_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text)
        if days <= 0:
            await message.answer("❌ Введи положительное число!")
            return
        price = days * 50
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="Подписка на читы",
            description=f"Доступ к читам на {days} дней",
            payload=f"sub_{days}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Подписка", amount=price*100)],
            start_parameter="sub"
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введи число!")

@dp.callback_query(F.data.startswith("sub_"))
async def process_sub(callback: CallbackQuery, state: FSMContext):
    days = int(callback.data.split("_")[1])
    prices_map = {1:50, 7:100, 30:250, 365:500}
    price = prices_map.get(days, 50)
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Подписка на читы",
        description=f"Доступ к читам на {days} дней",
        payload=f"sub_{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=price*100)],
        start_parameter="sub"
    )
    await state.clear()
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    days = int(message.successful_payment.invoice_payload.split("_")[1])
    amount = message.successful_payment.total_amount
    user_id = message.from_user.id
    
    # Активируем подписку
    activate_subscription(user_id, days)
    
    # Логируем оплату
    supabase.table("payments").insert({
        "user_id": user_id,
        "days": days,
        "amount": amount,
        "date": datetime.now().isoformat()
    }).execute()
    
    # Генерируем лицензионный ключ
    license_key = generate_license()
    expires_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    supabase.table("keys").insert({
        "user_id": user_id,
        "license_key": license_key,
        "game": "all",
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
        "used": 0
    }).execute()
    
    # Рефералка
    ref_by = get_ref_by(user_id)
    if ref_by:
        bonus_days = int(days * 0.4)
        if bonus_days > 0:
            activate_subscription(ref_by, bonus_days)
            try:
                await bot.send_message(ref_by, f"🎉 Твой реферал купил подписку! Ты получил +{bonus_days} дней!")
            except:
                pass
            supabase.table("users").update({"ref_by": None}).eq("user_id", user_id).execute()
    
    await message.answer(
        f"✅ Оплата прошла!\n"
        f"Подписка на *{days}* дней активирована!\n\n"
        f"🔑 *Твой лицензионный ключ:*\n"
        f"`{license_key}`\n\n"
        f"Используй его для активации софта.",
        parse_mode="Markdown",
        reply_markup=main_menu(message.from_user.id)
    )
    
    # Уведомление админам
    admins = supabase.table("admins").select("user_id").execute()
    for admin in admins.data:
        try:
            await bot.send_message(
                admin["user_id"],
                f"🛒 Юзер {message.from_user.first_name} (@{message.from_user.username})\n"
                f"купил подписку на {days} дней за {amount/100} ⭐!\n"
                f"🔑 Ключ: `{license_key}`",
                parse_mode="Markdown"
            )
        except:
            pass

@dp.callback_query(F.data == "download_cheat")
async def download_cheat(callback: CallbackQuery):
    if not is_subscribed(callback.from_user.id):
        await callback.message.answer("❌ Нет активной подписки!", reply_markup=back_button())
        await callback.answer()
        return
    await callback.message.edit_text(
        "*Выбери чит и доминируй в играх!*\nНе бойся играть — у нас читы не детектятся!",
        parse_mode="Markdown",
        reply_markup=cheat_menu()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("cheat_"))
async def send_cheat(callback: CallbackQuery):
    game = callback.data.split("_")[1]
    await callback.message.answer(f"📁 Файл чита для *{game.upper()}* скоро появится!", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🆘 Напиши свою проблему:", reply_markup=back_button())
    await state.set_state(States.support_message)
    await callback.answer()

@dp.message(States.support_message)
async def process_support(message: types.Message, state: FSMContext):
    admins = supabase.table("admins").select("user_id").execute()
    for admin in admins.data:
        try:
            await bot.send_message(
                admin["user_id"],
                f"🆘 *Новое обращение!*\n\n"
                f"От: {message.from_user.first_name} (@{message.from_user.username})\n"
                f"ID: `{message.from_user.id}`\n\n"
                f"Сообщение:\n{message.text}",
                parse_mode="Markdown"
            )
        except:
            pass
    await message.answer("✅ Отправлено админам!", reply_markup=main_menu(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ *Админ панель*",
        parse_mode="Markdown",
        reply_markup=admin_panel()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
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
        reply_markup=back_button()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_keys")
async def admin_keys(callback: CallbackQuery):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    res = supabase.table("keys").select("license_key, user_id, expires_at, used").execute()
    text = f"📦 *Всего ключей:* {len(res.data)}\n\n"
    for k in res.data[:20]:
        status = "✅" if k.get("used", 0) == 0 else "❌"
        text += f"{status} `{k['license_key']}` — {k['user_id']} до {k.get('expires_at', '∞')}\n"
    if len(res.data) > 20:
        text += f"\n...и ещё {len(res.data)-20}"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@dp.callback_query(F.data == "admin_add")
async def admin_add(callback: CallbackQuery, state: FSMContext):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("➕ Введи ID для добавления в админы:", reply_markup=back_button())
    await state.set_state(States.admin_add)
    await callback.answer()

@dp.message(States.admin_add)
async def process_admin_add(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        supabase.table("admins").insert({"user_id": user_id}).execute()
        await message.answer(f"✅ Админ {user_id} добавлен!", reply_markup=main_menu(message.from_user.id))
    except:
        await message.answer("❌ Неверный ID!")
    await state.clear()

@dp.callback_query(F.data == "admin_remove")
async def admin_remove(callback: CallbackQuery, state: FSMContext):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("➖ Введи ID для удаления из админов:", reply_markup=back_button())
    await state.set_state(States.admin_remove)
    await callback.answer()

@dp.message(States.admin_remove)
async def process_admin_remove(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        supabase.table("admins").delete().eq("user_id", user_id).execute()
        await message.answer(f"✅ Админ {user_id} удалён!", reply_markup=main_menu(message.from_user.id))
    except:
        await message.answer("❌ Неверный ID!")
    await state.clear()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    users = get_active_users()
    text = f"📋 *Всего активных:* {len(users)}\n\n"
    for uid, end in users[:20]:
        text += f"👤 `{uid}` — до {end}\n"
    if len(users) > 20:
        text += f"\n...и ещё {len(users)-20}"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_button())
    await callback.answer()

@dp.callback_query(F.data == "admin_give")
async def admin_give(callback: CallbackQuery, state: FSMContext):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🎁 Введи ID и дни (формат: ID 30):", reply_markup=back_button())
    await state.set_state(States.admin_give)
    await callback.answer()

@dp.message(States.admin_give)
async def process_admin_give(message: types.Message, state: FSMContext):
    try:
        parts = message.text.split()
        user_id = int(parts[0])
        days = int(parts[1])
        activate_subscription(user_id, days)
        # Генерируем ключ для пользователя
        license_key = generate_license()
        expires_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        supabase.table("keys").insert({
            "user_id": user_id,
            "license_key": license_key,
            "game": "all",
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at,
            "used": 0
        }).execute()
        await message.answer(
            f"✅ Пользователю {user_id} выдано {days} дней!\n"
            f"🔑 Ключ: `{license_key}`",
            parse_mode="Markdown",
            reply_markup=main_menu(message.from_user.id)
        )
    except:
        await message.answer("❌ Формат: ID 30")
    await state.clear()

@dp.callback_query(F.data == "admin_ban")
async def admin_ban(callback: CallbackQuery, state: FSMContext):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🔨 Введи ID для бана:", reply_markup=back_button())
    await state.set_state(States.admin_ban)
    await callback.answer()

@dp.message(States.admin_ban)
async def process_admin_ban(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        existing = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if existing.data:
            supabase.table("users").update({"banned": 1}).eq("user_id", user_id).execute()
        else:
            supabase.table("users").insert({"user_id": user_id, "banned": 1}).execute()
        await message.answer(f"✅ Пользователь {user_id} забанен!", reply_markup=main_menu(message.from_user.id))
    except:
        await message.answer("❌ Неверный ID!")
    await state.clear()

@dp.callback_query(F.data == "admin_unban")
async def admin_unban(callback: CallbackQuery, state: FSMContext):
    admin_check = supabase.table("admins").select("*").eq("user_id", callback.from_user.id).execute()
    if not admin_check.data:
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    await callback.message.edit_text("🔓 Введи ID для разбана:", reply_markup=back_button())
    await state.set_state(States.admin_unban)
    await callback.answer()

@dp.message(States.admin_unban)
async def process_admin_unban(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        existing = supabase.table("users").select("*").eq("user_id", user_id).execute()
        if existing.data:
            supabase.table("users").update({"banned": 0}).eq("user_id", user_id).execute()
        else:
            supabase.table("users").insert({"user_id": user_id, "banned": 0}).execute()
        await message.answer(f"✅ Пользователь {user_id} разбанен!", reply_markup=main_menu(message.from_user.id))
    except:
        await message.answer("❌ Неверный ID!")
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
    res = supabase.table("keys").select("*").eq("license_key", key).execute()
    
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
        f"Действителен до: {expires}\n"
        f"Игра: {key_data.get('game', 'all')}"
    )

async def main():
    print("🚀 Бот запущен с Supabase...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
