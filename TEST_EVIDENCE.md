# 轻量验证记录

在独立、无模型权重的发布副本中执行：

| 检查 | 结果 |
|---|---|
| `cd backend && python -B -m unittest discover -s tests -v` | 55/55 通过 |
| `python -B -m unittest discover -s adapters\tests -v` | 46/46 通过 |
| `cd frontend && npm run test` | 43/43 通过，12 个测试文件 |
| `cd frontend && npm run build` | TypeScript 与 Vite 构建通过 |

测试使用临时数据库、合成音频和 Mock 组件，不启动或下载大型模型。构建有一个 Vite 大 chunk 提示（懒加载 Three.js），不是失败。浏览器端真实麦克风、外部模型和商业许可没有在此记录中宣称验收。
