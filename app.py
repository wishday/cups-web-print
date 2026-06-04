#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web 打印服务 - 基于 Python Flask + CUPS
支持文档/图片上传、打印设置、队列管理
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import subprocess
import json
import uuid
from datetime import datetime
import threading
import time
import logging
import re
import shutil
import glob

# 导入 img2pdf（图片转 PDF 无损转换，非必需——有 LibreOffice 作为 fallback）
try:
    import img2pdf
    IMG2PDF_AVAILABLE = True
except ImportError:
    IMG2PDF_AVAILABLE = False

# 导入 IPP 客户端
try:
    from ipp_client import IPPTOOL_AVAILABLE
except ImportError:
    IPPTOOL_AVAILABLE = False

# 导入打印机在线检测模块
try:
    from printer_checker import check_printer_online, IPPTOOL_AVAILABLE as CHECKER_IPPTOOL_AVAILABLE
    IPPTOOL_AVAILABLE = IPPTOOL_AVAILABLE or CHECKER_IPPTOOL_AVAILABLE
except ImportError:
    check_printer_online = None

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['PREVIEW_FOLDER'] = os.path.join(os.path.dirname(__file__), 'previews')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB 最大文件
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'txt', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'rtf', 'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg'}

# 确保上传目录和预览目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PREVIEW_FOLDER'], exist_ok=True)

# 导入日志轮换处理器
from logging.handlers import RotatingFileHandler

# 配置日志（使用 RotatingFileHandler 自动轮换）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建轮换处理器：单文件最大 1MB，保留 5 个备份文件
rotating_handler = RotatingFileHandler(
    filename=os.path.join(os.path.dirname(__file__), 'app.log'),
    maxBytes=1*1024*1024,     # 1MB
    backupCount=5,            # 保留 5 个备份
    encoding='utf-8'
)
rotating_handler.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 设置格式
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
rotating_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 添加处理器
logger.addHandler(rotating_handler)
logger.addHandler(console_handler)

# 存储打印任务状态
print_jobs = {}
print_jobs_lock = threading.Lock()  # 添加线程锁保护共享数据

# 上传取消令牌
_upload_tokens = {}
_upload_tokens_lock = threading.Lock()


def _register_upload_file(token, filepath):
    """注册上传文件路径，返回 (是否已取消, 是否应终止)"""
    with _upload_tokens_lock:
        entry = _upload_tokens.get(token)
        if not entry:
            return True  # token 不存在，应终止
        entry['files'].append(filepath)
        if entry.get('cancelled'):
            return True
    return False


def _cleanup_upload(token):
    """清理 token 下所有已注册文件"""
    with _upload_tokens_lock:
        entry = _upload_tokens.pop(token, None)
    if not entry:
        return
    for path in entry.get('files', []):
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"已清理取消上传的残留文件：{path}")
        except Exception as e:
            logger.warning(f"清理残留文件失败：{path}, {e}")

def is_safe_path(base_path, target_path):
    """
    检查目标路径是否在基础路径内，防止路径遍历攻击

    Args:
        base_path: 允许访问的基础目录
        target_path: 目标路径

    Returns:
        bool: 安全返回True，不安全返回False
    """
    # 规范化路径，解析所有符号链接和相对路径
    base_abs = os.path.abspath(base_path)
    target_abs = os.path.abspath(target_path)

    # 检查目标路径是否以基础路径开头
    return target_abs.startswith(base_abs + os.sep) or target_abs == base_abs


