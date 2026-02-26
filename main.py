import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON', "[]")


def mask_username(username):
    if not username:
        return "未知账号"
    if len(username) <= 3:
        return username[0] + "***"
    return username[:3] + "***"


# === 图像识别核心 ===
def identify_gap(bg_image_path):
    print("   🔍 [视觉] 正在计算缺口位置...")
    try:
        image = cv2.imread(bg_image_path)
        if image is None:
            print("   ⚠️ 背景图片加载失败")
            return 0
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        canny = cv2.Canny(blurred, 200, 400)
        contours, _ = cv2.findContours(canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        target_x = 0
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if 35 < w < 85 and 35 < h < 85 and x > 50:
                target_x = x
                break

        if target_x == 0:
            print("   ❌ 未找到明显缺口，返回默认值 210")
            return 210
        print(f"   🎯 [视觉] 缺口锁定 X = {target_x}")
        return target_x
    except Exception as e:
        print(f"   ❌ 识别缺口失败: {e}")
        return 210


# === 仿真轨迹 ===
def get_track(distance):
    track = []
    current = 0
    mid = distance * 4 / 5
    t = 0.2  # 单位时间
    v = 0  # 初速度
    while current < distance:
        if current < mid:
            a = 2  # 加速度
        else:
            a = -3
        v0 = v
        v = v0 + a * t
        move = v0 * t + 1 / 2 * a * t * t
        current += move
        track.append(round(move) + random.randint(-2, 2))  # 随机微调
    return track


async def mouse_slide(page, box, target_x):
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()

    tracks = get_track(target_x)
    for track in tracks:
        start_x += track
        await page.mouse.move(start_x, start_y + random.uniform(-2, 2))
        await asyncio.sleep(random.uniform(0.01, 0.02))

    await page.mouse.move(start_x + target_x + 3, start_y, steps=5)
    await asyncio.sleep(0.1)
    await page.mouse.move(start_x + target_x, start_y, steps=5)
    await page.mouse.up()
    print(f"   └── 🖱️ 滑动完成")


async def handle_geetest(page, context_name="", max_retries=3):
    """通用极验处理，支持多次重试"""
    for attempt in range(max_retries):
        print(f"   🔄 第 {attempt + 1}/{max_retries} 次尝试处理验证码...")
        try:
            # 点击式验证
            radar = page.locator('.geetest_radar_tip, .geetest_radar_btn')
            if await radar.count() > 0 and await radar.first.is_visible():
                print(f"   🛡️ [{context_name}] 点击验证按钮...")
                await radar.first.click()
                await asyncio.sleep(3)

            # 滑动式验证
            slider = page.locator('.geetest_slider_button')
            if await slider.count() > 0 and await slider.first.is_visible():
                print(f"   🛡️ [{context_name}] 发现滑块，启动视觉识别...")
                captcha_box = page.locator('.geetest_window, .geetest_box_wrap, .geetest_widget').first
                if await captcha_box.count() > 0 and await captcha_box.is_visible():
                    await captcha_box.screenshot(path=f"captcha_bg_{context_name}.png")
                    gap_x = identify_gap(f"captcha_bg_{context_name}.png")
                    final_distance = max(0, gap_x - 5)

                    box = await slider.bounding_box()
                    if box:
                        await mouse_slide(page, box, final_distance)
                        await asyncio.sleep(4)

                # 尝试清理遮挡
                await page.evaluate("document.querySelectorAll('.geetest_popup_ghost, .geetest_wrap').forEach(e => e.remove())")
                return  # 验证成功直接返回
        except Exception as e:
            print(f"   ❌ 验证码处理异常: {e}")

    print("   ❌ 最终处理验证码失败，放弃操作。")


async def run_one_account(account, browser):
    username = account.get('u')
    password = account.get('p')
    masked = mask_username(username)

    if not username or not password:
        print(f"⚠️ 跳过无效账号: {masked}")
        return

    print(f"\n========== 🟢 正在执行: {masked} ==========")
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        print("1. 访问登录页...")
        try:
            await page.goto("https://panel.chmlfrp.net/", timeout=60000)
        except Exception as e:
            print(f"   ❌ 打开页面失败: {e}")
            await context.close()
            return

        await page.wait_for_selector('input[name="username"]', timeout=20000)

        print("   👉 输入账号密码...")
        await page.fill('input[name="username"]', username)
        await page.fill('input[name="password"]', password)

        login_btn = page.locator('button[type="submit"]').first
        await login_btn.click()
        await asyncio.sleep(2)

        # 验证登录验证码
        await handle_geetest(page, "登录阶段")

        # 检查是否进入主页
        try:
            await page.wait_for_url("**/home", timeout=15000)
            print("   ✅ 登录成功！")
        except:
            print("   ❌ 登录后未跳转主页，可能失败！截图保存。")
            await page.screenshot(path=f"login_failed_{username}.png")
            return

        print("2. 检测签到按钮...")
        sign_button = page.locator('button:has-text("签到")').first
        if await sign_button.is_visible():
            print("   👉 点击签到按钮...")
            await sign_button.click()
            await asyncio.sleep(2)
            await handle_geetest(page, "签到阶段")
            await asyncio.sleep(3)
            print("   🎉 签到完成！")
        else:
            print("   ✅ 已检测到【已签到】标识，不需要重复签到。")

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await context.close()


async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON")
        return

    try:
        accounts = json.loads(ACCOUNTS_JSON)
    except json.JSONDecodeError as e:
        print(f"错误: 无效的 JSON 格式 - {e}")
        return

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
