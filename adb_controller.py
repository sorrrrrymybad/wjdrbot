import subprocess
import numpy as np
from PIL import Image
import io
import re

class ADBController:
    def __init__(self):
        self.check_adb_connection()
    
    def check_adb_connection(self):
        try:
            subprocess.run(['adb', 'devices'], check=True)
        except subprocess.CalledProcessError:
            raise Exception("ADB 连接失败，请检查设备连接状态")
    
    def tap(self, x, y):
        subprocess.run(['adb', 'shell', 'input', 'tap', str(x), str(y)])
    
    def screenshot(self):
        # 获取屏幕截图
        result = subprocess.run(['adb', 'shell', 'screencap', '-p'], capture_output=True)
        
        # 将输出转换为图片
        image = Image.open(io.BytesIO(result.stdout))
        
        # 转换为OpenCV格式
        return np.array(image)
    
    def get_current_app(self):
        """获取当前前台应用的包名"""
        cmd = ['adb', 'shell', 'dumpsys', 'window', '|', 'grep', '-E', 'mCurrentFocus']
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 使用正则表达式提取包名
        match = re.search(r'mCurrentFocus=.*{.*\s+([\w\.]+)\/.*}', result.stdout)
        if match:
            return match.group(1)
        return None
    
    def is_app_foreground(self, package_name):
        """检查指定应用是否在前台"""
        current_app = self.get_current_app()
        return current_app == package_name
    
    def launch_app(self, package_name):
        """启动指定应用"""
        subprocess.run(['adb', 'shell', 'monkey', '-p', package_name, '-c', 'android.intent.category.LAUNCHER', '1']) 
    
    def force_stop_app(self, package_name):
        """强制停止应用"""
        subprocess.run(['adb', 'shell', 'am', 'force-stop', package_name])
        print(f"已强制停止应用: {package_name}")

    def swipe(self, start_x, start_y, end_x, end_y, duration=500):
        """
        执行滑动操作
        :param start_x: 起始点X坐标
        :param start_y: 起始点Y坐标
        :param end_x: 结束点X坐标
        :param end_y: 结束点Y坐标
        :param duration: 滑动持续时间（毫秒）
        """
        subprocess.run([
            'adb', 'shell', 'input', 'swipe',
            str(start_x), str(start_y),
            str(end_x), str(end_y),
            str(duration)
        ])

    def long_press(self, x, y, duration=1000):
        """
        执行长按操作
        :param x: X坐标
        :param y: Y坐标
        :param duration: 长按持续时间（毫秒）
        """
        subprocess.run([
            'adb', 'shell', 'input', 'swipe',
            str(x), str(y), str(x), str(y),
            str(duration)
        ])