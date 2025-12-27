#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstrBot插件：鸿蒙应用更新实时推送
通过接收Webhook实现实时通知
"""
import asyncio
import hmac
import hashlib
from typing import Any, Dict
from astrbot.core import Space, SpaceType, MessageEvent, Robot, BotEvent
from astrbot.core.network import http_server
from astrbot.core.message import MessageSegment
from flask import Flask, request, jsonify, abort

class HarmonyUpdatePlugin:
    def __init__(self, robot: Robot):
        self.robot = robot
        self.app = Flask(__name__)
        self.config = {}  # 将从metadata.yaml加载
        self.setup_routes()
        
    def setup_routes(self):
        """设置Webhook路由"""
        @self.app.route('/webhook/harmony-update', methods=['POST'])
        def handle_webhook():
            return self.process_webhook(request)
            
        # 健康检查端点
        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({'status': 'ok', 'plugin': 'harmony-update'})
    
    def process_webhook(self, request):
        """处理Webhook请求"""
        # 1. 验证签名（确保请求来自可信源）
        if not self.verify_signature(request):
            abort(401, 'Invalid signature')
        
        # 2. 解析更新数据
        data = request.get_json()
        if not data:
            abort(400, 'Invalid JSON data')
        
        # 3. 触发异步处理
        asyncio.create_task(self.handle_update_event(data))
        
        return jsonify({'status': 'received'})
    
    def verify_signature(self, request) -> bool:
        """验证Webhook签名"""
        # 从配置获取密钥
        secret = self.config.get('webhook_secret', '').encode()
        if not secret:
            return True  # 未配置密钥时跳过验证
        
        # 获取签名头
        signature = request.headers.get('X-Harmony-Signature', '')
        if not signature:
            return False
        
        # 计算HMAC SHA256
        payload = request.get_data()
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    async def handle_update_event(self, data: Dict[str, Any]):
        """处理更新事件并发送通知"""
        try:
            # 提取更新信息
            app_name = data.get('app_name', '未知应用')
            version = data.get('version', '未知版本')
            changelog = data.get('changelog', '')
            download_url = data.get('download_url', '')
            release_time = data.get('release_time', '')
            
            # 构建消息内容
            message = await self.build_update_message(
                app_name, version, changelog, download_url, release_time
            )
            
            # 获取目标空间（QQ群/私聊）
            target_space = await self.get_target_space()
            if target_space:
                # 发送消息
                await self.robot.send_message(target_space, message)
                print(f"[HarmonyUpdate] 已推送 {app_name} v{version} 更新")
            else:
                print("[HarmonyUpdate] 未找到目标推送空间")
                
        except Exception as e:
            print(f"[HarmonyUpdate] 处理更新事件失败: {e}")
    
    async def build_update_message(self, app_name: str, version: str, 
                                  changelog: str, download_url: str, 
                                  release_time: str) -> list:
        """构建富文本消息"""
        message = []
        
        # 标题
        message.append(MessageSegment.text(f"🚀 发现 {app_name} 新版本！\n"))
        message.append(MessageSegment.text(f"📦 版本号: v{version}\n"))
        
        if release_time:
            message.append(MessageSegment.text(f"⏰ 发布时间: {release_time}\n"))
        
        # 更新日志
        if changelog:
            message.append(MessageSegment.text("\n📝 更新内容:\n"))
            # 限制日志长度
            if len(changelog) > 500:
                changelog = changelog[:500] + "..."
            message.append(MessageSegment.text(f"{changelog}\n"))
        
        # 下载链接
        if download_url:
            message.append(MessageSegment.text(f"\n🔗 下载链接: {download_url}"))
        
        return message
    
    async def get_target_space(self):
        """获取配置的推送目标空间"""
        # 这里从配置读取目标QQ群或用户
        # 示例：返回第一个可用空间
        spaces = await self.robot.get_spaces()
        return spaces[0] if spaces else None
    
    def run_webhook_server(self):
        """启动Webhook服务器"""
        port = self.config.get('webhook_port', 5000)
        host = self.config.get('webhook_host', '0.0.0.0')
        
        print(f"[HarmonyUpdate] Webhook服务器启动在 http://{host}:{port}")
        print(f"[HarmonyUpdate] Webhook端点: http://{host}:{port}/webhook/harmony-update")
        
        # 注意：在生产环境中建议使用生产级WSGI服务器
        self.app.run(host=host, port=port, debug=False)

# 插件入口
def setup(robot: Robot):
    plugin = HarmonyUpdatePlugin(robot)
    
    # 从元数据加载配置
    plugin.config = robot.plugin_config
    
    # 在新线程中启动Webhook服务器
    import threading
    server_thread = threading.Thread(target=plugin.run_webhook_server, daemon=True)
    server_thread.start()
    
    return plugin
