# 完全对齐原始模板，仅替换业务逻辑
import requests
from bs4 import BeautifulSoup
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# 硬编码配置（直接修改这里的URL即可）
TARGET_URL = "https://appgallery.huawei.com/app/detail?id=com.ericple.onebill"
HISTORY_VERSION = ""

# 严格对齐原始模板的注册装饰器
@register("astrbot_plugin_harmony_app_monitor", "YourName", "鸿蒙应用更新监控插件", "v1.0.0")
class MyPlugin(Star):
    # 完全复制原始模板的__init__
    def __init__(self, context: Context):
        super().__init__(context)

    # 原始模板的可选初始化方法（空实现，避免报错）
    async def initialize(self):
        pass

    # 完全对齐原始模板的指令装饰器（仅改指令名和业务逻辑）
    @filter.command("hmcheck")
    async def helloworld(self, event: AstrMessageEvent):
        """手动检查鸿蒙应用更新（指令：/hmcheck）"""
        global HISTORY_VERSION
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(f"用户 {user_name} 发送了 {message_str}")

        # 核心业务逻辑（同步请求，避免异步兼容问题）
        try:
            # 同步请求（替换异步aiohttp，兼容所有版本）
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            resp = requests.get(TARGET_URL, headers=headers, timeout=15, verify=False)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")

            # 解析信息（纯Python 3.6+兼容写法）
            app_name_elem = soup.select_one("h1.app-name")
            app_name = app_name_elem.text.strip() if app_name_elem else "未知应用"

            version_elem = soup.select_one("div.version")
            current_version = version_elem.text.strip() if version_elem else "未知版本"

            update_time_elem = soup.select_one("span.update-date")
            update_time = update_time_elem.text.strip() if update_time_elem else "未知时间"

            update_log_elem = soup.select_one("div.update-content")
            update_log = update_log_elem.text.strip() if update_log_elem else "无更新内容"

            # 版本对比
            if not HISTORY_VERSION:
                HISTORY_VERSION = current_version
                reply = f"Hello, {user_name}, 首次检查！\n📱应用：{app_name}\n🔢版本：{current_version}\n🕒更新时间：{update_time}"
            elif current_version != HISTORY_VERSION:
                reply = f"Hello, {user_name}, 检测到更新！\n📱应用：{app_name}\n🔢旧版本：{HISTORY_VERSION} → 新版本：{current_version}\n🕒更新时间：{update_time}\n📝更新内容：{update_log}"
                HISTORY_VERSION = current_version
            else:
                reply = f"Hello, {user_name}, 暂无更新！\n📱应用：{app_name}\n🔢当前版本：{current_version}\n🕒更新时间：{update_time}"

        except Exception as e:
            reply = f"Hello, {user_name}, 检查失败：{str(e)}"

        # 完全复制原始模板的返回方式
        yield event.plain_result(reply)

    # 原始模板的可选销毁方法（空实现）
    async def terminate(self):
        pass
