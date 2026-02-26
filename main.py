import os
import json
import asyncio
import random
import math
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    if not username: return "未知账号"
    if len(username) <= 3: return username[0] + "***"
    return username[:3] + "***"

# 缓动函数：模拟人手先快后慢
def ease_out_quad(x):
    return 1 - (1 - x) * (1 - x)

async def mouse_slide(page, box):
    """
    【核心升级】仿真鼠标拖动轨迹
    """
    # 起点：滑块中心
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2
    
    # 移动到起点
    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    
    # 目标距离：通常是 220-260px 之间，加随机数
    distance = 255 + random.randint(-5, 10)
    
    # 轨迹生成的份数
    steps = 45
    
    for i in range(steps):
        # 进度 0 -> 1
        t = (i + 1) / steps
        # 应用缓动函数
        progress = ease_out_quad(t)
        
        # 当前 X 坐标
        current_x = start_x + (distance * progress)
        
        # Y 坐标加入随机抖动 (模拟手抖)
        jitter_y = random.uniform(-2, 2)
        current_y = start_y + jitter_y
        
        # 只有最后几步才慢下来
        if i > steps - 10:
             await asyncio.sleep(random.uniform(0.03, 0.05))
        else:
             await asyncio.sleep(random.uniform(0.005, 0.01))
             
        await page.mouse.move(current_x, current_y)

    # 稍微过冲一点点，再回退（模拟真人修正）
    await page.mouse.move(current_x + 3, start_y, steps=5)
    await asyncio.sleep(0.1)
    await page.mouse.move(current_x, start_y, steps=5)
    
    # 松开鼠标
    await page.mouse.up()
    print(f"   └── 🖱️ 模拟拖动完成，距离: {distance}px")

async def log_api_response(response):
    """监听具体的签到动作结果"""
    # 监听 POST 请求 /qiandao，这才是真正的签到动作
    if "/qiandao" in response.url and response.request.method == "POST":
        try:
            data = await response.json()
            print(f"\n🔔 [签到结果] 服务器回复: {json.dumps(data, ensure_ascii=False)}")
        except:
            pass
            
    # 监听用户信息
    if "qiandao_info" in response.url:
        try:
            data = await response.json()
            # print(f"   [状态查询] {json.dumps(data, ensure_ascii=False)}")
        except:
            pass

async def handle_geetest(page):
    """处理极验"""
    print(">>> [验证] 正在扫描验证码...")
    try:
        # 1. 优先处理“点击验证”按钮
        radar = page.locator('.geetest_radar_tip, .geetest_radar_btn')
        if await radar.count() > 0 and await radar.first.is_visible():
            print("   └── 发现点击验证按钮，点击...")
            await radar.first.click()
            await asyncio.sleep(2)

        # 2. 处理滑块
        # 等待滑块出现
        slider = await page.wait_for_selector(
            '.geetest_slider_button, .geetest_btn, .ant-slider-handle, .nc_iconfont', 
            timeout=5000
        )
        if slider:
            print("   └── 发现滑块，开始仿真拖动...")
            box = await slider.bounding_box()
            if box:
                await mouse_slide(page, box)
                # 拖完等待验证结果
                await asyncio.sleep(4)
    except Exception as e:
        # 没滑块是好事
        pass

async def safe_click_info(page):
    """安全读取积分"""
    print(">>> 读取最终积分...")
    try:
        # 【修复点】使用 .first 避免报错
        ghost = page.locator('.geetest_popup_ghost, .geetest_wrap')
        if await ghost.count() > 0 and await ghost.first.is_visible():
             print("   ⚠️ 警告：验证码遮挡层未消失，可能验证失败。")
        
        info_btn = page.get_by_text("签到信息").first
        if await info_btn.is_visible():
            await info_btn.click(force=True) # 强制点击
            await asyncio.sleep(1)
            
            popover = page.locator(".ant-popover-inner-content, .ant-tooltip-inner, div[role='tooltip']")
            if await popover.count() > 0:
                text = await popover.first.inner_text()
                print("-" * 30)
                print(f"📊 积分统计:\n{text.strip()}")
                print("-" * 30)
    except:
        pass

async def run_one_account(account, browser):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username)
    
    if "你的用户名" in username: return

    print(f"\n========== 🟢 正在执行: {masked_name} ==========")
    
    # 独立的上下文
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        locale='zh-CN',
        timezone_id='Asia/Shanghai'
    )
    
    page = await context.new_page()
    # 屏蔽 webdriver 特征
    await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page.on("response", log_api_response)

    try:
        # 1. 登录
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/", timeout=60000)
        
        # 登录逻辑
        if "/home" not in page.url:
            try:
                await page.wait_for_selector('input[type="text"]', timeout=15000)
                await page.fill('input[type="text"]', username)
                await page.fill('input[type="password"]', password)
                
                login_btn = page.locator('button:has-text("登录"), button[type="submit"]')
                if await login_btn.count() > 0:
                    await login_btn.first.click()
                else:
                    await page.keyboard.press('Enter')
                
                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(3)
            except:
                print("   ⚠️ 登录页面加载超时或已登录")

        # 2. 确认首页
        if "/home" not in page.url:
            await page.goto("https://panel.chmlfrp.net/home")
            await asyncio.sleep(3)

        # 3. 签到
        print("3. 操作签到...")
        
        # 检查是否已签到
        # 注意：这里增加 .first 以防匹配到多个
        if await page.get_by_text("已签到").count() > 0:
             print("   ✅ 页面显示【已签到】，跳过。")
        else:
            # 寻找签到按钮
            checkin_btn = page.locator('button').filter(has_text="签到").filter(has_not_text="已签到")
            
            if await checkin_btn.count() > 0:
                print("   └── 点击【签到】按钮...")
                # 监听弹窗事件
                page.once("dialog", lambda d: print(f"🔔 [弹窗] {d.message}"))
                
                await checkin_btn.first.click(force=True)
                await asyncio.sleep(2)
                
                # 处理验证
                await handle_geetest(page)
                
                # 等待结果弹窗
                await asyncio.sleep(2)
                
                # 检查页面上的提示 Toast
                toast = page.locator('.swal2-title, .ant-message-notice-content')
                if await toast.count() > 0:
                    print(f"🔔 [页面提示] {await toast.first.inner_text()}")
            else:
                print("   ⚠️ 未找到可点击的签到按钮。")

        # 4. 获取积分
        await safe_click_info(page)
        
        await page.screenshot(path=f"result_{username}.png")

    except Exception as e:
        print(f"❌ 运行出错: {e}")
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
