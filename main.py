#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstrBot Plugin: Harmony App Update Notifier
"""
import asyncio
import json
import os
import time
from typing import Any, Dict, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from astrbot.core import Robot, Space, SpaceType

class HarmonyUpdatePlugin:
    def __init__(self, robot: Robot):
        self.robot = robot
        self.config = robot.plugin_config
        # 确保配置读取正常
        self.apps_to_watch: List[Dict[str, Any]] = self.config.get('apps_to_watch', [])
        self.check_interval: int = self.config.get('check_interval_minutes', 30)
        self.version_store_file = os.path.join(os.path.dirname(__file__), 'harmony_versions.json')
        self.version_store = self._load_version_store()
        self.scheduler = AsyncIOScheduler()
        print(f"[HarmonyUpdate] 插件初始化完成，共监控 {len(self.apps_to_watch)} 个应用。")

    def _load_version_store(self) -> Dict[str, str]:
        """从JSON文件加载已存储的应用版本"""
        try:
            if os.path.exists(self.version_store_file):
                with open(self.version_store_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[HarmonyUpdate] 读取版本存储文件失败: {e}")
        return {}

    def _save_version_store(self):
        """保存当前版本信息到JSON文件"""
        try:
            with open(self.version_store_file, 'w', encoding='utf-8') as f:
                json.dump(self.version_store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[HarmonyUpdate] 保存版本存储文件失败: {e}")

    async def fetch_version(self, app_config: Dict[str, Any]) -> str:
        """使用Playwright抓取单个应用的当前版本号"""
        url = app_config['detail_url']
        selector = app_config['version_selector']
        async with async_playwright() as p:
            # 启动无头浏览器
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            try:
                # 导航到页面并等待网络空闲
                await page.goto(url, wait_until="networkidle", timeout=15000)
                # 等待特定的版本元素出现
                await page.wait_for_selector(selector, state="attached", timeout=10000)
                # 获取元素的文本内容
                version_text = await page.text_content(selector)
                return version_text.strip() if version_text else ""
            except PlaywrightTimeoutError:
                print(f"[HarmonyUpdate] 警告：抓取 {app_config['app_name']} 时超时，选择器 '{selector}' 可能已失效。")
                return ""
            except Exception as e:
                print(f"[HarmonyUpdate] 抓取 {app_config['app_name']} 时发生错误: {e}")
                return ""
            finally:
                await browser.close()

    async def check_all_apps(self):
        """核心检查函数：遍历所有配置的应用，检查更新"""
        if not self.apps_to_watch:
            print("[HarmonyUpdate] 配置的应用列表为空，请检查插件配置。")
            return

        print(f"[{time.strftime('%H:%M:%S')}] 开始执行定时检查...")
        for app in self.apps_to_watch:
            app_name = app['app_name']
            print(f"  正在检查应用: {app_name}")

            current_version = await self.fetch_version(app)
            if not current_version:
                continue  # 抓取失败，跳过本次

            old_version = self.version_store.get(app_name)

            # 版本比较逻辑
            if old_version is None:
                print(f"    首次记录版本: {current_version}")
                self.version_store[app_name] = current_version
                self._save_version_store()
            elif current_version != old_version:
                print(f"    🔥 发现新版本! {old_version} -> {current_version}")
                # 1. 更新存储
                self.version_store[app_name] = current_version
                self._save_version_store()
                # 2. 发送通知
                await self._send_notification(app, old_version, current_version)
            else:
                print(f"    当前已是最新版本 ({current_version})")

    async def _send_notification(self, app: Dict[str, Any], old_ver: str, new_ver: str):
        """构造并发送更新通知消息"""
        app_name = app['app_name']
        url = app['detail_url']

        # 构造富文本消息（根据你的机器人平台调整）
        message = (
            f"🚀 **鸿蒙应用更新通知**\n\n"
            f"📱 **应用名称:** {app_name}\n"
            f"🔄 **版本更新:** `{old_ver}` → `{new_ver}`\n"
            f"🔗 **市场链接:** {url}\n"
            f"⏰ **检测时间:** {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # 调用AstrBot API发送消息（此处为示例，具体API根据AstrBot版本调整）
        try:
            # 假设获取第一个可用空间（群聊）
            spaces = await self.robot.get_spaces()
            if spaces:
                target_space = spaces[0]
                await self.robot.send_message(target_space, message)
                print(f"    通知消息已发送至空间: {target_space.id}")
            else:
                print("    警告：未找到可发送消息的目标空间。")
        except Exception as e:
            print(f"    发送消息失败: {e}")

    def start_scheduler(self):
        """启动定时任务调度器"""
        if not self.scheduler.running:
            trigger = IntervalTrigger(minutes=self.check_interval)
            self.scheduler.add_job(self.check_all_apps, trigger)
            self.scheduler.start()
            print(f"[HarmonyUpdate] 定时检查已启动，间隔 {self.check_interval} 分钟。")

    def stop_scheduler(self):
        """停止定时任务调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            print("[HarmonyUpdate] 定时检查已停止。")

# AstrBot标准插件入口
def setup(robot: Robot):
    plugin = HarmonyUpdatePlugin(robot)
    # 插件加载后启动定时任务
    robot.on_plugin_enable(lambda: plugin.start_scheduler())
    # 插件禁用时停止定时任务
    robot.on_plugin_disable(lambda: plugin.stop_scheduler())
    return plugin
