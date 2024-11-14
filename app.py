import os
import uuid
import traceback
from flask import Flask, request, abort, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage, MessageEvent, TextMessage, PostbackEvent, MemberJoinedEvent
from linepay import LinePayApi
import openai
import psycopg2
from psycopg2 import sql
app = Flask(__name__)

# 設定 LINE Bot 的 Channel Access Token 和 Channel Secret
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# 設定 OpenAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')

# 設定 LINE Pay 的 Channel ID 和 Channel Secret
LINE_PAY_CHANNEL_ID = os.getenv('LINE_PAY_CHANNEL_ID')
LINE_PAY_CHANNEL_SECRET = os.getenv('LINE_PAY_CHANNEL_SECRET')
IS_SANDBOX = True  # 使用 Sandbox 環境進行測試

# 初始化 LINE Pay API 客戶端
line_pay_api = LinePayApi(
    channel_id=LINE_PAY_CHANNEL_ID,
    channel_secret=LINE_PAY_CHANNEL_SECRET,
    is_sandbox=IS_SANDBOX
)


# 設定資料庫連線參數
DB_NAME = 'EnoteSQL'
DB_USER = 'enotesql_user'
DB_PASSWORD = 'Zkl7NsVZOLvv6gqvT64XwO66qUF45sfD'
DB_HOST = 'dpg-csqti4d2ng1s73bq5c50-a'
DB_PORT = '5432'

CREATE TABLE user_files (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50),
    file_name VARCHAR(255),
    file_data BYTEA,
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

def get_db_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
def download_file(message_id):
    message_content = line_bot_api.get_message_content(message_id)
    file_data = b''
    for chunk in message_content.iter_content():
        file_data += chunk
    return file_data
    
def GPT_response(text):
    # 呼叫 OpenAI API 獲取回應
    response = openai.Completion.create(
        model="gpt-3.5-turbo-instruct",
        prompt=text,
        temperature=0.5,
        max_tokens=500
    )
    # 提取並處理回應文本
    answer = response['choices'][0]['text'].strip()
    return answer

@app.route("/callback", methods=['POST'])
def callback():
    # 獲取 X-Line-Signature 標頭值
    signature = request.headers['X-Line-Signature']
    # 獲取請求主體內容
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    # 處理 webhook 主體
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    message_id = event.message.id
    user_id = event.source.user_id
    file_name = event.message.file_name
    # 下載檔案
    file_data = download_file(message_id)
    # 儲存至資料庫
    save_file_to_db(user_id, file_name, file_data)
    # 回應使用者
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"您已成功上傳檔案：{file_name}")
    )
    msg = event.message.text
    if msg == "購買筆記":
        # 觸發付款流程
        pay_url = url_for('pay', _external=True)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"請點擊以下連結進行付款：{pay_url}")
        )
    else:
        try:
            GPT_answer = GPT_response(msg)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(GPT_answer))
        except Exception:
            app.logger.error(traceback.format_exc())
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage('發生錯誤，請稍後再試')
            )

@handler.add(PostbackEvent)
def handle_postback(event):
    app.logger.info(f"Postback data: {event.postback.data}")

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}，歡迎加入！')
    line_bot_api.reply_message(event.reply_token, message)

@app.route("/pay", methods=['GET'])
def pay():
    product_name = "E-note 筆記"
    amount = 100  # 金額
    currency = 'TWD'  # 貨幣
    order_id = str(uuid.uuid4())

    # 設定付款完成後的回調 URL
    confirm_url = url_for('linepay_confirm', _external=True)
    cancel_url = url_for('cancel', _external=True)

    request_options = {
        'amount': amount,
        'currency': currency,
        'orderId': order_id,
        'packages': [
            {
                'id': 'package-1',
                'amount': amount,
                'name': product_name,
                'products': [
                    {
                        'id': 'product-1',
                        'name': product_name,
                        'imageUrl': 'https://example.com/product.jpg',
                        'quantity': 1,
                        'price': amount
                    }
                ]
            }
        ],
        'redirectUrls': {
            'confirmUrl': confirm_url,
            'cancelUrl': cancel_url
        }
    }

    try:
        response = line_pay_api.request(request_options)
        payment_url = response['info']['paymentUrl']['web']
        return redirect(payment_url)
    except Exception:
        app.logger.error(traceback.format_exc())
        return "發生錯誤，請稍後再試"

@app.route("/linepay/confirm", methods=['GET'])
def linepay_confirm():
    transaction_id = request.args.get('transactionId')
    if not transaction_id:
        return "Transaction ID not found", 400

    # 假設您在付款請求時保存了 order_id 與 user_id 的對應關係
    order_id = request.args.get('orderId')
    user_id = get_user_id_from_order(order_id)  # 根據您的邏輯獲取 user_id

    # 呼叫 Confirm API
    amount = 100  # 與付款請求中的金額一致
    currency = 'TWD'  # 與付款請求中的貨幣一致
    response = line_pay_api.confirm(transaction_id, amount, currency)
    if response['returnCode'] == '0000':
        # 付款成功，通知使用者
        line_bot_api.push_message(user_id, TextSendMessage(text="付款成功，感謝您的購買！"))
        return "Payment confirmed", 200
    else:
        return f"Payment confirmation failed: {response['returnMessage']}", 400


@app.route("/cancel", methods=['GET'])
def cancel():
    return "您已取消付款"

if __name__ == "__main__":
    app.run(debug=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
