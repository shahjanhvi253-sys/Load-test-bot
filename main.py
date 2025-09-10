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
import math

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
live_stats = {}  # For real-time statistics

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

# Enhanced Load testing functions
def validate_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def check_website_online(url, timeout=5):
    """Check if website is online with detailed info"""
    try:
        start_time = time.time()
        response = requests.get(url, timeout=timeout, verify=False, 
                               headers={'User-Agent': 'Mozilla/5.0 (Load-Test-Bot)'})
        response_time = time.time() - start_time
        
        return {
            'online': response.status_code < 500,
            'status_code': response.status_code,
            'response_time': response_time,
            'message': f'✅ ONLINE - {response.status_code} ({response_time:.2f}s)'
            if response.status_code < 500 else 
            f'❌ OFFLINE - {response.status_code}'
        }
    except Exception as e:
        return {
            'online': False,
            'status_code': 'Error',
            'response_time': 0,
            'message': f'❌ ERROR - {str(e)}'
        }

def generate_random_user_agent():
    browsers = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    ]
    return random.choice(browsers)

def generate_request_headers():
    return {
        'User-Agent': generate_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
        'DNT': random.choice(['1', '0']),
    }

def make_request(session, url, timeout, method='GET', data=None):
    headers = generate_request_headers()
    start_time = time.time()
    
    try:
        if method.upper() == 'POST':
            response = session.post(url, headers=headers, timeout=timeout, 
                                   verify=False, data=data or {}, allow_redirects=True)
        else:
            response = session.get(url, headers=headers, timeout=timeout, 
                                  verify=False, allow_redirects=True)
        
        latency = time.time() - start_time
        return response.status_code, latency, None
        
    except requests.exceptions.Timeout:
        latency = time.time() - start_time
        return 'Timeout', latency, 'Request timed out'
    except requests.exceptions.ConnectionError:
        latency = time.time() - start_time
        return 'ConnectionError', latency, 'Connection error'
    except requests.exceptions.RequestException as e:
        latency = time.time() - start_time
        return 'Error', latency, str(e)
    except Exception as e:
        latency = time.time() - start_time
        return 'Exception', latency, str(e)

def load_test_worker(worker_id, target_url, requests_queue, results, 
                    timeout, method, data, delay, user_id, message_id, context):
    session = requests.Session()
    session.trust_env = False
    
    # Enhanced connection settings for maximum performance
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=200,
        pool_maxsize=200,
        max_retries=0,
        pool_block=False
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    last_update_time = time.time()
    
    while not requests_queue.empty():
        try:
            request_id = requests_queue.get_nowait()
        except queue.Empty:
            break
            
        # Random delay for more realistic traffic
        time.sleep(delay * random.uniform(0.5, 1.5))
        
        status_code, latency, error = make_request(session, target_url, timeout, method, data)
        
        with results['lock']:
            results['total_requests'] += 1
            results['latencies'].append(latency)
            
            if isinstance(status_code, int):
                if 100 <= status_code < 200:
                    results['informational'] += 1
                elif 200 <= status_code < 300:
                    results['success'] += 1
                elif 300 <= status_code < 400:
                    results['redirection'] += 1
                elif 400 <= status_code < 500:
                    results['client_errors'] += 1
                elif 500 <= status_code < 600:
                    results['server_errors'] += 1
            else:
                results['errors'] += 1
            
            # Live stats update every 30 seconds
            current_time = time.time()
            if current_time - last_update_time >= 30:
                try:
                    progress = (results['total_requests'] / results['total_to_process']) * 100
                    stats_text = f"📊 Live Stats:\n\n"
                    stats_text += f"✅ Successful: {results['success']}\n"
                    stats_text += f"⚠️ Client Errors: {results['client_errors']}\n"
                    stats_text += f"❌ Server Errors: {results['server_errors']}\n"
                    stats_text += f"🔌 Network Errors: {results['errors']}\n"
                    stats_text += f"📈 Progress: {progress:.1f}%\n"
                    stats_text += f"⏰ Elapsed: {int(current_time - results['start_time'])}s"
                    
                    asyncio.run_coroutine_threadsafe(
                        context.bot.edit_message_text(
                            chat_id=user_id,
                            message_id=message_id,
                            text=stats_text
                        ),
                        asyncio.get_event_loop()
                    )
                    last_update_time = current_time
                except:
                    pass
        
        requests_queue.task_done()

