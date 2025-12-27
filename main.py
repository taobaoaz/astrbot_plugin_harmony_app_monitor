from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
import asyncio
import json
import os
import time
from typing import Any, Dict, List

# 动态导入Playwright，避免初始化时出错
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.warning("[鸿蒙监控] Playwright未安装，将无法抓取版本。请运行: pip install playwright && playwright install chromium")

@register("harmony_app_monitor", "YourName", "鸿蒙应用更新监控与推送插件", "1.0.0")
class HarmonyAppMonitor(Star):
    def __init__(self, context: Context):
        # 严格按照模板：先调用父类初始化
        super().__init__(context)
        # 保存context但不立即使用
        self._ctx = context
        # 初始化变量（不访问context）
        self._monitor_task = None
        self._is_running = False
        self.apps_to_watch = []
        self.check_interval = 30
        self.version_store_file = ""
        self.version_store = {}

    async def initialize(self):
        """插件初始化：安全地获取配置并启动任务"""
        logger.info("[鸿蒙监控] 开始执行初始化...")
        
        # === 安全获取配置（多种方式尝试）===
        config = {}
        
        # 方式1：直接尝试访问（最标准的方式）
        try:
            if hasattr(self._ctx, 'config'):
                config = self._ctx.config
                logger.info("[鸿蒙监控] 通过 self._ctx.config 获取配置")
        except:
            pass
            
        # 方式2：如果方式1失败，尝试其他属性名
        if not config:
            for attr_name in ['plugin_config', 'settings', 'configs']:
                if hasattr(self._ctx, attr_name):
                    config = getattr(self._ctx, attr_name, {})
                    if config:
                        logger.info(f"[鸿蒙监控] 通过 self._ctx.{attr_name} 获取配置")
                        break
        
        # 方式3：如果以上都失败，使用空配置
        if not config:
            logger.warning("[鸿蒙监控] 无法从context获取配置，使用默认配置")
            config = {}
        
        # === 从配置中读取参数 ===
        self.apps_to_watch = config.get('apps_to_watch', [])
        self.check_interval = config.get('check_interval_minutes', 30)
        
        # === 初始化数据存储 ===
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.version_store_file = os.path.join(plugin_dir, 'harmony_versions.json')
        self.version_store = self._load_version_store()
        
        logger.info(f"[鸿蒙监控] 初始化完成！共监控 {len(self.apps_to_watch)} 个应用，检查间隔 {self.check_interval} 分钟")
        
        # === 启动监控任务 ===
        if self.apps_to_watch and PLAYWRIGHT_AVAILABLE:
            self._is_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("[鸿蒙监控] 定时监控任务已启动")
        else:
            if not PLAYWRIGHT_AVAILABLE:
                logger.error("[鸿蒙监控] Playwright不可用，监控任务无法启动")
            if not self.apps_to_watch:
                logger.warning("[鸿蒙监控] 监控列表为空，请在插件配置中添加应用")

    async def terminate(self):
        """插件销毁：停止所有任务"""
        logger.info("[鸿蒙监控] 插件正在停止...")
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("[鸿蒙监控] 插件已停止")

    # ---------- 核心监控逻辑 ----------
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
        """检查所有配置的应用"""
        if not self.apps_to_watch:
            return
            
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"[鸿蒙监控] 开始本轮应用检查 ({current_time})")
        
        for app_config in self.apps_to_watch:
            app_name = app_config.get('app_name', '未知应用')
            detail_url = app_config.get('detail_url', '')
            version_selector = app_config.get('version_selector', 'span.content-value')
            
            if not detail_url:
                logger.warning(f"[鸿蒙监控] 应用 {app_name} 的URL为空，跳过")
                continue
                
            logger.info(f"[鸿蒙监控] 正在检查: {app_name}")
            current_version = await self._fetch_version(detail_url, version_selector)
            
            if not current_version:
                logger.warning(f"[鸿蒙监控] {app_name} 版本抓取失败")
                continue
                
            old_version = self.version_store.get(app_name)
            
            # 版本比较与处理
            if old_version is None:
                logger.info(f"[鸿蒙监控] {app_name} 首次记录版本: {current_version}")
                self.version_store[app_name] = current_version
                self._save_version_store()
            elif current_version != old_version:
                logger.info(f"[鸿蒙监控] 发现 {app_name} 更新: {old_version} -> {current_version}")
                # 更新存储
                self.version_store[app_name] = current_version
                self._save_version_store()
                # 发送通知
                await self._send_update_notification(app_name, old_version, current_version, detail_url)
            else:
                logger.debug(f"[鸿蒙监控] {app_name} 已是最新 ({current_version})")

    async def _fetch_version(self, url: str, selector: str) -> str:
        """使用Playwright抓取版本号"""
        if not PLAYWRIGHT_AVAILABLE:
            return ""
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.wait_for_selector(selector, state="attached", timeout=10000)
                version_text = await page.text_content(selector)
                return version_text.strip() if version_text else ""
            except Exception as e:
                logger.error(f"[鸿蒙监控] 抓取失败: {e}")
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
            logger.error(f"[鸿蒙监控] 读取版本存储失败: {e}")
        return {}

    def _save_version_store(self):
        """保存版本存储到JSON文件"""
        try:
            with open(self.version_store_file, 'w', encoding='utf-8') as f:
                json.dump(self.version_store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[鸿蒙监控] 保存版本存储失败: {e}")

    # ---------- 消息通知 ----------
    async def _send_update_notification(self, app_name: str, old_ver: str, new_ver: str, url: str):
        """发送更新通知"""
        message = (
            f"🚀 **鸿蒙应用更新通知**\n\n"
            f"📱 **应用名称:** {app_name}\n"
            f"🔄 **版本更新:** `{old_ver}` → `{new_ver}`\n"
            f"🔗 **市场链接:** {url}\n"
            f"⏰ **检测时间:** {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        try:
            # 尝试通过context发送消息
            if hasattr(self._ctx, 'bot') and hasattr(self._ctx.bot, 'spaces'):
                for space in self._ctx.bot.spaces:
                    await space.send([Plain(message)])
                    logger.info(f"[鸿蒙监控] 已发送通知到空间: {space.id}")
            else:
                # 备用方案：如果无法自动发送，在日志中显示消息内容
                logger.info(f"[鸿蒙监控] 更新通知内容:\n{message}")
        except Exception as e:
            logger.error(f"[鸿蒙监控] 发送通知失败: {e}")

    # ---------- 插件指令 ----------
    @filter.command("checknow")
    async def cmd_check_now(self, event: AstrMessageEvent):
        """手动立即检查更新 /checknow"""
        user_name = event.get_sender_name()
        logger.info(f"[鸿蒙监控] 用户 {user_name} 触发手动检查")
        
        yield event.plain_result(f"🔍 {user_name}，正在立即检查应用更新...")
        
        await self._check_all_apps()
        
        yield event.plain_result("✅ 手动检查完成！请查看机器人日志了解详情。")

    @filter.command("monitor_status")
    async def cmd_show_status(self, event: AstrMessageEvent):
        """显示监控状态 /monitor_status"""
        status_lines = [
            "📊 **鸿蒙应用监控状态**",
            f"• 监控应用数: {len(self.apps_to_watch)}",
            f"• 检查间隔: {self.check_interval} 分钟",
            f"• 运行状态: {'✅ 运行中' if self._is_running else '❌ 已停止'}",
            f"• Playwright: {'✅ 可用' if PLAYWRIGHT_AVAILABLE else '❌ 未安装'}",
            "",
            "📋 **已记录版本的应用:**"
        ]
        
        if self.version_store:
            for app_name, version in self.version_store.items():
                status_lines.append(f"  • {app_name}: v{version}")
        else:
            status_lines.append("  （暂无记录）")
            
        if not self.apps_to_watch:
            status_lines.append("\n⚠️ **提示:** 监控列表为空，请在插件配置中添加应用。")
        
        yield event.plain_result("\n".join(status_lines))

    @filter.command("monitor_add")
    async def cmd_add_app(self, event: AstrMessageEvent):
        """添加监控应用 /monitor_add <应用名> <URL> <选择器>"""
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.plain_result("❌ 参数不足！正确格式: /monitor_add <应用名> <URL> <CSS选择器>\n例如: /monitor_add 一记账单 https://appgallery.huawei.com/app/detail?id=com.ericple.onebill span.content-value")
            return
            
        app_name = args[0]
        detail_url = args[1]
        version_selector = args[2]
        
        # 检查是否已存在
        for app in self.apps_to_watch:
            if app['app_name'] == app_name:
                yield event.plain_result(f"❌ 应用 {app_name} 已在监控列表中")
                return
        
        # 添加到列表
        new_app = {
            'app_name': app_name,
            'detail_url': detail_url,
            'version_selector': version_selector
        }
        self.apps_to_watch.append(new_app)
        
        yield event.plain_result(f"✅ 已添加应用 {app_name} 到监控列表")
