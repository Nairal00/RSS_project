# RSS AI News Digest

一个面向技术资讯场景的智能内容筛选工具，帮助你在海量 RSS 信息中快速发现真正值得关注的新闻、更新和趋势。

它会自动抓取多个 RSS 源，过滤低价值内容，提取文章正文，并结合 DeepSeek AI 对每篇文章进行摘要和评分，然后生成一份精致的 HTML 新闻摘要，帮助你高效浏览和决策。

---

## 产品价值

在信息过载的今天，内容筛选往往比“获取信息”更重要。RSS AI News Digest 的目标，是让你从“被动看新闻”升级为“主动筛选关键信息”。

### 你能获得的价值

- 按时间窗口快速聚合多个信息源
- 自动识别低价值与高价值文章
- 摘要复杂文章，减少阅读负担
- 按 AI 评分排序，优先看最重要的新闻
- 生成美观可分享的每日新闻摘要页面
- 适合技术团队、研究人员和内容运营人员使用

---

## 核心功能

- 多源 RSS 聚合：支持同时订阅多个 RSS/Atom 来源
- 智能时间过滤：仅保留最近一段时间内的内容
- 正文提取：从文章链接中抽取干净正文，去除噪音
- AI 评分：利用 DeepSeek 对文章做 0/1 价值判断
- 自动总结：输出简洁、可读的英文摘要
- 本地 HTML 摘要：生成结构化的 digest.html 页面
- 自动打开浏览器：生成后立即展示结果
- 安全防护：包含 URL 校验、SSRF 防护、XSS 过滤和异常处理

---

## 使用场景

### 1. 技术资讯监控

适合关注 AI、工程实践、产品动态、创业信息等内容的用户。每天只看最值得看的新闻，而不是被大量重复信息淹没。

### 2. 研究与趋势追踪

帮助研究者和 PM 快速关注行业变化，减少人工筛选成本，并在短时间内形成对关键趋势的判断。

### 3. 日报、简报和内容整理

生成稳定的 Daily Digest，便于团队内部分享、复盘和汇总。

---

## 产品体验

程序运行后，会自动完成以下工作：

1. 读取 RSS 配置源
2. 按时间范围拉取文章
3. 校验链接和发布时间
4. 抽取正文内容
5. 调用 AI 模型进行总结和评分
6. 依次展示高价值内容
7. 生成 HTML 摘要并在浏览器中打开

最终效果类似于：

- 一份结构化的数字化资讯简报
- 只保留高价值内容的精选版新闻
- 自动生成的每日更新页面，便于查看和复用

---

## 快速开始

### 环境要求

- Python 3.9+
- 可访问网络
- DeepSeek API Key

### 安装

```bash
git clone <your-repo-url>
cd RSS_project
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 配置 RSS 源

编辑 `feeds.txt`，每行一条源，推荐使用 `名称=URL` 形式：

```text
tech=https://example.com/feed.xml
ai=https://example.com/ai.xml
```

### 配置 API Key

在项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key_here
```

### 运行

```bash
python main.py
```

运行完成后，程序会在本地生成 `digest.html`，并自动用默认浏览器打开。

---

## 架构概览

```text
RSS_project/
├── main.py                 # 程序入口
├── config.py               # 全局配置
├── feed_fetcher.py         # RSS 拉取与解析
├── content_extractor.py    # 正文抽取
├── summarizer.py           # DeepSeek 调用与评分
├── pipeline.py             # 流程编排
├── html_generator.py       # HTML 生成
├── validators.py           # 安全校验
├── models.py               # 数据模型
├── feeds.txt               # RSS 源配置
├── digest.html             # 生成结果
├── requirements.txt        # 依赖清单
├── tests/                  # 单元测试
├── README.md               # 项目说明
├── Dockerfile              # 容器配置
└── plan.md                # 开发计划
```

---

## 安全与稳定性

产品设计中重点考虑了可靠性与安全性：

- SSRF 防护：避免访问私有 IP 或保留地址
- URL 校验：统一校验 HTTP/HTTPS scheme
- 控制字符过滤：防止异常请求参数带来注入风险
- XSS 防护：对输出到 HTML 的内容做转义处理
- JSON 校验：确保模型返回结构稳定可靠
- API 密钥脱敏：避免敏感信息泄漏到日志

---

## 开发与测试

### 运行测试

```bash
pytest
```

### 查看覆盖率

```bash
pytest --cov=. --cov-report=html
```

### 代码检查

```bash
flake8 .
pylint .
```

---

## 常见问题

### 为什么没有生成结果？

请确认：

- `feeds.txt` 是否存在且格式正确
- RSS 源是否可访问
- 网络是否正常
- 文章是否落在时间窗口内

### DeepSeek API Key 报错

请检查 `.env` 文件中是否存在：

```env
DEEPSEEK_API_KEY=your_api_key_here
```

### 为什么部分文章被跳过？

通常是因为以下原因：

- 无效链接
- RSS 时间字段缺失
- 正文提取失败
- AI 返回内容格式异常

这些信息会在最终 HTML 中的错误区域展示。

---

## 依赖列表

```text
feedparser==6.0.12
requests==2.34.2
python-dotenv==1.2.2
pytest==9.0.3
pytest-cov==7.1.0
flake8==7.3.0
pylint==4.0.5
openai
```

---

## 许可证

本项目目前未附带单独许可证声明，使用前请根据实际场景确认授权和发布要求。

---

## 结论

RSS AI News Digest 是一个以“信息筛选 + AI 摘要 + 结构化展示”为核心的智能资讯工具。它不仅能帮助你快速聚合新闻，还能把噪声过滤掉，把真正有价值的内容按优先级呈现出来，适合技术团队、研究者和内容运营人员使用。

本项目目前未附带特定许可证声明，使用前请根据实际部署场景确认授权要求。


---

## 相关资源

- DeepSeek API: https://platform.deepseek.com/
- OpenAI Python SDK: https://github.com/openai/openai-python
- feedparser: https://feedparser.readthedocs.io/
- Jina Reader: https://jina.ai/
