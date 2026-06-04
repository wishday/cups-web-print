#!/usr/bin/env python3
"""
通过IPP协议获取打印机墨盒和纸盒信息
使用 ipptool 命令行工具提取信息
"""

import subprocess
import logging
import re
import tempfile
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# 添加控制台处理器（如果没有）
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# 检查 ipptool 是否可用
def check_ipptool_available():
    """检查 ipptool 命令是否可用"""
    try:
        result = subprocess.run(
            ['which', 'ipptool'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False

IPPTOOL_AVAILABLE = check_ipptool_available()

# ============================================================================
# 优化的属性列表 - 只获取必要的数据（方案 B）
# ============================================================================

# 墨盒相关属性
NEEDED_MARKER_ATTRIBUTES = [
    'marker-names',
    'marker-colors',
    'marker-types',
    'marker-levels',
    'marker-high-levels',
    'marker-low-levels'
]

# 纸盒相关属性
NEEDED_TRAY_ATTRIBUTES = [
    'printer-input-tray',
    'media-ready'
]

# 打印机基本信息属性
NEEDED_INFO_ATTRIBUTES = [
    'printer-info',
    'printer-up-time',
    'printer-firmware-version',
    'printer-make-and-model',
    'printer-state'
]

# 打印机状态属性
NEEDED_STATUS_ATTRIBUTES = [
    'printer-state',           # 与 NEEDED_INFO_ATTRIBUTES 重复，会自动去重
    'printer-state-reasons',
    'printer-alert',
    'printer-alert-description',
    'printer-state-message'
]

# 合并所有需要的属性（自动去重）
ALL_NEEDED_ATTRIBUTES = list(set(
    NEEDED_MARKER_ATTRIBUTES + 
    NEEDED_TRAY_ATTRIBUTES + 
    NEEDED_INFO_ATTRIBUTES + 
    NEEDED_STATUS_ATTRIBUTES
))

# 生成 requested-attributes 字符串
ALL_NEEDED_ATTRIBUTES_STR = ','.join(ALL_NEEDED_ATTRIBUTES)


def get_all_printer_info_with_status(printer_url):
    """
    一次性获取打印机所有信息（墨盒、纸盒、基本信息、状态属性）
    使用自定义测试文件，只获取必要的 17 个属性，减少响应数据量
    
    Args:
        printer_url: 打印机 URL，如 "ipp://192.168.1.100:631/ipp/print"
        
    Returns:
        字典包含所有信息：
        {
            'ink_cartridges': [...],      # 墨盒信息
            'trays': [...],               # 纸盒信息
            'printer_info': {...},        # 打印机基本信息
            'ipp_status': {...},          # IPP 状态属性
            'raw_output': '...',          # 原始输出（用于调试）
            'error': None                 # 错误信息（如果有）
        }
    """
    if not IPPTOOL_AVAILABLE:
        logger.warning("ipptool 不可用，无法获取打印机信息")
        return {
            'ink_cartridges': [],
            'trays': [],
            'printer_info': {},
            'ipp_status': None,
            'raw_output': '',
            'error': 'ipptool not available'
        }
    
    try:
        # 生成自定义测试文件（只请求必要的 17 个属性）
        test_content = f"""{{
    NAME "Get-All-Printer-Info"
    OPERATION Get-Printer-Attributes
    GROUP operation
    ATTR charset attributes-charset utf-8
    ATTR language attributes-natural-language en
    ATTR uri printer-uri {printer_url}
    ATTR keyword requested-attributes {ALL_NEEDED_ATTRIBUTES_STR}
}}
"""
        # 写入临时文件
        fd, test_file = tempfile.mkstemp(suffix='.test')
        try:
            os.write(fd, test_content.encode('utf-8'))
            os.close(fd)
            
            # 执行 ipptool
            cmd = ['ipptool', '-tv', printer_url, test_file]
            logger.debug(f"执行命令：{' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15  # 15 秒超时
            )
            
            if result.returncode != 0:
                logger.error(f"ipptool 执行失败：{result.stderr}")
                return {
                    'ink_cartridges': [],
                    'trays': [],
                    'printer_info': {},
                    'ipp_status': None,
                    'raw_output': '',
                    'error': result.stderr.strip()
                }
            
            output = result.stdout
            logger.debug(f"ipptool 输出长度：{len(output)} 字节")
            
            # 解析各类信息（独立 try-except，部分失败不影响其他）
            try:
                ink_cartridges = _parse_ink_cartridges(output)
            except Exception as e:
                logger.warning(f"解析墨盒信息失败：{e}")
                ink_cartridges = []
            
            try:
                trays = _parse_trays(output)
            except Exception as e:
                logger.warning(f"解析纸盒信息失败：{e}")
                trays = []
            
            try:
                printer_info = _parse_printer_info(output)
            except Exception as e:
                logger.warning(f"解析打印机基本信息失败：{e}")
                printer_info = {}
            
            try:
                ipp_status = _parse_printer_status(output)
            except Exception as e:
                logger.warning(f"解析 IPP 状态失败：{e}")
                ipp_status = None
            
            return {
                'ink_cartridges': ink_cartridges,
                'trays': trays,
                'printer_info': printer_info,
                'ipp_status': ipp_status,
                'raw_output': output,
                'error': None
            }
            
        finally:
            # 清理临时文件
            try:
                os.unlink(test_file)
            except OSError:
                pass
                
    except subprocess.TimeoutExpired:
        logger.error("获取打印机信息超时")
        return {
            'ink_cartridges': [],
            'trays': [],
            'printer_info': {},
            'ipp_status': None,
            'raw_output': '',
            'error': 'timeout'
        }
    except Exception as e:
        logger.error(f"获取打印机信息失败：{e}")
        return {
            'ink_cartridges': [],
            'trays': [],
            'printer_info': {},
            'ipp_status': None,
            'raw_output': '',
            'error': str(e)
        }


def _parse_ink_cartridges(output):
    """
    从 ipptool 输出中解析墨盒信息
    遵循 IPP RFC 3805 标准处理 marker-levels 特殊值

    Args:
        output: ipptool 输出文本

    Returns:
        墨盒信息列表
    """
    marker_names = _parse_ipp_attribute(output, 'marker-names')
    marker_colors = _parse_ipp_attribute(output, 'marker-colors')
    marker_types = _parse_ipp_attribute(output, 'marker-types')
    marker_levels_raw = _parse_ipp_attribute(output, 'marker-levels')

    # 将 marker-levels 转换为整数（IPP 返回的是整数值，但 ipptool 输出为字符串）
    marker_levels = []
    for v in marker_levels_raw:
        try:
            marker_levels.append(int(v))
        except (ValueError, TypeError):
            marker_levels.append(-1)

    ink_cartridges = []
    for i in range(len(marker_names)):
        name = marker_names[i] if i < len(marker_names) else f'墨盒 {i+1}'
        color = marker_colors[i] if i < len(marker_colors) else 'unknown'
        level_type = marker_types[i] if i < len(marker_types) else 'unknown'

        # 获取原始级别值
        raw_level = marker_levels[i] if i < len(marker_levels) else -1

        # 根据 IPP RFC 3805 标准处理特殊值
        # -1: unknown, -2: notInstalled, -3: notApplicable
        if raw_level == -1:
            level_status = 'unknown'
            level_value = None
        elif raw_level == -2:
            level_status = 'not_installed'
            level_value = None
        elif raw_level == -3:
            level_status = 'not_applicable'
            level_value = None
        elif 0 <= raw_level <= 100:
            level_status = 'normal'
            level_value = raw_level
        else:
            # 其他异常负数或超出范围的值，视为未知
            logger.warning(f"墨盒 '{name}' 的级别值异常: {raw_level}")
            level_status = 'unknown'
            level_value = None

        ink_cartridges.append({
            'name': name,
            'color': color,
            'type': level_type,
            'level': level_value,
            'level_status': level_status,
            'raw_level': raw_level
        })

    logger.debug(f"提取到 {len(ink_cartridges)} 个墨盒信息")
    return ink_cartridges


def _parse_trays(output):
    """
    从 ipptool 输出中解析纸盒信息
    
    Args:
        output: ipptool 输出文本
        
    Returns:
        纸盒信息列表
    """
    printer_tray_info = _parse_printer_input_tray(output)
    media_ready_match = re.search(r'media-ready\s*\([^)]+\)\s*=\s*([^\s]+)', output)
    media_ready = media_ready_match.group(1) if media_ready_match else None
    
    # 根据状态码映射中文/英文状态
    status_cn_map = {
        '3': '空',
        '4': '已装载',
        '5': '可用',
        '6': '移除'
    }
    status_en_map = {
        '3': 'Empty',
        '4': 'Loaded',
        '5': 'Available',
        '6': 'Removed'
    }
    
    trays = []
    for i, tray_info in enumerate(printer_tray_info):
        name = tray_info.get('name', f'纸盒 {i+1}')
        tray_type = tray_info.get('type', 'unknown')
        status = tray_info.get('status', 'unknown')
        status_cn = status_cn_map.get(status, '未知')
        status_en = status_en_map.get(status, status)
        
        trays.append({
            'name': name,
            'type': tray_type,
            'status': status,
            'status_cn': status_cn,
            'status_en': status_en,
            'media_ready': media_ready
        })
    
    logger.debug(f"提取到 {len(trays)} 个纸盒信息")
    return trays


def _parse_printer_info(output):
    """
    从 ipptool 输出中解析打印机基本信息
    
    Args:
        output: ipptool 输出文本
        
    Returns:
        字典包含打印机基本信息
    """
    printer_info = {}
    
    # printer-info
    printer_info_match = re.search(r'printer-info\s*\([^)]+\)\s*=\s*([^\n]+)', output)
    if printer_info_match:
        printer_info['printer_info'] = printer_info_match.group(1).strip()
    
    # printer-make-and-model
    make_model_match = re.search(r'printer-make-and-model\s*\([^)]+\)\s*=\s*([^\n]+)', output)
    if make_model_match:
        printer_info['printer_make_and_model'] = make_model_match.group(1).strip()
    
    # printer-up-time (秒转小时)
    uptime_match = re.search(r'printer-up-time\s*\([^)]+\)\s*=\s*(\d+)', output)
    if uptime_match:
        uptime_seconds = int(uptime_match.group(1))
        uptime_hours = round(uptime_seconds / 3600, 2)
        printer_info['printer_up_time_hours'] = uptime_hours
        printer_info['printer_up_time_seconds'] = uptime_seconds
    
    # printer-firmware-version
    firmware_match = re.search(r'printer-firmware-version\s*\([^)]+\)\s*=\s*([^\n]+)', output)
    if firmware_match:
        printer_info['printer_firmware_version'] = firmware_match.group(1).strip()
    
    logger.debug(f"打印机信息：{printer_info}")
    return printer_info


def _parse_ipp_attribute(output, attribute_name):
    """
    从 ipptool 输出中解析 IPP 属性

    Args:
        output: ipptool 输出文本
        attribute_name: 属性名称

    Returns:
        属性值列表
    """
    pattern = rf'{attribute_name}\s*\([^)]+\)\s*=\s*(.+)'
    match = re.search(pattern, output)

    if not match:
        logger.debug(f"未找到属性: {attribute_name}")
        return []

    values_str = match.group(1)

    # 分割值（按逗号）
    values = [v.strip() for v in values_str.split(',')]

    return values

def _parse_printer_input_tray(output):
    """
    从 ipptool 输出中解析 printer-input-tray

    Args:
        output: ipptool 输出文本

    Returns:
        纸盒信息列表
    """
    pattern = r'printer-input-tray\s*\([^)]+\)\s*=\s*(.+)'
    match = re.search(pattern, output)

    if not match:
        logger.debug("未找到 printer-input-tray 属性")
        return []

    values_str = match.group(1)

    # 分割多个纸盒（按 ;, 分隔）
    trays = []
    for tray_str in values_str.split(';,'):
        # 解析键值对
        tray_info = {}
        for kv in tray_str.split(';'):
            if '=' in kv:
                key, value = kv.split('=', 1)
                tray_info[key.strip()] = value.strip()
        trays.append(tray_info)

    return trays


def _parse_printer_status(output):
    """
    从 ipptool 输出中解析打印机 IPP 状态属性
    
    Args:
        output: ipptool 输出文本
        
    Returns:
        字典包含状态信息：
        {
            'printer_state': 'idle',
            'printer_state_reasons': ['none'],
            'printer_alert': None,
            'printer_alert_description': None,
            'printer_state_message': None
        }
    """
    def extract_attr_value(attr_name, output_text):
        """提取属性值，逐行匹配"""
        for line in output_text.split('\n'):
            line = line.strip()
            if line.startswith(attr_name + ' '):
                match = re.search(rf'^{re.escape(attr_name)}\s*\([^)]+\)\s*=\s*(.*)$', line)
                if match:
                    return match.group(1).strip()
        return None
    
    # 提取各个属性
    printer_state_raw = extract_attr_value('printer-state', output)
    printer_state_reasons_raw = extract_attr_value('printer-state-reasons', output)
    printer_alert_raw = extract_attr_value('printer-alert', output)
    printer_alert_description_raw = extract_attr_value('printer-alert-description', output)
    printer_state_message_raw = extract_attr_value('printer-state-message', output)
    
    # 解析 printer-state
    printer_state = None
    if printer_state_raw:
        state_match = re.search(r'enum\s*=\s*(\S+)', printer_state_raw)
        if state_match:
            printer_state = state_match.group(1)
        else:
            printer_state = printer_state_raw
    
    # 解析 printer-state-reasons（转换为列表）
    printer_state_reasons = []
    if printer_state_reasons_raw:
        reasons_match = re.search(r'keyword\)?\s*=\s*(.+)', printer_state_reasons_raw)
        if reasons_match:
            reasons_str = reasons_match.group(1).strip()
            printer_state_reasons = [r.strip() for r in reasons_str.split(',')]
        else:
            printer_state_reasons = [r.strip() for r in printer_state_reasons_raw.split(',')]
    
    # 解析 printer-alert
    printer_alert = None
    if printer_alert_raw:
        alert_match = re.search(r'octetString\)?\s*=\s*(.+)', printer_alert_raw)
        if alert_match:
            printer_alert = alert_match.group(1).strip()
        else:
            printer_alert = printer_alert_raw
    
    # 解析 printer-alert-description
    printer_alert_description = None
    if printer_alert_description_raw:
        desc_match = re.search(r'textWithoutLanguage\)?\s*=\s*(.+)', printer_alert_description_raw)
        if desc_match:
            printer_alert_description = desc_match.group(1).strip()
        else:
            printer_alert_description = printer_alert_description_raw
    
    # 解析 printer-state-message
    printer_state_message = None
    if printer_state_message_raw:
        msg_match = re.search(r'textWithoutLanguage\)?\s*=\s*(.+)', printer_state_message_raw)
        if msg_match:
            printer_state_message = msg_match.group(1).strip()
        else:
            printer_state_message = printer_state_message_raw
    
    return {
        'printer_state': printer_state,
        'printer_state_reasons': printer_state_reasons,
        'printer_alert': printer_alert,
        'printer_alert_description': printer_alert_description,
        'printer_state_message': printer_state_message
    }