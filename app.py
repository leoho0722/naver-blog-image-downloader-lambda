import json

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import helper
from data_models import DownloadResult
from response_builder import build_response


def download_images_from_naver_blog(blog_url: str) -> DownloadResult:
    start_time = helper.get_current_time()
    errors = []
    img_urls = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--single-process",  # 關鍵:在 Lambda 中使用單進程模式
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-blink-features=AutomationControlled",
                ],
                chromium_sandbox=False,  # 關鍵:完全禁用 sandbox
            )
            context = browser.new_context(
                locale="ko-KR",
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()

            helper.debug_print(f"正在訪問: {blog_url}")
            page.goto(blog_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(500)  # 等待頁面穩定

            # 若是手機版則切換到電腦版
            if "m.blog.naver.com" in page.url:
                try:
                    pc_btn = page.locator("a#goToBase")
                    if pc_btn.is_visible():
                        pc_btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                        page.wait_for_timeout(500)
                except Exception as e:
                    helper.debug_print(f"切換到電腦版時發生錯誤: {e}")

            # 等待 mainFrame 載入
            try:
                page.wait_for_selector("iframe#mainFrame", timeout=5000)
            except Exception:
                pass

            frame = page.frame(name="mainFrame") or page
            helper.debug_print(
                f"使用 frame: {'mainFrame' if page.frame(name='mainFrame') else 'page'}"
            )

            # 等待圖片載入
            try:
                helper.debug_print("等待圖片元素載入...")
                frame.wait_for_selector(
                    "img.se-image-resource.egjs-visible", timeout=10000
                )
                helper.debug_print("圖片元素已載入")
            except PlaywrightTimeoutError:
                errors.append("等待圖片元素超時")
                elapsed = helper.calculate_elapsed_time(start_time)
                return DownloadResult(0, 0, 1, [], errors, elapsed)
            except Exception as e:
                error_msg = str(e)
                elapsed = helper.calculate_elapsed_time(start_time)
                if "closed" in error_msg.lower():
                    errors.append(f"瀏覽器/頁面被關閉: {error_msg}")
                    return DownloadResult(0, 0, 1, [], errors, elapsed)
                else:
                    errors.append(f"載入圖片時發生錯誤: {error_msg}")
                    return DownloadResult(0, 0, 1, [], errors, elapsed)

            # 額外等待確保所有圖片都載入
            page.wait_for_timeout(500)

            img_elements = frame.query_selector_all(
                "img.se-image-resource.egjs-visible"
            )
            helper.debug_print(f"找到 {len(img_elements)} 張圖片")

            if not img_elements:
                elapsed = helper.calculate_elapsed_time(start_time)
                return DownloadResult(0, 0, 0, [], ["未找到任何圖片"], elapsed)

            for idx, img_element in enumerate(img_elements):
                try:
                    helper.debug_print(f"處理第 {idx + 1}/{len(img_elements)} 張圖片")

                    # 檢查元素是否還存在
                    if not img_element.is_visible():
                        errors.append(f"第{idx + 1}張圖片不可見")
                        continue

                    # 點擊圖片
                    img_element.click()
                    page.wait_for_timeout(300)

                    # 等待彈窗出現
                    popup_img = None
                    for attempt in range(8):
                        popup_img_el = frame.query_selector(
                            "div.cpv__img_wrap img.cpv__img"
                        )
                        if popup_img_el:
                            popup_img = popup_img_el
                            helper.debug_print(f"第 {idx + 1} 張圖片彈窗已出現")
                            break
                        page.wait_for_timeout(200)

                    if not popup_img:
                        errors.append(f"第{idx + 1}張圖片未找到彈窗原圖")
                        # 嘗試關閉可能存在的彈窗
                        try:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(200)
                        except Exception:
                            pass
                        continue

                    img_url = popup_img.get_attribute("src")
                    if not img_url or not img_url.startswith("http"):
                        errors.append(f"第{idx + 1}張圖片無效連結: {img_url}")
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                        continue

                    img_urls.append(img_url)
                    helper.debug_print(f"第 {idx + 1} 張圖片 URL: {img_url[:80]}...")

                    # 關閉彈窗
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(200)

                except Exception as e:
                    error_msg = str(e)
                    if "closed" in error_msg.lower():
                        errors.append(f"第{idx + 1}張圖片處理時瀏覽器被關閉")
                        break  # 停止處理剩餘圖片
                    else:
                        errors.append(f"第{idx + 1}張圖片錯誤: {error_msg}")

                    # 嘗試關閉可能存在的彈窗
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(200)
                    except Exception:
                        pass
                    continue

            browser.close()

        elapsed = helper.calculate_elapsed_time(start_time)
        return DownloadResult(
            total_images=len(img_elements),
            successful_downloads=len(img_urls),
            failure_downloads=len(errors),
            image_urls=img_urls,
            errors=errors,
            elapsed_time=elapsed,
        )

    except Exception as e:
        elapsed = helper.calculate_elapsed_time(start_time)
        return DownloadResult(0, 0, 0, [], [str(e)], elapsed)


def lambda_handler(event, context):
    request_start_time = helper.get_current_time()

    helper.debug_print("Event: {}".format(event))

    # 從 event 中取得 Naver Blog URL
    blog_url = None

    # 1. 解析 event 內容
    # 如果 event 是字串，嘗試將其解析為 JSON
    if isinstance(event, str):
        event = json.loads(event or "{}")
        helper.debug_print("Raw Request Body: {}".format(event))

    # 如果 event 是字典，直接使用
    if isinstance(event, dict):
        helper.debug_print("Raw Request Body: {}".format(event))

    # 2. 判斷 event 結構中是否有 body，還是直接包含參數
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            body = json.loads(body or "{}")
            helper.debug_print("Parsed Request Body: {}".format(body))
        elif isinstance(body, dict):
            helper.debug_print("Parsed Request Body: {}".format(body))
        else:
            body = {}
        blog_url = body.get("blog_url")
    else:
        blog_url = event.get("blog_url")

    if not blog_url:
        elapsed = helper.calculate_elapsed_time(request_start_time)
        result = DownloadResult(0, 0, 0, [], ["缺少 blog_url 參數"], elapsed)
        return build_response(400, result.to_dict())

    result = download_images_from_naver_blog(blog_url)

    # 更新總花費時間（包含請求解析時間）
    total_elapsed = helper.calculate_elapsed_time(request_start_time)
    result.elapsed_time = total_elapsed

    status = 200 if result.image_urls else 500
    return build_response(status, result.to_dict())
