from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
import asyncio
import json
import os
import time
import re
from typing import Any, Dict, List

# 动态导入Playwright
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("[鸿蒙监控] Playwright未安装,抓取功能将不可用。")

@register("harmony_app_monitor", "xianyao", "鸿蒙应用更新监控与推送插件", "1.0.0")
class HarmonyAppMonitor(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._ctx = context
        self._monitor_task = None
        self._is_running = False
        
        # 初始化变量
        self.apps_to_watch = []
        self.check_interval = 30
        self.command_prefix = "/"
        
        logger.info(f"[鸿蒙监控] DEBUG: ctx 对象类型: {type(self._ctx)}")

    async def initialize(self):
        """初始化插件"""
        logger.info("[鸿蒙监控] DEBUG: initialize方法被调用")
        
        # 1. 获取配置
        plugin_config = self._get_plugin_config()
        
        # 2. 从配置中读取数据，处理None值
        app_names = plugin_config.get("app_name_list")
        detail_urls = plugin_config.get("detail_url_list")
        version_selectors = plugin_config.get("version_selector_list")
        
        logger.info(f"[鸿蒙监控] DEBUG: 从配置读取:")
        logger.info(f"  - app_name_list: {app_names}")
        logger.info(f"  - detail_url_list: {detail_urls}")
        logger.info(f"  - version_selector_list: {version_selectors}")
        
        # 3. 处理None值
        if app_names is None:
            app_names = []
        if detail_urls is None:
            detail_urls = []
        if version_selectors is None:
            version_selectors = []
        
        # 4. 如果是字符串，按行分割
        if isinstance(app_names, str):
            app_names = [line.strip() for line in app_names.split('\n') if line.strip()]
        if isinstance(detail_urls, str):
            detail_urls = [line.strip() for line in detail_urls.split('\n') if line.strip()]
        if isinstance(version_selectors, str):
            version_selectors = [line.strip() for line in version_selectors.split('\n') if line.strip()]
        
        # 5. 组合应用数据
        self.apps_to_watch = []
        min_length = min(len(app_names), len(detail_urls), len(version_selectors))
        
        if min_length > 0:
            for i in range(min_length):
                self.apps_to_watch.append({
                    'app_name': app_names[i],
                    'detail_url': detail_urls[i],
                    'version_selector': version_selectors[i]
                })
            logger.info(f"[鸿蒙监控] 从配置成功组合 {min_length} 个应用的监控配置。")
        else:
            logger.warning("[鸿蒙监控] 配置不完整，至少一个列表为空")
            # 使用默认配置
            self.apps_to_watch = [{
                'app_name': "一记账单",
                'detail_url': "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill",
                'version_selector': "span.content-value"
            }]
            logger.info("[鸿蒙监控] 使用默认配置")
        
        # 6. 读取其他配置，处理None值
        check_interval = plugin_config.get('check_interval_minutes')
        command_prefix = plugin_config.get('command_prefix')
        
        if check_interval is not None:
            self.check_interval = check_interval
        else:
            self.check_interval = 30
            
        if command_prefix is not None:
            self.command_prefix = command_prefix
        else:
            self.command_prefix = "/"
        
        logger.info(f"[鸿蒙监控] 初始化完成！监控应用: {len(self.apps_to_watch)}个, 间隔: {self.check_interval}分钟")
        
        # 7. 初始化数据存储
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.version_store_file = os.path.join(plugin_dir, 'harmony_versions.json')
        self.version_store = self._load_version_store()
        
        logger.info(f"[鸿蒙监控] 版本存储文件: {self.version_store_file}")
        
        # 8. 启动监控任务
        if self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("[鸿蒙监控] 定时监控任务已启动。")
        else:
            reason = []
            if not self.apps_to_watch:
                reason.append("监控列表为空")
            if not PLAYWRIGHT_AVAILABLE:
                reason.append("Playwright不可用")
            logger.warning(f"[鸿蒙监控] 监控未启动: {'; '.join(reason)}")

    def _get_plugin_config(self):
        """获取插件配置"""
        plugin_config = {}
        
        # 方法1: 尝试从AstrBot配置系统获取
        try:
            if hasattr(self._ctx, 'get_config'):
                config = self._ctx.get_config("harmony_app_monitor")
                logger.info(f"[鸿蒙监控] DEBUG: get_config返回: {type(config)}")
                
                # 检查配置对象是否有我们需要的属性
                if config is not None:
                    if hasattr(config, '__dict__'):
                        # 这是一个对象，尝试获取属性
                        for key in ['app_name_list', 'detail_url_list', 'version_selector_list', 
                                   'check_interval_minutes', 'command_prefix']:
                            if hasattr(config, key):
                                value = getattr(config, key)
                                plugin_config[key] = value
                                logger.info(f"[鸿蒙监控] DEBUG: 从config对象获取 {key}: {value}")
                    elif isinstance(config, dict):
                        # 这是一个字典
                        for key in ['app_name_list', 'detail_url_list', 'version_selector_list', 
                                   'check_interval_minutes', 'command_prefix']:
                            if key in config:
                                plugin_config[key] = config[key]
                                logger.info(f"[鸿蒙监控] DEBUG: 从config字典获取 {key}: {config[key]}")
        except Exception as e:
            logger.error(f"[鸿蒙监控] 从AstrBot获取配置失败: {e}")
        
        # 方法2: 尝试从文件读取
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(plugin_dir, 'config.json')
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                logger.info(f"[鸿蒙监控] 从文件读取配置: {file_config}")
                
                # 合并配置，文件配置优先级高于AstrBot配置
                for key in ['app_name_list', 'detail_url_list', 'version_selector_list', 
                           'check_interval_minutes', 'command_prefix']:
                    if key in file_config:
                        plugin_config[key] = file_config[key]
            except Exception as e:
                logger.error(f"[鸿蒙监控] 读取配置文件失败: {e}")
        
        logger.info(f"[鸿蒙监控] DEBUG: 最终配置: {plugin_config}")
        return plugin_config

    def _save_plugin_config(self):
        """保存插件配置到文件"""
        # 准备配置数据
        config_data = {
            "app_name_list": [app['app_name'] for app in self.apps_to_watch],
            "detail_url_list": [app['detail_url'] for app in self.apps_to_watch],
            "version_selector_list": [app['version_selector'] for app in self.apps_to_watch],
            "check_interval_minutes": self.check_interval,
            "command_prefix": self.command_prefix
        }
        
        # 保存到文件
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        config_file = os.path.join(plugin_dir, 'config.json')
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[鸿蒙监控] 配置已保存到文件: {config_file}")
            return True
        except Exception as e:
            logger.error(f"[鸿蒙监控] 保存配置文件失败: {e}")
            return False

    
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
        logger.info(f"[鸿蒙监控] 更新通知:\n{message}")

        # ---------- 核心监控方法 ----------
    async def _monitor_loop(self):
        """定时监控循环"""
        while self._is_running:
            try:
                await self._check_all_apps()
            except Exception as e:
                logger.error(f"[鸿蒙监控] 监控循环出错: {e}")
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
                continue
                
            version = await self._fetch_version(detail_url, selector)
            if not version:
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
            return ""
            
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.wait_for_selector(selector, timeout=30000)
                text = await page.text_content(selector)
                await browser.close()
                return text.strip() if text else ""
        except Exception as e:
            logger.error(f"[鸿蒙监控] 抓取失败: {e}")
            return ""
    # ---------- 插件管理指令 ----------
    
    @filter.command("status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看状态 /status"""
        status = [
            "📊 鸿蒙监控状态",
            f"• 应用数: {len(self.apps_to_watch)}",
            f"• 间隔: {self.check_interval}分钟",
            f"• 状态: {'运行中' if self._is_running else '停止'}",
            f"• Playwright: {'可用' if PLAYWRIGHT_AVAILABLE else '不可用'}"
        ]
        yield event.plain_result("\n".join(status))

    @filter.command("check")
    async def cmd_check(self, event: AstrMessageEvent):
        """立即检查更新 /check"""
        # 1. 首先通知用户开始检查
        yield event.plain_result("🔍 正在检查所有应用更新，请稍候...")
        
        # 2. 执行核心检查逻辑（这会更新 self.version_store）
        await self._check_all_apps()
        
        # 3. 重新加载一次版本存储，确保获取到最新的检查结果
        current_store = self._load_version_store()
        
        # 4. 组织并显示最终结果
        if current_store:
            result_lines = ["✅ 检查完成！当前最新版本状态："]
            for app_name, version in current_store.items():
                result_lines.append(f"  • **{app_name}**: `v{version}`")
        else:
            result_lines = ["ℹ️ 检查完成，但尚未记录任何应用的版本信息。"]
            result_lines.append("请确保监控列表中的应用链接和选择器正确，且网络可访问。")
        
        yield event.plain_result("\n".join(result_lines))

    @filter.command("config")
    async def cmd_config(self, event: AstrMessageEvent):
        """查看当前配置 /config"""
        config_info = [
            "🔧 当前配置信息:",
            f"检查间隔: {self.check_interval}分钟",
            f"指令前缀: '{self.command_prefix}'",
            "",
            "📱 监控应用列表:"
        ]
        
        if self.apps_to_watch:
            for i, app in enumerate(self.apps_to_watch, 1):
                config_info.append(f"{i}. {app['app_name']}")
                config_info.append(f"   链接: {app['detail_url']}")
                config_info.append(f"   选择器: {app['version_selector']}")
                config_info.append("")
        else:
            config_info.append("  （暂无监控应用）")
        
        config_info.append("")
        config_info.append("💡 使用以下指令管理配置:")
        config_info.append("  /set_interval <分钟> - 设置检查间隔")
        config_info.append("  /set_prefix <前缀> - 设置指令前缀")
        config_info.append("  /add_app <名称> <链接> <选择器> - 添加应用")
        config_info.append("  /del_app <名称或编号> - 删除应用")
        config_info.append("  /clear_records - 清空所有版本记录")
        config_info.append("  /save_config - 保存当前配置")
        config_info.append("  /reload_config - 重新加载配置")
        
        yield event.plain_result("\n".join(config_info))

    @filter.command("set_interval")
    async def cmd_set_interval(self, event: AstrMessageEvent):
        """设置检查间隔 /set_interval <分钟>"""
        args = event.get_plain_text().strip().split()
        
        if len(args) < 2:
            yield event.plain_result("❌ 用法: /set_interval <分钟>\n例如: /set_interval 60")
            return
        
        try:
            minutes = int(args[1])
            if minutes < 5:
                yield event.plain_result("❌ 检查间隔不能小于5分钟")
                return
            
            self.check_interval = minutes
            
            # 重启监控任务
            if self._is_running and self._monitor_task:
                self._is_running = False
                self._monitor_task.cancel()
                await asyncio.sleep(1)
            
            if self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
                self._is_running = True
                self._monitor_task = asyncio.create_task(self._monitor_loop())
            
            yield event.plain_result(f"✅ 检查间隔已设置为 {minutes} 分钟，监控任务已重启")
        except ValueError:
            yield event.plain_result("❌ 请输入有效的数字")

    @filter.command("set_prefix")
    async def cmd_set_prefix(self, event: AstrMessageEvent):
        """设置指令前缀 /set_prefix <前缀>"""
        args = event.get_plain_text().strip().split()
        
        if len(args) < 2:
            yield event.plain_result("❌ 用法: /set_prefix <前缀>\n例如: /set_prefix !")
            return
        
        new_prefix = args[1]
        self.command_prefix = new_prefix
        
        yield event.plain_result(f"✅ 指令前缀已设置为 '{new_prefix}'")

    @filter.command("add_app")
    async def cmd_add_app(self, event: AstrMessageEvent):
        """添加监控应用 /add_app <名称> <链接> <选择器>"""
        # 使用正则表达式解析参数，允许名称中有空格
        text = event.get_plain_text().strip()
        match = re.match(r'/add_app\s+"([^"]+)"\s+(\S+)\s+(\S+)', text)
        
        if not match:
            # 尝试不带引号的解析
            args = text.split()
            if len(args) < 4:
                yield event.plain_result('❌ 用法: /add_app "应用名称" <链接> <选择器>\n例如: /add_app "一记账单" https://appgallery.huawei.com/app/detail?id=com.ericple.onebill span.content-value')
                return
            app_name = args[1]
            url = args[2]
            selector = args[3]
        else:
            app_name = match.group(1)
            url = match.group(2)
            selector = match.group(3)
        
        # 检查是否已存在
        for app in self.apps_to_watch:
            if app['app_name'] == app_name or app['detail_url'] == url:
                yield event.plain_result(f"❌ 应用 '{app_name}' 或链接已存在")
                return
        
        # 验证URL格式
        if not url.startswith('http'):
            yield event.plain_result("❌ 链接格式不正确，请以 http:// 或 https:// 开头")
            return
        
        # 添加应用
        self.apps_to_watch.append({
            'app_name': app_name,
            'detail_url': url,
            'version_selector': selector
        })
        
        yield event.plain_result(f"✅ 已添加应用: {app_name}\n链接: {url}\n选择器: {selector}\n\n注意: 使用 /save_config 保存配置")

    @filter.command("del_app")
    async def cmd_del_app(self, event: AstrMessageEvent):
        """删除监控应用 /del_app <名称或编号>"""
        args = event.get_plain_text().strip().split()
        
        if len(args) < 2:
            yield event.plain_result("❌ 用法: /del_app <名称或编号>\n例如: /del_app 一记账单 或 /del_app 1")
            return
        
        target = ' '.join(args[1:])
        
        # 尝试按编号删除
        if target.isdigit():
            index = int(target) - 1
            if 0 <= index < len(self.apps_to_watch):
                removed_app = self.apps_to_watch.pop(index)
                yield event.plain_result(f"✅ 已删除应用: {removed_app['app_name']}\n\n注意: 使用 /save_config 保存配置")
                return
            else:
                yield event.plain_result(f"❌ 编号 {target} 不存在，当前共有 {len(self.apps_to_watch)} 个应用")
                return
        
        # 按名称删除
        for i, app in enumerate(self.apps_to_watch):
            if app['app_name'] == target:
                removed_app = self.apps_to_watch.pop(i)
                yield event.plain_result(f"✅ 已删除应用: {removed_app['app_name']}\n\n注意: 使用 /save_config 保存配置")
                return
        
        # 未找到
        yield event.plain_result(f"❌ 未找到应用: {target}")

    @filter.command("clear_records")
    async def cmd_clear_records(self, event: AstrMessageEvent):
        """清空所有版本记录 /clear_records"""
        self.version_store = {}
        self._save_version_store()
        
        yield event.plain_result("✅ 所有版本记录已清空")

    @filter.command("save_config")
    async def cmd_save_config(self, event: AstrMessageEvent):
        """保存当前配置 /save_config"""
        success = self._save_plugin_config()
        
        if success:
            yield event.plain_result("✅ 配置已保存到插件目录的 config.json 文件")
        else:
            yield event.plain_result("❌ 配置保存失败，请检查日志")

    @filter.command("reload_config")
    async def cmd_reload_config(self, event: AstrMessageEvent):
        """重新加载配置 /reload_config"""
        # 保存当前运行状态
        was_running = self._is_running
        
        # 停止监控任务
        if self._is_running and self._monitor_task:
            self._is_running = False
            self._monitor_task.cancel()
            await asyncio.sleep(1)
        
        # 重新获取配置
        plugin_config = self._get_plugin_config()
        
        # 重新解析应用列表
        app_names = plugin_config.get("app_name_list", [])
        detail_urls = plugin_config.get("detail_url_list", [])
        version_selectors = plugin_config.get("version_selector_list", [])
        
        # 处理None值
        if app_names is None:
            app_names = []
        if detail_urls is None:
            detail_urls = []
        if version_selectors is None:
            version_selectors = []
        
        if isinstance(app_names, str):
            app_names = [line.strip() for line in app_names.split('\n') if line.strip()]
        if isinstance(detail_urls, str):
            detail_urls = [line.strip() for line in detail_urls.split('\n') if line.strip()]
        if isinstance(version_selectors, str):
            version_selectors = [line.strip() for line in version_selectors.split('\n') if line.strip()]
        
        self.apps_to_watch = []
        min_length = min(len(app_names), len(detail_urls), len(version_selectors))
        
        if min_length > 0:
            for i in range(min_length):
                self.apps_to_watch.append({
                    'app_name': app_names[i],
                    'detail_url': detail_urls[i],
                    'version_selector': version_selectors[i]
                })
        
        # 更新其他配置
        check_interval = plugin_config.get('check_interval_minutes')
        command_prefix = plugin_config.get('command_prefix')
        
        if check_interval is not None:
            self.check_interval = check_interval
        else:
            self.check_interval = 30
            
        if command_prefix is not None:
            self.command_prefix = command_prefix
        else:
            self.command_prefix = "/"
        
        # 重新启动监控任务
        if was_running and self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        yield event.plain_result("✅ 配置已重新加载")

    @filter.command("export_config")
    async def cmd_export_config(self, event: AstrMessageEvent):
        """导出当前配置 /export_config"""
        config_info = [
            "📋 当前配置内容:",
            "```json"
        ]
        
        config_data = {
            "app_name_list": [app['app_name'] for app in self.apps_to_watch],
            "detail_url_list": [app['detail_url'] for app in self.apps_to_watch],
            "version_selector_list": [app['version_selector'] for app in self.apps_to_watch],
            "check_interval_minutes": self.check_interval,
            "command_prefix": self.command_prefix
        }
        
        formatted_json = json.dumps(config_data, ensure_ascii=False, indent=2)
        lines = formatted_json.split('\n')
        for line in lines[:20]:  # 限制显示行数
            config_info.append(line)
        if len(lines) > 20:
            config_info.append("...")
        
        config_info.append("```")
        config_info.append("💡 将此内容保存为 config.json 文件即可应用")
        
        yield event.plain_result("\n".join(config_info))

    @filter.command("reset_config")
    async def cmd_reset_config(self, event: AstrMessageEvent):
        """重置配置为默认 /reset_config"""
        confirm = event.get_plain_text().strip()
        if not confirm.endswith("confirm"):
            yield event.plain_result("⚠️ 此操作将重置所有配置为默认值！\n如果要继续，请发送: /reset_config confirm")
            return
        
        # 重置配置
        self.apps_to_watch = [{
            'app_name': "一记账单",
            'detail_url': "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill",
            'version_selector': "span.content-value"
        }]
        self.check_interval = 30
        self.command_prefix = "/"
        
        # 清空版本记录
        self.version_store = {}
        self._save_version_store()
        
        # 保存配置
        self._save_plugin_config()
        
        # 重启监控任务
        if self._is_running and self._monitor_task:
            self._is_running = False
            self._monitor_task.cancel()
        
        if self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        yield event.plain_result("✅ 配置已重置为默认值，所有记录已清空")