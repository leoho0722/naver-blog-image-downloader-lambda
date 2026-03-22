"""Lambda 入口點：路由 submit/status/async worker，含圖片擷取邏輯"""

import json
import re

import boto3
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import helper
from data_models import DownloadResult, JobStatus
from job_store import JobStore, LogStore
from response_builder import build_response

job_store = JobStore()
log_store = LogStore()


def _dedup_urls(img_urls: list[str]) -> list[str]:
    """去重：移除重複的 URL，保留首次出現的順序

    Args:
        img_urls (list[str]): 可能含重複的圖片 URL 列表

    Returns:
        去重後的圖片 URL 列表
    """
    if not img_urls:
        return img_urls

    helper.debug_print(f"去重前共 {len(img_urls)} 筆 URL：")
    for i, url in enumerate(img_urls):
        helper.debug_print(f"  [{i + 1}] {url}")

    seen = set()
    unique_urls = []
    duplicate_urls = []
    for url in img_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
        else:
            duplicate_urls.append(url)
    if duplicate_urls:
        helper.debug_print(f"去重：從 {len(img_urls)} 筆移除 {len(duplicate_urls)} 筆重複，剩餘 {len(unique_urls)} 筆")
        for dup_url in duplicate_urls:
            helper.debug_print(f"去重移除: {dup_url}")

    helper.debug_print(f"去重後共 {len(unique_urls)} 筆 URL：")
    for i, url in enumerate(unique_urls):
        helper.debug_print(f"  [{i + 1}] {url}")

    return unique_urls


def _sort_urls_by_number(img_urls: list[str]) -> list[str]:
    """根據檔名中的數字編號（如 _1.jpg、_31.jpg）遞增排序

    Args:
        img_urls (list[str]): 圖片 URL 列表

    Returns:
        按編號排序後的圖片 URL 列表
    """
    if len(img_urls) <= 1:
        return img_urls

    try:
        url_with_numbers = []
        for url in img_urls:
            match = re.search(r"_(\d+)\.(jpg|jpeg|png|gif)", url)
            if match:
                number = int(match.group(1))
                url_with_numbers.append((number, url))
            else:
                url_with_numbers.append((float("inf"), url))

        helper.debug_print(f"提取到的編號: {[num for num, _ in url_with_numbers]}")

        all_numbers = [num for num, _ in url_with_numbers if num != float("inf")]
        is_sorted = all(all_numbers[i] <= all_numbers[i + 1] for i in range(len(all_numbers) - 1))

        if not is_sorted:
            url_with_numbers.sort(key=lambda x: x[0])
            img_urls = [url for _, url in url_with_numbers]
            helper.debug_print(f"圖片順序已修正,排序後編號: {[num for num, _ in url_with_numbers]}")
        else:
            helper.debug_print("圖片順序正確,無需調整")

    except Exception as e:
        helper.debug_print(f"順序修正時發生錯誤: {e},保持原順序")

    return img_urls


def _wait_popup_closed(frame, page, max_retries=10, interval=200):
    """按 Escape 後，主動輪詢直到彈窗消失（元素被移除或不可見）

    Args:
        frame: Playwright Frame 或 Page，用於查詢彈窗元素
        page: Playwright Page，用於 wait_for_timeout
        max_retries (int): 最大輪詢次數，預設 10
        interval (int): 每次輪詢間隔毫秒數，預設 200
    """
    for _ in range(max_retries):
        popup_check = frame.query_selector("div.cpv__img_wrap img.cpv__img")
        if not popup_check or not popup_check.is_visible():
            return
        page.wait_for_timeout(interval)


