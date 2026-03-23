# Image Tagging Windows

[![Build](https://github.com/HDYA/image-tagging-windows/actions/workflows/build.yml/badge.svg)](https://github.com/HDYA/image-tagging-windows/actions)

十万级照片/视频自动分组、拼音标注匹配、可选本地人脸识别的桌面分类工具。

## 功能特性

- **时间分组**: 按文件时间戳自动分组（相邻≤10秒归为同组）
- **可配置排序优先级**: 时间戳来源(EXIF/mtime/ctime/文件名)顺序通过配置文件或GUI自由调整
- **拼音标注匹配**: 自动识别文件名中的中文拼音/缩写标注，与类别库匹配
- **智能类别搜索**: 中文子字符串/拼音全拼/首字母缩写/英文数字混合搜索，推荐结果置顶
- **冲突检测**: 自动发现拼音缩写冲突，支持人工消歧
- **本地人脸识别** (可选): 基于 InsightFace，支持 AMD 7900XTX (DirectML)，完全离线
- **双模式**: GUI 桌面客户端 + CLI 命令行
- **多格式导出**: JSON / CSV / PowerShell 脚本 / Batch 脚本
- **离线友好**: 支持手动导入类别列表，无需联网

## 系统要求

| 项目 | 最低要求 |
|------|---------|
| OS | Windows 10/11 (AMD64 或 ARM64) |
| Python | 3.11+ |
| 内存 | 4GB (无人脸) / 8GB (有人脸) |
| GPU | 可选: AMD 7900XTX (DirectML) |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 可选: 人脸识别
pip install -r requirements-face.txt
pip install onnxruntime-directml    # AMD GPU (Windows)
```

### 2. 运行

```bash
# GUI 模式
python main.py

# CLI 模式
python cli.py --db project.db categories --archive "D:\Archive\Photos"
python cli.py --db project.db scan --source "D:\DCIM"
python cli.py --db project.db classify
python cli.py --db project.db stats
python cli.py --db project.db export --format json --output result.json --archive-root "D:\Archive\Photos"
```

## 项目结构

```
image-tagging-windows/
├── main.py              # GUI 入口
├── cli.py               # CLI 入口
├── core/
│   ├── config.py        # 配置
│   ├── models.py        # 数据模型
│   ├── database.py      # SQLite
│   ├── scanner.py       # 文件扫描 + 时间分组
│   ├── category_tree.py # 类别树 + 拼音索引
│   ├── classifier.py    # 三级分类调度器
│   ├── face_engine.py   # 人脸识别 (可选)
│   └── exporter.py      # 导出模块
├── ui/
│   ├── main_window.py   # 主窗口
│   ├── category_panel.py # 类别树面板
│   ├── category_selector.py # 智能类别搜索选择器
│   ├── group_panel.py   # 分组列表
│   └── review_panel.py  # 审核面板
├── scripts/
│   ├── build_amd64.bat  # AMD64 构建
│   ├── build_arm64.bat  # ARM64 构建
│   └── build.sh         # 跨平台构建
├── examples/
│   ├── categories_example.txt
│   ├── config_default.json
│   ├── config_mtime_first.json
│   └── config_filename_first.json
├── .github/workflows/
│   └── build.yml        # CI/CD
├── .gitignore
├── requirements.txt
└── requirements-face.txt
```

## License

MIT
