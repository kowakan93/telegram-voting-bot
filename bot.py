import logging
import json
import os
from datetime import datetime
from typing import Dict, Set, List, Tuple
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, Update, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Эмодзи для кнопок
EMOJI_YES = "👍"
EMOJI_NO = "❌"
EMOJI_RESERVE = "✍️"
EMOJI_YES_PLUS = "👥"
EMOJI_CHICKEN = "🐔"
EMOJI_STATS = "📊"
EMOJI_SHARE = "🔗"
EMOJI_RESULTS = "📈"
EMOJI_FINISH = "🏁"


class VotingSystem:
    def __init__(self):
        self.active_poll = False
        self.poll_title = ""
        self.votes = {
            "yes": {},  # {user_id: (user_name, guest_count, timestamp)}
            "no": {},  # {user_id: (user_name, 0, timestamp)}
            "reserve": {},  # {user_id: (user_name, 0, timestamp)}
        }
        self.vote_history = {}  # {user_id: previous_vote}
        self.chicken_coop_stats = {}  # {user_id: count}
        self.current_chicken_coop = set()  # user_ids in current chicken coop
        self.message_id = None
        self.chat_id = None
        self.waiting_for_guests = {}  # {user_id: message_id}

    def reset(self):
        self.active_poll = False
        self.poll_title = ""
        self.votes = {"yes": {}, "no": {}, "reserve": {}}
        self.vote_history = {}
        self.current_chicken_coop = set()
        self.message_id = None
        self.chat_id = None
        self.waiting_for_guests = {}


voting_system = VotingSystem()


def get_user_display_name(user) -> str:
    """Получить отображаемое имя пользователя без @"""
    if user.username:
        return f"@{user.username}" if not user.username.startswith('@') else user.username
    elif user.first_name:
        return user.first_name + (f" {user.last_name}" if user.last_name else "")
    else:
        return "Аноним"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start"""
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI_YES} Создать голосование", callback_data="create_poll")],
        [InlineKeyboardButton(f"{EMOJI_RESULTS} Результаты", callback_data="show_results")],
        [InlineKeyboardButton(f"{EMOJI_STATS} Статистика курятника", callback_data="show_stats")],
        [InlineKeyboardButton(f"{EMOJI_SHARE} Поделиться", callback_data="share_results")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Добро пожаловать в систему голосования! 🗳️\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )


async def create_poll_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начало создания голосования"""
    query = update.callback_query
    await query.answer()

    if voting_system.active_poll:
        await query.edit_message_text(
            "Голосование уже активно! Используйте кнопку 'Результаты' для просмотра."
        )
        return

    await query.edit_message_text(
        "Введите заголовок для голосования:"
    )
    context.user_data['waiting_for_title'] = True


