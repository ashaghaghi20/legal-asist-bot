#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
import sqlite3
import asyncio
import threading
import requests
import json
from flask import Flask, request
import nest_asyncio

# اعمال nest_asyncio برای حل مشکل event loop
nest_asyncio.apply()

# تنظیمات لاگ‌گیری
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تنظیمات DeepSeek API
DEEPSEEK_API_KEY = "sk-398708d4b84e47fdbda76e841ec28384"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# تنظیمات Flask برای وب‌هاک
app = Flask(__name__)

# توکن تست ربات تلگرام
BOT_TOKEN = "7693531934:AAH0IXfuZaWUlbAfRjNurZqxWFZD2r2g9ZY"
SPONSOR_CHANNEL = "@Radio_Zhelofen"  # کانال اسپانسر

# مدیریت پایگاه داده
def init_db():
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    usage_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database error: {e}")

def get_user_data(user_id):
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute('SELECT usage_count FROM users WHERE user_id = ?', (user_id,))
            result = c.fetchone()
            if result:
                return {'usage_count': result[0]}
            else:
                return {'usage_count': 0}
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        return {'usage_count': 0}

def add_user(user_id, username=None, first_name=None):
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute(
                'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                (user_id, username, first_name)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Database error: {e}")

def increment_usage(user_id):
    try:
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"❌ Database error: {e}")

# تابع بررسی عضویت در کانال
def check_channel_membership(user_id):
    """بررسی واقعی عضویت کاربر در کانال اسپانسر"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember"
        payload = {
            "chat_id": SPONSOR_CHANNEL,
            "user_id": user_id
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            status = result['result']['status']
            # وضعیت‌های مجاز: member, administrator, creator
            allowed_statuses = ['member', 'administrator', 'creator']
            return status in allowed_statuses
        else:
            logger.error(f"Membership check failed: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

# تابع ارتباط با DeepSeek API
def get_deepseek_response(user_message, user_context=None):
    """ارسال درخواست به DeepSeek API و دریافت پاسخ"""
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
        }
        
        # ایجاد محتوای هوشمند بر اساس نوع سوال
        system_message = """شما یک دستیار حقوقی هوشمند هستید. به کاربران در موارد زیر کمک کنید:
        
1. تحلیل متون حقوقی و قراردادها
2. پاسخ به سوالات حقوقی
3. راهنمایی در مورد قوانین
4. تبدیل مفاهیم حقوقی به زبان ساده

