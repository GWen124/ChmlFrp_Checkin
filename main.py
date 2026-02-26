import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

# 从环境变量获取账号信息
ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

async def handle_slider(page):
    """
    处理滑块验证的通用逻辑
    """
    try:
        print("正在检测滑块...")
        # 等待滑块元素出现，这里的选择器是基于常见 Ant Design/Element UI 的猜测
        # 如果跑不通，请查看 Artifacts 里的截图，并修改这里的选择器
        try:
            slider_handle = await page.wait_for_selector('.ant-slider-handle, .slider-btn, .drag-btn', timeout=5000)
            slider_track = await page.wait_for_selector('.ant-slider, .slider-track, .drag-track', timeout=5000)
        except:
            print("未检测到滑块元素，跳过滑动步骤。")
            return

        if slider_handle:
            print("发现滑块，开始模拟拖动...")
            box = await slider_handle.bounding_box()
            track_box = await slider_track.bounding_box()
            
            # 计算拖动距离 (轨道宽度 - 滑块宽度)
            if track_box and box:
                target_x = track_box['width'] - box['width']
            else:
                target_x = 200 # 兜底距离

            # 模拟鼠标操作
            await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            await page.mouse.down()
            
            # 模拟人类不匀速拖动
            steps = 25
            for i in range(steps):
                # 缓动算法
                move_x = (target_x / steps) * (i + 1)
                jitter = random.randint(-2, 2)
                await page.mouse.move(box['x'] + move_x, box['y'] + jitter + box['height'] / 2)
                await asyncio.sleep(random.uniform(0.01, 0.05))
            
            await page.mouse.up()
            print("滑块拖动完成")
            await asyncio.sleep(3) # 等待验证结果
            
    except Exception as e:
        print(f"滑动过程出错: {e}")

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    print(f"--- 开始处理账号: {username} ---")
    
    page = await context.new_page()
    try:
        # 1. 访问登录页
        print("访问登录页...")
        await page.goto("https://panel.chmlfrp.net/")
        
        # 2. 登录流程
        # 这里的选择器 input[type="text"] 是通用的，如果网页特殊需要修改
        await page.wait_for_selector('input[type="text"], input[name="username"]', timeout=15000)
        
        await page.fill('input[type="text"], input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        
        print("点击登录...")
        # 尝试点击登录按钮，通常是 submit 类型或有 login 类名
        await page.click('button[type="submit"], .login-btn, button:has-text("登录")') 
        
        # 等待登录成功 (通过 URL 变化或特定元素判断)
        await page.wait_for_load_state('networkidle')
        
        # 截图一张看看登录状态
        await page.screenshot(path=f"login_status_{username}.png")

        # 3. 寻找签到入口
        print("查找签到按钮...")
        try:
            # 模糊匹配“签到”文字
            checkin_btn = page.get_by_text("签到", exact=False).first
            if await checkin_btn.is_visible():
                print("点击签到按钮...")
                await checkin_btn.click()
                await asyncio.sleep(2)
            else:
                print("未在首页找到明显签到按钮，尝试访问 /qiandao 接口对应的页面或弹窗...")
                # 如果你知道具体的签到 URL，可以在这里 await page.goto("...")
        except Exception as e:
            print(f"寻找签到按钮时出错: {e}")

        # 4. 处理可能出现的滑块
        await handle_slider(page)
        
        # 截图保存最终结果
        await page.screenshot(path=f"result_{username}.png")
        print(f"账号 {username} 流程结束")
        
    except Exception as e:
        print(f"账号 {username} 执行严重错误: {e}")
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 环境变量 ACCOUNTS_JSON 未设置！")
        return

    try:
        accounts = json.loads(ACCOUNTS_JSON)
    except json.JSONDecodeError:
        print("错误: ACCOUNTS_JSON 格式不正确，必须是 JSON 字符串")
        return
    
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        
        for account in accounts:
            await run_one_account(account, context)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
