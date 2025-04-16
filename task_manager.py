import cv2
import numpy as np
from adb_controller import ADBController
import time
import pytesseract  # 需要安装pytesseract
import os
from datetime import datetime, timedelta
import heapq
import threading
from logger import log
from telegram_notifier import send_notification

class TaskManager:
    def __init__(self, app_package):
        self.adb = ADBController()
        self.app_package = app_package
        self.task_queue = []  # 优先队列，按执行时间排序
        self.task_lock = threading.Lock()  # 用于线程安全操作
        self.task_next_run = {}  # 存储每个任务的下次执行时间
        self.running = True  # 控制任务循环
        self.idle_timeout = 300  # 空闲超时时间（秒），超过此时间关闭应用
        self.startup_wait_time = 30  # 应用启动等待时间（秒）
        self.app_closed = True  # 应用是否已关闭
        self.startup_actions = []  # 应用启动时执行的操作
        # 调试配置
        self.save_images = False
        self.save_path = "images/tmp"
        self.last_cleanup_time = datetime.now()
        self.cleanup_interval = 60  # 清理间隔，默认1小时
        self.image_retention_hours = 1  # 图片保留小时数，默认24小时
        log(f"任务管理器初始化完成，应用包名: {app_package}")
    
    def start(self):
        """启动任务管理器"""
        # 初始化所有任务的下次执行时间为现在
        for task_name in self.task_next_run:
            self.schedule_task(task_name)
        
        # 启动任务执行线程
        self.task_thread = threading.Thread(target=self.task_loop)
        self.task_thread.daemon = True
        self.task_thread.start()
    
    def stop(self):
        """停止任务管理器"""
        self.running = False
        if hasattr(self, 'task_thread'):
            self.task_thread.join(timeout=5)
    
    def schedule_task(self, task_name, delay=0):
        """安排任务在指定延迟后执行"""
        next_run = datetime.now() + timedelta(seconds=delay)
        with self.task_lock:
            self.task_next_run[task_name] = next_run
            # 将任务添加到优先队列
            heapq.heappush(self.task_queue, (next_run, task_name))
        log(f"任务 {task_name} 已安排在 {next_run.strftime('%Y-%m-%d %H:%M:%S')} 执行")
    
    def task_loop(self):
        """任务执行循环"""
        while self.running:
            now = datetime.now()

            # 检查是否需要清理图片
            if (now - self.last_cleanup_time).total_seconds() >= self.cleanup_interval:
                self.cleanup_old_images()
                self.last_cleanup_time = now
            
            # 检查是否有任务需要执行
            with self.task_lock:
                if self.task_queue and self.task_queue[0][0] <= now:
                    # 获取下一个要执行的任务
                    _, task_name = heapq.heappop(self.task_queue)
                    # 释放锁后执行任务
                    self.task_lock.release()
                    
                    try:
                        # 执行任务
                        self.execute_task_by_name(task_name)
                    except Exception as e:
                        log(f"执行任务 {task_name} 出错: {e}")
                    
                    # 重新获取锁
                    self.task_lock.acquire()
                else:
                    # 检查下一个任务的等待时间
                    if self.task_queue:
                        next_task_time = self.task_queue[0][0]
                        wait_seconds = (next_task_time - now).total_seconds()
                        
                        # print(f"下一个任务等待时间: {wait_seconds}秒")
                        
                        # 如果等待时间超过阈值，关闭应用
                        if wait_seconds > self.idle_timeout and not self.app_closed:
                            log(f"等待时间 {wait_seconds}秒 超过空闲阈值 {self.idle_timeout}秒")
                            self.task_lock.release()
                            self.close_app_for_idle()
                            # 重新获取锁
                            self.task_lock.acquire()
                    
                    # 没有任务需要执行，释放锁
                    self.task_lock.release()
                    # 等待一段时间
                    time.sleep(1)
                    # 重新获取锁
                    self.task_lock.acquire()
    
    def execute_task_by_name(self, task_name):
        """根据任务名称执行任务"""
        from main import load_config
        config = load_config()
        
        if task_name in config['tasks'] and config['tasks'][task_name]['enabled']:
            task_config = config['tasks'][task_name]
            # print(f"开始执行任务: {task_name}")
            
            # 执行任务并获取冷却时间
            cooldown_time = self.execute_task(task_config)
            
            # 如果没有通过get_countdown操作获取到冷却时间，使用配置中的时间
            if cooldown_time is None:
                cooldown_time = 600  # 默认冷却时间
                if 'cooldown' in task_config:
                    if task_config['cooldown']['type'] == 'fixed':
                        cooldown_time = task_config['cooldown'].get('time', cooldown_time)
            
            # 重新安排任务
            self.schedule_task(task_name, cooldown_time)
        else:
            log(f"任务 {task_name} 不存在或已禁用")

    def ensure_app_running(self):
        """确保应用在前台运行"""
        was_closed = self.app_closed
        
        if not self.adb.is_app_foreground(self.app_package):
            log(f"应用 {self.app_package} 不在前台，正在启动...")
            self.adb.launch_app(self.app_package)
            log(f"等待应用启动 {self.startup_wait_time} 秒...")
            time.sleep(self.startup_wait_time)  # 使用配置的启动等待时间
            self.app_closed = False
            
            # 如果应用之前是关闭状态，或者检测到应用异常退出，执行启动操作
            if was_closed:
                log("应用之前处于关闭状态，执行启动操作...")
                self.perform_startup_actions()
                log("启动操作完成，继续执行任务...")
            
            # 再次检查应用是否在前台
            if not self.adb.is_app_foreground(self.app_package):
                raise Exception(f"无法将应用 {self.app_package} 切换到前台")

    def get_countdown_time(self, region):
        """识别屏幕上的倒计时时间，支持多种格式"""
        try:
            # 获取屏幕截图
            screen = self.adb.screenshot()
            
            # 裁剪倒计时区域
            roi = screen[region['top']:region['bottom'], region['left']:region['right']]
            
            # 转换为灰度图
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            
            # 二值化处理，使用自适应阈值以提高文字识别率
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 11, 2
            )
            
            # 使用OCR识别文字，配置为识别数字和冒号
            text = pytesseract.image_to_string(
                binary,
                config='--psm 7 -c tessedit_char_whitelist=0123456789:'
            ).strip()
            
            log(f"识别到的原始倒计时文本: {text}")
            
            # 保存识别区域的图片（用于调试）
            self.save_image(binary, 'countdown')
            
            # 清理文本，只保留数字和冒号
            cleaned_text = ''.join(char for char in text if char.isdigit() or char == ':')
            log(f"清理后的文本: {cleaned_text}")
            
            # 处理不同格式的时间字符串
            if ':' in cleaned_text:
                # 处理包含冒号的格式 (HH:MM:SS 或 MM:SS)
                parts = cleaned_text.split(':')
                if len(parts) == 3:
                    # HH:MM:SS 格式
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    seconds = int(parts[2])
                elif len(parts) == 2:
                    # MM:SS 格式
                    hours = 0
                    minutes = int(parts[0])
                    seconds = int(parts[1])
                else:
                    log(f"无效的时间格式: {cleaned_text}")
                    return None
            else:
                # 处理无冒号的纯数字格式
                if len(cleaned_text) == 6:
                    # HHMMSS 格式
                    hours = int(cleaned_text[:2])
                    minutes = int(cleaned_text[2:4])
                    seconds = int(cleaned_text[4:])
                elif len(cleaned_text) == 4:
                    # MMSS 格式
                    hours = 0
                    minutes = int(cleaned_text[:2])
                    seconds = int(cleaned_text[2:])
                else:
                    log(f"无法解析的时间格式: {cleaned_text}")
                    return None
            
            # 验证时间值的合理性
            if hours >= 0 and minutes >= 0 and minutes < 60 and seconds >= 0 and seconds < 60:
                total_seconds = hours * 3600 + minutes * 60 + seconds
                log(f"解析倒计时: {hours}时{minutes}分{seconds}秒，共{total_seconds}秒")
                return total_seconds
            else:
                log(f"时间值超出范围: {hours}:{minutes}:{seconds}")
                return None
            
        except Exception as e:
            log(f"倒计时识别失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def find_and_click_image(self, template_path, threshold=0.8, click_offset=(0, 0), notify=False, task_name=None):
        """在屏幕上查找模板图片并点击匹配位置"""
        try:
            # 获取屏幕截图
            screen = self.adb.screenshot()
            
            # 检查屏幕截图是否有效
            if screen is None or screen.size == 0:
                log("获取屏幕截图失败")
                return False
            
            # 转换为BGR格式（OpenCV默认格式）
            screen_bgr = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
            
            # 读取模板图片
            template = cv2.imread(template_path)
            if template is None:
                log(f"无法读取模板图片: {template_path}")
                return False
            
            # 保存调试图片
            self.save_image(screen_bgr, 'screen')
            # self.save_image(template, 'template')
            
            # 进行模板匹配
            result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
            
            # 获取最佳匹配位置
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            log(f"最佳匹配度: {max_val}, 位置: {max_loc}")
            
            # 如果匹配度超过阈值，点击匹配位置
            if max_val > threshold:
                # 计算点击位置（模板中心 + 偏移量）
                h, w = template.shape[:2]
                center_x = max_loc[0] + w // 2 + click_offset[0]
                center_y = max_loc[1] + h // 2 + click_offset[1]
                
                # 如果启用了通知
                if notify:
                    # 保存匹配成功的图片（如果启用了保存）
                    matched_image_path = None
                    if self.save_images:
                        matched_image_path = self.save_image(screen_bgr, 'matched')
                    
                    task_info = f"\n任务名称: {task_name}" if task_name else ""
                    message = f"图片匹配成功！{task_info}\n匹配度: {max_val:.2f}\n阈值: {threshold}\n点击位置: ({center_x}, {center_y})"
                    send_notification(message, matched_image_path)
                
                # 点击位置
                self.adb.tap(center_x, center_y)
                log(f"点击位置: ({center_x}, {center_y})")
                return True
            else:
                log(f"未找到匹配图片，最佳匹配度: {max_val}")
                return False
            
        except Exception as e:
            log(f"查找图片出错: {e}")
            import traceback
            traceback.print_exc()
            return False

    def execute_task(self, task_config):
        log(f"执行任务: {task_config['name']}")
        
        # 确保应用在前台
        self.ensure_app_running()
        
        # 执行任务动作
        i = 0
        cooldown_time = None  # 用于存储识别到的冷却时间
        
        while i < len(task_config['actions']):
            action = task_config['actions'][i]
            
            # 每个操作前都检查一次应用状态
            self.ensure_app_running()
            
            if action['type'] == 'get_countdown':
                # 获取倒计时操作
                region = action.get('region')
                if region:
                    countdown = self.get_countdown_time(region)
                    if countdown:
                        log(f"获取到倒计时: {countdown}秒")
                        cooldown_time = countdown  # 保存识别到的冷却时间
                    else:
                        log("倒计时获取失败")
                i += 1
            
            elif action['type'] == 'click':
                self.adb.tap(action['x'], action['y'])
                i += 1
            
            elif action['type'] == 'long_press':
                # 获取长按参数
                x = action['x']
                y = action['y']
                duration = action.get('duration', 1000)  # 默认长按1000毫秒
                
                log(f"执行长按操作: ({x}, {y}), 持续时间: {duration}ms")
                self.adb.long_press(x, y, duration)
                i += 1
            
            elif action['type'] == 'swipe':
                # 获取滑动参数
                start_x = action['start_x']
                start_y = action['start_y']
                end_x = action['end_x']
                end_y = action['end_y']
                duration = action.get('duration', 500)  # 默认滑动时间500毫秒
                
                log(f"执行滑动操作: ({start_x}, {start_y}) -> ({end_x}, {end_y})")
                self.adb.swipe(start_x, start_y, end_x, end_y, duration)
                i += 1
            
            elif action['type'] == 'image_check':
                # 获取自定义阈值和通知设置
                threshold = action.get('threshold', 0.8)
                notify = action.get('notify', False)
                skip_if_match = action.get('skip_if_match', False)
                skip_count = action.get('skip_count', 0)
                
                # 执行图像检查
                if self.check_image(action['image'], action['region'], threshold, notify, task_config['name']):
                    
                    # 如果设置了匹配成功跳过后续操作
                    if skip_if_match and skip_count > 0:
                        log(f"图像匹配成功，跳过后续 {skip_count} 个操作（包含当前操作）")
                        i += skip_count  # 不再 +1，因为 skip_count 已经包含当前操作
                    else:
                        # 计算区域中心点进行点击
                        x = (action['region']['left'] + action['region']['right']) // 2
                        y = (action['region']['top'] + action['region']['bottom']) // 2
                        self.adb.tap(x, y)
                        i += 1
                else:
                    i += 1
            
            elif action['type'] == 'find_image':
                # 获取可选参数
                threshold = action.get('threshold', 0.8)
                offset_x = action.get('offset_x', 0)
                offset_y = action.get('offset_y', 0)
                notify = action.get('notify', False)
                skip_if_match = action.get('skip_if_match', False)
                skip_count = action.get('skip_count', 0)
                
                # 查找并点击图片
                if self.find_and_click_image(
                    action['image'], 
                    threshold=threshold,
                    click_offset=(offset_x, offset_y),
                    notify=notify,
                    task_name=task_config['name']
                ):
                    # 如果匹配成功且设置了跳过
                    if skip_if_match and skip_count > 0:
                        log(f"图像匹配成功，跳过后续 {skip_count} 个操作（包含当前操作）")
                        i += skip_count  # 不再 +1，因为 skip_count 已经包含当前操作
                    else:
                        i += 1
                else:
                    i += 1
            
            elif action['type'] == 'wait':
                time.sleep(action['time'])
                i += 1

        # 返回识别到的冷却时间
        return cooldown_time

    def save_image(self, image, prefix='cropped'):
        """保存图片到指定目录"""
        # 如果未启用图片保存，直接返回
        if not self.save_images:
            return None
        
        try:
            # 确保保存目录存在
            if not os.path.exists(self.save_path):
                os.makedirs(self.save_path)
            
            # 生成文件名，包含时间戳
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'{self.save_path}/{prefix}_{timestamp}.png'
            
            # 保存图片
            cv2.imwrite(filename, image)
            log(f"调试图片已保存: {filename}")
            return filename
        except Exception as e:
            log(f"保存调试图片失败: {e}")
            return None

    def check_image(self, template_path, region, threshold=0.8, notify=False, task_name=None):
        """检查指定区域是否匹配模板图片，使用自定义阈值"""
        try:
            # 获取屏幕截图
            screen = self.adb.screenshot()
            
            # 检查屏幕截图是否有效
            if screen is None or screen.size == 0:
                log("获取屏幕截图失败")
                return False
            
            # 检查区域坐标是否有效
            screen_height, screen_width = screen.shape[:2]
            if (region['left'] < 0 or region['top'] < 0 or 
                region['right'] > screen_width or region['bottom'] > screen_height or
                region['left'] >= region['right'] or region['top'] >= region['bottom']):
                log(f"区域坐标无效: {region}, 屏幕大小: {screen_width}x{screen_height}")
                return False
            
            # 裁剪感兴趣区域
            try:
                roi = screen[region['top']:region['bottom'], region['left']:region['right']]
                if roi.size == 0:
                    log("裁剪区域为空")
                    return False
            except Exception as e:
                log(f"裁剪区域出错: {e}")
                return False
            
            # 转换为BGR格式（OpenCV默认格式）
            try:
                roi_bgr = cv2.cvtColor(roi, cv2.COLOR_RGB2BGR)
            except Exception as e:
                log(f"颜色空间转换出错: {e}")
                return False
            
            # 保存裁剪区域的图片（用于调试）
            self.save_image(roi_bgr, 'cropped')
            
            # 读取模板图片
            template = cv2.imread(template_path)
            if template is None:
                log(f"无法读取模板图片: {template_path}")
                return False
            
            # 检查两个图像的形状和类型是否匹配
            if roi_bgr.shape != template.shape:
                log(f"图像形状不匹配: ROI {roi_bgr.shape}, 模板 {template.shape}")
                return False
            
            if roi_bgr.dtype != template.dtype:
                log(f"图像类型不匹配: ROI {roi_bgr.dtype}, 模板 {template.dtype}")
                template = template.astype(roi_bgr.dtype)
            
            # 进行模板匹配
            try:
                result = cv2.matchTemplate(roi_bgr, template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                log(f"模板匹配度: {max_val}, 阈值: {threshold}")
                
                # 如果匹配成功且启用了通知
                if max_val > threshold and notify:
                    # 保存匹配成功的图片（如果启用了保存）
                    matched_image_path = None
                    if self.save_images:
                        matched_image_path = self.save_image(roi_bgr, 'matched')
                    
                    # 发送通知
                    task_info = f"\n任务名称: {task_name}" if task_name else ""
                    message = f"图片匹配成功！{task_info}\n匹配度: {max_val:.2f}\n阈值: {threshold}\n区域: {region}"
                    send_notification(message, matched_image_path)
                
                return max_val > threshold
            except Exception as e:
                log(f"模板匹配出错: {e}")
                return False
        
        except Exception as e:
            log(f"图片匹配过程中出现未知错误: {e}")
            import traceback
            traceback.print_exc()
            return False

    def close_app_for_idle(self):
        """关闭应用进入待机状态"""
        if not self.app_closed:
            log(f"下一个任务等待时间较长，关闭应用 {self.app_package} 进入待机状态")
            self.adb.force_stop_app(self.app_package)
            self.app_closed = True

    def set_startup_actions(self, actions):
        """设置应用启动时执行的操作"""
        self.startup_actions = actions

    def perform_startup_actions(self):
        """执行应用启动后的操作"""
        if not self.startup_actions:
            return
        
        log("执行应用启动操作...")
        i = 0
        while i < len(self.startup_actions):
            action = self.startup_actions[i]
            try:
                if action['type'] == 'click':
                    self.adb.tap(action['x'], action['y'])
                    i += 1
                
                elif action['type'] == 'long_press':
                    x = action['x']
                    y = action['y']
                    duration = action.get('duration', 1000)
                    log(f"执行长按操作: ({x}, {y}), 持续时间: {duration}ms")
                    self.adb.long_press(x, y, duration)
                    i += 1
                
                elif action['type'] == 'wait':
                    time.sleep(action['time'])
                    i += 1
                
                elif action['type'] == 'image_check':
                    # 获取自定义阈值（如果有）
                    threshold = action.get('threshold', 0.8)
                    
                    # 检查是否有条件执行标志
                    skip_if_match = action.get('skip_if_match', False)
                    skip_count = action.get('skip_count', 0)
                    
                    if self.check_image(action['image'], action['region'], threshold):
                        # 计算区域中心点进行点击
                        x = (action['region']['left'] + action['region']['right']) // 2
                        y = (action['region']['top'] + action['region']['bottom']) // 2
                        log(f"图像匹配成功，点击位置: ({x}, {y})")
                        self.adb.tap(x, y)
                        
                        # 如果设置了匹配成功跳过后续操作
                        if skip_if_match and skip_count > 0:
                            log(f"图像匹配成功，跳过后续 {skip_count} 个操作")
                            i += skip_count + 1  # +1 是因为还要跳过当前操作
                        else:
                            i += 1
                    else:
                        log("图像匹配失败，跳过点击")
                        i += 1
                
                elif action['type'] == 'find_image':
                    threshold = action.get('threshold', 0.8)
                    offset_x = action.get('offset_x', 0)
                    offset_y = action.get('offset_y', 0)
                    skip_if_match = action.get('skip_if_match', False)
                    skip_count = action.get('skip_count', 0)
                    
                    if self.find_and_click_image(
                        action['image'], 
                        threshold=threshold,
                        click_offset=(offset_x, offset_y)
                    ):
                        # 如果匹配成功且设置了跳过
                        if skip_if_match and skip_count > 0:
                            log(f"图像匹配成功，跳过后续 {skip_count} 个操作")
                            i += skip_count + 1
                        else:
                            i += 1
                    else:
                        i += 1
                
            except Exception as e:
                log(f"执行启动操作出错: {e}")
                i += 1
        
        log("应用启动操作完成")

    def cleanup_old_images(self):
        """清理过期的图片文件"""
        try:
            if not os.path.exists(self.save_path):
                return
            
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(hours=self.image_retention_hours)
            
            for filename in os.listdir(self.save_path):
                file_path = os.path.join(self.save_path, filename)
                if os.path.isfile(file_path):
                    # 获取文件修改时间
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff_time:
                        try:
                            os.remove(file_path)
                            log(f"删除过期图片: {filename}")
                        except Exception as e:
                            log(f"删除图片失败 {filename}: {e}")
        except Exception as e:
            log(f"清理图片时出错: {e}")