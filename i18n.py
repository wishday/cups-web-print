"""集中式中英文消息目录。

约定：
- 所有面向用户的动态文案都定义在 MESSAGES 中，key 为消息码。
- 任务类消息只保存 code + params，在返回给前端时按查看者语言渲染，
  这样同一个任务在中文页/英文页查看都能显示正确语言。
- 占位符使用 str.format 语法；导入时会自检 zh/en 是否齐全、占位符是否一致。
"""

from collections import namedtuple
from string import Formatter

SUPPORTED_LANGS = ('zh', 'en')
DEFAULT_LANG = 'zh'


MESSAGES = {
    # ---------- 任务状态 ----------
    'job.submitted': {
        'zh': '已提交到打印队列',
        'en': 'Submitted to print queue',
    },
    'job.no_job_id_submitted': {
        'zh': 'CUPS 未返回可识别的任务 ID，请到打印机确认任务是否已提交',
        'en': 'CUPS did not return a recognizable job ID. Please check the printer to confirm whether the job was submitted.',
    },
    'job.no_job_id_tracking': {
        'zh': 'CUPS 未返回可识别的任务 ID，无法跟踪进度',
        'en': 'CUPS did not return a recognizable job ID; progress cannot be tracked.',
    },
    'job.submit_failed': {
        'zh': '打印任务提交失败：{detail}',
        'en': 'Failed to submit print job: {detail}',
    },
    'job.error': {
        'zh': '打印任务处理异常：{detail}',
        'en': 'Print job error: {detail}',
    },
    'job.timeout': {
        'zh': '监控超时（任务已执行{minutes}分钟）',
        'en': 'Monitoring timed out (job has been running for {minutes} min)',
    },
    'job.processing': {
        'zh': '打印中... ({percent}%)',
        'en': 'Printing... ({percent}%)',
    },
    'job.processing_long': {
        'zh': '打印中... 已执行 {minutes} 分钟',
        'en': 'Printing... running for {minutes} min',
    },
    'job.queued': {
        'zh': '排队中（前方 {position} 个任务）',
        'en': 'Queued ({position} job(s) ahead)',
    },
    'job.queued_long': {
        'zh': '排队中（前方 {position} 个任务，已等待 {minutes} 分钟）',
        'en': 'Queued ({position} job(s) ahead, waiting {minutes} min)',
    },
    'job.completed': {
        'zh': '打印完成 (耗时{seconds}秒)',
        'en': 'Printing completed ({seconds}s)',
    },
    'job.sent_unconfirmed': {
        'zh': '打印已发送完成 (耗时{seconds}秒，出纸状态未确认)',
        'en': 'Sent to printer ({seconds}s; paper output not confirmed)',
    },
    'job.cancelled': {
        'zh': '打印任务已被取消，请检查打印机',
        'en': 'Print job was cancelled. Please check the printer.',
    },
    'job.cancelled_reason': {
        'zh': '打印任务已被取消（{reason}），请检查打印机',
        'en': 'Print job was cancelled ({reason}). Please check the printer.',
    },
    'job.failed': {
        'zh': '打印任务已中止，请检查打印机状态',
        'en': 'Print job was aborted. Please check the printer status.',
    },
    'job.failed_reason': {
        'zh': '打印任务已中止（{reason}），请检查打印机状态',
        'en': 'Print job was aborted ({reason}). Please check the printer status.',
    },
    'job.unknown': {
        'zh': '打印状态无法确认，请查看打印机输出',
        'en': 'Print status could not be confirmed. Please check the printer output.',
    },
    'job.unknown_reason': {
        'zh': '打印状态无法确认，请查看打印机输出（CUPS 状态：{reason}）',
        'en': 'Print status could not be confirmed. Please check the printer output (CUPS reason: {reason})',
    },
    'job.manual_cancelled': {
        'zh': '任务已取消 (用户手动取消)',
        'en': 'Job cancelled (manually by user)',
    },
    'job.record_deleted': {
        'zh': '任务记录已删除',
        'en': 'Job record deleted',
    },
    'job.cancel_requested': {
        'zh': '打印任务已取消，5 秒后从列表删除',
        'en': 'Print job cancelled; it will be removed from the list in 5 seconds',
    },
    'job.marked_cancelled': {
        'zh': '任务已标记为取消，5 秒后从列表删除',
        'en': 'Job marked as cancelled; it will be removed from the list in 5 seconds',
    },

    # ---------- PDF / 预览文件处理 ----------
    'error.page_out_of_range': {
        'zh': '页码超出范围：文件共 {total} 页，无法打印第 {requested} 页',
        'en': 'Page out of range: the file has {total} pages; cannot print page {requested}',
    },
    'error.pdftk_missing': {
        'zh': 'pdftk 未安装，无法提取页面',
        'en': 'pdftk is not installed; cannot extract pages',
    },
    'error.pdftk_timeout': {
        'zh': 'pdftk 响应超时',
        'en': 'pdftk timed out',
    },
    'error.pdf_extract_failed': {
        'zh': 'PDF 页面提取失败：{detail}',
        'en': 'Failed to extract PDF pages: {detail}',
    },
    'error.pdf_extract_timeout': {
        'zh': 'PDF 页面提取超时',
        'en': 'PDF page extraction timed out',
    },
    'error.pdf_extract_exception': {
        'zh': 'PDF 页面提取异常：{detail}',
        'en': 'PDF page extraction error: {detail}',
    },
    'error.preview_path_invalid': {
        'zh': '预览文件路径错误：{filename}',
        'en': 'Invalid preview file path: {filename}',
    },
    'error.preview_missing': {
        'zh': '预览文件不存在：{filename}，请重新上传',
        'en': 'Preview file not found: {filename}. Please upload it again.',
    },
    'error.preview_incomplete': {
        'zh': '预览文件不完整：{filename}，请重新上传',
        'en': 'Preview file is incomplete: {filename}. Please upload it again.',
    },
    'error.unknown': {
        'zh': '未知错误',
        'en': 'unknown error',
    },

    # ---------- 上传 ----------
    'error.no_file': {
        'zh': '没有文件',
        'en': 'No file',
    },
    'error.no_file_selected': {
        'zh': '未选择文件',
        'en': 'No file selected',
    },
    'error.unsupported_file_type': {
        'zh': '不支持的文件类型',
        'en': 'Unsupported file type',
    },
    'error.upload_cancelled': {
        'zh': '上传已取消',
        'en': 'Upload cancelled',
    },
    'error.file_save_failed': {
        'zh': '文件保存失败: {detail}',
        'en': 'Failed to save file: {detail}',
    },
    'warning.doc_conversion_failed': {
        'zh': '文档转换失败，预览和打印将不可用，请检查 LibreOffice 是否安装或文档格式是否正确',
        'en': 'Document conversion failed; preview and printing are unavailable. Check whether LibreOffice is installed or the document format is valid.',
    },
    'warning.image_conversion_failed': {
        'zh': '图片转换失败，预览和打印将不可用',
        'en': 'Image conversion failed; preview and printing are unavailable.',
    },
    'warning.pdf_copy_failed': {
        'zh': 'PDF 复制失败，预览和打印将不可用，请联系管理员',
        'en': 'PDF copy failed; preview and printing are unavailable. Please contact the administrator.',
    },
    'warning.pdf_missing_preview': {
        'zh': 'PDF 文件不存在，预览将不可用',
        'en': 'The PDF file does not exist; preview is unavailable.',
    },
    'warning.preview_image_failed': {
        'zh': '预览图片生成失败，可能无法预览（请确认系统已安装 poppler-utils / pdftoppm）',
        'en': 'Failed to generate the preview image; preview may not work (ensure poppler-utils / pdftoppm is installed).',
    },

    # ---------- 文件管理 / 预览 ----------
    'error.invalid_file_path': {
        'zh': '非法文件路径',
        'en': 'Invalid file path',
    },
    'error.file_not_found': {
        'zh': '文件不存在',
        'en': 'File not found',
    },
    'error.file_missing_message': {
        'zh': '文件 {filename} 不存在或已被删除',
        'en': 'File {filename} does not exist or has been deleted.',
    },
    'error.preview_not_found': {
        'zh': '预览文件不存在',
        'en': 'Preview file not found',
    },
    'error.preview_not_found_message': {
        'zh': '文件 {filename} 的预览文件不存在，请重新上传该文件',
        'en': 'The preview file for {filename} does not exist. Please upload the file again.',
    },
    'error.preview_not_found_solution': {
        'zh': '请删除该文件后重新上传，系统将自动生成预览文件',
        'en': 'Delete this file and upload it again; a preview will be generated automatically.',
    },
    'error.cannot_preview': {
        'zh': '无法预览此文件',
        'en': 'This file cannot be previewed',
    },
    'error.preview_failed': {
        'zh': '预览失败: {detail}',
        'en': 'Preview failed: {detail}',
    },
    'error.preview_image_missing': {
        'zh': '预览图片不存在',
        'en': 'Preview image not found',
    },
    'error.file_in_use': {
        'zh': '文件正在打印中，无法删除 (任务状态：{status})',
        'en': 'The file is being printed and cannot be deleted (job status: {status})',
    },

    # ---------- 打印机 ----------
    'error.printer_not_found': {
        'zh': '打印机不存在',
        'en': 'Printer not found',
    },
    'error.printer_not_found_name': {
        'zh': '打印机不存在：{printer}',
        'en': 'Printer not found: {printer}',
    },
    'error.printer_status_failed': {
        'zh': '获取打印机状态失败：{detail}',
        'en': 'Failed to get printer status: {detail}',
    },
    'source.ipptool': {
        'zh': 'ipptool: {uri}',
        'en': 'ipptool: {uri}',
    },
    'source.ipptool_failed': {
        'zh': 'ipptool 查询失败：{detail}',
        'en': 'ipptool query failed: {detail}',
    },
    'source.ipptool_failed_short': {
        'zh': 'ipptool（查询失败）',
        'en': 'ipptool (query failed)',
    },
    'source.ipptool_unavailable': {
        'zh': 'ipptool 不可用',
        'en': 'ipptool unavailable',
    },
    'source.unsupported': {
        'zh': '不支持的打印机类型',
        'en': 'Unsupported printer type',
    },

    # ---------- 打印接口校验 ----------
    'error.invalid_json': {
        'zh': '请求数据必须是 JSON 对象',
        'en': 'Request data must be a JSON object',
    },
    'error.invalid_json_format': {
        'zh': '请求数据格式错误',
        'en': 'Invalid request data format',
    },
    'error.filename_not_string': {
        'zh': 'filename 必须是字符串',
        'en': 'filename must be a string',
    },
    'error.printer_not_string': {
        'zh': 'printer 必须是字符串',
        'en': 'printer must be a string',
    },
    'error.page_range_not_string': {
        'zh': 'page_range 必须是字符串',
        'en': 'page_range must be a string',
    },
    'error.missing_params': {
        'zh': '缺少必要参数',
        'en': 'Missing required parameters',
    },
    'error.invalid_printer_name': {
        'zh': '打印机名称包含非法字符',
        'en': 'Printer name contains invalid characters',
    },
    'error.printer_list_unavailable': {
        'zh': '无法获取打印机列表，请稍后重试',
        'en': 'Unable to retrieve the printer list. Please try again later.',
    },
    'error.invalid_paper_size': {
        'zh': '无效的纸张大小，支持的格式: {sizes}',
        'en': 'Invalid paper size. Supported values: {sizes}',
    },
    'error.invalid_paper_type': {
        'zh': '无效的纸张材质，支持的类型: {types}',
        'en': 'Invalid paper type. Supported values: {types}',
    },
    'error.invalid_copies_range': {
        'zh': '打印份数必须在1-99之间',
        'en': 'Copies must be between 1 and 99',
    },
    'error.invalid_copies_type': {
        'zh': '打印份数必须是数字',
        'en': 'Copies must be a number',
    },
    'error.invalid_color_mode': {
        'zh': '色彩模式无效，必须是 color 或 mono',
        'en': 'Invalid color mode; must be color or mono',
    },
    'error.invalid_duplex': {
        'zh': '双面设置无效',
        'en': 'Invalid duplex setting',
    },
    'error.invalid_orientation': {
        'zh': '打印方向无效，必须是 portrait 或 landscape',
        'en': 'Invalid orientation; must be portrait or landscape',
    },
    'error.invalid_scaling': {
        'zh': '无效的打印缩放，支持的格式：{values}',
        'en': 'Invalid print scaling. Supported values: {values}',
    },
    'error.invalid_page_range': {
        'zh': '页面范围格式无效：请使用空格分隔（如 1-5 8 10-12），页码从 1 开始，且起始页不能大于结束页',
        'en': 'Invalid page range. Use spaces (e.g. 1-5 8 10-12); page numbers start at 1 and the start cannot exceed the end.',
    },
    'error.job_not_found': {
        'zh': '任务不存在',
        'en': 'Job not found',
    },
    'error.cancel_failed': {
        'zh': 'CUPS 取消失败：{detail}',
        'en': 'CUPS cancel failed: {detail}',
    },
    'error.cancel_failed_default_detail': {
        'zh': '任务可能已完成或已被删除',
        'en': 'the job may have already completed or been deleted',
    },
}


