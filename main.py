import os
import json
import asyncio
import random
from playwright.async_api import async_playwright

# 从环境变量获取账号信息，格式为 JSON 字符串: [{"u": "账号1", "p": "密码1"}, ...]
ACCOUNTS_JSON = os.environ.get('ACCOUNTS_JSON')

async def handle_slider(page):
    """
    处理滑块验证的通用逻辑
    注意：你需要根据实际网页修改滑块的选择器
    """
    try:
        print("正在检测滑块...")
        # 等待滑块元素出现，这里的选择器 '.slider-btn' 需要你按F12查看实际的类名或ID
        # 常见类名: .nc_iconfont, .drag-btn, .slide-handler
        slider_handle = await page.wait_for_selector('.ant-slider-handle', timeout=5000) # 示例选择器
        slider_track = await page.wait_for_selector('.ant-slider', timeout=5000)   # 示例选择器
        
        if slider_handle:
            print("发现滑块，开始模拟拖动...")
            box = await slider_handle.bounding_box()
            track_box = await slider_track.bounding_box()
            
            # 计算拖动距离 (通常是轨道宽度 - 滑块宽度)
            target_x = track_box['width'] 
            
            # 模拟鼠标操作
            await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            await page.mouse.down()
            
            # 模拟人类不匀速拖动
            steps = 20
            for i in range(steps):
                # 缓动算法，先快后慢
                move_x = (target_x / steps) * (i + 1)
                # 加一点随机抖动
                jitter = random.randint(-2, 2)
                await page.mouse.move(box['x'] + move_x, box['y'] + jitter + box['height'] / 2)
                await asyncio.sleep(random.uniform(0.01, 0.05))
            
            await page.mouse.up()
            print("滑块拖动完成")
            await asyncio.sleep(2) # 等待验证结果
    except Exception as e:
        print(f"未检测到滑块或无需滑动: {e}")

async def run_one_account(account, context):
    username = account['u']
    password = account['p']
    print(f"--- 开始处理账号: {username} ---")
    
    page = await context.new_page()
    try:
        # 1. 访问登录页
        await page.goto("https://panel.chmlfrp.net/")
        
        # 2. 登录流程 (选择器需要根据实际网页调整)
        # 假设输入框是 input[type="text"] 或 id="username"
        print("正在登录...")
        # 这里的 wait_for_selector 是为了确保页面加载完成
        await page.wait_for_selector('input[type="text"], input[name="username"]', timeout=10000)
        
        # 填写账号密码
        await page.fill('input[type="text"], input[name="username"]', username)
        await page.fill('input[type="password"]', password)
        
        # 点击登录按钮
        await page.click('button[type="submit"], .login-button') 
        
        # 等待登录成功跳转 (比如等待 URL 变化或出现了用户头像)
        await page.wait_for_load_state('networkidle')
        
        # 3. 寻找签到入口
        print("查找签到按钮...")
        # 尝试通过文字内容查找按钮，这比 class 更通用
        try:
            # 有些签到可能在模态框里，或者直接在首页
            # 如果是请求抓包里的 "/qiandao"，通常界面上会有 "签到" 两个字
            checkin_btn = page.get_by_text("签到", exact=False).first
            if await checkin_btn.is_visible():
                await checkin_btn.click()
            else:
                print("未在首页找到明显签到按钮，尝试直接访问可能的签到页面...")
                # 如果有专门签到页，可以在这里 goto
        except:
            pass

        # 4. 处理可能出现的滑块
        # 如果点击签到后弹出了滑块
        await handle_slider(page)
        
        # 5. 再次确认签到 (有时候滑块滑完需要再点一下确定)
        # await page.click('text="确认"') 
        
        print(f"账号 {username} 操作流程结束 (请检查截图确认结果)")
        
    except Exception as e:
        print(f"账号 {username} 执行出错: {e}")
        # 截图保存以便在 GitHub Actions Artifacts 中查看错误
        await page.screenshot(path=f"error_{username}.png")
    finally:
        await page.close()

async def main():
    if not ACCOUNTS_JSON:
        print("错误: 未设置 ACCOUNTS_JSON 环境变量")
        return

    accounts = json.loads(ACCOUNTS_JSON)
    
    async with async_playwright() as p:
        # 启动浏览器 (headless=True 表示无头模式，GitHub 上必须为 True)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        for account in accounts:
            await run_one_account(account, context)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
