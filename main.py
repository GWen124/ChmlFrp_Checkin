import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

def mask_username(username):
    """
    账号脱敏处理：保留前3位，其余隐藏
    例如: weizong -> wei***
    """
    if not username:
        return "未知账号"
    if len(username) <= 3:
        return username[0] + "***"
    return username[:3] + "***"

async def handle_slider(page):
    """
    通用滑块处理逻辑
    """
    print(">>> [滑块检测] 正在扫描页面是否有滑块...")
    try:
        # 定义常见的滑块把手选择器
        slider_handle = await page.wait_for_selector(
            '.ant-slider-handle, .nc_iconfont, .drag-btn, .secsdk-captcha-drag-icon, .geetest_slider_button', 
            timeout=3000
        )
    except:
        print(">>> [滑块检测] 未检测到滑块，假设无需验证或验证已通过。")
        return

    if slider_handle:
        print(">>> [滑块操作] 发现滑块！开始拖动...")
        try:
            box = await slider_handle.bounding_box()
            track_width = 260 # 默认轨道宽度
            try:
                # 尝试查找轨道元素计算实际宽度
                track = await page.query_selector('.ant-slider, .nc_scale, .drag-track, .geetest_slider_track')
                if track:
                    track_box = await track.bounding_box()
                    track_width = track_box['width'] - box['width']
            except:
                pass

            # === 模拟鼠标轨迹 ===
            start_x = box['x'] + box['width'] / 2
            start_y = box['y'] + box['height'] / 2
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            
            # 模拟人类变速拖动
            steps = 25
            for i in range(steps):
                progress = (i + 1) / steps
                # 缓动：先快后慢
                progress = 1 - (1 - progress) * (1 - progress)
                move_x = track_width * progress
                jitter = random.randint(-2, 2)
                await page.mouse.move(start_x + move_x, start_y + jitter)
                await asyncio.sleep(random.uniform(0.02, 0.05))
            
            await page.mouse.up()
            print(">>> [滑块操作] 拖动完成，等待验证结果...")
            await asyncio.sleep(2)
        except Exception as e:
            print(f">>> [滑块错误] 拖动过程出错: {e}")

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    masked_name = mask_username(username) # 生成脱敏后的名字用于日志显示
    
    # 跳过示例账号
    if "你的用户名" in username:
        return

    print(f"\n========== 🟢 开始处理账号: {masked_name} ==========")
    page = await context.new_page()
    
    # 开启 API 监听
    page.on("response", lambda response: print_response(response))

    try:
        # 1. 登录
        print("1. 访问登录页...")
        await page.goto("https://panel.chmlfrp.net/")
        
        await page.wait_for_selector('input[type="text"], input[name="username"]', timeout=15000)
        await page.fill('input[type="text"], input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        
        print("2. 提交登录...")
        await page.keyboard.press('Enter')
        
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        # 3. 强制跳转到签到页
        target_url = "https://panel.chmlfrp.net/home"
        print(f"3. 强制跳转到面板首页: {target_url}")
        await page.goto(target_url)
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(3)

        # 截图文件名保留完整用户名，方便你在 Artifacts 中区分
        # 如果连文件名也想隐藏，可以改成 masked_name
        await page.screenshot(path=f"home_page_{username}.png")

        # 4. 寻找签到按钮
        print("4. 扫描签到按钮...")
        checkin_keywords = ["每日签到", "签到", "Sign in", "Check in"]
        found_btn = None
        
        for keyword in checkin_keywords:
            locator = page.get_by_text(keyword)
            if await locator.count() > 0:
                for i in range(await locator.count()):
                    btn = locator.nth(i)
                    if await btn.is_visible():
                        found_btn = btn
                        print(f">>> 找到按钮，文本为: {keyword}")
                        break
            if found_btn: break
        
        if found_btn:
            print(">>> 点击签到按钮...")
            await found_btn.click(force=True)
            await asyncio.sleep(2)
            
            # 5. 处理滑块
            await handle_slider(page)
            
            await asyncio.sleep(3)
            await page.screenshot(path=f"result_{username}.png")
            print(f">>> 账号 {masked_name} 操作结束，请检查 Result 截图确认结果。")
            
        else:
            print(f"⚠️ 警告: 账号 {masked_name} 未在首页找到包含'签到'字样的按钮。")
            # 检查是否已签到
            if await page.get_by_text("已签到").count() > 0:
                print(">>> 检测到 '已签到' 状态，跳过。")
            else:
                print(">>> 无法判断状态，请查看截图。")

    except Exception as e:
        print(f"❌ 账号 {masked_name} 执行出错: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

def print_response(response):
    try:
        # 简单过滤，防止日志刷屏
        if "qiandao" in response.url and response.status == 200:
            print(f"✅ [API 捕获] 成功触发接口: {response.url}")
    except:
        pass

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 环境变量 ACCOUNTS_JSON 未设置")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # 1920x1080 确保页面元素展开
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        
        for account in accounts:
            await run_one_account(account, context)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
