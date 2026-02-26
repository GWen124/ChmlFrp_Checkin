import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")
# --- 修正：更新为正确的登录地址 ---
LOGIN_URL = "https://panel.chmlfrp.net/sign"

async def solve_slider(page):
    """尝试解决滑块验证码"""
    try:
        print("正在检测是否有滑块验证...")
        # 等待滑块相关元素，超时设短一点
        try:
            # 常见极验类选择器
            bg_handle = await page.wait_for_selector(".geetest_bg, canvas.geetest_canvas_bg", timeout=5000)
        except:
            print("未检测到滑块或无需验证")
            return

        print("检测到滑块，开始处理...")
        box = await bg_handle.bounding_box()
        if not box: return

        # 截图保存用于分析
        await page.screenshot(path="captcha_bg.png", clip=box)
        
        # 简单的图像识别逻辑
        target_x = 150 # 默认值
        try:
            image = cv2.imread("captcha_bg.png")
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            canny = cv2.Canny(blurred, 200, 400)
            contours, _ = cv2.findContours(canny, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                (x, y, w, h) = cv2.boundingRect(contour)
                # 过滤轮廓，寻找缺口
                if 30 < w < 80 and 30 < h < 80 and x > 40:
                    target_x = x
                    break
            print(f"识别缺口位置: {target_x}")
        except:
            print("OpenCV 识别异常，使用默认距离")

        # 寻找滑块按钮
        knob = await page.query_selector(".geetest_btn, .geetest_slider_button")
        if knob:
            box_knob = await knob.bounding_box()
            if box_knob:
                start_x = box_knob["x"] + box_knob["width"] / 2
                start_y = box_knob["y"] + box_knob["height"] / 2
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                # 模拟滑动轨迹
                await page.mouse.move(start_x + target_x, start_y + random.randint(-5, 5), steps=30)
                await asyncio.sleep(0.5)
                await page.mouse.up()
                print("滑动动作完成")
        
        await asyncio.sleep(3) # 等待验证结果
    except Exception as e:
        print(f"滑块处理出错: {e}")

async def run_account(context, account):
    username = account.get("username")
    password = account.get("password")
    print(f"--- 开始处理账号: {username} ---")

    page = await context.new_page()
    checkin_result = {"status": "未知", "msg": "未执行", "points": 0}

    # 监听 API 响应
    async def handle_response(response):
        if "qiandao" in response.url and response.status == 200:
            try:
                data = await response.json()
                print(f"API响应: {data}")
                checkin_result["msg"] = data.get("msg", "无消息")
                code = data.get("code")
                if code == 200:
                    checkin_result["status"] = "成功"
                    import re
                    match = re.search(r'获得(\d+)', str(checkin_result["msg"]))
                    if match: checkin_result["points"] = match.group(1)
                elif code == 409:
                    checkin_result["status"] = "重复签到"
                else:
                    checkin_result["status"] = "失败"
            except: pass
    page.on("response", handle_response)

    try:
        print(f"正在打开登录页面: {LOGIN_URL}")
        await page.goto(LOGIN_URL, timeout=60000)
        await asyncio.sleep(5) 

        # --- 新增：防止进入注册页，尝试点击“登录” ---
        # 很多页面是 /sign 既是登录也是注册，需要切Tab
        try:
            # 查找包含“登录”字样的可点击元素，如果是Tab的话
            login_tab = page.locator("text='登录'").first
            if await login_tab.is_visible():
                print("尝试点击'登录'切换标签...")
                await login_tab.click()
                await asyncio.sleep(1)
        except:
            pass

        # 截图保存，用于调试（如果失败了，你可以去Artifacts看这张图）
        await page.screenshot(path=f"debug_page_{username}.png")
        
        # 填写表单
        print("正在寻找输入框...")
        input_found = False
        # 常见选择器列表
        selectors = [
            "input[name='username']", 
            "input[name='user']",
            "input[type='text']",
            "input[placeholder*='用户']",
            "input[placeholder*='账号']", 
            "input[placeholder*='Email']"
        ]
        
        for sel in selectors:
            try:
                if await page.is_visible(sel):
                    print(f"找到输入框: {sel}")
                    await page.fill(sel, username)
                    input_found = True
                    break
            except: continue
            
        if not input_found:
            raise Exception("无法找到用户名输入框，请检查 debug_page.png")

        await page.fill("input[type='password']", password)
        
        # 点击登录
        print("点击登录...")
        # 常见登录按钮选择器
        login_btns = ["button[type='submit']", "button:has-text('登录')", "button:has-text('Login')", ".login-btn"]
        for btn in login_btns:
             if await page.is_visible(btn):
                 await page.click(btn)
                 break
        
        # 等待跳转
        try:
            await page.wait_for_url("**/panel**", timeout=15000)
            print("登录成功跳转")
        except:
            print("未检测到URL跳转，继续尝试寻找签到按钮...")

        # 尝试签到
        await asyncio.sleep(5) # 多等一会加载 dashboard
        # 保存进入后台后的截图
        await page.screenshot(path=f"dashboard_{username}.png")

        # 寻找签到按钮
        qiandao_selectors = ["text='签到'", "text='每日签到'", ".qiandao-btn", "#checkin-btn", "a:has-text('签到')"]
        btn_clicked = False
        for q_sel in qiandao_selectors:
             try:
                if await page.is_visible(q_sel):
                    print(f"点击签到按钮: {q_sel}")
                    await page.click(q_sel)
                    btn_clicked = True
                    break
             except: continue
        
        if btn_clicked:
            await solve_slider(page)
            await asyncio.sleep(5)
        else:
            print("未找到签到按钮，请检查 dashboard 截图")

    except Exception as e:
        print(f"操作异常: {e}")
        checkin_result["msg"] = f"错误: {str(e)}"
        try: await page.screenshot(path=f"error_{username}.png")
        except: pass

    finally:
        await page.close()

    status_icon = "✅" if checkin_result["status"] == "成功" else ("⚠️" if checkin_result["status"] == "重复签到" else "❌")
    log_msg = f"账号 [{username}] {status_icon} | 状态: {checkin_result['status']} | 消息: {checkin_result['msg']} | 收益: {checkin_result['points']}"
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
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-setuid-sandbox']
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        # 反爬虫绕过
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        
        for account in accounts:
            await run_account(context, account)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
