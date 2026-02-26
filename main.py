import os
import json
import asyncio
import random
import cv2
import numpy as np
import requests
from playwright.async_api import async_playwright

# 从环境变量获取账号信息，格式应为 JSON 字符串: [{"username": "u1", "password": "p1"}, ...]
ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")

# 目标网址
LOGIN_URL = "https://panel.chmlfrp.net/login"
BASE_URL = "https://panel.chmlfrp.net"

async def solve_slider(page):
    """
    尝试解决滑块验证码
    """
    try:
        # 等待滑块元素出现 (根据截图推测的通用选择器，可能需要根据实际DOM调整)
        # 这里假设是常见的极验或类似验证码
        print("检测是否有滑块验证...")
        
        # 等待滑块图片加载。这里需要根据实际页面元素调整选择器
        # 常见选择器：.geetest_canvas_bg, .slide-box, 等
        # 这里使用一个宽泛的等待，如果2秒内没出现则认为无需验证或已通过
        try:
            slider_handle = await page.wait_for_selector(".geetest_slice", timeout=3000) # 滑块图
            bg_handle = await page.wait_for_selector(".geetest_bg", timeout=3000)       # 背景图
        except:
            print("未检测到滑块或无需验证")
            return

        print("检测到滑块，开始尝试破解...")
        
        # 获取图片位置和截图
        box = await bg_handle.bounding_box()
        if not box:
            return

        # 截取背景图用于识别
        await page.screenshot(path="captcha_bg.png", clip=box)
        
        # 截取滑块图（如果有独立滑块图更好，没有则使用背景图计算）
        # 简单的OpenCV缺口识别逻辑
        image = cv2.imread("captcha_bg.png")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # 应用高斯模糊
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        # 边缘检测
        canny = cv2.Canny(blurred, 200, 400)
        
        # 寻找轮廓
        contours, hierarchy = cv2.findContours(canny, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        
        target_x = 0
        for contour in contours:
            (x, y, w, h) = cv2.boundingRect(contour)
            # 过滤掉太小或太大的轮廓，寻找缺口特征（通常是正方形）
            if 30 < w < 80 and 30 < h < 80 and x > 40: # x>40是为了避开左侧初始位置
                target_x = x
                break
        
        if target_x == 0:
            # 备用方案：如果轮廓识别失败，尝试简单的色差对比（需双图）或盲猜
            print("OpenCV 识别失败，尝试默认滑动...")
            target_x = 150 # 默认值
        else:
            print(f"识别到缺口位置 X: {target_x}")

        # 获取滑块按钮
        knob = await page.wait_for_selector(".geetest_btn") # 滑块按钮选择器
        if knob:
            box_knob = await knob.bounding_box()
            start_x = box_knob["x"] + box_knob["width"] / 2
            start_y = box_knob["y"] + box_knob["height"] / 2
            
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            
            # 模拟人类轨迹：加速-减速
            distance = target_x 
            # 轨迹算法简化版
            steps = 15
            for i in range(steps):
                move_x = start_x + (distance * (i+1) / steps)
                # 加入随机抖动
                move_y = start_y + random.randint(-2, 2)
                await page.mouse.move(move_x, move_y)
                await asyncio.sleep(random.uniform(0.01, 0.05))
            
            # 稍微过滑一点再回调
            await page.mouse.move(start_x + distance + 3, start_y)
            await asyncio.sleep(0.1)
            await page.mouse.move(start_x + distance, start_y)
            
            await page.mouse.up()
            print("滑动完成，等待验证结果...")
            await asyncio.sleep(3) # 等待验证结果
            
    except Exception as e:
        print(f"处理滑块时出错: {e}")

async def run_account(context, account):
    username = account.get("username")
    password = account.get("password")
    print(f"--- 开始处理账号: {username} ---")

    page = await context.new_page()
    
    # 变量用于存储签到接口的响应
    checkin_result = {"status": None, "msg": "未知", "points": 0}

    # 监听网络响应，直接解析接口返回的JSON
    async def handle_response(response):
        if "qiandao" in response.url and response.status == 200:
            try:
                data = await response.json()
                # 你的抓包显示返回结构: {"msg": "...", "code": 200, "data": ...}
                print(f"拦截到签到接口响应: {data}")
                checkin_result["msg"] = data.get("msg", "")
                
                # 判断成功与否
                if data.get("code") == 200:
                    checkin_result["status"] = "成功"
                    # 尝试提取积分，msg通常包含 "获得238点积分"
                    import re
                    points_match = re.search(r'获得(\d+)点积分', checkin_result["msg"])
                    if points_match:
                        checkin_result["points"] = points_match.group(1)
                elif data.get("code") == 409:
                    checkin_result["status"] = "重复签到"
                else:
                    checkin_result["status"] = "失败"
            except:
                pass

    page.on("response", handle_response)

    try:
        # 1. 登录
        print("正在打开登录页面...")
        await page.goto(LOGIN_URL)
        
        # 填充表单 (根据常规页面推断选择器，可能需要修正)
        await page.fill('input[placeholder*="用户"]', username) # 模糊匹配 placeholder 包含“用户”的输入框
        await page.fill('input[type="password"]', password)
        
        # 点击登录
        await page.click('button:has-text("登录")')
        
        # 等待登录成功跳转或 Dashboard 加载
        await page.wait_for_url("**/panel**", timeout=10000)
        print("登录成功，进入控制台。")

        # 2. 签到
        # 等待页面加载完成
        await asyncio.sleep(3)
        
        # 寻找签到按钮。通常在右上角或侧边栏，文本包含 "签到"
        # 使用 Playwright 的文本定位器
        print("寻找签到按钮...")
        # 你的抓包 referer 是 panel.chmlfrp.net，按钮可能在首页
        qiandao_btn = page.locator("text=签到").first
        
        if await qiandao_btn.is_visible():
            print("点击签到按钮...")
            await qiandao_btn.click()
            
            # 3. 处理潜在的滑块
            # 点击后可能会立刻发包，也可能会弹窗。等待一会
            await asyncio.sleep(2)
            await solve_slider(page)
            
            # 等待接口返回
            await asyncio.sleep(3)
        else:
            # 如果找不到按钮，可能已经签到过了，或者布局不同
            print("未找到签到按钮，尝试直接访问签到页面或确认是否已签到。")
            
    except Exception as e:
        print(f"操作异常: {e}")
        checkin_result["msg"] = f"脚本执行错误: {str(e)}"
    
    finally:
        await page.close()
        
    # 输出最终日志
    status_icon = "✅" if checkin_result["status"] == "成功" else ("⚠️" if checkin_result["status"] == "重复签到" else "❌")
    log_msg = f"账号 [{username}] {status_icon} | 状态: {checkin_result['status']} | 消息: {checkin_result['msg']} | 收益: {checkin_result['points']} 积分"
    print(log_msg)
    # 写入 GitHub Actions Summary
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
        f.write(f"{log_msg}\n")

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON 环境变量")
        return

    try:
        accounts = json.loads(ACCOUNTS_JSON)
    except:
        print("错误: ACCOUNTS_JSON 格式不正确")
        return

    async with async_playwright() as p:
        # 启动浏览器，headless=True 表示无头模式（不显示界面）
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        for account in accounts:
            await run_account(context, account)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
