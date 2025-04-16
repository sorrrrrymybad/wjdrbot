import requests
import os
from logger import log

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        log("Telegram通知器初始化完成")

    def send_message(self, message):
        """发送文本消息"""
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, data=data)
            response.raise_for_status()
            log(f"Telegram消息发送成功: {message}")
            return True
        except Exception as e:
            log(f"Telegram消息发送失败: {e}")
            return False

    def send_photo(self, photo_path, caption=None):
        """发送图片"""
        try:
            url = f"{self.base_url}/sendPhoto"
            with open(photo_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    "chat_id": self.chat_id,
                    "caption": caption
                }
                response = requests.post(url, files=files, data=data)
                response.raise_for_status()
                log(f"Telegram图片发送成功: {photo_path}")
                return True
        except Exception as e:
            log(f"Telegram图片发送失败: {e}")
            return False

# 创建全局通知器实例
notifier = None

def init_notifier(token, chat_id):
    """初始化通知器"""
    global notifier
    notifier = TelegramNotifier(token, chat_id)
    return notifier

def send_notification(message, photo_path=None):
    """发送通知"""
    if notifier is None:
        log("Telegram通知器未初始化")
        return False
    
    # 总是发送文本消息
    success = notifier.send_message(message)
    
    # 如果提供了图片路径且图片存在，则发送图片
    if photo_path and os.path.exists(photo_path):
        notifier.send_photo(photo_path, caption=message)
    
    return success 