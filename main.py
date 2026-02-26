import os
import json
import asyncio
import random
import cv2
import numpy as np
import re
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")
LOGIN_URL = "https://panel.chmlfrp.net/sign"

def mask_username(username):
    """
    账号脱敏处理：只显示前3位，后面用*代替
    例如: 9708281 -> 970****
    """
    if not username: return "***"
    if len(username) <= 3: return username + "***"
    return username[:3] + "*" * (len(username) - 3)

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
        except: pass

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
    points = "0"
    try:
        # 尝试寻找签到信息按钮
        info_btns = await page.locator("text='签到信息'").all()
        if info_btns:
            print("正在悬停'签到信息'获取积分...")
            await info_btns[0].hover()
            await asyncio.sleep(2)
            content = await page.content()
            match = re.search(r'累计签到积分\s*[:：]\s*(\d+)', content)
            if match:
                points = match.group(1)
                print(f"从统计信息中读取到积分: {points}")
    except: pass
    return points

async def run_account(context, account):
    username = account.get("username")
    password = account.get("password")
    
    # --- 生成脱敏后的用户名用于日志显示 ---
    masked_name = mask_username(username)
    print(f"--- 开始处理账号: {masked_name} ---")

    page = await context.new_page()
    checkin_result = {"status": "未知", "msg": "未执行", "points": "0"}
    
    # 拦截 API 响应
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
        
        try:
            login_tab = page.locator("text='登录'").first
            if await login_tab.is_visible(): await login_tab.click()
        except: pass

        # 使用真实账号填写表单，但日志里不体现
        await page.fill("input[placeholder*='用户'], input[placeholder*='账号'], input[name='username']", username)
        await page.fill("input[type='password']", password)
        await page.click("button:has-text('登录'), .login-btn, button[type='submit']")
        
        try:
            await page.wait_for_url("**/panel**", timeout=20000)
            print("登录成功，等待页面资源加载...")
            try:
                await page.wait_for_load_state('networkidle', timeout=10000)
            except:
                print("页面加载较慢，继续尝试...")
        except:
            print("警告：未检测到URL变化，但尝试继续寻找元素...")

        await asyncio.sleep(5)
        # 截图文件名保留真实用户名以便调试（Artifacts默认只有你能看），如果介意也可以改成 masked_name
        await page.screenshot(path=f"dashboard_{username}.png")

        # 寻找签到按钮
        target_btn = None
        possible_texts = ["签到", "每日签到", "点击签到", "Check in", "Sign in"]
        
        for text in possible_texts:
            locator = page.locator(f"text='{text}'")
            count = await locator.count()
            for i in range(count):
                el = locator.nth(i)
                if await el.is_visible():
                    target_btn = el
                    print(f"找到签到按钮，文本为: {text}")
                    break
            if target_btn: break
        
        if target_btn:
            print("检测按钮状态...")
            await target_btn.hover()
            await asyncio.sleep(2)
            
            # 检测是否已签到
            if await page.locator("text='您今天已经签到过啦'").is_visible() or \
               await page.locator("text='已签到'").is_visible():
                print("提示：今天已签到")
                checkin_result["status"] = "已签到"
                checkin_result["msg"] = "无需重复签到"
                checkin_result["points"] = await get_points_from_info(page)
            else:
                print("点击签到...")
                await target_btn.click()
                await solve_slider(page)
                await asyncio.sleep(3)
                if checkin_result["points"] == "0":
                    checkin_result["points"] = await get_points_from_info(page)
                if checkin_result["status"] == "未知":
                    checkin_result["status"] = "成功"
                    checkin_result["msg"] = "执行完毕"
        else:
            print("❌ 依然未找到签到按钮！")
            checkin_result["msg"] = "找不到按钮"

    except Exception as e:
        print(f"执行异常: {str(e)[:100]}...") # 限制错误日志长度防止泄露敏感信息
        checkin_result["msg"] = f"Error occurred"
        try: await page.screenshot(path=f"error_{username}.png")
        except: pass

    finally:
        await page.close()

    # --- 日志输出使用脱敏后的用户名 ---
    status_icon = "✅" if checkin_result["status"] in ["成功", "已签到"] else "❌"
    log_msg = f"账号 [{masked_name}] {status_icon} | 状态: {checkin_result['status']} | 消息: {checkin_result['msg']} | 积分: {checkin_result['points']}"
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
        
        for account in accounts:
            # 保持大屏分辨率 1920x1080 确保按钮可见
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            
            await run_account(context, account)
            await context.close()
            
            delay = random.randint(10, 20)
            print(f"等待 {delay} 秒...")
            await asyncio.sleep(delay)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
