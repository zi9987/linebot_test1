import os
import uuid
import io
import traceback
from flask import Flask, request, abort, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    TextSendMessage, MessageEvent, TextMessage,
    ImageMessage, VideoMessage, AudioMessage, FileMessage
)
import psycopg2
from psycopg2 import sql
from urllib.parse import urlparse

app = Flask(__name__)

# Set LINE Bot's Channel Access Token and Channel Secret
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# Database connection parameters
DB_NAME = 'enotesql'
DB_USER = 'enotesql_user'
DB_PASSWORD = 'Zkl7NsVZOLvv6gqvT64XwO66qUF45sfD'
DB_HOST = 'dpg-csqti4d2ng1s73bq5c50-a'
DB_PORT = '5432'
DATABASE_URL = 'postgresql://enotesql_user:Zkl7NsVZOLvv6gqvT64XwO66qUF45sfD@dpg-csqti4d2ng1s73bq5c50-a/enotesql' 
def get_db_connection():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL environment variable not set")

    result = urlparse(db_url)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port

    return psycopg2.connect(
        dbname=database,
        user=username,
        password=password,
        host=hostname,
        port=port
    )

def create_user_images_table():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                create_table_query = '''
                CREATE TABLE IF NOT EXISTS user_images (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(50) NOT NULL,
                    image_name VARCHAR(255) NOT NULL,
                    image_data BYTEA NOT NULL,
                    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER
                );
                '''
                cursor.execute(create_table_query)
                conn.commit()
        print("Table 'user_images' is ready.")
    except Exception as e:
        print(f"An error occurred while creating the table: {e}")
def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        app.logger.error(f"Database connection error: {e}")
        return None

def download_file(message_id):
    try:
        message_content = line_bot_api.get_message_content(message_id)
        file_data = b''.join(chunk for chunk in message_content.iter_content())
        app.logger.info(f"Downloaded file size: {len(file_data)} bytes")
        return file_data
    except Exception as e:
        app.logger.error(f"Error downloading file: {str(e)}")
        return None

def save_file_to_db(user_id, file_name, file_data):
    conn = get_db_connection()
    if conn is None:
        app.logger.error("Failed to connect to the database.")
        return
    try:
        cursor = conn.cursor()
        insert_query = '''
        INSERT INTO user_images (user_id, image_name, image_data)
        VALUES (%s, %s, %s);
        '''
        cursor.execute(insert_query, (user_id, file_name, psycopg2.Binary(file_data)))
        conn.commit()
        cursor.close()
        conn.close()
        app.logger.info(f"File '{file_name}' saved to database for user '{user_id}'.")
    except Exception as e:
        app.logger.error(f"Error saving file to database: {str(e)}")
        
def get_latest_image_for_user(user_id):
    conn = get_db_connection()
    if conn is None:
        return None, None
    try:
        cursor = conn.cursor()
        query = '''
        SELECT image_name, image_data
        FROM user_images
        WHERE user_id = %s
        ORDER BY upload_time DESC
        LIMIT 1;
        '''
        cursor.execute(query, (user_id,))
        record = cursor.fetchone()
        cursor.close()
        conn.close()
        if record:
            image_name, image_data = record
            return image_data, image_name
        else:
            return None, None
    except Exception as e:
        app.logger.error(f"Error retrieving image from database: {str(e)}")
        return None, None

@app.route('/image/<int:image_id>')
def get_image(image_id):
    conn = get_db_connection()
    if conn is None:
        return 'Internal server error', 500
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT image_name, image_data FROM user_images WHERE id = %s;', (image_id,))
        record = cursor.fetchone()
        cursor.close()
        conn.close()
        if record:
            image_name, image_data = record
            return send_file(
                io.BytesIO(image_data),
                mimetype='image/jpeg',  # Adjust MIME type as needed
                as_attachment=False,
                download_name=image_name
            )
        else:
            return 'Image not found', 404
    except Exception as e:
        app.logger.error(f"Error retrieving image from database: {str(e)}")
        return 'Internal server error', 500
@app.route('/image/<image_name>')
def serve_image(image_name):
    conn = get_db_connection()
    if conn is None:
        return 'Internal server error', 500
    try:
        cursor = conn.cursor()
        query = '''
        SELECT image_data
        FROM user_images
        WHERE image_name = %s;
        '''
        cursor.execute(query, (image_name,))
        record = cursor.fetchone()
        cursor.close()
        conn.close()
        if record:
            image_data = record[0]
            return send_file(
                io.BytesIO(image_data),
                mimetype='image/jpeg',  # Adjust MIME type as needed
                as_attachment=False,
                download_name=image_name
            )
        else:
            return 'Image not found', 404
    except Exception as e:
        app.logger.error(f"Error serving image: {str(e)}")
        return 'Internal server error', 500

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        app.logger.error("Missing X-Line-Signature header")
        abort(400)

    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature error")
        abort(400)
    except Exception as e:
        app.logger.error(f"Exception occurred while handling webhook: {str(e)}")
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=(ImageMessage, VideoMessage, AudioMessage, FileMessage))
def handle_media_message(event):
    user_id = event.source.user_id
    message_id = event.message.id
    message_type = event.message.type

    ext = {
        'image': 'jpg',
        'video': 'mp4',
        'audio': 'm4a',
        'file': None  # For FileMessage, handle separately
    }.get(message_type, 'dat')

    file_data = download_file(message_id)
    if file_data is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="Error downloading the file. Please try again later.")
        )
        return

    if message_type == 'file':
        file_name = event.message.file_name
    else:
        file_name = f"{uuid.uuid4()}.{ext}"

    save_file_to_db(user_id, file_name, file_data)

    reply_text = f"Successfully received your {message_type} file: {file_name}"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if text == '傳送檔案':
        # Retrieve the latest image for the user
        image_data, image_name = get_latest_image_for_user(user_id)
        if image_data:
            # Send the image back to the user
            image_message = ImageSendMessage(
                original_content_url=f"{YOUR_SERVER_URL}/image/{image_name}",
                preview_image_url=f"{YOUR_SERVER_URL}/image/{image_name}"
            )
            line_bot_api.reply_message(event.reply_token, image_message)
        else:
            # Inform the user that no image was found
            reply_text = "您尚未上傳任何圖片。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    else:
        # Handle other text messages
        reply_text = f"您說了：{text}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))


if __name__ == "__main__":
    create_user_images_table()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
