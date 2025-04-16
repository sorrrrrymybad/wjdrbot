from flask import Flask, request, jsonify
from flask_cors import CORS
from logger import log
import threading
import os
import heapq
import signal
import sys
from ruamel.yaml import YAML

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 全局任务管理器实例
task_manager = None

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
def get_tasks():
    """获取所有任务状态"""
    try:
        config = load_config()
        tasks = []
        for name, task in config['tasks'].items():
            tasks.append({
                'name': name,
                'enabled': task['enabled'],
                'description': task.get('name', '')
            })
        return jsonify({'success': True, 'tasks': tasks})
    except Exception as e:
        log(f"获取任务列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/tasks/<task_name>', methods=['PUT'])
def update_task(task_name):
    """更新任务状态"""
    try:
        config = load_config()
        if task_name not in config['tasks']:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
        
        data = request.get_json()
        if 'enabled' not in data:
            return jsonify({'success': False, 'error': '缺少enabled参数'}), 400
        
        # 更新任务状态
        config['tasks'][task_name]['enabled'] = data['enabled']
        save_config(config)
        
        # 处理任务队列
        if task_manager:
            enabled_tasks = []  # 存储需要启用的任务
            with task_manager.task_lock:
                if not data['enabled']:
                    # 如果任务被禁用，从队列中移除
                    task_manager.task_queue = [(time, name) for time, name in task_manager.task_queue if name != task_name]
                    heapq.heapify(task_manager.task_queue)
                else:
                    # 如果任务被启用，清空队列并记录需要启用的任务
                    task_manager.task_queue = []
                    for name, task in config['tasks'].items():
                        if task['enabled']:
                            enabled_tasks.append(name)
            
            # 在释放锁后重新安排任务
            for name in enabled_tasks:
                task_manager.schedule_task(name)
        
        log(f"任务 {task_name} 状态已更新为: {data['enabled']}")
        return jsonify({'success': True})
    except Exception as e:
        log(f"更新任务状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/apps/<package_name>/close', methods=['POST'])
def close_app(package_name):
    """关闭指定的应用"""
    try:
        if task_manager:
           # 直接使用 ADB 关闭应用
            task_manager.adb.force_stop_app(package_name)
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