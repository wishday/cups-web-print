---
<span id="中文版"></span>

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-GPLv3-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

**[🇨🇳 中文版](#中文版)** | **[🇺🇸 English Version](#english-version)**

# Web 打印服务

基于 Python Flask 和 CUPS 的 Web 打印服务，支持文件上传、预览、打印设置和任务管理。

<img src="static/zh.jpg" style="width: 100%; max-width: 800px;" alt="打印设置界面">

## 功能特性

### 多品牌兼容
- 使用ipp标准协议和cups标准命令，理论上可兼容大部分支持ipp协议的打印机
- 已在Canon_G3881完成测试，其他打印机请自行验证

### 文件管理
- 支持 PDF、DOC、DOCX、PPT、PPTX、XLS、XLSX、TXT、RTF 以及图片格式（JPG、JPEG、PNG、GIF、BMP、SVG）
- 支持拖拽上传
- 文件在线预览（电脑端PDF，移动端图片）
- 文件列表查看和删除

### 打印设置
- **纸张大小**: 办公A1-A4/照片5-10 寸等
- **纸张材质**: 普通纸/光面照片纸等
- **色彩模式**: 彩色/黑白打印
- **双面打印**: 单面/双面（长边装订）/双面（短边装订）
- **打印方向**: 纵向/横向
- **打印份数**: 支持 1-99 份
- **页面范围**: 支持指定页面范围（如 1-5 8 10-12）
- **打印缩放**: 自动/适应/填充/无缩放
- **页面镜像**: 支持水平翻转

### 任务管理
- 打印机在线状态检测(限ipp打印机)
- 实时任务状态监控（已提交/处理中/已完成/失败/已取消）
- 任务进度显示（基于时间和cups队列估算）
- 任务取消功能
- 打印队列实时查看
- 纸盒信息（IPP 协议）
- 墨盒信息（IPP 协议）
- 打印机信息（运行时间、固件版本、告警等）

### 安全防护
- 路径遍历攻击防护
- 文件类型白名单验证
- 文件大小限制（100MB）
- 日志自动轮换
- 删除文件自动清理预览缓存

### 中英双语切换
- 中文界面 http://localhost:5000/zh
- 英文界面 http://localhost:5000/en

## 技术栈

- **后端**: Python 3.9+ + Flask 3.0+
- **前端**: HTML5 + Tailwind CSS (CDN)
- **打印服务**: CUPS 2.0+
- **文档转换**: LibreOffice 6.0+
- **PDF 处理**: poppler-utils (pdftoppm), pdftk
- **IPP 协议**: ipptool (cups-client)

## 部署指导-容器安装(推荐)
### 1. 部署容器
```bash
# 特权模式为usb打印机需要，如使仅使用网络打印机可以去除usb挂载和特权模式

docker run -d \
  --name cups-web-print \
  --hostname=cups-web-print \
  --restart unless-stopped \
  --privileged \
  -p 5000:5000 \
  -p 631:631 \
  -v /var/run/dbus:/var/run/dbus \
  -v /dev/bus/usb:/dev/bus/usb \
  -v cups-etc:/etc/cups \
  -v cups-spool:/var/spool/cups \
  -v cups-log:/var/log/cups \
  -v cups-uploads:/app/uploads \
  -v cups-previews:/app/previews \
  ghcr.io/wishday/cups-web-print:latest
```

### 2. 添加cups打印机
#### 以网络打印机为例，其他打印机手动进入容器，参考cups官方文档操作
```bash
# 建议打印机固定ip，避免复杂mDNS解析
docker exec cups-web-print lpadmin -p Canon_G3881 -v ipp://192.168.1.16:631/ipp/print -m everywhere -E
```
### 3. 使用 Web 界面
#### 打开浏览器访问 `http://localhost:5000`，局域网内设备访问 `http://cups服务器ip:5000`

## 部署指导-本地安装

### 1. 下载源代码

#### 方式一：从 GitHub 克隆（推荐）
```bash
# 克隆项目到本地
git clone https://github.com/wishday/cups-web-print.git

# 进入项目目录
cd cups-web-print
```

#### 方式二：下载 ZIP 压缩包
```bash
# 下载并解压
wget https://github.com/wishday/cups-web-print/archive/refs/heads/main.zip
unzip main.zip
cd cups-web-print-main
```

### 2. 安装依赖

#### 安装系统依赖
```bash
sudo apt-get update
sudo apt-get install -y cups cups-client \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    poppler-utils pdftk python3-pip
```

#### 安装 Python 依赖
```bash
pip3 install -r requirements.txt
```

### 3. 配置打印机

#### 启动 CUPS 服务
```bash
sudo systemctl start cups
sudo systemctl enable cups
```

#### 添加打印机
```bash
# 添加ipp网络打印机示例(建议打印机固定ip，避免复杂mDNS解析)
sudo lpadmin -p Canon_G3881 -v ipp://192.168.1.16:631/ipp/print -m everywhere -E

# 查看可用打印机
lpstat -p -v

```

### 4. 启动服务
```bash
python3 app.py

#添加开机自启动后台运行(可选)
crontab -e
#添加以下一行(替换实际项目路径)
@reboot nohup python3 /your-path-to/app.py > /dev/null 2>&1 &

```

服务将在 `http://localhost:5000` 启动

### 5. 使用 Web 界面
1. 打开浏览器访问 `http://localhost:5000`，局域网内设备访问 `http://cups服务器ip:5000`
2. 上传文件（点击上传区域或拖拽）
3. 选择打印机
4. 配置打印设置
5. 点击"提交打印"

## 目录结构

```
cups-web-print/
├── app.py                    # Flask 应用主文件
├── ipp_client.py             # 通过 IPP 获取纸盒、墨盒等状态信息
├── printer_checker.py        # 通过 IPP、BJNP 等协议确认打印机在线状态
├── requirements.txt          # Python 依赖
├── README.md                 # 项目文档
├── static/                   # 页面资源文件
│   └── favicon.png
├── uploads/                  # 上传文件目录
├── previews/                 # 预览文件目录
├── templates/                # HTML 模板
│   ├── index.html           # 中文主页
│   └── index_en.html        # 英文主页
```

## 项目地址

- **GitHub**: https://github.com/wishday/cups-web-print

## 故障排查


### 问题：lpadmin添加打印机失败
```bash
# 重启 CUPS 服务再试
sudo systemctl restart cups

# 检查打印机 IP 是否能 ping 通
ping 192.168.1.16

# 检查 IPP 地址是否正确（不同品牌地址不同）
# 佳能：ipp://ip:631/ipp/print
# 惠普：ipp://ip:631/ipp/print
# 爱普生：ipp://ip:631/ipp/printer

# 查看 CUPS 错误日志
cat /var/log/cups/error_log

# 尝试使用驱动less模式（everywhere）
sudo lpadmin -p 打印机名 -v ipp://打印机IP:631/ipp/print -m everywhere -E

# 启用打印机并接受任务
sudo cupsenable 打印机名
sudo cupsaccept 打印机名
```

### 问题：访问5000端口无反应
```bash
# 检查服务是否正常启动
ps -ef | grep app.py

# 检查 5000 端口是否监听
sudo lsof -i:5000
sudo netstat -tulpn | grep 5000

# 防火墙放行端口（Ubuntu/Debian）
sudo ufw allow 5000/tcp

# 检查 Flask 绑定地址是否为 0.0.0.0（必须修改才能局域网访问）
# 确保 app.py 中使用：app.run(host='0.0.0.0', port=5000)
```

### 问题：打开页面列表无可用打印机
```bash
# 检查 CUPS 服务状态
sudo systemctl status cups

# 启动 CUPS 服务
sudo systemctl start cups

# 确保 CUPS 已配置有可用打印机
lpstat -p
```

### 问题：文档转换失败
```bash
# 验证 LibreOffice 是否安装
libreoffice --version

# 重新安装 LibreOffice
sudo apt-get install --reinstall libreoffice-writer libreoffice-calc libreoffice-impress
```

### 问题：PDF 预览无法生成
```bash
# 验证 pdftoppm 是否安装
pdftoppm -h

# 安装 poppler-utils
sudo apt-get install poppler-utils
```

### 问题：页面范围提取失败
```bash
# 验证 pdftk 是否安装
pdftk --version

# 安装 pdftk
sudo apt-get install pdftk
```

### 问题：打印机墨盒/纸盒信息无法获取
```bash
# 验证 ipptool 是否安装
ipptool --version

# 安装 cups-client
sudo apt-get install cups-client

# 测试 IPP 连接
ipptool -t ipp://打印机 IP:631/ipp/print get-printer-attributes.test
```

### 问题：打印任务提交失败，打印提示成功但无输出
- 确保cups打印机已正确配置，本项目打印office文档会转换成pdf，依赖cups将pdf转为打印机支持的光栅化格式，使用lpadmin添加打印机时确保带有-m everywhere参数，确保cups正确识别打印机支持的光栅化格式
- 确定cups的驱动和pdd文件是否正常，可能需要安装打印机厂商cups专属驱动或PDD文件
- 检查打印机是否处于空闲状态：`lpstat -p`
- 查看 CUPS 日志：`/var/log/cups/error_log`
- 检查打印机在线状态


## 许可证

本项目基于 GPLv3 开源许可证。
 
本软件按"原样"提供，作者不对使用后果承担任何责任。
---
---
<span id="english-version"></span>

![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-GPLv3-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

**[🇨🇳 中文版](#中文版)** | **[🇺🇸 English Version](#english-version)**

# Web Print Service

A web-based print service built with Python Flask and CUPS, supporting file upload, preview, print settings, and job management.

<img src="static/en.jpg" style="width: 100%; max-width: 800px;" alt="Print Settings Interface">

## Features

### Multi-Brand Compatibility
- Uses IPP standard protocol and CUPS standard commands, compatible with most printers supporting IPP protocol
- Tested on Canon G3881; please verify for other printers

### File Management
- Supports PDF, DOC, DOCX, PPT, PPTX, XLS, XLSX, TXT, RTF, and image formats (JPG, JPEG, PNG, GIF, BMP, SVG)
- Drag-and-drop upload support
- Online file preview (PDF on desktop, images on mobile)
- File list view and deletion

### Print Settings
- **Paper Size**: Office A1-A4 / Photo 5-10 inches, etc.
- **Paper Type**: Plain paper / Glossy photo paper, etc.
- **Color Mode**: Color / Black & white printing
- **Duplex**: Single-sided / Duplex (long-edge binding) / Duplex (short-edge binding)
- **Orientation**: Portrait / Landscape
- **Copies**: Supports 1-99 copies
- **Page Range**: Supports specified page ranges (e.g., 1-5 8 10-12)
- **Scaling**: Auto / Fit / Fill / None
- **Mirror**: Supports horizontal flip

### Job Management
- Printer online status detection (IPP printers only)
- Real-time job status monitoring (Submitted / Processing / Completed / Failed / Cancelled)
- Job progress display (estimated based on time and CUPS queue)
- Job cancellation function
- Real-time print queue view
- Paper tray information (IPP protocol)
- Ink cartridge information (IPP protocol)
- Printer information (uptime, firmware version, alerts, etc.)

### Security
- Path traversal attack protection
- File type whitelist validation
- File size limit (100MB)
- Automatic log rotation
- Automatic preview cache cleanup on file deletion

### Bilingual Support
- Chinese interface: http://localhost:5000/zh
- English interface: http://localhost:5000/en

## Tech Stack

- **Backend**: Python 3.9+ + Flask 3.0+
- **Frontend**: HTML5 + Tailwind CSS (CDN)
- **Print Service**: CUPS 2.0+
- **Document Conversion**: LibreOffice 6.0+
- **PDF Processing**: poppler-utils (pdftoppm), pdftk
- **IPP Protocol**: ipptool (cups-client)

## Deployment Guide - Container Installation (Recommended)

### 1. Deploy the Container

```bash
# Privileged mode is required for USB printers. If using only network printers, you can remove the USB mount and privileged flag.

docker run -d \
  --name cups-web-print \
  --hostname=cups-web-print \
  --restart unless-stopped \
  --privileged \
  -p 5000:5000 \
  -p 631:631 \
  -v /var/run/dbus:/var/run/dbus \
  -v /dev/bus/usb:/dev/bus/usb \
  -v cups-etc:/etc/cups \
  -v cups-spool:/var/spool/cups \
  -v cups-log:/var/log/cups \
  -v cups-uploads:/app/uploads \
  -v cups-previews:/app/previews \
  ghcr.io/wishday/cups-web-print:latest
```

### 2. Add a CUPS Printer

#### Using a network printer as an example. For other printer types, manually enter the container and refer to the official CUPS documentation.

```bash
# It is recommended to assign a static IP to the printer to avoid complex mDNS resolution.
docker exec cups-web-print lpadmin -p Canon_G3881 -v ipp://192.168.1.16:631/ipp/print -m everywhere -E
```

### 3. Use the Web Interface

#### Open a browser and visit http://localhost:5000. For devices on the local network, visit http://cups-server-ip:5000

## Deployment Guide-Local Installation

### 1. Download Source Code

#### Option A: Clone from GitHub (Recommended)
```bash
# Clone the project locally
git clone https://github.com/wishday/cups-web-print.git

# Navigate to project directory
cd cups-web-print
```

#### Option B: Download ZIP Archive
```bash
# Download and extract
wget https://github.com/wishday/cups-web-print/archive/refs/heads/main.zip
unzip main.zip
cd cups-web-print-main
```

### 2. Install Dependencies

#### Install System Dependencies
```bash
sudo apt-get update
sudo apt-get install -y cups cups-client \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    poppler-utils pdftk python3-pip
```

#### Install Python Dependencies
```bash
pip3 install -r requirements.txt
```

### 3. Configure Printer

#### Start CUPS Service
```bash
sudo systemctl start cups
sudo systemctl enable cups
```

#### Add Printer
```bash
# Example: Add IPP network printer (recommended to use fixed IP for printer to avoid complex mDNS resolution)
sudo lpadmin -p Canon_G3881 -v ipp://192.168.1.16:631/ipp/print -m everywhere -E

# View available printers
lpstat -p -v
```

### 4. Start Service
```bash
python3 app.py

# Add auto-start on boot (optional)
crontab -e
# Add the following line (replace with actual project path)
@reboot nohup python3 /your-path-to/app.py > /dev/null 2>&1 &
```

The service will start on `http://localhost:5000/en`

### 5. Use Web Interface
1. Open browser and visit `http://localhost:5000/en`, or `http://cups-server-ip:5000/en` for LAN devices
2. Upload files (click upload area or drag-and-drop)
3. Select printer
4. Configure print settings
5. Click "Submit Print"

## Directory Structure

```
cups-web-print/
├── app.py                    # Flask application main file
├── ipp_client.py             # Get paper tray, ink cartridge status via IPP
├── printer_checker.py        # Check printer online status via IPP, BJNP protocols
├── requirements.txt          # Python dependencies
├── README.md                 # Project documentation
├── static/                   # Page assets
│   └── favicon.png
├── uploads/                  # Upload directory
├── previews/                 # Preview files directory
├── templates/                # HTML templates
│   ├── index.html           # Chinese homepage
│   └── index_en.html        # English homepage
```

## Project URL

- **GitHub**: https://github.com/wishday/cups-web-print

## Troubleshooting

### Issue: lpadmin add printer failed
```bash
# Restart CUPS service and try again
sudo systemctl restart cups

# Check if printer IP is reachable
ping 192.168.1.16

# Check if IPP address is correct (varies by brand)
# Canon: ipp://ip:631/ipp/print
# HP: ipp://ip:631/ipp/print
# Epson: ipp://ip:631/ipp/printer

# View CUPS error log
cat /var/log/cups/error_log

# Try driverless mode (everywhere)
sudo lpadmin -p printer_name -v ipp://printer_IP:631/ipp/print -m everywhere -E

# Enable printer and accept jobs
sudo cupsenable printer_name
sudo cupsaccept printer_name
```

### Issue: No response when accessing port 5000
```bash
# Check if service is running
ps -ef | grep app.py

# Check if port 5000 is listening
sudo lsof -i:5000
sudo netstat -tulpn | grep 5000

# Allow port through firewall (Ubuntu/Debian)
sudo ufw allow 5000/tcp

# Check Flask binding address (must be 0.0.0.0 for LAN access)
# Ensure app.py uses: app.run(host='0.0.0.0', port=5000)
```

### Issue: No available printers in page list
```bash
# Check CUPS service status
sudo systemctl status cups

# Start CUPS service
sudo systemctl start cups

# Ensure CUPS has configured printers
lpstat -p
```

### Issue: Document conversion failed
```bash
# Verify LibreOffice installation
libreoffice --version

# Reinstall LibreOffice
sudo apt-get install --reinstall libreoffice-writer libreoffice-calc libreoffice-impress
```

### Issue: PDF preview generation failed
```bash
# Verify pdftoppm installation
pdftoppm -h

# Install poppler-utils
sudo apt-get install poppler-utils
```

### Issue: Page range extraction failed
```bash
# Verify pdftk installation
pdftk --version

# Install pdftk
sudo apt-get install pdftk
```

### Issue: Printer ink/paper tray information cannot be retrieved
```bash
# Verify ipptool installation
ipptool --version

# Install cups-client
sudo apt-get install cups-client

# Test IPP connection
ipptool -t ipp://printer_IP:631/ipp/print get-printer-attributes.test
```

### Issue: Print job submission failed, print shows success but no output
- Ensure CUPS printer is properly configured. This project converts Office documents to PDF, relying on CUPS to convert PDF to raster format supported by the printer. When using lpadmin to add printer, ensure the -m everywhere parameter is included to ensure CUPS correctly identifies the printer-supported raster format
- Verify CUPS driver and PPD files are normal; you may need to install printer manufacturer's specific CUPS driver or PPD files
- Check printer idle status: `lpstat -p`
- View CUPS logs: `/var/log/cups/error_log`
- Check printer online status

## License

This project is licensed under the GPLv3 open source license.

This software is provided "as is" without any warranty. The author assumes no responsibility for any consequences arising from its use.

---