async def receive_poll_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Получение заголовка голосования"""
    if context.user_data.get('waiting_for_title'):
        title = update.message.text
        voting_system.poll_title = title
        voting_system.active_poll = True
        voting_system.chat_id = update.effective_chat.id
        context.user_data['waiting_for_title'] = False

        # Создаем сообщение с голосованием
        message = await send_poll_message(update, context)
        voting_system.message_id = message.message_id

        # Оповещаем всех участников с тегом
        await notify_all_participants(update, context, title)


async def send_poll_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка сообщения с голосованием"""
    poll_text = format_poll_with_results()

    keyboard = [
        [
            InlineKeyboardButton(f"{EMOJI_YES} Буду", callback_data="vote_yes"),
            InlineKeyboardButton(f"{EMOJI_NO} Не буду", callback_data="vote_no")
        ],
        [
            InlineKeyboardButton(f"{EMOJI_RESERVE} Резерв", callback_data="vote_reserve"),
            InlineKeyboardButton(f"{EMOJI_YES_PLUS} Буду с гостями", callback_data="add_guests")
        ],
        [
            InlineKeyboardButton(f"{EMOJI_RESULTS} Результаты", callback_data="show_results"),
            InlineKeyboardButton(f"{EMOJI_STATS} Статистика", callback_data="show_stats")
        ],
        [
            InlineKeyboardButton(f"{EMOJI_SHARE} Поделиться", callback_data="share_results"),
            InlineKeyboardButton(f"{EMOJI_FINISH} Завершить", callback_data="finish_poll")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        return await update.callback_query.edit_message_text(
            poll_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        return await update.message.reply_text(
            poll_text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )


def format_poll_with_results() -> str:
    """Форматирование сообщения голосования с результатами"""
    if not voting_system.active_poll:
        return "🗳️ <b>Голосование завершено</b>"

    results = []
    results.append(f"🗳️ <b>{voting_system.poll_title}</b>\n")

    # Объединенный список "Буду" (с гостями) - сортировка по времени
    if voting_system.votes["yes"]:
        results.append(f"\n<b>{EMOJI_YES} Буду:</b>")
        # Сортируем по timestamp (первые - кто раньше нажал)
        sorted_yes = sorted(
            voting_system.votes["yes"].items(),
            key=lambda x: x[1][2]  # timestamp находится по индексу 2
        )

        for user_id, (user_name, guest_count, timestamp) in sorted_yes:
            if guest_count > 0:
                results.append(f"  • {user_name} (+{guest_count})")
            else:
                results.append(f"  • {user_name}")
    else:
        results.append(f"\n<b>{EMOJI_YES} Буду:</b> нет участников")

    # Не буду
    if voting_system.votes["no"]:
        results.append(f"\n<b>{EMOJI_NO} Не буду:</b>")
        for user_id, (user_name, count, timestamp) in voting_system.votes["no"].items():
            results.append(f"  • {user_name}")
    else:
        results.append(f"\n<b>{EMOJI_NO} Не буду:</b> нет участников")

    # Резерв
    if voting_system.votes["reserve"]:
        results.append(f"\n<b>{EMOJI_RESERVE} Резерв:</b>")
        for user_id, (user_name, count, timestamp) in voting_system.votes["reserve"].items():
            results.append(f"  • {user_name}")
    else:
        results.append(f"\n<b>{EMOJI_RESERVE} Резерв:</b> нет участников")

    # Курятник
    if voting_system.current_chicken_coop:
        results.append(f"\n<b>{EMOJI_CHICKEN} Курятник:</b>")
        for user_id in voting_system.current_chicken_coop:
            user_name = "Неизвестный"
            # Ищем имя пользователя в истории голосований
            for vote_type in voting_system.votes:
                if user_id in voting_system.votes[vote_type]:
                    user_name = voting_system.votes[vote_type][user_id][0]
                    break
            results.append(f"  • {user_name}")

    # Статистика - ПРАВИЛЬНЫЙ подсчет
    total_participants_yes = len(voting_system.votes["yes"])  # количество участников "Буду"
    total_guests = sum(guest_count for _, guest_count, _ in voting_system.votes["yes"].values())  # сумма гостей
    total_yes_with_guests = total_participants_yes + total_guests  # участники + гости
    total_no = len(voting_system.votes["no"])
    total_reserve = len(voting_system.votes["reserve"])
    total_participants = total_participants_yes + total_no + total_reserve  # только участники чата

    results.append(f"\n<b>Итого:</b>")
    if total_guests > 0:
        results.append(f"✅ Будут: {total_participants_yes} чел. (+{total_guests})")
    else:
        results.append(f"✅ Будут: {total_participants_yes} чел.")
    results.append(f"❌ Не будут: {total_no} чел.")
    results.append(f"✍️ Резерв: {total_reserve} чел.")
    results.append(f"📊 Всего участников: {total_yes_with_guests} чел.")

    return "\n".join(results)


async def notify_all_participants(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str):
    """Оповещение всех участников о создании голосования с тегом"""
    try:
        # Получаем информацию о чате
        chat = await context.bot.get_chat(update.effective_chat.id)

        # Формируем текст уведомления с тегом всех участников
        notification_text = (
            f"🚀 <b>Создано новое голосование!</b>\n\n"
            f"<b>Тема:</b> {title}\n\n"
            f"Примите участие в голосовании! 🗳️"
        )

        # Отправляем уведомление с тегом всех участников
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=notification_text,
            parse_mode='HTML'
        )

    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления: {e}")
        # Если не удалось отправить с тегом, отправляем обычное уведомление
        notification_text = (
            f"🚀 <b>Создано новое голосование!</b>\n\n"
            f"<b>Тема:</b> {title}\n\n"
            f"Все участники чата приглашаются к голосованию! 🗳️"
        )

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=notification_text,
            parse_mode='HTML'
        )


async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосования"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = str(user.id)
    user_name = get_user_display_name(user)
    vote_type = query.data.replace("vote_", "")
    timestamp = datetime.now()

    previous_vote = voting_system.vote_history.get(user_id)

    # Проверка перехода из "Буду" в "Не буду" (попадание в курятник)
    if previous_vote == "yes" and vote_type == "no":
        voting_system.current_chicken_coop.add(user_id)
        voting_system.chicken_coop_stats[user_id] = voting_system.chicken_coop_stats.get(user_id, 0) + 1
        await notify_chicken_coop(update, context, user_name)

    # Удаляем предыдущий голос
    for vote_key in voting_system.votes:
        if user_id in voting_system.votes[vote_key]:
            del voting_system.votes[vote_key][user_id]
            break

    # Добавляем новый голос (по умолчанию 0 гостей)
    voting_system.votes[vote_type][user_id] = (user_name, 0, timestamp)
    voting_system.vote_history[user_id] = vote_type

    # Обновляем сообщение с голосованием и результатами
    await update_poll_message(update, context)


async def add_guests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатия кнопки 'Буду с гостями'"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = str(user.id)
    user_name = get_user_display_name(user)
    timestamp = datetime.now()

    # Удаляем предыдущий голос
    for vote_key in voting_system.votes:
        if user_id in voting_system.votes[vote_key]:
            del voting_system.votes[vote_key][user_id]
            break

    # Добавляем пользователя в "Буду" с 0 гостями (пока)
    voting_system.votes["yes"][user_id] = (user_name, 0, timestamp)
    voting_system.vote_history[user_id] = "yes"

    # Сохраняем ID сообщения для ожидания ввода гостей
    voting_system.waiting_for_guests[user_id] = query.message.message_id

    # Запрашиваем количество гостей в ЛИЧНОМ сообщении
    await context.bot.send_message(
        chat_id=user_id,
        text=f"👥 <b>Добавление гостей</b>\n\n"
             f"Пользователь: {user_name}\n"
             f"Введите количество гостей (только цифру):\n\n"
             f"<i>Это сообщение видно только вам</i>",
        parse_mode='HTML'
    )

    # Возвращаем основное сообщение голосования к исходному состоянию
    await update_poll_message(update, context)


async def handle_guests_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода количества гостей"""
    user_id = str(update.effective_user.id)

    # Проверяем, ожидаем ли мы ввод гостей от этого пользователя
    if user_id not in voting_system.waiting_for_guests:
        # Игнорируем сообщение, если это не ввод гостей
        return

    try:
        guest_count = int(update.message.text.strip())
        if guest_count < 0:
            await update.message.reply_text("Пожалуйста, введите положительное число или 0")
            return

        # Обновляем количество гостей для пользователя
        if user_id in voting_system.votes["yes"]:
            user_name, _, timestamp = voting_system.votes["yes"][user_id]
            voting_system.votes["yes"][user_id] = (user_name, guest_count, timestamp)

        # Удаляем из ожидания
        del voting_system.waiting_for_guests[user_id]

        # Подтверждаем ввод гостей в личном сообщении
        await update.message.reply_text(
            f"✅ <b>Гости добавлены!</b>\n\n"
            f"Количество гостей: {guest_count}\n"
            f"Результаты обновлены в основном голосовании.",
            parse_mode='HTML'
        )

        # Обновляем основное сообщение голосования
        if voting_system.message_id and voting_system.chat_id:
            poll_text = format_poll_with_results()

            keyboard = [
                [
                    InlineKeyboardButton(f"{EMOJI_YES} Буду", callback_data="vote_yes"),
                    InlineKeyboardButton(f"{EMOJI_NO} Не буду", callback_data="vote_no")
                ],
                [
                    InlineKeyboardButton(f"{EMOJI_RESERVE} Резерв", callback_data="vote_reserve"),
                    InlineKeyboardButton(f"{EMOJI_YES_PLUS} Буду с гостями", callback_data="add_guests")
                ],
                [
                    InlineKeyboardButton(f"{EMOJI_RESULTS} Результаты", callback_data="show_results"),
                    InlineKeyboardButton(f"{EMOJI_STATS} Статистика", callback_data="show_stats")
                ],
                [
                    InlineKeyboardButton(f"{EMOJI_SHARE} Поделиться", callback_data="share_results"),
                    InlineKeyboardButton(f"{EMOJI_FINISH} Завершить", callback_data="finish_poll")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.edit_message_text(
                chat_id=voting_system.chat_id,
                message_id=voting_system.message_id,
                text=poll_text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите только цифру (например: 2)")


async def notify_chicken_coop(update: Update, context: ContextTypes.DEFAULT_TYPE, user_name: str):
    """Оповещение о попадании в курятник"""
    notification_text = (
        f"🐔 <b>ВНИМАНИЕ!</b> 🐔\n\n"
        f"Пользователь <b>{user_name}</b> перешел из 'Буду' в 'Не буду' и попадает в КУРЯТНИК! 🏠"
    )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=notification_text,
        parse_mode='HTML'
    )


async def update_poll_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновление сообщения с голосованием"""
    poll_text = format_poll_with_results()

    keyboard = [
        [
            InlineKeyboardButton(f"{EMOJI_YES} Буду", callback_data="vote_yes"),
            InlineKeyboardButton(f"{EMOJI_NO} Не буду", callback_data="vote_no")
        ],
        [
            InlineKeyboardButton(f"{EMOJI_RESERVE} Резерв", callback_data="vote_reserve"),
            InlineKeyboardButton(f"{EMOJI_YES_PLUS} Буду с гостями", callback_data="add_guests")
        ],
        [
            InlineKeyboardButton(f"{EMOJI_RESULTS} Результаты", callback_data="show_results"),
            InlineKeyboardButton(f"{EMOJI_STATS} Статистика", callback_data="show_stats")
        ],
        [
            InlineKeyboardButton(f"{EMOJI_SHARE} Поделиться", callback_data="share_results"),
            InlineKeyboardButton(f"{EMOJI_FINISH} Завершить", callback_data="finish_poll")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        poll_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать результаты голосования"""
    query = update.callback_query
    await query.answer()

    if not voting_system.active_poll:
        await query.edit_message_text("Активного голосования нет!")
        return

    results_text = format_results()

    keyboard = [
        [InlineKeyboardButton("↩️ Назад к голосованию", callback_data="back_to_poll")],
        [InlineKeyboardButton(f"{EMOJI_SHARE} Поделиться", callback_data="share_results")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        results_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


def format_results() -> str:
    """Форматирование результатов голосования"""
    results = []
    results.append(f"📊 <b>Результаты голосования:</b>")
    results.append(f"<b>{voting_system.poll_title}</b>\n")

    # Объединенный список "Буду" (с гостями) - сортировка по времени
    if voting_system.votes["yes"]:
        results.append(f"<b>{EMOJI_YES} Буду:</b>")
        # Сортируем по timestamp (первые - кто раньше нажал)
        sorted_yes = sorted(
            voting_system.votes["yes"].items(),
            key=lambda x: x[1][2]  # timestamp находится по индексу 2
        )

        for user_id, (user_name, guest_count, timestamp) in sorted_yes:
            if guest_count > 0:
                results.append(f"  • {user_name} (+{guest_count})")
            else:
                results.append(f"  • {user_name}")
    else:
        results.append(f"<b>{EMOJI_YES} Буду:</b> нет участников")

    # Не буду
    if voting_system.votes["no"]:
        results.append(f"\n<b>{EMOJI_NO} Не буду:</b>")
        for user_id, (user_name, count, timestamp) in voting_system.votes["no"].items():
            results.append(f"  • {user_name}")
    else:
        results.append(f"\n<b>{EMOJI_NO} Не буду:</b> нет участников")

    # Резерв
    if voting_system.votes["reserve"]:
        results.append(f"\n<b>{EMOJI_RESERVE} Резерв:</b>")
        for user_id, (user_name, count, timestamp) in voting_system.votes["reserve"].items():
            results.append(f"  • {user_name}")
    else:
        results.append(f"\n<b>{EMOJI_RESERVE} Резерв:</b> нет участников")

    # Курятник
    if voting_system.current_chicken_coop:
        results.append(f"\n<b>{EMOJI_CHICKEN} Курятник:</b>")
        for user_id in voting_system.current_chicken_coop:
            user_name = "Неизвестный"
            # Ищем имя пользователя в истории голосований
            for vote_type in voting_system.votes:
                if user_id in voting_system.votes[vote_type]:
                    user_name = voting_system.votes[vote_type][user_id][0]
                    break
            results.append(f"  • {user_name}")
    else:
        results.append(f"\n<b>{EMOJI_CHICKEN} Курятник:</b> пусто")

    # Статистика - ПРАВИЛЬНЫЙ подсчет
    total_participants_yes = len(voting_system.votes["yes"])  # количество участников "Буду"
    total_guests = sum(guest_count for _, guest_count, _ in voting_system.votes["yes"].values())  # сумма гостей
    total_yes_with_guests = total_participants_yes + total_guests  # участники + гости
    total_no = len(voting_system.votes["no"])
    total_reserve = len(voting_system.votes["reserve"])
    total_participants = total_participants_yes + total_no + total_reserve  # только участники чата

    results.append(f"\n<b>Итого:</b>")
    if total_guests > 0:
        results.append(f"✅ Будут: {total_participants_yes} чел. (+{total_guests})")
    else:
        results.append(f"✅ Будут: {total_participants_yes} чел.")
    results.append(f"❌ Не будут: {total_no} чел.")
    results.append(f"✍️ Резерв: {total_reserve} чел.")
    results.append(f"📊 Всего участников: {total_yes_with_guests} чел.")

    return "\n".join(results)


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать статистику курятника"""
    query = update.callback_query
    await query.answer()

    if not voting_system.chicken_coop_stats:
        stats_text = "📊 <b>Статистика курятника</b>\n\nПока никто не попадал в курятник!"
    else:
        stats_text = "📊 <b>Статистика курятника за все время:</b>\n\n"
        sorted_stats = sorted(voting_system.chicken_coop_stats.items(),
                              key=lambda x: x[1], reverse=True)

        for user_id, count in sorted_stats:
            user_name = "Неизвестный"
            # Ищем актуальное имя пользователя
            for vote_type in voting_system.votes:
                if user_id in voting_system.votes[vote_type]:
                    user_name = voting_system.votes[vote_type][user_id][0]
                    break
            stats_text += f"• {user_name}: {count} раз\n"

    keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data="back_to_poll")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def share_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Поделиться результатами"""
    query = update.callback_query
    await query.answer()

    if not voting_system.active_poll:
        await query.edit_message_text("Нет активного голосования!")
        return

    results_text = format_results()
    share_text = f"🔗 <b>Результаты голосования:</b>\n\n{results_text}"

    await query.edit_message_text(
        share_text,
        parse_mode='HTML'
    )


async def finish_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Завершение голосования"""
    query = update.callback_query
    await query.answer()

    if not voting_system.active_poll:
        await query.edit_message_text("Нет активного голосования для завершения!")
        return

    # Сохраняем результаты перед сбросом
    final_results = format_results()

    # Сбрасываем систему голосования
    voting_system.reset()

    keyboard = [
        [InlineKeyboardButton(f"{EMOJI_YES} Создать новое голосование", callback_data="create_poll")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"🏁 <b>Голосование завершено!</b>\n\n{final_results}",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def back_to_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вернуться к голосованию"""
    query = update.callback_query
    await query.answer()

    await send_poll_message(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений"""
    user_id = str(update.effective_user.id)

    # Проверяем, ожидаем ли мы ввод заголовка
    if context.user_data.get('waiting_for_title'):
        await receive_poll_title(update, context)
    # Проверяем, ожидаем ли мы ввод количества гостей
    elif user_id in voting_system.waiting_for_guests:
        await handle_guests_input(update, context)
    # Игнорируем все остальные сообщения - позволяем участникам общаться свободно


def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))

    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(create_poll_start, pattern="^create_poll$"))
    application.add_handler(CallbackQueryHandler(show_results, pattern="^show_results$"))
    application.add_handler(CallbackQueryHandler(show_stats, pattern="^show_stats$"))
    application.add_handler(CallbackQueryHandler(share_results, pattern="^share_results$"))
    application.add_handler(CallbackQueryHandler(back_to_poll, pattern="^back_to_poll$"))
    application.add_handler(CallbackQueryHandler(finish_poll, pattern="^finish_poll$"))
    application.add_handler(CallbackQueryHandler(add_guests, pattern="^add_guests$"))
    application.add_handler(CallbackQueryHandler(handle_vote, pattern="^vote_"))

    # Обработчик текстовых сообщений - только для специфических случаев
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск бота
    application.run_polling()


if __name__ == "__main__":
    main()