import asyncio
import aiohttp
from bs4 import BeautifulSoup
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 反爬请求头（适配鸿蒙应用商城）
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://appgallery.huawei.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache"
}

@register(
    "astrbot_plugin_harmony_app_monitor",  # 与metadata.yaml的name一致
    "xianyao",             # 作者名
    "鸿蒙应用更新监控插件",  # 插件描述
    "v1.0.0"                # 版本号（与metadata.yaml一致）
)
class HarmonyAppMonitorPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # ========== 修正核心：用官方方法获取插件配置 ==========
        # 获取插件配置（AstralBot官方API：get_config()，返回字典）
        plugin_config = context.get_config() or {}
        self.target_url = plugin_config.get("target_url", "")  # 应用URL
        self.check_interval = plugin_config.get("check_interval", 10)  # 检查间隔（分钟）
        self.history_version = plugin_config.get("history_version", "")  # 历史版本
        
        # 异步请求会话（适配异步插件）
        self.session: aiohttp.ClientSession | None = None
        # 定时任务对象（用于停止插件时销毁）
        self.check_task: asyncio.Task | None = None

    async def initialize(self):
        """插件初始化（异步）：创建请求会话+启动定时检查任务"""
        logger.info("[鸿蒙应用监控插件] 初始化插件...")
        # 创建异步HTTP会话
        self.session = aiohttp.ClientSession(headers=REQUEST_HEADERS)
        
        # 初始化历史版本（首次运行）
        if self.target_url:
            init_info = await self._get_app_info()
            if init_info:
                self.history_version = init_info["version"]
                # ========== 修正：用官方方法保存配置 ==========
                # 获取当前配置 → 更新 → 保存
                current_config = self.context.get_config() or {}
                current_config["history_version"] = self.history_version
                self.context.set_config(current_config)
                logger.info(f"[鸿蒙应用监控插件] 初始化历史版本：{self.history_version}")
        
        # 启动定时检查任务（间隔：check_interval 分钟）
        if self.target_url and self.check_interval > 0:
            self.check_task = asyncio.create_task(self._scheduled_check())
            logger.info(f"[鸿蒙应用监控插件] 定时检查任务启动，间隔：{self.check_interval}分钟")
        else:
            logger.warning("[鸿蒙应用监控插件] 未配置应用URL或间隔，跳过定时任务")

    async def _get_app_info(self) -> dict | None:
        """异步抓取鸿蒙应用商城应用信息"""
        if not self.target_url or not self.session:
            logger.error("[鸿蒙应用监控插件] URL或会话未初始化，抓取失败")
            return None
        
        try:
            async with self.session.get(
                url=self.target_url,
                timeout=aiohttp.ClientTimeout(total=15),
                verify_ssl=True
            ) as resp:
                resp.raise_for_status()  # 抛出HTTP错误
                html = await resp.text(encoding="utf-8")
                soup = BeautifulSoup(html, "html.parser")

                # 解析应用名称
                app_name_elem = soup.select_one("h1.app-name")
                app_name = app_name_elem.text.strip() if app_name_elem else "未知应用"
                
                # 解析版本号
                version_elem = soup.select_one("div.version")
                current_version = version_elem.text.strip() if version_elem else "未知版本"
                
                # 解析更新时间
                update_time_elem = soup.select_one("span.update-date")
                update_time = update_time_elem.text.strip() if update_time_elem else "未知时间"
                
                # 解析更新日志
                update_log_elem = soup.select_one("div.update-content")
                update_log = update_log_elem.text.strip() if update_log_elem else "无更新内容"

                logger.info(f"[鸿蒙应用监控插件] 抓取成功：{app_name} | {current_version}")
                return {
                    "name": app_name,
                    "version": current_version,
                    "time": update_time,
                    "log": update_log
                }
        except Exception as e:
            logger.error(f"[鸿蒙应用监控插件] 抓取失败：{str(e)}", exc_info=True)
            return None

    async def _send_notice(self, info: dict):
        """异步推送更新通知到机器人（适配多平台）"""
        notice_msg = f"""【鸿蒙应用更新提醒】
📱 应用名称：{info['name']}
🔢 最新版本：{info['version']}
🕒 更新时间：{info['time']}
📝 更新内容：{info['log']}"""
        
        try:
            # ========== 适配AstralBot官方消息发送API ==========
            # 兼容不同版本的Context.bot.send_message（确保参数正确）
            await self.context.bot.send_msg(
                content=notice_msg,
                msg_type="text"
            )
            logger.info("[鸿蒙应用监控插件] 通知推送成功")
        except Exception as e:
            # 兼容旧版API：若send_msg失败，尝试send_message
            try:
                await self.context.bot.send_message(
                    content=notice_msg,
                    message_type="text"
                )
                logger.info("[鸿蒙应用监控插件] 通知推送成功（兼容模式）")
            except Exception as e2:
                logger.error(f"[鸿蒙应用监控插件] 推送失败：{str(e2)}", exc_info=True)

    async def _scheduled_check(self):
        """定时检查更新的核心逻辑（异步循环）"""
        while True:
            if not self.target_url:
                await asyncio.sleep(self.check_interval * 60)
                continue
            
            # 抓取应用信息
            app_info = await self._get_app_info()
            if not app_info:
                await asyncio.sleep(self.check_interval * 60)
                continue
            
            # 版本对比：有更新则推送
            if app_info["version"] != self.history_version:
                logger.info(f"[鸿蒙应用监控插件] 检测到更新：{self.history_version} → {app_info['version']}")
                await self._send_notice(app_info)
                # 更新历史版本并保存配置
                self.history_version = app_info["version"]
                current_config = self.context.get_config() or {}
                current_config["history_version"] = self.history_version
                self.context.set_config(current_config)
            else:
                logger.info("[鸿蒙应用监控插件] 无版本更新，跳过推送")
            
            # 等待指定间隔（分钟转秒）
            await asyncio.sleep(self.check_interval * 60)

    # 注册手动触发指令：发送 /hmcheck 可手动检查更新
    @filter.command("hmcheck")
    async def manual_check(self, event: AstrMessageEvent):
        """手动触发检查鸿蒙应用更新（指令：/hmcheck）"""
        logger.info(f"[鸿蒙应用监控插件] 收到手动检查指令（用户：{event.get_sender_name()}）")
        
        # 未配置URL时回复提示
        if not self.target_url:
            yield event.plain_result("❌ 未配置鸿蒙应用URL，请先在插件面板填写！")
            return
        
        # 手动抓取并检查
        app_info = await self._get_app_info()
        if not app_info:
            yield event.plain_result("❌ 抓取应用信息失败，请检查URL或网络！")
            return
        
        # 构造回复消息
        if app_info["version"] != self.history_version:
            reply_msg = f"""✅ 检测到应用更新！
📱 应用名称：{app_info['name']}
🔢 当前版本：{self.history_version} → 最新版本：{app_info['version']}
🕒 更新时间：{app_info['time']}
📝 更新内容：{app_info['log']}"""
            # 推送通知并更新历史版本
            await self._send_notice(app_info)
            self.history_version = app_info["version"]
            current_config = self.context.get_config() or {}
            current_config["history_version"] = self.history_version
            self.context.set_config(current_config)
        else:
            reply_msg = f"""✅ 暂无更新！
📱 应用名称：{app_info['name']}
🔢 当前版本：{app_info['version']}
🕒 最后更新时间：{app_info['time']}"""
        
        yield event.plain_result(reply_msg)

    async def terminate(self):
        """插件销毁（异步）：停止定时任务+关闭会话"""
        logger.info("[鸿蒙应用监控插件] 销毁插件...")
        # 停止定时任务
        if self.check_task and not self.check_task.done():
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                logger.info("[鸿蒙应用监控插件] 定时任务已停止")
        # 关闭异步会话
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("[鸿蒙应用监控插件] HTTP会话已关闭")
