# -*- coding: utf-8 -*-
from datetime import datetime

import asyncio
import inspect
import os
import time
from pathlib import Path

from patchright.async_api import Page
from patchright.async_api import Playwright
from patchright.async_api import async_playwright

from conf import DEBUG_MODE, LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.base_video import BaseVideoUploader
from utils.base_social_media import set_init_script
from utils.login_qrcode import build_login_qrcode_path
from utils.login_qrcode import decode_qrcode_from_path
from utils.login_qrcode import print_terminal_qrcode
from utils.login_qrcode import remove_qrcode_file
from utils.login_qrcode import save_data_url_image
from utils.log import douyin_logger

DOUYIN_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
DOUYIN_PUBLISH_STRATEGY_SCHEDULED = "scheduled"
DOUYIN_UPLOAD_RETRY_LIMIT = int(os.environ.get("DOUYIN_UPLOAD_RETRY_LIMIT", "1") or 1)
DOUYIN_UPLOAD_WAIT_TIMEOUT = int(os.environ.get("DOUYIN_UPLOAD_WAIT_TIMEOUT", "1800") or 1800)
DOUYIN_ENTER_PUBLISH_PAGE_TIMEOUT = int(os.environ.get("DOUYIN_ENTER_PUBLISH_PAGE_TIMEOUT", "120") or 120)
DOUYIN_GOTO_TIMEOUT_MS = int(os.environ.get("DOUYIN_GOTO_TIMEOUT_MS", "90000") or 90000)
DOUYIN_PUBLISH_CONFIRM_TIMEOUT = int(os.environ.get("DOUYIN_PUBLISH_CONFIRM_TIMEOUT", "180") or 180)
DOUYIN_UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


async def launch_douyin_browser(playwright: Playwright, headless: bool):
    if LOCAL_CHROME_PATH:
        return await playwright.chromium.launch(headless=headless, executable_path=LOCAL_CHROME_PATH)
    return await playwright.chromium.launch(headless=headless, channel="chrome")


async def safe_goto_douyin(page: Page, url: str, retries: int = 2) -> None:
    last_error = None
    for attempt in range(retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=DOUYIN_GOTO_TIMEOUT_MS)
            return
        except Exception as exc:
            last_error = exc
            douyin_logger.warning(_msg("😵", f"打开抖音页面超时/失败，准备重试 {attempt + 1}/{retries + 1}: {exc}"))
            await asyncio.sleep(2)
    raise RuntimeError(f"打开抖音页面失败: {last_error}")


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return

    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_login_result(success: bool, status: str, message: str, account_file: str, qrcode: dict | None = None, current_url: str = "") -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": qrcode,
        "current_url": current_url,
    }


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await launch_douyin_browser(playwright, headless=True)
        try:
            context = await browser.new_context(storage_state=account_file)
            context = await set_init_script(context)
            page = await context.new_page()
            await safe_goto_douyin(page, DOUYIN_UPLOAD_URL)
            try:
                await page.wait_for_url(DOUYIN_UPLOAD_URL, timeout=5000)
            except Exception:
                return False

            if await page.get_by_text("手机号登录").count() or await page.get_by_text("扫码登录").count():
                return False

            return True
        finally:
            await browser.close()


async def douyin_setup(account_file, handle=False, return_detail=False, qrcode_callback=None, headless: bool = LOCAL_CHROME_HEADLESS):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        douyin_logger.info(_msg("🥹", "cookie 失效了，准备打开浏览器重新登录"))
        result = await douyin_cookie_gen(account_file, qrcode_callback=qrcode_callback, headless=headless)
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def _extract_douyin_qrcode_src(page: Page) -> str:
    scan_login_tab = page.get_by_text("扫码登录", exact=True).first
    await scan_login_tab.wait_for(timeout=30000)

    qrcode_img = (
        scan_login_tab
        .locator("..")
        .locator("xpath=following-sibling::div[1]")
        .locator('img[aria-label="二维码"]')
        .first
    )

    if not await qrcode_img.count():
        qrcode_img = page.get_by_role("img", name="二维码").first

    await qrcode_img.wait_for(state="visible", timeout=30000)
    src = await qrcode_img.get_attribute("src")
    if not src:
        raise RuntimeError("未获取到抖音登录二维码地址")

    return src