def get_printer_uri(printer_name):
    """
    获取打印机URI

    Args:
        printer_name: 打印机名称

    Returns:
        打印机URI字符串，如果失败返回None
    """
    try:
        result = subprocess.run(
            ['lpstat', '-p', printer_name, '-v'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            logger.error(f"获取打印机URI失败: {result.stderr}")
            return None

        printer_uri = None
        for line in result.stdout.split('\n'):
            match = re.search(r'device\s+for\s+' + re.escape(printer_name) + r':\s*(\S+)', line)
            if match:
                printer_uri = match.group(1).strip()
                break

        return printer_uri

    except subprocess.TimeoutExpired:
        logger.error(f"获取打印机URI超时")
        return None
    except Exception as e:
        logger.error(f"获取打印机URI失败: {e}")
        return None




def get_single_printer_status(printer_name, timeout=5):
    """
    获取单台打印机的在线状态（只探测这一台，不探测其他打印机）

    Args:
        printer_name: 打印机名称
        timeout: 超时时间（秒），默认 5 秒

    Returns:
        dict: {
            'name': str,
            'status': str,
            'online_status': str,
            'uri': str or None
        }
    """
    try:
        # 1. 获取打印机 URI
        printer_uri = get_printer_uri(printer_name)
        
        if not printer_uri:
            return {
                'name': printer_name,
                'status': 'unknown',
                'online_status': 'unknown',
                'uri': None
            }
        
        # 2. 获取 CUPS 队列状态
        status = 'idle'
        try:
            result = subprocess.run(
                ['lpstat', '-p', printer_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                line = result.stdout.strip()
                if 'is ready' in line.lower():
                    status = 'ready'
                elif 'is processing' in line.lower():
                    status = 'processing'
                elif 'is stopped' in line.lower():
                    status = 'stopped'
        except Exception as e:
            logger.warning(f"获取打印机 {printer_name} 队列状态失败：{e}")
        
        # 3. 使用协议级探测检查打印机是否真实在线（只探测这一台）
        online_status = 'unknown'
        if check_printer_online:
            try:
                probe_result = check_printer_online(printer_uri, timeout=timeout)
                if probe_result.get('online'):
                    online_status = 'online'
                else:
                    online_status = 'offline'
                    # 如果探测离线，更新状态显示
                    if status == 'idle':
                        status = 'offline'
                logger.debug(f"打印机 {printer_name} 在线检测：{probe_result}")
            except Exception as e:
                logger.warning(f"打印机 {printer_name} 在线检测失败：{e}")
                online_status = 'unknown'
        
        return {
            'name': printer_name,
            'status': status,
            'online_status': online_status,
            'uri': printer_uri
        }
        
    except Exception as e:
        logger.error(f"获取单台打印机状态失败：{printer_name}, 错误：{e}")
        return {
            'name': printer_name,
            'status': 'unknown',
            'online_status': 'unknown',
            'uri': None
        }

def get_safe_path(base_path, filename):
    """
    获取安全的文件路径，防止路径遍历攻击

    Args:
        base_path: 允许访问的基础目录
        filename: 文件名

    Returns:
        str: 安全的文件路径，如果不安全返回None
    """
    # 移除所有路径遍历字符
    filename = os.path.basename(filename)

    # 拼接完整路径
    filepath = os.path.join(base_path, filename)

    # 检查路径安全性
    if is_safe_path(base_path, filepath):
        return filepath
    else:
        logger.warning(f"检测到潜在的路径遍历攻击: {filename}")
        return None


def safe_filename(filename, allowed_extensions):
    """
    自定义安全文件名处理，保留中文等非ASCII字符

    Args:
        filename: 原始文件名
        allowed_extensions: 允许的扩展名集合

    Returns:
        str: 安全的文件名
    """
    # 1. 移除路径部分，只保留文件名
    filename = os.path.basename(filename)

    # 2. 移除空字符串
    if not filename:
        return 'file'

    # 3. 提取并验证扩展名
    name_part, ext = os.path.splitext(filename)
    ext = ext.lower()

    # 如果无扩展名或扩展名不在允许列表中
    if not ext or ext.lstrip('.') not in allowed_extensions:
        return 'file'

    # 4. 清理文件名中的非法字符（保留中文、英文、数字、下划线、连字符、空格、括号等）
    # 移除路径分隔符和控制字符
    illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\x00']
    safe_name = name_part
    for char in illegal_chars:
        safe_name = safe_name.replace(char, '')

    # 移除 '..' 防止路径遍历
    safe_name = safe_name.replace('..', '')

    # 5. 如果文件名为空，使用默认名
    if not safe_name.strip():
        safe_name = 'file'

    # 6. 限制文件名长度（避免文件系统限制）
    if len(safe_name) > 200:
        safe_name = safe_name[:200]

    return f"{safe_name}{ext}"


def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def is_image_file(filename):
    """检查是否为图片文件"""
    image_extensions = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in image_extensions

def is_document_file(filename):
    """检查是否为文档文件（非PDF）"""
    doc_extensions = {'txt', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'rtf'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in doc_extensions



def convert_pdf_to_images(pdf_path, output_dir, dpi=150, pdf_filename=None):
    """
    Convert PDF pages to PNG images using pdftoppm

    Args:
        pdf_path: Input PDF file path
        output_dir: Output directory
        dpi: Resolution in dots per inch (default 150)
        pdf_filename: PDF filename (e.g., "document.pdf")

    Returns:
        List of generated image paths, or empty list if failed
    """
    try:
        # Check if pdftoppm is available
        try:
            subprocess.run(['pdftoppm', '-h'], capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.error("pdftoppm not available (install poppler-utils)")
            return []

        # Generate output filename prefix (same as PDF name without .pdf extension)
        # Use provided filename (keeps timestamp) if available
        if pdf_filename:
            # Remove .pdf extension if present
            if pdf_filename.lower().endswith('.pdf'):
                pdf_name = os.path.splitext(pdf_filename)[0]
            else:
                pdf_name = pdf_filename
        else:
            # Extract from pdf_path
            pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        
        output_prefix = os.path.join(output_dir, pdf_name)

        # Convert PDF to PNG images
        # -png: output format
        # -r: resolution in DPI
        # Output files will be: {prefix}-1.png, {prefix}-2.png, ...
        cmd = ['pdftoppm', '-png', '-r', str(dpi), pdf_path, output_prefix]

        logger.info(f"Converting PDF to images: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            # Find all generated images using glob
            # pdftoppm generates files like: prefix-1.png, prefix-2.png, ...
            image_pattern = f"{output_prefix}-*.png"
            image_files = sorted(glob.glob(image_pattern))

            logger.info(f"Generated {len(image_files)} page images")
            return image_files

        logger.error(f"PDF to image conversion failed: {result.stderr}")
        return []

    except subprocess.TimeoutExpired:
        logger.error("PDF to image conversion timeout")
        return []
    except Exception as e:
        logger.error(f"PDF to image conversion failed: {e}")
        return []



def get_preview_images(pdf_filename):
    """
    Get list of preview images for a PDF file
    
    Args:
        pdf_filename: PDF filename (e.g., "document.pdf")
    
    Returns:
        List of dicts with page number and image path
    """
    try:
        
        # Get the base name without extension
        if pdf_filename.lower().endswith('.pdf'):
            base_name = pdf_filename[:-4]
        else:
            base_name = pdf_filename
        
        # Image files are named: {base_name}-1.png, {base_name}-2.png, ...
        image_pattern = os.path.join(app.config['PREVIEW_FOLDER'], f"{base_name}-*.png")
        image_files = sorted(glob.glob(image_pattern))
        
        # Extract page numbers from filenames
        images = []
        for img_path in image_files:
            img_filename = os.path.basename(img_path)
            # Extract page number from filename like "document-1.png"
            match = img_filename.replace(base_name + '-', '').replace('.png', '')
            try:
                page_num = int(match)
                images.append({
                    'page': page_num,
                    'filename': img_filename
                    # Removed 'path' for security - frontend uses /api/preview/ endpoint
                })
            except ValueError:
                continue
        
        return images
    
    except Exception as e:
        logger.error(f"Failed to get preview images: {e}")
        return []


def convert_to_pdf(input_file, output_dir):
    """
    使用 LibreOffice 将文档转换为 PDF

    Args:
        input_file: 输入文件路径
        output_dir: 输出目录

    Returns:
        转换后的 PDF 文件路径，如果失败返回 None
    """
    try:
        filename = os.path.basename(input_file)
        name, ext = os.path.splitext(filename)

        # 检查 libreoffice 是否可用
        try:
            subprocess.run(['libreoffice', '--version'],
                         capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.error("LibreOffice 未安装或不可用")
            return None

        # 使用 libreoffice 转换
        cmd = [
            'libreoffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', output_dir,
            input_file
        ]

        logger.info(f"开始转换文档：{filename}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        # 检查转换后的 PDF 文件是否存在（LibreOffice 可能返回非零退出码但实际转换成功）
        pdf_filename = f"{name}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)

        if os.path.exists(pdf_path):
            logger.info(f"文档转换成功：{pdf_path}")
            # 注意：图片预览由 api_upload() 统一生成，避免重复调用
            return pdf_path
        else:
            # 转换失败，记录详细错误
            error_msg = result.stderr.strip() if result.stderr else "未知错误"
            logger.error(f"文档转换失败：{error_msg}")
            logger.error(f"PDF 文件不存在：{pdf_path}")
            return None

    except subprocess.TimeoutExpired:
        logger.error("文档转换超时")
        return None
    except Exception as e:
        logger.error(f"文档转换异常：{e}")
        return None

def convert_image_to_pdf(input_file, output_dir):
    """
    将图片转换为 PDF
    - raster 图片（jpg/jpeg/png/gif/bmp）：使用 img2pdf（无损），不可用时降级 LibreOffice
    - SVG：使用 LibreOffice 转换

    Args:
        input_file: 输入图片路径
        output_dir: 输出目录

    Returns:
        转换后的 PDF 文件路径，如果失败返回 None
    """
    filename = os.path.basename(input_file)
    name, ext = os.path.splitext(filename)
    ext_lower = ext.lower()
    pdf_filename = f"{name}.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)

    # SVG：img2pdf 不支持，直接用 LibreOffice
    if ext_lower == '.svg':
        logger.info(f"SVG 文件使用 LibreOffice 转换：{filename}")
        return convert_to_pdf(input_file, output_dir)

    # raster 图片：优先使用 img2pdf（无损）
    if IMG2PDF_AVAILABLE:
        try:
            with open(input_file, 'rb') as f:
                pdf_bytes = img2pdf.convert(f.read())
            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            if os.path.exists(pdf_path):
                logger.info(f"图片转换成功（img2pdf）：{pdf_path}")
                return pdf_path
            logger.error(f"图片转换失败（img2pdf），输出不存在：{pdf_path}")
        except Exception as e:
            logger.warning(f"img2pdf 转换失败（{e}），降级到 LibreOffice")

    # fallback：使用 LibreOffice
    logger.info(f"使用 LibreOffice 转换图片：{filename}")
    return convert_to_pdf(input_file, output_dir)

def get_preview_file(original_filename):
    """
    获取预览文件路径

    Args:
        original_filename: 原始文件名

    Returns:
        预览文件路径（PDF），如果无法预览返回 None

    注意：PDF 复制和文档转换应在 api_upload() 中完成，这里只返回已存在的路径
    """
    # 安全检查：只获取文件名，移除路径部分
    original_filename = os.path.basename(original_filename)

    # 统一逻辑：所有文件类型都返回 previews/目录中对应的 PDF
    # 如果是 PDF，直接返回 previews/目录的 PDF
    if original_filename.lower().endswith('.pdf'):
        pdf_path = get_safe_path(app.config['PREVIEW_FOLDER'], original_filename)
        if pdf_path and os.path.exists(pdf_path):
            return pdf_path
        return None

    # 图片和文档：返回 previews/目录的 {basename}.pdf
    if is_image_file(original_filename) or is_document_file(original_filename):
        pdf_filename = os.path.splitext(original_filename)[0] + '.pdf'
        pdf_path = get_safe_path(app.config['PREVIEW_FOLDER'], pdf_filename)
        if pdf_path and os.path.exists(pdf_path):
            return pdf_path
        return None

    return None



def get_printers():
    """获取可用的 CUPS 打印机列表（带在线状态检测）"""
    try:
        result = subprocess.run(
            ['lpstat', '-p'],
            capture_output=True,
            text=True,
            timeout=5
        )
        printers = []
        if result.returncode == 0:
            lines_output = result.stdout.strip().split('\n')
            for line in lines_output:
                # 检测包含"printer"关键字的行
                if 'printer' in line.lower():
                    # 提取打印机名称
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].lower() == 'printer':
                        printer_name = parts[1]
                        # 提取状态
                        status = 'idle'
                        if 'is ready' in line.lower():
                            status = 'ready'
                        elif 'is processing' in line.lower():
                            status = 'processing'
                        elif 'is stopped' in line.lower():
                            status = 'stopped'

                        # 获取打印机 URI
                        printer_uri = get_printer_uri(printer_name)

                        # 使用协议级探测检查打印机是否真实在线
                        online_status = 'unknown'
                        if printer_uri and check_printer_online:
                            try:
                                probe_result = check_printer_online(printer_uri, timeout=5)
                                if probe_result.get('online'):
                                    online_status = 'online'
                                else:
                                    online_status = 'offline'
                                    # 如果探测离线，更新状态显示
                                    if status == 'idle':
                                        status = 'offline'
                                logger.debug(f"打印机 {printer_name} 在线检测：{probe_result}")
                            except Exception as e:
                                logger.warning(f"打印机 {printer_name} 在线检测失败：{e}")
                                online_status = 'unknown'

                        printers.append({
                            'name': printer_name,
                            'status': status,
                            'uri': printer_uri,
                            'online_status': online_status
                        })

        if not printers:
            logger.warning("未检测到可用打印机")

        return printers
    except Exception as e:
        logger.error(f"获取打印机列表失败：{e}")
        return []

def get_printers_fast():
    """获取可用的 CUPS 打印机列表（快速版本，不进行在线探测）"""
    try:
        result = subprocess.run(
            ['lpstat', '-p'],
            capture_output=True,
            text=True,
            timeout=5
        )
        printers = []
        if result.returncode == 0:
            lines_output = result.stdout.strip().split('\n')
            for line in lines_output:
                # 检测包含"printer"关键字的行
                if 'printer' in line.lower():
                    # 提取打印机名称
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].lower() == 'printer':
                        printer_name = parts[1]
                        # 提取状态
                        status = 'idle'
                        if 'is ready' in line.lower():
                            status = 'ready'
                        elif 'is processing' in line.lower():
                            status = 'processing'
                        elif 'is stopped' in line.lower():
                            status = 'stopped'

                        # 获取打印机 URI
                        printer_uri = get_printer_uri(printer_name)

                        # 快速版本：不进行在线探测，初始状态为 unknown
                        printers.append({
                            'name': printer_name,
                            'status': status,
                            'uri': printer_uri,
                            'online_status': 'unknown'
                        })

        if not printers:
            logger.warning("未检测到可用打印机")

        return printers
    except Exception as e:
        logger.error(f"获取打印机列表失败：{e}")
        return []





def extract_pdf_pages_to_tmp(input_pdf, page_range):
    """
    使用 pdftk 提取 PDF 指定页面到 /tmp 目录（系统重启后自动清除）

    Args:
        input_pdf: 输入 PDF 路径
        page_range: 页面范围，如 "1-5,8,10-12"

    Returns:
        (pdf_path, error_message) 元组
    """
    try:
        # 生成输出文件名到/tmp 目录
        base_name = os.path.splitext(os.path.basename(input_pdf))[0]
        unique_id = uuid.uuid4().hex[:8]
        output_pdf = os.path.join('/tmp', f"print_{base_name}_{unique_id}_pages_{page_range.replace('-', '_').replace(',', '_')}.pdf")

        # 检查 pdftk 是否可用
        try:
            result = subprocess.run(['pdftk', '--version'], capture_output=True, text=True, timeout=5)
            logger.info(f"pdftk 版本：{result.stdout.strip()[:100] if result.stdout else 'available'}")
        except FileNotFoundError:
            logger.error("pdftk 未安装")
            return None, "pdftk 未安装，无法提取页面"
        except subprocess.TimeoutExpired:
            return None, "pdftk 响应超时"

        # 使用 pdftk 提取页面到/tmp
        # pdftk 需要空格分隔的参数，如：pdftk input.pdf cat 2 4 output out.pdf
        # 将 page_range 按空格分割成多个参数
        page_parts = page_range.split()
        cmd = ['pdftk', input_pdf, 'cat'] + page_parts + ['output', output_pdf]
        logger.info(f"提取 PDF 页面到/tmp: {cmd}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0 and os.path.exists(output_pdf):
            logger.info(f"PDF 页面提取成功：{output_pdf}")
            return output_pdf, None

        error_msg = result.stderr.strip() if result.stderr else "未知错误"
        logger.error(f"PDF 页面提取失败：{error_msg}")
        return None, f"PDF 页面提取失败：{error_msg}"

    except subprocess.TimeoutExpired:
        logger.error("PDF 页面提取超时")
        return None, "PDF 页面提取超时"
    except Exception as e:
        logger.error(f"PDF 页面提取异常：{e}")
        return None, f"PDF 页面提取异常：{str(e)}"


def get_printable_file(filepath, filename, page_range=None):
    """
    获取可打印的文件路径
    - PDF 和图片：返回 previews/或 uploads/目录的文件路径
    - Office 文档：返回 previews/目录的预览 PDF（如不存在则返回错误）
    - 如指定页面范围，生成对应页面的临时 PDF 到/tmp 目录（系统重启后自动清除）

    注意：PDF 复制和文档转换应在 api_upload() 中完成，如文件不存在请重新上传

    Args:
        filepath: 原始文件路径
        filename: 文件名
        page_range: 页面范围，如 "1-5,8,10-12"

    Returns:
        (printable_path, error_message, is_temp_file) 元组
        成功返回 (文件路径，None, 是否临时文件)，失败返回 (None, 错误信息，False)
    """
    # PDF 文件 - 使用 previews/目录的 PDF
    if filename.lower().endswith('.pdf'):
        base_name = os.path.splitext(filename)[0]
        pdf_filename = f"{base_name}.pdf"
        preview_pdf_path = get_safe_path(app.config['PREVIEW_FOLDER'], pdf_filename)
        
        # 检查预览 PDF 是否存在
        if not preview_pdf_path or not os.path.exists(preview_pdf_path):
            # 预览 PDF 不存在，返回错误
            return None, f"预览文件不存在：{pdf_filename}，请重新上传", False
        
        if page_range and page_range.strip():
            # 需要提取指定页面到/tmp 目录
            logger.info(f"PDF 文件指定页面范围：{page_range}")
            extracted_pdf, error = extract_pdf_pages_to_tmp(preview_pdf_path, page_range.strip())
            if extracted_pdf:
                return extracted_pdf, None, True  # 临时文件
            else:
                return None, error, False
        
        return preview_pdf_path, None, False

    # 图片文件 - 使用预览 PDF（与文档相同逻辑）
    if is_image_file(filename):
        base_name = os.path.splitext(filename)[0]
        pdf_filename = f"{base_name}.pdf"
        pdf_path = get_safe_path(app.config['PREVIEW_FOLDER'], pdf_filename)

        if pdf_path and os.path.exists(pdf_path):
            logger.info(f"使用图片预览 PDF: {pdf_path}")
            if page_range and page_range.strip():
                logger.info(f"从预览 PDF 提取页面范围：{page_range}")
                extracted_pdf, error = extract_pdf_pages_to_tmp(pdf_path, page_range.strip())
                if extracted_pdf:
                    return extracted_pdf, None, True
                else:
                    return None, error, False
            return pdf_path, None, False
        elif not pdf_path:
            logger.error(f"预览文件路径不安全：{pdf_filename}")
            return None, f"预览文件路径错误：{pdf_filename}", False
        else:
            logger.error(f"预览 PDF 不存在：{pdf_filename}，请重新上传")
            return None, f"预览文件不存在：{pdf_filename}，请重新上传", False

    # Office 文档和其他需要转换的格式 - 使用预览 PDF
    if is_document_file(filename):
        # Use full filename with timestamp
        base_name = os.path.splitext(filename)[0]
        pdf_filename = f"{base_name}.pdf"
        pdf_path = get_safe_path(app.config['PREVIEW_FOLDER'], pdf_filename)

        # 检查预览 PDF 是否已存在
        if pdf_path and os.path.exists(pdf_path):
            logger.info(f"使用已存在的预览 PDF: {pdf_path}")
            if page_range and page_range.strip():
                # 从已有 PDF 提取指定页面到/tmp 目录
                logger.info(f"从预览 PDF 提取页面范围：{page_range}")
                extracted_pdf, error = extract_pdf_pages_to_tmp(pdf_path, page_range.strip())
                if extracted_pdf:
                    return extracted_pdf, None, True  # 临时文件
                else:
                    return None, error, False
            return pdf_path, None, False
        elif not pdf_path:
            # get_safe_path() 返回 None，路径不安全
            logger.error(f"预览文件路径不安全：{pdf_filename}")
            return None, f"预览文件路径错误：{pdf_filename}", False
        else:
            # 预览 PDF 不存在，返回错误（应该在 api_upload() 中已转换）
            logger.error(f"预览 PDF 不存在：{pdf_filename}，请重新上传")
            return None, f"预览文件不存在：{pdf_filename}，请重新上传", False

    # 其他格式 - 尝试直接打印
    logger.warning(f"未知文件类型，尝试直接打印：{filename}")
    return filepath, None, False



def submit_print_job(filepath, printer_name, color_mode='mono', duplex='one-sided', orientation='portrait', paper_size='A4', paper_type='plain', copies=1, page_range=None, mirror=False, print_scaling='fit'):
    """
    提交打印任务到CUPS

    Args:
        filepath: 文件路径
        printer_name: 打印机名称
        color_mode: color/mono
        duplex: one-sided/two-sided-long-edge/two-sided-short-edge
        orientation: portrait/landscape (打印方向)
        paper_size: 纸张大小 (A4, A3, A5, 3.5x5, 4x6, 5x7, 8x10)
        paper_type: 纸张材质 (plain, glossy)
        copies: 打印份数
        page_range: 页面范围，格式如 "1-5,8,10-12"
        mirror: 是否镜像打印
        print_scaling: 打印缩放 (none, fill, fit, auto-fit, auto)
    """
    job_id = str(uuid.uuid4())
    filename = os.path.basename(filepath)
    try:
        # 所有文件类型（文档、图片、PDF）均有对应的预览 PDF
        actual_print_file, conversion_error, _ = get_printable_file(filepath, filename, page_range)
        
        if conversion_error:
            logger.error(f"文件转换失败：{conversion_error}")
            with print_jobs_lock:
                print_jobs[job_id] = {
                    'id': job_id,
                    'filename': filename,
                    'printer': printer_name,
                    'status': 'failed',
                    'message': conversion_error,
                    'timestamp': datetime.now().isoformat(),
                    'progress': 0
                }
            return job_id, False
        
        # 构建lp命令
        cmd = ['lp', '-d', printer_name, '-n', str(copies)]

        # 添加纸张大小设置
        # PWG 5101.1 标准纸张大小映射（多品牌打印机兼容）
        # 参考：https://www.pwg.org/standards.html
        # 格式说明：iso_* = ISO 标准，na_* = 北美标准，jpn_* = 日本标准，om_* = 其他标准
        paper_size_map = {
            # ISO 标准纸张 (A 系列)
            'A4': 'iso_a4_210x297mm',    # A4 (210×297mm)
            'A3': 'iso_a3_297x420mm',    # A3 (297×420mm)
            'A2': 'iso_a2_420x594mm',    # A2 (420×594mm)
            'A1': 'iso_a1_594x841mm',    # A1 (594×841mm)
            'A5': 'iso_a5_148x210mm',    # A5 (148×210mm)
            'A6': 'iso_a6_105x148mm',    # A6 (105×148mm)

            # ISO 标准纸张 (B 系列)
            'B4': 'iso_b4_250x353mm',    # B4 (250×353mm)
            'B5': 'iso_b5_176x250mm',    # B5 (176×250mm)

            # 照片纸尺寸 (英寸)
            '3.5x5': 'na_index-3.5x5_3.5x5in',       # 3.5×5 英寸照片
            '4x6': 'na_index-4x6_4x6in',         # 4×6 英寸照片 (102×152mm)
            '5x7': 'na_5x7_5x7in',               # 5×7 英寸照片 (127×178mm)
            '8x10': 'na_govt-letter_8x10in',     # 8×10 英寸照片 (203×254mm)

        }
        # 获取纸张大小，如果不在映射表中则使用 A4 作为默认值
        cups_paper_size = paper_size_map.get(paper_size, 'iso_a4_210x297mm')
        cmd.extend(['-o', f'media={cups_paper_size}'])


        # 添加纸张材质设置
        # PWG 5101.1 标准介质类型映射（多品牌打印机兼容）
        paper_type_map = {
            # 标准类型 (PWG 5101.1)
            'plain': 'stationery',       # 普通纸
            'paper': 'stationery',       # 普通纸别名
            'normal': 'stationery',      # 普通纸别名
            'photo': 'photographic',     # 照片纸
            'glossy': 'photographic',    # 光面照片纸
            'matte': 'photographic',     # 哑光照片纸
            'envelope': 'envelope',      # 信封
            'transparency': 'transparency',  # 透明胶片
            'labels': 'labels',          # 标签纸
            'cardstock': 'cardstock',    # 卡片纸
            'auto': 'auto',              # 自动选择
        }
        cups_paper_type = paper_type_map.get(paper_type.lower(), 'stationery')
        cmd.extend(['-o', f'media-type={cups_paper_type}'])

        # 添加色彩设置
        if color_mode == 'mono':
            cmd.extend(['-o', 'print-color-mode=monochrome'])
        else:
            cmd.extend(['-o', 'print-color-mode=color'])
            
        # 添加双面打印设置
        if duplex == 'two-sided-long-edge':
            cmd.extend(['-o', 'sides=two-sided-long-edge'])
        elif duplex == 'two-sided-short-edge':
            cmd.extend(['-o', 'sides=two-sided-short-edge'])
        else:
            cmd.extend(['-o', 'sides=one-sided'])

        # 添加打印方向设置（纵向/横向）
        if orientation == 'landscape':
            cmd.extend(['-o', 'orientation-requested=5'])
        else:
            cmd.extend(['-o', 'orientation-requested=3'])

        # 页面范围已在文件处理时处理，不需要再传递给 CUPS
        # 注意：打印机可能不支持 page-ranges 属性，所以我们在文件层面处理
        
        # 添加打印缩放设置
        if print_scaling and print_scaling.strip():
            cmd.extend(['-o', f'print-scaling={print_scaling.strip()}'])

        # 添加镜像打印设置（水平翻转）
        if mirror:
            cmd.extend(['-o', 'mirror-print'])
        
        # 添加文件
        cmd.append(actual_print_file)
        
        # 记录打印命令（用于调试）
        logger.info(f"执行打印命令: {' '.join(cmd)}")
        logger.info(f"打印参数: color_mode={color_mode}, duplex={duplex}, orientation={orientation}, paper_size={paper_size}, paper_type={paper_type}, copies={copies}, page_range={page_range}")

        # 执行打印命令
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # 提取CUPS任务ID
        cups_job_id = None
        if result.returncode == 0:
            # 从输出中提取任务ID，格式通常是 "request id is PDF_Printer-1 (1 file(s))"
            output = result.stdout.strip()
            if 'request id' in output.lower():
                # 提取包含打印机名称和任务ID的部分
                words = output.split()
                for word in words:
                    # 查找格式为 "PrinterName-123" 的词
                    if '-' in word:
                        parts = word.split('-')
                        if len(parts) >= 2:
                            # 检查最后一部分是否为纯数字（任务ID）
                            potential_id = parts[-1]
                            if potential_id.isdigit():
                                cups_job_id = potential_id
                                break


        # 更新任务状态
        with print_jobs_lock:
            print_jobs[job_id] = {
                'id': job_id,
                'cups_job_id': cups_job_id,
                'filename': os.path.basename(filepath),
                'printer': printer_name,
                'color_mode': color_mode,
                'duplex': duplex,
                'orientation': orientation,
                'paper_size': paper_size,
                'paper_type': paper_type,
                'copies': copies,
                'page_range': page_range,
                'print_scaling': print_scaling,
                'mirror': mirror,
                'actual_print_file': actual_print_file,
                'status': 'submitted' if result.returncode == 0 else 'failed',
                'message': result.stdout if result.returncode == 0 else result.stderr,
                'timestamp': datetime.now().isoformat(),
                'progress': 0
            }

        if result.returncode == 0:
            # 启动后台线程监控进度
            logger.info(f"启动监控线程：job_id={job_id}, cups_job_id={cups_job_id}, printer_name={printer_name}")
            monitor_thread = threading.Thread(
                target=monitor_job_progress,
                args=(job_id, cups_job_id, printer_name)
            )
            monitor_thread.daemon = True
            monitor_thread.start()

        return job_id, result.returncode == 0

    except Exception as e:
        with print_jobs_lock:
            print_jobs[job_id] = {
                'id': job_id,
                'filename': os.path.basename(filepath),
                'printer': printer_name,
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.now().isoformat(),
                'progress': 0
            }
        return job_id, False

def monitor_job_progress(job_id, cups_job_id, printer_name):
    """
    监控打印任务进度（根据队列位置）

    每秒检查任务是否在 CUPS 队列中：
    - 不在队列：任务完成
    - 在队列中且为最小 job ID：处于队首，开始处理计时
    - 在队列中但不是最小 job ID：排队等待
    - 最大监控时间：10 分钟
    """
    start_time = time.time()
    processing_start_time = None
    max_monitor_time = 10 * 60

    while True:
        with print_jobs_lock:
            if job_id not in print_jobs:
                logger.debug(f"任务 {job_id} 不存在，停止监控")
                break
            job_status = print_jobs[job_id].get('status')

        if job_status == 'cancelled':
            logger.debug(f"任务 {job_id} 已取消，停止监控")
            break

        if cups_job_id is None:
            logger.warning(f"任务 {job_id} 缺少 CUPS job ID，无法跟踪进度，放弃监控")
            break

        elapsed_time = time.time() - start_time

        if elapsed_time >= max_monitor_time:
            with print_jobs_lock:
                if job_id in print_jobs:
                    print_jobs[job_id]['status'] = 'timeout'
                    print_jobs[job_id]['progress'] = 50
                    print_jobs[job_id]['message'] = f'监控超时（已运行{int(elapsed_time/60)}分钟）'
            logger.warning(f"任务 {job_id} 超时")
            break

        try:
            queue_result = subprocess.run(
                ['lpstat', '-o', printer_name],
                capture_output=True,
                text=True,
                timeout=5
            )

            job_in_queue = (
                queue_result.returncode == 0 and
                any(line.strip().startswith(f"{printer_name}-{cups_job_id} ")
                    for line in queue_result.stdout.split('\n'))
            )

            if job_in_queue:
                # 解析队列中所有 CUPS job ID
                all_ids = []
                for line in queue_result.stdout.split('\n'):
                    m = re.match(rf'{re.escape(printer_name)}-(\d+)\s', line)
                    if m:
                        all_ids.append(int(m.group(1)))

                current_cups_id = int(cups_job_id)
                is_front = all_ids and current_cups_id == min(all_ids)

                if is_front:
                    # 队首：开始或继续处理计时
                    if processing_start_time is None:
                        processing_start_time = time.time()
                    processing_elapsed = time.time() - processing_start_time
                    progress = min(90, int(processing_elapsed))
                    with print_jobs_lock:
                        if job_id in print_jobs:
                            print_jobs[job_id]['status'] = 'processing'
                            print_jobs[job_id]['progress'] = progress
                            print_jobs[job_id]['message'] = f'打印中... ({progress}%)'
                    logger.debug(f"任务 {job_id} 正在打印，进度：{progress}%")
                else:
                    # 排队中：重置处理计时，显示前方任务数
                    processing_start_time = None
                    sorted_ids = sorted(all_ids)
                    position = sorted_ids.index(current_cups_id)
                    with print_jobs_lock:
                        if job_id in print_jobs:
                            print_jobs[job_id]['status'] = 'queued'
                            print_jobs[job_id]['progress'] = 0
                            print_jobs[job_id]['message'] = f'排队中（前方 {position} 个任务）'
                    logger.debug(f"任务 {job_id} 排队中，前方 {position} 个任务")
            else:
                # 任务不在队列中：显示 100% 完成
                if processing_start_time is None:
                    processing_start_time = start_time
                total_time = int(time.time() - processing_start_time)
                with print_jobs_lock:
                    if job_id in print_jobs:
                        print_jobs[job_id]['status'] = 'completed'
                        print_jobs[job_id]['progress'] = 100
                        print_jobs[job_id]['message'] = f'打印完成 (耗时{total_time}秒)'
                logger.info(f"任务 {job_id} 已完成")
                cleanup_temp_file(job_id)
                break

        except Exception as e:
            logger.error(f"监控任务进度失败：{e}")
            time.sleep(10)
        else:
            time.sleep(1)


def cleanup_temp_file(job_id):
    """
    清理打印任务的临时文件

    只清理 /tmp 目录下的临时文件，previews 目录的文件保留
    """
    with print_jobs_lock:
        if job_id not in print_jobs:
            return
        actual_print_file = print_jobs[job_id].get('actual_print_file')
    
    if not actual_print_file:
        return

    # 只清理 /tmp 目录下的临时文件
    if actual_print_file.startswith('/tmp/'):
        try:
            if os.path.exists(actual_print_file):
                os.remove(actual_print_file)
                logger.info(f"已清理临时文件：{actual_print_file}")
        except Exception as e:
            logger.error(f"清理临时文件失败：{e}")


def get_printer_queue(printer_name):
    """获取特定打印机的队列信息"""
    queue = []
    status = "unknown"
    
    try:
        # 获取打印队列
        result = subprocess.run(['lpstat', '-o'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line.strip():
                    # lpstat -o 输出格式: "printer-name-123    username    1024   filename"
                    parts = [part for part in line.split() if part]
                    if len(parts) >= 4:
                        # 第一部分是 printer-jobID
                        job_info = parts[0]
                        # 检查是否属于指定打印机
                        if job_info.startswith(f"{printer_name}-"):
                            queue.append({
                                'job_id': job_info.split('-')[-1],
                                'user': parts[1],
                                'size': parts[2],
                                'filename': ' '.join(parts[3:])
                            })
    except Exception as e:
        logger.error(f"获取打印队列失败: {e}")
    
    try:
        # 获取打印机状态
        printer_status = subprocess.run(
            ['lpstat', '-p', printer_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if printer_status.returncode == 0:
            status_line = printer_status.stdout.strip()
            if "idle" in status_line.lower():
                status = "idle"
            elif "printing" in status_line.lower():
                status = "printing"
            elif "disabled" in status_line.lower():
                status = "disabled"
        else:
            logger.warning(f"获取打印机状态失败: {printer_status.stderr}")
    except Exception as e:
        logger.error(f"获取打印机状态失败: {e}")
    
    # 总是返回队列信息，即使状态获取失败
    return {
        'printer': printer_name,
        'status': status,
        'queue': queue,
        'queue_length': len(queue)
    }

@app.route('/')
@app.route('/zh')
def index():
    """中文主页（默认）"""
    return render_template('index.html',
        max_upload_size=app.config['MAX_CONTENT_LENGTH'],
        allowed_extensions=sorted(app.config['ALLOWED_EXTENSIONS']))

@app.route('/en')
def index_en():
    """English Home Page"""
    return render_template('index_en.html',
        max_upload_size=app.config['MAX_CONTENT_LENGTH'],
        allowed_extensions=sorted(app.config['ALLOWED_EXTENSIONS']))

@app.route('/api/printers', methods=['GET'])
def api_printers():
    """获取可用打印机列表（支持异步探测模式）"""
    # 检查是否启用异步探测模式
    async_probe = request.args.get('async', 'false').lower() == 'true'

    if async_probe:
        # 异步模式：快速返回，不进行在线探测
        printers = get_printers_fast()
    else:
        # 同步模式：完整探测（等待所有打印机在线状态）
        printers = get_printers()

    return jsonify({'printers': printers})


@app.route('/api/printer/<printer_name>/status', methods=['GET'])
def api_printer_status(printer_name):
    """获取单台打印机的在线状态（快速探测）"""
    try:
        # 获取单台打印机信息
        printer = get_single_printer_status(printer_name, timeout=5)
        if not printer:
            return jsonify({'error': '打印机不存在'}), 404
        
        return jsonify({
            'name': printer['name'],
            'status': printer['status'],
            'online_status': printer['online_status'],
            'uri': printer.get('uri')
        })
    except Exception as e:
        logger.error(f"获取打印机 {printer_name} 状态失败：{e}")
        return jsonify({
            'name': printer_name,
            'status': 'unknown',
            'online_status': 'unknown',
            'error': str(e)
        }), 500


@app.route('/api/printer/<printer_name>', methods=['GET'])
def api_printer_detail(printer_name):
    """获取单台打印机详细信息（墨盒、纸盒、队列信息）"""
    printer_data = {
        'name': printer_name,
        'status': 'unknown',
        'uri': None,
        'ink_cartridges': [],
        'trays': [],
        'queue': [],
        'ipp_status': None,
        'source': 'unknown'
    }

    # 获取打印机基本信息
    try:
        result = subprocess.run(
            ['lpstat', '-p', printer_name, '-v'],
            capture_output=True,
            text=True,
            timeout=5
        )

        for line in result.stdout.split('\n'):
            match = re.search(r'device\s+for\s+' + re.escape(printer_name) + r':\s*(\S+)', line)
            if match:
                printer_uri = match.group(1).strip()
                printer_data['uri'] = printer_uri

                # 判断打印机类型
                if printer_uri.startswith('ipp') or printer_uri.startswith('http') or printer_uri.startswith('ipps'):
                    # IPP 网络打印机，使用 ipptool 一次性获取所有信息（方案 B：只获取必要的 17 个属性）
                    printer_data['status'] = 'idle'
                    if IPPTOOL_AVAILABLE:
                        try:
                            from ipp_client import get_all_printer_info_with_status
                            all_info = get_all_printer_info_with_status(printer_uri)
                            printer_data['ink_cartridges'] = all_info.get('ink_cartridges', [])
                            printer_data['trays'] = all_info.get('trays', [])
                            printer_data['printer_info'] = all_info.get('printer_info', {})
                            printer_data['ipp_status'] = all_info.get('ipp_status', {})
                            if all_info.get('error'):
                                printer_data['source'] = f'ipptool 查询失败：{all_info.get("error")}'
                            else:
                                printer_data['source'] = f'ipptool: {printer_uri}'
                        except Exception as e:
                            logger.error(f"通过 ipptool 获取打印机信息失败：{e}")
                            printer_data['source'] = 'ipptool（查询失败）'
                    else:
                        printer_data['source'] = 'ipptool 不可用'
                else:
                    printer_data['status'] = 'idle'
                    printer_data['source'] = '不支持的打印机类型'
                break
    except Exception as e:
        logger.error(f"获取打印机信息失败：{e}")
    
    # 获取打印队列
    queue_info = get_printer_queue(printer_name)
    printer_data['queue'] = queue_info.get('queue', [])
    if queue_info.get('status') != 'unknown':
        printer_data['status'] = queue_info.get('status')
    
    return jsonify(printer_data)

@app.route('/api/upload-cancel/<token>', methods=['DELETE'])
def api_upload_cancel(token):
    """取消上传，标记取消并清理已注册的文件（不 pop token，留给 api_upload 结束清理）"""
    with _upload_tokens_lock:
        entry = _upload_tokens.get(token)
        if not entry:
            return jsonify({'success': True})
        entry['cancelled'] = True
        files = list(entry['files'])
        entry['files'].clear()
    for path in files:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"已清理取消上传的残留文件：{path}")
        except Exception as e:
            logger.warning(f"清理残留文件失败：{path}, {e}")
    return jsonify({'success': True})


@app.route('/api/upload', methods=['POST'])
def api_upload():
    """上传文件"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    
    if file and allowed_file(file.filename):
        token = request.form.get('upload_token', '')
        if token:
            with _upload_tokens_lock:
                _upload_tokens[token] = {'cancelled': False, 'files': []}

        try:
            # 获取文件名和扩展名（使用自定义 safe_filename 保留中文等非ASCII字符）
            original_filename = file.filename
            filename = safe_filename(original_filename, app.config['ALLOWED_EXTENSIONS'])

            # 添加时间戳避免文件名冲突
            name, ext = os.path.splitext(filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{name}_{timestamp}{ext}"
            
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            if token and _register_upload_file(token, filepath):
                _cleanup_upload(token)
                return jsonify({'error': '上传已取消'}), 499
            
            # All file types: trigger conversion to PDF and generate preview images
            if is_document_file(filename) or ext.lower().endswith('.pdf') or is_image_file(filename):
                # Get base name for matching (remove original extension, keep timestamp)
                base_name = os.path.splitext(filename)[0]
                pdf_filename = f"{base_name}.pdf"

                conversion_warning = None

                # For Office documents, convert using LibreOffice
                if is_document_file(filename):
                    pdf_path = convert_to_pdf(filepath, app.config['PREVIEW_FOLDER'])
                    if not pdf_path:
                        logger.error(f"上传时文档转换失败：{filename} - LibreOffice 转换未生成 PDF 文件")
                        logger.error(f"原始文件路径：{filepath}")
                        logger.error(f"预期 PDF 路径：{os.path.join(app.config['PREVIEW_FOLDER'], pdf_filename)}")
                        conversion_warning = "文档转换失败，预览和打印将不可用，请检查 LibreOffice 是否安装或文档格式是否正确"
                    else:
                        if token and _register_upload_file(token, pdf_path):
                            _cleanup_upload(token)
                            return jsonify({'error': '上传已取消'}), 499
                        logger.info(f"文档转换成功，生成预览图片：{pdf_path}")
                        convert_pdf_to_images(pdf_path, app.config['PREVIEW_FOLDER'], pdf_filename=pdf_filename)

                # For images, convert using img2pdf
                elif is_image_file(filename):
                    pdf_path = convert_image_to_pdf(filepath, app.config['PREVIEW_FOLDER'])
                    if not pdf_path:
                        logger.error(f"上传时图片转换失败：{filename}")
                        conversion_warning = "图片转换失败，预览和打印将不可用"
                    else:
                        if token and _register_upload_file(token, pdf_path):
                            _cleanup_upload(token)
                            return jsonify({'error': '上传已取消'}), 499
                        logger.info(f"图片转换成功，生成预览图片：{pdf_path}")
                        convert_pdf_to_images(pdf_path, app.config['PREVIEW_FOLDER'], pdf_filename=pdf_filename)

                # For PDFs, copy to previews and generate images
                elif ext.lower().endswith('.pdf'):
                    pdf_path = os.path.join(app.config['PREVIEW_FOLDER'], pdf_filename)
                    if not os.path.exists(pdf_path):
                        try:
                            shutil.copy2(filepath, pdf_path)
                            if token and _register_upload_file(token, pdf_path):
                                _cleanup_upload(token)
                                return jsonify({'error': '上传已取消'}), 499
                            logger.info(f"PDF 复制成功：{pdf_path}")
                        except Exception as copy_error:
                            logger.error(f"PDF 复制失败：{copy_error}")
                            conversion_warning = "PDF 复制失败，预览和打印将不可用，请联系管理员"

                    if os.path.exists(pdf_path):
                        logger.info(f"PDF 文件，生成预览图片：{pdf_path}")
                        convert_pdf_to_images(pdf_path, app.config['PREVIEW_FOLDER'], pdf_filename=pdf_filename)
                    else:
                        logger.warning(f"PDF 文件不存在：{pdf_filename}")
                        if not conversion_warning:
                            conversion_warning = "PDF 文件不存在，预览将不可用"

                # Get preview images (only if no conversion warning)
                preview_images = []
                if not conversion_warning:
                    preview_images = get_preview_images(pdf_filename)
            
            response_data = {
                'success': True,
                'filename': filename,
                'filepath': filepath
            }
            if preview_images:
                response_data['preview_images'] = preview_images
                response_data['preview_images_count'] = len(preview_images)
            
            # Add warning if conversion failed
            if conversion_warning:
                response_data['warning'] = conversion_warning

            # 成功，清除 token
            if token:
                with _upload_tokens_lock:
                    _upload_tokens.pop(token, None)

            return jsonify(response_data)
        except Exception as e:
            if token:
                _cleanup_upload(token)
            return jsonify({'error': f'文件保存失败: {str(e)}'}), 500
    
    return jsonify({'error': '不支持的文件类型'}), 400

@app.route('/api/preview/<path:filename>', methods=['GET'])
def api_preview(filename):
    """获取文件预览"""
    try:
        # 安全检查：移除路径遍历字符
        filename = os.path.basename(filename)

        # 检查是否是预览图片（格式：{base_name}-{page}.png）
        # 预览图片保存在 previews/ 目录
        # 判断规则：文件名中包含 -数字.png 格式
        if re.search(r'-\d+\.png$', filename, re.IGNORECASE):
            # 预览图片在 previews/ 目录中
            image_path = get_safe_path(app.config['PREVIEW_FOLDER'], filename)
            if image_path and os.path.exists(image_path):
                ext = filename.rsplit('.', 1)[1].lower()
                mime_types = {
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg',
                    'png': 'image/png',
                    'gif': 'image/gif',
                    'bmp': 'image/bmp',
                    'svg': 'image/svg+xml'
                }
                return send_from_directory(
                    app.config['PREVIEW_FOLDER'],
                    filename,
                    mimetype=mime_types.get(ext, 'application/octet-stream')
                )
            else:
                logger.warning(f"预览图片不存在：{filename}, 路径：{image_path}")
                return jsonify({'error': '预览图片不存在'}), 404
        
        # 对于 PDF 和文档文件，使用 get_preview_file 获取预览 PDF
        preview_file = get_preview_file(filename)
        
        if not preview_file:
            # 无法获取预览文件 - 可能是文件不存在或转换失败
            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
            convertible_extensions = ['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'rtf', 'txt',
                                       'jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg']
            
            if ext in convertible_extensions:
                # 检查是否是文件不存在
                upload_path = get_safe_path(app.config['UPLOAD_FOLDER'], filename)
                if not upload_path or not os.path.exists(upload_path):
                    return jsonify({
                        'error': '文件不存在',
                        'message': f'文件 {filename} 不存在或已被删除'
                    }), 404
                else:
                    # 文件存在但预览不可用 - 预览文件不存在，需要重新上传
                    return jsonify({
                        'error': '预览文件不存在',
                        'message': f'文件 {filename} 的预览文件不存在，请重新上传该文件',
                        'solution': '请删除该文件后重新上传，系统将自动生成预览文件'
                    }), 500
            else:
                return jsonify({'error': '无法预览此文件'}), 404
        if os.path.exists(preview_file):
            # 获取文件所在的目录
            preview_dir = os.path.dirname(preview_file)
            preview_filename = os.path.basename(preview_file)
            
            # 根据文件类型设置Content-Type
            if preview_file.lower().endswith('.pdf'):
                # 手动创建响应，确保inline显示
                response = send_from_directory(
                    preview_dir, 
                    preview_filename, 
                    mimetype='application/pdf'
                )
                # 强制设置Content-Disposition为inline，移除filename参数
                response.headers['Content-Disposition'] = 'inline'
                return response
            else:
                # 图片文件
                ext = preview_file.rsplit('.', 1)[1].lower()
                mime_types = {
                    'jpg': 'image/jpeg',
                    'jpeg': 'image/jpeg',
                    'png': 'image/png',
                    'gif': 'image/gif',
                    'bmp': 'image/bmp',
                    'svg': 'image/svg+xml'
                }
                return send_from_directory(
                    preview_dir, 
                    preview_filename, 
                    mimetype=mime_types.get(ext, 'application/octet-stream')
                )
        else:
            return jsonify({'error': '预览文件不存在'}), 404
    except Exception as e:
        logger.error(f"获取预览失败: {e}")
        return jsonify({'error': f'预览失败: {str(e)}'}), 500

@app.route('/api/files', methods=['GET'])
def api_list_files():
    """获取已上传的文件列表"""
    try:
        files = []
        upload_folder = app.config['UPLOAD_FOLDER']

        if os.path.exists(upload_folder):
            for filename in os.listdir(upload_folder):
                filepath = os.path.join(upload_folder, filename)
                if os.path.isfile(filepath):
                    # 获取文件信息
                    stat = os.stat(filepath)
                    # 内联文件类型判断
                    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    if ext in ['pdf']:
                        file_type = 'pdf'  # lowercase for frontend comparison
                    elif ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'svg']:
                        file_type = 'image'  # lowercase for frontend comparison
                    elif ext in ['txt', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'rtf']:
                        file_type = 'document'  # lowercase for frontend comparison
                    else:
                        file_type = 'other'  # lowercase for frontend comparison
                    # Get preview images for document, image and PDF files
                    preview_images = []
                    if file_type == 'document' or file_type == 'image' or file_type == 'pdf':
                        # Use full filename with timestamp
                        pdf_filename = os.path.splitext(filename)[0] + '.pdf'
                        preview_images = get_preview_images(pdf_filename)
                    
                    file_info = {
                        'filename': filename,
                        'filepath': filepath,
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                        'type': file_type
                    }
                    if preview_images:
                        file_info['preview_images'] = preview_images
                        file_info['preview_images_count'] = len(preview_images)
                    files.append(file_info)

        # 按修改时间倒序排列（最新的在前）
        files.sort(key=lambda x: x['mtime'], reverse=True)

        return jsonify({'success': True, 'files': files})
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/files/<path:filename>', methods=['DELETE'])
def api_delete_file(filename):
    """删除上传的文件"""
    # 获取安全的文件路径
    filepath = get_safe_path(app.config['UPLOAD_FOLDER'], filename)
    
    if not filepath:
        logger.warning(f"非法文件路径访问尝试: {filename}")
        return jsonify({'error': '非法文件路径'}), 403
    
    # 检查是否有正在进行的打印任务
    with print_jobs_lock:
        for job_id, job in print_jobs.items():
            if job['filename'] == filename:
                if job['status'] in ['submitted', 'processing']:
                    logger.warning(f"文件 {filename} 正在打印中，无法删除 (任务状态：{job['status']})")
                    return jsonify({
                        'error': f'文件正在打印中，无法删除 (任务状态：{job["status"]})'
                    }), 400
    
    if os.path.exists(filepath):
        try:
            # 删除原始文件
            os.remove(filepath)
            
            # 同时删除对应的预览文件（如果存在）
            # 对于文档文件和 PDF 文件，预览文件会保存在 PREVIEW_FOLDER
            name, ext = os.path.splitext(filename)
            # 检查是否需要删除预览文件（文档、图片或 PDF）
            is_document = is_document_file(filename)
            is_image = is_image_file(filename)
            is_pdf = ext.lower().endswith('.pdf')
            if is_document or is_image or is_pdf:
                # 预览文件是转换后的 PDF
                # Use consistent naming with api_print()
                base_name = os.path.splitext(filename)[0]
                preview_pdf_filename = f"{base_name}.pdf"
                preview_pdf = get_safe_path(app.config['PREVIEW_FOLDER'], preview_pdf_filename)
                if preview_pdf and os.path.exists(preview_pdf):
                    try:
                        os.remove(preview_pdf)
                        logger.info(f"已删除预览文件：{preview_pdf}")
                    except Exception as e:
                        logger.warning(f"删除预览文件失败：{e}")

            # Delete preview images (generated by pdftoppm)
            # Images are named: {filename}-1.png, {filename}-2.png, ...
            image_base_name = os.path.splitext(filename)[0]  # Keep timestamp
            # Use glob.escape to handle special characters in filename
            image_pattern = os.path.join(app.config['PREVIEW_FOLDER'], f"{glob.escape(image_base_name)}-*.png")
            image_files = glob.glob(image_pattern)
            for img_file in image_files:
                try:
                    os.remove(img_file)
                    logger.info(f"已删除预览图片：{img_file}")
                except Exception as e:
                    logger.warning(f"删除预览图片失败：{e}")
            
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': '文件不存在'}), 404

def validate_page_range(page_range):
    """验证页面范围格式"""
    # 允许的格式：1, 1-5, 1-5 8, 1-5 8 10-12（空格分隔，不支持逗号）
    # pdftk 语法要求：空格分隔多个页面范围，如 "1-5 8 10-12"
    if ',' in page_range:
        return False
    pattern = r'^(\d+(-\d+)?)(\s+\d+(-\d+)?)*$'
    return bool(re.match(pattern, page_range))

@app.route('/api/print', methods=['POST'])
def api_print():
    """提交打印任务"""
    logger.info("=" * 80)
    logger.info("接收到打印请求")

    # 记录原始数据
    logger.info(f"原始数据: {request.data}")

    try:
        data = request.json
        logger.info(f"解析后的JSON: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception as e:
        logger.error(f"JSON解析失败: {e}")
        return jsonify({'error': '请求数据格式错误'}), 400

    filepath = data.get('filepath')
    printer_name = data.get('printer')
    color_mode = data.get('color_mode', 'mono')  # 默认改为mono（黑白）
    duplex = data.get('duplex', 'one-sided')
    orientation = data.get('orientation', 'portrait')
    paper_size = data.get('paper_size', 'A4')
    paper_type = data.get('paper_type', 'plain')
    copies = data.get('copies', 1)  # Default to int, not string
    page_range = data.get('page_range', None)
    
    # 空字符串视为 None（无页面范围限制）
    if page_range is not None and not page_range.strip():
        page_range = None
    
    mirror = data.get('mirror', False)
    print_scaling = data.get('print_scaling', 'fit')

    # 记录解析后的参数
    logger.info(f"解析后的参数:")
    logger.info(f"  filepath: {filepath}")
    logger.info(f"  printer_name: {printer_name}")
    logger.info(f"  color_mode: {color_mode}")
    logger.info(f"  duplex: {duplex}")
    logger.info(f"  orientation: {orientation}")
    logger.info(f"  paper_size: {paper_size}")
    logger.info(f"  paper_type: {paper_type}")
    logger.info(f"  copies: {copies}")
    logger.info(f"  page_range: {page_range}")
    logger.info(f"  mirror: {mirror}")
    logger.info(f"  print_scaling: {print_scaling}")

    # 基本参数验证
    if not filepath or not printer_name:
        return jsonify({'error': '缺少必要参数'}), 400

    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404
    
    # 注意：预览文件检查在 get_printable_file() 中进行，避免重复检查
    # 验证纸张大小
    valid_paper_sizes = ['A4', 'A3', 'A2', 'A1', 'A5', 'A6', 'B4', 'B5', '3.5x5', '4x6', '5x7', '8x10']
    if paper_size not in valid_paper_sizes:
        return jsonify({'error': f'无效的纸张大小，支持的格式: {", ".join(valid_paper_sizes)}'}), 400

    # 验证纸张材质
    valid_paper_types = ['plain', 'glossy']
    if paper_type not in valid_paper_types:
        return jsonify({'error': f'无效的纸张材质，支持的类型: {", ".join(valid_paper_types)}'}), 400

    # 验证打印份数
    try:
        copies = int(copies)
        if copies < 1 or copies > 99:
            return jsonify({'error': '打印份数必须在1-99之间'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': '打印份数必须是数字'}), 400

    # 验证色彩模式
    if color_mode not in ['color', 'mono']:
        return jsonify({'error': '色彩模式无效，必须是 color 或 mono'}), 400

    # 验证双面设置
    if duplex not in ['one-sided', 'two-sided-long-edge', 'two-sided-short-edge']:
        return jsonify({'error': '双面设置无效'}), 400

    # 验证打印方向
    if orientation not in ['portrait', 'landscape']:
        return jsonify({'error': '打印方向无效，必须是 portrait 或 landscape'}), 400

    # 验证打印缩放设置
    valid_print_scalings = ['none', 'fill', 'fit', 'auto-fit', 'auto']
    if print_scaling not in valid_print_scalings:
        return jsonify({'error': f'无效的打印缩放，支持的格式：{", ".join(valid_print_scalings)}'}), 400

    # 验证页面范围格式（可选）
    if page_range and page_range.strip():
        if not validate_page_range(page_range.strip()):
            return jsonify({'error': '页面范围格式无效，请使用空格分隔（如：1-5 8 10-12）'}), 400
        page_range = page_range.strip()

    job_id, success = submit_print_job(filepath, printer_name, color_mode, duplex, orientation, paper_size, paper_type, copies, page_range, mirror, print_scaling)

    if success:
        with print_jobs_lock:
            job_data = print_jobs[job_id].copy()
        return jsonify({
            'success': True,
            'job_id': job_id,
            'job': job_data
        })
    else:
        with print_jobs_lock:
            error_message = print_jobs[job_id]['message']
        return jsonify({
            'success': False,
            'error': error_message
        }), 500

@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def api_cancel_job(job_id):
    """取消打印任务或删除已完成/失败的任务"""
    # 检查任务是否存在（加锁读取）
    with print_jobs_lock:
        if job_id not in print_jobs:
            return jsonify({'error': '任务不存在'}), 404
        job = print_jobs[job_id].copy()

    # 检查任务状态
    if job['status'] in ['completed', 'failed', 'cancelled']:
        # 已完成、失败或已取消的任务，先清理临时文件，再删除
        cleanup_temp_file(job_id)
        with print_jobs_lock:
            if job_id in print_jobs:
                del print_jobs[job_id]
                logger.info(f"任务 {job_id} 已删除（状态：{job['status']}）")
        return jsonify({
            'success': True,
            'message': '任务记录已删除'
        })

    # 检查任务是否已经结束（错误状态）
    if job['status'] == 'error':
        return jsonify({'error': f'任务处于错误状态，无法取消'}), 400

    # 保存当前进度
    current_progress = job.get('progress', 0)

    def remove_job_after_delay(job_id, delay_seconds=5):
        """延时删除任务，先清理临时文件"""
        time.sleep(delay_seconds)
        # 删除前先清理临时文件
        cleanup_temp_file(job_id)
        with print_jobs_lock:
            if job_id in print_jobs:
                del print_jobs[job_id]
                logger.info(f"任务 {job_id} 已从列表中删除")

    # 尝试取消 CUPS 任务
    if job.get('cups_job_id'):
        try:
            result = subprocess.run(
                ['cancel', job['cups_job_id']],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                with print_jobs_lock:
                    if job_id in print_jobs:
                        print_jobs[job_id]['status'] = 'cancelled'
                        print_jobs[job_id]['progress'] = current_progress
                        print_jobs[job_id]['message'] = f'任务已取消 (用户手动取消)'
                # 清理临时文件
                cleanup_temp_file(job_id)
                # 启动后台线程，5 秒后删除任务
                remove_thread = threading.Thread(target=remove_job_after_delay, args=(job_id, 5))
                remove_thread.daemon = True
                remove_thread.start()
                return jsonify({
                    'success': True,
                    'message': '打印任务已取消，5 秒后从列表删除'
                })
            else:
                # CUPS 取消失败，但本地标记为已取消
                logger.warning(f"CUPS 取消任务失败：{result.stderr}")
                with print_jobs_lock:
                    if job_id in print_jobs:
                        print_jobs[job_id]['status'] = 'cancelled'
                        print_jobs[job_id]['progress'] = current_progress
                        print_jobs[job_id]['message'] = f'任务已取消 (CUPS 取消失败，但本地已标记为取消)'
                # 清理临时文件
                cleanup_temp_file(job_id)
                # 启动后台线程，5 秒后删除任务
                remove_thread = threading.Thread(target=remove_job_after_delay, args=(job_id, 5))
                remove_thread.daemon = True
                remove_thread.start()
                return jsonify({
                    'success': True,
                    'message': '任务已标记为取消（CUPS 可能已完成），5 秒后从列表删除'
                })
        except Exception as e:
            logger.error(f"取消任务异常：{e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    else:
        # 如果没有 cups_job_id，直接标记为取消
        with print_jobs_lock:
            if job_id in print_jobs:
                print_jobs[job_id]['status'] = 'cancelled'
                print_jobs[job_id]['progress'] = current_progress
                print_jobs[job_id]['message'] = f'任务已取消 (用户手动取消)'
        # 启动后台线程，5 秒后删除任务
        remove_thread = threading.Thread(target=remove_job_after_delay, args=(job_id, 5))
        remove_thread.daemon = True
        remove_thread.start()
        return jsonify({
            'success': True,
            'message': '任务已标记为取消，5 秒后从列表删除'
        })

@app.route('/api/jobs', methods=['GET'])
def api_all_jobs():
    """获取所有任务"""
    with print_jobs_lock:
        jobs = list(print_jobs.values())
    return jsonify({'jobs': jobs})

@app.route('/api/printer-queue/<printer_name>', methods=['GET'])
def api_printer_queue(printer_name):
    """获取特定打印机的队列信息"""
    queue_info = get_printer_queue(printer_name)
    return jsonify(queue_info)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """访问上传的文件"""
    # 防止路径遍历攻击
    safe_filename = secure_filename(filename)
    if safe_filename != filename:
        return jsonify({'error': '无效的文件名'}), 400
    return send_from_directory(app.config['UPLOAD_FOLDER'], safe_filename)

if __name__ == '__main__':
    print("=" * 60)
    print("Web 打印服务启动中...")
    print("=" * 60)
    print(f"服务地址：http://localhost:5000")
    print(f"上传目录：{os.path.abspath(app.config['UPLOAD_FOLDER'])}")
    print("=" * 60)
    print("提示：打印机状态由前端异步获取，无需等待")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