# 结构化消息：用于在函数之间传递“消息码 + 参数”，由响应边界统一按语言渲染
Msg = namedtuple('Msg', 'code params')


def msg(code, **params):
    return Msg(code, params)


def normalize_lang(value):
    """把 zh-CN / en-US 等取值归一化为 zh 或 en。"""
    if not value:
        return DEFAULT_LANG
    value = str(value).strip().lower()
    if value.startswith('en'):
        return 'en'
    return DEFAULT_LANG


def get_request_lang():
    """读取当前请求的语言：X-Lang > ?lang > Accept-Language > 默认中文。"""
    try:
        from flask import request, has_request_context
    except ImportError:
        return DEFAULT_LANG
    if not has_request_context():
        return DEFAULT_LANG

    explicit = request.headers.get('X-Lang') or request.args.get('lang')
    if explicit:
        return normalize_lang(explicit)

    accept = request.headers.get('Accept-Language', '')
    # 取第一个语言标签，例如 "en-US,en;q=0.9" -> "en-US"
    first = accept.split(',')[0].strip() if accept else ''
    return normalize_lang(first)


def t(key, lang=None, **params):
    """按语言渲染消息；未知 key 原样返回，避免因漏配导致接口 500。"""
    entry = MESSAGES.get(key)
    if not entry:
        return key
    template = entry.get(normalize_lang(lang), entry[DEFAULT_LANG])
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def _placeholders(template):
    names = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            names.add(field_name)
    return names


def validate_messages():
    """自检：每个 key 必须同时有 zh/en，且占位符一致。"""
    for key, entry in MESSAGES.items():
        missing = set(SUPPORTED_LANGS) - set(entry)
        if missing:
            raise ValueError(f"消息 {key} 缺少语言: {', '.join(sorted(missing))}")
        zh_names = _placeholders(entry['zh'])
        en_names = _placeholders(entry['en'])
        if zh_names != en_names:
            raise ValueError(
                f"消息 {key} 的中英文占位符不一致: zh={sorted(zh_names)} en={sorted(en_names)}"
            )


validate_messages()
