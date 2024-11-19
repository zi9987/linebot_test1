import os
import uuid
import traceback
from flask import Flask, request, abort, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    TextSendMessage, MessageEvent, TextMessage,
    ImageMessage, VideoMessage, AudioMessage, FileMessage
)
import psycopg2
from psycopg2 import sql

app = Flask(__name__)

# 設定 LINE Bot 的 Channel Access Token 和 Channel Secret
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# 設定資料庫連線參數
DB_NAME = 'dpg-csqti4d2ng1s73bq5c50-a'
DB_USER = 'enotesql_user'
DB_PASSWORD = 'Zkl7NsVZOLvv6gqvT64XwO66qUF45sfD'
DB_HOST = 'dpg-csqti4d2ng1s73bq5c50-a'
DB_PORT = '5432'

def create_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    create_table_query = '''
    CREATE TABLE IF NOT EXISTS user_files (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(50),
        file_name VARCHAR(255),
        file_data BYTEA,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    '''
    cursor.execute(create_table_query)
    conn.commit()
    cursor.close()
    conn.close()

def get_db_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

def download_file(message_id):
    try:
        message_content = line_bot_api.get_message_content(message_id)
        file_data = b''.join(chunk for chunk in message_content.iter_content())
        app.logger.info(f"下載的檔案大小：{len(file_data)} bytes")
        return file_data
    except Exception as e:
        app.logger.error(f"下載檔案時發生錯誤：{str(e)}")
        return None

def save_file_to_db(user_id, file_name, file_data):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        insert_query = '''
        INSERT INTO user_files (user_id, file_name, file_data)
        VALUES (%s, %s, %s);
        '''
        cursor.execute(insert_query, (user_id, file_name, file_data))
        conn.commit()
        app.logger.info(f"檔案 {file_name} 已成功儲存到資料庫，使用者 ID: {user_id}")
        cursor.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"儲存檔案失敗：{str(e)}")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        app.logger.error("缺少 X-Line-Signature 標頭值")
        abort(400)

    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("無效的簽名錯誤")
        abort(400)
    except Exception as e:
        app.logger.error(f"處理 webhook 時發生異常：{str(e)}")
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=(ImageMessage, VideoMessage, AudioMessage, FileMessage))
def handle_media_message(event):
    user_id = event.source.user_id
    message_id = event.message.id
    message_type = event.message.type

    # 根據訊息類型設定檔案副檔名
    ext = {
        'image': 'jpg',
        'video': 'mp4',
        'audio': 'm4a',
        'file': None  # 對於 FileMessage，稍後處理
    }.get(message_type, 'dat')

    # 下載檔案內容
    file_data = download_file(message_id)
    if file_data is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="下載檔案時發生錯誤，請稍後再試。")
        )
        return

    # 生成檔案名稱
    if message_type == 'file':
        # 對於 FileMessage，使用原始檔案名稱
        file_name = event.message.file_name
    else:
        # 對於其他訊息類型，生成唯一的檔案名稱
        file_name = f"{uuid.uuid4()}.{ext}"

    # 儲存檔案到資料庫
    save_file_to_db(user_id, file_name, file_data)

    # 回覆使用者
    reply_text = f"已成功接收您的{message_type}檔案：{file_name}"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text

    # 根據使用者輸入的文字進行相應處理
    if text.lower() == 'hello':
        reply_text = "您好！請上傳您想要儲存的檔案。"
    else:
        reply_text = f"您說了：{text}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    create_table()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
