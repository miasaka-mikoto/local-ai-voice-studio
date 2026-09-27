# Local AI Voice Studio

一个面向 Windows 本机的开源语音制作与日语口语练习工作台。当前版本是可运行的轻量 MVP：FastAPI + SQLite 后端、React + TypeScript 前端、统一引擎能力注册表，以及无需模型权重即可验证流程的确定性 Mock 引擎。

项目覆盖四类工作区：视频/动画配音、游戏台词、角色声音管理、日语口语训练。现阶段可以持久化项目、导入和编辑台词、映射角色/声音、生成并选择 Mock 多 take、恢复任务和导出清单。日语模块包含会话录音、半双工教师接口、错句修复、影子跟读、复习记录与分项证据反馈。Mock 音频和启发式反馈都不代表真实语音质量或绝对发音准确度。

## 快速开始

在仓库根目录安装轻量依赖：

```cmd
python -m pip install -r backend\requirements.txt
cd frontend
npm ci
```

分别打开两个终端，均从仓库根目录运行：

```cmd
cd backend
python -B -m app.main --host 127.0.0.1 --port 8766
```

```cmd
cd frontend
npm run dev
```

浏览器打开 <http://127.0.0.1:5173>，API 文档在 <http://127.0.0.1:8766/docs>。默认仅绑定本机回环地址。前端 `auto` 模式会尝试本地 API；连接失败时明确提示并进入浏览器 Mock。也可复制 `frontend/.env.example` 为不提交的 `frontend/.env.local` 选择 `api` 或 `mock`。仓库不会启动、下载或训练大型模型，也不会控制已有的其他服务。

Windows 启动脚本见 `backend/start_backend.ps1` 与 `frontend/start_frontend.ps1`；端口被占用时会退出，不会停止占用进程。

## 可选的真实组件

本仓库不附带模型权重、声音、用户录音或私有部署清单。要使用本机已有组件，可自行配置环境变量：`VOICE_STUDIO_FFMPEG` 指向 FFmpeg 可执行文件（浏览器 WebM/Opus 上传所需）；`VOICE_STUDIO_JP_ASR_COMMAND_JSON` 和 `VOICE_STUDIO_JP_TTS_COMMAND_JSON` 指向隔离的本机命令；`VOICE_STUDIO_TEACHER_BASE_URL`、`VOICE_STUDIO_TEACHER_MODEL`、`VOICE_STUDIO_TEACHER_API_KEY` 配置 OpenAI 兼容教师；`VOICE_STUDIO_QWTTS_MANIFEST` 可选导入外部能力清单。密钥只从环境变量读取，不写入仓库。

未经许可的声音克隆、模型权重和第三方角色素材不在发布范围。前端默认伙伴是原创 CSS 形象；VRM 只从用户主动选择的本机文件加载，且先要求确认授权。四张场景 WebP 为本项目生成的原创环境插画。

## 日语录音与评分契约

浏览器把原始 Blob 以 raw body 上传至 `POST /api/japanese/recordings?session_id=...&filename=...`，并保留实际 `Content-Type`。响应的 `recording_id` 是后续会话轮次和影子跟读提交的唯一录音引用；客户端不提交文件路径或自报 `source_kind`。后端用不可变来源记录核验 session、上传入口、文件大小和 SHA-256；所有评分只看染色前的原录音。静音或活动帧不足时分项值为空、置信度为零，提示重录；转写提示不能绕过语音证据。反馈分为内容、节奏与 F0，含证据、局限和置信度，不生成伪精确总分。

## 验证与边界

```cmd
cd backend
python -B -m unittest discover -s tests -v
cd ..
python -B -m unittest discover -s adapters\tests -v
cd frontend
npm run test
npm run build
```

当前验证结果见 [TEST_EVIDENCE.md](TEST_EVIDENCE.md)。真实模型推理、训练、视频分离/混音、商业授权放行与桌面打包仍未完成。代码采用 MIT 许可证；第三方依赖和用户自备资源的许可分别见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
