# 第三方与许可证提示

本目录的新核心代码没有复制现有模型仓库实现；真实模型当前全部禁用。

只读 `deployment.json` 显示的重点风险：

- VoxCPM2、Qwen3-TTS、CosyVoice：Apache-2.0；仍需核对具体模型权重与声音数据授权。
- GPT-SoVITS、RVC：清单标为 MIT；需要继续审计依赖、权重和训练数据。
- Seed-VC：GPL-3.0。后续只考虑独立进程边界并在分发前完成许可证审查，不复制其代码进核心。
- IndexTTS2：模型自有许可；默认 MaskGCT 依赖包含 CC BY-NC 4.0，未获额外许可时不得用于商业成片。
- FFmpeg/imageio-ffmpeg：后续分发时应按实际构建配置维护 LGPL/GPL notice。

所有声音参考、克隆、转换、训练与发布必须保存明确授权元数据。`validated_static` 只表示静态检查，不等于商业许可或运行时质量验收。