async def _save_douyin_qrcode(page: Page, account_file: str, previous_qrcode_path: Path | None = None, qrcode_callback=None) -> dict:
    qrcode_src = await _extract_douyin_qrcode_src(page)
    qrcode_path = save_data_url_image(qrcode_src, build_login_qrcode_path(account_file))
    if previous_qrcode_path and previous_qrcode_path != qrcode_path:
        if remove_qrcode_file(previous_qrcode_path):
            douyin_logger.info(_msg("🧹", f"临时二维码文件已清理: {previous_qrcode_path}"))
    douyin_logger.info(_msg("🖼️", f"二维码已经准备好啦，已保存到: {qrcode_path}"))
    qrcode_content = decode_qrcode_from_path(qrcode_path)
    if qrcode_content:
        print_terminal_qrcode(qrcode_content, qrcode_path, "抖音APP")
    else:
        douyin_logger.warning(_msg("😵", f"终端没法完整显示二维码，请打开 {qrcode_path} 扫码"))
    qrcode_info = {
        "image_path": str(qrcode_path),
        "image_data_url": qrcode_src,
    }
    await _emit_qrcode_callback(qrcode_callback, qrcode_info)
    return qrcode_info


async def _is_douyin_login_completed(page: Page) -> bool:
    if not page.url.startswith("https://creator.douyin.com/creator-micro/home"):
        return False

    login_markers = [
        page.get_by_text("扫码登录", exact=True).first,
        page.get_by_text("手机号登录", exact=True).first,
        page.get_by_text("二维码失效", exact=True).first,
        page.get_by_role("img", name="二维码").first,
    ]

    for marker in login_markers:
        if not await marker.count():
            continue
        try:
            if await marker.is_visible():
                return False
        except Exception:
            continue

    return True


async def _wait_for_douyin_login(page: Page, account_file: str, qrcode_info: dict, qrcode_callback=None, poll_interval: int = 3, max_checks: int = 100) -> dict:
    qrcode_path = Path(qrcode_info["image_path"])
    for _ in range(max_checks):
        if await _is_douyin_login_completed(page):
            douyin_logger.info(_msg("🥳", f"扫码成功，已经跳转到登录后页面: {page.url}"))
            return _build_login_result(True, "success", "抖音扫码登录成功", account_file, qrcode_info, page.url)

        expired_box = page.get_by_text("二维码失效", exact=True).locator("..").first
        if await expired_box.count() and await expired_box.is_visible():
            douyin_logger.warning(_msg("😵", "二维码失效了，小人马上去刷新"))
            await expired_box.click()
            await asyncio.sleep(1)
            qrcode_info = await _save_douyin_qrcode(page, account_file, qrcode_path, qrcode_callback=qrcode_callback)
            qrcode_path = Path(qrcode_info["image_path"])

        await asyncio.sleep(poll_interval)

    return _build_login_result(False, "timeout", "等待抖音扫码登录超时", account_file, qrcode_info, page.url)


async def douyin_cookie_gen(
    account_file,
    qrcode_callback=None,
    poll_interval: int = 3,
    max_checks: int = 100,
    headless: bool = LOCAL_CHROME_HEADLESS,
):
    async with async_playwright() as playwright:
        browser = await launch_douyin_browser(playwright, headless=headless)
        context = await browser.new_context()
        context = await set_init_script(context)
        qrcode_path = None
        result = _build_login_result(False, "failed", "抖音登录失败", account_file)
        try:
            page = await context.new_page()
            await safe_goto_douyin(page, "https://creator.douyin.com/")
            qrcode_info = await _save_douyin_qrcode(page, account_file, qrcode_callback=qrcode_callback)
            qrcode_path = Path(qrcode_info["image_path"])
            douyin_logger.info(_msg("🧍", "请扫码，小人正在耐心等待登录完成"))
            result = await _wait_for_douyin_login(
                page,
                account_file,
                qrcode_info,
                qrcode_callback=qrcode_callback,
                poll_interval=poll_interval,
                max_checks=max_checks,
            )
            if result["success"]:
                await asyncio.sleep(2)
                await context.storage_state(path=account_file)
                if not await cookie_auth(account_file):
                    result = _build_login_result(
                        False,
                        "cookie_invalid",
                        "抖音扫码流程结束，但 cookie 校验失败",
                        account_file,
                        qrcode_info,
                        page.url,
                    )
        except Exception as exc:
            result = _build_login_result(False, "failed", str(exc), account_file, current_url=page.url if "page" in locals() else "")
        finally:
            if remove_qrcode_file(qrcode_path):
                douyin_logger.info(_msg("🧹", f"临时二维码文件已清理: {qrcode_path}"))
            if not result["success"]:
                douyin_logger.error(_msg("😢", f"登录失败: {result['message']}"))
            await context.close()
            await browser.close()
        return result


