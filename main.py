from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
import asyncio
import json
import os
import time
import yaml
from typing import Any, Dict, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

@register("harmony_app_monitor", "YourName", "鸿蒙应用更新监控与推送插件", "1.0.0")
class HarmonyAppMonitor(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 初始化变量，但先不访问context.config
        self._context = context
        self.config = {}  # 留空，在initialize中填充
        self.apps_to_watch = []
        self.check_interval = 30
        self.version_store_file = ""
        self.version_store = {}
        self._monitor_task = None
        self._is_running = False
        logger.info("[鸿蒙监控] 插件实例创建完成，等待初始化...")

    async def initialize(self):
        """插件初始化：在这里安全地获取配置和启动任务"""
        logger.info("[鸿蒙监控] 开始执行初始化...")
        try:
            # 方法1: 尝试从context的不同属性获取配置
            if hasattr(self._context, 'config'):
                self.config = self._context.config
                logger.info("[鸿蒙监控] 从 context.config 获取配置")
            elif hasattr(self._context, 'plugin_config'):
                self.config = self._context.plugin_config
                logger.info("[鸿蒙监控] 从 context.plugin_config 获取配置")
            elif hasattr(self._context, 'settings'):
                self.config = self._context.settings
                logger.info("[鸿蒙监控] 从 context.settings 获取配置")
            else:
                # 方法2: 作为备选，直接从metadata.yaml文件读取
                logger.warning("[鸿蒙监控] Context未找到标准配置属性，尝试读取文件...")
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                metadata_path = os.path.join(plugin_dir, 'metadata.yaml')
                if os.path.exists(metadata_path):
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        metadata = yaml.safe_load(f)
                        self.config = metadata.get('config', {})
                else:
                    logger.error("[鸿蒙监控] 未找到metadata.yaml配置文件")
                    return

            # 打印调试信息，查看实际获取到的配置结构
            logger.info(f"[鸿蒙监控] 配置对象类型: {type(self.config)}")
            logger.info(f"[鸿蒙监控] 配置键值: {list(self.config.keys()) if isinstance(self.config, dict) else '非字典类型'}")

            # 从配置中读取核心参数
            self.apps_to_watch = self.config.get('apps_to_watch', [])
            self.check_interval = self.config.get('check_interval_minutes', 30)

            # 设置版本存储文件路径
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            self.version_store_file = os.path.join(plugin_dir, 'harmony_versions.json')
            self.version_store = self._load_version_store()

            logger.info(f"[鸿蒙监控] 初始化完成！共监控 {len(self.apps_to_watch)} 个应用，检查间隔 {self.check_interval} 分钟。")

            # 启动监控任务
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("[鸿蒙监控] 定时监控任务已启动。")

        except Exception as e:
            logger.error(f"[鸿蒙监控] 初始化过程中发生严重错误: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def terminate(self):
        """插件销毁：停止监控任务，清理资源"""
        logger.info("[鸿蒙监控] 插件正在停止...")
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("[鸿蒙监控] 插件已停止。")

    # ---------- 核心监控逻辑 ----------
    async def _monitor_loop(self):
        """定时监控循环"""
        while self._is_running:
            try:
                await self._check_all_apps()
            except Exception as e:
                logger.error(f"[鸿蒙监控] 监控循环出错: {e}")
            # 等待指定的间隔时间（转换为秒）
            await asyncio.sleep(self.check_interval * 60)

    async def _check_all_apps(self):
        """检查所有配置的应用"""
        if not self.apps_to_watch:
            logger.warning("[鸿蒙监控] 应用监控列表为空，请在插件配置中添加应用。")
            return

        logger.info(f"[鸿蒙监控] 开始本轮应用检查 ({time.strftime('%Y-%m-%d %H:%M:%S')})")
        for app_config in self.apps_to_watch:
            app_name = app_config['app_name']
            detail_url = app_config['detail_url']
            version_selector = app_config.get('version_selector', 'span.content-value')

            logger.info(f"[鸿蒙监控] 正在检查应用: {app_name}")
            current_version = await self._fetch_version(detail_url, version_selector)

            if not current_version:
                logger.warning(f"[鸿蒙监控] 应用 {app_name} 版本抓取失败，请检查URL或选择器。")
                continue

            old_version = self.version_store.get(app_name)

            # 版本比较与处理
            if old_version is None:
                logger.info(f"[鸿蒙监控] 应用 {app_name} 首次记录版本: {current_version}")
                self.version_store[app_name] = current_version
                self._save_version_store()
            elif current_version != old_version:
                logger.info(f"[鸿蒙监控] 发现应用 {app_name} 更新: {old_version} -> {current_version}")
                # 1. 更新存储
                self.version_store[app_name] = current_version
                self._save_version_store()
                # 2. 发送更新通知
                await self._send_update_notification(app_name, old_version, current_version, detail_url)
            else:
                logger.debug(f"[鸿蒙监控] 应用 {app_name} 当前已是最新版本 ({current_version})")

    async def _fetch_version(self, url: str, selector: str) -> str:
        """使用Playwright抓取单个应用的版本号"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.wait_for_selector(selector, state="attached", timeout=10000)
                version_text = await page.text_content(selector)
                return version_text.strip() if version_text else ""
            except TimeoutError:
                logger.warning(f"[鸿蒙监控] 抓取超时，选择器 '{selector}' 可能无效或页面加载过慢。")
                return ""
            except Exception as e:
                logger.error(f"[鸿蒙监控] 抓取过程出错: {e}")
                return ""
            finally:
                await browser.close()

    # ---------- 数据持久化 ----------
    def _load_version_store(self) -> Dict[str, str]:
        """从JSON文件加载版本存储"""
        try:
            if os.path.exists(self.version_store_file):
                with open(self.version_store_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[鸿蒙监控] 读取版本存储文件失败: {e}")
        return {}

    def _save_version_store(self):
        """保存版本存储到JSON文件"""
        try:
            with open(self.version_store_file, 'w', encoding='utf-8') as f:
                json.dump(self.version_store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[鸿蒙监控] 保存版本存储文件失败: {e}")

    # ---------- 消息通知 ----------
    async def _send_update_notification(self, app_name: str, old_ver: str, new_ver: str, url: str):
        """发送更新通知到机器人"""
        message = (
            f"🚀 **鸿蒙应用更新通知**\n\n"
            f"📱 **应用名称:** {app_name}\n"
            f"🔄 **版本更新:** `{old_ver}` → `{new_ver}`\n"
            f"🔗 **市场链接:** {url}\n"
            f"⏰ **检测时间:** {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # 尝试使用context的bot对象发送消息
        try:
            if hasattr(self._context, 'bot'):
                # 发送到所有空间
                for space in self._context.bot.spaces:
                    await space.send([Plain(message)])
                    logger.info(f"[鸿蒙监控] 已发送更新通知到空间: {space.id}")
            else:
                logger.warning("[鸿蒙监控] 无法发送消息：未找到bot对象")
        except Exception as e:
            logger.error(f"[鸿蒙监控] 发送消息失败: {e}")

    # ---------- 插件指令 ----------
    @filter.command("checknow")
    async def cmd_check_now(self, event: AstrMessageEvent):
        """手动立即检查所有应用更新"""
        user_name = event.get_sender_name()
        logger.info(f"[鸿蒙监控] 用户 {user_name} 触发手动检查")

        yield event.plain_result(f"{user_name}，正在立即检查应用更新...")

        # 执行一次检查
        await self._check_all_apps()

        yield event.plain_result("手动检查完成！请查看日志了解详情。")

    @filter.command("monitor_status")
    async def cmd_show_status(self, event: AstrMessageEvent):
        """显示当前监控状态"""
        status_lines = []
        status_lines.append("📊 **鸿蒙应用监控状态**")
        status_lines.append(f"• 监控应用数: {len(self.apps_to_watch)}")
        status_lines.append(f"• 检查间隔: {self.check_interval} 分钟")
        status_lines.append(f"• 运行状态: {'运行中' if self._is_running else '已停止'}")
        status_lines.append("")
        status_lines.append("📋 **已记录版本的应用:**")

        for app_name, version in self.version_store.items():
            status_lines.append(f"  • {app_name}: v{version}")

        if not self.version_store:
            status_lines.append("  （暂无记录）")

        yield event.plain_result("\n".join(status_lines))
