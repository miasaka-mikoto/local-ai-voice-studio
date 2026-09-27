# 日语口语训练模块

本模块由核心 FastAPI 应用挂载在 `/api/japanese`。无需模型权重即可用 Mock 后备完成 learner、session、recording、turn、shadowing、review 和学习路径流程。外部 ASR、TTS、OpenAI 兼容教师均为可选适配器，配置只读取环境变量，不把密钥写入数据库、响应或日志。

## 原录音契约

`POST /api/japanese/recordings?session_id=...&filename=...` 接收 raw 音频字节，保存规范化的单声道 48 kHz PCM-24 WAV，并登记不可变 `recording_id`、来源、上传入口、SHA-256 与字节数。浏览器 WebM/Opus 等格式需要本机 FFmpeg（PATH 或 `VOICE_STUDIO_FFMPEG`）；目标格式 WAV 可直接提交。会话轮次和影子跟读只接收 `recording_id`，不接受客户端声称的原录音路径或来源类型。服务在评分前重新核验 session 归属、上传来源和文件完整性。

每轮会话的序号、turn 与复习项在 SQLite `BEGIN IMMEDIATE` 事务中原子提交；失败会清理未引用的示范音频。影子跟读 A/B 分别保留学习者原录音与参考音路径；评分只基于染色前原录音。

情景会话提交轮次时先检查原录音 RMS 与活动帧比例，静音会在 ASR、教师和 TTS 调用前被拒绝，不会形成 turn、复习项或示范音，也不能凑课程完成轮数；客户端应提示检查麦克风并重录。

项目台词转课程先验证输入和已有参考音，再生成缺少的参考音；session 与全部练习在同一 SQLite 事务提交。TTS 或数据库失败时回滚并清理本次生成的音频，保留用户原有参考音。

## 反馈边界

内容、节奏与 F0 各自返回 value、confidence、summary、evidence 和 limitations，没有单一总分。mora 分段是近似启发式提示，不宣称经过标定的发音准确度。静音或语音活动不足时相关值为 `null`、置信度为 `0`，并要求重录；`transcript_hint` 不能绕过音频证据。错句修复给出原句、最小修改、自然表达与重说提示，复习队列可导出 AnkiConnect 载荷，但不会自动调用本机 Anki。

## 本机验证

在 `backend` 目录执行 `python -B -m unittest discover -s tests -v`。测试使用合成小波形和临时数据库；不会启动、训练或下载大型模型。