class DouYinBaseUploader(BaseVideoUploader):
    def __init__(
        self,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        self.publish_date = publish_date
        self.account_file = account_file
        self.publish_strategy = publish_strategy
        self.debug = debug
        self.date_format = "%Y年%m月%d日 %H:%M"
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = headless

    async def validate_base_args(self):
        if not os.path.exists(self.account_file):
            raise RuntimeError(f"cookie文件不存在，请先完成抖音登录: {self.account_file}")
        if not await cookie_auth(self.account_file):
            raise RuntimeError(f"cookie文件已失效，请先完成抖音登录: {self.account_file}")
        if self.publish_strategy not in {DOUYIN_PUBLISH_STRATEGY_IMMEDIATE, DOUYIN_PUBLISH_STRATEGY_SCHEDULED}:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")

        if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED:
            self.publish_date = self.validate_publish_date(self.publish_date)
        else:
            self.publish_date = 0

    async def set_schedule_time_douyin(self, page, publish_date):
        label_element = page.locator("[class^='radio']:has-text('定时发布')")
        await label_element.click()
        await asyncio.sleep(1)
        publish_date_hour = publish_date.strftime("%Y-%m-%d %H:%M")

        await asyncio.sleep(1)
        await page.locator('.semi-input[placeholder="日期和时间"]').click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.type(str(publish_date_hour))
        await page.keyboard.press("Enter")
        await asyncio.sleep(1)

    async def fill_title_and_description(self, page: Page, title: str, description: str, tags: list[str] | None = None):
        description_section = (
            page.get_by_text("作品描述", exact=True)
            .locator("xpath=ancestor::div[2]")
            .locator("xpath=following-sibling::div[1]")
        )

        title_input = description_section.locator('input[type="text"]').first
        await title_input.wait_for(state="visible", timeout=10000)
        await title_input.fill(title[:30])

        description_editor = description_section.locator('.zone-container[contenteditable="true"]').first
        await description_editor.wait_for(state="visible", timeout=10000)
        await description_editor.click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.press("Delete")
        await page.keyboard.type(description)

        for tag in tags or []:
            await page.keyboard.type(" #" + tag)
            await page.keyboard.press("Space")

    async def set_location(self, page: Page, location: str = ""):
        if not location:
            return
        await page.locator('div.semi-select span:has-text("输入地理位置")').click()
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(2000)
        await page.keyboard.type(location)
        await page.wait_for_selector('div[role="listbox"] [role="option"]', timeout=5000)
        await page.locator('div[role="listbox"] [role="option"]').first.click()

    async def handle_product_dialog(self, page: Page, product_title: str):
        await page.wait_for_timeout(2000)
        await page.wait_for_selector('input[placeholder="请输入商品短标题"]', timeout=10000)
        short_title_input = page.locator('input[placeholder="请输入商品短标题"]')
        if not await short_title_input.count():
            douyin_logger.error(_msg("😵", "没找到商品短标题输入框"))
            return False

        product_title = product_title[:10]
        await short_title_input.fill(product_title)
        await page.wait_for_timeout(1000)

        finish_button = page.locator('button:has-text("完成编辑")')
        if "disabled" not in await finish_button.get_attribute("class"):
            await finish_button.click()
            douyin_logger.debug(_msg("🥳", "已点击“完成编辑”按钮"))
            await page.wait_for_selector(".semi-modal-content", state="hidden", timeout=5000)
            return True

        douyin_logger.error(_msg("😵", "“完成编辑”按钮是灰的，小人先把弹窗关掉"))
        cancel_button = page.locator('button:has-text("取消")')
        if await cancel_button.count():
            await cancel_button.click()
        else:
            close_button = page.locator(".semi-modal-close")
            await close_button.click()
        await page.wait_for_selector(".semi-modal-content", state="hidden", timeout=5000)
        return False

    async def set_product_link(self, page: Page, product_link: str, product_title: str):
        await page.wait_for_timeout(2000)
        try:
            await page.wait_for_selector("text=添加标签", timeout=10000)
            dropdown = page.get_by_text("添加标签").locator("..").locator("..").locator("..").locator(".semi-select").first
            if not await dropdown.count():
                douyin_logger.error(_msg("😵", "没找到标签下拉框"))
                return False
            douyin_logger.debug(_msg("🧍", "找到标签下拉框，小人准备选择“购物车”"))
            await dropdown.click()
            await page.wait_for_selector('[role="listbox"]', timeout=5000)
            await page.locator('[role="option"]:has-text("购物车")').click()
            douyin_logger.debug(_msg("🥳", "已经选中“购物车”"))

            await page.wait_for_selector('input[placeholder="粘贴商品链接"]', timeout=5000)
            input_field = page.locator('input[placeholder="粘贴商品链接"]')
            await input_field.fill(product_link)
            douyin_logger.debug(_msg("🔗", f"商品链接已经填好了: {product_link}"))

            add_button = page.locator('span:has-text("添加链接")')
            button_class = await add_button.get_attribute("class") or ""
            if "disable" in button_class:
                douyin_logger.error(_msg("😵", "“添加链接”按钮现在点不了"))
                return False
            await add_button.click()
            douyin_logger.debug(_msg("🥳", "已点击“添加链接”按钮"))

            await page.wait_for_timeout(2000)
            error_modal = page.locator("text=未搜索到对应商品")
            if await error_modal.count():
                confirm_button = page.locator('button:has-text("确定")')
                await confirm_button.click()
                douyin_logger.error(_msg("😢", "这个商品链接无效"))
                return False

            if not await self.handle_product_dialog(page, product_title):
                return False

            douyin_logger.debug(_msg("🥳", "商品链接设置好了"))
            return True
        except Exception as e:
            douyin_logger.error(_msg("😢", f"设置商品链接时出错: {str(e)}"))
            return False


class DouYinVideo(DouYinBaseUploader):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime | int,
        account_file,
        thumbnail_landscape_path=None,
        productLink="",
        productTitle="",
        thumbnail_portrait_path=None,
        desc: str | None = None,
        publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        upload_retry_limit: int | None = None,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
        )
        self.title = title
        self.file_path = file_path
        self.tags = tags
        self.thumbnail_landscape_path = thumbnail_landscape_path
        self.thumbnail_portrait_path = thumbnail_portrait_path
        self.productLink = productLink
        self.productTitle = productTitle
        self.desc = desc or ""
        self.upload_retry_limit = DOUYIN_UPLOAD_RETRY_LIMIT if upload_retry_limit is None else int(upload_retry_limit)

    async def is_upload_ready_to_publish(self, page: Page) -> bool:
        if await page.locator('[class^="long-card"] div:has-text("重新上传")').count():
            return True
        for selector in ("text=上传成功", "text=视频上传成功", "text=上传完成", "text=重新上传"):
            try:
                if await page.locator(selector).count():
                    return True
            except Exception:
                continue
        publish_button = page.get_by_role("button", name="发布", exact=True)
        if await publish_button.count():
            try:
                button_class = await publish_button.first.get_attribute("class") or ""
                disabled_attr = await publish_button.first.get_attribute("disabled")
                return disabled_attr is None and "disabled" not in button_class
            except Exception:
                return False
        return False

    async def is_upload_paused(self, page: Page) -> bool:
        selectors = (
            'div.progress-div:has-text("继续上传")',
            'div.progress-div:has-text("已暂停")',
            "text=继续上传",
            "text=已暂停",
            "text=恢复上传",
        )
        for selector in selectors:
            try:
                if await page.locator(selector).count():
                    return True
            except Exception:
                continue
        return False

    async def has_upload_failed(self, page: Page) -> bool:
        selectors = (
            'div.progress-div:has-text("上传失败")',
            "text=上传失败",
            "text=文件格式不支持",
            "text=上传出错",
        )
        for selector in selectors:
            try:
                if await page.locator(selector).count():
                    return True
            except Exception:
                continue
        return False

    async def click_publish_button(self, page: Page) -> bool:
        publish_button = page.get_by_role("button", name="发布", exact=True).first
        if not await publish_button.count():
            return False
        button_class = await publish_button.get_attribute("class") or ""
        disabled_attr = await publish_button.get_attribute("disabled")
        if disabled_attr is not None or "disabled" in button_class:
            return False
        await publish_button.click()
        return True

    async def is_publish_success(self, page: Page) -> bool:
        if "creator-micro/content/manage" in page.url:
            return True
        for selector in ("text=发布成功", "text=发布完成", "text=作品管理"):
            try:
                if await page.locator(selector).count():
                    return True
            except Exception:
                continue
        return False

    async def set_video_file_for_upload(self, page: Page):
        selectors = [
            'input[type="file"][accept*="video"]',
            'input[accept*="video"]',
            'div[class^="container"] input[type="file"]',
            'div[class^="container"] input',
        ]
        last_error = None
        for selector in selectors:
            try:
                upload_input = page.locator(selector).first
                await upload_input.wait_for(state="attached", timeout=8000)
                await upload_input.set_input_files(self.file_path)
                douyin_logger.info(_msg("🥳", "已把视频文件交给抖音上传控件"))
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            "VF-PUBLISH-UPLOAD-INPUT-MISSING: 未找到可用的抖音视频上传控件，"
            "可能是平台页面结构变化、Cookie 跳转异常，或页面未正常加载。"
            f"最后错误: {last_error}"
        )

    async def wait_for_publish_editor_page(self, page: Page):
        started_at = asyncio.get_running_loop().time()
        while True:
            if "creator-micro/content/publish" in page.url:
                douyin_logger.info(_msg("🥳", "已经进入 version_1 发布页面"))
                return
            if "creator-micro/content/post/video" in page.url:
                douyin_logger.info(_msg("🥳", "已经进入 version_2 发布页面"))
                return
            if await page.get_by_text("手机号登录").count() or await page.get_by_text("扫码登录").count():
                raise RuntimeError("VF-PUBLISH-COOKIE-INVALID: 抖音 Cookie 已失效，请重新连接账号。")
            if await self.has_upload_failed(page):
                raise RuntimeError("VF-PUBLISH-UPLOAD-START-FAILED: 抖音页面提示上传失败，请检查视频文件或平台页面状态。")
            elapsed_seconds = asyncio.get_running_loop().time() - started_at
            if elapsed_seconds > DOUYIN_ENTER_PUBLISH_PAGE_TIMEOUT:
                raise RuntimeError(
                    f"VF-PUBLISH-UPLOAD-NOT-STARTED: 已等待 {DOUYIN_ENTER_PUBLISH_PAGE_TIMEOUT} 秒，"
                    "抖音仍未进入发布编辑页。可能是没有成功触发上传、浏览器文件控件失效、"
                    "平台页面结构变化，或账号页面被风控拦截。"
                )
            douyin_logger.debug(_msg("🧍", "还没进到视频发布页面，小人继续等一会"))
            await asyncio.sleep(1)

    async def validate_upload_args(self):
        await self.validate_base_args()
        if not self.title or not str(self.title).strip():
            raise ValueError("视频模式下，title 是必须的")

        self.file_path = str(self.validate_video_file(self.file_path))
        if self.thumbnail_landscape_path:
            self.thumbnail_landscape_path = str(self.validate_image_file(self.thumbnail_landscape_path))
        if self.thumbnail_portrait_path:
            self.thumbnail_portrait_path = str(self.validate_image_file(self.thumbnail_portrait_path))

    async def handle_upload_error(self, page, retry_count):
        if retry_count >= self.upload_retry_limit:
            raise RuntimeError(
                f"抖音视频上传失败，已停止自动重传。当前自动重试上限为 {self.upload_retry_limit} 次；"
                "如需允许重试，可在 .env 设置 DOUYIN_UPLOAD_RETRY_LIMIT。"
            )
        douyin_logger.warning(_msg("😵", f"检测到上传失败，准备第 {retry_count + 1}/{self.upload_retry_limit} 次重新上传"))
        await self.set_video_file_for_upload(page)
        return retry_count + 1

    async def handle_auto_video_cover(self, page):
        if await page.get_by_text("请设置封面后再发布").first.is_visible():
            douyin_logger.info(_msg("🧍", "发布前还得先把封面弄好"))
            recommend_cover = page.locator('[class^="recommendCover-"]').first
            if await recommend_cover.count():
                douyin_logger.info(_msg("🏃", "小人去选第一个推荐封面"))
                try:
                    await recommend_cover.click()
                    await asyncio.sleep(1)
                    confirm_text = "是否确认应用此封面？"
                    if await page.get_by_text(confirm_text).first.is_visible():
                        douyin_logger.info(_msg("🪟", f"弹出确认框了: {confirm_text}"))
                        await page.get_by_role("button", name="确定").click()
                        douyin_logger.info(_msg("🥳", "推荐封面已经应用"))
                        await asyncio.sleep(1)
                    douyin_logger.info(_msg("🥳", "封面选择流程完成"))
                    return True
                except Exception as e:
                    douyin_logger.warning(_msg("😵", f"推荐封面没选成功: {e}"))
        return False

    async def set_thumbnail(self, page: Page):
        if not self.thumbnail_landscape_path and not self.thumbnail_portrait_path:
            return

        douyin_logger.info(_msg("🏃", "小人正在设置视频封面"))
        await page.click('text="选择封面"')
        cover_locator_str = 'div[id*="creator-content-modal"]'
        cover_locator = page.locator(cover_locator_str)
        await page.wait_for_selector(cover_locator_str)

        upload_input = cover_locator.locator("div[class^='semi-upload upload'] >> input.semi-upload-hidden-input")

        if self.thumbnail_landscape_path:
            await page.wait_for_timeout(1000)
            await upload_input.set_input_files(self.thumbnail_landscape_path)
            await page.wait_for_timeout(2000)
            douyin_logger.info(_msg("🖼️", "横版封面上传完成"))

        if self.thumbnail_portrait_path:
            await cover_locator.locator("div[class*='steps'] div").nth(1).click()
            await page.wait_for_timeout(1000)
            await upload_input.set_input_files(self.thumbnail_portrait_path)
            await page.wait_for_timeout(2000)
            douyin_logger.info(_msg("🖼️", "竖版封面上传完成"))

        await cover_locator.locator('button:visible:has-text("完成")').click()
        douyin_logger.info(_msg("🥳", "视频封面设置完成"))
        await page.wait_for_selector("div.extractFooter", state="detached")

    async def upload(self, playwright: Playwright) -> None:
        douyin_logger.info(_msg("🧍", "小人先检查 cookie、视频文件、封面和发布时间"))
        await self.validate_upload_args()
        douyin_logger.info(_msg("🥳", "上传前检查通过"))

        browser = await launch_douyin_browser(playwright, headless=self.headless)
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
            permissions=["geolocation"],
        )
        context = await set_init_script(context)

        upload_success = False
        try:
            page = await context.new_page()
            await safe_goto_douyin(page, DOUYIN_UPLOAD_URL)
            douyin_logger.info(_msg("🏃", f"小人开始搬运视频: {self.title}.mp4"))
            douyin_logger.info(_msg("🧭", "小人正在赶往上传主页"))
            await page.wait_for_url(DOUYIN_UPLOAD_URL, timeout=DOUYIN_GOTO_TIMEOUT_MS)
            await self.set_video_file_for_upload(page)
            await self.wait_for_publish_editor_page(page)

            await asyncio.sleep(1)
            douyin_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
            await self.fill_title_and_description(page, self.title, self.desc or self.title, self.tags)
            douyin_logger.info(_msg("🏷️", f"小人一共贴了 {len(self.tags)} 个话题"))

            upload_retry_count = 0
            last_upload_progress_text = ""
            stable_progress_rounds = 0
            upload_wait_started_at = asyncio.get_running_loop().time()
            while True:
                try:
                    if await self.is_upload_paused(page):
                        raise RuntimeError(
                            "VF-PUBLISH-UPLOAD-PAUSED: 抖音视频上传已暂停，可能是发布过程中手动点击了暂停传输。"
                            "请到抖音创作者中心恢复上传，或重新发起发布任务。"
                        )
                    if await self.is_upload_ready_to_publish(page):
                        douyin_logger.success(_msg("🥳", "视频已经传完啦"))
                        break
                    elapsed_seconds = asyncio.get_running_loop().time() - upload_wait_started_at
                    if elapsed_seconds > DOUYIN_UPLOAD_WAIT_TIMEOUT:
                        raise RuntimeError(
                            f"VF-PUBLISH-UPLOAD-TIMEOUT: 抖音视频上传等待超过 {DOUYIN_UPLOAD_WAIT_TIMEOUT} 秒，"
                            "页面未出现可发布状态。可能原因：上传被浏览器暂停、平台页面结构变化、网络上传卡住，"
                            "或已手动发布导致自动化无法继续确认。"
                        )
                    progress_text = ""
                    try:
                        progress_node = page.locator("div.progress-div").first
                        if await progress_node.count():
                            progress_text = (await progress_node.inner_text(timeout=1000)).strip()
                    except Exception:
                        progress_text = ""
                    if progress_text and progress_text != last_upload_progress_text:
                        douyin_logger.info(_msg("🏃", f"抖音上传进度: {progress_text}"))
                        last_upload_progress_text = progress_text
                        stable_progress_rounds = 0
                    else:
                        stable_progress_rounds += 1
                        if stable_progress_rounds % 15 == 0:
                            douyin_logger.info(_msg("🏃", "抖音仍在上传视频，继续等待"))
                    await asyncio.sleep(2)
                    if await self.has_upload_failed(page):
                        douyin_logger.error(_msg("😵", "检测到上传失败，小人准备重试"))
                        upload_retry_count = await self.handle_upload_error(page, upload_retry_count)
                except RuntimeError:
                    raise
                except Exception as exc:
                    douyin_logger.warning(_msg("😵", f"等待抖音上传状态时出错，继续观察: {exc}"))
                    await asyncio.sleep(2)

            if self.productLink and self.productTitle:
                douyin_logger.info(_msg("🛒", "小人正在设置商品链接"))
                await self.set_product_link(page, self.productLink, self.productTitle)
                douyin_logger.info(_msg("🥳", "商品链接设置完成"))

            await self.set_thumbnail(page)

            third_part_element = '[class^="info"] > [class^="first-part"] div div.semi-switch'
            if await page.locator(third_part_element).count():
                if "semi-switch-checked" not in await page.eval_on_selector(third_part_element, "div => div.className"):
                    await page.locator(third_part_element).locator("input.semi-switch-native-control").click()

            if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
                await self.set_schedule_time_douyin(page, self.publish_date)

            publish_deadline = time.monotonic() + DOUYIN_PUBLISH_CONFIRM_TIMEOUT
            while True:
                if time.monotonic() > publish_deadline:
                    raise RuntimeError("VF-PUBLISH-CONFIRM-TIMEOUT: 抖音发布确认超时，未跳转到内容管理页。")
                try:
                    clicked = await self.click_publish_button(page)
                    if not clicked:
                        douyin_logger.info(_msg("🏃", "发布按钮暂不可点，继续等待"))
                    await page.wait_for_url(
                        "https://creator.douyin.com/creator-micro/content/manage**",
                        timeout=3000,
                    )
                    douyin_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                    upload_success = True
                    break
                except Exception:
                    if await self.is_publish_success(page):
                        douyin_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                        upload_success = True
                        break
                    await self.handle_auto_video_cover(page)
                    douyin_logger.info(_msg("🏃", "小人正在冲刺发布视频"))
                    if self.debug:
                        await page.screenshot(full_page=True)
                    await asyncio.sleep(0.5)

            await context.storage_state(path=self.account_file)
            douyin_logger.success(_msg("🥳", "cookie 更新完毕"))
            await asyncio.sleep(2)
        finally:
            await context.close()
            await browser.close()

    async def douyin_upload_video(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)

    async def main(self):
        await self.douyin_upload_video()


