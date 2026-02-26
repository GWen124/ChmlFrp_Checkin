import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

# 全局变量用于存储接口返回的信息，方便后续判断
API_RESULTS = []

async def handle_response(response):
    """
    异步处理网络响应，修复之前的 RuntimeWarning
    """
    if "qiandao" in response.url and response.status == 200:
        try:
            # 这里的 await 是关键，获取响应体
            json_body = await response.json()
            print(f"\n[API 监听] 接口: {response.url}")
            print(f"[API 响应] 内容: {json.dumps(json_body, ensure_ascii=False)}")
            API_RESULTS.append(json_body)
        except:
            # 有些响应可能不是 json，忽略
            pass

async def handle_slider(page):
    """
    处理滑块验证
    """
    print(">>> 正在扫描页面上的滑块元素...")
    
    # 常见的滑块选择器列表，包含 AntDesign, 极验, 阿里等
    selectors = [
        '.ant-slider-handle', 
        '.nc_iconfont', 
        '.drag-btn', 
        '.secsdk-captcha-drag-icon', 
        '.geetest_slider_button',
        '#nc_1_n1z', # 阿里滑块常见ID
        '.slider-handler'
    ]
    
    slider_handle = None
    for selector in selectors:
        try:
            # 缩短超时时间，快速轮询
            if await page.query_selector(selector):
                slider_handle = await page.wait_for_selector(selector, timeout=1000)
                print(f"锁定滑块元素: {selector}")
                break
        except:
            continue
            
    if slider_handle:
        print(">>> 开始执行滑块拖动...")
        box = await slider_handle.bounding_box()
        
        # 尝试寻找轨道以计算距离
        target_x = 260 # 默认距离
        try:
            track = await page.wait_for_selector('.ant-slider, .nc_scale, .drag-track, .geetest_slider_track, #nc_1__scale_text', timeout=1000)
            if track:
                track_box = await track.bounding_box()
                if track_box and box:
                    target_x = track_box['width'] - box['width']
                    print(f"计算出滑块行程: {target_x}")
        except:
            print("未找到轨道，使用默认行程拖动")

        # 模拟鼠标操作
        await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        await page.mouse.down()
        
        # 模拟人类不匀速拖动
        steps = 35
        for i in range(steps):
            move_x = (target_x / steps) * (i + 1)
            jitter = random.randint(-2, 2)
            await page.mouse.move(box['x'] + move_x, box['y'] + jitter + box['height'] / 2)
            # 变加速
            if i < steps / 2:
                await asyncio.sleep(random.uniform(0.02, 0.04))
            else:
                await asyncio.sleep(random.uniform(0.01, 0.02))
        
        # 稍微过冲一点点再拉回来（模拟真人修正）
        await page.mouse.move(box['x'] + target_x + 5, box['y'] + box['height'] / 2)
        await asyncio.sleep(0.1)
        await page.mouse.move(box['x'] + target_x, box['y'] + box['height'] / 2)
        
        await page.mouse.up()
        print(">>> 滑动动作结束")
        await asyncio.sleep(3)
    else:
        print("当前页面未检测到已知样式的滑块。")

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    
    if "你的用户名" in username:
        return

    print(f"\n========== 🟢 开始处理账号: {username} ==========")
    API_RESULTS.clear() # 清空上一轮的结果
    
    page = await context.new_page()
    
    # 注册监听器
    page.on("response", handle_response)

    try:
        # 1. 登录
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/")
        
        await page.wait_for_selector('input[type="text"], input[name="username"]', timeout=20000)
        await page.fill('input[type="text"], input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        
        print("2. 提交登录...")
        # 同时支持回车和点击
        await page.keyboard.press('Enter')
        try:
            btn = await page.wait_for_selector('button[type="submit"]', timeout=3000)
            if btn: await btn.click()
        except:
            pass
            
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(3) # 等待首页完全渲染

        # 截图登录后状态
        await page.screenshot(path=f"step1_login_{username}.png")

        # 3. 寻找并点击签到
        print("3. 寻找签到入口...")
        
        # 这里的策略是：先找按钮，点击，然后看是否有滑块
        # 很多面板的签到按钮可能只是一个图标或者文字
        checkin_targets = [
            page.get_by_text("签到", exact=True),
            page.get_by_text("每日签到"),
            page.locator("button:has-text('签到')"),
            page.locator(".qiandao-btn") # 猜测的类名
        ]
        
        clicked = False
        for target in checkin_targets:
            if await target.count() > 0 and await target.first.is_visible():
                print(f"找到签到按钮，尝试点击...")
                # force=True 强行点击，忽略遮挡
                await target.first.click(force=True)
                clicked = True
                break
        
        if not clicked:
            print("⚠️ 未在首页找到显眼的'签到'按钮，尝试直接访问可能的签到页...")
            # 有些面板签到在 /user/qiandao 或者弹窗里
            # 这里先不乱跳，依靠 artifact 截图来排查
        
        # 4. 无论点击是否成功，都检测一下滑块（也许点击后弹出了）
        await asyncio.sleep(2)
        await handle_slider(page)
        
        # 5. 等待最后的结果
        await asyncio.sleep(3)
        await page.screenshot(path=f"step2_result_{username}.png")
        
        print(f"流程结束。本次捕获的 API 响应数: {len(API_RESULTS)}")
        
    except Exception as e:
        print(f"❌ 账号 {username} 执行出错: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 环境变量 ACCOUNTS_JSON 未设置！")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 设置较大的视窗，模拟桌面环境
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        
        for account in accounts:
            await run_one_account(account, context)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
