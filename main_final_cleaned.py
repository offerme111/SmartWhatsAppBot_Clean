from flask import Flask, request, render_template, redirect
from twilio.rest import Client
import requests, os, sqlite3, smtplib, json
from dotenv import load_dotenv
from datetime import datetime
from email.mime.text import MIMEText

load_dotenv()
app = Flask(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

sessions = {}

def has_received_template(sender):
    conn = sqlite3.connect("messages.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS template_log (sender TEXT PRIMARY KEY, sent_at TEXT)")
    c.execute("SELECT 1 FROM template_log WHERE sender = ?", (sender,))
    result = c.fetchone()
    conn.close()
    return result is not None

def log_template_sent(sender):
    conn = sqlite3.connect("messages.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO template_log (sender, sent_at) VALUES (?, ?)", (sender, datetime.now()))
    conn.commit()
    conn.close()

def send_template(to_number):
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    payload = {
        "To": to_number,
        "From": TWILIO_PHONE_NUMBER,
        "ContentSid": "HX20732d6109ed00a2d58bb95103bdc2f0",
        "MessagingServiceSid": TWILIO_MESSAGING_SERVICE_SID
    }
    try:
        res = requests.post(url, data=payload, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        print("📤 Template sent:", res.status_code)
    except Exception as e:
        print("❌ Error sending template:", str(e))

def send_email(subject, body):
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("📧 Email sent")
    except Exception as e:
        print("❌ Error sending email:", str(e))

def get_ai_response(user_message, sender):
    # 🧾 تحميل بيانات البوت
    try:
        with open("bot_info.json", "r", encoding="utf-8") as f:
            bot_info = json.load(f)
    except Exception as e:
        bot_info = {
            "company_name": "Offer ME",
            "description": "نقدم خدمات العروض الترويجية"
        }

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json"
    }

    previous = sessions.get(sender, {}).get("context", "")
    full_context = f"{previous}\n{user_message}"

    system_message = f"""
    أنت مساعد ذكي تمثل شركة {bot_info['company_name']}.
    وصف الشركة: {bot_info['description']}.
    اجعل ردودك قصيرة وواضحة.
    تحدث مع العملاء بأسلوب احترافي وودود.
    إذا شعرت أن الزبون مهتم بالخدمة، اطلب منه اسمه ونوع عمله ورقمه وإيميله.
    لا تطلب أي معلومة إذا لم يكن مهتمًا بوضوح.
    """

    data = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": full_context}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        reply = response.json()['choices'][0]['message']['content']
        sessions[sender] = sessions.get(sender, {})
        sessions[sender]["context"] = full_context + f"\n{reply}"

        if any(word in user_message for word in ["@gmail", "@hotmail", "اسمي", "رقمي", "+974", "ايميلي"]):
            send_email("عميل محتمل من واتساب", f"رقم الزبون: {sender}\n\nرسالة:\n{user_message}\n\nرد البوت:\n{reply}")
        return reply
    except Exception as e:
        print("❌ OpenRouter Error:", str(e))
        return "حدث خطأ في الرد الذكي."

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "")

    if not has_received_template(sender):
        send_template(sender)
        log_template_sent(sender)
        return "OK", 200

    reply = get_ai_response(incoming_msg, sender)
    send_message(sender, reply)
    return "OK", 200

def send_message(to, body):
    client.messages.create(
        to=to,
        body=body,
        messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID
    )

@app.route("/update-bot-info", methods=["POST"])
def update_bot_info():
    try:
        data = request.get_json()
        if not data:
            return {"error": "بيانات غير موجودة"}, 400

        with open("bot_info.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("✅ تم تحديث ملف bot_info.json")
        return {"message": "تم التحديث بنجاح"}, 200

    except Exception as e:
        print("❌ خطأ في التحديث:", str(e))
        return {"error": str(e)}, 500

@app.route("/bot-info")
def show_bot_info():
    try:
        with open("bot_info.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return f"<h2>🧾 آخر بيانات البوت:</h2><pre>{json.dumps(data, ensure_ascii=False, indent=2)}</pre>"
    except Exception as e:
        return f"<h3>❌ خطأ في قراءة البيانات: {str(e)}</h3>"

@app.route("/")
def home():
    return "<h2 style='text-align:center;margin-top:50px'>✅ البوت يعمل بنجاح!</h2>"

if __name__ == "__main__":
    print("✅ البوت يعمل على http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
