import sys
import os

# 将项目根目录添加到 python path，以便能找到 config.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import hmac
import hashlib
import base64
import requests
import json
import logging
from config import Config

logger = logging.getLogger('Notification')

class Notifier:
    """
    消息通知模块 (飞书 Feishu/Lark)
    """
    
    @staticmethod
    def _gen_sign(timestamp, secret):
        """
        飞书签名生成算法
        :param timestamp: 时间戳 (秒级, string)
        :param secret: 密钥 (string)
        :return: 签名字符串
        """
        # 飞书签名算法: timestamp + "\n" + secret
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), 
            digestmod=hashlib.sha256
        ).digest()
        
        # Base64 编码
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign

    @staticmethod
    def send_feishu(msg, is_error=False):
        """
        发送飞书消息
        :param msg: 消息内容
        :param is_error: 是否为报错信息
        """
        webhook_url = Config.FEISHU_WEBHOOK
        secret = Config.FEISHU_SECRET

        if not webhook_url:
            logger.warning("⚠️ 未配置飞书 Webhook，跳过发送消息。")
            return

        try:
            # 1. 构造基础消息内容
            prefix = "❌ [报错]" if is_error else "📢 [通知]"
            if Config.TRADING_MODE == 'DEMO':
                prefix = f"[模拟盘] {prefix}"
            
            # 组合最终文本
            full_text = f"{prefix}\n{msg}\n\n⏱ {time.strftime('%Y-%m-%d %H:%M:%S')}"

            # 2. 构造 Payload
            payload = {
                "msg_type": "text",
                "content": {
                    "text": full_text
                }
            }

            # 3. 处理签名校验 (如果配置了 Secret)
            if secret:
                timestamp = str(int(time.time()))
                sign = Notifier._gen_sign(timestamp, secret)
                
                # 飞书将签名参数放在 JSON Body 中
                payload["timestamp"] = timestamp
                payload["sign"] = sign

            headers = {'Content-Type': 'application/json'}

            # 4. 发送请求
            response = requests.post(
                webhook_url, 
                data=json.dumps(payload), 
                headers=headers, 
                timeout=5
            )
            
            # 5. 检查响应
            # 飞书成功返回: {"code": 0, "msg": "success", ...}
            resp_json = response.json()
            if resp_json.get('code') == 0:
                logger.info("✅ 飞书消息发送成功")
            else:
                logger.error(f"❌ 飞书发送失败: {resp_json}")

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 网络请求异常导致发送失败: {e}")
        except Exception as e:
            logger.error(f"❌ 发送通知时发生未知错误: {e}")

# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("正在测试飞书推送...")
    Notifier.send_feishu("这是一条来自 OKX 量化机器人的测试消息。\n系统正在初始化...")