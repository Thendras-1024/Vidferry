"""各平台扫码登录与 Cookie 获取(抖音/视频号/快手/小红书)。"""


import asyncio
import base64
import sqlite3

from playwright.async_api import async_playwright

from myUtils.auth import check_cookie
from utils.base_social_media import set_init_script
import uuid
from pathlib import Path
from conf import BASE_DIR, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH

# 统一获取浏览器启动配置（防风控+引入本地浏览器）
def get_browser_options():
    options = {
        'headless': LOCAL_CHROME_HEADLESS,
        'args': [
            '--disable-blink-features=AutomationControlled',  # 核心防爬屏蔽：去掉 window.navigator.webdriver 标签
            '--lang=zh-CN',
            '--disable-infobars',
            '--start-maximized'
        ]
    }
    # 如果用户在 conf.py 里配置了本地 Chrome，就用本地的，这样成功率极高
    if LOCAL_CHROME_PATH:
        options['executable_path'] = LOCAL_CHROME_PATH

    return options


async def safe_goto(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        # 部分创作者站点在跳转到登录壳时会中断首次导航。若文档仍已加载,
        # 则继续执行,交由下面的选择器等待来判断页面是否可用。
        if page.url == "about:blank":
            raise e


async def send_qr_from_locator(locator, status_queue):
    await locator.wait_for(state="visible", timeout=30000)
    try:
        src = await locator.get_attribute("src")
        if src and src.startswith("data:image"):
            status_queue.put(src)
            return src
    except Exception:
        pass

    image_bytes = await locator.screenshot(type="png")
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    status_queue.put(data_url)
    return data_url

def save_login_account(platform_type, cookie_file, user_name, status_queue, account_id=None):
    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        old_cookie_file = None

        if account_id is not None:
            cursor.execute("SELECT type, filePath FROM user_info WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if row is None:
                status_queue.put("500")
                print(f"❌ 未找到需要重新连接的账号: {account_id}")
                return False
            if int(row[0]) != int(platform_type):
                status_queue.put("500")
                print(f"❌ 重新连接账号平台不匹配: account_id={account_id}, expect={row[0]}, actual={platform_type}")
                return False
            old_cookie_file = row[1]

            cursor.execute(
                '''
                UPDATE user_info
                SET type = ?, filePath = ?, userName = ?, status = ?
                WHERE id = ?
                ''',
                (platform_type, cookie_file, user_name, 1, account_id)
            )
        else:
            cursor.execute(
                '''
                INSERT INTO user_info (type, filePath, userName, status)
                VALUES (?, ?, ?, ?)
                ''',
                (platform_type, cookie_file, user_name, 1)
            )

        conn.commit()
        print("✅ 用户状态已记录")

        if old_cookie_file and old_cookie_file != cookie_file:
            old_path = Path(BASE_DIR / "cookiesFile" / old_cookie_file)
            try:
                if old_path.exists():
                    old_path.unlink()
                    print(f"✅ 旧 Cookie 文件已删除: {old_path}")
            except Exception as e:
                print(f"⚠️ 删除旧 Cookie 文件失败: {e}")

        return True


# 抖音登录
async def douyin_cookie_gen(id,status_queue,account_id=None):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()
    async with async_playwright() as playwright:
        options = get_browser_options()
        # 必须使用有头模式运行,否则无法扫码。
        browser = await playwright.chromium.launch(**options)
        # 按需创建浏览器上下文。
        context = await browser.new_context()  # 可传入任意上下文选项
        context = await set_init_script(context)
        # 暂停页面,开始手动操作(扫码)。
        page = await context.new_page()
        await safe_goto(page, "https://creator.douyin.com/")
        original_url = page.url
        img_locator = page.get_by_role("img", name="二维码")
        src = await send_qr_from_locator(img_locator, status_queue)
        print("✅ 图片地址:", src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)
        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            status_queue.put("500")
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(3, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()
        if save_login_account(3, f"{uuid_v1}.json", id, status_queue, account_id):
            status_queue.put("200")


# 视频号登录
async def get_tencent_cookie(id,status_queue,account_id=None):
    from uploader.tencent_uploader.main import tencent_setup

    uuid_v1 = uuid.uuid1()
    cookie_file = f"tencent_{uuid_v1}.json"
    cookies_dir = Path(BASE_DIR / "cookiesFile")
    cookies_dir.mkdir(exist_ok=True)
    account_file = cookies_dir / cookie_file

    def on_qrcode(payload):
        image_data_url = (payload or {}).get("image_data_url")
        if image_data_url:
            status_queue.put(image_data_url)

    result = await tencent_setup(
        str(account_file),
        handle=True,
        return_detail=True,
        qrcode_callback=on_qrcode,
        headless=False,
    )
    if not result.get("success"):
        status_queue.put(f"ERROR::{result.get('message') or '视频号登录失败'}")
        status_queue.put("500")
        return None

    if save_login_account(2, cookie_file, id, status_queue, account_id):
        status_queue.put("200")

# 快手登录
async def get_ks_cookie(id,status_queue,account_id=None):
    url_changed_event = asyncio.Event()
    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()
    async with async_playwright() as playwright:
        options = get_browser_options()
        # 必须使用有头模式运行,否则无法扫码。
        browser = await playwright.chromium.launch(**options)
        # 按需创建浏览器上下文。
        context = await browser.new_context()  # 可传入任意上下文选项
        context = await set_init_script(context)
        # 暂停页面,开始手动操作(扫码)。
        page = await context.new_page()
        await safe_goto(page, "https://cp.kuaishou.com")

        # 定位并点击“立即登录”按钮（类型为 link）
        await page.get_by_role("link", name="立即登录").click()
        await page.get_by_text("扫码登录").click()
        img_locator = page.get_by_role("img", name="qrcode")
        src = await send_qr_from_locator(img_locator, status_queue)
        original_url = page.url
        print("✅ 图片地址:", src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(4, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        if save_login_account(4, f"{uuid_v1}.json", id, status_queue, account_id):
            status_queue.put("200")

# 小红书登录
async def xiaohongshu_cookie_gen(id,status_queue,account_id=None):
    url_changed_event = asyncio.Event()

    async def on_url_change():
        # 检查是否是主框架的变化
        if page.url != original_url:
            url_changed_event.set()

    async with async_playwright() as playwright:
        options = get_browser_options()
        # 必须使用有头模式运行,否则无法扫码。
        browser = await playwright.chromium.launch(**options)
        # 按需创建浏览器上下文。
        context = await browser.new_context()  # 可传入任意上下文选项
        context = await set_init_script(context)
        # 暂停页面,开始手动操作(扫码)。
        page = await context.new_page()
        await safe_goto(page, "https://creator.xiaohongshu.com/")
        await page.locator('img.css-wemwzq').click()

        img_locator = page.get_by_role("img").nth(2)
        src = await send_qr_from_locator(img_locator, status_queue)
        original_url = page.url
        print("✅ 图片地址:", src)
        # 监听页面的 'framenavigated' 事件，只关注主框架的变化
        page.on('framenavigated',
                lambda frame: asyncio.create_task(on_url_change()) if frame == page.main_frame else None)

        try:
            # 等待 URL 变化或超时
            await asyncio.wait_for(url_changed_event.wait(), timeout=200)  # 最多等待 200 秒
            print("监听页面跳转成功")
        except asyncio.TimeoutError:
            status_queue.put("500")
            print("监听页面跳转超时")
            await page.close()
            await context.close()
            await browser.close()
            return None
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        # 确保cookiesFile目录存在
        cookies_dir = Path(BASE_DIR / "cookiesFile")
        cookies_dir.mkdir(exist_ok=True)
        await context.storage_state(path=cookies_dir / f"{uuid_v1}.json")
        result = await check_cookie(1, f"{uuid_v1}.json")
        if not result:
            status_queue.put("500")
            await page.close()
            await context.close()
            await browser.close()
            return None
        await page.close()
        await context.close()
        await browser.close()

        if save_login_account(1, f"{uuid_v1}.json", id, status_queue, account_id):
            status_queue.put("200")

# a = asyncio.run(xiaohongshu_cookie_gen(4,None))
# print(a)
