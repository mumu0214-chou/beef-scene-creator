# 实况图制作器 Windows 版

批量把图片或视频转换为 Apple 实况照片使用的一对 HEIC 和 MOV 文件。支持拖入多个素材或文件夹，同批素材输出到一个新文件夹。

- 图片：中央 3:4 取景，范围 45%–95%，可调整运动幅度，提供左旋和右旋两种手持轨迹。
- 视频：选择起点、0.5–3 秒片段和封面，短视频自动缩短；中央裁切为 3:4，并保留原声。
- 每组文件需要一起导入 Apple 照片，导入后查看是否显示“实况”。输出的视频为 1080 × 1440；图片封面根据原图裁切后的实际像素保存。

## Windows 使用

从本仓库的 Releases 下载最新版 `LivePhotoMaker.exe`，双击运行。选择素材和输出位置，点击“开始批量制作”。Windows 可能对没有数字签名的程序显示安全提示。批量处理完成后，可通过“打开结果文件夹”查看 HEIC / MOV；不要只传其中一个。

## 从源码运行

需要 Windows 和 Python 3.11 或 3.12：

```powershell
cd windows-live-photo
py -m pip install -r requirements.txt
py app.py
```

GitHub Actions 在 Windows 环境运行转换测试并构建程序；源码中不包含个人照片或视频。实际 Apple 设备导入体验取决于导入方式和系统版本。
