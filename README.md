# Bestdori 背景图批量下载器 (Bestdori BG Image Downloader) 🎸

Bestdori 场景背景图下载工具。

## 主要功能

本工具用来批量下载 [Bestdori](https://bestdori.com) 数据站中的 BanG Dream! 背景图（scenario）。

| 功能 | 说明 |
| :--- | :--- |
| **异步批量下载** | 采用 `aiohttp` + `asyncio`，并发下载。 |
| **GUI页面** | 简单易用的图形化界面。 |

## 技术栈

- **Python 3.10+**
- **Playwright**: 动态渲染网页并提取图片资源链接。
- **aiohttp**: 异步网络请求。
- **customtkinter**: 构建GUI界面。

## 安装与环境配置

建议使用 Python 虚拟环境来运行本项目，避免依赖冲突。

### 1. 克隆项目

```bash
git clone https://github.com/Yulinanami/Bestdori_BG_ImgDownload
cd Bestdori_BG_ImgDownload
```

### 2. 创建并激活虚拟环境

```bash
# 创建虚拟环境
python -m venv .venv
# 或
python3 -m venv .venv

# 激活虚拟环境 (Windows)
.\.venv\Scripts\activate

# 激活虚拟环境 (macOS/Linux)
source .venv/bin/activate
```

### 3. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 4. 安装 Playwright 浏览器内核

使用 Playwright 模拟浏览器行为进行扫描，需要安装内核：

```bash
python -m playwright install chromium
```

### 5. 启动程序

在终端中运行命令启动 GUI 界面：

```bash
python main.py
```

### 界面功能说明

1.  **保存目录**
    *   点击“选择…”设置图片下载的存放路径（默认为当前目录下的 `bestdori_scenarios`）。

2.  **下载速度（并发数）**
    *   设置同时下载的图片数量。
    *   *注意：数值越大下载越快，但会对 Bestdori 服务器造成更大压力，请适度设置。*

3.  **每批扫描 Scenario 数**
    *   设置扫描器每扫描多少个 Scenario 文件夹就进行一次批量下载任务。
    *   **默认值**：`20`。

## 注意事项

1.  **服务器负载**：请**不要**将并发数设置得过高，以免对服务器造成攻击行为。
2.  **网络问题**：如果遇到下载失败，建议检查网络连接或稍后重试。

## 📄 许可证

MIT License
