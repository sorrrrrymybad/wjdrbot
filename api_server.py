from flask import Flask, request, jsonify
from flask_cors import CORS
from logger import log
import threading
import os
import heapq
import signal
import sys
from ruamel.yaml import YAML
from functools import wraps
from dotenv import load_dotenv
import time
from datetime import datetime

# 加载 .env 文件
load_dotenv()

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 全局任务管理器实例
task_manager = None

# 从环境变量获取 API 密钥
API_KEY = os.getenv('API_KEY')
if not API_KEY:
    raise ValueError("API_KEY 未在 .env 文件中设置")

def require_api_key(f):
    """验证 API 密钥的装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('X-API-Key')
        if auth_header and auth_header == API_KEY:
            return f(*args, **kwargs)
        else:
            return jsonify({
                'success': False,
                'error': '无效的 API 密钥'
            }), 401
    return decorated_function

def load_config():
    yaml = YAML()
    yaml.preserve_quotes = True
    with open('config.yaml', 'r', encoding='utf-8') as f:
        return yaml.load(f)

def save_config(config):
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open('config.yaml', 'w', encoding='utf-8') as f:
        yaml.dump(config, f)

@app.route('/tasks', methods=['GET'])
@require_api_key
def get_tasks():
    """获取所有任务状态"""
    try:
        config = load_config()
        tasks = []
        for name, task in config['tasks'].items():
            # 获取任务的下一次执行时间
            next_run = None
            if task_manager and name in task_manager.task_next_run:
                next_run_time = task_manager.task_next_run[name]
                if next_run_time:
                    next_run = next_run_time.strftime('%Y-%m-%d %H:%M:%S')
            
            tasks.append({
                'name': name,
                'enabled': task['enabled'],
                'description': task.get('name', ''),
                'next_run': next_run,  # 添加下一次执行时间
                'cooldown': task.get('cooldown', {})  # 添加冷却时间配置
            })
        
        return jsonify({
            'success': True, 
            'tasks': tasks,
            'current_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # 添加当前时间用于对比
        })
    except Exception as e:
        log(f"获取任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/tasks', methods=['PUT'])
@require_api_key
def update_task():
    """批量更新任务状态"""
    try:
        data = request.get_json()
        if not isinstance(data, list):
            return jsonify({'success': False, 'error': '请求数据必须是数组格式'}), 400
        
        config = load_config()
        results = []
        enabled_tasks = []
        has_status_change = False  # 标记是否有任务状态发生变化
        
        # 处理每个任务的更新
        for task_update in data:
            if 'name' not in task_update or 'enabled' not in task_update:
                results.append({
                    'name': task_update.get('name', 'unknown'),
                    'success': False,
                    'error': '缺少必要参数 name 或 enabled'
                })
                continue
                
            task_name = task_update['name']
            if task_name not in config['tasks']:
                results.append({
                    'name': task_name,
                    'success': False,
                    'error': '任务不存在'
                })
                continue
            
            # 检查任务状态是否发生变化
            current_status = config['tasks'][task_name]['enabled']
            new_status = task_update['enabled']
            
            if current_status != new_status:
                has_status_change = True
            
            # 更新任务状态
            config['tasks'][task_name]['enabled'] = new_status
            
            # 如果任务被启用，添加到启用列表
            if new_status:
                enabled_tasks.append(task_name)
            
            results.append({
                'name': task_name,
                'success': True,
                'enabled': new_status,
                'status_changed': current_status != new_status
            })
        
        # 保存配置
        save_config(config)
        
        # 处理任务队列
        if task_manager:
            with task_manager.task_lock:
                # 只有当有任务状态发生变化时才重新调度
                if has_status_change:
                    # 清空当前任务队列
                    task_manager.task_queue = []
                    # 清空所有任务的下次执行时间
                    task_manager.task_next_run = {}
                    
                    # 重新初始化所有启用任务的下次执行时间
                    for name in enabled_tasks:
                        task_manager.task_next_run[name] = None
            
            # 在释放锁后重新安排所有启用的任务
            for name in enabled_tasks:
                task_manager.schedule_task(name)
        
        log(f"批量更新任务状态完成，结果: {results}")
        return jsonify({
            'success': True,
            'results': results
        })
    except Exception as e:
        log(f"批量更新任务状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/apps/<package_name>/close', methods=['POST'])
@require_api_key
def close_app(package_name):
    """关闭指定的应用"""
    try:
        if task_manager:
            # 直接使用 ADB 关闭应用
            task_manager.adb.force_stop_app(package_name)
            # 更新应用状态
            task_manager.app_closed = True
            log(f"已强制停止应用: {package_name}")
                
            return jsonify({
                'success': True,
                'message': f'应用 {package_name} 已关闭'
            })
        else:
            return jsonify({
                'success': False,
                'error': '任务管理器未初始化'
            }), 500
    except Exception as e:
        log(f"关闭应用失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/logs', methods=['GET'])
@require_api_key
def get_logs():
    """获取最新的日志内容"""
    try:
        # 获取查询参数
        lines = request.args.get('lines', default=100, type=int)  # 默认返回最后100行
        
        # 获取日志文件路径
        log_dir = "logs"
        if not os.path.exists(log_dir):
            return jsonify({
                'success': False,
                'error': '日志目录不存在'
            }), 404
        
        # 获取最新的日志文件
        log_files = [f for f in os.listdir(log_dir) if f.startswith('app_')]
        if not log_files:
            return jsonify({
                'success': False,
                'error': '没有找到日志文件'
            }), 404
            
        latest_log = max(log_files, key=lambda x: os.path.getmtime(os.path.join(log_dir, x)))
        log_path = os.path.join(log_dir, latest_log)
        
        # 读取日志内容
        with open(log_path, 'r', encoding='utf-8') as f:
            # 读取所有行并保留最后N行
            all_lines = f.readlines()
            log_content = all_lines[-lines:] if lines > 0 else all_lines
        
        return jsonify({
            'success': True,
            'log_file': latest_log,
            'content': log_content
        })
    except Exception as e:
        log(f"获取日志失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/process/stop', methods=['POST'])
@require_api_key
def stop_process():
    """结束当前进程"""
    try:
        if task_manager:
            # 停止任务管理器
            task_manager.stop()
            log("任务管理器已停止")
            
            # 发送关闭信号给主进程
            def delayed_shutdown():
                time.sleep(1)  # 等待1秒确保响应能够发送
                os.kill(os.getpid(), signal.SIGTERM)
            
            # 在新线程中执行延迟关闭
            shutdown_thread = threading.Thread(target=delayed_shutdown)
            shutdown_thread.daemon = True
            shutdown_thread.start()
            
            return jsonify({
                'success': True,
                'message': '进程正在关闭...'
            })
        else:
            return jsonify({
                'success': False,
                'error': '任务管理器未初始化'
            }), 500
    except Exception as e:
        log(f"停止进程失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def start_api_server(host='0.0.0.0', port=1234):
    """启动API服务器"""
    app.run(host=host, port=port)

def init_api_server(manager):
    """初始化API服务器"""
    global task_manager
    task_manager = manager
    
    # 在新线程中启动API服务器
    api_thread = threading.Thread(target=start_api_server)
    api_thread.daemon = True
    api_thread.start()
    log("API服务器已启动") 