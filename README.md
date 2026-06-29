# 提单识别 EDI 工作台

本项目是一个面向海运物流提单识别的本地 MVP：上传 PDF 或图片形式的提单，抽取文本，解析关键字段，并生成结构化 JSON 与 EDIFACT IFTMCS 风格 EDI 草稿。

## 功能

- 多模态大模型识别：上传 PDF/图片后可渲染页面并调用 OpenAI 视觉模型抽取结构化 JSON
- 未配置 API Key 或模型调用失败时，自动回退到本地规则/模板识别
- 上传文本型 PDF 自动抽取提单文本
- 粘贴 OCR 文本或人工录入提单内容
- 识别提单号、订舱号、发货人、收货人、通知方、船名航次、起运港、目的港、箱号、封号、件重尺、运费条款、货描
- 输出结构化 JSON、Flat EDI、EDIFACT IFTMCS 风格报文
- 识别完整度和缺失字段提示
- 图片 OCR 为可插拔能力：安装 Tesseract 与 pytesseract 后自动启用

## 启动

```powershell
pip install -r requirements.txt
python app.py
```

浏览器打开：

```text
http://127.0.0.1:5000
```

## 多模态识别

复制 `.env.example` 为 `.env`，填入 API Key、模型和接口地址：

```powershell
copy .env.example .env
```

编辑 `.env`：

```text
VISION_PROVIDER=openai
VISION_API_KEY=sk-your-api-key
VISION_MODEL=gpt-4.1
VISION_API_STYLE=responses
```

第三方 OpenAI-compatible 服务通常需要额外配置：

```text
VISION_PROVIDER=mimo
VISION_API_KEY=sk-your-provider-key
VISION_BASE_URL=https://api.provider.example/v1
VISION_MODEL=your-vision-model
VISION_API_STYLE=chat
```

配置后重启应用。上传 PDF 或图片时，只有勾选页面上的“使用视觉模型识别”选项，系统才会把文件页面图像发送到配置的模型服务识别；不勾选时仅使用本地规则/模板识别。

如果未配置 Key、网络失败或模型调用失败，会自动回退到本地规则识别，并在页面警告中说明原因。

当前本地规则仍保留，用于：

- API 不可用时兜底
- 已知模板快速解析
- 对模型结果做后续校验和格式化

## 图片 OCR

当前环境若没有 Tesseract，图片上传会返回提示。安装后可启用图片 OCR：

```powershell
pip install pytesseract
```

同时需要安装 Tesseract OCR 程序，并确保 `tesseract` 在系统 PATH 中。

## 后续增强方向

- 接入企业 OCR 服务或大模型视觉识别，提升扫描件、盖章件、低清图片识别率
- 建立船司模板库，按 COSCO、MSK、MSC、ONE 等格式做字段定位
- 增加人工校对队列、字段置信度、导出 Excel/API/Webhook
- 按目标系统扩展 ANSI X12、CargoWise、INTTRA、海关舱单等 EDI 映射
