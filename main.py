import yaml
import time
import signal
import sys
from datetime import time as dt_time
from logger import log
from telegram_notifier import init_notifier, send_notification
from api_server import init_api_server

def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def main():
    try:
        log("启动自动化任务系统")
        
        # 加载配置文件
        config = load_config()
        log("配置文件加载完成")
        
        # 初始化Telegram通知器
        if 'telegram' in config and config['telegram']['enabled']:
            init_notifier(
                config['telegram']['token'],
                config['telegram']['chat_id']
            )
            log("Telegram通知器初始化完成")
        
        # 导入TaskManager
        from task_manager import TaskManager
        
        # 初始化任务管理器
        task_manager = TaskManager(config['app_package'])
        
        # 设置空闲超时时间（如果配置中有）
        if 'idle_timeout' in config:
            task_manager.idle_timeout = config['idle_timeout']
        
        # 设置应用启动等待时间（如果配置中有）
        if 'startup_wait_time' in config:
            task_manager.startup_wait_time = config['startup_wait_time']
        
        # 设置调试配置
        if 'debug' in config:
            debug_config = config['debug']
            task_manager.save_images = debug_config.get('save_images', False)
            task_manager.save_path = debug_config.get('save_path', 'images/tmp')
        
        
        # 设置应用启动操作（如果配置中有）
        if 'startup_actions' in config:
            task_manager.set_startup_actions(config['startup_actions'])
        
        # 注册所有启用的任务
        for task_name, task_config in config['tasks'].items():
            if task_config['enabled']:
                task_manager.task_next_run[task_name] = None
        
        # 初始化API服务器
        init_api_server(task_manager)
        
        # 启动任务管理器
        log("启动任务管理器...")
        task_manager.start()
        
        # 注册信号处理
        def signal_handler(signum, frame):
            log(f"收到信号 {signum}，正在停止程序...")
            task_manager.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # kill 命令
        
        # 保持主线程运行
        while True:
            time.sleep(1)
    except Exception as e:
        log(f"程序执行出错: {e}")
        import traceback
        log(traceback.format_exc())
    finally:
        log("程序退出")

if __name__ == "__main__":
    main() 