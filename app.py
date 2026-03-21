import json

import boto3
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import helper
import job_store
from data_models import DownloadResult, JobStatus
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
            helper.debug_print(f"使用 frame: {'mainFrame' if page.frame(name='mainFrame') else 'page'}")

            # 等待圖片載入
            try:
                helper.debug_print("等待圖片元素載入...")
                frame.wait_for_selector("img.se-image-resource.egjs-visible", timeout=10000)
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

            img_elements = frame.query_selector_all("img.se-image-resource.egjs-visible")
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
                    for _attempt in range(8):
                        popup_img_el = frame.query_selector("div.cpv__img_wrap img.cpv__img")
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

        # 修正順序:根據檔名編號排序
        if len(img_urls) > 1:
            try:
                import re

                # 提取所有圖片的編號
                url_with_numbers = []
                for url in img_urls:
                    match = re.search(r"_(\d+)\.(jpg|jpeg|png|gif)", url)
                    if match:
                        number = int(match.group(1))
                        url_with_numbers.append((number, url))
                    else:
                        url_with_numbers.append((float("inf"), url))  # 無法提取編號的放最後

                helper.debug_print(f"提取到的編號: {[num for num, _ in url_with_numbers[:10]]}")

                # 檢查是否需要排序(前幾張編號是否已經是遞增的)
                check_count = min(5, len(url_with_numbers))
                first_few_numbers = [num for num, _ in url_with_numbers[:check_count]]

                # 檢查前幾張是否已經排序好
                is_sorted = all(
                    first_few_numbers[i] <= first_few_numbers[i + 1]
                    for i in range(len(first_few_numbers) - 1)
                    if first_few_numbers[i] != float("inf") and first_few_numbers[i + 1] != float("inf")
                )

                if not is_sorted:
                    # 按編號排序
                    url_with_numbers.sort(key=lambda x: x[0])
                    img_urls = [url for _, url in url_with_numbers]
                    helper.debug_print(f"圖片順序已修正,排序後前 5 張編號: {[num for num, _ in url_with_numbers[:5]]}")
                else:
                    helper.debug_print("圖片順序正確,無需調整")

            except Exception as e:
                helper.debug_print(f"順序修正時發生錯誤: {e},保持原順序")

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


def _parse_request_body(event) -> dict:
    """解析 API Gateway 或直接呼叫的 event，回傳 body dict"""
    if isinstance(event, str):
        event = json.loads(event or "{}")

    if not isinstance(event, dict):
        return {}

    helper.debug_print(f"Raw Event: {event}")

    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            body = json.loads(body or "{}")
        elif not isinstance(body, dict):
            body = {}
        helper.debug_print(f"Parsed Request Body: {body}")
        return body

    return event


def _handle_submit(body, context):
    """建立任務 → 非同步呼叫 worker → 回傳 job_id"""
    blog_url = body.get("blog_url")
    if not blog_url:
        response = build_response(400, {"error": "缺少 blog_url 參數"})
        helper.debug_print(f"Response: {response}")
        return response

    job_id = job_store.create_job(blog_url)
    helper.debug_print(f"已建立任務: {job_id}，準備非同步呼叫 worker")

    # 非同步呼叫自身處理
    boto3.client("lambda").invoke(
        FunctionName=context.function_name,
        InvocationType="Event",
        Payload=json.dumps(
            {
                "_async_worker": True,
                "job_id": job_id,
                "blog_url": blog_url,
            }
        ),
    )

    response = build_response(202, {"job_id": job_id, "status": JobStatus.PROCESSING})
    helper.debug_print(f"Response: {response}")
    return response


def _handle_status(body):
    """查詢任務狀態"""
    job_id = body.get("job_id")
    if not job_id:
        response = build_response(400, {"error": "缺少 job_id 參數"})
        helper.debug_print(f"Response: {response}")
        return response

    job = job_store.get_job(job_id)
    if not job:
        response = build_response(404, {"error": "任務不存在"})
        helper.debug_print(f"Response: {response}")
        return response

    response_body = {"job_id": job_id, "status": job["status"]}
    if job.get("result"):
        response_body["result"] = job["result"]
    response = build_response(200, response_body)
    helper.debug_print(f"Response: {response}")
    return response


def _handle_async_worker(event):
    """背景 worker：執行 Playwright 爬取，結果寫入 S3"""
    job_id = event["job_id"]
    blog_url = event["blog_url"]
    helper.debug_print(f"Worker 開始處理任務: {job_id}，URL: {blog_url}")

    try:
        result = download_images_from_naver_blog(blog_url)
        if result.image_urls:
            status = JobStatus.COMPLETED
        elif result.errors:
            status = JobStatus.FAILED
        else:
            status = JobStatus.COMPLETED  # 沒有圖片也沒有錯誤（例如文章本身無圖）
        job_store.update_job(job_id, status, result.to_dict())
        helper.debug_print(f"任務 {job_id} 狀態: {status}，找到 {result.successful_downloads} 張圖片")
    except Exception as e:
        helper.debug_print(f"任務 {job_id} 處理失敗: {e}")
        job_store.update_job(job_id, JobStatus.FAILED, {"error": str(e)})


def lambda_handler(event, context):
    helper.debug_print(f"Event: {event}")

    # 1. 非同步 worker 模式（被自己 async invoke）
    if isinstance(event, dict) and "_async_worker" in event:
        _handle_async_worker(event)
        return

    # 2. 解析 API Gateway 請求
    body = _parse_request_body(event)
    action = body.get("action", "download")  # 向後相容：沒有 action 就當 download

    if action == "download":
        return _handle_submit(body, context)
    elif action == "status":
        return _handle_status(body)
    else:
        response = build_response(400, {"error": f"未知的 action: {action}"})
        helper.debug_print(f"Response: {response}")
        return response