همیشه پاسخ‌های دقیق، مفید و مبتنی بر اصول حقوقی ارائه دهید."""

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"DeepSeek API Error: {response.status_code} - {response.text}")
            return "⚠️ متاسفانه در ارتباط با سرویس هوش مصنوعی مشکل پیش آمده. لطفاً稍后再试 کنید。"
    
    except Exception as e:
        logger.error(f"Error calling DeepSeek API: {e}")
        return "❌ خطا در پردازش درخواست. لطفاً مجدداً تلاش کنید。"

# وب‌هاک برای تلگرام
@app.route('/')
def home():
    return "🤖 Legal Assistant Bot with DeepSeek API is Running!", 200

@app.route('/health')
def health():
    return "✅ OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """دریافت به‌روزرسانی‌های تلگرام از طریق وب‌هاک"""
    try:
        update_data = request.get_json()
        
        # پردازش غیرهمزمان به‌روزرسانی
        threading.Thread(target=process_telegram_update, args=(update_data,)).start()
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "ERROR", 500

def process_telegram_update(update_data):
    """پردازش به‌روزرسانی تلگرام"""
    try:
        if 'message' in update_data:
            message = update_data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            user = message.get('from', {})
            user_id = user['id']
            
            # بررسی عضویت برای همه دستورات به جز /start
            if not text.startswith('/start'):
                is_member = check_channel_membership(user_id)
                if not is_member:
                    send_telegram_message(chat_id,
                        f"🚫 **دسترسی محدود**\n\n"
                        f"برای استفاده از خدمات ربات، باید در کانال اسپانسر ما عضو باشید.\n\n"
                        f"📢 **کانال اسپانسر:** {SPONSOR_CHANNEL}\n\n"
                        f"✅ پس از عضویت، مجدداً سوال خود را بفرستید.\n"
                        f"🔍 سیستم به طور خودکار عضویت شما را بررسی می‌کند."
                    )
                    return
            
            # پردازش دستورات
            if text.startswith('/start'):
                # برای دستور start هم عضویت را چک می‌کنیم اما پیام متفاوت می‌دهیم
                is_member = check_channel_membership(user_id)
                
                if is_member:
                    welcome_text = (
                        f"👋 سلام {user.get('first_name', 'کاربر')}!\n"
                        "🤖 به ربات دستیار حقوقی هوشمند خوش آمدید\n\n"
                        "✅ **عضویت شما تایید شد!**\n\n"
                        "🎯 **امکانات ربات:**\n"
                        "• سوالات حقوقی بپرسید\n"
                        "• متون حقوقی تحلیل کنید\n" 
                        "• راهنمایی حقوقی دریافت کنید\n\n"
                        "⚡ **قدرت گرفته از DeepSeek AI**\n\n"
                        "💡 سوال حقوقی خود را تایپ کنید..."
                    )
                else:
                    welcome_text = (
                        f"👋 سلام {user.get('first_name', 'کاربر')}!\n"
                        "🤖 به ربات دستیار حقوقی هوشمند خوش آمدید\n\n"
                        "📢 **شرایط استفاده:**\n"
                        f"برای استفاده از ربات، باید در کانال اسپانسر عضو باشید:\n{SPONSOR_CHANNEL}\n\n"
                        "🔒 **دسترسی فعلی:** غیرفعال\n"
                        "✅ **پس از عضویت:** فعال می‌شود\n\n"
                        "💡 پس از عضویت در کانال، مجدداً پیام بفرستید."
                    )
                
                send_telegram_message(chat_id, welcome_text)
                add_user(user_id, user.get('username'), user.get('first_name'))
            
            elif text.startswith('/status'):
                user_data = get_user_data(user_id)
                is_member = check_channel_membership(user_id)
                
                status_text = (
                    f"📊 **وضعیت حساب شما:**\n"
                    f"👤 کاربر: {user.get('first_name', '')}\n"
                    f"✅ تعداد استفاده: {user_data['usage_count']}\n"
                    f"🔒 وضعیت عضویت: {'✅ فعال' if is_member else '❌ غیرفعال'}\n"
                    f"🤖 سرویس: DeepSeek AI\n"
                )
                
                if not is_member:
                    status_text += f"\n📢 برای فعال شدن دسترسی، در کانال عضو شوید:\n{SPONSOR_CHANNEL}"
                
                send_telegram_message(chat_id, status_text)
            
            elif text.startswith('/help'):
                help_text = (
                    "📖 **راهنمای ربات:**\n\n"
                    "💬 **پرسش سوال** - سوال حقوقی خود را بپرسید\n"
                    "📄 **تحلیل متن** - متن حقوقی را برای تحلیل ارسال کنید\n"
                    "📊 **وضعیت** - مشاهده وضعیت حساب\n\n"
                    "🔒 **شرایط استفاده:**\n"
                    f"عضویت در کانال: {SPONSOR_CHANNEL}\n\n"
                    "⚡ **قدرت گرفته از DeepSeek AI**\n\n"
                    "❓ برای شروع، سوال خود را تایپ کنید"
                )
                send_telegram_message(chat_id, help_text)
            
            else:
                # کاربر عضو است - پردازش سوال با DeepSeek
                increment_usage(user_id)
                
                # ارسال پیام "در حال پردازش"
                processing_msg = send_telegram_message(chat_id, "🔄 در حال پردازش با DeepSeek AI...")
                
                # دریافت پاسخ از DeepSeek
                ai_response = get_deepseek_response(text)
                
                # ارسال پاسخ
                send_telegram_message(chat_id, 
                    f"🤖 **پاسخ هوش مصنوعی:**\n\n"
                    f"{ai_response}\n\n"
                    f"📊 **تعداد استفاده:** {get_user_data(user_id)['usage_count']}"
                )
                
                # حذف پیام "در حال پردازش"
                if processing_msg:
                    delete_telegram_message(chat_id, processing_msg['result']['message_id'])
    
    except Exception as e:
        logger.error(f"Error processing update: {e}")

def send_telegram_message(chat_id, text):
    """ارسال پیام به تلگرام"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None

def delete_telegram_message(chat_id, message_id):
    """حذف پیام از تلگرام"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

def set_webhook():
    """تنظیم وب‌هاک برای تلگرام"""
    try:
        # ابتدا آدرس Render خود را اینجا قرار دهید
        # بعد از deploy، آدرس واقعی را جایگزین کنید
        webhook_url = "https://your-app-name.onrender.com/webhook"
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        payload = {
            "url": webhook_url,
            "drop_pending_updates": True
        }
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("✅ Webhook set successfully!")
        else:
            logger.error(f"❌ Webhook setup failed: {response.text}")
    except Exception as e:
        logger.error(f"❌ Error setting webhook: {e}")

def ping_self():
    """پینگ کردن خود برای جلوگیری از sleep"""
    try:
        # بعد از deploy، آدرس واقعی را جایگزین کنید
        app_url = "https://your-app-name.onrender.com/health"
        requests.get(app_url, timeout=10)
        logger.info("✅ Self-ping completed")
    except Exception as e:
        logger.error(f"❌ Self-ping failed: {e}")

def start_ping_service():
    """شروع سرویس پینگ دوره‌ای"""
    def ping_loop():
        import time
        while True:
            ping_self()
            time.sleep(300)  # هر 5 دقیقه
    
    ping_thread = threading.Thread(target=ping_loop)
    ping_thread.daemon = True
    ping_thread.start()
    logger.info("✅ Auto-ping service started")

def main():
    """تابع اصلی"""
    logger.info("🚀 Starting Legal Assistant Bot with DeepSeek API...")
    logger.info(f"🤖 Bot Token: {BOT_TOKEN[:10]}...")
    logger.info(f"📢 Sponsor Channel: {SPONSOR_CHANNEL}")
    
    # راه‌اندازی پایگاه داده
    init_db()
    
    # تنظیم وب‌هاک
    set_webhook()
    
    # شروع سرویس پینگ خودکار
    start_ping_service()
    
    logger.info("✅ Bot is fully operational!")
    logger.info("🤖 Powered by DeepSeek AI")
    logger.info("🔒 Membership check: ENABLED")
    
    # اجرای Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    main()
