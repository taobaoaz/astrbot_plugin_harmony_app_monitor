import asyncio
import aiohttp
from bs4 import BeautifulSoup
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# ========== 硬编码配置（先保证插件载入，后续可在面板配置） ==========
# 替换为你要监控的鸿蒙应用URL
TARGET_URL = "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill9"
# 检查间隔（暂时注释定时任务，先保留手动触发）
CHECK_INTERVAL = 10
# 历史版本（初始为空）
HISTORY_VERSION = ""

# 反爬请求头
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://appgallery.huawei.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache"
}

# ========== 严格对齐原始模板的注册格式 ==========
@register("astrbot_plugin_harmony_app_monitor", "YourName", "鸿蒙应用更新监控插件（手动触发）", "v1.0.0")
class MyPlugin(Star):
    # ========== 完全对齐原始模板的__init__ ==========
    def __init__(self, context: Context):
        super().__init__(context)
        # 移除所有Context.config相关代码（避免AttributeError）
        self.session = None

    # ========== 可选初始化方法（极简版） ==========
    async def initialize(self):
        """插件初始化"""
        logger.info("[鸿蒙应用监控插件] 插件初始化成功（仅手动触发模式）")
        self.session = aiohttp.ClientSession(headers=REQUEST_HEADERS)

    # ========== 核心：手动触发指令（/hmcheck） ==========
    @filter.command("hmcheck")
    async def helloworld(self, event: AstrMessageEvent):
        """手动检查鸿蒙应用更新（指令：/hmcheck）"""
        global HISTORY_VERSION
        user_name = event.get_sender_name()
        logger.info(f"[鸿蒙应用监控插件] {user_name} 触发手动检查更新")

        # 1. 检查会话是否初始化
        if not self.session:
            yield event.plain_result("❌ 插件初始化失败，请重启插件！")
            return

        # 2. 抓取应用信息
        app_info = await self._get_app_info()
        if not app_info:
            yield event.plain_result("❌ 抓取应用信息失败，请检查URL或网络！")
            return

        # 3. 版本对比&构造回复
        if not HISTORY_VERSION:
            HISTORY_VERSION = app_info["version"]
            reply_msg = f"""✅ 首次检查，初始化版本！
📱 应用名称：{app_info['name']}
🔢 当前版本：{app_info['version']}
🕒 最后更新时间：{app_info['time']}"""
        elif app_info["version"] != HISTORY_VERSION:
            reply_msg = f"""✅ 检测到应用更新！
📱 应用名称：{app_info['name']}
🔢 旧版本：{HISTORY_VERSION} → 新版本：{app_info['version']}
🕒 更新时间：{app_info['time']}
📝 更新内容：{app_info['log']}"""
            HISTORY_VERSION = app_info["version"]
        else:
            reply_msg = f"""✅ 暂无更新！
📱 应用名称：{app_info['name']}
🔢 当前版本：{app_info['version']}
🕒 最后更新时间：{app_info['time']}"""

        # 4. 返回结果（完全对齐原始模板的yield方式）
        yield event.plain_result(reply_msg)

    # ========== 私有方法：抓取应用信息（兼容版） ==========
    async def _get_app_info(self):
        """异步抓取鸿蒙应用信息"""
        try:
            async with self.session.get(
                url=TARGET_URL,
                timeout=aiohttp.ClientTimeout(total=15),
                verify_ssl=False  # 兼容老旧服务器SSL问题
            ) as resp:
                html = await resp.text(encoding="utf-8")
                soup = BeautifulSoup(html, "html.parser")

                # 解析信息（纯Python写法，无语法糖）
                app_name_elem = soup.select_one("h1.app-name")
                app_name = app_name_elem.text.strip() if app_name_elem else "未知应用"

                version_elem = soup.select_one("div.version")
                current_version = version_elem.text.strip() if version_elem else "未知版本"

                update_time_elem = soup.select_one("span.update-date")
                update_time = update_time_elem.text.strip() if update_time_elem else "未知时间"

                update_log_elem = soup.select_one("div.update-content")
                update_log = update_log_elem.text.strip() if update_log_elem else "无更新内容"

                return {
                    "name": app_name,
                    "version": current_version,
                    "time": update_time,
                    "log": update_log
                }
        except Exception as e:
            logger.error(f"抓取失败：{str(e)}")
            return None

    # ========== 可选销毁方法 ==========
    async def terminate(self):
        """插件销毁"""
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("[鸿蒙应用监控插件] 插件已销毁")

# ========== 原始模板无此部分，仅保留核心类 ==========