def download_images_from_naver_blog(blog_url: str) -> DownloadResult:
    """從 Naver Blog 文章擷取所有原始圖片 URL

    透過 Playwright Chromium 訪問文章頁面，逐一點擊圖片開啟彈窗，
    從彈窗中取得原圖 URL。包含三層防禦機制確保完整性：
    Layer 1 確認彈窗關閉、Layer 2 偵測 stale src、Layer 3 重試遺漏，
    以及最終的序號完整性驗證。

    Args:
        blog_url (str): Naver Blog 文章 URL

    Returns:
        DownloadResult 包含擷取到的圖片 URL、錯誤訊息與統計資訊
    """
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

            previous_url = None  # 追蹤上一張圖片的 URL，用於偵測彈窗未更新
            index_to_url = {}  # 記錄每個索引成功擷取的 URL

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

                    # Phase A：等待彈窗出現
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
                        # 嘗試關閉可能存在的彈窗並確認關閉
                        try:
                            page.keyboard.press("Escape")
                            _wait_popup_closed(frame, page)
                        except Exception:
                            pass
                        continue

                    # Phase B：偵測 stale src（彈窗 src 是否仍為上一張圖片）
                    img_url = popup_img.get_attribute("src")
                    if previous_url is not None and img_url == previous_url:
                        for _stale in range(10):
                            if img_url != previous_url:
                                break
                            helper.debug_print(f"第 {idx + 1} 張圖片彈窗 src 尚未更新，重試第 {_stale + 1} 次")
                            page.wait_for_timeout(200)
                            popup_img_el = frame.query_selector("div.cpv__img_wrap img.cpv__img")
                            if popup_img_el:
                                popup_img = popup_img_el
                            img_url = popup_img.get_attribute("src")

                    # Phase B 失敗：stale src 始終未更新，跳過讓 Layer 3 重試
                    if previous_url is not None and img_url == previous_url:
                        errors.append(f"第{idx + 1}張圖片彈窗 src 始終未更新")
                        helper.debug_print(f"第 {idx + 1} 張圖片 Phase B 失敗，將由 Layer 3 重試")
                        page.keyboard.press("Escape")
                        _wait_popup_closed(frame, page)
                        continue

                    if not img_url or not img_url.startswith("http"):
                        errors.append(f"第{idx + 1}張圖片無效連結: {img_url}")
                        page.keyboard.press("Escape")
                        _wait_popup_closed(frame, page)
                        continue

                    img_urls.append(img_url)
                    previous_url = img_url
                    index_to_url[idx] = img_url
                    helper.debug_print(f"第 {idx + 1} 張圖片 URL: {img_url}")

                    # Layer 1：關閉彈窗並主動驗證已關閉
                    page.keyboard.press("Escape")
                    _wait_popup_closed(frame, page)

                except Exception as e:
                    error_msg = str(e)
                    if "closed" in error_msg.lower():
                        errors.append(f"第{idx + 1}張圖片處理時瀏覽器被關閉")
                        break  # 停止處理剩餘圖片
                    else:
                        errors.append(f"第{idx + 1}張圖片錯誤: {error_msg}")

                    # 嘗試關閉可能存在的彈窗並確認關閉
                    try:
                        page.keyboard.press("Escape")
                        _wait_popup_closed(frame, page)
                    except Exception:
                        pass
                    continue

            # === Layer 3：識別需重試的索引（重複或失敗） ===
            indices_to_retry = []
            seen_urls = set()
            for idx in sorted(index_to_url.keys()):
                url = index_to_url[idx]
                if url in seen_urls:
                    indices_to_retry.append(idx)
                else:
                    seen_urls.add(url)

            # 加入完全失敗的索引
            all_indices = set(range(len(img_elements)))
            successful_indices = set(index_to_url.keys())
            failed_indices = all_indices - successful_indices
            indices_to_retry.extend(sorted(failed_indices))
            indices_to_retry = sorted(set(indices_to_retry))

            if indices_to_retry:
                helper.debug_print(f"準備重新擷取 {len(indices_to_retry)} 張圖片，索引: {indices_to_retry}")
                for retry_idx in indices_to_retry:
                    try:
                        img_element = img_elements[retry_idx]
                        if not img_element.is_visible():
                            helper.debug_print(f"重試：第 {retry_idx + 1} 張圖片不可見，跳過")
                            continue

                        stale_url = index_to_url.get(retry_idx)
                        img_element.click()
                        page.wait_for_timeout(500)

                        popup_img = None
                        for _attempt in range(8):
                            popup_img_el = frame.query_selector("div.cpv__img_wrap img.cpv__img")
                            if popup_img_el:
                                popup_img = popup_img_el
                                break
                            page.wait_for_timeout(200)

                        if not popup_img:
                            helper.debug_print(f"重試：第 {retry_idx + 1} 張圖片未找到彈窗")
                            try:
                                page.keyboard.press("Escape")
                                _wait_popup_closed(frame, page)
                            except Exception:
                                pass
                            continue

                        img_url = popup_img.get_attribute("src")
                        if stale_url:
                            for _stale in range(15):
                                if img_url != stale_url:
                                    break
                                page.wait_for_timeout(300)
                                popup_img_el = frame.query_selector("div.cpv__img_wrap img.cpv__img")
                                if popup_img_el:
                                    popup_img = popup_img_el
                                img_url = popup_img.get_attribute("src")

                        if img_url and img_url.startswith("http") and img_url != stale_url:
                            index_to_url[retry_idx] = img_url
                            helper.debug_print(f"重試成功：第 {retry_idx + 1} 張圖片 URL: {img_url}")
                        else:
                            helper.debug_print(f"重試失敗：第 {retry_idx + 1} 張圖片仍為相同或無效 URL")

                        page.keyboard.press("Escape")
                        _wait_popup_closed(frame, page)

                    except Exception as e:
                        error_msg = str(e)
                        if "closed" in error_msg.lower():
                            helper.debug_print(f"重試：第 {retry_idx + 1} 張圖片處理時瀏覽器被關閉")
                            break
                        helper.debug_print(f"重試：第 {retry_idx + 1} 張圖片錯誤: {error_msg}")
                        try:
                            page.keyboard.press("Escape")
                            _wait_popup_closed(frame, page)
                        except Exception:
                            pass

                # 從 index_to_url 按索引順序重建 img_urls
                img_urls = [index_to_url[idx] for idx in sorted(index_to_url.keys())]
                helper.debug_print(f"重試後共有 {len(img_urls)} 張圖片 URL")
            else:
                helper.debug_print("所有圖片擷取成功，無需重試")

            # === 去重 + 排序（移至 browser.close 前） ===
            img_urls = _dedup_urls(img_urls)
            img_urls = _sort_urls_by_number(img_urls)

            # === 序號完整性驗證：檢查缺漏並重新爬取 ===
            collected_numbers = set()
            for url in img_urls:
                m = re.search(r"_(\d+)\.(jpg|jpeg|png|gif)", url)
                if m:
                    collected_numbers.add(int(m.group(1)))

            if collected_numbers:
                # 取 max(已收集最大序號, 頁面元素數量)，確保尾端遺漏也能偵測
                max_num = max(max(collected_numbers), len(img_elements))
                expected = set(range(1, max_num + 1))
                missing = sorted(expected - collected_numbers)
            else:
                missing = []

            if missing:
                helper.debug_print(f"序號完整性驗證：缺漏序號 {missing}")

                # 開啟彈窗：點擊最後一個可見元素，透過 carousel 導航
                try:
                    last_elem = img_elements[-1]
                    last_elem.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    last_elem.click()
                    page.wait_for_timeout(1000)

                    popup_img = None
                    for _attempt in range(12):
                        popup_img_el = frame.query_selector("div.cpv__img_wrap img.cpv__img")
                        if popup_img_el:
                            popup_img = popup_img_el
                            break
                        page.wait_for_timeout(300)

                    if popup_img:
                        for num in sorted(missing):
                            expected_pattern = f"_{num}."
                            found = False
                            # 用方向鍵導航，最多按 max_num 次（繞一圈）
                            for _nav in range(max_num):
                                img_url = popup_img.get_attribute("src")
                                if img_url and expected_pattern in img_url:
                                    img_urls.append(img_url)
                                    found = True
                                    helper.debug_print(f"序號 {num} 補回成功（carousel 導航）：{img_url}")
                                    break
                                page.keyboard.press("ArrowRight")
                                page.wait_for_timeout(500)
                                popup_img_el = frame.query_selector("div.cpv__img_wrap img.cpv__img")
                                if popup_img_el:
                                    popup_img = popup_img_el

                            if not found:
                                helper.debug_print(f"序號 {num} 補回失敗：carousel 導航未找到")
                                errors.append(f"序號 {num} 圖片無法成功擷取")
                    else:
                        helper.debug_print("序號補回：無法開啟彈窗")

                    page.keyboard.press("Escape")
                    _wait_popup_closed(frame, page)

                except Exception as e:
                    error_msg = str(e)
                    if "closed" not in error_msg.lower():
                        helper.debug_print(f"序號補回錯誤: {error_msg}")
                    try:
                        page.keyboard.press("Escape")
                        _wait_popup_closed(frame, page)
                    except Exception:
                        pass

                # 有新增圖片，重新去重 + 排序
                img_urls = _dedup_urls(img_urls)
                img_urls = _sort_urls_by_number(img_urls)
            else:
                helper.debug_print("序號完整性驗證通過，無缺漏")

            browser.close()

        # 根據最終序號缺漏計算實際失敗數量
        final_numbers = set()
        for url in img_urls:
            m = re.search(r"_(\d+)\.(jpg|jpeg|png|gif)", url)
            if m:
                final_numbers.add(int(m.group(1)))
        if final_numbers:
            expected_total = max(max(final_numbers), len(img_elements))
            actual_failures = len(set(range(1, expected_total + 1)) - final_numbers)
        else:
            expected_total = len(img_elements)
            actual_failures = expected_total

        elapsed = helper.calculate_elapsed_time(start_time)
        return DownloadResult(
            total_images=expected_total,
            successful_downloads=len(img_urls),
            failure_downloads=actual_failures,
            image_urls=img_urls,
            errors=errors,
            elapsed_time=elapsed,
        )

    except Exception as e:
        elapsed = helper.calculate_elapsed_time(start_time)
        return DownloadResult(0, 0, 0, [], [str(e)], elapsed)


