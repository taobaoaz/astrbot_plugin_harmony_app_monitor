from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api import AstrBotConfig
import asyncio
import json
import os
import time
import re
from typing import Any, Dict, List, Optional

# 动态导入Playwright
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("[鸿蒙监控] Playwright未安装,抓取功能将不可用。")

@register("harmony_app_monitor", "xianyao", "鸿蒙应用更新监控与推送插件", "1.0.0")
class HarmonyAppMonitor(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        """初始化插件"""
        super().__init__(context)
        self._ctx = context
        self.config = config  # AstrBotConfig对象
        self._monitor_task = None
        self._is_running = False
        self.enable_debug_log = False  # 先初始化，避免后续访问时报错
        
        logger.info(f"[鸿蒙监控] 插件初始化开始")
        
        # 初始化配置
        self._init_config()
        
        # 初始化数据存储
        self._init_data_store()
        
        # 启动监控任务
        self._start_monitor_task()
        
        logger.info(f"[鸿蒙监控] 插件初始化完成")
    
    def _init_config(self):
        """初始化配置参数"""
        try:
            # 先读取基础配置
            self.check_interval = int(self.config.get("check_interval_minutes", 30))
            self.command_prefix = str(self.config.get("command_prefix", "/"))
            self.enable_debug_log = bool(self.config.get("enable_debug_log", False))
            
            # 再读取列表配置
            # 1. 读取应用名称列表
            app_names_raw = self.config.get("app_name_list", "一日记账")
            self.app_names = self._parse_text_list(app_names_raw, "应用名称")
            
            # 2. 读取应用链接列表
            detail_urls_raw = self.config.get("detail_url_list", "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill")
            self.detail_urls = self._parse_text_list(detail_urls_raw, "应用链接")
            
            # 3. 读取版本选择器列表
            selectors_raw = self.config.get("version_selector_list", "span.content-value")
            self.version_selectors = self._parse_text_list(selectors_raw, "版本选择器")
            
            # 4. 通知配置
            groups_raw = self.config.get("notification_groups", "")
            self.notification_groups = self._parse_text_list(groups_raw, "通知群组")
            
            users_raw = self.config.get("notification_users", "")
            self.notification_users = self._parse_text_list(users_raw, "通知用户")
            
            # 5. 构建应用监控列表
            self.apps_to_watch = []
            min_length = min(len(self.app_names), len(self.detail_urls), len(self.version_selectors))
            
            if min_length > 0:
                for i in range(min_length):
                    self.apps_to_watch.append({
                        'app_name': self.app_names[i],
                        'detail_url': self.detail_urls[i],
                        'version_selector': self.version_selectors[i]
                    })
                
                # 检查是否有行数不匹配
                if len(self.app_names) != len(self.detail_urls) or len(self.app_names) != len(self.version_selectors):
                    logger.warning(f"[鸿蒙监控] 配置行数不匹配: 名称={len(self.app_names)}, 链接={len(self.detail_urls)}, 选择器={len(self.version_selectors)}")
                
                logger.info(f"[鸿蒙监控] 成功加载 {min_length} 个应用的监控配置")
            else:
                logger.warning("[鸿蒙监控] 配置不完整，至少一个列表为空")
                # 使用默认配置
                self.apps_to_watch = [{
                    'app_name': "一日记账",
                    'detail_url': "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill",
                    'version_selector': "span.content-value"
                }]
            
            # 输出配置信息
            if self.enable_debug_log:
                logger.info(f"[鸿蒙监控] 调试信息 - 配置详情:")
                logger.info(f"  监控应用数: {len(self.apps_to_watch)}")
                logger.info(f"  检查间隔: {self.check_interval}分钟")
                logger.info(f"  指令前缀: '{self.command_prefix}'")
                logger.info(f"  通知群组数: {len(self.notification_groups)}")
                logger.info(f"  通知用户数: {len(self.notification_users)}")
                logger.info(f"  启用调试: {self.enable_debug_log}")
                
                # 输出每个应用的配置
                for i, app in enumerate(self.apps_to_watch, 1):
                    logger.info(f"  应用{i}: {app['app_name']}")
                    logger.info(f"    链接: {app['detail_url']}")
                    logger.info(f"    选择器: {app['version_selector']}")
            
        except Exception as e:
            logger.error(f"[鸿蒙监控] 配置初始化失败: {e}")
            # 使用默认配置
            self.apps_to_watch = [{
                'app_name': "一日记账",
                'detail_url': "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill",
                'version_selector': "span.content-value"
            }]
            self.check_interval = 30
            self.command_prefix = "/"
            self.notification_groups = []
            self.notification_users = []
            self.enable_debug_log = False
    
    def _parse_text_list(self, text: str, field_name: str) -> List[str]:
        """解析文本列表，处理各种格式"""
        result = []
        
        if not text:
            return result
        
        try:
            # 如果是字符串，按行分割
            if isinstance(text, str):
                lines = text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line:  # 忽略空行
                        result.append(line)
            # 如果是列表，直接使用
            elif isinstance(text, list):
                for item in text:
                    if isinstance(item, str):
                        item = item.strip()
                        if item:
                            result.append(item)
            else:
                # 尝试转换为字符串
                result = [str(text).strip()]
                
        except Exception as e:
            logger.error(f"[鸿蒙监控] 解析{field_name}失败: {e}, 原始数据: {text}")
            result = []
        
        # 这里不再访问 self.enable_debug_log，因为可能在初始化过程中还未赋值
        # 如果需要调试日志，调用方可以在调用后自己输出
        return result
    
    def _init_data_store(self):
        """初始化数据存储"""
        try:
            # 尝试使用AstrBot的数据目录
            if hasattr(self._ctx, 'get_data_dir'):
                data_dir = self._ctx.get_data_dir()
                self.version_store_file = os.path.join(data_dir, 'harmony_versions.json')
            else:
                # 回退到插件目录
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                self.version_store_file = os.path.join(plugin_dir, 'harmony_versions.json')
            
            logger.info(f"[鸿蒙监控] 版本存储文件: {self.version_store_file}")
            self.version_store = self._load_version_store()
            
        except Exception as e:
            logger.error(f"[鸿蒙监控] 初始化数据存储失败: {e}")
            # 使用插件目录作为回退
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            self.version_store_file = os.path.join(plugin_dir, 'harmony_versions.json')
            self.version_store = {}
    
    def _start_monitor_task(self):
        """启动监控任务"""
        if self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info(f"[鸿蒙监控] 定时监控任务已启动，间隔: {self.check_interval}分钟")
        else:
            reason = []
            if not self.apps_to_watch:
                reason.append("监控列表为空")
            if not PLAYWRIGHT_AVAILABLE:
                reason.append("Playwright不可用")
            logger.warning(f"[鸿蒙监控] 监控未启动: {'; '.join(reason)}")
    
    def _load_version_store(self) -> Dict[str, str]:
        """加载版本记录"""
        try:
            if os.path.exists(self.version_store_file):
                with open(self.version_store_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[鸿蒙监控] 加载版本记录失败: {e}")
        return {}
    
    def _save_version_store(self):
        """保存版本记录"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.version_store_file), exist_ok=True)
            with open(self.version_store_file, 'w', encoding='utf-8') as f:
                json.dump(self.version_store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[鸿蒙监控] 保存版本记录失败: {e}")
    
    async def _send_notification(self, app_name: str, old_ver: str, new_ver: str, url: str):
        """发送更新通知"""
        message = (
            f"🚀 鸿蒙应用更新通知\n\n"
            f"📱 应用: {app_name}\n"
            f"🔄 版本: v{old_ver} → v{new_ver}\n"
            f"🔗 链接: {url}\n"
            f"⏰ 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        logger.info(f"[鸿蒙监控] 发现更新: {app_name} v{old_ver} -> v{new_ver}")
        
        # 发送到所有通知群组
        for group_id in self.notification_groups:
            try:
                # 根据实际的消息发送API调整
                # 示例：await self._ctx.send_group_message(group_id, message)
                logger.info(f"[鸿蒙监控] 发送通知到群组: {group_id}")
            except Exception as e:
                logger.error(f"[鸿蒙监控] 发送群组通知失败 {group_id}: {e}")
        
        # 发送到所有通知用户
        for user_id in self.notification_users:
            try:
                # 根据实际的消息发送API调整
                # 示例：await self._ctx.send_private_message(user_id, message)
                logger.info(f"[鸿蒙监控] 发送通知到用户: {user_id}")
            except Exception as e:
                logger.error(f"[鸿蒙监控] 发送用户通知失败 {user_id}: {e}")
    
    async def _monitor_loop(self):
        """定时监控循环"""
        while self._is_running:
            try:
                await self._check_all_apps()
            except Exception as e:
                logger.error(f"[鸿蒙监控] 监控循环出错: {e}")
            
            # 等待指定间隔
            await asyncio.sleep(self.check_interval * 60)
    
    async def _check_all_apps(self):
        """检查所有应用"""
        if not self.apps_to_watch:
            return
            
        logger.info(f"[鸿蒙监控] 开始检查 ({time.strftime('%H:%M:%S')})")
        
        for app in self.apps_to_watch:
            app_name = app.get('app_name', '未知应用')
            detail_url = app.get('detail_url', '')
            selector = app.get('version_selector', 'span.content-value')
            
            if not detail_url:
                logger.warning(f"[鸿蒙监控] 应用 '{app_name}' 缺少链接")
                continue
                
            version = await self._fetch_version(detail_url, selector)
            if not version:
                logger.warning(f"[鸿蒙监控] 无法获取 {app_name} 的版本号")
                continue
                
            old_version = self.version_store.get(app_name)
            
            if old_version is None:
                self.version_store[app_name] = version
                self._save_version_store()
                logger.info(f"[鸿蒙监控] 首次记录 {app_name}: v{version}")
            elif version != old_version:
                self.version_store[app_name] = version
                self._save_version_store()
                logger.info(f"[鸿蒙监控] 发现更新 {app_name}: v{old_version} -> v{version}")
                await self._send_notification(app_name, old_version, version, detail_url)
    
    async def _fetch_version(self, url: str, selector: str) -> str:
        """抓取版本号"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning(f"[鸿蒙监控] Playwright不可用，无法抓取: {url}")
            return ""
            
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # 设置超时和重试
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.wait_for_selector(selector, timeout=30000)
                
                text = await page.text_content(selector)
                await browser.close()
                
                return text.strip() if text else ""
        except PlaywrightTimeoutError:
            logger.error(f"[鸿蒙监控] 抓取超时: {url}")
            return ""
        except Exception as e:
            logger.error(f"[鸿蒙监控] 抓取失败 {url}: {e}")
            return ""
    
    # ---------- 插件管理指令 ----------
    
    @filter.command("status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看状态 /status"""
        status = [
            "📊 鸿蒙监控状态",
            f"• 监控应用: {len(self.apps_to_watch)}个",
            f"• 检查间隔: {self.check_interval}分钟",
            f"• 运行状态: {'✅ 运行中' if self._is_running else '❌ 已停止'}",
            f"• Playwright: {'✅ 可用' if PLAYWRIGHT_AVAILABLE else '❌ 不可用'}",
            f"• 通知群组: {len(self.notification_groups)}个",
            f"• 通知用户: {len(self.notification_users)}个",
            f"• 版本记录: {len(self.version_store)}个",
            f"• 调试模式: {'✅ 开启' if self.enable_debug_log else '❌ 关闭'}"
        ]
        yield event.plain_result("\n".join(status))
    
    @filter.command("check")
    async def cmd_check(self, event: AstrMessageEvent):
        """立即检查更新 /check"""
        yield event.plain_result("🔍 正在检查所有应用更新，请稍候...")
        
        start_time = time.time()
        await self._check_all_apps()
        elapsed = time.time() - start_time
        
        # 获取当前版本信息
        current_info = []
        for app in self.apps_to_watch:
            app_name = app['app_name']
            version = self.version_store.get(app_name, "未知")
            current_info.append(f"  • {app_name}: v{version}")
        
        result = [
            f"✅ 检查完成！耗时: {elapsed:.1f}秒",
            "",
            "📋 当前版本信息:"
        ] + current_info
        
        yield event.plain_result("\n".join(result))
    
    @filter.command("list")
    async def cmd_list(self, event: AstrMessageEvent):
        """列出监控应用 /list"""
        if not self.apps_to_watch:
            yield event.plain_result("📭 当前没有监控任何应用")
            return
        
        result = ["📱 监控应用列表:"]
        for i, app in enumerate(self.apps_to_watch, 1):
            current_version = self.version_store.get(app['app_name'], '未知')
            result.append(f"{i}. {app['app_name']} (当前: v{current_version})")
            result.append(f"   链接: {app['detail_url'][:50]}...")
            result.append(f"   选择器: {app['version_selector']}")
            result.append("")
        
        result.append(f"总计: {len(self.apps_to_watch)} 个应用")
        yield event.plain_result("\n".join(result))
    
    @filter.command("notify")
    async def cmd_notify(self, event: AstrMessageEvent):
        """查看通知配置 /notify"""
        groups_info = "无" if not self.notification_groups else "\n".join([f"  • {g}" for g in self.notification_groups])
        users_info = "无" if not self.notification_users else "\n".join([f"  • {u}" for u in self.notification_users])
        
        result = [
            "🔔 通知配置:",
            "",
            "📢 通知群组:",
            groups_info,
            "",
            "👤 通知用户:",
            users_info,
            "",
            f"总计: {len(self.notification_groups)} 个群组, {len(self.notification_users)} 个用户"
        ]
        
        yield event.plain_result("\n".join(result))
    
    @filter.command("add_notify")
    async def cmd_add_notify(self, event: AstrMessageEvent):
        """添加通知目标 /add_notify <类型> <ID>"""
        args = event.get_plain_text().strip().split()
        
        if len(args) < 3:
            yield event.plain_result("❌ 用法: /add_notify <group|user> <ID>\n例如: /add_notify group 123456789\n       /add_notify user 987654321")
            return
        
        target_type = args[1].lower()
        target_id = args[2]
        
        if target_type == "group":
            if target_id in self.notification_groups:
                yield event.plain_result(f"❌ 群组 {target_id} 已存在")
            else:
                self.notification_groups.append(target_id)
                # 保存配置
                self._save_config_to_file()
                yield event.plain_result(f"✅ 已添加通知群组: {target_id}")
                
        elif target_type == "user":
            if target_id in self.notification_users:
                yield event.plain_result(f"❌ 用户 {target_id} 已存在")
            else:
                self.notification_users.append(target_id)
                # 保存配置
                self._save_config_to_file()
                yield event.plain_result(f"✅ 已添加通知用户: {target_id}")
        else:
            yield event.plain_result("❌ 类型错误，请使用 'group' 或 'user'")
    
    @filter.command("del_notify")
    async def cmd_del_notify(self, event: AstrMessageEvent):
        """删除通知目标 /del_notify <类型> <ID或序号>"""
        args = event.get_plain_text().strip().split()
        
        if len(args) < 3:
            yield event.plain_result("❌ 用法: /del_notify <group|user> <ID或序号>\n例如: /del_notify group 123456789\n       /del_notify user 1")
            return
        
        target_type = args[1].lower()
        target = args[2]
        
        if target_type == "group":
            if target.isdigit():
                # 按序号删除
                index = int(target) - 1
                if 0 <= index < len(self.notification_groups):
                    removed_id = self.notification_groups.pop(index)
                    self._save_config_to_file()
                    yield event.plain_result(f"✅ 已删除群组: {removed_id}")
                else:
                    yield event.plain_result(f"❌ 序号 {target} 无效，当前有 {len(self.notification_groups)} 个群组")
            else:
                # 按ID删除
                if target in self.notification_groups:
                    self.notification_groups.remove(target)
                    self._save_config_to_file()
                    yield event.plain_result(f"✅ 已删除群组: {target}")
                else:
                    yield event.plain_result(f"❌ 未找到群组: {target}")
                    
        elif target_type == "user":
            if target.isdigit():
                # 按序号删除
                index = int(target) - 1
                if 0 <= index < len(self.notification_users):
                    removed_id = self.notification_users.pop(index)
                    self._save_config_to_file()
                    yield event.plain_result(f"✅ 已删除用户: {removed_id}")
                else:
                    yield event.plain_result(f"❌ 序号 {target} 无效，当前有 {len(self.notification_users)} 个用户")
            else:
                # 按ID删除
                if target in self.notification_users:
                    self.notification_users.remove(target)
                    self._save_config_to_file()
                    yield event.plain_result(f"✅ 已删除用户: {target}")
                else:
                    yield event.plain_result(f"❌ 未找到用户: {target}")
        else:
            yield event.plain_result("❌ 类型错误，请使用 'group' 或 'user'")
    
    def _save_config_to_file(self):
        """保存配置到文件"""
        try:
            # 获取插件目录
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(plugin_dir, 'user_config.json')
            
            config_data = {
                'notification_groups': self.notification_groups,
                'notification_users': self.notification_users
            }
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[鸿蒙监控] 用户配置已保存到: {config_file}")
            return True
        except Exception as e:
            logger.error(f"[鸿蒙监控] 保存用户配置失败: {e}")
            return False
    
    @filter.command("refresh")
    async def cmd_refresh(self, event: AstrMessageEvent):
        """刷新配置 /refresh"""
        # 保存当前运行状态
        was_running = self._is_running
        
        # 停止监控任务
        if self._is_running and self._monitor_task:
            self._is_running = False
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(1)
        
        # 重新初始化配置
        self._init_config()
        
        # 重新启动监控任务
        if was_running and self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        yield event.plain_result("✅ 配置已刷新，监控任务已重启")
    
    @filter.command("help")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助 /help"""
        help_text = [
            "📖 鸿蒙应用监控插件帮助",
            "",
            "🔧 配置指令:",
            "  /status - 查看插件状态",
            "  /check - 立即检查更新",
            "  /list - 列出监控应用",
            "  /notify - 查看通知配置",
            "  /add_notify <group|user> <ID> - 添加通知目标",
            "  /del_notify <group|user> <ID或序号> - 删除通知目标",
            "  /refresh - 刷新配置",
            "  /help - 显示帮助",
            "",
            "📝 配置说明:",
            "  1. 在AstrBot管理面板配置插件",
            "  2. 应用名称、链接、选择器需按行对应",
            "  3. 修改配置后使用 /refresh 生效",
            "",
            "💡 提示:",
            "  • 确保已安装 Playwright: pip install playwright",
            "  • 首次使用需安装浏览器: playwright install chromium",
            "  • 可在Web界面配置通知群组和用户"
        ]
        
        yield event.plain_result("\n".join(help_text))
    
    def on_disable(self):
        """插件禁用时调用"""
        logger.info("[鸿蒙监控] 插件正在禁用...")
        if self._is_running and self._monitor_task:
            self._is_running = False
            self._monitor_task.cancel()
            logger.info("[鸿蒙监控] 监控任务已停止")