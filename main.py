import os
import json
import asyncio
import random
import cv2
import numpy as np
import re
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")
# 更新为正确的登录页
LOGIN_URL = "https://panel.chmlfrp.net/sign"

async def solve_slider(page):
    """尝试解决滑块验证码"""
    try:
        print("正在检测是否有滑块验证...")
        try:
            bg_handle = await page.wait_for_selector(".geetest_bg, canvas.geetest_canvas_bg", timeout=3000)
        except:
            print("无需滑块验证")
            return

        print("检测到滑块，开始处理...")
        box = await bg_handle.bounding_box()
        if not box: return

        await page.screenshot(path="captcha_bg.png", clip=box)
        
        target_x = 150 
        try:
            image = cv2.imread("captcha_bg.png")
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            canny = cv2.Canny(blurred, 200, 400)
            contours, _ = cv2.findContours(canny, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                (x, y, w, h) = cv2.boundingRect(contour)
                if 30 < w < 80 and 30 < h < 80 and x > 40:
                    target_x = x
                    break
            print(f"识别缺口位置: {target_x}")
        except:
            pass

        knob = await page.query_selector(".geetest_btn, .geetest_slider_button")
        if knob:
            box_knob = await knob.bounding_box()
            if box_knob:
                start_x = box_knob["x"] + box_knob["width"] / 2
                start_y = box_knob["y"] + box_knob["height"] / 2
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                await page.mouse.move(start_x + target_x, start_y + random.randint(-5, 5), steps=30)
                await asyncio.sleep(0.5)
                await page.mouse.up()
                print("滑动完成")
        
        await asyncio.sleep(3)
    except Exception as e:
        print(f"滑块处理出错: {e}")

async def get_points_from_info(page):
    """从'签到信息'按钮的悬停提示中获取积分"""
    points = "0"
    try:
        info_btn = page.locator("text='签到信息'").first
        if await info_btn.is_visible():
            print("正在悬停'签到信息'获取积分...")
            await info_btn.hover()
            await asyncio.sleep(2) # 等待提示框浮现
            
            # 你的截图显示提示框里有 "累计签到积分: 355"
            # 我们尝试获取包含该文本的元素
            content = await page.content()
            match = re.search(r'累计签到积分\s*[:：]\s*(\d+)', content)
            if match:
                points = match.group(1)
                print(f"从统计信息中读取到积分: {points}")
            else:
                print("未在页面源码中匹配到积分格式")
    except Exception as e:
        print(f"获取统计信息失败: {e}")
    return points

async def run_account(context, account):
    username = account.get("username")
    password = account.get("password")
    print(f"--- 开始处理账号: {username} ---")

    page = await context.new_page()
    checkin_result = {"status": "未知", "msg": "未执行", "points": "0"}
    
    # 拦截 API 响应作为备用数据源
    async def handle_response(response):
        if "qiandao" in response.url and response.status == 200:
            try:
                data = await response.json()
                if data.get("code") == 200:
                    match = re.search(r'获得(\d+)', str(data.get("msg")))
                    if match: checkin_result["points"] = match.group(1)
            except: pass
    page.on("response", handle_response)

    try:
        print(f"打开登录页: {LOGIN_URL}")
        await page.goto(LOGIN_URL, timeout=60000)
        
        # 1. 切换到登录 Tab (防止默认是注册)
        try:
            # 查找所有包含“登录”的元素，点击看起来像 Tab 的那个
            # 这里使用一个更宽泛的策略，点击页面上可见的“登录”文本
            login_tab = page.locator("text='登录'").first
            if await login_tab.is_visible():
                await login_tab.click()
                await asyncio.sleep(1)
        except: pass

        # 2. 登录
        await page.fill("input[placeholder*='用户'], input[placeholder*='账号'], input[name='username']", username)
        await page.fill("input[type='password']", password)
        
        # 点击登录按钮
        await page.click("button:has-text('登录'), .login-btn, button[type='submit']")
        
        # 等待进入后台
        try:
            await page.wait_for_url("**/panel**", timeout=15000)
            print("登录成功，进入后台")
        except:
            print("未检测到跳转，尝试继续操作...")

        await asyncio.sleep(5) # 等待Dashboard加载
        await page.screenshot(path=f"dashboard_{username}.png") # 截图留底

        # 3. 寻找签到按钮并判断状态
        qiandao_btn = page.locator("text='签到'").first
        
        if await qiandao_btn.is_visible():
            print("找到签到按钮，正在检测是否已签到（悬停检测）...")
            
            # 模拟鼠标悬停
            await qiandao_btn.hover()
            await asyncio.sleep(2) # 等待 tooltip 出现
            
            # 检查是否有“已签到”提示
            # 根据你的截图，提示文本是 "您今天已经签到过啦"
            is_signed = await page.locator("text='您今天已经签到过啦'").is_visible()
            
            if is_signed:
                print("检测到提示：今天已经签到过啦")
                checkin_result["status"] = "已签到"
                checkin_result["msg"] = "无需重复签到"
                # 获取积分信息
                checkin_result["points"] = await get_points_from_info(page)
            else:
                print("未检测到已签到提示，尝试点击签到...")
                await qiandao_btn.click()
                
                # 处理可能出现的滑块
                await solve_slider(page)
                await asyncio.sleep(3)
                
                # 再次获取积分（如果API拦截没拿到，就从信息板拿）
                if checkin_result["points"] == "0":
                    checkin_result["points"] = await get_points_from_info(page)
                    
                if checkin_result["status"] == "未知":
                    checkin_result["status"] = "成功" # 假设流程走完即成功
                    checkin_result["msg"] = "签到动作已执行"
        else:
            print("未找到签到按钮")
            checkin_result["msg"] = "找不到签到按钮"

    except Exception as e:
        print(f"执行异常: {e}")
        checkin_result["msg"] = f"Error: {str(e)}"
        await page.screenshot(path=f"error_{username}.png")

    finally:
        await page.close()

    status_icon = "✅" if checkin_result["status"] in ["成功", "已签到"] else "❌"
    log_msg = f"账号 [{username}] {status_icon} | 状态: {checkin_result['status']} | 消息: {checkin_result['msg']} | 当前积分: {checkin_result['points']}"
    print(log_msg)
    
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(f"{log_msg}\n")

async def main():
    if not ACCOUNTS_JSON: return
    accounts = json.loads(ACCOUNTS_JSON)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        
        # 4. 账号隔离：为每个账号创建一个全新的 Context
        for account in accounts:
            # 创建独立的上下文 (Cookie、缓存是隔离的)
            context = await browser.new_context(
                user_agent=f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/12{random.randint(0, 5)}.0.0.0 Safari/537.36"
            )
            # 反检测脚本
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            
            await run_account(context, account)
            await context.close() # 关闭上下文，清理Cookie
            
            # 5. 安全延时：账号间增加随机等待，降低被判定为机器人的风险
            delay = random.randint(10, 30)
            print(f"为了安全，等待 {delay} 秒后处理下一个账号...")
            await asyncio.sleep(delay)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
