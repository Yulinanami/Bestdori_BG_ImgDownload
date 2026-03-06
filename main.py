import asyncio
import time
import aiohttp
from pathlib import Path
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


BASE_URL = "https://bestdori.com/assets/jp/bg"
# 缺失图片的响应内容大小通常固定14,084 bytes
KNOWN_PLACEHOLDER_SIZES = {14084}

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=90, connect=15)
MAX_RETRIES = 5
RETRY_FAILED_ROUNDS = 5
CHUNK_SIZE = 64 * 1024
PROGRESS_BAR_WIDTH = 24
console = Console()


def create_progress(phase_style: str, bar_style: str) -> Progress:
    """创建带阶段颜色的统一进度条样式。"""
    return Progress(
        TextColumn("{task.description}", style=phase_style),
        BarColumn(
            bar_width=PROGRESS_BAR_WIDTH,
            complete_style=bar_style,
            finished_style=bar_style,
            pulse_style=bar_style,
        ),
        TaskProgressColumn(),
        TextColumn("| 已完成 {task.completed}/{task.total}"),
        TextColumn("| 下载 {task.fields[downloaded]}"),
        TextColumn(
            "| 跳过 {task.fields[skipped]} (空图 {task.fields[skip_placeholder]} | 已存在 {task.fields[skip_existing]})"
        ),
        TextColumn("| 失败 {task.fields[failed]}"),
        TextColumn("|"),
        TimeElapsedColumn(),
        TextColumn("|"),
        TimeRemainingColumn(),
        console=console,
    )


def build_filename(scenario_number: int, last_digit: int) -> str:
    """生成背景图文件名。"""
    scen_str = f"{scenario_number:03d}"
    return f"bg0{scen_str}{last_digit}.png"


def build_url(scenario_number: int, filename: str) -> str:
    """生成背景图下载地址。"""
    scen_name = f"scenario{scenario_number}"
    return f"{BASE_URL}/{scen_name}_rip/{filename}"


def get_save_dir(
    output_root: Path,
    scenario_number: int,
    split_by_scenario: bool,
) -> Path:
    """返回当前文件的保存目录。"""
    if split_by_scenario:
        return output_root / f"scenario{scenario_number}"
    return output_root


def ensure_save_dir(
    save_dir: Path,
    scenario_number: int,
    split_by_scenario: bool,
    prepared_scenarios: set[int],
):
    """按需创建场景目录并缓存。"""
    if not split_by_scenario:
        return
    if scenario_number in prepared_scenarios:
        return
    save_dir.mkdir(parents=True, exist_ok=True)
    prepared_scenarios.add(scenario_number)


