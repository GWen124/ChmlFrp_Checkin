import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")
LOGIN_URL = "https://panel.chmlfrp.net/login"

async def solve_slider(page):
    """尝试解决滑块验证码"""
    try:
        print("正在检测是否有滑块验证...")
        # 等待滑块相关元素，超时设短一点，如果没有就是没出验证码
        try:
            # 常见极验类选择器，根据实际情况可能需要调整
            bg_handle = await page.wait_for_selector(".geetest_bg, canvas.geetest_canvas_bg", timeout=5000)
        except:
            print("未检测到滑块或无需验证 (或选择器不匹配)")
            return

        print("检测到滑块，开始处理...")
        box = await bg_handle.bounding_box()
        if not box: return

        # 截图保存用于分析
        await page.screenshot(path="captcha_bg.png", clip=box)
        
        # 简单的图像识别逻辑 (这里简化处理，核心是先跑通流程)
        target_x = 150 # 默认值，防止识别失败报错
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

    # 监听网络请求获取接口返回
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
        print("正在打开登录页面...")
        await page.goto(LOGIN_URL, timeout=60000) # 增加超时时间到60秒
        
        # 等待页面加载，如果有 Cloudflare 盾，这里会卡住
        await asyncio.sleep(5) 

        # --- 调试步骤：保存页面截图 ---
        # 如果找不到元素，我们需要看看到底显示了什么
        await page.screenshot(path=f"debug_page_{username}.png")
        
        # 尝试多种选择器定位用户名输入框
        print("正在寻找输入框...")
        # 策略1: name属性 (最标准)
        # 策略2: type属性 (宽泛)
        # 策略3: placeholder (模糊匹配)
        input_found = False
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
                    print(f"找到输入框，使用选择器: {sel}")
                    await page.fill(sel, username)
                    input_found = True
                    break
            except: continue
            
        if not input_found:
            raise Exception("无法找到用户名输入框，请检查 debug_page.png 截图")

        # 寻找密码框
        await page.fill("input[type='password']", password)
        
        # 点击登录 (尝试多重定位)
        print("点击登录...")
        login_btns = ["button[type='submit']", "button:has-text('登录')", "button:has-text('Login')"]
        for btn in login_btns:
             if await page.is_visible(btn):
                 await page.click(btn)
                 break
        
        # 等待跳转
        try:
            await page.wait_for_url("**/panel**", timeout=15000)
            print("登录成功跳转")
        except:
            print("未检测到URL跳转，可能通过AJAX登录或验证失败")

        # 尝试签到
        await asyncio.sleep(3)
        # 查找签到按钮 (根据通常的 panel 面板)
        # 有些面板可能在左侧菜单，有些在顶部
        qiandao_selectors = ["text='签到'", "text='每日签到'", ".qiandao-btn", "#checkin-btn"]
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
            await asyncio.sleep(3)
        else:
            print("未找到签到按钮，可能需要手动更新选择器")

    except Exception as e:
        print(f"操作异常: {e}")
        checkin_result["msg"] = f"错误: {str(e)}"
        # 发生错误时再次截图
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
        # 添加参数以规避简单的机器人检测
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # 注入脚本移除 webdriver 属性
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        for account in accounts:
            await run_account(context, account)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
