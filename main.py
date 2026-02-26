import os
import json
import asyncio
import random
import cv2
import numpy as np
from playwright.async_api import async_playwright

# 获取环境变量
ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    """账号脱敏"""
    if not username: return "未知账号"
    if len(username) <= 3: return username[0] + "***"
    return username[:3] + "***"

# === OpenCV 图像识别算法 ===
def identify_gap(bg_image_path):
    """
    识别滑块拼图的缺口位置
    """
    print("   🔍 正在进行图像分析...")
    try:
        # 读取图片
        image = cv2.imread(bg_image_path)
        if image is None:
            print("   ⚠️ 无法读取验证码图片")
            return 0
            
        # 1. 高斯模糊，去噪
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        
        # 2. Canny 边缘检测
        canny = cv2.Canny(blurred, 200, 400)
        
        # 3. 寻找轮廓
        contours, hierarchy = cv2.findContours(canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        target_x = 0
        
        # 4. 遍历轮廓，筛选出缺口
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            
            # 缺口特征：通常接近正方形，边长在一定范围内 (极验缺口约 40-50px)
            if 35 < w < 85 and 35 < h < 85:
                # 过滤掉左侧的起始滑块位置 (通常 x < 50)
                if x < 50:
                    continue
                
                target_x = x
                break # 找到第一个符合条件的即可
        
        if target_x == 0:
            print("   ⚠️ 未识别到明显缺口，使用默认距离")
            return 210 # 兜底距离
            
        print(f"   🎯 识别成功！缺口位置 X = {target_x}")
        return target_x

    except Exception as e:
        print(f"   ⚠️ 图像识别出错: {e}")
        return 210

# === 仿真鼠标轨迹 ===
def get_track(distance):
    """生成符合人类行为的拖动轨迹"""
    track = []
    current = 0
    mid = distance * 4 / 5
    t = 0.2
    v = 0
    
    while current < distance:
        if current < mid:
            a = 2
        else:
            a = -3
        v0 = v
        v = v0 + a * t
        move = v0 * t + 1 / 2 * a * t * t
        current += move
        track.append(round(move))
    return track

async def mouse_slide(page, box, target_x):
    """执行拖动操作"""
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    
    # 获取轨迹
    tracks = get_track(target_x)
    
    for track in tracks:
        x = start_x + track
        y = start_y + random.uniform(-2, 2) # Y轴微抖动
        await page.mouse.move(x, y)
        # 随机变速
        await asyncio.sleep(random.uniform(0.01, 0.02))
        
    # 最后微调：模拟人手过冲后回退
    await page.mouse.move(start_x + target_x + 3, start_y, steps=5)
    await asyncio.sleep(0.1)
    await page.mouse.move(start_x + target_x, start_y, steps=5)
    
    await page.mouse.up()
    print(f"   └── 🖱️ 拖动动作完成")

async def handle_geetest(page):
    """处理极验验证码"""
    print(">>> [验证] 扫描验证码...")
    try:
        # 1. 尝试点击验证按钮 (Radar)
        radar = page.locator('.geetest_radar_tip, .geetest_radar_btn')
        if await radar.count() > 0 and await radar.first.is_visible():
            print("   └── 发现点击按钮，点击...")
            await radar.first.click()
            await asyncio.sleep(3)

        # 2. 扫描滑块
        slider = await page.wait_for_selector(
            '.geetest_slider_button, .geetest_btn, .ant-slider-handle', 
            timeout=4000
        )
        if slider:
            print("   └── 发现滑块！准备识别缺口...")
            
            # 寻找背景图容器进行截图
            # 尝试定位包含完整背景图的元素
            captcha_box = page.locator('.geetest_window, .geetest_box_wrap, .geetest_widget').first
            
            if await captcha_box.count() > 0 and await captcha_box.is_visible():
                # 截图保存
                await captcha_box.screenshot(path="captcha_bg.png")
                
                # 计算距离
                gap_x = identify_gap("captcha_bg.png")
                
                # 修正距离：缺口位置 - 滑块起始位置 + 修正值
                # 极验滑块本身约 40px 宽，通常需要减去一点偏移
                final_distance = gap_x - 5
                
                box = await slider.bounding_box()
                if box:
                    await mouse_slide(page, box, final_distance)
                    await asyncio.sleep(3)
            else:
                print("   ⚠️ 无法截取验证码背景，跳过滑动")
    except Exception as e:
        # 没滑块是好事，或者已经自动过了
        pass

async def check_success(page):
    """检查是否成功，返回 (Success: bool, Message: str)"""
    try:
        # 1. 检查页面上是否有“已签到”文字
        if await page.get_by_text("已签到").count() > 0:
            return True, "页面已显示【已签到】"
            
        # 2. 点击“签到信息”查看弹窗
        info_btn = page.get_by_text("签到信息").first
        if await info_btn.is_visible():
            # 强制点击，因为可能有透明遮挡层
            await info_btn.click(force=True)
            await asyncio.sleep(1)
            
            popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
            if await popover.count() > 0:
                text = await popover.first.inner_text()
                # 简单判断：只要能读出积分，就算广义上的“流程成功”
                return True, f"账户信息读取成功:\n{text.strip()}"
                
        return False, "未找到状态信息"
    except Exception as e:
        return False, str(e)

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    # 示例账号跳过
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    
    # 独立的上下文，防止串号
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    
    # 屏蔽自动化特征
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        # 1. 登录
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/", timeout=45000)
        
        # 登录流程 (如果在首页则跳过)
        if "/home" not in page.url:
            try:
                await page.wait_for_selector('input[type="text"]', timeout=15000)
                await page.fill('input[type="text"]', username)
                await page.fill('input[type="password"]', password)
                # 点击登录
                await page.locator('button[type="submit"]').first.click()
                await page.wait_for_load_state('networkidle')
            except:
                pass # 可能已经登录

        # 2. 确保进入首页
        if "/home" not in page.url:
            await page.goto("https://panel.chmlfrp.net/home")
            await asyncio.sleep(3)

        # 3. 签到逻辑
        print("3. 检测签到状态...")
        
        # 优先判断是否已签到
        signed_text = page.get_by_text("已签到")
        if await signed_text.count() > 0:
            print("   ✅ [检测] 今日已签到，无需操作。")
        else:
            # 寻找签到按钮
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到")
            
            if await checkin_btn.count() > 0:
                print("   └── 点击签到按钮...")
                await checkin_btn.first.click(force=True)
                await asyncio.sleep(2)
                
                # 调用 OpenCV 处理验证码
                await handle_geetest(page)
                
                # 等待一会儿
                await asyncio.sleep(3)
                
                # 尝试清除残留遮挡层 (暴力移除法)
                await page.evaluate("document.querySelectorAll('.geetest_popup_ghost, .geetest_wrap').forEach(e => e.remove())")
            else:
                print("   ⚠️ 未找到明显签到按钮")

        # 4. 验证结果并截图
        success, msg = await check_success(page)
        print("-" * 30)
        print(msg)
        print("-" * 30)
        
        # 根据结果保存不同文件名的截图
        if success:
            print(f"🎉 账号 {masked_name} 流程结束")
            await page.screenshot(path=f"success_{username}.png")
        else:
            print(f"❌ 账号 {masked_name} 似乎未成功")
            await page.screenshot(path=f"failed_{username}.png")

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