async def download_one(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    scenario_number: int,
    last_digit: int,
    output_root: Path,
    split_by_scenario: bool,
    prepared_scenarios: set[int],
) -> dict[str, object]:
    """下载单个文件并返回结果。"""
    filename = build_filename(scenario_number, last_digit)
    url = build_url(scenario_number, filename)
    save_dir = get_save_dir(output_root, scenario_number, split_by_scenario)
    save_path = save_dir / filename
    temp_path = save_dir / f"{filename}.tmp"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 小的等待抖动，降低瞬时并发对服务器的压力
            await asyncio.sleep(0.2 * attempt)
            async with sem:
                async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientResponseError(
                            resp.request_info, resp.history, status=resp.status
                        )

                    remote_size = resp.content_length
                    if remote_size in KNOWN_PLACEHOLDER_SIZES:
                        return {"status": "skip", "skip_reason": "placeholder"}

                    if save_path.exists() and remote_size is not None:
                        local_size = save_path.stat().st_size
                        if local_size > 0 and local_size == remote_size:
                            return {"status": "skip", "skip_reason": "existing"}

                    ensure_save_dir(
                        save_dir,
                        scenario_number,
                        split_by_scenario,
                        prepared_scenarios,
                    )

                    temp_path.unlink(missing_ok=True)
                    downloaded_size = 0
                    with open(temp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded_size += len(chunk)

                    if downloaded_size in KNOWN_PLACEHOLDER_SIZES:
                        temp_path.unlink(missing_ok=True)
                        return {"status": "skip", "skip_reason": "placeholder"}

                    temp_path.replace(save_path)
                    return {"status": "downloaded"}
        except Exception as e:
            temp_path.unlink(missing_ok=True)
            if attempt >= MAX_RETRIES:
                return {
                    "status": "failed",
                    "scenario_number": scenario_number,
                    "last_digit": last_digit,
                    "filename": filename,
                    "error": str(e),
                }
            await asyncio.sleep(1.5 * attempt)


async def retry_failed_files(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    failed_files,
    output: Path,
    split_by_scenario: bool,
    prepared_scenarios: set[int],
):
    """统一重试失败文件。"""
    remaining_files = failed_files
    retried_success = 0
    retried_skip_placeholder = 0
    retried_skip_existing = 0

    for round_index in range(1, RETRY_FAILED_ROUNDS + 1):
        if not remaining_files:
            break

        retry_tasks = [
            download_one(
                session,
                sem,
                item["scenario_number"],
                item["last_digit"],
                output,
                split_by_scenario,
                prepared_scenarios,
            )
            for item in remaining_files
        ]

        total = len(retry_tasks)
        round_success = 0
        round_failed = 0
        round_skipped = 0
        round_skip_placeholder = 0
        round_skip_existing = 0
        next_failed_files = []

        with create_progress("bold yellow", "yellow") as progress:
            task_id = progress.add_task(
                f"补重试 {round_index}/{RETRY_FAILED_ROUNDS}",
                total=total,
                downloaded=round_success,
                skipped=round_skipped,
                skip_placeholder=round_skip_placeholder,
                skip_existing=round_skip_existing,
                failed=round_failed,
            )

            for coro in asyncio.as_completed(retry_tasks):
                result = await coro
                if result["status"] == "downloaded":
                    round_success += 1
                    retried_success += 1
                elif result["status"] == "skip":
                    round_skipped += 1
                    if result["skip_reason"] == "placeholder":
                        round_skip_placeholder += 1
                        retried_skip_placeholder += 1
                    else:
                        round_skip_existing += 1
                        retried_skip_existing += 1
                else:
                    round_failed += 1
                    next_failed_files.append(result)

                progress.update(
                    task_id,
                    advance=1,
                    downloaded=round_success,
                    skipped=round_skipped,
                    skip_placeholder=round_skip_placeholder,
                    skip_existing=round_skip_existing,
                    failed=round_failed,
                )

        remaining_files = next_failed_files

    return (
        retried_success,
        retried_skip_placeholder,
        retried_skip_existing,
        remaining_files,
    )


async def download_batch(
    scenarios,
    last_digits,
    output: Path,
    concurrency: int,
    split_by_scenario: bool,
):
    """执行整批下载并汇总结果。"""
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(
        connector=connector, timeout=REQUEST_TIMEOUT
    ) as session:
        sem = asyncio.Semaphore(concurrency)
        prepared_scenarios: set[int] = set()
        tasks = []
        for scen in scenarios:
            for d in last_digits:
                tasks.append(
                    download_one(
                        session,
                        sem,
                        scen,
                        d,
                        output,
                        split_by_scenario,
                        prepared_scenarios,
                    )
                )

        total = len(tasks)
        success = 0
        skipped = 0
        skipped_placeholder = 0
        skipped_existing = 0
        failed = 0
        failed_files = []

        with create_progress("bold cyan", "cyan") as progress:
            task_id = progress.add_task(
                "进度",
                total=total,
                downloaded=success,
                skipped=skipped,
                skip_placeholder=skipped_placeholder,
                skip_existing=skipped_existing,
                failed=failed,
            )

            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result["status"] == "skip":
                    skipped += 1
                    if result["skip_reason"] == "placeholder":
                        skipped_placeholder += 1
                    else:
                        skipped_existing += 1
                elif result["status"] == "downloaded":
                    success += 1
                else:
                    failed += 1
                    failed_files.append(result)

                progress.update(
                    task_id,
                    advance=1,
                    downloaded=success,
                    skipped=skipped,
                    skip_placeholder=skipped_placeholder,
                    skip_existing=skipped_existing,
                    failed=failed,
                )

        if failed_files:
            console.print("\n开始统一重试失败文件...")
            (
                retried_success,
                retried_skip_placeholder,
                retried_skip_existing,
                failed_files,
            ) = await retry_failed_files(
                session,
                sem,
                failed_files,
                output,
                split_by_scenario,
                prepared_scenarios,
            )
            success += retried_success
            skipped_placeholder += retried_skip_placeholder
            skipped_existing += retried_skip_existing
            skipped = skipped_placeholder + skipped_existing
            failed = len(failed_files)

    effective_total = total - skipped
    return (
        success,
        effective_total,
        skipped,
        failed,
        failed_files,
        skipped_placeholder,
        skipped_existing,
    )


def prompt_range(default_start: int, default_end: int) -> tuple[int, int]:
    """交互式获取起止编号。"""

    def _read(prompt: str, default_val: int) -> int:
        """读取一个场景编号输入。"""
        raw = input(prompt).strip()
        if not raw:
            return default_val
        try:
            val = int(raw)
            if val < 0:
                raise ValueError
            return val
        except ValueError:
            console.print(f"输入无效，使用默认值 {default_val}")
            return default_val

    start = _read(f"请输入起始 scenario 编号（默认 {default_start}）: ", default_start)
    end = _read(f"请输入结束 scenario 编号（默认 {default_end}）: ", default_end)

    if start > end:
        start, end = end, start
        console.print(f"起始大于结束，已交换为 {start} - {end}")

    return start, end


def main():
    """运行命令行主流程。"""
    default_start = 0
    default_end = 391
    default_output = "./bg_downloads"
    concurrency = 12

    console.print("按命名规则下载 Bestdori scenario 背景图（无需扫描网页）")
    console.print("默认起止为 0-391，/可按提示输入覆盖。")
    console.print(f"已启用占位过滤：长度 {sorted(KNOWN_PLACEHOLDER_SIZES)} bytes。")

    start, end = prompt_range(default_start, default_end)
    scenarios = range(start, end + 1)
    choice = input("按 scenario 分目录保存? (默认关闭，输入Y/y开启): ").strip().lower()
    split_by_scenario = choice == "y"

    output_input = input(f"请输入输出目录（默认 {default_output}）: ").strip()
    output_path = output_input or default_output
    output = Path(output_path).resolve()
    output.mkdir(parents=True, exist_ok=True)

    last_digits = range(10)

    console.print(f"准备下载 scenario {scenarios}，每个尝试文件 bg0###(0-9).png")
    console.print(f"输出目录: {output}")
    console.print(f"并发: {concurrency}，按 scenario 分目录: {split_by_scenario}\n")
    console.print("开始下载...\n")

    start_time = time.time()
    (
        success,
        total,
        skipped,
        failed,
        failed_files,
        skipped_placeholder,
        skipped_existing,
    ) = asyncio.run(
        download_batch(
            scenarios,
            last_digits,
            output,
            concurrency,
            split_by_scenario,
        )
    )
    elapsed = time.time() - start_time

    console.print("\n下载完成")
    console.print(f"耗时: {elapsed:.1f}s")
    console.print(f"成功下载: {success}")
    console.print(
        f"已跳过: {skipped} (空图 {skipped_placeholder} | 已存在 {skipped_existing})"
    )
    console.print(f"下载失败: {failed}")

    if failed_files:
        console.print("\n失败文件列表:")
        for item in failed_files:
            console.print(f"  - {item['filename']}: {item['error']}")


if __name__ == "__main__":
    main()
