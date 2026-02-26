import os
import json
import asyncio
import random
import cv2
import numpy as np
import re
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.getenv("ACCOUNTS_JSON")
# 登录页
LOGIN_URL = "https://panel.chmlfrp.net/sign"
# 面板首页（签到按钮通常在这里）
DASHBOARD_URL = "https://panel.chmlfrp.net/"

def mask_username(username):
    if not username: return "***"
    if len(username) <= 2: return username + "***"
    return username[:2] + "****" + username[-1:]

async def solve_slider(page):
    try:
        print("   >> 正在检测滑块验证...")
        try:
            # 增加等待时间，防止滑块加载慢
            bg_handle = await page.wait_for_selector(".geetest_bg, canvas.geetest_canvas_bg", timeout=5000)
        except:
            print("   >> 未检测到滑块，跳过")
            return

        print("   >> 发现滑块，开始破解...")
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
            print(f"   >> 识别缺口位置: {target_x}")
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
                print("   >> 滑动操作完成")
        await asyncio.sleep(4)
    except Exception as e:
        print(f"   >> 滑块处理异常: {e}")

async def run_account(context, account):
    username = account.get("username")
    password = account.get("password")
    masked_name = mask_username(username)
    print(f"\n========== 开始处理账号: {masked_name} ==========")

    page = await context.new_page()
    checkin_result = {"status": "未知", "msg": "未执行", "points": "0"}
    
    # 监听 API 响应（这是最准确的数据源）
    async def handle_response(response):
        # 监听 /qiandao 接口（签到动作）
        if "qiandao" in response.url and response.request.method == "POST" and response.status == 200:
            try:
                data = await response.json()
                print(f"   [API] 捕获签到响应: {data}")
                checkin_result["msg"] = data.get("msg", "API无消息")
                if data.get("code") == 200:
                    checkin_result["status"] = "成功"
                    # 正则提取积分
                    match = re.search(r'获得(\d+)', str(data.get("msg")))
                    if match: checkin_result["points"] = match.group(1)
                elif data.get("code") == 409: # 409 Conflict 通常是重复签到
                    checkin_result["status"] = "已签到"
            except: pass
        
        # 监听 /qiandao_info 接口（查询信息）
        if "qiandao_info" in response.url and response.status == 200:
            try:
                data = await response.json()
                # print(f"   [API] 捕获状态信息: {data}") # 调试用，平时注释防止日志过长
                d = data.get("data", {})
                if d and d.get("is_signed_in_today") is True:
                     checkin_result["status"] = "已签到"
                     checkin_result["msg"] = "API检测到今日已签"
                     checkin_result["points"] = str(d.get("total_points", 0))
            except: pass

    page.on("response", handle_response)

    try:
        print(f"1. 打开登录页: {LOGIN_URL}")
        await page.goto(LOGIN_URL, timeout=60000)
        
        # 确保在登录 Tab
        try:
            login_tab = page.locator("text='登录'").first
            if await login_tab.is_visible(): await login_tab.click()
        except: pass

        print("2. 填写表单...")
        await page.fill("input[placeholder*='用户'], input[placeholder*='账号'], input[name='username']", username)
        await page.fill("input[type='password']", password)
        
        print("3. 点击登录，等待 API 回应...")
        # 这里的关键是：点击登录后，我们要等待 /login 接口返回，确保登录真的成功了
        async with page.expect_response(lambda response: "login" in response.url and response.status == 200, timeout=15000) as response_info:
            await page.click("button:has-text('登录'), .login-btn, button[type='submit']")
        
        print("   >> 登录接口返回 200，登录成功！")
        
        # --- 强制跳转 ---
        print(f"4. 强制跳转到面板首页: {DASHBOARD_URL}")
        await page.goto(DASHBOARD_URL)
        
        print("5. 等待页面加载关键数据 (qiandao_info)...")
        # 你的抓包显示，页面加载好会请求这个接口。等到这个包，说明页面元素肯定出来了
        try:
            await page.wait_for_response(lambda res: "qiandao_info" in res.url, timeout=15000)
            print("   >> 页面数据加载完毕！")
        except:
            print("   >> 警告：等待数据加载超时，尝试硬找按钮...")

        await asyncio.sleep(3)
        await page.screenshot(path=f"dashboard_{username}.png")

        # --- 寻找按钮逻辑升级 ---
        print("6. 开始寻找签到按钮...")
        
        # 你的截图里按钮文字是 "签到"，旁边是 "签到信息"
        # 策略A: 找 "签到" 按钮
        qiandao_btn = page.locator("button:has-text('签到'), a:has-text('签到'), div[role='button']:has-text('签到')").first
        
        # 策略B: 如果找不到，找 "签到信息" 的兄弟元素 (针对你的截图优化)
        if not await qiandao_btn.is_visible():
            print("   >> 策略A失败，尝试策略B (寻找'签到信息'旁边的按钮)...")
            # 找到包含"签到信息"的元素的父级，然后在父级里找其他按钮
            qiandao_btn = page.locator("text='签到信息'").locator("xpath=..").locator("button, a, div[role='button']").first

        if await qiandao_btn.is_visible():
            btn_text = await qiandao_btn.text_content()
            print(f"   >> 找到按钮！文字内容: [{btn_text.strip()}]")
            
            # 悬停检测是否已签到（根据截图里的tooltip）
            await qiandao_btn.hover()
            await asyncio.sleep(1)
            if await page.locator("text='您今天已经签到过啦'").is_visible():
                 print("   >> 提示框出现：今天已签到")
                 checkin_result["status"] = "已签到"
            else:
                if "已签到" not in checkin_result["status"]:
                    print("   >> 点击签到...")
                    await qiandao_btn.click()
                    await solve_slider(page)
                    await asyncio.sleep(5) # 等待结果刷新
        else:
            print("❌ 致命错误：依然找不到按钮！")
            checkin_result["msg"] = "按钮隐身"
            
            # --- 尸检报告：打印页面 HTML 结构供调试 ---
            print("\n[HTML DUMP START] ---------------------")
            # 只打印 body 内的前 2000 个字符，防止日志爆炸，重点看结构
            content = await page.inner_html("body") 
            # 简单的清理，去掉脚本内容，只留标签
            clean_content = re.sub(r'<script.*?>.*?</script>', '', content, flags=re.DOTALL)
            clean_content = re.sub(r'<style.*?>.*?</style>', '', clean_content, flags=re.DOTALL)
            print(clean_content[:3000]) 
            print("[HTML DUMP END] -----------------------\n")

    except Exception as e:
        print(f"❌ 运行异常: {str(e)[:100]}")
        checkin_result["msg"] = "脚本错误"
        try: await page.screenshot(path=f"error_{username}.png")
        except: pass

    finally:
        await page.close()

    # 优先信任 API 拦截到的状态
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
            # 使用桌面分辨率，方便定位
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
