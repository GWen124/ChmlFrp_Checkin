import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright
# 修改导入方式
from playwright_stealth import stealth

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    if not username: return "未知"
    return username[:3] + "***" if len(username) > 3 else username[0] + "***"

def identify_gap(bg_path):
    """OpenCV 识别拼图缺口"""
    try:
        img = cv2.imread(bg_path)
        if img is None: return 210
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        canny = cv2.Canny(blurred, 200, 450)
        contours, _ = cv2.findContours(canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 38 < w < 75 and 38 < h < 75 and x > 55:
                return x
        return 210
    except:
        return 210

async def mouse_slide(page, slider_btn, distance):
    """仿真真人轨迹拖动"""
    box = await slider_btn.bounding_box()
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    steps = 45
    for i in range(steps):
        t = (i + 1) / steps
        move = distance * (1 - (1 - t)**3)
        await page.mouse.move(start_x + move, start_y + random.uniform(-3, 3))
        await asyncio.sleep(random.uniform(0.005, 0.015))
    await page.mouse.move(start_x + distance + 5, start_y, steps=5)
    await asyncio.sleep(0.1)
    await page.mouse.move(start_x + distance, start_y, steps=5)
    await page.mouse.up()

async def handle_geetest(page):
    """极验 V4 自动化处理"""
    try:
        radar = page.locator('.geetest_radar_tip, .geetest_radar_btn').first
        if await radar.is_visible(timeout=3000):
            await radar.click()
            await asyncio.sleep(4)
        slider = await page.wait_for_selector('.geetest_slider_button, .geetest_btn', timeout=4000)
        if slider:
            captcha_box = page.locator('.geetest_window, .geetest_box_wrap').first
            await captcha_box.screenshot(path="captcha.png")
            gap_x = identify_gap("captcha.png")
            await mouse_slide(page, slider, gap_x - 5)
            await asyncio.sleep(4)
            await page.evaluate("document.querySelectorAll('.geetest_popup_ghost, .geetest_wrap').forEach(e => e.remove())")
    except:
        pass

async def run_account(account, browser):
    username, password = account['u'], account['p']
    masked = mask_username(username)
    print(f"\n========== 🟢 执行账号: {masked} ==========")

    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    # 使用修正后的 stealth 调用
    await stealth(page)

    try:
        print("   1. 正在访问主页...")
        await page.goto("https://panel.chmlfrp.net/", timeout=90000, wait_until="networkidle")
        
        try:
            await page.wait_for_selector('input[type="text"]', timeout=30000)
        except:
            if await page.get_by_text("Verify you are human").is_visible():
                print("   🛡️ 遇到 Cloudflare 盾，尝试模拟点击验证...")
                await page.mouse.click(300, 300)
                await asyncio.sleep(5)
            
        if "/home" not in page.url:
            print("   👉 正在输入登录信息...")
            await page.fill('input[type="text"]', username)
            await page.fill('input[type="password"]', password)
            await page.click('button[type="submit"]')
            await asyncio.sleep(3)
            await handle_geetest(page)
            try:
                await page.wait_for_url("**/home", timeout=20000)
                print("   ✅ 登录成功")
            except:
                if "/home" not in page.url:
                    print("   🚫 登录确认失败，跳过。")
                    await page.screenshot(path=f"login_fail_{username}.png")
                    await context.close(); return

        print("   2. 正在检测签到...")
        if "/home" not in page.url: await page.goto("https://panel.chmlfrp.net/home")
        await asyncio.sleep(4)

        if await page.get_by_text("已签到").count() > 0:
            print("   ✅ 今日已签到")
        else:
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到").first
            if await checkin_btn.is_visible():
                print("   👉 正在点击签到...")
                await checkin_btn.click(force=True)
                await asyncio.sleep(2)
                await handle_geetest(page)
                await asyncio.sleep(3)
                if await page.get_by_text("已签到").count() > 0:
                    print("   🎉 签到任务完成！")
                else:
                    print("   ⚠️ 签到状态未更新")
            else:
                print("   ⚠️ 未找到签到按钮，可能页面未完全加载")
        
        await page.screenshot(path=f"final_{username}.png")

    except Exception as e:
        print(f"   ❌ 发生异常: {str(e)[:100]}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await context.close()

async def main():
    if not ACCOUNTS_JSON: return print("错误: 未设置 ACCOUNTS_JSON")
    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        for acc in accounts: 
            await run_account(acc, browser)
            await asyncio.sleep(5)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
