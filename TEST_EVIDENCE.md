# 轻量验证记录

在独立、无模型权重的发布副本中执行：

| 检查 | 结果 |
|---|---|
| `cd backend && python -B -m unittest discover -s tests -v` | 61/61 通过 |
| `python -B -m unittest discover -s adapters\tests -v` | 46/46 通过 |
| `cd frontend && npm run test` | 43/43 通过，12 个测试文件 |
| `cd frontend && npm run build` | TypeScript 与 Vite 构建通过 |

测试使用临时数据库、合成音频和 Mock 组件，不启动或下载大型模型。构建有一个 Vite 大 chunk 提示（懒加载 Three.js），不是失败。浏览器端真实麦克风、外部模型和商业许可没有在此记录中宣称验收。

新增回归覆盖静音会话在 ASR/教师/TTS 前返回重录错误、不写入轮次或示范音；HTTP 上传后用 `recording_id` 提交静音轮次返回 400。仅活动检测模式跳过 F0 提取，原有跟读评分仍计算 F0。

项目课程新增 TTS 第二条失败、数据库第二条练习插入后失败和用户已有参考音保留三项回归；失败后无新 session/exercise，生成的参考 WAV 被清理。
