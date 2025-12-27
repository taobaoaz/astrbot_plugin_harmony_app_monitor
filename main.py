from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
import asyncio
import json
import os
import time
from typing import Any, Dict, List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

@register("harmony_app_monitor", "YourName", "鸿蒙应用更新监控与推送插件", "1.0.0")
class HarmonyAppMonitor(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 从 context.config 中获取插件配置（对应 metadata.yaml 中的 config）
        self.config: Dict[str, Any] = context.config
        # 初始化核心属性
        self.apps_to_watch: List[Dict[str, Any]] = self.config.get('apps_to_watch', [])
        self.check_interval: int = self.config.get('check_interval_minutes', 30)
        # 版本存储文件的路径（放在插件目录下）
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.version_store_file = os.path.join(plugin_dir, 'harmony_versions.json')
        self.version_store: Dict[str, str] = {}
        # 控制定时任务的变量
        self._monitor_task = None
        self._is_running = False
        
    async def initialize(self):
        """插件初始化：加载数据、启动监控任务"""
        logger.info("[鸿蒙监控] 插件开始初始化...")
        self.version_store = self._load_version_store()
        logger.info(f"[鸿蒙监控] 已加载 {len(self.version_store)} 个应用的版本记录。")
        logger.info(f"[鸿蒙监控] 配置监控 {len(self.apps_to_watch)} 个应用，检查间隔 {self.check_interval} 分钟。")
        
        # 启动监控任务
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("[鸿蒙监控] 定时监控任务已启动。")
        
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
        
        # 这里需要根据你的实际需求发送消息
        # 示例1: 发送到所有已连接的空间（群聊）
        # for space in self.context.bot.spaces:
        #     await space.send([Plain(message)])
            
        # 示例2: 发送到特定空间（需要知道空间ID）
        # target_space_id = "your_space_id"
        # space = self.context.bot.get_space(target_space_id)
        # if space:
        #     await space.send([Plain(message)])
            
        logger.info(f"[鸿蒙监控] 已生成更新通知: {app_name} {old_ver}->{new_ver}")
        # 暂时先打印到日志，你需要根据实际情况实现消息发送
        
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
