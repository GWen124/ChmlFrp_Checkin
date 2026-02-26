import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    if not username: return "未知账号"
    if len(username) <= 3: return username[0] + "***"
    return username[:3] + "***"

# === 图像识别核心 ===
def identify_gap(bg_image_path):
    print("   🔍 [视觉] 正在计算缺口位置...")
    try:
        image = cv2.imread(bg_image_path)
        if image is None: return 0
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        canny = cv2.Canny(blurred, 200, 400)
        contours, _ = cv2.findContours(canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        target_x = 0
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 35 < w < 85 and 35 < h < 85 and x > 50:
                target_x = x
                break
        
        if target_x == 0: return 210
        print(f"   🎯 [视觉] 缺口锁定 X = {target_x}")
        return target_x
    except:
        return 210

# === 仿真轨迹 ===
def get_track(distance):
    track = []
    current = 0
    mid = distance * 4 / 5
    t = 0.2
    v = 0
    while current < distance:
        if current < mid: a = 2
        else: a = -3
        v0 = v
        v = v0 + a * t
        move = v0 * t + 1 / 2 * a * t * t
        current += move
        track.append(round(move))
    return track

async def mouse_slide(page, box, target_x):
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    
    tracks = get_track(target_x)
    for track in tracks:
        await page.mouse.move(start_x + track, start_y + random.uniform(-2, 2))
        await asyncio.sleep(random.uniform(0.01, 0.02))
        
    await page.mouse.move(start_x + target_x + 3, start_y, steps=5)
    await asyncio.sleep(0.1)
    await page.mouse.move(start_x + target_x, start_y, steps=5)
    await page.mouse.up()
    print(f"   └── 🖱️ 滑动完成")

async def handle_geetest(page, context_name=""):
    """通用极验处理（登录页+签到页均可用）"""
    try:
        # 1. 点击式验证
        radar = page.locator('.geetest_radar_tip, .geetest_radar_btn')
        if await radar.count() > 0 and await radar.first.is_visible():
            print(f"   🛡️ [{context_name}] 点击验证按钮...")
            await radar.first.click()
            await asyncio.sleep(3)

        # 2. 滑动式验证
        slider = await page.wait_for_selector(
            '.geetest_slider_button, .geetest_btn, .ant-slider-handle', 
            timeout=3000
        )
        if slider:
            print(f"   🛡️ [{context_name}] 发现滑块，启动视觉识别...")
            # 截图背景
            captcha_box = page.locator('.geetest_window, .geetest_box_wrap, .geetest_widget').first
            if await captcha_box.count() > 0 and await captcha_box.is_visible():
                await captcha_box.screenshot(path="captcha_bg.png")
                gap_x = identify_gap("captcha_bg.png")
                final_distance = gap_x - 5
                
                box = await slider.bounding_box()
                if box:
                    await mouse_slide(page, box, final_distance)
                    await asyncio.sleep(4)
                    
            # 尝试清理遮挡
            await page.evaluate("document.querySelectorAll('.geetest_popup_ghost, .geetest_wrap').forEach(e => e.remove())")
    except:
        pass

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked} ==========")
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        # --- 步骤1：登录环节 (加强版) ---
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/", timeout=60000)
        
        # 检测是否卡在 Cloudflare
        try:
            # 增加等待时间，专门等输入框
            await page.wait_for_selector('input[type="text"], input[name="username"]', timeout=20000)
        except:
            print("   ⚠️ 警告：未找到输入框，可能卡在 Cloudflare 或网页加载极慢！截图保存。")
            await page.screenshot(path=f"login_stuck_{username}.png")
            # 尝试盲点一下可能存在的cf验证框
            await page.mouse.click(300, 300) 
            # 这里的 return 会让脚本放弃当前账号，不再做无用功
            print("   🚫 登录环境异常，跳过此账号。")
            await context.close()
            return

        # 正常输入流程
        if "/home" not in page.url:
            print("   👉 输入账号密码...")
            await page.fill('input[type="text"], input[name="username"]', username)
            await page.fill('input[type="password"]', password)
            
            # 点击登录
            login_btn = page.locator('button[type="submit"], button:has-text("登录")').first
            await login_btn.click()
            
            # 【新增】登录也可能触发验证码！
            await asyncio.sleep(2)
            await handle_geetest(page, "登录阶段")
            
            # 等待跳转
            try:
                await page.wait_for_url("**/home", timeout=15000)
                print("   ✅ 登录成功，跳转至首页。")
            except:
                print("   ⚠️ 登录后未跳转，再次检查...")

        # --- 步骤2：确认进入系统 ---
        if "/home" not in page.url:
            await page.goto("https://panel.chmlfrp.net/home")
            await asyncio.sleep(3)
        
        # 终极检查：是否真的进来了？找“注销”或“签到”关键字
        if await page.locator("body").get_by_text("签到").count() == 0 and await page.locator("body").get_by_text("注销").count() == 0:
             print("   ❌ 严重：页面未加载出面板内容，可能登录失败。截图保存。")
             await page.screenshot(path=f"login_failed_{username}.png")
             await context.close()
             return

        # --- 步骤3：签到环节 ---
        print("3. 执行签到检测...")
        
        # 检查是否已签到
        signed_mark = page.locator("text=已签到")
        if await signed_mark.count() > 0:
            print("   ✅ 检测到【已签到】标识，任务完成。")
        else:
            # 找签到按钮
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到").first
            
            if await checkin_btn.is_visible():
                print("   👉 点击签到...")
                await checkin_btn.click(force=True)
                await asyncio.sleep(2)
                
                # 处理签到验证码
                await handle_geetest(page, "签到阶段")
                
                await asyncio.sleep(3)
                
                # 再次检查结果
                if await signed_mark.count() > 0:
                    print("   🎉 签到成功！")
                    await page.screenshot(path=f"success_{username}.png")
                else:
                    print("   ⚠️ 签到后状态未更新，可能验证失败。")
                    await page.screenshot(path=f"checkin_fail_{username}.png")
            else:
                print("   ⚠️ 未找到可点击的签到按钮。")

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        await page.screenshot(path=f"error_{username}.png")
    
    finally:
        await context.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        for account in accounts:
            await run_one_account(account, browser)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