def run_load_test(target_url, total_requests, concurrency, timeout=10, 
                 method='GET', data=None, delay=0, user_id=None, message_id=None, context=None):
    requests_queue = queue.Queue()
    for i in range(total_requests):
        requests_queue.put(i)
    
    results = {
        'lock': threading.Lock(),
        'total_requests': 0,
        'total_to_process': total_requests,
        'success': 0,
        'redirection': 0,
        'client_errors': 0,
        'server_errors': 0,
        'informational': 0,
        'errors': 0,
        'latencies': [],
        'start_time': time.time()
    }
    
    start_time = time.time()
    
    threads = []
    for i in range(concurrency):
        thread = threading.Thread(
            target=load_test_worker,
            args=(i+1, target_url, requests_queue, results, timeout, method, data, delay, 
                 user_id, message_id, context),
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
    sorted_latencies = sorted(results['latencies'])
    
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0
    p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)] if sorted_latencies else 0
    max_latency = max(results['latencies']) if results['latencies'] else 0
    
    success_rate = ((results['success'] + results['redirection']) / total_requests) * 100 if total_requests > 0 else 0
    
    # Check website status after test
    status_info = check_website_online(target_url)
    
    result_text = f"""
🚀 *LOAD TEST COMPLETE*

🔗 *Target:* {target_url}
⏱️ *Duration:* {test_duration:.2f}s
📊 *Total Requests:* {total_requests}
⚡ *RPS:* {requests_per_second:.2f}/s
✅ *Success Rate:* {success_rate:.2f}%

📈 *Response Summary:*
  ✅ 2xx Success: {results['success']}
  🔄 3xx Redirect: {results['redirection']}
  ⚠️ 4xx Client Errors: {results['client_errors']}
  ❌ 5xx Server Errors: {results['server_errors']}
  🔌 Network Errors: {results['errors']}

⏳ *Latency Stats:*
  📊 Average: {avg_latency:.3f}s
  📈 95th %ile: {p95:.3f}s
  📉 99th %ile: {p99:.3f}s
  📌 Max: {max_latency:.3f}s

🌐 *Website Status:*
  {status_info['message']}
"""

    # Performance rating
    if requests_per_second > 1000:
        rating = "🏆 EXCELLENT - Enterprise Grade"
    elif requests_per_second > 500:
        rating = "⭐ VERY GOOD - High Performance"
    elif requests_per_second > 100:
        rating = "👍 GOOD - Standard Production"
    elif requests_per_second > 50:
        rating = "📊 AVERAGE - Basic Hosting"
    elif requests_per_second > 10:
        rating = "📉 BELOW AVERAGE"
    else:
        rating = "❌ POOR - Underpowered"
    
    result_text += f"\n🏅 *Performance Rating:* {rating}"
    
    # Recommendations
    if results['server_errors'] > total_requests * 0.1:
        result_text += "\n\n❌ *WARNING:* High server errors - Server may be overloaded"
    if avg_latency > 2:
        result_text += "\n\n⚠️ *NOTE:* High latency - Optimize server/application"
    if success_rate < 90:
        result_text += "\n\n⚠️ *NOTE:* Low success rate - Website struggling with load"
    
    return result_text

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot. Contact the administrator.")
        return
    
    keyboard = [['🚀 Start Load Test', '📊 My Tests'], ['👥 Admin Panel']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"👋 Welcome *{username}* to the Ultimate Load Testing Bot!\n\n"
        "Use this tool responsibly and only on websites you own or have permission to test.\n\n"
        "Select an option below:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if not is_user_allowed(user_id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    
    if text == '🚀 Start Load Test':
        user_states[user_id] = 'awaiting_confirmation'
        await update.message.reply_text(
            "⚠️ *WARNING:* This is a powerful load testing tool.\n\n"
            "Use it only on websites you own or have explicit permission to test.\n\n"
            "To proceed, type: *I OWN THIS SITE*",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
    
    elif text == '📊 My Tests':
        await update.message.reply_text("📊 Feature coming soon!")
    
    elif text == '👥 Admin Panel' and user_id == ADMIN_USER_ID:
        keyboard = [['➕ Add User', '➖ Remove User'], ['📋 List Users', '🔙 Back']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "👨‍💼 *Admin Panel*\n\nSelect an option:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif user_id == ADMIN_USER_ID and text == '➕ Add User':
        user_states[user_id] = 'awaiting_user_add'
        await update.message.reply_text("Send me the user ID to add:")
    
    elif user_id == ADMIN_USER_ID and text == '➖ Remove User':
        user_states[user_id] = 'awaiting_user_remove'
        await update.message.reply_text("Send me the user ID to remove:")
    
    elif user_id == ADMIN_USER_ID and text == '📋 List Users':
        users = get_all_users()
        if not users:
            await update.message.reply_text("No users found in the database.")
        else:
            users_text = "📋 *Registered Users:*\n\n"
            for user in users:
                users_text += f"👤 User ID: {user[0]}\n📛 Username: {user[1]}\n📅 Added: {user[2]}\n🔰 Status: {'Active' if user[3] else 'Inactive'}\n\n"
            await update.message.reply_text(users_text, parse_mode='Markdown')
    
    elif user_id == ADMIN_USER_ID and text == '🔙 Back':
        keyboard = [['🚀 Start Load Test', '📊 My Tests'], ['👥 Admin Panel']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Main menu:", reply_markup=reply_markup)
    
    elif user_id in user_states:
        state = user_states[user_id]
        
        if state == 'awaiting_confirmation':
            if text.upper() == 'I OWN THIS SITE':
                user_states[user_id] = 'awaiting_url'
                await update.message.reply_text("🌐 Please send the target URL (include http:// or https://):")
            else:
                await update.message.reply_text("❌ Confirmation failed. Type exactly: I OWN THIS SITE")
        
        elif state == 'awaiting_url':
            if validate_url(text):
                # Check website status before proceeding
                status_info = check_website_online(text)
                await update.message.reply_text(
                    f"🌐 *Website Status Check:*\n{status_info['message']}\n\n"
                    "✅ URL accepted!\n📊 Enter total number of requests (default: 10000):",
                    parse_mode='Markdown'
                )
                user_states[user_id] = 'awaiting_requests'
                context.user_data['target_url'] = text
            else:
                await update.message.reply_text("❌ Invalid URL format. Please include http:// or https:// and try again:")
        
        elif state == 'awaiting_requests':
            try:
                total_requests = int(text) if text else 10000
                user_states[user_id] = 'awaiting_concurrency'
                context.user_data['total_requests'] = total_requests
                await update.message.reply_text(f"✅ Total requests set to: {total_requests}\n\n🧵 Enter concurrency level (default: 500):")
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number:")
        
        elif state == 'awaiting_concurrency':
            try:
                concurrency = int(text) if text else 500
                user_states[user_id] = 'awaiting_timeout'
                context.user_data['concurrency'] = concurrency
                await update.message.reply_text(f"✅ Concurrency set to: {concurrency}\n\n⏱️ Enter request timeout in seconds (default: 10):")
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number:")
        
        elif state == 'awaiting_timeout':
            try:
                timeout = int(text) if text else 10
                user_states[user_id] = 'awaiting_delay'
                context.user_data['timeout'] = timeout
                await update.message.reply_text(f"✅ Timeout set to: {timeout}s\n\n⏳ Enter delay between requests in seconds (default: 0.01):")
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number:")
        
        elif state == 'awaiting_delay':
            try:
                delay = float(text) if text else 0.01
                user_states[user_id] = 'awaiting_method'
                context.user_data['delay'] = delay
                
                keyboard = [['GET', 'POST']]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(
                    f"✅ Delay set to: {delay}s\n\n📨 Select HTTP method:",
                    reply_markup=reply_markup
                )
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid number:")
        
        elif state == 'awaiting_method':
            if text.upper() in ['GET', 'POST']:
                context.user_data['method'] = text.upper()
                
                if text.upper() == 'POST':
                    user_states[user_id] = 'awaiting_post_data'
                    await update.message.reply_text(
                        "📝 Enter POST data (as key=value&key2=value2) or send 'skip' for no data:",
                        reply_markup=ReplyKeyboardRemove()
                    )
                else:
                    # Start the test with GET method
                    await start_load_test(update, context)
            else:
                await update.message.reply_text("❌ Please select either GET or POST:")
        
        elif state == 'awaiting_post_data':
            if text.upper() == 'SKIP':
                context.user_data['post_data'] = None
            else:
                try:
                    post_data = {}
                    for pair in text.split('&'):
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            post_data[key] = value
                    context.user_data['post_data'] = post_data
                except:
                    await update.message.reply_text("❌ Invalid format. Please use key=value&key2=value2 format:")
                    return
            
            # Start the test
            await start_load_test(update, context)
        
        elif state == 'awaiting_user_add':
            try:
                new_user_id = int(text)
                username = f"user_{new_user_id}"
                add_user(new_user_id, username)
                del user_states[user_id]
                await update.message.reply_text(f"✅ User {new_user_id} added successfully!")
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid user ID:")
        
        elif state == 'awaiting_user_remove':
            try:
                remove_user_id = int(text)
                remove_user(remove_user_id)
                del user_states[user_id]
                await update.message.reply_text(f"✅ User {remove_user_id} removed successfully!")
            except ValueError:
                await update.message.reply_text("❌ Please enter a valid user ID:")
    
    else:
        await update.message.reply_text("Please select an option from the menu.")

async def start_load_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    config = context.user_data
    
    # Send initial message with live stats
    status_message = await update.message.reply_text("🚀 Starting load test...\n\n⏳ Please wait, this may take several minutes.")
    
    # Run the load test in a separate thread
    def run_test():
        try:
            results, test_duration = run_load_test(
                config['target_url'],
                config['total_requests'],
                config['concurrency'],
                config['timeout'],
                config.get('method', 'GET'),
                config.get('post_data'),
                config['delay'],
                user_id,
                status_message.message_id,
                context
            )
            
            result_text = format_results(config['target_url'], results, test_duration)
            
            # Send final results
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_message.message_id,
                    text=result_text,
                    parse_mode='Markdown'
                ),
                asyncio.get_event_loop()
            )
            
        except Exception as e:
            error_text = f"❌ An error occurred during testing: {str(e)}"
            asyncio.run_coroutine_threadsafe(
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_message.message_id,
                    text=error_text
                ),
                asyncio.get_event_loop()
            )
        
        finally:
            # Clean up user state
            if user_id in user_states:
                del user_states[user_id]
            context.user_data.clear()
    
    # Start the test in a separate thread
    thread = threading.Thread(target=run_test)
    thread.start()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ An error occurred. Please try again.")

def main():
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 Ultimate Load Test Bot is running...")
    print(f"👑 Admin User ID: {ADMIN_USER_ID}")
    application.run_polling()

if __name__ == "__main__":
    main()