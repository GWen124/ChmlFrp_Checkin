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
DASHBOARD_URL = "https://panel.chmlfrp.net/"

async def solve_geetest_v4(page):
    """专门处理 Geetest v4 滑块"""
    try:
        print("      >> [滑块] 正在检测 Geetest v4...")
        # v4 的特征是 canvas 画布，且通常在 modal 容器里
        # 等待滑块出现的容器
        try:
            # 等待 canvas 出现，或者 .geetest_box
            wrapper = await page.wait_for_selector(".geetest_box, .geetest_window, canvas.geetest_canvas_bg", state="visible", timeout=6000)
        except:
            print("      >> [滑块] 未检测到验证码弹出")
            return

        print("      >> [滑块] 验证码已弹出！准备破解...")
        await asyncio.sleep(1) # 等待图片完全渲染
        
        # 寻找背景图 canvas
        # v4 通常有三个 canvas：背景(bg)、缺口(slice)、完整图(full)
        # 我们找背景图，通常类名包含 bg
        bg_canvas = await page.query_selector("canvas.geetest_canvas_bg")
        if not bg_canvas:
            # 备选：有时候没有特定 class，找第一个大的 canvas
            canvases = await page.query_selector_all("canvas")
            for c in canvases:
                box = await c.bounding_box()
                if box and box['width'] > 200: # 假设背景图宽度大于200
                    bg_canvas = c
                    break
        
        if not bg_canvas:
            print("      >> [滑块] 无法定位背景图片")
            return

        box = await bg_canvas.bounding_box()
        await page.screenshot(path="captcha_bg.png", clip=box)
        
        # 识别缺口
        target_x = 150
        try:
            image = cv2.imread("captcha_bg.png")
            # 简单的缺口识别算法
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # v4 的图片可能有干扰，加一点高斯模糊
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            canny = cv2.Canny(blurred, 200, 400)
            contours, _ = cv2.findContours(canny, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                (x, y, w, h) = cv2.boundingRect(contour)
                # v4 的缺口通常比较规整，正方形或拼图状
                if 35 < w < 85 and 35 < h < 85 and x > 40:
                    target_x = x
                    break
            print(f"      >> [滑块] 计算缺口位置: {target_x}")
        except Exception as e:
            print(f"      >> [滑块] 识别算法出错: {e}，使用默认距离")

        # 寻找滑块按钮
        # v4 的滑块按钮通常是 .geetest_slider_button 或 .geetest_btn
        slider_btn = await page.query_selector(".geetest_slider_button, .geetest_btn, .geetest_slider_arrow")
        
        if slider_btn:
            box_btn = await slider_btn.bounding_box()
            if box_btn:
                start_x = box_btn["x"] + box_btn["width"] / 2
                start_y = box_btn["y"] + box_btn["height"] / 2
                
                await page.mouse.move(start_x, start_y)
                await page.mouse.down()
                
                # 模拟真人轨迹
                await page.mouse.move(start_x + target_x, start_y + random.randint(-2, 2), steps=35)
                # 稍微回退一点，模拟修正
                await page.mouse.move(start_x + target_x - 2, start_y, steps=5)
                await page.mouse.move(start_x + target_x, start_y, steps=5)
                
                await asyncio.sleep(0.5)
                await page.mouse.up()
                print("      >> [滑块] 滑动完成")
        
        await asyncio.sleep(5) # 等待验证结果
    except Exception as e:
        print(f"      >> [滑块] 异常: {e}")

async def run_account(context, account, account_index):
    username = account.get("username")
    password = account.get("password")
    account_label = f"账号 {account_index}"
    print(f"\n========== 开始处理 {account_label} ==========")

    page = await context.new_page()
    checkin_result = {"status": "未知", "msg": "未执行", "points": "0"}
    
    # API 监听
    async def handle_response(response):
        if "qiandao" in response.url and response.request.method == "POST" and response.status == 200:
            try:
                data = await response.json()
                print(f"   [API] 签到返回: {data.get('msg')}")
                checkin_result["msg"] = data.get("msg", "API无消息")
                if data.get("code") == 200:
                    checkin_result["status"] = "成功"
                    match = re.search(r'获得(\d+)', str(data.get("msg")))
                    if match: checkin_result["points"] = match.group(1)
                elif data.get("code") == 409:
                    checkin_result["status"] = "已签到"
            except: pass
        
        if "qiandao_info" in response.url and response.status == 200:
            try:
                data = await response.json()
                d = data.get("data", {})
                if d and d.get("is_signed_in_today") is True:
                     checkin_result["status"] = "已签到"
                     checkin_result["msg"] = "API检测: 今日已签"
                     checkin_result["points"] = str(d.get("total_points", 0))
                     print(f"   [API] 今日已签到，积分: {checkin_result['points']}")
            except: pass

    page.on("response", handle_response)

    try:
        print(f"1. 打开登录页...")
        await page.goto(LOGIN_URL, timeout=60000)
        
        # 确保在登录Tab
        try:
            login_tab = page.locator("text='登录'").first
            if await login_tab.is_visible(): await login_tab.click()
        except: pass

        print("2. 正在登录...")
        await page.fill("input[name='username'], input[placeholder*='账号'], input[placeholder*='用户']", username)
        await page.fill("input[type='password']", password)
        
        # 点击登录并等待
        login_success = False
        try:
            async with page.expect_response(lambda response: "login" in response.url and response.status == 200, timeout=20000) as response_info:
                await page.click("button:has-text('登录'), button[type='submit']")
            print("   >> 登录接口返回 200")
            login_success = True
        except:
            print("   >> ⚠️ 登录接口超时或未捕获，可能网络卡顿")

        # 强制跳转到面板
        print(f"3. 前往面板: {DASHBOARD_URL}")
        await page.goto(DASHBOARD_URL)
        await page.wait_for_load_state('domcontentloaded')

        # --- 登录状态检查 ---
        # 如果还在 /sign 页面，说明登录失败被踢回来了
        if "/sign" in page.url:
            print("   >> ❌ 检测到 URL 仍为登录页，尝试刷新并重新登录...")
            # 这里可以写重试逻辑，或者直接报错
            checkin_result["msg"] = "登录失败(Cookie未生效)"
            # 简单的重试：这里如果不成功，后面也没法跑
        
        print("4. 等待加载...")
        # 尝试刷新一次确保数据加载
        if not login_success:
             print("   >> 刚才登录不稳定，刷新页面...")
             await page.reload()
             await asyncio.sleep(5)

        # 检查是否已通过API检测到签到
        if checkin_result["status"] == "已签到":
            print("   >> API 显示已签到，跳过后续步骤")
        else:
            print("5. 寻找签到按钮...")
            await asyncio.sleep(2)
            
            # 按钮定位逻辑
            qiandao_btn = None
            # 策略：直接找包含“签到”文本的元素，但排除“签到信息”
            # 使用 XPath 排除包含 "信息" 的文本
            try:
                # 寻找文本包含“签到”但不包含“信息”的元素
                btn_loc = page.locator("xpath=//*[contains(text(), '签到') and not(contains(text(), '信息'))]")
                count = await btn_loc.count()
                for i in range(count):
                    el = btn_loc.nth(i)
                    if await el.is_visible():
                        # 再次确认是不是按钮或可点击元素
                        tag = await el.evaluate("el => el.tagName")
                        if tag in ['BUTTON', 'A', 'DIV', 'SPAN']:
                            qiandao_btn = el
                            print(f"   >> 找到按钮: {tag}")
                            break
            except: pass
            
            # 备用策略：找“签到信息”旁边的按钮
            if not qiandao_btn:
                print("   >> 策略1未找到，尝试找兄弟元素...")
                info_btn = page.locator("text='签到信息'")
                if await info_btn.count() > 0:
                     # 找它的前一个兄弟
                     parent = info_btn.first.locator("xpath=..")
                     # 假设按钮在同一个父级下
                     qiandao_btn = parent.locator("button, div[role='button']").first

            if qiandao_btn:
                print("   >> 点击签到按钮...")
                # 截图防崩
                await page.screenshot(path=f"before_click_{account_index}.png")
                await qiandao_btn.click()
                
                # --- 核心：处理 Geetest v4 ---
                # 点击后等待验证码弹窗
                await solve_geetest_v4(page)
                
                # 再次等待，让积分更新
                await asyncio.sleep(5)
                # 尝试再次获取积分
                if checkin_result["points"] == "0":
                    # 尝试从弹出的提示框或页面获取
                    pass 
            else:
                print(f"❌ 找不到按钮。当前URL: {page.url}")
                # 打印页面文本辅助调试
                # body_text = await page.inner_text("body")
                # print(body_text[:200])
                checkin_result["msg"] = "找不到签到按钮"

    except Exception as e:
        print(f"❌ 异常: {str(e)[:100]}")
        checkin_result["msg"] = "脚本错误"

    finally:
        await page.close()

    status_icon = "✅" if checkin_result["status"] in ["成功", "已签到"] else "❌"
    log_msg = f"{account_label} {status_icon} | 状态: {checkin_result['status']} | 消息: {checkin_result['msg']} | 积分: {checkin_result['points']}"
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
        
        for index, account in enumerate(accounts):
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            
            await run_account(context, account, index + 1)
            await context.close()
            
            delay = random.randint(10, 20)
            print(f"等待 {delay} 秒...")
            await asyncio.sleep(delay)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
