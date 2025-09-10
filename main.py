import os
import asyncio
import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import threading
import time
import queue
import requests
import random
import urllib3
from datetime import datetime
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', "7477086445:AAHpsBLrjc5v7qsJKR_TVdcWPgXwQcCwNTc")
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', "6731610123"))

# Database setup
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_date TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Store active tests and user states
active_tests = {}
user_states = {}

# Database functions
def add_user(user_id, username):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, added_date) VALUES (?, ?, ?)',
                  (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_user(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, added_date, is_active FROM users')
    users = cursor.fetchall()
    conn.close()
    return users

def is_user_allowed(user_id):
    if user_id == ADMIN_USER_ID:
        return True
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE user_id = ? AND is_active = 1', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user is not None

# Load testing functions
def validate_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def check_website_online(url, timeout=5):
    try:
        response = requests.get(url, timeout=timeout, verify=False)
        return response.status_code < 500
    except:
        return False

def generate_random_user_agent():
    browsers = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/92.0.4515.107',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    ]
    return random.choice(browsers)

def generate_request_headers():
    return {
        'User-Agent': generate_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
    }

def make_request(session, url, timeout, method='GET', data=None):
    headers = generate_request_headers()
    start_time = time.time()
    
    try:
        if method.upper() == 'POST':
            response = session.post(url, headers=headers, timeout=timeout, verify=False, data=data or {})
        else:
            response = session.get(url, headers=headers, timeout=timeout, verify=False)
        
        latency = time.time() - start_time
        return response.status_code, latency, None
        
    except requests.exceptions.Timeout:
        latency = time.time() - start_time
        return 'Timeout', latency, 'Request timed out'
    except requests.exceptions.ConnectionError:
        latency = time.time() - start_time
        return 'ConnectionError', latency, 'Connection error'
    except Exception as e:
        latency = time.time() - start_time
        return 'Error', latency, str(e)

def load_test_worker(target_url, requests_queue, results, timeout, method, data, delay):
    session = requests.Session()
    session.trust_env = False
    
    while not requests_queue.empty():
        try:
            request_id = requests_queue.get_nowait()
        except queue.Empty:
            break
            
        time.sleep(delay * random.uniform(0.8, 1.2))
        status_code, latency, error = make_request(session, target_url, timeout, method, data)
        
        with results['lock']:
            results['total_requests'] += 1
            results['latencies'].append(latency)
            
            if isinstance(status_code, int):
                if 200 <= status_code < 300:
                    results['success'] += 1
                elif 400 <= status_code < 500:
                    results['client_errors'] += 1
                elif 500 <= status_code < 600:
                    results['server_errors'] += 1
            else:
                results['errors'] += 1

def run_load_test(target_url, total_requests, concurrency, timeout=10, method='GET', data=None, delay=0):
    requests_queue = queue.Queue()
    for i in range(total_requests):
        requests_queue.put(i)
    
    results = {
        'lock': threading.Lock(),
        'total_requests': 0,
        'success': 0,
        'client_errors': 0,
        'server_errors': 0,
        'errors': 0,
        'latencies': [],
    }
    
    start_time = time.time()
    threads = []
    
    for i in range(concurrency):
        thread = threading.Thread(
            target=load_test_worker,
            args=(target_url, requests_queue, results, timeout, method, data, delay),
            daemon=True
        )
        thread.start()
        threads.append(thread)
    
    for thread in threads:
        thread.join()
    
    test_duration = time.time() - start_time
    return results, test_duration

def format_results(target_url, results, test_duration):
    total_requests = results['total_requests']
    if total_requests == 0:
        return "❌ No requests were completed."
    
    requests_per_second = total_requests / test_duration
    avg_latency = sum(results['latencies']) / len(results['latencies']) if results['latencies'] else 0
    success_rate = (results['success'] / total_requests) * 100 if total_requests > 0 else 0
    
    # Check website status after test
    is_online = check_website_online(target_url)
    status = "✅ ONLINE" if is_online else "❌ OFFLINE"
    
    return f"""
🚀 LOAD TEST COMPLETE

🔗 Target: {target_url}
⏱️ Duration: {test_duration:.2f}s
📊 Total Requests: {total_requests}
⚡ RPS: {requests_per_second:.2f}/s
✅ Success Rate: {success_rate:.2f}%

📈 Response Summary:
  ✅ 2xx Success: {results['success']}
  ⚠️ 4xx Client Errors: {results['client_errors']}
  ❌ 5xx Server Errors: {results['server_errors']}
  🔌 Network Errors: {results['errors']}

⏳ Latency Stats:
  📊 Average: {avg_latency:.3f}s

🌐 Website Status: {status}
"""

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("❌ You are not authorized. Contact admin.")
        return
    
    keyboard = [['🚀 Start Load Test'], ['👥 Admin Panel']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"👋 Welcome {username} to Load Testing Bot!",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("❌ Not authorized.")
        return
    
    if text == '🚀 Start Load Test':
        user_states[user_id] = 'awaiting_confirmation'
        await update.message.reply_text("⚠️ Type: I OWN THIS SITE")
    
    elif text == '👥 Admin Panel' and user_id == ADMIN_USER_ID:
        users = get_all_users()
        users_text = "📋 Users:\n"
        for user in users:
            users_text += f"👤 {user[0]} - {user[1]}\n"
        await update.message.reply_text(users_text)
    
    elif user_id in user_states:
        state = user_states[user_id]
        
        if state == 'awaiting_confirmation' and text.upper() == 'I OWN THIS SITE':
            user_states[user_id] = 'awaiting_url'
            await update.message.reply_text("🌐 Enter target URL:")
        
        elif state == 'awaiting_url' and validate_url(text):
            context.user_data['target_url'] = text
            user_states[user_id] = 'awaiting_requests'
            await update.message.reply_text("📊 Enter total requests (default 1000):")
        
        elif state == 'awaiting_requests':
            try:
                total_requests = int(text) if text else 1000
                context.user_data['total_requests'] = total_requests
                user_states[user_id] = 'awaiting_concurrency'
                await update.message.reply_text("🧵 Enter concurrency (default 50):")
            except:
                await update.message.reply_text("❌ Enter valid number:")
        
        elif state == 'awaiting_concurrency':
            try:
                concurrency = int(text) if text else 50
                context.user_data['concurrency'] = concurrency
                await start_load_test(update, context)
            except:
                await update.message.reply_text("❌ Enter valid number:")

async def start_load_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = context.user_data
    status_message = await update.message.reply_text("🚀 Starting test...")
    
    def run_test():
        try:
            results, duration = run_load_test(
                config['target_url'],
                config['total_requests'],
                config['concurrency']
            )
            result_text = format_results(config['target_url'], results, duration)
            
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text=result_text
                ),
                asyncio.get_event_loop()
            )
        except Exception as e:
            error_text = f"❌ Error: {str(e)}"
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status_message.message_id,
                    text=error_text
                ),
                asyncio.get_event_loop()
            )
        finally:
            if update.effective_user.id in user_states:
                del user_states[update.effective_user.id]
            context.user_data.clear()
    
    threading.Thread(target=run_test, daemon=True).start()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    print("🤖 Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
