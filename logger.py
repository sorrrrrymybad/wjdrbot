import logging
import sys
from datetime import datetime
import os

class Logger:
    _instance = None
    
    @staticmethod
    def get_instance():
        if Logger._instance is None:
            Logger._instance = Logger()
        return Logger._instance
    
    def __init__(self):
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        # 生成日志文件名，包含日期
        log_file = f'logs/app_{datetime.now().strftime("%Y%m%d")}.log'
        
        # 配置日志格式
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        
        # 配置logger
        self.logger = logging.getLogger('App')
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def info(self, message):
        self.logger.info(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def warning(self, message):
        self.logger.warning(message)
    
    def debug(self, message):
        self.logger.debug(message)

# 创建全局日志实例
logger = Logger.get_instance()

def log(message):
    """便捷的日志记录函数"""
    logger.info(message) 