def _parse_request_body(event) -> dict:
    """解析 API Gateway 或 Lambda 直接呼叫的 event，回傳 body dict

    支援三種輸入格式：JSON 字串、含 body 欄位的 API Gateway event、純 dict。

    Args:
        event: Lambda event，可能是 str、dict 或含 body 的 API Gateway 格式

    Returns:
        解析後的請求 body dict
    """
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
    """處理下載請求：建立 S3 任務 → 非同步呼叫 worker → 回傳 job_id

    Args:
        body (dict): 請求內容，需包含 blog_url
        context: Lambda context，用於取得 function_name 進行非同步自呼叫

    Returns:
        API Gateway 回應 dict（HTTP 202 含 job_id，或 400 錯誤）
    """
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
    """查詢任務狀態與結果

    Args:
        body (dict): 請求內容，需包含 job_id

    Returns:
        API Gateway 回應 dict（HTTP 200/404/500 含任務狀態）
    """
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
    status_code = 500 if job["status"] == JobStatus.FAILED else 200
    response = build_response(status_code, response_body)
    helper.debug_print(f"Response: {response}")
    return response


def _handle_async_worker(event):
    """背景 worker：執行 Playwright 爬取圖片，結果與 log 寫入 S3

    由 _handle_submit 透過 Lambda 非同步呼叫觸發。
    無論成功或失敗，最終都會將 debug log 儲存至 S3。

    Args:
        event (dict): 包含 job_id 與 blog_url 的 worker 事件
    """
    job_id = event["job_id"]
    blog_url = event["blog_url"]
    helper.clear_logs()
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
    finally:
        log_store.save_logs(job_id, helper.get_logs())


def lambda_handler(event, context):
    """Lambda 入口點：根據 event 路由至 submit、status 或 async worker

    Args:
        event: Lambda event（API Gateway 請求或非同步 worker 呼叫）
        context: Lambda context
    """
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