class DouYinNote(DouYinBaseUploader):
    def __init__(
        self,
        image_paths,
        note,
        tags,
        publish_date: datetime | int,
        account_file,
        title: str | None = None,
        publish_strategy: str = DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = DEBUG_MODE,
        headless: bool = LOCAL_CHROME_HEADLESS,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
        )
        self.image_paths = image_paths
        self.note = note or ""
        self.title = title or (self.note[:30] if self.note else "")
        self.tags = tags or []

    async def validate_upload_args(self):
        await self.validate_base_args()
        if not self.title or not str(self.title).strip():
            raise ValueError("图文模式下，title 是必须的")
        if not self.image_paths:
            raise ValueError("图文模式下，图片是必须的")

        if isinstance(self.image_paths, (str, Path)):
            self.image_paths = [self.image_paths]

        if len(self.image_paths) > 35:
            raise ValueError("图文模式下最多只支持上传 35 张图片")

        normalized_image_paths = []
        for image_path in self.image_paths:
            normalized_image_paths.append(str(self.validate_image_file(image_path)))
        self.image_paths = normalized_image_paths

    async def upload_note_content(self, page: Page) -> None:
        douyin_logger.info(_msg("🏃", f"小人开始搬运图文，共 {len(self.image_paths)} 张图片"))
        douyin_logger.info(_msg("🔀", "小人正在切换到图文发布"))
        await page.get_by_text("发布图文", exact=True).click()
        await page.wait_for_timeout(1000)

        douyin_logger.info(_msg("📤", "小人正在上传图片"))
        await page.locator("div[class^='container'] input[accept*='image']").set_input_files(self.image_paths)

        while True:
            try:
                await page.wait_for_url(
                    "**/creator-micro/content/post/image?**",
                    timeout=3000,
                )
                douyin_logger.info(_msg("🥳", "已经进入图文发布页面"))
                break
            except Exception:
                douyin_logger.debug(_msg("🧍", "小人还在等图片上传完成"))
                await asyncio.sleep(0.5)

        await asyncio.sleep(1)
        douyin_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_title_and_description(page, self.title, self.note, self.tags)
        douyin_logger.info(_msg("🏷️", f"小人一共贴了 {len(self.tags)} 个话题"))

        if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_douyin(page, self.publish_date)

        while True:
            try:
                publish_button = page.get_by_role("button", name="发布", exact=True)
                if await publish_button.count():
                    await publish_button.click()
                await page.wait_for_url(
                    "**/creator-micro/content/manage?enter_from=publish**",
                    timeout=3000,
                )
                douyin_logger.success(_msg("🥳", "图文发布成功，小人开心收工"))
                break
            except Exception:
                douyin_logger.info(_msg("🏃", "小人正在冲刺发布图文"))
                await asyncio.sleep(0.5)

    async def upload(self, playwright: Playwright) -> None:
        douyin_logger.info(_msg("🧍", "小人先检查 cookie、图片和发布时间"))
        await self.validate_upload_args()
        douyin_logger.info(_msg("🥳", "图文上传前检查通过"))

        browser = await launch_douyin_browser(playwright, headless=self.headless)
        context = await browser.new_context(
            storage_state=f"{self.account_file}",
            permissions=["geolocation"],
        )
        context = await set_init_script(context)

        upload_success = False
        try:
            page = await context.new_page()
            await safe_goto_douyin(page, DOUYIN_UPLOAD_URL)
            douyin_logger.info(_msg("🧭", "小人正在赶往图文发布页"))
            await page.wait_for_url(DOUYIN_UPLOAD_URL, timeout=DOUYIN_GOTO_TIMEOUT_MS)

            await self.upload_note_content(page)
            upload_success = True
        finally:
            if upload_success:
                await context.storage_state(path=self.account_file)
                douyin_logger.success(_msg("🥳", "cookie 更新完毕"))
                await asyncio.sleep(2)
            await context.close()
            await browser.close()

    async def douyin_upload_note(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)
